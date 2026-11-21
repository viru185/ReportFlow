"""The Insert-placeholder picker: right list per field, inserts at the cursor, stays open."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit, QPlainTextEdit

from reportflow.core.email.render import PLACEHOLDERS
from reportflow.core.output_names import OUTPUT_NAME_TOKENS
from reportflow.ui.placeholder_picker import (
    PlaceholderButton,
    PlaceholderPicker,
    email_placeholders,
    output_name_placeholders,
)

from .test_ui import FakeApi, _sample_job_dict

NOW = datetime(2026, 10, 7, 6, 15)


def test_catalogues_come_from_the_single_lists():
    body = email_placeholders(now=NOW)
    assert [p.token for p in body] == [t for _, _, t, _ in PLACEHOLDERS]
    subject = email_placeholders(subject=True, now=NOW)
    assert all(p.group != "Blocks" for p in subject)  # no HTML blocks in a subject line
    today = next(p for p in subject if p.token == "{{ today }}")
    assert today.example == "07-Oct-2026"
    names = output_name_placeholders(job_name="Sales", now=NOW)
    assert [p.token for p in names] == [t for _, t, _ in OUTPUT_NAME_TOKENS]
    examples = {p.token: p.example for p in names}
    assert examples["{job}"] == "Sales" and examples["{date}"] == "20261007"
    assert examples["{datetime}"] == "20261007_061500"


def test_picker_inserts_at_the_cursor_and_stays_open(qtbot):
    field = QLineEdit("Report  for you")
    qtbot.addWidget(field)
    field.setCursorPosition(7)
    picker = PlaceholderPicker(
        field, email_placeholders(subject=True, now=NOW), field_name="Subject"
    )
    qtbot.addWidget(picker)
    picker.show()
    today = next(p for p in picker.items() if p.token == "{{ today }}")
    picker.insert(today)
    assert field.text() == "Report {{ today }} for you"
    assert picker.isVisible()  # add the next one straight away
    assert picker.notice.plain == "Inserted {{ today }} into Subject."
    month = next(p for p in picker.items() if p.token == "{{ month }}")
    picker.insert(month)
    assert "{{ today }}{{ month }}" in field.text()


def test_picker_works_on_a_multi_line_editor(qtbot):
    editor = QPlainTextEdit("Hello\n")
    qtbot.addWidget(editor)
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    picker = PlaceholderPicker(editor, email_placeholders(now=NOW), field_name="Email body")
    qtbot.addWidget(picker)
    picker.insert(next(p for p in picker.items() if p.label == "Job name"))
    assert editor.toPlainText() == "Hello\n{{ job_name }}"


def test_search_filters_and_the_keyboard_inserts(qtbot):
    field = QLineEdit()
    qtbot.addWidget(field)
    picker = PlaceholderPicker(
        field, email_placeholders(subject=True, now=NOW), field_name="Subject"
    )
    qtbot.addWidget(picker)
    picker.show()
    picker.search.setText("month")
    assert picker.visible_tokens() == [
        "{{ month }}",
        "{{ previous_month }}",
        "{{ run_date.strftime('%d/%m/%Y') }}",  # its description mentions "%m month"
    ]
    qtbot.keyClick(picker.search, Qt.Key.Key_Down)
    qtbot.keyClick(picker.search, Qt.Key.Key_Return)
    assert field.text() == "{{ previous_month }}"
    picker.search.setText("zzz")
    assert picker.visible_tokens() == []


def test_block_tokens_show_as_written_not_as_html(qtbot):
    field = QPlainTextEdit()
    qtbot.addWidget(field)
    picker = PlaceholderPicker(field, email_placeholders(now=NOW), field_name="Email body")
    qtbot.addWidget(picker)
    from PySide6.QtWidgets import QLabel

    tokens = [label.text() for label in picker.findChildren(QLabel, "placeholderToken")]
    assert any("<ul>" in t for t in tokens)
    assert all(
        label.textFormat() == Qt.TextFormat.PlainText
        for label in picker.findChildren(QLabel, "placeholderToken")
    )


def test_editor_fields_have_their_own_pickers(qtbot):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    dlg = JobEditorDialog(FakeApi(), _sample_job_dict())
    qtbot.addWidget(dlg)
    assert isinstance(dlg.subject_placeholders, PlaceholderButton)
    subject_picker = dlg.subject_placeholders.open_picker()
    qtbot.addWidget(subject_picker)
    assert "{{ today }}" in [p.token for p in subject_picker.items()]
    assert all(p.group != "Blocks" for p in subject_picker.items())
    assert dlg.subject_placeholders.open_picker() is subject_picker  # one per field
    names_picker = dlg.output_placeholders.open_picker()
    qtbot.addWidget(names_picker)
    assert [p.token for p in names_picker.items()] == [t for _, t, _ in OUTPUT_NAME_TOKENS]
    job = next(p for p in names_picker.items() if p.token == "{job}")
    assert job.example == "daily"  # this job's name
    for _, token, _ in OUTPUT_NAME_TOKENS:
        assert token in dlg.output_name.toolTip()


def test_the_picker_is_a_popover_without_title_bar_or_done_button(qtbot):
    from PySide6.QtWidgets import QPushButton

    from reportflow.ui.kit import Popover

    field = QLineEdit()
    qtbot.addWidget(field)
    picker = PlaceholderPicker(
        field, email_placeholders(subject=True, now=NOW), field_name="Subject"
    )
    qtbot.addWidget(picker)
    assert isinstance(picker, Popover)
    assert picker.windowFlags() & Qt.WindowType.Popup  # closes on a click outside
    assert not [b for b in picker.findChildren(QPushButton) if b.text() in ("Done", "Close")]
    picker.show()
    qtbot.keyClick(picker.search, Qt.Key.Key_Escape)
    assert not picker.isVisible()


def test_each_open_shows_the_current_job_name_in_examples(qtbot):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    dlg = JobEditorDialog(FakeApi(), _sample_job_dict())
    qtbot.addWidget(dlg)
    dlg.show()
    picker = dlg.output_placeholders.open_picker()
    assert next(p for p in picker.items() if p.token == "{job}").example == "daily"
    picker.close()
    dlg.name.setText("Monthly energy")
    picker = dlg.output_placeholders.open_picker()
    assert next(p for p in picker.items() if p.token == "{job}").example == "Monthly energy"
    picker.close()
