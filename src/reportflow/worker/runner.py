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
import tempfile
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
from reportflow.worker.diagnostics import VstoDiagnostics, windows_identity
from reportflow.worker.excel import (
    ExcelJobError,
    ExcelRun,
    _pdf_path_for_sheet,
    format_error_cell_message,
    format_error_cell_warnings,
    is_transient_com_error,
)
from reportflow.worker.pdf import merge_pdfs

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
    attachment_paths: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failed_workbooks: list[str] = field(default_factory=list)
    excel_pid: int | None = None
    excel_pid_reaped: bool = False


def _email_xlsx_path(task: WorkbookTask) -> Path:
    return task.output_xlsx_path.with_name(f"{task.output_xlsx_path.stem}_email.xlsx")


def _validate_output_paths(request: WorkerRequest) -> None:
    """Reject collisions before any workbook is opened or any artifact is overwritten."""
    sources = {str(t.input_excel_path.resolve()).casefold() for t in request.workbooks}
    seen: set[str] = set()
    for task in request.workbooks:
        targets = [task.output_xlsx_path]
        if any(s.excel for s in task.sheets):
            targets.append(_email_xlsx_path(task))
        pdf_sheets = [s.name for s in task.sheets if s.pdf]
        if pdf_sheets and task.output_pdf_path is not None:
            if task.pdf_mode == "combined":
                targets.append(task.output_xlsx_path.with_suffix(".pdf"))
            else:
                targets.extend(
                    _pdf_path_for_sheet(task.output_pdf_path, name, single=len(pdf_sheets) == 1)
                    for name in pdf_sheets
                )
        for path in targets:
            key = str(path.resolve()).casefold()
            if key in sources:
                raise ExcelJobError(
                    f"output path equals an input workbook ({path}) — refusing to "
                    "overwrite the source file"
                )
            if key in seen:
                raise ExcelJobError(
                    f"output files have the same path: {path}; choose distinct output names"
                )
            seen.add(key)


def _build_workbook(
    run: ExcelRun, request: WorkerRequest, task: WorkbookTask
) -> tuple[Path, list[Path], list[Path], list[str]]:
    """Build local Excel, chosen PDFs, and an exact-sheet Excel email copy."""
    names = task.sheet_names
    if request.require_pi_datalink and not run.pi_datalink_connected:
        raise ExcelJobError(
            f"PI DataLink is required but did not connect under {windows_identity()}. "
            "Cached or pasted values do not prove a refresh. See this run's pi_diagnostics "
            "folder in Export logs for the VSTO installation/activation error."
        )
    book = run.open_workbook(task.input_excel_path, names)
    try:
        run.refresh_and_wait(book, names, request.post_refresh_wait_seconds)
        findings = run.scan_error_cells(book, names)
        if findings and request.fail_if_sheet_has_errors:
            raise ExcelJobError(format_error_cell_message(findings, run.failed_addins, _account()))
        warnings = [*run.settle_warnings]
        if findings:
            warnings.extend(format_error_cell_warnings(findings))
        if request.freeze_values:
            run.freeze_sheets(book, names)
        if request.fail_if_sheet_empty:
            run.validate_sheets_not_empty(book, names)
        pdf_paths: list[Path] = []
        pdf_sheets = [s.name for s in task.sheets if s.pdf]
        if pdf_sheets and task.output_pdf_path is not None:
            # Export while all dependencies still exist and included sheets are visible.
            if task.pdf_mode == "combined":
                with tempfile.TemporaryDirectory(
                    prefix="pdf-", dir=request.result_path.parent
                ) as tmp:
                    # Numbered intermediates also distinguish legal sheet names whose
                    # filename-safe forms collide (e.g. A<B and A>B).
                    intermediate = []
                    for index, name in enumerate(pdf_sheets):
                        intermediate.extend(
                            run.export_pdfs(book, [name], Path(tmp) / f"{index}.pdf")
                        )
                    combined = task.output_xlsx_path.with_suffix(".pdf")
                    merge_pdfs(intermediate, combined, check_deadline=run._check_deadline)
                    pdf_paths = [combined]
            else:
                pdf_paths = run.export_pdfs(book, pdf_sheets, task.output_pdf_path)
        if task.unselected_sheets != "keep":
            run.drop_unselected_sheets(book, names, mode=task.unselected_sheets)
        # Hidden is relevant only to Excel-selected sheets; PDF-only/local-only sheets
        # stay visible so an entirely PDF-only run still saves an inspectable workbook.
        visible = [s.name for s in task.sheets if not (s.excel and s.hidden)]
        run.collapse_selection(book, visible)
        hidden = [s.name for s in task.sheets if s.excel and s.hidden]
        if hidden:
            run.hide_sheets(book, hidden)
        output = run.save_output(book, task.output_xlsx_path)
        attachments: list[Path] = []
        excel_names = [s.name for s in task.sheets if s.excel]
        if excel_names:
            run.drop_unselected_sheets(book, excel_names, mode="remove")
            actual = [sheet.name for sheet in book.sheets]
            if set(actual) != set(excel_names):
                raise ExcelJobError(
                    f"Excel attachment sheet selection failed: expected {excel_names}, got {actual}"
                )
            run.collapse_selection(book, [s.name for s in task.sheets if s.excel and not s.hidden])
            attachments.append(run.save_output(book, _email_xlsx_path(task)))
        attachments.extend(pdf_paths)
    finally:
        run.close_book(book)
        del book
    return output, pdf_paths, attachments, warnings


def _execute_once(
    request: WorkerRequest, deadline: float, outcome: _Attempt, diagnostics: VstoDiagnostics
) -> None:
    """Run every workbook in one fresh Excel session, mutating ``outcome``.

    ``outcome`` is caller-owned so the reaped-PID accounting survives even when this raises.
    """
    run = ExcelRun(deadline=deadline, diagnostics=diagnostics)
    multi = len(request.workbooks) > 1
    try:
        with run:
            outcome.warnings.extend(
                f"add-in {name!r} did not connect — automatic data refresh may be unavailable; "
                "see pi_diagnostics in Export logs"
                for name in run.failed_addins
            )
            for task in request.workbooks:
                label = task.input_excel_path.name
                try:
                    output, pdfs, attachments, warnings = _build_workbook(run, request, task)
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
                outcome.attachment_paths.extend(attachments)
                # With several workbooks, say which one a sheet warning belongs to.
                outcome.warnings.extend(f"{label}: {w}" if multi else w for w in warnings)
        if not outcome.output_xlsx_paths:
            raise ExcelJobError("every workbook failed: " + "; ".join(outcome.warnings))
        if request.blank_out_values:
            for output in [
                *outcome.output_xlsx_paths,
                *(p for p in outcome.attachment_paths if p.suffix.lower() == ".xlsx"),
            ]:
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
    logger.info("Executing as {}", windows_identity())
    if _is_machine_account():
        logger.warning(
            "Running as the machine account ({}). VSTO add-ins such as PI DataLink cannot "
            "load in this context, so their cells will be #NAME?. Configure the ReportFlow "
            "service to log on as a user with the add-in installed and data access "
            "(scripts/set-service-account.ps1 or the installer's service-account page).",
            _account(),
        )
    diagnostics = VstoDiagnostics(request.result_path.parent)
    diagnostics.start()
    try:
        try:
            _validate_output_paths(request)
        except ExcelJobError as exc:
            message = str(exc)
            error_detail = traceback.format_exc()
            logger.error("Run {} failed: {}", request.run_id, message)
        for attempt in range(1, _MAX_COM_ATTEMPTS + 1) if not message else ():
            deadline = time.monotonic() + request.timeout_seconds
            result_attempt = _Attempt()
            try:
                _execute_once(request, deadline, result_attempt, diagnostics)
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
        diagnostics.finish()
        finished = datetime.now()
        result = WorkerResult(
            run_id=request.run_id,
            status=status,
            message=message,
            output_xlsx_paths=result_attempt.output_xlsx_paths,
            pdf_paths=result_attempt.pdf_paths,
            attachment_paths=result_attempt.attachment_paths,
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
