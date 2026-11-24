"""0.16: runs cut off by a service stop/restart are recovered at the next start, a clean
stop ends in-flight runs itself, and only one service may own the data folder."""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import psutil
import pytest
from fastapi.testclient import TestClient

from reportflow.core import paths
from reportflow.core.ipc import WorkerProgress, WorkerResult, write_progress, write_result
from reportflow.core.ipc.contract import RunStatus
from reportflow.core.state import RunRecord, RunStore, RunTrigger
from reportflow.service.launcher import Launcher

from .fake_worker import _detached_sleeper
from .test_launcher import _job, _launcher
from .test_stop_and_queue import _config

_IMAGES = frozenset({"excel.exe", "python.exe"})


@pytest.fixture(autouse=True)
def _stand_ins(monkeypatch):
    monkeypatch.setattr(Launcher, "_EXCEL_IMAGES", _IMAGES)


def _running_row(store: RunStore, run_id: str) -> Path:
    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    store.upsert(
        RunRecord(
            run_id=run_id,
            job_name="daily",
            trigger=RunTrigger.SCHEDULED,
            status=RunStatus.RUNNING,
            started_at="2026-11-24T11:54:30",
            worker_log_path=str(run_dir / "worker.log"),
        )
    )
    return run_dir


def _gone(pid: int) -> bool:
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if not psutil.pid_exists(pid) or not psutil.Process(pid).is_running():
            return True
        time.sleep(0.05)
    return False


def test_a_cut_off_run_is_recorded_and_what_it_left_is_closed(tmp_path):
    launcher = _launcher(tmp_path, _config(_job(tmp_path)))
    run_dir = _running_row(launcher.run_store, "b2f50a6d96c7")
    worker = _detached_sleeper(run_dir / "w.pid")
    excel = _detached_sleeper(run_dir / "e.pid")
    write_progress(
        WorkerProgress(
            run_id="b2f50a6d96c7",
            step="Freezing values on 'Problem Points'",
            since=datetime.now().isoformat(timespec="seconds"),
            worker=worker,
            excels=[excel],
        ),
        run_dir / "progress.json",
    )
    assert launcher.recover_interrupted() == 1
    assert _gone(worker.pid) and _gone(excel.pid)
    rec = launcher.run_store.get("b2f50a6d96c7")
    assert rec.status is RunStatus.INTERRUPTED and rec.email_note == "not sent — interrupted"
    assert "while this run was at: Freezing values on 'Problem Points'" in rec.error_summary


def test_a_process_that_reused_the_pid_is_spared(tmp_path):
    launcher = _launcher(tmp_path, _config(_job(tmp_path)))
    run_dir = _running_row(launcher.run_store, "r1")
    bystander = _detached_sleeper(run_dir / "b.pid")
    stale = bystander.model_copy(update={"create_time": bystander.create_time - 600})
    write_progress(
        WorkerProgress(
            run_id="r1", step="Refreshing data", since="2026-11-24T11:55:00", excels=[stale]
        ),
        run_dir / "progress.json",
    )
    try:
        launcher.recover_interrupted()
        assert psutil.pid_exists(bystander.pid) and psutil.Process(bystander.pid).is_running()
    finally:
        psutil.Process(bystander.pid).kill()


def test_a_run_cut_off_after_it_was_built_keeps_its_report(tmp_path):
    launcher = _launcher(tmp_path, _config(_job(tmp_path)))
    run_dir = _running_row(launcher.run_store, "r2")
    out = tmp_path / "report.xlsx"
    out.write_bytes(b"PK")
    write_result(
        WorkerResult(run_id="r2", status=RunStatus.SUCCESS, output_xlsx_paths=[out]),
        run_dir / "result.json",
    )
    launcher.recover_interrupted()
    rec = launcher.run_store.get("r2")
    assert rec.status is RunStatus.INTERRUPTED and rec.output_xlsx == str(out)
    assert "built but before it was emailed" in rec.error_summary


def test_a_run_of_this_service_is_left_alone(tmp_path):
    from .inflight import queued_run

    launcher = _launcher(tmp_path, _config(_job(tmp_path)))
    _running_row(launcher.run_store, "r-queued")
    with queued_run(launcher, "daily", "r-queued"):
        assert launcher.recover_interrupted() == 0
    assert launcher.run_store.get("r-queued").status is RunStatus.RUNNING


def test_stopping_the_service_ends_its_runs_as_interrupted(tmp_path, monkeypatch):
    from reportflow.core.config.loader import save_config
    from reportflow.service.api import ServiceState, create_app

    from .test_api import FAKE, _job_payload, _make_wb

    monkeypatch.setenv("REPORTFLOW_FAKE_MODE", "hang")
    save_config(_config())
    state = ServiceState(worker_command=[sys.executable, FAKE])
    with TestClient(create_app(state)) as c:
        _make_wb(tmp_path / "t.xlsx")
        assert c.post("/jobs", json=_job_payload(tmp_path)).status_code == 201
        run_id = c.post("/jobs/daily/dry-run").json()["run_id"]
        end = time.monotonic() + 10
        while run_id not in state.launcher.active_run_ids() and time.monotonic() < end:
            time.sleep(0.05)
    rec = state.run_store.get(run_id)  # the service stopped: lifespan shutdown ran
    assert rec.status is RunStatus.INTERRUPTED
    assert "service was stopping" in rec.error_summary


def test_only_one_service_owns_the_data_folder():
    import msvcrt

    from reportflow.service import __main__ as service_main

    assert service_main.take_instance_lock() is True
    try:
        with open(paths.state_dir() / "service.lock", "a+") as other:
            with pytest.raises(OSError):
                msvcrt.locking(other.fileno(), msvcrt.LK_NBLCK, 1)
    finally:
        assert service_main._instance_lock is not None
        service_main._instance_lock.close()
        service_main._instance_lock = None


def test_the_installer_lets_the_service_stop_cleanly():
    iss = (
        Path(__file__).resolve().parents[2] / "packaging" / "innosetup" / "reportflow.iss"
    ).read_text(encoding="utf-8")
    assert "AppStopMethodConsole 15000" in iss
