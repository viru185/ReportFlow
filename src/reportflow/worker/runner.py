"""Orchestrate one job run: WorkerRequest -> Excel automation -> WorkerResult.

The runner ALWAYS produces a ``result.json`` (success or failure) and never lets an
exception escape without first recording it. The Excel teardown is guaranteed by
``ExcelRun`` regardless of how the body exits.

A job may have several workbooks: they are built one after another in the same Excel
session. A genuine failure of one either fails the run (default) or, when the job allows
partial delivery, is skipped with a warning.

Transient COM failures (Excel/DCOM briefly unavailable — common when several workers
activate Excel at once) are retried with a fresh session, because the worker's output is
idempotent. This is an internal transient retry only; a genuine job failure (missing sheet,
bad template, data error) is NOT retried and is reported as-is.
"""

from __future__ import annotations

import os
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from loguru import logger

from reportflow.core.ipc import (
    RunStatus,
    WorkbookTask,
    WorkerRequest,
    WorkerResult,
    write_result,
)
from reportflow.core.logging_setup import add_run_log, remove_sink
from reportflow.worker.cleanup import blank_out_values
from reportflow.worker.excel import (
    ExcelJobError,
    ExcelRun,
    format_error_cell_message,
    format_error_cell_warnings,
    is_transient_com_error,
)

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
    output_xlsx_paths: list[Path] = field(default_factory=list)
    pdf_paths: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failed_workbooks: list[str] = field(default_factory=list)
    excel_pid: int | None = None
    excel_pid_reaped: bool = False


def _build_workbook(
    run: ExcelRun, request: WorkerRequest, task: WorkbookTask
) -> tuple[Path, list[Path], list[str]]:
    """Open -> refresh -> check -> freeze -> PDFs -> tidy -> save one workbook.

    Returns ``(output_xlsx, pdf_paths, warnings)``. Raises on a failure of this workbook.
    """
    names = task.sheet_names
    book = run.open_workbook(task.input_excel_path, names)
    try:
        run.refresh_and_wait(book, names, request.post_refresh_wait_seconds)
        # Scan BEFORE freeze, while add-in formulas are still present. By default we
        # DELIVER the report and just warn about error cells; strict mode fails instead.
        # #NAME? still gets the pointed add-in/account hint in the strict message.
        findings = run.scan_error_cells(book, names)
        if findings and request.fail_if_sheet_has_errors:
            raise ExcelJobError(format_error_cell_message(findings, run.failed_addins, _account()))
        warnings = [*run.settle_warnings]  # e.g. a sheet still below its opening baseline
        if findings:
            warnings.extend(format_error_cell_warnings(findings))
        if request.freeze_values:
            run.freeze_sheets(book, names)
        if request.fail_if_sheet_empty:
            run.validate_sheets_not_empty(book, names)
        if task.unselected_sheets != "keep":
            run.drop_unselected_sheets(book, names, mode=task.unselected_sheets)
        pdf_paths: list[Path] = []
        pdf_sheets = [s.name for s in task.sheets if s.pdf]
        if pdf_sheets and task.output_pdf_path is not None:
            # Before hide_sheets: Excel cannot export a hidden sheet.
            pdf_paths = run.export_pdfs(book, pdf_sheets, task.output_pdf_path)
        # Leave the file tidy: A1 selected everywhere, first visible sheet active
        # (PasteSpecial's whole-range selection would otherwise persist into the file).
        run.collapse_selection(book, [s.name for s in task.sheets if not s.hidden])
        hidden = [s.name for s in task.sheets if s.hidden]
        if hidden:
            run.hide_sheets(book, hidden)
        output = run.save_output(book, task.output_xlsx_path)
    finally:
        run.close_book(book)
    return output, pdf_paths, warnings


def _execute_once(request: WorkerRequest, deadline: float, outcome: _Attempt) -> None:
    """Run every workbook in one fresh Excel session, mutating ``outcome``.

    ``outcome`` is caller-owned so the reaped-PID accounting survives even when this raises.
    """
    run = ExcelRun(deadline=deadline)
    multi = len(request.workbooks) > 1
    try:
        with run:
            for task in request.workbooks:
                label = task.input_excel_path.name
                try:
                    output, pdfs, warnings = _build_workbook(run, request, task)
                except Exception as exc:
                    # Transient COM trouble retries the whole session (outputs are
                    # idempotent); only a genuine failure of THIS workbook may be skipped.
                    if is_transient_com_error(exc):
                        raise
                    if not request.continue_on_workbook_failure:
                        if multi:  # name the workbook so the run history is actionable
                            raise ExcelJobError(f"{label}: {exc}") from exc
                        raise
                    logger.error("Workbook {} failed, continuing with the rest: {}", label, exc)
                    outcome.failed_workbooks.append(label)
                    outcome.warnings.append(f"workbook {label!r} failed — not attached: {exc}")
                    continue
                outcome.output_xlsx_paths.append(output)
                outcome.pdf_paths.extend(pdfs)
                # With several workbooks, say which one a sheet warning belongs to.
                outcome.warnings.extend(f"{label}: {w}" if multi else w for w in warnings)
        if not outcome.output_xlsx_paths:
            raise ExcelJobError("every workbook failed: " + "; ".join(outcome.warnings))
        if request.blank_out_values:
            for output in outcome.output_xlsx_paths:
                blank_out_values(output, request.blank_out_values)
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
    result_attempt = _Attempt()

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
            result_attempt = _Attempt()
            try:
                _execute_once(request, deadline, result_attempt)
                status = RunStatus.SUCCESS
                warns = result_attempt.warnings
                message = f"completed with {len(warns)} warning(s)" if warns else "completed"
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
            output_xlsx_paths=result_attempt.output_xlsx_paths,
            pdf_paths=result_attempt.pdf_paths,
            warnings=result_attempt.warnings,
            failed_workbooks=result_attempt.failed_workbooks,
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
