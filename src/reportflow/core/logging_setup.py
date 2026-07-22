"""Centralized loguru configuration shared by all processes.

* Each process writes a rolling file sink at ``logs/{process}/{process}.log``.
* ``enqueue=True`` makes logging safe across the worker subprocesses.
* ``diagnose=False`` in production so tracebacks never expand and leak secret values.
* A redaction patcher masks anything that looks like a secret before it is written.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from loguru import Record

from reportflow.core import paths

# Patterns whose value we mask in any log record (defensive; we also never log secrets on purpose).
_REDACT_PATTERNS = [
    re.compile(r"(?i)(password|passwd|pwd|secret|token|api[_-]?key)(\s*[=:]\s*)(\S+)"),
]
_REDACTED = "***REDACTED***"

_configured: set[str] = set()


def _redact(message: str) -> str:
    for pat in _REDACT_PATTERNS:
        message = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}{_REDACTED}", message)
    return message


def _patch(record: Record) -> None:
    record["message"] = _redact(record["message"])


def configure_logging(process_name: str, *, level: str = "INFO", to_console: bool = True) -> None:
    """Configure loguru for a process. Idempotent per ``process_name``."""
    if process_name in _configured:
        return
    _apply(process_name, level=level, to_console=to_console)
    _configured.add(process_name)


def reconfigure(
    process_name: str, *, level: str, to_console: bool = True, retention_days: int = 30
) -> None:
    """Re-apply the process sinks with new settings (debug toggle / retention changed)."""
    _apply(process_name, level=level, to_console=to_console, retention_days=retention_days)
    _configured.add(process_name)
    logger.info("Log level set to {} (retention {} days)", level, retention_days)


def _apply(process_name: str, *, level: str, to_console: bool, retention_days: int = 30) -> None:
    logger.remove()
    logger.configure(patcher=_patch)

    if to_console:
        logger.add(sys.stderr, level=level, backtrace=False, diagnose=False)

    log_path = paths.logs_dir() / process_name / f"{process_name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_path,
        level=level,
        rotation="10 MB",
        # Honors the Settings value (log_retention_days) — hardcoding this was why the
        # setting silently did nothing before 0.8.0.
        retention=f"{max(1, retention_days)} days",
        enqueue=True,
        backtrace=False,
        diagnose=False,
        encoding="utf-8",
    )


def add_run_log(run_log_path: Path, *, level: str = "DEBUG") -> int:
    """Add a per-run file sink and return its sink id (remove with :func:`remove_sink`)."""
    run_log_path.parent.mkdir(parents=True, exist_ok=True)
    return logger.add(
        run_log_path,
        level=level,
        enqueue=True,
        backtrace=False,
        diagnose=False,
        encoding="utf-8",
    )


def remove_sink(sink_id: int) -> None:
    try:
        logger.remove(sink_id)
    except ValueError:
        pass
