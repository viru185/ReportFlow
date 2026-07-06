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
from reportflow.service.launcher import Launcher

FAKE = str(Path(__file__).parent / "fake_worker.py")


def _job(tmp_path: Path, **over) -> JobConfig:
    base = dict(
        name="daily",
        workbook_template_path=tmp_path / "t.xlsx",
        output_xlsx_path=tmp_path / "out" / "{run_id}.xlsx",
        output_pdf_path=tmp_path / "out" / "{run_id}_{sheet}.pdf",
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
