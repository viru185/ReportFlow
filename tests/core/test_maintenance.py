"""purge_logs sweeps run folders, bundles, and rotated logs — never live files/active runs."""

from __future__ import annotations

import os
import time
from pathlib import Path

from reportflow.core import paths
from reportflow.core.ipc.contract import RunStatus
from reportflow.core.maintenance import purge_logs
from reportflow.core.state import RunRecord, RunStore, RunTrigger

_OLD = time.time() - 40 * 86400  # 40 days ago — past a 30-day window


def _age(path: Path, mtime: float = _OLD) -> None:
    os.utime(path, (mtime, mtime))


def _seed_run_dir(run_id: str, *, old: bool) -> Path:
    d = paths.runs_dir() / run_id
    d.mkdir(parents=True)
    (d / "worker.log").write_text("log line", encoding="utf-8")
    (d / "result.json").write_text("{}", encoding="utf-8")
    if old:
        for f in d.iterdir():
            _age(f)
        _age(d)
    return d


def _seed_bundle(name: str, *, old: bool) -> Path:
    bundles = paths.state_dir() / "bundles"
    bundles.mkdir(parents=True, exist_ok=True)
    z = bundles / name
    z.write_bytes(b"PK\x03\x04" + b"x" * 100)
    if old:
        _age(z)
    return z


def _seed_logs() -> tuple[Path, Path]:
    """A live service.log (never deleted) and an old rotated file (deletable)."""
    svc_dir = paths.logs_dir() / "service"
    svc_dir.mkdir(parents=True, exist_ok=True)
    live = svc_dir / "service.log"
    live.write_text("live", encoding="utf-8")
    _age(live)  # even an OLD live file must survive
    rotated = svc_dir / "service.2026-06-01_10-00-00_000000.log"
    rotated.write_text("rotated", encoding="utf-8")
    _age(rotated)
    return live, rotated


def test_purge_old_deletes_only_expired(tmp_path):
    old_run = _seed_run_dir("oldrun", old=True)
    new_run = _seed_run_dir("newrun", old=False)
    old_zip = _seed_bundle("old.zip", old=True)
    new_zip = _seed_bundle("new.zip", old=False)
    live, rotated = _seed_logs()

    stats = purge_logs(30)

    assert not old_run.exists() and new_run.exists()
    assert not old_zip.exists() and new_zip.exists()
    assert live.exists() and not rotated.exists()  # live survives even when old
    assert stats.run_dirs == 1 and stats.bundles == 1 and stats.log_files == 1
    assert stats.bytes_freed > 0


def test_purge_everything_ignores_age_but_keeps_live_and_active(tmp_path):
    active = _seed_run_dir("activerun", old=False)
    idle = _seed_run_dir("idlerun", old=False)
    _seed_bundle("fresh.zip", old=False)
    live, rotated = _seed_logs()

    stats = purge_logs(None, everything=True, active_run_ids={"activerun"})

    assert active.exists()  # in-flight run untouched
    assert not idle.exists()
    assert live.exists() and not rotated.exists()
    assert stats.run_dirs == 1 and stats.bundles == 1


def test_purge_prunes_matching_db_rows(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    for run_id, started in (("a", "2026-01-01T06:00:00"), ("b", "2026-07-20T06:00:00")):
        store.upsert(
            RunRecord(
                run_id=run_id,
                job_name="j",
                trigger=RunTrigger.MANUAL,
                status=RunStatus.SUCCESS,
                started_at=started,
            )
        )

    stats = purge_logs(30, run_store=store)

    assert stats.db_rows == 1
    assert store.get("a") is None and store.get("b") is not None

    stats = purge_logs(None, everything=True, run_store=store, active_run_ids={"b"})
    assert stats.db_rows == 0  # "b" is active -> kept
    assert store.get("b") is not None


def test_run_store_delete_all_and_before(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    for run_id, started in (("x", "2026-01-01T00:00:00"), ("y", "2026-07-01T00:00:00")):
        store.upsert(
            RunRecord(
                run_id=run_id,
                job_name="j",
                trigger=RunTrigger.MANUAL,
                status=RunStatus.SUCCESS,
                started_at=started,
            )
        )
    assert store.delete_before("2026-06-01T00:00:00") == 1
    assert store.get("x") is None
    assert store.delete_all(keep_ids={"y"}) == 0
    assert store.delete_all() == 1
