"""Delete a job's old reports (0.16, per job, off by default)."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from reportflow.core.maintenance import purge_logs
from reportflow.core.report_cleanup import delete_old_reports, record_run_files
from reportflow.core.state import RunStore

NOW = datetime(2026, 11, 24, 12, 0, 0)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")


def _run(store, folder: Path, run_id: str, days_ago: float, *, job="daily", ok=True, names=None):
    """A run of ``job`` that wrote its files ``days_ago`` days before NOW."""
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    for name in names or (f"{run_id}.xlsx", f"{run_id}_email.xlsx", f"{run_id}_Summary.pdf"):
        path = folder / name
        path.write_bytes(f"report {run_id}".encode())
        files.append(path)
    record_run_files(
        store, job_name=job, run_id=run_id, finished_at=_iso(days_ago), ok=ok, files=files
    )
    return files


def _names(folder: Path) -> set[str]:
    return {p.name for p in folder.iterdir()}


def test_off_deletes_nothing(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    files = _run(store, tmp_path / "out", "r1", 400)
    _run(store, tmp_path / "out", "r2", 300)
    for days in (None, 0):
        assert delete_old_reports(store, "daily", days, now=NOW).deleted == 0
    assert all(f.exists() for f in files)


def test_old_reports_go_and_everything_else_stays(tmp_path):
    out = tmp_path / "out"
    store = RunStore(tmp_path / "runs.db")
    old = _run(store, out, "r1", 40)
    older = _run(store, out, "r0", 90)
    recent = _run(store, out, "r2", 3)
    newest = _run(store, out, "r3", 0)
    (out / "Budget.xlsx").write_bytes(b"someone else's file")  # never ReportFlow's
    other_job = _run(store, out, "x1", 90, job="weekly")
    stats = delete_old_reports(store, "daily", 30, now=NOW)
    assert stats.deleted == 6 and stats.bytes_freed > 0
    assert not any(f.exists() for f in old + older)
    assert all(f.exists() for f in recent + newest + other_job)
    assert (out / "Budget.xlsx").exists()
    assert {f.run_id for f in store.report_files("daily")} == {"r2", "r3"}
    assert delete_old_reports(store, "daily", 30, now=NOW).deleted == 0  # nothing left to do


def test_the_newest_report_is_always_kept(tmp_path):
    out = tmp_path / "out"
    store = RunStore(tmp_path / "runs.db")
    _run(store, out, "r1", 200)
    good = _run(store, out, "r2", 100)  # the last good report
    failed = _run(store, out, "r3", 50, ok=False, names=["r3.xlsx"])  # newest, but failed
    delete_old_reports(store, "daily", 7, now=NOW)
    assert all(f.exists() for f in good + failed)
    assert _names(out) == {f.name for f in good + failed}


def test_a_file_someone_changed_is_left_alone(tmp_path):
    out = tmp_path / "out"
    store = RunStore(tmp_path / "runs.db")
    edited, resized, untouched = _run(store, out, "r1", 60)
    _run(store, out, "r2", 0)
    later = edited.stat().st_mtime + 3600
    os.utime(edited, (later, later))  # someone opened and saved it
    original = resized.stat().st_mtime
    resized.write_bytes(b"replaced by another file with the same name")
    os.utime(resized, (original, original))  # same time, different size
    stats = delete_old_reports(store, "daily", 30, now=NOW)
    assert (stats.deleted, stats.changed) == (1, 2)
    assert edited.exists() and resized.exists() and not untouched.exists()
    assert {f.run_id for f in store.report_files("daily")} == {"r2"}  # forgotten, not retried


def test_a_file_in_use_is_retried_next_time(tmp_path):
    out = tmp_path / "out"
    store = RunStore(tmp_path / "runs.db")
    report, *_ = _run(store, out, "r1", 60)
    _run(store, out, "r2", 0)
    with report.open("rb"):  # open in Excel: Windows refuses to delete it
        stats = delete_old_reports(store, "daily", 30, now=NOW)
    if sys.platform == "win32":
        assert stats.retry == 1 and report.exists()
        assert delete_old_reports(store, "daily", 30, now=NOW).deleted == 1
    assert not report.exists()


def test_files_already_gone_are_forgotten_unless_the_folder_is_unreachable(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    gone = _run(store, tmp_path / "out", "r1", 60)
    lost = _run(store, tmp_path / "share", "r2", 60)
    _run(store, tmp_path / "out", "r3", 0)
    for f in gone:
        f.unlink()
    for f in lost:
        f.unlink()
    (tmp_path / "share").rmdir()  # a network share that is down looks like this
    stats = delete_old_reports(store, "daily", 30, now=NOW)
    assert (stats.deleted, stats.retry) == (0, 3)
    assert {f.run_id for f in store.report_files("daily")} == {"r2", "r3"}


def test_a_name_written_again_belongs_to_the_newer_run(tmp_path):
    out = tmp_path / "out"
    store = RunStore(tmp_path / "runs.db")
    _run(store, out, "r1", 60, names=["Daily.xlsx"])
    (same,) = _run(store, out, "r2", 1, names=["Daily.xlsx"])  # a name without the date
    _run(store, out, "r3", 0, names=["other.xlsx"])
    assert delete_old_reports(store, "daily", 30, now=NOW).deleted == 0
    assert same.exists()
    records = {f.path.casefold(): f.run_id for f in store.report_files("daily")}
    assert records[str(same).casefold()] == "r2"


def test_paths_match_whatever_their_case(tmp_path):
    out = tmp_path / "out"
    store = RunStore(tmp_path / "runs.db")
    (first,) = _run(store, out, "r1", 60, names=["Report.xlsx"])
    record_run_files(
        store,
        job_name="daily",
        run_id="r2",
        finished_at=_iso(0),
        ok=True,
        files=[Path(str(first).upper())],
    )
    assert [f.run_id for f in store.report_files("daily")] == ["r2"]


def test_a_renamed_job_keeps_its_reports_and_the_log_purge_never_forgets_them(tmp_path):
    out = tmp_path / "out"
    store = RunStore(tmp_path / "runs.db")
    old = _run(store, out, "r1", 60)
    _run(store, out, "r2", 0)
    store.rename_job("daily", "daily report")
    purge_logs(None, everything=True, run_store=store)  # "Delete ALL logs"
    assert store.report_files("daily") == []
    assert delete_old_reports(store, "daily report", 30, now=NOW).deleted == 3
    assert not any(f.exists() for f in old)


def test_runs_record_only_files_that_exist(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    real = tmp_path / "a.xlsx"
    real.write_bytes(b"x")
    count = record_run_files(
        store,
        job_name="daily",
        run_id="r1",
        finished_at=_iso(0),
        ok=False,
        files=[real, real, tmp_path / "never-written.pdf"],
    )
    assert count == 1
    assert [f.path for f in store.report_files("daily")] == [str(real)]
