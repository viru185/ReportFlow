"""The clipboard-free freeze (0.16), without Excel: the per-cell plan, rectangles, addresses,
and the driver against a fake sheet that behaves like Excel did in the 2026-11-24 probe —
written text is re-parsed like typing, a partial write into a legacy array is silently
ignored, errors come back from Value2 as ints."""

from __future__ import annotations

import re

import pytest

from reportflow.worker import freeze
from reportflow.worker.freeze import (
    Rect,
    address,
    always_quote,
    column_letters,
    error_code,
    freeze_sheet,
    grid,
    plan_cell,
    rectangles,
)

NA = freeze._ERROR_BASE + 2042  # what Value2 returns for #N/A
DIV0 = freeze._ERROR_BASE + 2007
SPILL = freeze._ERROR_BASE + 2045


# -- the plan --------------------------------------------------------------------------


def test_constants_and_empty_cells_are_never_written():
    assert plan_cell("abc", "abc") is None  # a text constant reports its own text
    assert plan_cell("42", 42.0) is None
    assert plan_cell("", None) is None  # empty
    assert plan_cell("=A1", None) is None  # a formula whose cell reads empty: nothing to keep


@pytest.mark.parametrize(
    ("value", "written"),
    [
        (0.1 + 0.2, 0.1 + 0.2),  # numbers (and date serials) exactly as Value2 gave them
        (46350.0, 46350.0),
        (True, True),
        (NA, "#N/A"),  # Excel turns the literal back into the error
        (DIV0, "#DIV/0!"),
        ("Pump north", "Pump north"),  # plain text: written as is, checked after
        ("Pump 2", "'Pump 2"),  # any digit: Excel could read a number or a date
        ("00123", "'00123"),
        ("1-2", "'1-2"),
        ("=x", "'=x"),  # would become a formula
        ("+1", "'+1"),
        ("-5 dB", "'-5 dB"),
        ("@sum", "'@sum"),
        ("#N/A", "'#N/A"),  # text that looks like an error stays text
        ("'quoted", "''quoted"),
        ("TRUE", "'TRUE"),
        (" false ", "' false "),
        ("", "'"),  # empty text, not a cleared cell
    ],
)
def test_formula_results_are_written_back_as_values(value, written):
    assert plan_cell("=SOMETHING()", value) == written


def test_spilled_cells_are_formula_results():
    """A spill child has no formula of its own (Formula is empty) but a value."""
    assert plan_cell("", 3.0) == 3.0
    assert plan_cell("", "x") == "x"


def test_error_codes():
    assert error_code(NA) == 2042 and error_code(SPILL) == 2045
    assert error_code(True) is None and error_code(1.0) is None and error_code(7) is None
    assert plan_cell("=X()", freeze._ERROR_BASE + 2099) == freeze._ERROR_BASE + 2099  # unknown


def test_always_quote():
    assert always_quote("") and always_quote("=1") and always_quote("#REF!")
    assert always_quote("True") and always_quote("12") and always_quote("Q3 total")
    assert not always_quote("Truck") and not always_quote("n/a")


# -- rectangles and addresses ---------------------------------------------------------


def _cells(*coords):
    return [(r, c, f"v{r},{c}", f"v{r},{c}") for r, c in coords]


def test_rectangles_merge_runs_and_stack_rows():
    planned = _cells((1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (1, 5), (2, 5), (4, 1), (4, 2))
    rects = rectangles(planned)
    shapes = sorted((r.row, r.col, r.rows, r.cols) for r in rects)
    # A1:B2 is one block; A3 breaks the run (only A); E1:E2 stacks; A4:B4 starts again.
    assert shapes == [(1, 1, 2, 2), (1, 5, 2, 1), (3, 1, 1, 1), (4, 1, 1, 2)]
    block = next(r for r in rects if (r.row, r.col) == (1, 1))
    assert block.values == [["v1,1", "v1,2"], ["v2,1", "v2,2"]]


def test_rectangles_respect_the_size_cap():
    planned = _cells(*[(r, c) for r in range(1, 11) for c in range(1, 4)])
    rects = rectangles(planned, max_cells=7)
    assert all(r.rows * r.cols <= 7 for r in rects)
    assert sum(r.rows * r.cols for r in rects) == 30
    wide = rectangles(_cells(*[(1, c) for c in range(1, 20)]), max_cells=8)
    assert [r.cols for r in wide] == [8, 8, 3]


def test_addresses():
    assert column_letters(1) == "A" and column_letters(26) == "Z" and column_letters(27) == "AA"
    assert column_letters(16384) == "XFD"
    assert address(3, 2) == "B3" and address(1, 1, 2, 28) == "A1:AB2"


def test_grid_handles_single_cells():
    assert grid(5.0, 1, 1) == [[5.0]]
    assert grid(((1, 2), (3, 4)), 2, 2) == [[1, 2], [3, 4]]


def test_needs_check_only_for_unquoted_text():
    assert Rect(1, 1, [["abc", 1.0]], [["abc", 1.0]]).needs_check
    assert not Rect(1, 1, [["'=x", True]], [["=x", True]]).needs_check


# -- the driver against a fake Excel sheet ---------------------------------------------


def _parse_like_typing(value):
    """What Excel stores when text is written through COM (the 2026-11-24 probe)."""
    if not isinstance(value, str):
        return value, None
    if value.startswith("'"):
        return value[1:], None
    if value.startswith("="):
        return 0.0, value
    if value in freeze.ERROR_LITERALS.values():
        code = next(c for c, t in freeze.ERROR_LITERALS.items() if t == value)
        return (freeze._ERROR_BASE + code if code <= 2042 else value), None
    if value.upper() in ("TRUE", "FALSE", "WAHR"):
        return value.upper() != "FALSE", None
    if re.fullmatch(r"\s*\d+(\.\d+)?\s*", value):
        return float(value), None
    if re.fullmatch(r"\d+-\d+", value):
        return 46024.0, None  # a date serial
    return value, None


def _rc(a1):
    m = re.fullmatch(r"([A-Z]+)(\d+)", a1)
    col = 0
    for ch in m.group(1):
        col = col * 26 + ord(ch) - 64
    return int(m.group(2)), col


class FakeSheet:
    """Cells: (row, col) -> [formula or None, value, array id or None]."""

    def __init__(self, name, cells, *, protected=False):
        self.Name = name
        self.cells = cells
        self.ProtectContents = protected
        self.ListObjects = []
        self.writes = 0

    def Range(self, addr):  # noqa: N802 — COM name
        first, _, last = addr.partition(":")
        r0, c0 = _rc(first)
        r1, c1 = _rc(last) if last else (r0, c0)
        return FakeRange(self, r0, c0, r1, c1)

    @property
    def UsedRange(self):  # noqa: N802
        rows = [r for r, _ in self.cells]
        cols = [c for _, c in self.cells]
        return FakeRange(self, min(rows), min(cols), max(rows), max(cols))

    def formula_cells(self):
        return [k for k, (f, _v, _a) in self.cells.items() if f is not None]


class FakeRange:
    def __init__(self, sheet, r0, c0, r1, c1):
        self.sheet, self.r0, self.c0, self.r1, self.c1 = sheet, r0, c0, r1, c1
        self.Row, self.Column = r0, c0
        self.Rows = type("N", (), {"Count": r1 - r0 + 1})()
        self.Columns = type("N", (), {"Count": c1 - c0 + 1})()

    def _keys(self):  # noqa: D401
        return [[(r, c) for c in range(self.c0, self.c1 + 1)] for r in range(self.r0, self.r1 + 1)]

    def _read(self, index):
        def one(key):
            formula, value, _array = self.sheet.cells.get(key, [None, None, None])
            if index == 1:
                return value
            if formula is None:  # a constant reports its own text; an empty cell ""
                return "" if value is None else str(value)
            return formula  # "=…", or "" for a spilled cell

        out = tuple(tuple(one(k) for k in line) for line in self._keys())
        return out[0][0] if len(out) == 1 and len(out[0]) == 1 else out

    @property
    def Formula(self):  # noqa: N802
        return self._read(0)

    @property
    def Value2(self):  # noqa: N802
        return self._read(1)

    @Value2.setter
    def Value2(self, payload):  # noqa: N802
        keys = self._keys()
        rows = payload if isinstance(payload, tuple) else ((payload,),)
        arrays = {self.sheet.cells.get(k, [None, None, None])[2] for line in keys for k in line}
        arrays.discard(None)
        for array in arrays:  # a partial write into a legacy array is silently ignored
            members = {k for k, v in self.sheet.cells.items() if v[2] == array}
            if not members <= {k for line in keys for k in line}:
                return
        self.sheet.writes += 1
        for line, values in zip(keys, rows, strict=True):
            for key, value in zip(line, values, strict=True):
                stored, formula = _parse_like_typing(value)
                self.sheet.cells[key] = [formula, stored, None]

    @property
    def HasFormula(self):  # noqa: N802
        flags = {
            self.sheet.cells.get(k, [None])[0] is not None for line in self._keys() for k in line
        }
        return None if len(flags) > 1 else flags.pop()

    def SpecialCells(self, _kind):  # noqa: N802
        found = [k for k in self.sheet.formula_cells()]
        if not found:
            raise Exception(-2146827284, "No cells were found.", None, None)  # noqa: TRY002
        return type(
            "Found",
            (),
            {"Areas": [type("A", (), {"Cells": [FakeCell(self.sheet, k) for k in found]})()]},
        )()


class FakeCell(FakeRange):
    """One cell — a Range in Excel, with Value2, HasArray and CurrentArray."""

    def __init__(self, sheet, key):
        super().__init__(sheet, *key, *key)
        self.key = key

    @property
    def HasArray(self):  # noqa: N802
        return self.sheet.cells[self.key][2] is not None

    @property
    def CurrentArray(self):  # noqa: N802
        array = self.sheet.cells[self.key][2]
        keys = [k for k, v in self.sheet.cells.items() if v[2] == array]
        rows, cols = [r for r, _ in keys], [c for _, c in keys]
        rng = FakeRange(self.sheet, min(rows), min(cols), max(rows), max(cols))
        rng.Address = (
            f"{address(min(rows), min(cols), max(rows) - min(rows) + 1, max(cols) - min(cols) + 1)}"
        )
        return rng


def _sheet():
    return FakeSheet(
        "Problem Points",
        {
            (1, 1): [None, "Tag", None],  # constants: left alone
            (1, 2): [None, "Value", None],
            (2, 1): ["=A", "Pump 2", None],
            (2, 2): ["=B", 0.25, None],
            (3, 1): ["=A", "WAHR", None],  # a localised TRUE: re-parsed → re-quoted
            (3, 2): ["=B", NA, None],
            (4, 1): ["=A", "=cmd|x", None],  # quoted up front
            (4, 2): ["=B", True, None],
            (5, 1): ["=A", 7.0, None],
            (5, 2): ["={1;2}", 1.0, "arr"],  # a legacy array B5:B6 that a block only half covers
            (6, 2): ["={1;2}", 2.0, "arr"],
        },
    )


def test_the_driver_freezes_every_formula_and_keeps_every_value():
    sheet = _sheet()
    before = {k: v[1] for k, v in sheet.cells.items()}
    report = freeze_sheet(sheet)
    assert sheet.formula_cells() == []  # nothing left as a formula
    assert {k: v[1] for k, v in sheet.cells.items()} == before  # every value the same
    # The A2:B5 block overlapped half the array, so Excel ignored all of it silently: every
    # cell was then frozen on its own and the array whole.
    assert report.requoted == 1  # "WAHR" was re-parsed and fixed
    assert report.arrays == 1 and report.left == 0 and report.warnings() == []
    assert report.frozen == 9


def test_a_sheet_without_formulas_is_not_touched():
    sheet = FakeSheet("Config", {(1, 1): [None, "x", None], (2, 1): [None, 5.0, None]})
    report = freeze_sheet(sheet)
    assert sheet.writes == 0 and report.blocks == 0


def test_newer_errors_that_cannot_be_typed_are_reported():
    sheet = FakeSheet("S", {(1, 1): [None, "head", None], (2, 1): ["=X()", SPILL, None]})
    report = freeze_sheet(sheet)
    assert report.errors_as_text == 1
    assert "frozen as text" in report.warnings()[0]


def test_reads_happen_in_chunks_and_check_the_deadline(monkeypatch):
    monkeypatch.setattr(freeze, "CHUNK_CELLS", 4)
    calls = []
    sheet = _sheet()
    freeze_sheet(sheet, check=calls.append)
    assert sum("reading" in c for c in calls) == 3  # 6 rows × 2 cols, 2 rows per chunk


def test_a_transient_com_error_is_raised_for_the_runner_to_retry():
    class Down(Exception):
        pass

    sheet = _sheet()

    def broken(*_a):
        raise Down("RPC server is unavailable")

    sheet.Range = lambda addr: type(
        "R", (), {"Formula": property(lambda s: broken()), "Value2": None}
    )()  # type: ignore[method-assign]
    with pytest.raises(Down):
        freeze_sheet(sheet, is_transient=lambda e: isinstance(e, Down))
