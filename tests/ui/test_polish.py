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
