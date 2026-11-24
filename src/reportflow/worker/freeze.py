"""Freeze formulas to values WITHOUT the clipboard (0.16).

The old freeze was ``UsedRange.Copy()`` → ``PasteSpecial(xlPasteValues)``, which goes through
the Windows clipboard. Under a service (session 0) Office's clipboard use is unsupported, and
every run of every job shares that one clipboard: the 2026-11-24 server hangs all sat in that
call, and two jobs freezing at once could paste each other's data.

How it works, per selected sheet:

1. A sheet without formulas is left alone (``UsedRange.HasFormula is False``).
2. Read the whole used range first, in row chunks (bulk ``Formula`` + ``Value2``): replacing a
   spilled formula's anchor clears its children, so nothing may be written before all is read.
3. Plan each cell (:func:`plan_cell`). Constants and empty cells are never written. A formula
   result goes back as a value: numbers and booleans as they are (``Value2`` keeps dates and
   currency exact; number formats are untouched), errors as their literal (``#DIV/0!`` — Excel
   turns the text back into the error), text as it is — except text Excel would re-read when
   written: anything with a digit ("00123" → 123, "1-2" → a date AND a date number format on the
   cell), starting with ``= + - @ ' #``, or reading TRUE/FALSE. That text is written with a
   leading apostrophe — Excel's own "this is text" mark.
4. Write rectangles of planned cells (:func:`rectangles`), one ``Value2`` call each.
5. Read back the text written without an apostrophe (a safety net, e.g. a localised TRUE
   such as WAHR) and rewrite any cell Excel changed with the apostrophe.
6. Anything still a formula — a legacy array formula ignores a partial write without an error —
   is frozen as a whole array; what still refuses stays a formula and is reported.

Filtered/hidden rows don't matter (reads and writes ignore visibility), so a filter and its
hidden rows stay exactly as they were. The only visible difference from PasteSpecial: a
quoted text cell shows the apostrophe in the formula bar (Excel's quotePrefix).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

# Value2 of an error cell is this base plus the error's code (0x800A0000 as a signed int).
_ERROR_BASE = -2146828288
ERROR_LITERALS: dict[int, str] = {
    2000: "#NULL!",
    2007: "#DIV/0!",
    2015: "#VALUE!",
    2023: "#REF!",
    2029: "#NAME?",
    2036: "#NUM!",
    2042: "#N/A",
    2043: "#GETTING_DATA",
    2045: "#SPILL!",
    2046: "#CONNECT!",
    2047: "#BLOCKED!",
    2048: "#UNKNOWN!",
    2049: "#FIELD!",
    2050: "#CALC!",
}
_ALWAYS_QUOTE_FIRST = frozenset("=+-@'#")
CHUNK_CELLS = 20_000  # cells per bulk read
MAX_RECT_CELLS = 20_000  # cells per bulk write
_XL_CELLTYPE_FORMULAS = -4123
_NO_CELLS_FOUND = -2146827284  # SpecialCells matched nothing


def error_code(value: object) -> int | None:
    """The Excel error code (2007 = #DIV/0!) of a ``Value2`` error, else None."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    code = value - _ERROR_BASE
    return code if 2000 <= code < 2100 else None


def quoted(text: str) -> str:
    return "'" + text


def always_quote(text: str) -> bool:
    """Text Excel could turn into something else when written — a number, a date (which also
    puts a date format on the cell: found by the real-Excel test), a formula, a boolean, an
    error — or empty text, which unquoted would clear the cell."""
    return (
        text == ""
        or text[0] in _ALWAYS_QUOTE_FIRST
        or any(ch.isdigit() for ch in text)
        or text.strip().upper() in ("TRUE", "FALSE")
    )


def is_formula_result(formula: object, value: object) -> bool:
    """True for a cell whose value comes from a formula: its own (``=…``), a spilled array's
    (no formula of its own — ``Formula`` is empty — but a value), or a legacy array's.
    A constant reports its own text as ``Formula``; an empty cell has no value."""
    if value is None:
        return False
    text = formula if isinstance(formula, str) else ""
    return text == "" or text.startswith("=")


def plan_cell(formula: object, value: object) -> object | None:
    """What to write over a cell to freeze it, or None to leave it alone."""
    if not is_formula_result(formula, value):
        return None
    if isinstance(value, bool | float):
        return value
    code = error_code(value)
    if code is not None:
        return ERROR_LITERALS.get(code, value)
    if isinstance(value, int):  # never seen from Value2, but harmless
        return value
    if isinstance(value, str):
        return quoted(value) if always_quote(value) else value
    return value  # anything else Excel handed us goes back as it came


@dataclass
class Rect:
    """A block of planned cells written with one call. ``values`` row-major."""

    row: int
    col: int
    values: list[list[object]] = field(default_factory=list)
    originals: list[list[object]] = field(default_factory=list)

    @property
    def rows(self) -> int:
        return len(self.values)

    @property
    def cols(self) -> int:
        return len(self.values[0]) if self.values else 0

    @property
    def needs_check(self) -> bool:
        """Holds text written unquoted (Excel may re-parse it) or an error literal."""
        return any(
            isinstance(w, str) and not w.startswith("'") for line in self.values for w in line
        )


def rectangles(
    planned: Sequence[tuple[int, int, object, object]], *, max_cells: int = MAX_RECT_CELLS
) -> list[Rect]:
    """Group planned cells ``(row, col, write, original)`` — any order — into rectangles:
    runs of adjacent columns per row, stacked while the next row has the same run."""
    by_row: dict[int, dict[int, tuple[object, object]]] = {}
    for row, col, write, original in planned:
        by_row.setdefault(row, {})[col] = (write, original)
    out: list[Rect] = []
    open_rects: dict[tuple[int, int], Rect] = {}  # (first col, width) -> rect ending last row
    previous_row: int | None = None
    for row in sorted(by_row):
        cells = by_row[row]
        runs: list[tuple[int, int]] = []
        for col in sorted(cells):
            if runs and col == runs[-1][0] + runs[-1][1]:
                runs[-1] = (runs[-1][0], runs[-1][1] + 1)
            else:
                runs.append((col, 1))
        still_open: dict[tuple[int, int], Rect] = {}
        for first, width in runs:
            # A very wide run is cut so no single write exceeds the cap.
            step = max(1, min(width, max_cells))
            for start in range(first, first + width, step):
                span = min(step, first + width - start)
                key = (start, span)
                line_values = [cells[c][0] for c in range(start, start + span)]
                line_originals = [cells[c][1] for c in range(start, start + span)]
                rect = open_rects.get(key) if previous_row == row - 1 else None
                if rect is not None and (rect.rows + 1) * span <= max_cells:
                    rect.values.append(line_values)
                    rect.originals.append(line_originals)
                else:
                    rect = Rect(row, start, [line_values], [line_originals])
                    out.append(rect)
                still_open[key] = rect
        open_rects = still_open
        previous_row = row
    return out


def column_letters(col: int) -> str:
    """1 → A, 27 → AA, 16384 → XFD."""
    letters = ""
    while col:
        col, rem = divmod(col - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def address(row: int, col: int, rows: int = 1, cols: int = 1) -> str:
    first = f"{column_letters(col)}{row}"
    if rows == 1 and cols == 1:
        return first
    return f"{first}:{column_letters(col + cols - 1)}{row + rows - 1}"


def grid(data: object, rows: int, cols: int) -> list[list[object]]:
    """COM returns a scalar for one cell, else a tuple of row tuples."""
    if rows == 1 and cols == 1 and not isinstance(data, tuple):
        return [[data]]
    return [list(line) for line in data]  # type: ignore[attr-defined]


def _payload(values: list[list[object]]) -> object:
    if len(values) == 1 and len(values[0]) == 1:
        return values[0][0]
    return tuple(tuple(line) for line in values)


@dataclass
class FreezeReport:
    sheet: str
    frozen: int = 0  # formula cells now values
    blocks: int = 0
    requoted: int = 0  # text Excel re-parsed, rewritten with an apostrophe
    arrays: int = 0  # legacy array formulas frozen whole
    left: int = 0  # cells that still hold a formula
    errors_as_text: int = 0  # newer errors Excel can't take as a literal
    resized_tables: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def warnings(self) -> list[str]:
        out: list[str] = []
        if self.left:
            out.append(
                f"sheet {self.sheet!r}: {self.left} cell(s) could not be frozen (data table or "
                "array formula) — they still contain formulas"
            )
        if self.errors_as_text:
            out.append(
                f"sheet {self.sheet!r}: {self.errors_as_text} error cell(s) such as #SPILL! were "
                "frozen as text"
            )
        return out


def freeze_sheet(
    sheet: Any,
    *,
    check: Callable[[str], None] = lambda _what: None,
    is_transient: Callable[[BaseException], bool] = lambda _e: False,
) -> FreezeReport:
    """Freeze one worksheet (its COM object). ``check`` is called between bulk steps (the
    run's deadline); a transient COM error is re-raised so the runner retries the session."""
    started = time.monotonic()
    report = FreezeReport(str(sheet.Name))
    used = sheet.UsedRange
    if used.HasFormula is False:  # None means "some cells"
        return report
    tables = [(lo, str(lo.Range.Address)) for lo in sheet.ListObjects]
    top, left = int(used.Row), int(used.Column)
    nrows, ncols = int(used.Rows.Count), int(used.Columns.Count)
    chunk_rows = max(1, CHUNK_CELLS // max(ncols, 1))

    planned: list[tuple[int, int, object, object]] = []
    for offset in range(0, nrows, chunk_rows):
        check(f"freezing sheet {report.sheet} (reading)")
        count = min(chunk_rows, nrows - offset)
        block = sheet.Range(address(top + offset, left, count, ncols))
        formulas = grid(block.Formula, count, ncols)
        values = grid(block.Value2, count, ncols)
        for i in range(count):
            for j in range(ncols):
                write = plan_cell(formulas[i][j], values[i][j])
                if write is not None:
                    planned.append((top + offset + i, left + j, write, values[i][j]))

    rects = rectangles(planned)
    report.blocks = len(rects)
    for index, rect in enumerate(rects):
        if index % 50 == 0:
            check(f"freezing sheet {report.sheet} (writing)")
        _write_rect(sheet, rect, is_transient)
    for rect in rects:
        if rect.needs_check:
            report.requoted += _recheck(sheet, rect, report, is_transient)
    _finish_leftovers(sheet, report, is_transient)
    report.frozen = len(planned) - report.left
    for lo, before in tables:
        try:
            if str(lo.Range.Address) != before:
                lo.Resize(sheet.Range(before))
                report.resized_tables.append(str(lo.Name))
        except Exception as e:  # noqa: BLE001 — cosmetic: the values are already frozen
            logger.debug("Could not restore table range on {!r}: {}", report.sheet, e)
    report.seconds = time.monotonic() - started
    return report


def _write_rect(sheet: Any, rect: Rect, is_transient: Callable[[BaseException], bool]) -> None:
    """One bulk write; on a refusal, row by row, then cell by cell (a refused cell is left
    for :func:`_finish_arrays`)."""
    try:
        sheet.Range(address(rect.row, rect.col, rect.rows, rect.cols)).Value2 = _payload(
            rect.values
        )
        return
    except Exception as e:  # noqa: BLE001
        if is_transient(e):
            raise
    for i, line in enumerate(rect.values):
        try:
            sheet.Range(address(rect.row + i, rect.col, 1, len(line))).Value2 = _payload([line])
            continue
        except Exception as e:  # noqa: BLE001
            if is_transient(e):
                raise
        for j, value in enumerate(line):
            try:
                sheet.Range(address(rect.row + i, rect.col + j)).Value2 = value
            except Exception as e:  # noqa: BLE001
                if is_transient(e):
                    raise


def _recheck(
    sheet: Any, rect: Rect, report: FreezeReport, is_transient: Callable[[BaseException], bool]
) -> int:
    """Read back a rectangle that held unquoted text or error literals; rewrite text Excel
    re-parsed with an apostrophe. Returns how many cells were rewritten."""
    try:
        back = grid(
            sheet.Range(address(rect.row, rect.col, rect.rows, rect.cols)).Value2,
            rect.rows,
            rect.cols,
        )
    except Exception as e:  # noqa: BLE001
        if is_transient(e):
            raise
        return 0
    fixed = 0
    for i in range(rect.rows):
        for j in range(rect.cols):
            written, original, now = rect.values[i][j], rect.originals[i][j], back[i][j]
            if not isinstance(written, str) or written.startswith("'"):
                continue
            if error_code(original) is not None:
                if now != original:
                    report.errors_as_text += 1
                continue
            if now != original:
                try:
                    sheet.Range(address(rect.row + i, rect.col + j)).Value2 = quoted(written)
                    fixed += 1
                except Exception as e:  # noqa: BLE001
                    if is_transient(e):
                        raise
    return fixed


def _no_cells_found(exc: BaseException) -> bool:
    """SpecialCells raises 0x800A03EC "No cells were found." when nothing matches."""
    args: tuple[object, ...] = tuple(getattr(exc, "args", ()))
    info: tuple[object, ...] = args[2] if len(args) > 2 and isinstance(args[2], tuple) else ()
    return (len(info) > 5 and info[5] == _NO_CELLS_FOUND) or "No cells were found" in str(exc)


def _formula_cells(sheet: Any) -> Iterable[Any]:
    try:
        found = sheet.UsedRange.SpecialCells(_XL_CELLTYPE_FORMULAS)
    except Exception as e:  # noqa: BLE001
        if _no_cells_found(e):
            return []
        raise
    return [cell for area in found.Areas for cell in area.Cells]


def _write_checked(cell: Any, value: object) -> bool:
    """Write one planned value; text Excel re-parses is rewritten with an apostrophe.
    Returns True when it had to be re-quoted."""
    cell.Value2 = value
    if isinstance(value, str) and not value.startswith("'") and cell.Value2 != value:
        if value not in ERROR_LITERALS.values():
            cell.Value2 = quoted(value)
            return True
    return False


def _finish_leftovers(
    sheet: Any, report: FreezeReport, is_transient: Callable[[BaseException], bool]
) -> None:
    """Freeze whatever still holds a formula. A write that overlaps part of a legacy array
    formula is ignored by Excel WITHOUT an error (2026-11-24 probe), so a block can come back
    untouched: arrays are frozen whole, other cells one by one. What still refuses (a data
    table) is counted in ``report.left``."""
    try:
        remaining = list(_formula_cells(sheet))
    except Exception as e:  # noqa: BLE001
        if is_transient(e):
            raise
        logger.debug("Could not list remaining formulas on {!r}: {}", sheet.Name, e)
        return
    done: set[str] = set()
    for cell in remaining:
        try:
            if cell.HasArray:
                region = cell.CurrentArray
                key = str(region.Address)
                if key in done:
                    continue
                done.add(key)
                rows, cols = int(region.Rows.Count), int(region.Columns.Count)
                values = grid(region.Value2, rows, cols)
                plan = [[plan_cell("=", v) for v in line] for line in values]
                region.Value2 = _payload(plan)
                report.arrays += 1
            elif _write_checked(cell, plan_cell("=", cell.Value2)):
                report.requoted += 1
        except Exception as e:  # noqa: BLE001
            if is_transient(e):
                raise
    try:
        report.left = len(list(_formula_cells(sheet)))
    except Exception as e:  # noqa: BLE001
        if is_transient(e):
            raise
