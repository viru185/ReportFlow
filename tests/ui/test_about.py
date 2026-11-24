"""About: read-only facts (no editable-looking boxes), live service facts, copy for support."""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialogButtonBox, QLineEdit, QPlainTextEdit, QPushButton

from reportflow import __about__ as about
from reportflow.ui.kit import PathLabel
from reportflow.ui.windows.about_dialog import AboutDialog

from .test_ui import FakeApi


def _about(qtbot, api, **kw) -> AboutDialog:
    dlg = AboutDialog(api=api, **kw)
    qtbot.addWidget(dlg)
    qtbot.waitUntil(lambda: dlg.service_state.text() != "Checking…", timeout=3000)
    return dlg


def test_paths_are_text_with_copy_and_open_not_edit_boxes(qtbot):
    dlg = _about(qtbot, FakeApi())
    assert not dlg.findChildren(QPlainTextEdit) and not dlg.findChildren(QLineEdit)
    assert set(dlg.folders) == {"Data", "Logs", "Program"}
    assert all(
        isinstance(w, PathLabel) and w.copy_button and w.open_button for w in dlg.folders.values()
    )


def test_no_close_button_the_title_bar_has_one(qtbot):
    dlg = _about(qtbot, FakeApi())
    assert dlg.findChild(QDialogButtonBox) is None
    assert not [b for b in dlg.findChildren(QPushButton) if b.text() == "Close"]


def test_service_facts_and_a_version_mismatch_warning(qtbot):
    api = FakeApi()
    api.pi_trusted = True
    dlg = _about(qtbot, api)
    assert dlg.service_state.text().startswith("● Connected")
    # FakeApi's service reports 0.2.0, so the mismatch with this app is called out.
    assert "install the same version" in dlg.service_version.text()
    assert dlg.service_version.property("tone") == "warning"
    assert "trigger" in dlg.service_schedule.text()
    assert dlg.pi_trust.text().startswith("Trusted") and dlg.pi_trust.property("tone") == "success"


def test_pi_datalink_switched_off_by_excel_is_called_out(qtbot):
    api = FakeApi()
    api.pi_trusted = True
    api.pi_disabled = ("PI DataLink",)
    dlg = _about(qtbot, api)
    assert dlg.pi_trust.text().startswith("Switched off by Excel: PI DataLink")
    assert "Fix PI DataLink" in dlg.pi_trust.text()
    assert dlg.pi_trust.property("tone") == "danger"


def test_an_unreachable_service_is_said_plainly(qtbot):
    dlg = _about(qtbot, FakeApi(connected=False))
    assert "Not reachable" in dlg.service_state.text()
    assert dlg.service_state.property("tone") == "danger"


def test_copy_details_for_support(qtbot):
    calls = []
    dlg = _about(qtbot, FakeApi(), on_help=lambda: calls.append("help"))
    dlg.copy_details()
    text = QGuiApplication.clipboard().text()
    assert text.startswith(f"{about.NAME} {about.VERSION}")
    assert "Data folder:" in text and "Runs as:" in text and "Python" in text
    guide = next(b for b in dlg.findChildren(QPushButton) if b.text() == "User guide")
    guide.click()
    assert calls == ["help"]
