"""Atomic JSON read/write for the IPC request and result files.

Writes go to a temp file in the same directory followed by ``os.replace`` so a reader can
never observe a half-written file.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from reportflow.core.ipc.contract import WorkerProgress, WorkerRequest, WorkerResult


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


def write_progress(progress: WorkerProgress, path: Path) -> bool:
    """Best effort: a reader holding the file open makes ``os.replace`` fail on Windows for
    a moment, so retry briefly — and never fail a run over its progress note."""
    text = progress.model_dump_json(indent=2)
    for attempt in range(5):
        try:
            _atomic_write(Path(path), text)
            return True
        except OSError as e:
            if attempt == 4:
                logger.debug("Could not write progress {}: {}", path, e)
            time.sleep(0.02)
    return False


def read_progress(path: Path) -> WorkerProgress | None:
    """The run's progress, or None when there is none (yet) or it can't be read."""
    try:
        return WorkerProgress.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        return None
