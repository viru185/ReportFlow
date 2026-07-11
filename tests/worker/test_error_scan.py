"""Unit tests for the error-cell message + machine-account detection (no Excel needed)."""

from __future__ import annotations

from reportflow.worker.excel import format_error_cell_message
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


def test_machine_account_detection(monkeypatch):
    monkeypatch.setenv("USERNAME", "VIREN-BOOK$")
    monkeypatch.setenv("USERDOMAIN", "WORKGROUP")
    assert _is_machine_account() is True
    assert _account() == "WORKGROUP\\VIREN-BOOK$"

    monkeypatch.setenv("USERNAME", "pi_reports")
    assert _is_machine_account() is False
