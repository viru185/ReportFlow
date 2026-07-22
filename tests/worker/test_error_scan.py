"""Unit tests for the error-cell message, settle predicate, and account detection
(no Excel needed)."""

from __future__ import annotations

from reportflow.worker.excel import (
    _count_values,
    _settle_verdict,
    format_error_cell_message,
    format_error_cell_warnings,
)
from reportflow.worker.runner import _account, _is_machine_account


def test_message_lists_sheets_and_counts():
    msg = format_error_cell_message({"Report": (3, ["#REF!"])}, [], "CORP\\svc")
    assert "'Report'" in msg
    assert "3 cell(s): #REF!" in msg
    # No #NAME? -> no add-in/account hint (only the trailing "See Help" pointer).
    assert "did not load" not in msg
    assert "run as a Windows user" not in msg
    assert "See Help" in msg


def test_name_error_adds_addin_and_account_hint():
    msg = format_error_cell_message(
        {"Snapshot Report": (70, ["#NAME?"])}, ["PI DataLink"], "WORKGROUP\\VIREN-BOOK$"
    )
    assert "#NAME?" in msg
    assert "PI DataLink" in msg
    assert "WORKGROUP\\VIREN-BOOK$" in msg
    assert "run as a Windows user" in msg


def test_warnings_are_deliver_anyway_notes():
    warns = format_error_cell_warnings({"Detailed report": (12, ["#REF!"])})
    assert len(warns) == 1
    assert "'Detailed report'" in warns[0]
    assert "12 error cell(s)" in warns[0]
    assert "#REF!" in warns[0]
    assert "delivered anyway" in warns[0]
    assert format_error_cell_warnings({}) == []


def test_count_values_counts_only_non_empty():
    # A 2x3 grid: numbers + a string count, blanks/None do not.
    grid = [[1, "", None], [0, "x", "  "]]
    assert _count_values(grid) == 3  # 1, 0, and "x"
    assert _count_values(None) == 0
    assert _count_values([[None, None]]) == 0


def test_settle_decrease_is_never_stable():
    """A collapsed dynamic-array spill (count DROPS mid-recalc) must reset stability —
    the old `sig <= prev` treated the drop as convergence and froze half-loaded sheets."""
    baselines = {"Snapshot": 60, "TimeSeries": 1100}
    # Round 1: TimeSeries collapsed to headers only.
    stable, lagging = _settle_verdict(
        {"Snapshot": 60, "TimeSeries": 44}, {"Snapshot": 60, "TimeSeries": 1100}, baselines, 1
    )
    assert stable == 0  # decrease resets, never increments
    assert lagging == ["TimeSeries"]


def test_settle_stable_below_baseline_keeps_lagging():
    """Unchanged-but-empty is NOT settled: the sheet opened with far more data."""
    baselines = {"TimeSeries": 1100}
    counts = {"TimeSeries": 44}
    stable, lagging = _settle_verdict(counts, dict(counts), baselines, 1)
    assert stable == 2  # counts unchanged -> stability advances...
    assert lagging == ["TimeSeries"]  # ...but the sheet is still flagged as lagging


def test_settle_converges_when_all_sheets_stable_at_or_above_baseline():
    baselines = {"Snapshot": 60, "TimeSeries": 1100}
    counts = {"Snapshot": 62, "TimeSeries": 1144}
    stable, lagging = _settle_verdict(counts, dict(counts), baselines, 1)
    assert stable == 2 and lagging == []


def test_settle_first_round_and_per_sheet_masking():
    baselines = {"Fast": 100, "Slow": 500}
    # First round (no prev) never counts as stable.
    stable, _ = _settle_verdict({"Fast": 100, "Slow": 0}, None, baselines, 5)
    assert stable == 0
    # A big stable sheet must not mask a still-growing small one (per-sheet, not summed).
    stable, lagging = _settle_verdict(
        {"Fast": 100, "Slow": 200}, {"Fast": 100, "Slow": 100}, baselines, 1
    )
    assert stable == 0  # Slow changed -> whole round unstable
    assert lagging == ["Slow"]


def test_machine_account_detection(monkeypatch):
    monkeypatch.setenv("USERNAME", "VIREN-BOOK$")
    monkeypatch.setenv("USERDOMAIN", "WORKGROUP")
    assert _is_machine_account() is True
    assert _account() == "WORKGROUP\\VIREN-BOOK$"

    monkeypatch.setenv("USERNAME", "pi_reports")
    assert _is_machine_account() is False
