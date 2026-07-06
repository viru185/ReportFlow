"""Atomic JSON read/write for the IPC request and result files.

Writes go to a temp file in the same directory followed by ``os.replace`` so a reader can
never observe a half-written file.
"""

from __future__ import annotations

import os
from pathlib import Path

from reportflow.core.ipc.contract import WorkerRequest, WorkerResult


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_request(request: WorkerRequest, path: Path | None = None) -> Path:
    target = path or request.result_path.parent / "request.json"
    _atomic_write(target, request.model_dump_json(indent=2))
    return target


def read_request(path: Path) -> WorkerRequest:
    return WorkerRequest.model_validate_json(Path(path).read_text(encoding="utf-8"))


def write_result(result: WorkerResult, path: Path) -> Path:
    _atomic_write(Path(path), result.model_dump_json(indent=2))
    return Path(path)


def read_result(path: Path) -> WorkerResult:
    return WorkerResult.model_validate_json(Path(path).read_text(encoding="utf-8"))
