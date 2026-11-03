"""Failures must never deliver sheets/formats the user excluded."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from reportflow.core.ipc import SheetTask, WorkbookTask, WorkerRequest
from reportflow.worker.excel import ExcelJobError, ExcelRun
from reportflow.worker.runner import _build_workbook, _validate_output_paths


def _request(tmp_path, **over):
    task = WorkbookTask(
        input_excel_path=tmp_path / "source.xlsx",
        output_xlsx_path=tmp_path / "report.xlsx",
        output_pdf_path=tmp_path / "{sheet}.pdf",
        sheets=[SheetTask(name="Report", pdf=False)],
    )
    values = dict(
        run_id="r",
        job_name="j",
        workbooks=[task],
        timeout_seconds=60,
        result_path=tmp_path / "result.json",
        log_path=tmp_path / "worker.log",
    )
    values.update(over)
    return WorkerRequest(**values)


def test_required_pi_fails_before_using_pasted_or_cached_workbook(tmp_path):
    request = _request(tmp_path, require_pi_datalink=True, fail_if_sheet_has_errors=False)
    run = Mock(spec=ExcelRun)
    run.pi_datalink_connected = False
    with pytest.raises(ExcelJobError, match="Cached or pasted values do not prove a refresh"):
        _build_workbook(run, request, request.workbooks[0])
    run.open_workbook.assert_not_called()


def test_failed_sheet_removal_cannot_produce_an_excel_email_attachment(tmp_path):
    request = _request(tmp_path)
    task = request.workbooks[0]
    run = Mock(spec=ExcelRun)
    run.open_workbook.return_value = SimpleNamespace(
        sheets=[SimpleNamespace(name="Report"), SimpleNamespace(name="Private data")]
    )
    run.scan_error_cells.return_value = {}
    run.settle_warnings = []
    run.save_output.return_value = task.output_xlsx_path
    with pytest.raises(ExcelJobError, match="sheet selection failed"):
        _build_workbook(run, request, task)
    # Only the local report was saved; failure prevents returning a delivery manifest.
    assert run.save_output.call_count == 1
    run.close_book.assert_called_once()


def test_output_cannot_overwrite_another_input(tmp_path):
    request = _request(tmp_path)
    other = request.workbooks[0].model_copy(
        update={
            "input_excel_path": request.workbooks[0].output_xlsx_path,
            "output_xlsx_path": tmp_path / "other.xlsx",
        }
    )
    request.workbooks.append(other)
    with pytest.raises(ExcelJobError, match="refusing to overwrite"):
        _validate_output_paths(request)


def test_sanitized_pdf_name_collisions_are_rejected_before_output(tmp_path):
    request = _request(tmp_path)
    request.workbooks[0].sheets = [SheetTask(name="A<B"), SheetTask(name="A>B")]
    with pytest.raises(ExcelJobError, match="same path"):
        _validate_output_paths(request)
    assert not list(Path(tmp_path).glob("*.pdf"))


def test_combined_pdf_keeps_distinct_sheets_with_same_sanitized_name(tmp_path):
    from pypdf import PdfReader, PdfWriter

    request = _request(tmp_path)
    task = request.workbooks[0]
    task.pdf_mode = "combined"
    task.sheets = [SheetTask(name="A<B", excel=False), SheetTask(name="A>B", excel=False)]
    run = Mock(spec=ExcelRun)
    run.open_workbook.return_value = SimpleNamespace(sheets=[])
    run.scan_error_cells.return_value = {}
    run.settle_warnings = []
    run.save_output.return_value = task.output_xlsx_path

    def export(book, names, output):
        with PdfWriter() as writer:
            writer.add_blank_page(width=100 if names[0] == "A<B" else 200, height=300)
            writer.write(output)
        return [output]

    run.export_pdfs.side_effect = export
    _, pdfs, attachments, _ = _build_workbook(run, request, task)
    assert attachments == pdfs
    assert [float(page.mediabox.width) for page in PdfReader(pdfs[0]).pages] == [100, 200]
