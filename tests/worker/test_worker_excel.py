"""End-to-end worker tests that drive a real Excel instance.

Marked ``excel`` so CI (which has no Excel) skips them via ``-m "not excel"``. Run locally
with ``uv run pytest -m excel``.

Every test asserts no net-new ``EXCEL.EXE`` process survives — the ghost check is the whole
point of the worker's teardown design.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import openpyxl
import psutil
import pytest

from reportflow.core.ipc import (
    RunStatus,
    SheetTask,
    WorkbookTask,
    WorkerRequest,
    read_result,
    write_request,
)
from reportflow.worker.runner import run_job

pytestmark = pytest.mark.excel


def _excel_pids() -> set[int]:
    pids: set[int] = set()
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() == "excel.exe":
                pids.add(p.pid)
        except psutil.Error:
            pass
    return pids


def _make_workbook(path: Path) -> None:
    wb = openpyxl.Workbook()
    data = wb.active
    data.title = "Data"
    for i, (u, pr) in enumerate([(120, 9.5), (80, 11.0), (200, 8.25), (150, 10.0)], start=2):
        data[f"B{i}"] = u
        data[f"C{i}"] = pr
        data[f"D{i}"] = f"=B{i}*C{i}"
    summary = wb.create_sheet("Summary")
    summary["B1"] = "=SUM(Data!B2:B5)"
    summary["B2"] = "=SUM(Data!D2:D5)"
    summary["B3"] = "=B2/B1"
    summary.print_area = "A1:B3"
    detail = wb.create_sheet("Detail")
    detail["B2"] = "=Summary!B2*2"
    detail["B3"] = "=Summary!B1+10"
    detail.print_area = "A1:B3"
    wb.save(path)


_WORKBOOK_KEYS = {"input_excel_path", "output_xlsx_path", "output_pdf_path", "unselected_sheets"}


def _request(tmp_path: Path, sheets, **over) -> WorkerRequest:
    """One-workbook request. ``sheets``: names (PDF on, visible) or SheetTask objects.
    Workbook-level keys in ``over`` go to the WorkbookTask, the rest to the request."""
    wb = tmp_path / "template.xlsx"
    if not wb.exists():
        _make_workbook(wb)
    task = dict(
        input_excel_path=wb,
        output_xlsx_path=tmp_path / "out.xlsx",
        output_pdf_path=tmp_path / "{sheet}.pdf",
        sheets=[s if isinstance(s, SheetTask) else SheetTask(name=s) for s in sheets],
    )
    task.update({k: v for k, v in over.items() if k in _WORKBOOK_KEYS})
    defaults = dict(
        run_id="r1",
        job_name="j",
        workbooks=[WorkbookTask(**task)],
        timeout_seconds=120,
        is_test=True,
        result_path=tmp_path / "result.json",
        log_path=tmp_path / "worker.log",
    )
    defaults.update({k: v for k, v in over.items() if k not in _WORKBOOK_KEYS})
    return WorkerRequest(**defaults)


def test_success_freezes_and_exports(tmp_path):
    before = _excel_pids()
    result = run_job(_request(tmp_path, ["Summary", "Detail"]))

    assert result.status is RunStatus.SUCCESS
    assert Path(result.output_xlsx_paths[0]).exists()
    assert len(result.pdf_paths) == 2
    assert all(Path(p).stat().st_size > 0 for p in result.pdf_paths)
    assert result.excel_pid_reaped is True
    assert not (_excel_pids() - before), "ghost EXCEL.EXE leaked"

    wb = openpyxl.load_workbook(result.output_xlsx_paths[0])
    assert wb["Summary"]["B1"].value == 550  # frozen to a value, not a formula
    assert "Data" not in wb.sheetnames  # unselected sheets are removed from the OUTPUT
    assert set(wb.sheetnames) == {"Summary", "Detail"}

    # Selection is collapsed: the file opens on the first selected sheet with A1 active,
    # not with the whole used range highlighted (PasteSpecial's leftover selection).
    assert wb.active.title == "Summary"
    for name in ("Summary", "Detail"):
        selection = wb[name].sheet_view.selection[0]
        assert selection.activeCell == "A1"
        assert selection.sqref == "A1"

    # The SOURCE workbook is untouched: helper sheet still there, formulas intact.
    src = openpyxl.load_workbook(tmp_path / "template.xlsx")
    assert "Data" in src.sheetnames
    assert str(src["Summary"]["B1"].value).startswith("=")


def _make_broken_workbook(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Report"
    ws["A1"] = "=THISFUNCTIONDOESNOTEXIST()"  # -> #NAME? once Excel recalculates
    ws["A2"] = 123
    ws.print_area = "A1:A2"
    wb.save(path)


def test_error_cells_deliver_by_default(tmp_path):
    """Default policy: an error cell (#NAME? here) does NOT fail the run — the report is
    delivered and the error is reported as a warning."""
    before = _excel_pids()
    wb_path = tmp_path / "broken.xlsx"
    _make_broken_workbook(wb_path)

    result = run_job(_request(tmp_path, ["Report"], input_excel_path=wb_path))

    assert result.status is RunStatus.SUCCESS
    assert Path(result.output_xlsx_paths[0]).exists()
    assert result.warnings and "#NAME?" in result.warnings[0]
    assert not (_excel_pids() - before), "ghost EXCEL.EXE leaked"


def test_error_cells_fail_in_strict_mode(tmp_path):
    """Opt-in strict mode still fails on error cells with the pointed #NAME? message."""
    before = _excel_pids()
    wb_path = tmp_path / "broken.xlsx"
    _make_broken_workbook(wb_path)

    result = run_job(
        _request(tmp_path, ["Report"], input_excel_path=wb_path, fail_if_sheet_has_errors=True)
    )

    assert result.status is RunStatus.FAILED
    assert "#NAME?" in result.message
    assert not (_excel_pids() - before)


def test_broken_defined_names_purged_so_output_opens(tmp_path):
    """Deleting a sheet referenced by a defined name would leave a #REF! name that Office
    File Validation blocks. The output must load cleanly with no broken names."""
    from openpyxl.workbook.defined_name import DefinedName

    before = _excel_pids()
    wb_path = tmp_path / "named.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Report"
    ws["A1"] = 1
    ws.print_area = "A1:A1"
    wb.create_sheet("Data")["A1"] = 99
    dn = DefinedName("LinkToData", attr_text="Data!$A$1")
    try:
        wb.defined_names.add(dn)
    except AttributeError:  # older openpyxl API
        wb.defined_names["LinkToData"] = dn
    wb.save(wb_path)

    result = run_job(_request(tmp_path, ["Report"], input_excel_path=wb_path))

    assert result.status is RunStatus.SUCCESS
    out = openpyxl.load_workbook(result.output_xlsx_paths[0])  # must not raise
    assert "Data" not in out.sheetnames
    refs = []
    try:
        refs = [str(d.value) for d in out.defined_names.values()]
    except AttributeError:
        refs = [str(out.defined_names[k].value) for k in out.defined_names]
    assert not any("#REF!" in r for r in refs), refs
    assert not (_excel_pids() - before)


def test_hide_mode_keeps_sheets_very_hidden(tmp_path):
    """In 'hide' mode the unselected sheets stay in the file but very-hidden (never breaks
    references), so the output always opens."""
    before = _excel_pids()
    result = run_job(_request(tmp_path, ["Summary"], unselected_sheets="hide"))

    assert result.status is RunStatus.SUCCESS
    out = openpyxl.load_workbook(result.output_xlsx_paths[0])
    assert "Data" in out.sheetnames  # kept, not deleted
    assert out["Data"].sheet_state == "veryHidden"
    assert not (_excel_pids() - before)


def test_missing_sheet_fails_cleanly(tmp_path):
    before = _excel_pids()
    result = run_job(_request(tmp_path, ["Summary", "DoesNotExist"]))

    assert result.status is RunStatus.FAILED
    assert "not found" in result.message.lower()
    assert result.excel_pid_reaped is True
    assert not (_excel_pids() - before)
    assert Path(tmp_path / "result.json").exists()


def test_missing_template_fails_cleanly(tmp_path):
    before = _excel_pids()
    req = _request(tmp_path, ["Summary"], input_excel_path=tmp_path / "nope.xlsx")
    result = run_job(req)

    assert result.status is RunStatus.FAILED
    assert result.excel_pid_reaped is True
    assert not (_excel_pids() - before)


def test_no_pdf_no_freeze_keeps_formulas(tmp_path):
    before = _excel_pids()
    req = _request(tmp_path, ["Summary"], output_pdf_path=None, freeze_values=False)
    result = run_job(req)

    assert result.status is RunStatus.SUCCESS
    assert result.pdf_paths == []
    assert not (_excel_pids() - before)
    wb = openpyxl.load_workbook(result.output_xlsx_paths[0])
    assert str(wb["Summary"]["B1"].value).startswith("=")  # not frozen -> still a formula


def test_per_sheet_pdf_and_hidden(tmp_path):
    """PDF and Hidden are per sheet: a hidden sheet can still get a PDF (export runs before
    hiding), and the file opens on the first VISIBLE included sheet."""
    before = _excel_pids()
    sheets = [
        SheetTask(name="Summary", pdf=False, hidden=True),
        SheetTask(name="Detail", pdf=True),
        SheetTask(name="Data", pdf=True, hidden=True),
    ]
    result = run_job(_request(tmp_path, sheets))

    assert result.status is RunStatus.SUCCESS, result.message
    assert sorted(Path(p).name for p in result.pdf_paths) == ["Data.pdf", "Detail.pdf"]
    assert all(Path(p).stat().st_size > 0 for p in result.pdf_paths)
    out = openpyxl.load_workbook(result.output_xlsx_paths[0])
    assert out["Summary"].sheet_state == "hidden"  # normal hidden: recipients can unhide
    assert out["Data"].sheet_state == "hidden"
    assert out["Detail"].sheet_state == "visible"
    assert out.active.title == "Detail"
    assert not (_excel_pids() - before)


def test_keep_mode_leaves_unincluded_sheets_visible(tmp_path):
    before = _excel_pids()
    result = run_job(_request(tmp_path, ["Summary"], unselected_sheets="keep"))

    assert result.status is RunStatus.SUCCESS
    out = openpyxl.load_workbook(result.output_xlsx_paths[0])
    assert out["Data"].sheet_state == "visible" and out["Detail"].sheet_state == "visible"
    assert not (_excel_pids() - before)


def _second_workbook(tmp_path: Path, input_path: Path) -> WorkbookTask:
    return WorkbookTask(
        input_excel_path=input_path,
        output_xlsx_path=tmp_path / "out2.xlsx",
        output_pdf_path=tmp_path / "second_{sheet}.pdf",
        sheets=[SheetTask(name="Detail")],
    )


def test_two_workbooks_build_in_one_session(tmp_path):
    before = _excel_pids()
    other = tmp_path / "other.xlsx"
    _make_workbook(other)
    req = _request(tmp_path, ["Summary"])
    req = req.model_copy(update={"workbooks": [*req.workbooks, _second_workbook(tmp_path, other)]})

    result = run_job(req)

    assert result.status is RunStatus.SUCCESS, result.message
    assert [p.name for p in result.output_xlsx_paths] == ["out.xlsx", "out2.xlsx"]
    assert all(p.exists() for p in result.output_xlsx_paths)
    assert sorted(Path(p).name for p in result.pdf_paths) == ["Summary.pdf", "second_Detail.pdf"]
    assert openpyxl.load_workbook(result.output_xlsx_paths[1]).sheetnames == ["Detail"]
    assert not (_excel_pids() - before), "ghost EXCEL.EXE leaked"


def test_failed_workbook_fails_run_or_is_skipped(tmp_path):
    """Default: one bad workbook fails the run, naming it. Partial delivery: it is skipped
    with a warning and the rest is delivered."""
    before = _excel_pids()
    req = _request(tmp_path, ["Summary"])
    missing = _second_workbook(tmp_path, tmp_path / "nope.xlsx")
    req = req.model_copy(update={"workbooks": [*req.workbooks, missing]})

    strict = run_job(req)
    assert strict.status is RunStatus.FAILED
    assert strict.message.startswith("nope.xlsx:")

    partial = run_job(req.model_copy(update={"continue_on_workbook_failure": True}))
    assert partial.status is RunStatus.SUCCESS
    assert [p.name for p in partial.output_xlsx_paths] == ["out.xlsx"]
    assert partial.failed_workbooks == ["nope.xlsx"]
    assert any("nope.xlsx" in w and "not attached" in w for w in partial.warnings)
    assert not (_excel_pids() - before)


def test_parallel_subprocesses_no_ghost(tmp_path):
    """The real concurrency model: N separate worker processes at once (COM in a frozen
    subprocess), none leaking Excel."""
    before = _excel_pids()
    env = {**os.environ, "REPORTFLOW_DATA_DIR": str(tmp_path / "_data")}

    procs = []
    for i in range(3):
        run_dir = tmp_path / f"run{i}"
        run_dir.mkdir(parents=True, exist_ok=True)
        req = _request(
            tmp_path,
            ["Summary", "Detail"],
            run_id=f"run{i}",
            output_xlsx_path=run_dir / "out.xlsx",
            output_pdf_path=run_dir / "{sheet}.pdf",
            result_path=run_dir / "result.json",
            log_path=run_dir / "worker.log",
        )
        req_path = write_request(req, run_dir / "request.json")
        procs.append(
            (
                req,
                subprocess.Popen(
                    [sys.executable, "-m", "reportflow.worker", "--request", str(req_path)],
                    env=env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                ),
            )
        )

    for req, proc in procs:
        assert proc.wait(timeout=180) == 0
        assert read_result(req.result_path).status is RunStatus.SUCCESS

    assert not (_excel_pids() - before), "ghost EXCEL.EXE leaked after parallel runs"
