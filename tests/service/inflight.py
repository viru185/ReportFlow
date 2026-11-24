"""Pretend a job has a run waiting in the launcher (no worker, no thread)."""

from __future__ import annotations

from contextlib import contextmanager

from reportflow.core.state import RunTrigger
from reportflow.service.launcher import Launcher, _Slot


@contextmanager
def queued_run(launcher: Launcher, job: str, run_id: str = "r-queued"):
    slot = _Slot(run_id=run_id, job_key=job.casefold(), job_name=job, trigger=RunTrigger.MANUAL)
    with launcher._cv:
        launcher._slots[run_id] = slot
        launcher._by_job[slot.job_key] = run_id
    try:
        yield slot
    finally:
        launcher._forget(slot)
