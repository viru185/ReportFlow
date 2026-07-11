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

import os
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger

from reportflow.core.ipc import RunStatus, WorkerRequest, WorkerResult, write_result
from reportflow.core.logging_setup import add_run_log, remove_sink
from reportflow.worker.cleanup import blank_out_values
from reportflow.worker.excel import ExcelRun, is_transient_com_error

_MAX_COM_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 2.0


def _account() -> str:
    """The Windows identity Excel runs under (PI & friends key data access off this)."""
    return f"{os.environ.get('USERDOMAIN', '?')}\\{os.environ.get('USERNAME', '?')}"


def _is_machine_account() -> bool:
    """True when running as the machine account (LocalSystem shows as ``COMPUTERNAME$``).

    VSTO add-ins such as PI DataLink cannot activate in that context (no user profile /
    VSTO cache / integrated-auth identity), so their worksheet functions come out ``#NAME?``.
    """
    return os.environ.get("USERNAME", "").endswith("$")


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
            book = run.open_workbook(request.input_excel_path, request.sheet_names)
            run.refresh_and_wait(book, request.post_refresh_wait_seconds)
            # Scan BEFORE freeze, while add-in formulas are still present: #NAME? here means
            # the add-in (e.g. PI DataLink) never loaded and the report would ship broken.
            if request.fail_if_sheet_has_errors:
                run.validate_sheets_data(book, request.sheet_names, account=_account())
            if request.freeze_values:
                run.freeze_sheets(book, request.sheet_names)
            if request.fail_if_sheet_empty:
                run.validate_sheets_not_empty(book, request.sheet_names)
            if request.keep_only_selected_sheets:
                run.delete_unselected_sheets(book, request.sheet_names)
            if request.generate_pdf and request.output_pdf_path is not None:
                outcome.pdf_paths = run.export_pdfs(
                    book, request.sheet_names, request.output_pdf_path
                )
            outcome.output_xlsx = run.save_output(book, request.output_xlsx_path)
        if outcome.output_xlsx is not None and request.blank_out_values:
            blank_out_values(outcome.output_xlsx, request.blank_out_values)
    finally:
        outcome.excel_pid = run.excel_pid
        outcome.excel_pid_reaped = run.excel_pid_reaped


def run_job(request: WorkerRequest) -> WorkerResult:
    """Execute a single run (with transient-COM retry) and write the result file."""
    sink_id = add_run_log(request.log_path, level="DEBUG" if request.debug else "INFO")
    started = datetime.now()

    status = RunStatus.FAILED
    message = ""
    error_detail: str | None = None
    result_attempt = _Attempt(pdf_paths=[])

    logger.info(
        "Run {} starting for job {!r} (test={})", request.run_id, request.job_name, request.is_test
    )
    # PI & friends use Windows-integrated security: WHO ran Excel decides data access.
    logger.info("Executing as {}", _account())
    if _is_machine_account():
        logger.warning(
            "Running as the machine account ({}). VSTO add-ins such as PI DataLink cannot "
            "load in this context, so their cells will be #NAME?. Configure the ReportFlow "
            "service to log on as a user with the add-in installed and data access "
            "(scripts/set-service-account.ps1 or the installer's service-account page).",
            _account(),
        )
    try:
        for attempt in range(1, _MAX_COM_ATTEMPTS + 1):
            deadline = time.monotonic() + request.timeout_seconds
            result_attempt = _Attempt(pdf_paths=[])
            try:
                _execute_once(request, deadline, result_attempt)
                status = RunStatus.SUCCESS
                message = (
                    "completed — no error cells; live data present"
                    if request.fail_if_sheet_has_errors
                    else "completed"
                )
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
