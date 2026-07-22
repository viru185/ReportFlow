"""Runtime state models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from reportflow.core.ipc.contract import RunStatus


class RunTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    TEST = "test"
    DRY_RUN = "dry_run"  # build + validate the report, never email (PI data check)


class RunRecord(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    run_id: str
    job_name: str
    trigger: RunTrigger
    status: RunStatus
    is_test: bool = False

    started_at: str | None = None
    finished_at: str | None = None
    # Authoritative worker-measured duration; falls back to finished-started when absent.
    duration_seconds: float | None = None
    exit_code: int | None = None

    output_xlsx: str | None = None
    pdf_paths: list[str] = Field(default_factory=list)

    error_summary: str | None = None
    # Non-fatal notes from the worker shown even on success (e.g. error cells delivered anyway).
    warnings: list[str] = Field(default_factory=list)
    worker_log_path: str | None = None
    email_sent: bool = False
    # Human-readable email outcome: "sent to N recipient(s)", "not sent — …", "failed: …"
    email_note: str | None = None
