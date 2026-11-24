"""The worker's ``progress.json`` writer (0.16): what the run is doing right now, and which
Excel processes it started. Best effort — it never fails a run."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportflow.core.ipc import WorkerProgress, progress_path, write_progress
from reportflow.core.procs import process_ref


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Progress:
    def __init__(self, run_id: str, result_path: Path) -> None:
        self.path = progress_path(result_path)
        self.data = WorkerProgress(
            run_id=run_id, step="Starting", since=_now(), worker=process_ref()
        )
        self._write()

    def step(self, text: str, *, workbook: str | None = None) -> None:
        """A new step (``workbook``: the file being built, kept until the next one)."""
        if text == self.data.step and (workbook is None or workbook == self.data.workbook):
            return
        self.data.step = text
        self.data.since = _now()
        if workbook is not None:
            self.data.workbook = workbook
        self._write()

    def add_excel(self, pid: int | None) -> None:
        """Record an Excel this run started — the service closes it on Stop or a timeout."""
        ref = process_ref(pid) if pid else None
        if ref is not None and all(r.pid != ref.pid for r in self.data.excels):
            self.data.excels.append(ref)
            self._write()

    def _write(self) -> None:
        write_progress(self.data, self.path)
