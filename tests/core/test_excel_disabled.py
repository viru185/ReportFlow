"""Excel's Disabled Items list for the PI add-ins (0.16) — against a throwaway HKCU key."""

from __future__ import annotations

import struct
import uuid
import winreg

import pytest

from reportflow.core import excel_disabled
from reportflow.core.excel_disabled import (
    DISABLED,
    STARTUP,
    decode,
    disabled_pi_addins,
    read_items,
    reenable_pi_addins,
)

PI_VSTO = "file:///E:/Program Files/PIPC/Excel/OSIsoft.PIDataLink.UI.vsto|vstolocal"


def entry(path: str, name: str, kind: int = 1) -> bytes:
    """An entry the way Excel writes one: kind, two byte lengths, path and name (UTF-16LE)."""
    p = (path + "\x00").encode("utf-16-le")
    n = (name + "\x00").encode("utf-16-le")
    return struct.pack("<III", kind, len(p), len(n)) + p + n


@pytest.fixture
def office():
    """``Software\\ReportFlowTests\\<id>\\Office`` under HKCU, removed afterwards."""
    root = rf"Software\ReportFlowTests\{uuid.uuid4().hex}"
    base = rf"{root}\Office"

    def put(version: str, kind: str, values: dict[str, object]) -> None:
        subkey = rf"{base}\{version}\Excel\Resiliency\{kind}"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_WRITE) as key:
            for name, data in values.items():
                kind_of = winreg.REG_BINARY if isinstance(data, bytes) else winreg.REG_SZ
                winreg.SetValueEx(key, name, 0, kind_of, data)

    def names(version: str, kind: str) -> set[str]:
        subkey = rf"{base}\{version}\Excel\Resiliency\{kind}"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
            return {winreg.EnumValue(key, i)[0] for i in range(winreg.QueryInfoKey(key)[1])}

    yield base, put, names
    _delete_tree(root)
    try:  # the shared parent, once no other test uses it
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\ReportFlowTests")
    except OSError:
        pass


def _delete_tree(subkey: str) -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
            children = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
    except OSError:
        return
    for child in children:
        _delete_tree(rf"{subkey}\{child}")
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, subkey)


def test_an_entry_reads_back_its_name_and_path():
    name, path, text = decode(entry(PI_VSTO, "pi datalink"))
    assert (name, path) == ("pi datalink", PI_VSTO)
    assert "pi datalink" in text


def test_an_entry_in_another_layout_still_matches_by_its_text():
    odd = b"\x07" + "PI DataLink (crashed)".encode("utf-16-le") + b"\x00\x00"
    name, path, text = decode(odd)
    assert (name, path) == ("", "")
    assert "PI DataLink" in text


def test_only_the_pi_add_ins_excel_switched_off_are_reported(office):
    base, put, _names = office
    put(
        "16.0",
        DISABLED,
        {
            "a1": entry(PI_VSTO, "pi datalink"),
            "b2": entry(r"C:\Reports\Budget.xlsx", "budget.xlsx", kind=3),  # a document
            "c3": entry(r"C:\addins\other.dll", "other add-in"),
            "d4": "not binary",
        },
    )
    put("16.0", STARTUP, {"e5": entry(r"E:\PIPC\AF\PIAFBuilder.vsto", "piafbuilder")})
    put("15.0", DISABLED, {"f6": entry(r"E:\PIPC\AF\PIAFBuilder.vsto", "piafbuilder")})
    assert disabled_pi_addins(base=base) == ["PI DataLink", "PIAFBuilder"]
    assert len(read_items(base=base)) == 5  # the REG_SZ value is ignored


def test_fixing_removes_only_pi_entries_and_their_crash_markers(office):
    base, put, names = office
    put(
        "16.0",
        DISABLED,
        {
            "a1": entry(PI_VSTO, "pi datalink"),
            "b2": entry(r"C:\Reports\Budget.xlsx", "budget.xlsx", kind=3),
        },
    )
    put(
        "16.0",
        STARTUP,
        {"c3": entry(PI_VSTO, "pi datalink"), "d4": entry(r"C:\x\other.dll", "other add-in")},
    )
    enabled, failed = reenable_pi_addins(base=base)
    assert (enabled, failed) == (["PI DataLink"], [])
    assert names("16.0", DISABLED) == {"b2"}  # the user's document stays disabled
    assert names("16.0", STARTUP) == {"d4"}
    assert disabled_pi_addins(base=base) == []
    assert reenable_pi_addins(base=base) == ([], [])  # nothing left to do


def test_no_office_settings_at_all_is_simply_nothing_disabled(office):
    base, _put, _names = office
    assert disabled_pi_addins(base=base) == []
    assert reenable_pi_addins(base=base) == ([], [])


def test_a_value_that_cannot_be_deleted_is_reported(office, monkeypatch):
    base, put, _names = office
    put("16.0", DISABLED, {"a1": entry(PI_VSTO, "pi datalink")})

    def refuse(_key, _value):
        raise PermissionError("access denied")

    monkeypatch.setattr(excel_disabled.winreg, "DeleteValue", refuse)
    enabled, failed = reenable_pi_addins(base=base)
    assert enabled == [] and failed == ["PI DataLink: access denied"]
