"""The email template editor: big, side by side, a preview that follows every change."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from reportflow.ui.windows.email_template_dialog import EmailTemplateDialog

JOB = {
    "name": "Daily Energy",
    "subject": "Daily energy — {{ job_name }}",
    "stage": "testing",
    "sheets": ["Summary"],
    "workbooks": ["Energy.xlsx"],
    "recipients": {
        "testing": {"to": ["dev@corp.example.com"], "cc": []},
        "live": {"to": ["boss@corp.example.com"], "cc": []},
    },
}


def _dialog(qtbot, html="<html><body><p>{{ job_name }}</p></body></html>"):
    dlg = EmailTemplateDialog(html, "Daily Energy", preview_job=JOB)
    qtbot.addWidget(dlg)
    return dlg


def test_preview_is_there_from_the_start_without_a_button(qtbot):
    dlg = _dialog(qtbot)
    assert "Daily Energy" in dlg.preview.toPlainText()
    assert "[TEST] Daily energy — Daily Energy" in dlg.preview.toPlainText()
    assert not [b for b in dlg.findChildren(type(dlg.preview_testing)) if b.text() == "Preview"]


def test_preview_follows_typing(qtbot):
    dlg = _dialog(qtbot)
    dlg.html_edit.setPlainText("<html><body><p>Now with {{ sheet_count }} sheet</p></body></html>")
    qtbot.waitUntil(lambda: "Now with 1 sheet" in dlg.preview.toPlainText(), timeout=2000)


def test_a_mistake_shows_above_the_preview_and_keeps_the_last_good_one(qtbot, monkeypatch):
    popups = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: popups.append(a)))
    dlg = _dialog(qtbot)
    dlg.html_edit.setPlainText("<html><body>\n<p>{{ job_name }</p></body></html>")
    dlg._preview()
    assert dlg.preview_error.isVisibleTo(dlg)
    assert dlg.preview_error.text().startswith("The template has a mistake — Line 2:")
    assert "Daily Energy" in dlg.preview.toPlainText()  # the last good preview stays
    dlg._on_save()  # saving is refused the same way — no popup to click away
    assert dlg.result() == 0 and popups == []
    dlg.html_edit.setPlainText("<p>fixed</p>")
    dlg._preview()
    assert not dlg.preview_error.isVisibleTo(dlg)


def test_an_empty_simple_message_shows_a_hint_not_a_blank_email(qtbot):
    dlg = EmailTemplateDialog("", "Daily Energy", preview_job=JOB)
    qtbot.addWidget(dlg)
    assert dlg.tabs.currentWidget() is dlg.simple_edit
    assert "Start writing on the left" in dlg.preview.toPlainText()
    dlg._on_save()
    assert dlg.result() == 0 and "empty" in dlg.preview_error.text()


def test_the_editor_is_large_resizable_and_opens_placeholder_help(qtbot, monkeypatch):
    dlg = _dialog(qtbot)
    assert dlg.minimumWidth() >= 900 and dlg.minimumHeight() >= 600
    assert dlg.splitter.count() == 2  # editor | preview, side by side
    assert dlg.help_anchor() == "placeholders"


def test_cancel_asks_only_after_an_edit(qtbot, monkeypatch):
    from reportflow.ui import feedback

    asked = []
    monkeypatch.setattr(feedback, "confirm_discard", lambda _p: asked.append(1) or False)
    dlg = _dialog(qtbot)
    dlg.show()
    qtbot.waitExposed(dlg)
    dlg.preview_production.click()  # looking at the other stage is not an edit
    dlg.reject()
    assert asked == [] and not dlg.isVisible()
    dlg = _dialog(qtbot)
    dlg.show()
    qtbot.waitExposed(dlg)
    dlg.html_edit.setPlainText("<p>changed</p>")
    dlg.reject()
    assert asked == [1] and dlg.isVisible()
