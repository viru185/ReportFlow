"""Disk housekeeping for the data root: run folders, diagnostic bundles, rotated logs.

Nothing pruned these before 0.8.0 — ``runs/<run_id>/`` (request/result/worker.log per run)
and ``state/bundles/*.zip`` grew forever, and the ``log_retention_days`` setting silently
did nothing. The service now purges on startup and daily; the UI exposes "Delete old
logs…" and "Delete ALL logs…" on the Logs menu.

Safety rules: active runs are never touched; the LIVE per-process log files
(``logs/<proc>/<proc>.log``) are never deleted (loguru holds them open — Windows would
refuse anyway); every deletion is individually best-effort so one locked file cannot
abort the sweep.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from reportflow.core import paths
from reportflow.core.state.run_store import RunStore


@dataclass
class PurgeStats:
    run_dirs: int = 0
    bundles: int = 0
    log_files: int = 0
    db_rows: int = 0
    bytes_freed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "run_dirs": self.run_dirs,
            "bundles": self.bundles,
            "log_files": self.log_files,
            "db_rows": self.db_rows,
            "bytes_freed": self.bytes_freed,
        }


def _tree_size(path: Path) -> int:
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except OSError:
        pass
    return total


def _is_live_log(path: Path) -> bool:
    """The active per-process sink is ``logs/<proc>/<proc>.log`` — never delete it."""
    return path.suffix == ".log" and path.stem == path.parent.name


def purge_logs(
    older_than_days: int | None,
    *,
    everything: bool = False,
    active_run_ids: set[str] | frozenset[str] = frozenset(),
    run_store: RunStore | None = None,
) -> PurgeStats:
    """Delete run folders, bundles, and rotated log files past the retention window.

    ``everything=True`` ignores age (the "Delete ALL logs" action); active runs and the
    live log files are still preserved. Matching runs.db rows are pruned when a
    ``run_store`` is supplied, so history never points at vanished folders.
    """
    stats = PurgeStats()
    cutoff = None if everything else time.time() - (older_than_days or 0) * 86400

    def _expired(path: Path) -> bool:
        if everything:
            return True
        try:
            return cutoff is not None and path.stat().st_mtime < cutoff
        except OSError:
            return False

    runs_root = paths.runs_dir()
    if runs_root.exists():
        for run_dir in runs_root.iterdir():
            if not run_dir.is_dir() or run_dir.name in active_run_ids:
                continue
            if not _expired(run_dir):
                continue
            size = _tree_size(run_dir)
            shutil.rmtree(run_dir, ignore_errors=True)
            if not run_dir.exists():
                stats.run_dirs += 1
                stats.bytes_freed += size

    bundles_root = paths.state_dir() / "bundles"
    if bundles_root.exists():
        for bundle in bundles_root.glob("*.zip"):
            if not _expired(bundle):
                continue
            try:
                size = bundle.stat().st_size
                bundle.unlink()
                stats.bundles += 1
                stats.bytes_freed += size
            except OSError as e:
                logger.debug("Could not delete bundle {}: {}", bundle, e)

    logs_root = paths.logs_dir()
    if logs_root.exists():
        for log_file in logs_root.rglob("*"):
            if not log_file.is_file() or _is_live_log(log_file):
                continue
            if not _expired(log_file):
                continue
            try:
                size = log_file.stat().st_size
                log_file.unlink()
                stats.log_files += 1
                stats.bytes_freed += size
            except OSError as e:  # live handles (rare) just stay for the next sweep
                logger.debug("Could not delete log file {}: {}", log_file, e)

    if run_store is not None:
        keep = set(active_run_ids)
        if everything:
            stats.db_rows = run_store.delete_all(keep_ids=keep)
        elif older_than_days is not None:
            cutoff_iso = (datetime.now() - timedelta(days=older_than_days)).isoformat(
                timespec="seconds"
            )
            stats.db_rows = run_store.delete_before(cutoff_iso, keep_ids=keep)

    logger.info(
        "Log purge ({}): {} run folder(s), {} bundle(s), {} log file(s), {} history row(s), "
        "{:.1f} MB freed",
        "everything" if everything else f"older than {older_than_days}d",
        stats.run_dirs,
        stats.bundles,
        stats.log_files,
        stats.db_rows,
        stats.bytes_freed / 1e6,
    )
    return stats
