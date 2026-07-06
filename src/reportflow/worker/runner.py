"""Orchestrate one job run: WorkerRequest -> Excel automation -> WorkerResult.

The runner ALWAYS produces a ``result.json`` (success or failure) and never lets an
exception escape without first recording it. The Excel teardown is guaranteed by
``ExcelRun`` regardless of how the body exits.

Transient COM failures (Excel/DCOM briefly unavailable — common when several workers
activate Excel at once) are retried with a fresh session, because the worker's output is
idempotent. This is an internal transient retry only; a genuine job failure (missing sheet,
bad template, data error) is NOT retried and is reported as-is.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger

from reportflow.core.ipc import RunStatus, WorkerRequest, WorkerResult, write_result
from reportflow.core.logging_setup import add_run_log, remove_sink
from reportflow.worker.excel import ExcelRun, is_transient_com_error

_MAX_COM_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 2.0


@dataclass
class _Attempt:
    output_xlsx: Path | None = None
    pdf_paths: list[Path] | None = None
    excel_pid: int | None = None
    excel_pid_reaped: bool = False


def _execute_once(request: WorkerRequest, deadline: float, outcome: _Attempt) -> None:
    """Run the full Excel flow in one fresh session, mutating ``outcome``.

    ``outcome`` is caller-owned so the reaped-PID accounting survives even when this raises.
    """
    run = ExcelRun(deadline=deadline)
    try:
        with run:
            book = run.open_workbook(request.workbook_template_path, request.sheet_names)
            run.refresh_and_wait(book)
            if request.freeze_values:
                run.freeze_sheets(book, request.sheet_names)
            if request.generate_pdf and request.output_pdf_path is not None:
                outcome.pdf_paths = run.export_pdfs(
                    book, request.sheet_names, request.output_pdf_path
                )
            outcome.output_xlsx = run.save_output(book, request.output_xlsx_path)
    finally:
        outcome.excel_pid = run.excel_pid
        outcome.excel_pid_reaped = run.excel_pid_reaped


def run_job(request: WorkerRequest) -> WorkerResult:
    """Execute a single run (with transient-COM retry) and write the result file."""
    sink_id = add_run_log(request.log_path)
    started = datetime.now()

    status = RunStatus.FAILED
    message = ""
    error_detail: str | None = None
    result_attempt = _Attempt(pdf_paths=[])

    logger.info(
        "Run {} starting for job {!r} (test={})", request.run_id, request.job_name, request.is_test
    )
    try:
        for attempt in range(1, _MAX_COM_ATTEMPTS + 1):
            deadline = time.monotonic() + request.timeout_seconds
            result_attempt = _Attempt(pdf_paths=[])
            try:
                _execute_once(request, deadline, result_attempt)
                status = RunStatus.SUCCESS
                message = "completed"
                logger.info("Run {} succeeded (attempt {})", request.run_id, attempt)
                break
            except Exception as exc:  # noqa: BLE001 — classify then retry or fail
                message = str(exc)
                error_detail = traceback.format_exc()
                if is_transient_com_error(exc) and attempt < _MAX_COM_ATTEMPTS:
                    logger.warning(
                        "Run {} hit transient COM error on attempt {}/{}: {} — retrying",
                        request.run_id,
                        attempt,
                        _MAX_COM_ATTEMPTS,
                        message,
                    )
                    time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
                    continue
                logger.error("Run {} failed: {}", request.run_id, message)
                logger.debug(error_detail)
                break
    finally:
        finished = datetime.now()
        result = WorkerResult(
            run_id=request.run_id,
            status=status,
            message=message,
            output_xlsx=result_attempt.output_xlsx,
            pdf_paths=result_attempt.pdf_paths or [],
            started_at=started.isoformat(timespec="seconds"),
            finished_at=finished.isoformat(timespec="seconds"),
            duration_seconds=round((finished - started).total_seconds(), 3),
            error_detail=error_detail if status is not RunStatus.SUCCESS else None,
            excel_pid=result_attempt.excel_pid,
            excel_pid_reaped=result_attempt.excel_pid_reaped,
        )
        write_result(result, request.result_path)
        logger.info(
            "Run {} result written: status={} reaped={} -> {}",
            request.run_id,
            status,
            result_attempt.excel_pid_reaped,
            request.result_path,
        )
        remove_sink(sink_id)

    return result
