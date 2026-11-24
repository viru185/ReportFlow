"""0.16: one admission queue, one run per job, Stop, and Excel closed on stop/timeout.

The fake worker's ``hang_excel`` mode starts a stand-in "Excel" that is NOT its child (as
COM's Excel isn't) and records it in progress.json; the launcher must close it.
"""

from __future__ import annotations

import time
from pathlib import Path

import psutil
import pytest

from reportflow.core.config.models import AppConfig, AppSettings, SmtpConfig, TestSettings
from reportflow.core.ipc import ProcessRef, read_progress
from reportflow.core.ipc.contract import RunStatus
from reportflow.core.procs import kill_verified, process_ref
from reportflow.core.state import RunTrigger
from reportflow.service.launcher import JobBusyError, Launcher, StopRefusedError

from .test_launcher import _job, _launcher

_TESTS_EXCEL = frozenset({"excel.exe", "python.exe"})  # the stand-in Excel is python.exe


def _config(*jobs, cap: int = 2, timeout: int = 60) -> AppConfig:
    return AppConfig(
        app=AppSettings(max_global_concurrency=cap, default_timeout_seconds=timeout),
        smtp=SmtpConfig(host="127.0.0.1", port=1, use_starttls=False, username=""),
        test=TestSettings(),
        jobs=list(jobs),
    )


@pytest.fixture(autouse=True)
def _stand_in_excel(monkeypatch):
    monkeypatch.setattr(Launcher, "_EXCEL_IMAGES", _TESTS_EXCEL)


def _wait(predicate, timeout: float = 20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("timed out waiting")


def _finished(launcher: Launcher, run_id: str):
    rec = launcher.run_store.get(run_id)
    return (
        rec
        if rec and rec.status is not RunStatus.RUNNING and run_id not in launcher.inflight_run_ids()
        else None
    )


def _fake_excel(launcher: Launcher, run_id: str) -> ProcessRef:
    """The stand-in Excel the fake worker recorded in the run's progress.json."""
    run_dir = Path(launcher.run_store.get(run_id).worker_log_path).parent
    progress = _wait(lambda: read_progress(run_dir / "progress.json"))
    return progress.excels[0]


def test_stop_ends_the_run_closes_its_excel_and_never_emails(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTFLOW_FAKE_MODE", "hang_excel")
    job = _job(tmp_path, stage="live")
    launcher = _launcher(tmp_path, _config(job))
    run_id = launcher.submit_job_by_name("daily", RunTrigger.MANUAL)
    excel = _fake_excel(launcher, run_id)
    assert psutil.pid_exists(excel.pid)
    _wait(lambda: (launcher.live(run_id) or {}).get("step"))
    assert launcher.live(run_id)["step"] == "Freezing values on 'Problem Points'"

    assert launcher.stop(run_id, "CORP\\tester") in ("running", "stopping")
    rec = _wait(lambda: _finished(launcher, run_id))
    assert rec.status is RunStatus.STOPPED
    assert "Stopped by CORP\\tester" in rec.error_summary
    assert "while: Freezing values on 'Problem Points'" in rec.error_summary
    assert rec.email_sent is False and rec.email_note == "not sent — stopped"
    assert not psutil.pid_exists(excel.pid) or not psutil.Process(excel.pid).is_running()


def test_a_timeout_closes_the_runs_excel_and_names_the_last_step(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTFLOW_FAKE_MODE", "hang_excel")
    job = _job(tmp_path, timeout_seconds=3)
    launcher = _launcher(tmp_path, _config(job))
    run_id = launcher.submit_job_by_name("daily", RunTrigger.MANUAL)
    excel = _fake_excel(launcher, run_id)
    rec = _wait(lambda: _finished(launcher, run_id))
    assert rec.status is RunStatus.TIMED_OUT
    assert "Last step: Freezing values on 'Problem Points'." in rec.error_summary
    assert not psutil.pid_exists(excel.pid) or not psutil.Process(excel.pid).is_running()


def test_one_run_per_job(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTFLOW_FAKE_MODE", "hang")
    launcher = _launcher(tmp_path, _config(_job(tmp_path)))
    run_id = launcher.submit_job_by_name("daily", RunTrigger.MANUAL)
    with pytest.raises(JobBusyError, match="already"):
        launcher.submit_job_by_name("daily", RunTrigger.SCHEDULED)
    launcher.stop(run_id, "tester")
    _wait(lambda: _finished(launcher, run_id))
    second = launcher.submit_job_by_name("daily", RunTrigger.MANUAL)  # free again
    launcher.stop(second, "tester")
    _wait(lambda: _finished(launcher, second))


def test_stopping_a_waiting_run_is_instant_and_starts_no_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTFLOW_FAKE_MODE", "hang")
    first = _job(tmp_path, name="first")
    second = _job(tmp_path, name="second", input_excel_path=tmp_path / "other.xlsx")
    launcher = _launcher(tmp_path, _config(first, second, cap=1))
    running = launcher.submit_job_by_name("first", RunTrigger.MANUAL)
    _wait(lambda: running in launcher.active_run_ids())
    waiting = launcher.submit_job_by_name("second", RunTrigger.MANUAL)
    live = _wait(
        lambda: (
            launcher.live(waiting) if (launcher.live(waiting) or {}).get("waiting_for") else None
        )
    )
    assert live["phase"] == "queued" and live["waiting_for"] == "all 1 run slot(s) are busy"
    started = time.monotonic()
    launcher.stop(waiting, "tester")
    rec = _wait(lambda: _finished(launcher, waiting))
    assert time.monotonic() - started < 2
    assert rec.status is RunStatus.STOPPED and "before it started" in rec.error_summary
    assert not (Path(rec.worker_log_path).parent / "request.json").exists()  # never launched
    assert running in launcher.active_run_ids()  # the other run is untouched
    launcher.stop(running, "tester")
    _wait(lambda: _finished(launcher, running))


def _intervals(log_dir: Path) -> dict[str, tuple[float, float]]:
    spans: dict[str, list[float]] = {}
    lines = [ln for f in log_dir.glob("*.log") for ln in f.read_text(encoding="utf-8").splitlines()]
    for line in lines:
        _kind, job, moment = line.split()
        spans.setdefault(job, []).append(float(moment))
    return {job: (min(v), max(v)) for job, v in spans.items()}


@pytest.mark.parametrize("same_file", [True, False])
def test_runs_on_the_same_workbook_wait_for_each_other(tmp_path, monkeypatch, same_file):
    log = tmp_path / "spans"
    log.mkdir()
    monkeypatch.setenv("REPORTFLOW_FAKE_MODE", "slow")
    monkeypatch.setenv("REPORTFLOW_FAKE_LOG", str(log))
    # Long enough that two workers starting on a busy machine still overlap.
    monkeypatch.setenv("REPORTFLOW_FAKE_SLEEP", "4")
    a = _job(tmp_path, name="alpha", input_excel_path=tmp_path / "Shared.xlsx")
    other = tmp_path / ("SHARED.xlsx" if same_file else "Other.xlsx")  # same file, other case
    b = _job(tmp_path, name="beta", input_excel_path=other)
    launcher = _launcher(tmp_path, _config(a, b, cap=2))
    ids = [launcher.submit_job_by_name(n, RunTrigger.MANUAL) for n in ("alpha", "beta")]
    if same_file:
        live = _wait(lambda: (launcher.live(ids[1]) or {}).get("waiting_for"))
        assert live == "same workbook as 'alpha' (SHARED.xlsx)"
    for run_id in ids:
        assert _wait(lambda r=run_id: _finished(launcher, r)).status is RunStatus.SUCCESS
    spans = _intervals(log)
    overlap = spans["alpha"][1] > spans["beta"][0] and spans["beta"][1] > spans["alpha"][0]
    assert overlap is not same_file, spans


def test_stop_after_the_run_finished_is_refused_or_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTFLOW_FAKE_MODE", "success")
    launcher = _launcher(tmp_path, _config(_job(tmp_path)))
    rec = launcher.run_job_by_name("daily", RunTrigger.DRY_RUN)
    with pytest.raises(KeyError):
        launcher.stop(rec.run_id, "tester")
    with pytest.raises(KeyError):
        launcher.stop("no-such-run", "tester")


def test_a_kill_needs_the_same_process_not_just_the_same_pid():
    me = process_ref()
    assert me is not None
    other_start = me.model_copy(update={"create_time": me.create_time - 3600})
    assert kill_verified(other_start, images={me.image}) is False  # a reused PID: spared
    assert kill_verified(me, images={"excel.exe"}) is False  # not an allowed image: spared


def test_refuses_stop_once_timing_out(tmp_path):
    launcher = _launcher(tmp_path, _config(_job(tmp_path)))
    from .inflight import queued_run

    with queued_run(launcher, "daily", "r1") as slot:
        slot.kill_reason = "timeout"
        with pytest.raises(StopRefusedError, match="timeout"):
            launcher.stop("r1", "tester")
