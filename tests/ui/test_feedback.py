"""Toasts, inline notices, field errors and the shared editing-dialog behaviour."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFormLayout, QLineEdit, QTabWidget, QVBoxLayout, QWidget

from reportflow.ui import feedback

from .test_ui import FakeApi, _sample_job_dict


def _capture_help(monkeypatch):
    """Replace the Help dialog with a stand-in that records the section it was opened at."""
    from reportflow.ui.windows import help_dialog

    opened = []

    class _Help:
        def __init__(self, parent=None, *, anchor=None):
            opened.append(anchor)

        def exec(self):
            return 0

    monkeypatch.setattr(help_dialog, "HelpDialog", _Help)
    return opened


def _shown(qtbot, widget):
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


# -- toasts and notices ---------------------------------------------------------------


def test_toasts_stack_in_one_column_and_fade_on_their_own(qtbot, monkeypatch):
    monkeypatch.setitem(feedback._TOAST_MS, "info", 50)
    window = _shown(qtbot, QDialog())
    window.resize(700, 400)
    feedback.toast(window, "First")
    second = feedback.toast(window, "Second, a bit longer than the first one", "warning")
    first = feedback.toasts(window)
    assert first == ["First", "Second, a bit longer than the first one"]
    host_items = [t for t in window.findChildren(feedback.Toast) if t.isVisible()]
    assert len({t.width() for t in host_items}) == 1  # one column, one width
    # Info notices fade on their own; the warning stays longer.
    qtbot.waitUntil(lambda: feedback.toasts(window) == [second.text], timeout=2000)


def test_toast_keeps_at_most_three_and_runs_its_action(qtbot):
    window = _shown(qtbot, QDialog())
    ran = []
    for i in range(4):
        feedback.toast(window, f"n{i}")
    assert feedback.toasts(window) == ["n1", "n2", "n3"]
    undo = feedback.toast(window, "Removed x.xlsx", action=("Undo", lambda: ran.append(1)))
    assert undo.action_button is not None
    undo.action_button.click()
    assert ran == [1]
    assert "Removed x.xlsx" not in feedback.toasts(window)


def test_inline_notice_shows_then_clears_and_offers_an_action(qtbot):
    notice = feedback.InlineNotice()
    qtbot.addWidget(notice)
    undone = []
    notice.show_notice(
        "Removed a@x — now covered by Plant leads.", action=("Undo", lambda: undone.append(1))
    )
    assert notice.plain.startswith("Removed a@x") and 'href="action"' in notice.text()
    notice.linkActivated.emit("action")
    assert undone == [1] and notice.plain == ""
    notice.show_notice("short", timeout_ms=30)
    qtbot.waitUntil(lambda: notice.plain == "", timeout=1000)
    assert notice.minimumHeight() > 0  # the line stays reserved: no layout jump


# -- field errors and tab dots ------------------------------------------------------


def test_field_error_sits_under_the_field_and_clears(qtbot):
    page = QWidget()
    qtbot.addWidget(page)
    form = QFormLayout(page)
    name = QLineEdit()
    form.addRow("Job name", name)
    feedback.set_field_error(name, "Give the job a name.")
    assert name.property("invalid") is True
    assert feedback.field_error(name) == "Give the job a name."
    feedback.clear_field_error(name)
    assert name.property("invalid") is False and feedback.field_error(name) == ""
    # Setting it again reuses the same label instead of stacking a second one.
    feedback.set_field_error(name, "Again.")
    from PySide6.QtWidgets import QLabel

    assert len(page.findChildren(QLabel, "fieldError")) == 1


def test_field_error_for_a_field_that_shares_a_row_with_a_button(qtbot):
    from PySide6.QtWidgets import QHBoxLayout, QPushButton

    page = QWidget()
    qtbot.addWidget(page)
    form = QFormLayout(page)
    row = QHBoxLayout()
    subject = QLineEdit()
    row.addWidget(subject)
    row.addWidget(QPushButton("Insert placeholder"))
    form.addRow("Subject", row)
    feedback.set_field_error(subject, "Unfinished placeholder.")
    assert feedback.field_error(subject) == "Unfinished placeholder."


def test_tab_dots_mark_only_the_tabs_with_problems(qtbot):
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    for name in ("General", "Output", "Email"):
        tabs.addTab(QWidget(), name)
    feedback.mark_tab_errors(tabs, {2})
    assert feedback.tabs_with_errors(tabs) == {2}
    feedback.mark_tab_errors(tabs, set())
    assert feedback.tabs_with_errors(tabs) == set()


# -- FormDialog: Enter, Ctrl+S, F1, unsaved changes, remembered size ----------------


class _Form(feedback.FormDialog):
    def __init__(self):
        super().__init__(settings_key="test_form")
        layout = QVBoxLayout(self)
        self.field = QLineEdit()
        layout.addWidget(self.field)
        self.saved = 0
        self.finish_form()

    def dirty_key(self):
        return self.field.text()

    def save_form(self):
        self.saved += 1


def test_enter_in_a_field_never_closes_the_form(qtbot):
    form = _shown(qtbot, _Form())
    form.field.setFocus()
    qtbot.keyClick(form.field, Qt.Key.Key_Return)
    qtbot.keyClick(form.field, Qt.Key.Key_Enter)
    assert form.isVisible() and form.result() == 0 and form.saved == 0


def test_ctrl_s_saves_and_f1_opens_help(qtbot, monkeypatch):
    form = _shown(qtbot, _Form())
    form.save_shortcut.activated.emit()
    assert form.saved == 1
    opened = _capture_help(monkeypatch)
    form.help_shortcut.activated.emit()
    assert opened == [None]


def test_cancel_asks_only_when_something_changed(qtbot, monkeypatch):
    asked = []

    def keep_editing(_parent):
        asked.append(1)
        return False

    monkeypatch.setattr(feedback, "confirm_discard", keep_editing)
    form = _shown(qtbot, _Form())
    form.reject()  # nothing changed: closes without asking
    assert asked == [] and not form.isVisible()

    form = _shown(qtbot, _Form())
    form.field.setText("edited")
    form.reject()
    assert asked == [1] and form.isVisible()  # "Keep editing"
    monkeypatch.setattr(feedback, "confirm_discard", lambda _p: True)
    form.reject()
    assert not form.isVisible()


def test_dialog_reopens_at_the_size_it_was_left_at(qtbot):
    form = _shown(qtbot, _Form())
    form.resize(733, 455)
    form.accept()
    again = _shown(qtbot, _Form())
    assert (again.width(), again.height()) == (733, 455)


# -- the real dialogs ---------------------------------------------------------------


def test_job_editor_enter_does_not_save_and_cancel_is_quiet_until_edited(qtbot, monkeypatch):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    asked = []
    monkeypatch.setattr(feedback, "confirm_discard", lambda _p: asked.append(1) or False)
    dlg = _shown(qtbot, JobEditorDialog(FakeApi(), _sample_job_dict()))
    qtbot.keyClick(dlg.name, Qt.Key.Key_Return)
    assert dlg.isVisible() and dlg.result() == 0
    assert not dlg.is_dirty()
    dlg.reject()
    assert asked == [] and not dlg.isVisible()

    dlg = _shown(qtbot, JobEditorDialog(FakeApi(), _sample_job_dict()))
    dlg.notes.setPlainText("changed")
    assert dlg.is_dirty()
    dlg.reject()
    assert asked == [1] and dlg.isVisible()


def test_job_editor_f1_opens_the_current_tabs_help(qtbot, monkeypatch):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    opened = _capture_help(monkeypatch)
    dlg = _shown(qtbot, JobEditorDialog(FakeApi(), _sample_job_dict()))
    dlg.tabs.setCurrentIndex(3)
    dlg.help_shortcut.activated.emit()
    assert opened == ["email"]


def test_settings_snapshot_never_holds_the_password(qtbot):
    from reportflow.ui.windows.settings_dialog import SettingsDialog

    dlg = _shown(qtbot, SettingsDialog(FakeApi()))
    assert not dlg.is_dirty()
    dlg.smtp_password.setText("s3cret-value")
    assert dlg.is_dirty()
    assert "s3cret-value" not in dlg.dirty_key()


def test_a_field_error_can_link_to_its_help_section(qtbot, monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(feedback, "show_help", lambda parent, anchor: opened.append(anchor))
    dlg = QDialog()
    qtbot.addWidget(dlg)
    form = QFormLayout(dlg)
    subject = QLineEdit()
    form.addRow("Subject", subject)
    feedback.set_field_error(subject, "This placeholder isn't finished: {{ today }", "placeholders")
    label = subject._rf_error_label
    assert "Learn more" in label.text() and 'href="placeholders"' in label.text()
    assert feedback.field_error(subject) == "This placeholder isn't finished: {{ today }"
    label.linkActivated.emit("placeholders")
    assert opened == ["placeholders"]


def test_learn_more_opens_the_guide_without_blocking_the_editor(qtbot):
    from reportflow.ui.windows.help_dialog import HelpDialog
    from reportflow.ui.windows.job_editor import JobEditorDialog

    dlg = _shown(qtbot, JobEditorDialog(FakeApi(), _sample_job_dict()))
    dlg.subject.setText("Daily {{ today }")
    dlg._on_save()
    label = dlg.subject._rf_error_label
    assert 'href="placeholders"' in label.text()
    label.linkActivated.emit("placeholders")
    guides = [w for w in dlg.findChildren(HelpDialog) if w.isVisible()]
    assert guides and not guides[0].isModal()
    qtbot.waitUntil(lambda: guides[0].current_section() == "placeholders", timeout=2000)
    guides[0].close()
