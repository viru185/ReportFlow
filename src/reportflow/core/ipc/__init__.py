"""Service <-> Worker IPC contract and atomic JSON I/O."""

from reportflow.core.ipc.contract import (
    RunStatus,
    SheetTask,
    WorkbookTask,
    WorkerRequest,
    WorkerResult,
)
from reportflow.core.ipc.result_io import (
    read_request,
    read_result,
    write_request,
    write_result,
)

__all__ = [
    "RunStatus",
    "SheetTask",
    "WorkbookTask",
    "WorkerRequest",
    "WorkerResult",
    "read_request",
    "read_result",
    "write_request",
    "write_result",
]
