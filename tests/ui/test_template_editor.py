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


# -- Send test… ---------------------------------------------------------------------------


def _sending(qtbot, send):
    dlg = EmailTemplateDialog(
        "<html><body><p>{{ job_name }}</p></body></html>",
        "Daily Energy",
        preview_job=JOB,
        send_test=send,
        addresses=["me@corp.example.com", "boss@corp.example.com"],
    )
    qtbot.addWidget(dlg)
    dlg.show()
    popover = dlg.open_send_test()
    assert popover is not None
    return dlg, popover


def test_send_test_is_hidden_without_a_service(qtbot):
    dlg = _dialog(qtbot)
    assert dlg.send_test_button.isHidden() and dlg.open_send_test() is None


def test_send_test_emails_the_editor_as_it_is_now_and_remembers_the_address(qtbot):
    from reportflow.ui.feedback import recall, toasts

    sent: list[dict] = []
    dlg, popover = _sending(qtbot, lambda payload: sent.append(payload) or {"ok": True})
    dlg.html_edit.setPlainText("<html><body><p>Unsaved change</p></body></html>")
    popover.address.setText("me@corp.example.com")
    popover.send()
    qtbot.waitUntil(lambda: bool(sent) and not popover.isVisible(), timeout=3000)
    payload = sent[0]
    assert payload["to"] == "me@corp.example.com" and payload["stage"] == "testing"
    assert "Unsaved change" in payload["template"]  # no need to save first
    assert payload["subject"] == JOB["subject"] and payload["workbooks"] == ["Energy.xlsx"]
    assert recall("template/test_address") == "me@corp.example.com"
    assert any("Test email sent to me@corp.example.com" in t for t in toasts(dlg))


def test_send_test_says_what_went_wrong_in_place(qtbot):
    from reportflow.ui.api_client import ApiError

    def refuse(payload):
        raise ApiError("The email server isn't set up yet — File → Settings → Email.", 400)

    _dlg, popover = _sending(qtbot, refuse)
    popover.address.setText("not an address")
    popover.send()
    assert "Type the email address" in popover.error.text()
    popover.address.setText("me@corp.example.com")
    popover.send()
    qtbot.waitUntil(lambda: "isn't set up" in popover.error.text(), timeout=3000)
    assert popover.isVisible() and popover.send_button.isEnabled()
