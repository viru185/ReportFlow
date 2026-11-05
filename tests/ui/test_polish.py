"""Interaction regressions for the polished editor, independent of a live service."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox, QScrollArea, QStyleOptionViewItem

from reportflow.ui.widgets import CenteredCheckDelegate
from reportflow.ui.windows.job_editor import JobEditorDialog, _SheetRow


@pytest.fixture
def themed_app(qapp):
    from PySide6.QtGui import QFont, QFontDatabase

    from reportflow.ui.style import apply_theme

    # Offscreen Qt does not discover Windows fonts automatically.
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_path)) if font_path.exists() else -1
    old_font, old_palette, old_qss = qapp.font(), qapp.palette(), qapp.styleSheet()
    qapp.setFont(QFont("Segoe UI", 10))
    apply_theme(qapp)
    yield qapp
    qapp.setStyleSheet(old_qss)
    qapp.setPalette(old_palette)
    qapp.setFont(old_font)
    if font_id >= 0:
        QFontDatabase.removeApplicationFont(font_id)


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


def test_schedule_overview_precedes_rules_and_tracks_added_times(qtbot):
    from PySide6.QtCore import QPoint, QTime

    from reportflow.ui.windows.schedule_widget import ScheduleWidget

    schedule = ScheduleWidget()
    qtbot.addWidget(schedule)
    schedule.load(["0 6 * * *", "0 10 * * SUN"])
    schedule.show()
    first, second = schedule.rows()
    assert schedule.summary.y() < first.y() < second.y()
    assert "06:00" in schedule.summary.text() and "10:00" in schedule.summary.text()
    first.time_edit.setTime(QTime(18, 30))
    assert "18:30" not in schedule.summary.text()
    first.add_time_button.click()
    assert "18:30" in schedule.summary.text()
    assert first.times_row.mapTo(first, QPoint()).y() < first.picker_row.y()
    first.kind.setCurrentIndex(first.kind.findData("cron"))
    assert first.times_row.isHidden() and first.picker_row.isHidden()


@pytest.mark.parametrize("size", [(640, 480), (960, 760)])
def test_editor_reflows_without_horizontal_scrolling_and_keeps_save_visible(
    qtbot, themed_app, size
):
    from PySide6.QtCore import QPoint
    from tests.ui.test_ui import FakeApi, _every_field_job

    job = _every_field_job().model_dump(mode="json")
    dialog = JobEditorDialog(FakeApi(), job)
    qtbot.addWidget(dialog)
    dialog.resize(*size)
    dialog.show()
    buttons = dialog.findChild(QDialogButtonBox)
    save = buttons.button(QDialogButtonBox.StandardButton.Save)
    for i in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(i)
        page = dialog.tabs.widget(i)
        qtbot.waitUntil(lambda page=page: page.horizontalScrollBar().maximum() == 0)
        page.verticalScrollBar().setValue(page.verticalScrollBar().maximum())
        assert save.isVisible()
        assert dialog.rect().contains(save.mapTo(dialog, QPoint(0, save.height() - 1)))
    assert dialog.payload()["workbooks"] == job["workbooks"]


@pytest.mark.parametrize("stage", ["live", "testing"])
@pytest.mark.parametrize("enabled", [False, True])
def test_job_card_run_status_and_stage_alignment(qtbot, themed_app, stage, enabled):
    from datetime import datetime

    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QLabel, QPushButton
    from tests.ui.test_ui import FakeApi, _sample_job_dict

    from reportflow.ui.windows.main_window import MainWindow

    job = dict(_sample_job_dict(), stage=stage, enabled=enabled)
    api = FakeApi(jobs=[job])
    window = MainWindow(api)
    qtbot.addWidget(window)
    window.show()
    for status, edge in [("running", "running"), ("success", "success"), ("failed", "failed")]:
        job.update(last_status=status, last_run_at=datetime.now().isoformat())
        window.refresh()
        card = window.jobs_layout.itemAt(0).widget()
        assert card.property("edge") == edge
        assert card.graphicsEffect() is None
        labels = card.findChildren(QLabel)
        assert not any("PAUSED" in label.text() for label in labels)
        assert any("running ·" in label.text() for label in labels) == (status == "running")
        run = next(b for b in card.findChildren(QPushButton) if b.text() == "▶ Run")
        build = next(b for b in card.findChildren(QPushButton) if b.text() == "👁 Build only")
        assert run.isEnabled() == build.isEnabled() == (status != "running")
        badge = card.findChild(QLabel, "jobStage")
        qtbot.waitUntil(lambda badge=badge: badge.isVisible() and badge.height() > 0)
        badge_center = badge.mapTo(card, QPoint(0, badge.height() // 2)).y()
        run_center = run.mapTo(card, QPoint(0, run.height() // 2)).y()
        assert abs(badge_center - run_center) <= 1


def test_job_card_double_click_text_opens_edit_but_actions_stay_separate(qtbot, monkeypatch):
    from PySide6.QtWidgets import QLabel, QPushButton
    from tests.ui.test_ui import FakeApi, _sample_job_dict

    from reportflow.ui.windows.main_window import MainWindow

    api = FakeApi(jobs=[_sample_job_dict()])
    window = MainWindow(api)
    qtbot.addWidget(window)
    edits = []
    actions = []
    monkeypatch.setattr(window, "_edit_job", edits.append)
    monkeypatch.setattr(window, "_trigger", lambda name, **kwargs: actions.append(name))
    window.show()
    card = window.jobs_layout.itemAt(0).widget()
    name = next(label for label in card.findChildren(QLabel) if label.text() == "daily")
    qtbot.mouseClick(name, Qt.MouseButton.LeftButton)
    assert edits == []
    qtbot.mouseDClick(name, Qt.MouseButton.LeftButton)
    assert edits == ["daily"]
    edits.clear()
    qtbot.mouseDClick(card, Qt.MouseButton.LeftButton)
    assert edits == ["daily"]
    edits.clear()
    run = next(button for button in card.findChildren(QPushButton) if button.text() == "▶ Run")
    qtbot.mouseDClick(run, Qt.MouseButton.LeftButton)
    assert edits == []
    qtbot.mouseClick(run, Qt.MouseButton.LeftButton)
    assert actions == ["daily"]


def test_job_card_context_menu_uses_existing_actions_and_defers_refresh(qtbot, monkeypatch):
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QApplication, QLabel, QToolButton
    from tests.ui.test_ui import FakeApi, _sample_job_dict

    from reportflow.ui.windows.main_window import MainWindow

    job = _sample_job_dict()
    window = MainWindow(FakeApi(jobs=[job]))
    qtbot.addWidget(window)
    window.show()
    card = window.jobs_layout.itemAt(0).widget()
    menu = card.findChild(QToolButton).menu()
    edits = []
    monkeypatch.setattr(window, "_edit_job", edits.append)
    name = next(label for label in card.findChildren(QLabel) if label.text() == "daily")
    pos = name.rect().center()
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, name.mapToGlobal(pos))
    QApplication.sendEvent(name, event)
    qtbot.waitUntil(menu.isVisible)
    assert QApplication.activePopupWidget() is menu
    assert edits == []
    job["last_status"] = "running"
    window.refresh()
    assert window._refresh_pending
    assert window.jobs_layout.itemAt(0).widget() is card
    menu.close()
    qtbot.waitUntil(lambda: window.jobs_layout.itemAt(0).widget() is not card)
    card = window.jobs_layout.itemAt(0).widget()
    menu = card.findChild(QToolButton).menu()
    card.setFocus()
    qtbot.keyClick(card, Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
    qtbot.waitUntil(menu.isVisible)
    edit = next(action for action in menu.actions() if "Edit" in action.text())
    edit.trigger()
    menu.close()
    assert edits == ["daily"]
