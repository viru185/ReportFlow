"""Interaction regressions for the polished editor, independent of a live service."""

from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox, QScrollArea, QStyleOptionViewItem

from reportflow.ui.widgets import CenteredCheckDelegate
from reportflow.ui.windows.job_editor import JobEditorDialog, _SheetRow


def test_sheet_checkbox_center_mouse_and_keyboard(qtbot):
    dialog = JobEditorDialog(SimpleNamespace(get_config=lambda: {}))
    qtbot.addWidget(dialog)
    dialog._set_rows([_SheetRow("Summary", True)])
    dialog.show()
    table = dialog.sheets
    index = table.model().index(0, 2)
    option = QStyleOptionViewItem()
    option.widget = table
    option.rect = table.visualRect(index)
    center = CenteredCheckDelegate.indicator_rect(option).center()
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    assert table.item(0, 2).checkState() == Qt.CheckState.Unchecked
    table.setCurrentCell(0, 2)
    qtbot.keyClick(table, Qt.Key.Key_Space)
    assert table.item(0, 2).checkState() == Qt.CheckState.Checked
    table.item(0, 1).setCheckState(Qt.CheckState.Unchecked)
    qtbot.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=center)
    assert table.item(0, 2).checkState() == Qt.CheckState.Checked


def test_editor_pages_scroll_with_actions_outside_content(qtbot):
    dialog = JobEditorDialog(SimpleNamespace(get_config=lambda: {}))
    qtbot.addWidget(dialog)
    assert all(isinstance(dialog.tabs.widget(i), QScrollArea) for i in range(5))
    buttons = dialog.findChild(QDialogButtonBox)
    assert buttons.button(QDialogButtonBox.StandardButton.Save).property("accent")


def test_schedule_pending_time_requires_add_and_duplicates_are_disabled(qtbot):
    from PySide6.QtCore import QTime
    from PySide6.QtWidgets import QPushButton

    from reportflow.ui.schedule_compile import ScheduleRule
    from reportflow.ui.windows.schedule_widget import ScheduleWidget

    schedule = ScheduleWidget()
    qtbot.addWidget(schedule)
    row = schedule.add_rule(ScheduleRule(kind="daily", times=["06:00"]))
    assert not row.add_time_button.isEnabled()
    row.time_edit.setTime(QTime(18, 30))
    assert schedule.to_crons() == ["0 6 * * *"]
    assert row.add_time_button.isEnabled()
    row.add_time_button.click()
    assert schedule.to_crons() == ["0 6 * * *", "30 18 * * *"]
    assert not row.add_time_button.isEnabled()
    chip = next(b for b in row.findChildren(QPushButton) if b.text().startswith("18:30"))
    chip.click()
    assert schedule.to_crons() == ["0 6 * * *"]
    assert row.add_time_button.isEnabled()


def test_monthly_validation_remains_visible_and_recoverable(qtbot):
    from reportflow.ui.schedule_compile import ScheduleRule
    from reportflow.ui.windows.schedule_widget import ScheduleWidget

    schedule = ScheduleWidget()
    qtbot.addWidget(schedule)
    row = schedule.add_rule(ScheduleRule(kind="monthly", times=["06:00"], month_days=[1]))
    row.month_days.setText("32")
    assert schedule.summary.text().startswith("Check schedule:")
    row.month_days.setText("1, 15")
    assert schedule.to_crons() == ["0 6 1,15 * *"]
    assert not schedule.summary.styleSheet()
