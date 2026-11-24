"""Service <-> Worker IPC contract and atomic JSON I/O."""

from reportflow.core.ipc.contract import (
    FAILURE_STATUSES,
    FINAL_STATUSES,
    ProcessRef,
    RunStatus,
    SheetTask,
    WorkbookTask,
    WorkerProgress,
    WorkerRequest,
    WorkerResult,
    progress_path,
)
from reportflow.core.ipc.result_io import (
    read_progress,
    read_request,
    read_result,
    write_progress,
    write_request,
    write_result,
)

__all__ = [
    "FAILURE_STATUSES",
    "FINAL_STATUSES",
    "ProcessRef",
    "RunStatus",
    "SheetTask",
    "WorkbookTask",
    "WorkerProgress",
    "WorkerRequest",
    "WorkerResult",
    "progress_path",
    "read_progress",
    "read_request",
    "read_result",
    "write_progress",
    "write_request",
    "write_result",
]
