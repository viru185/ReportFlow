"""Launcher orchestration tests using a fake worker (no Excel)."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

from aiosmtpd.controller import Controller

from reportflow.core.config.models import (
    AppConfig,
    AppSettings,
    JobConfig,
    Recipients,
    SmtpConfig,
    TestSettings,
)
from reportflow.core.ipc.contract import RunStatus
from reportflow.core.state import RunStore, RunTrigger
from reportflow.service.launcher import (
    Launcher,
    default_worker_command,
    resolve_output_paths,
)

FAKE = str(Path(__file__).parent / "fake_worker.py")


def _job(tmp_path: Path, **over) -> JobConfig:
    base = dict(
        name="daily",
        input_excel_path=tmp_path / "t.xlsx",
        output_dir=tmp_path / "out",
        output_name="{run_id}",
        sheet_names=["Summary", "Detail"],
        subject="Daily",
        prod=Recipients(to=["boss@corp.example.com"]),
        test=Recipients(to=["dev@corp.example.com"]),
    )
    base.update(over)
    return JobConfig(**base)


def _config(job: JobConfig, *, smtp_port: int = 25, timeout: int = 30) -> AppConfig:
    return AppConfig(
        app=AppSettings(max_global_concurrency=2, default_timeout_seconds=timeout),
        smtp=SmtpConfig(host="127.0.0.1", port=smtp_port, use_starttls=False, username=""),
        test=TestSettings(recipients=["dev@corp.example.com"]),
        jobs=[job],
    )


def _launcher(tmp_path, config) -> Launcher:
    store = RunStore(tmp_path / "runs.db")
    return Launcher(store, lambda: config, worker_command=[sys.executable, FAKE])


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Capture:
    def __init__(self):
        self.envelopes = []

    async def handle_DATA(self, server, session, envelope):
        self.envelopes.append(list(envelope.rcpt_tos))
        return "250 OK"


def _freeze(monkeypatch, service_exe):
    """Simulate a frozen service exe at the given path."""
    import sys as _sys

    monkeypatch.setattr(_sys, "frozen", True, raising=False)
    monkeypatch.setattr(_sys, "executable", str(service_exe))
    monkeypatch.delenv("REPORTFLOW_WORKER_CMD", raising=False)


def test_frozen_worker_resolves_installer_layout(tmp_path, monkeypatch):
    # {app}\service\reportflow-service.exe + {app}\worker\reportflow-worker.exe (siblings)
    (tmp_path / "service").mkdir()
    (tmp_path / "worker").mkdir()
    service_exe = tmp_path / "service" / "reportflow-service.exe"
    service_exe.write_bytes(b"x")
    worker_exe = tmp_path / "worker" / "reportflow-worker.exe"
    worker_exe.write_bytes(b"x")

    _freeze(monkeypatch, service_exe)
    assert default_worker_command() == [str(worker_exe)]


def test_frozen_worker_resolves_beside_service(tmp_path, monkeypatch):
    service_exe = tmp_path / "reportflow-service.exe"
    service_exe.write_bytes(b"x")
    worker_exe = tmp_path / "reportflow-worker.exe"
    worker_exe.write_bytes(b"x")

    _freeze(monkeypatch, service_exe)
    assert default_worker_command() == [str(worker_exe)]


def test_frozen_worker_missing_raises_with_all_paths(tmp_path, monkeypatch):
    (tmp_path / "service").mkdir()
    service_exe = tmp_path / "service" / "reportflow-service.exe"
    service_exe.write_bytes(b"x")

    _freeze(monkeypatch, service_exe)
    import pytest as _pytest

    with _pytest.raises(FileNotFoundError) as exc:
        default_worker_command()
    message = str(exc.value)
    assert "worker executable not found" in message
    assert str(tmp_path / "worker" / "reportflow-worker.exe") in message
    assert "Reinstall" in message


def test_missing_worker_records_actionable_error(tmp_path, monkeypatch):
    launcher = Launcher(
        RunStore(tmp_path / "runs.db"),
        lambda: _config(_job(tmp_path)),
        worker_command=[str(tmp_path / "does-not-exist.exe")],
    )
    rec = launcher.run_job_by_name("daily", RunTrigger.MANUAL, is_test=False)

    assert rec.status is RunStatus.CRASHED
    assert "worker executable not found" in (rec.error_summary or "")
    assert "does-not-exist.exe" in (rec.error_summary or "")


def test_resolve_output_paths_with_folder_and_stem(tmp_path):
    from datetime import datetime

    job = _job(tmp_path, output_dir=tmp_path / "reports", output_name="{job}_{date}")
    now = datetime(2026, 7, 7, 6, 0, 0)
    xlsx, pdf = resolve_output_paths(job, run_id="abc", now=now)
    assert xlsx == tmp_path / "reports" / "daily_20260707.xlsx"
    assert pdf == tmp_path / "reports" / "daily_20260707_{sheet}.pdf"


def test_resolve_output_paths_defaults_next_to_input(tmp_path):
    from datetime import datetime

    job = _job(tmp_path, output_dir=None, output_name=None)
    now = datetime(2026, 7, 7, 6, 0, 0)
    xlsx, pdf = resolve_output_paths(job, run_id="abc", now=now)
    # input is tmp_path/t.xlsx -> outputs land next to it with the default stem
    assert xlsx == tmp_path / "daily_20260707.xlsx"
    assert pdf == tmp_path / "daily_20260707_{sheet}.pdf"


def test_resolve_output_paths_no_pdf_when_disabled(tmp_path):
    from datetime import datetime

    job = _job(tmp_path, generate_pdf=False)
    xlsx, pdf = resolve_output_paths(job, run_id="abc", now=datetime(2026, 7, 7))
    assert xlsx.name.endswith(".xlsx")
    assert pdf is None


def test_success_real_run_no_email_when_not_optedin(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTFLOW_FAKE_MODE", "success")
    job = _job(tmp_path, send_report_email=False)
    launcher = _launcher(tmp_path, _config(job))

    rec = launcher.run_job_by_name("daily", RunTrigger.MANUAL, is_test=False)

    assert rec.status is RunStatus.SUCCESS
    assert rec.email_sent is False
    assert len(rec.pdf_paths) == 2
    assert Path(rec.output_xlsx).exists()


def test_fail_records_failed_and_no_email(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTFLOW_FAKE_MODE", "fail")
    job = _job(tmp_path, send_report_email=True)
    launcher = _launcher(tmp_path, _config(job))

    rec = launcher.run_job_by_name("daily", RunTrigger.MANUAL, is_test=False)

    assert rec.status is RunStatus.FAILED
    assert rec.email_sent is False
    assert "boom" in (rec.error_summary or "")


def test_crash_without_result_is_crashed(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTFLOW_FAKE_MODE", "crash")
    launcher = _launcher(tmp_path, _config(_job(tmp_path)))

    rec = launcher.run_job_by_name("daily", RunTrigger.MANUAL, is_test=False)

    assert rec.status is RunStatus.CRASHED
    assert rec.exit_code == 3


def test_timeout_kills_and_records_timed_out(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTFLOW_FAKE_MODE", "hang")
    job = _job(tmp_path)
    launcher = _launcher(tmp_path, _config(job, timeout=1))

    rec = launcher.run_job_by_name("daily", RunTrigger.MANUAL, is_test=False)

    assert rec.status is RunStatus.TIMED_OUT
    assert "timed out" in (rec.error_summary or "")


def test_test_run_sends_email_to_test_recipients(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTFLOW_FAKE_MODE", "success")
    handler = _Capture()
    port = _free_port()
    controller = Controller(handler, hostname="127.0.0.1", port=port)
    controller.start()
    try:
        job = _job(tmp_path, send_report_email=False)  # test run emails regardless
        launcher = _launcher(tmp_path, _config(job, smtp_port=port))
        rec = launcher.run_job_by_name("daily", RunTrigger.TEST, is_test=True)
    finally:
        controller.stop()

    assert rec.status is RunStatus.SUCCESS
    assert rec.email_sent is True
    assert handler.envelopes and set(handler.envelopes[0]) == {"dev@corp.example.com"}


def test_run_history_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTFLOW_FAKE_MODE", "success")
    config = _config(_job(tmp_path))
    launcher = _launcher(tmp_path, config)
    rec = launcher.run_job_by_name("daily", RunTrigger.MANUAL, is_test=False)

    stored = launcher.run_store.get(rec.run_id)
    assert stored is not None and stored.status is RunStatus.SUCCESS
    assert launcher.run_store.latest_for_job("daily").run_id == rec.run_id
