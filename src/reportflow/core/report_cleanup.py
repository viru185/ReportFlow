"""Delete a job's old reports (0.16 — per job, off by default).

Output names usually carry the date, so every run leaves a new Excel/PDF set in the output
folder and the folder only grows. A job can opt in to "Delete this job's reports after N days"
(``JobConfig.delete_reports_after_days``). It runs after each run of the job and in the nightly
maintenance. The rules, so it can never delete something it shouldn't:

- Only files ReportFlow itself wrote for this job are candidates. Each run's files (output
  workbook, email copy, PDFs) are recorded in runs.db's ``report_files`` table — kept apart from
  the run history, so the log purge never loses track of them. Nothing else in the folder is
  ever looked at.
- A file whose size or modified time no longer matches what the run left was changed by someone
  (edited, or replaced by another file of that name): it is left alone and forgotten.
- The newest report is always kept, however old: the newest run's files and the newest
  successful run's files.
- A file that can't be deleted now (open in Excel, share unreachable) is tried again next time.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from reportflow.core.state.run_store import ReportFile, RunStore

# FAT and some network shares keep modified times to 2 s.
_MTIME_SLACK_SECONDS = 2.0


@dataclass
class CleanupStats:
    deleted: int = 0
    bytes_freed: int = 0
    changed: int = 0  # left alone: changed since ReportFlow wrote it
    retry: int = 0  # in use or unreachable: tried again next time


def record_run_files(
    store: RunStore,
    *,
    job_name: str,
    run_id: str,
    finished_at: str,
    ok: bool,
    files: Iterable[Path | str],
) -> int:
    """Remember the files a run wrote, as they are now. Returns how many were recorded."""
    entries: list[ReportFile] = []
    seen: set[str] = set()
    for item in files:
        path = Path(item)
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        try:
            st = path.stat()
        except OSError:
            continue  # never written (failed part-way): nothing to remember
        entries.append(
            ReportFile(
                path=str(path),
                job_name=job_name,
                run_id=run_id,
                created_at=finished_at,
                ok=ok,
                mtime=st.st_mtime,
                size=st.st_size,
            )
        )
    store.record_report_files(entries)
    return len(entries)


def _newest_run(files: list[ReportFile]) -> str | None:
    if not files:
        return None
    return max(files, key=lambda f: (f.created_at, f.run_id)).run_id


def delete_old_reports(
    store: RunStore, job_name: str, days: int | None, *, now: datetime | None = None
) -> CleanupStats:
    """Delete ``job_name``'s recorded report files older than ``days`` (see the module rules)."""
    stats = CleanupStats()
    if not days or days < 1:
        return stats
    files = store.report_files(job_name)
    keep = {_newest_run(files), _newest_run([f for f in files if f.ok])} - {None}
    cutoff = ((now or datetime.now()) - timedelta(days=days)).isoformat(timespec="seconds")
    forget: list[str] = []
    for f in files:
        if f.run_id in keep or f.created_at >= cutoff:
            continue
        path = Path(f.path)
        try:
            st = path.stat()
        except FileNotFoundError:
            if path.parent.exists():
                forget.append(f.path)  # deleted by someone already
            else:
                stats.retry += 1  # the folder is gone or the share is down: check later
            continue
        except OSError:
            stats.retry += 1
            continue
        if abs(st.st_mtime - f.mtime) > _MTIME_SLACK_SECONDS or st.st_size != f.size:
            logger.info("Old report {} was changed since ReportFlow wrote it — left alone", path)
            stats.changed += 1
            forget.append(f.path)
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            forget.append(f.path)
            continue
        except OSError as e:  # open in Excel, read-only, …: next time
            logger.debug("Could not delete old report {} yet: {}", path, e)
            stats.retry += 1
            continue
        forget.append(f.path)
        stats.deleted += 1
        stats.bytes_freed += st.st_size
    store.forget_report_files(forget)
    if stats.deleted or stats.changed or stats.retry:
        logger.info(
            "Old reports of '{}' (older than {} day(s)): {} deleted ({:.1f} MB), {} changed by "
            "someone and kept, {} to retry",
            job_name,
            days,
            stats.deleted,
            stats.bytes_freed / 1e6,
            stats.changed,
            stats.retry,
        )
    return stats
