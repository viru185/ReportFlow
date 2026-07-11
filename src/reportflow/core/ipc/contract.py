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
    RUNNING = "running"  # service-side only: worker in flight (never written by the worker)
    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"  # set by the Service when it reaps a hung worker
    CRASHED = "crashed"  # set by the Service when no result file was produced


class _IpcBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkerRequest(_IpcBase):
    run_id: str
    job_name: str

    input_excel_path: Path
    output_xlsx_path: Path
    output_pdf_path: Path | None = None

    sheet_names: list[str] = Field(min_length=1)
    freeze_values: bool = True
    generate_pdf: bool = True
    post_refresh_wait_seconds: int = Field(default=10, ge=0)
    fail_if_sheet_empty: bool = True
    fail_if_sheet_has_errors: bool = False
    keep_only_selected_sheets: bool = True
    unselected_sheets_mode: Literal["remove", "hide"] = "remove"
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

    output_xlsx: Path | None = None
    pdf_paths: list[Path] = Field(default_factory=list)

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
