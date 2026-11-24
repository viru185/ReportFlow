"""The single source of truth for the Service <-> Worker contract.

The Service writes a ``WorkerRequest`` JSON file and launches the worker with its path.
The worker ALWAYS writes a ``WorkerResult`` JSON file (even on failure) and sets an exit
code. The result file — not stdout — is the authoritative channel.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(StrEnum):
    RUNNING = "running"  # service-side only: waiting or worker in flight (never from the worker)
    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"  # set by the Service when it reaps a hung worker
    CRASHED = "crashed"  # set by the Service when no result file was produced
    STOPPED = "stopped"  # 0.16: a user stopped it (Stop button) — not a failure
    INTERRUPTED = "interrupted"  # 0.16: the service stopped/restarted while it was in flight


# Runs that went wrong: the dashboard's Failures count, the red card edge, "last failure".
# A run a user stopped is not one of them.
FAILURE_STATUSES = frozenset(
    {RunStatus.FAILED, RunStatus.TIMED_OUT, RunStatus.CRASHED, RunStatus.INTERRUPTED}
)
# Everything a run can end as.
FINAL_STATUSES = frozenset(set(RunStatus) - {RunStatus.RUNNING})


class _IpcBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SheetTask(_IpcBase):
    """An included sheet. ``pdf``: export it; ``hidden``: hide it in the saved output."""

    name: str
    excel: bool = True
    pdf: bool = True
    hidden: bool = False


class WorkbookTask(_IpcBase):
    """One input workbook -> one output copy (plus per-sheet PDFs)."""

    input_excel_path: Path
    output_xlsx_path: Path
    # ``{sheet}``-tokenized pattern; None when no sheet of this workbook wants a PDF.
    output_pdf_path: Path | None = None
    sheets: list[SheetTask] = Field(min_length=1)
    unselected_sheets: Literal["remove", "hide", "keep"] = "remove"
    pdf_mode: Literal["separate", "combined"] = "separate"

    @property
    def sheet_names(self) -> list[str]:
        return [s.name for s in self.sheets]


class WorkerRequest(_IpcBase):
    run_id: str
    job_name: str

    workbooks: list[WorkbookTask] = Field(min_length=1)
    # False: the first failing workbook fails the run. True: skip it with a warning and
    # deliver the rest (the run still fails when EVERY workbook failed).
    continue_on_workbook_failure: bool = False

    freeze_values: bool = True
    post_refresh_wait_seconds: int = Field(default=10, ge=0)
    fail_if_sheet_empty: bool = True
    fail_if_sheet_has_errors: bool = False
    require_pi_datalink: bool = False
    blank_out_values: list[str] = Field(default_factory=list)

    timeout_seconds: int = Field(gt=0)
    is_test: bool = False
    debug: bool = False  # verbose per-run worker logging

    # Where the worker must write its result and per-run log.
    result_path: Path
    log_path: Path


class WorkerResult(_IpcBase):
    run_id: str
    status: RunStatus
    message: str = ""

    # One output workbook per successfully built input workbook, in job order.
    output_xlsx_paths: list[Path] = Field(default_factory=list)
    pdf_paths: list[Path] = Field(default_factory=list)
    # Explicit delivery manifest: local Excel copies must never leak into PDF-only mail.
    attachment_paths: list[Path] = Field(default_factory=list)
    # Input file names skipped under continue_on_workbook_failure (their reason is a warning).
    failed_workbooks: list[str] = Field(default_factory=list)

    started_at: str | None = None  # ISO-8601
    finished_at: str | None = None  # ISO-8601
    duration_seconds: float | None = None

    # Non-fatal notes the user should see even on success (e.g. "12 #REF! cells — delivered").
    warnings: list[str] = Field(default_factory=list)

    error_detail: str | None = None

    # Cleanup accounting so we can prove no ghost EXCEL.EXE was left behind.
    excel_pid: int | None = None
    excel_pid_reaped: bool = False

    @property
    def ok(self) -> bool:
        return self.status is RunStatus.SUCCESS


class ProcessRef(_IpcBase):
    """A process the run started. ``create_time`` (psutil) tells it apart from a later
    process that reuses its PID — nothing is ever killed on the PID alone."""

    pid: int
    create_time: float
    image: str  # lower-case executable name, e.g. "excel.exe"


class WorkerProgress(_IpcBase):
    """What a run is doing right now — ``progress.json`` beside ``result.json``, rewritten
    by the worker at every step (0.16). The service shows the step on the dashboard and in
    the history, and uses the process list to close a stopped/timed-out run's Excel (Excel
    is started by COM, so it is NOT a child of the worker)."""

    run_id: str
    step: str
    since: str  # ISO-8601, when this step began
    workbook: str | None = None  # file name of the workbook being built
    worker: ProcessRef | None = None
    excels: list[ProcessRef] = Field(default_factory=list)  # a COM retry starts a new one


def progress_path(result_path: Path) -> Path:
    """Where a run's progress file lives (the run folder)."""
    return Path(result_path).parent / "progress.json"
