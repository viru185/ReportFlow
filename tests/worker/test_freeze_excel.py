"""The clipboard-free freeze against real Excel (0.16). Marked ``excel`` (skipped in CI).

The workbook is built through Excel itself — openpyxl can't make a spill, a legacy array or a
filtered table. Every cell's value (errors included), its displayed text and number format, the
hidden rows, the filter and the table must come through unchanged; no formula may be left; the
calculation mode is restored; the clipboard is never touched.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import win32clipboard
import xlwings as xw

from reportflow.worker.excel import ExcelRun

pytestmark = pytest.mark.excel

_SHEET = "Problem Points"
_XL_AUTOMATIC = -4105


def _build(path: Path, *, perf_rows: int = 0) -> None:
    app = xw.App(visible=False, add_book=False)
    try:
        app.api.DisplayAlerts = False
        book = app.books.add()
        ws = book.sheets[0]
        ws.name = _SHEET
        s = ws.api
        s.Range("A1").Value2 = "Bad / stale points"  # a constant title
        s.Range("A3:D3").Value2 = (("Tag", "Value", "Label", "Even"),)
        for r in range(4, 24):
            s.Range(f"A{r}").Value2 = f"TAG-{r:03d}"
            s.Range(f"B{r}").Formula = "=ROW()*1.5"
            s.Range(f"C{r}").Formula = '="P-"&TEXT(ROW(),"000")'
            s.Range(f"D{r}").Formula = "=MOD(ROW(),2)=0"
        table = s.ListObjects.Add(1, s.Range("A3:D23"), None, 1)
        table.Name = "Points"
        table.Range.AutoFilter(Field=4, Criteria1="TRUE")  # hides the odd rows
        s.Range("F1:G1").Merge()
        s.Range("F1").Formula = '="Report "&"X"'
        s.Range("I1").Formula2 = "=SEQUENCE(4,2)"
        s.Range("L1:M2").FormulaArray = "={1,2;3,4}"
        tricky = [
            "=1/3",
            "=DATE(2026,11,24)",
            '=""',
            "=NA()",
            "=1/0",
            '="00123"',
            '="1-2"',
            '="=x"',
            '="\'abc"',
            '="#N/A"',
            '="TRUE"',
            "=TRUE",
            '=REPT("x",400)',
            '="Pump 2"',
            '="  12  "',
        ]
        for i, formula in enumerate(tricky, start=1):
            s.Range(f"O{i}").Formula = formula
        s.Range("O1").NumberFormat = "$#,##0.00000"
        s.Range("O2").NumberFormat = "yyyy-mm-dd"
        s.Range("Q1").NumberFormat = "@"
        s.Range("Q1").Value2 = "00042"  # a text constant: never written
        if perf_rows:
            grid = s.Range(f"S1:AB{perf_rows}")
            grid.Formula = "=ROW()*COLUMN()"
        config = book.sheets.add("Config", after=ws)
        config.api.Range("A1:B2").Value2 = (("Server", "DEMO"), ("Days", 3))  # no formulas
        book.save(str(path))
        book.close()
    finally:
        app.quit()


def _snapshot(sheet) -> dict:
    used = sheet.UsedRange
    rows, cols = used.Rows.Count, used.Columns.Count
    top, left = used.Row, used.Column
    cells = {}
    for r in range(top, top + rows):
        for c in range(left, left + cols):
            cell = sheet.Cells(r, c)
            cells[(r, c)] = (cell.Value2, cell.Text, cell.NumberFormat)
    hidden = [r for r in range(top, top + rows) if sheet.Rows(r).Hidden]
    table = sheet.ListObjects(1)
    return {
        "cells": cells,
        "hidden": hidden,
        "filter": bool(table.AutoFilter.FilterMode),  # a table's filter lives on the table
        "table": table.Range.Address,
        "merge": sheet.Range("F1").MergeArea.Address,
    }


def _formula_count(sheet) -> int:
    try:
        return sheet.UsedRange.SpecialCells(-4123).Count
    except Exception:  # noqa: BLE001 — "No cells were found"
        return 0


def _set_clipboard(text: str) -> None:
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text)
    finally:
        win32clipboard.CloseClipboard()


def _clipboard() -> str:
    win32clipboard.OpenClipboard()
    try:
        return win32clipboard.GetClipboardData()
    finally:
        win32clipboard.CloseClipboard()


def _freeze_and_measure(path: Path, sheets: list[str], *, size: bool = False) -> dict:
    """Open, snapshot, freeze, snapshot — returning plain data only. Assertions run after
    the Excel session has ended: a failing assert inside it would keep COM proxies alive in
    the traceback past CoUninitialize, and break the next test with RPC faults."""
    with ExcelRun() as run:
        book = run.open_workbook(path, sheets)
        sheet = book.sheets[_SHEET].api
        out: dict = {"formulas_before": _formula_count(sheet)}
        if not size:
            out["before"] = _snapshot(sheet)
        started = time.monotonic()
        out["warnings"] = run.freeze_sheets(book, sheets)
        out["seconds"] = time.monotonic() - started
        out["formulas_after"] = _formula_count(sheet)
        out["calculation"] = run.app.api.Calculation
        if size:
            out["corner"] = sheet.Range("AB20000").Value2
        else:
            out["after"] = _snapshot(sheet)
        del sheet
        run.close_book(book)
        del book
    return out


def test_freeze_keeps_every_value_and_never_touches_the_clipboard(tmp_path):
    path = tmp_path / "points.xlsx"
    _build(path)
    _set_clipboard("reportflow-sentinel")
    result = _freeze_and_measure(path, [_SHEET, "Config"])
    before, after = result["before"], result["after"]
    assert result["formulas_before"] > 0 and before["filter"] and before["hidden"]
    assert result["formulas_after"] == 0  # every formula is now a value
    assert result["calculation"] == _XL_AUTOMATIC  # restored
    changed = {
        k: (before["cells"][k], after["cells"].get(k))
        for k in before["cells"]
        if before["cells"][k] != after["cells"].get(k)
    }
    assert changed == {}  # values (errors included), displayed text, number formats
    assert {k: v for k, v in before.items() if k != "cells"} == {
        k: v for k, v in after.items() if k != "cells"
    }  # hidden rows, the filter, the table, the merged header
    assert result["warnings"] == []
    assert _clipboard() == "reportflow-sentinel"


def test_freeze_is_fast_on_a_large_formula_grid(tmp_path):
    path = tmp_path / "big.xlsx"
    _build(path, perf_rows=20_000)  # 200,000 formula cells next to the tricky ones
    result = _freeze_and_measure(path, [_SHEET], size=True)
    print(f"froze 200k cells in {result['seconds']:.1f}s")
    assert result["formulas_after"] == 0
    assert result["corner"] == 20_000 * 28
    assert result["seconds"] < 60
