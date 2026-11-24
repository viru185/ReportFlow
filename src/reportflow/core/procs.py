"""Recording and killing the processes a run started — never on the PID alone (0.16).

A PID is reused by Windows once its process ends, so a recorded process is killed only when
its PID, its executable name and its start time (psutil ``create_time``) all still match —
and only for the executable names the caller allows.
"""

from __future__ import annotations

import os

import psutil
from loguru import logger

from reportflow.core.ipc.contract import ProcessRef

_CREATE_TIME_SLACK = 0.5  # seconds — create_time is a float rounded by the OS


def process_ref(pid: int | None = None) -> ProcessRef | None:
    """A reference to a live process (default: this one), or None if it's gone."""
    try:
        proc = psutil.Process(pid or os.getpid())
        return ProcessRef(
            pid=proc.pid, create_time=proc.create_time(), image=(proc.name() or "").lower()
        )
    except psutil.Error:
        return None


def is_alive(ref: ProcessRef) -> bool:
    """True when the recorded process (same PID, name and start time) still runs."""
    try:
        proc = psutil.Process(ref.pid)
        return (proc.name() or "").lower() == ref.image and abs(
            proc.create_time() - ref.create_time
        ) <= _CREATE_TIME_SLACK
    except psutil.Error:
        return False


def kill_verified(ref: ProcessRef, *, images: frozenset[str] | set[str]) -> bool:
    """Kill the recorded process if it is still that very process and its executable is one
    of ``images``. Returns True when it was killed (False: already gone, or not ours)."""
    if ref.image not in images or not is_alive(ref):
        return False
    try:
        proc = psutil.Process(ref.pid)
        proc.kill()
        proc.wait(timeout=5)
        logger.info("Closed {} (pid {})", ref.image, ref.pid)
        return True
    except psutil.TimeoutExpired:
        logger.warning("{} (pid {}) did not exit after kill", ref.image, ref.pid)
        return True
    except psutil.Error as e:
        logger.debug("Could not kill {} (pid {}): {}", ref.image, ref.pid, e)
        return False
