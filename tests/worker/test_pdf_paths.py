"""Pure-logic tests for the worker (no Excel required)."""

from __future__ import annotations

from pathlib import Path

from reportflow.worker.excel import _pdf_path_for_sheet, _sanitize_for_filename


def test_sanitize_strips_invalid_chars():
    assert _sanitize_for_filename('a/b:c*?"<>|d') == "a_b_c_d"
    assert _sanitize_for_filename("   ") == "sheet"


def test_pdf_path_with_token():
    p = _pdf_path_for_sheet(Path(r"C:\out\{sheet}.pdf"), "Summary", single=False)
    assert p == Path(r"C:\out\Summary.pdf")


def test_pdf_path_single_sheet_no_token_uses_path_as_is():
    p = _pdf_path_for_sheet(Path(r"C:\out\report.pdf"), "Summary", single=True)
    assert p == Path(r"C:\out\report.pdf")


def test_pdf_path_multisheet_no_token_appends_sheet():
    p = _pdf_path_for_sheet(Path(r"C:\out\report.pdf"), "Detail", single=False)
    assert p == Path(r"C:\out\report_Detail.pdf")


def test_pdf_path_sanitizes_token_value():
    p = _pdf_path_for_sheet(Path(r"C:\out\{sheet}.pdf"), "Q1/Q2", single=False)
    assert p == Path(r"C:\out\Q1_Q2.pdf")
