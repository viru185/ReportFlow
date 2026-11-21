"""The compact schedule cards: pills with their own x, a picker that adds and closes."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTime

from reportflow.ui.schedule_compile import ScheduleRule
from reportflow.ui.windows.schedule_widget import ScheduleWidget


def _schedule(qtbot, rule):
    widget = ScheduleWidget()
    qtbot.addWidget(widget)
    return widget, widget.add_rule(rule)


def test_enter_in_the_picker_adds_the_time_and_closes_it(qtbot):
    widget, row = _schedule(qtbot, ScheduleRule(kind="daily", times=["06:00"]))
    picker = row.open_time_picker()
    picker.time_edit.setTime(QTime(14, 15))
    qtbot.keyClick(picker.time_edit, Qt.Key.Key_Return)
    assert row.times() == ["06:00", "14:15"] and not picker.isVisible()
    assert row.pill("14:15").property("flash") is True  # it shows where it landed
    assert widget.to_crons() == ["0 6 * * *", "15 14 * * *"]


def test_the_first_guess_is_the_next_free_hour(qtbot):
    _widget, row = _schedule(qtbot, ScheduleRule(kind="daily"))
    assert row.open_time_picker().time_edit.time() == QTime(6, 0)
    row.add_time("06:00")
    row.add_time("07:00")
    assert row._next_free_time() == QTime(8, 0)
    row.add_time("23:30")
    assert row._next_free_time() == QTime(0, 30)  # wraps past midnight


def test_pills_stay_in_time_order_and_only_the_x_removes(qtbot):
    _widget, row = _schedule(qtbot, ScheduleRule(kind="daily", times=["18:00", "06:00"]))
    row.add_time("12:00")
    assert row.times() == ["06:00", "12:00", "18:00"]
    assert row.no_times.isHidden()
    for t in list(row.times()):
        row.pill(t).remove_button.click()
    assert row.times() == [] and not row.no_times.isHidden()


def test_an_invalid_schedule_turns_the_overview_amber(qtbot):
    widget, row = _schedule(qtbot, ScheduleRule(kind="daily"))
    assert widget.summary.text().startswith("Check schedule:")
    assert widget.summary.property("state") == "warning"
    row.add_time("06:00")
    assert widget.summary.property("state") == ""
    assert widget.summary.text() == "Daily at 06:00"


def test_weekdays_are_a_one_row_toggle(qtbot):
    widget, row = _schedule(qtbot, ScheduleRule(kind="weekly", times=["05:00"]))
    row.weekday_checks["TUE"].click()
    row.weekday_checks["WED"].click()
    assert widget.to_crons() == ["0 5 * * TUE,WED"]
    assert [b.text() for b in row.weekday_checks.values()] == [
        "Mon",
        "Tue",
        "Wed",
        "Thu",
        "Fri",
        "Sat",
        "Sun",
    ]


def test_a_duplicate_schedule_is_outlined_live_and_blocks_save(qtbot):
    from reportflow.ui.feedback import tabs_with_errors
    from reportflow.ui.schedule_compile import ScheduleRule
    from reportflow.ui.windows.job_editor import JobEditorDialog

    from .test_ui import FakeApi, _sample_job_dict

    dlg = JobEditorDialog(FakeApi(), _sample_job_dict())
    qtbot.addWidget(dlg)
    schedule = dlg.schedule
    schedule.load(["0 5 * * *"])
    copy = schedule.add_rule(ScheduleRule(kind="daily", times=["05:00"]))
    # Shown as soon as it exists, on the card itself — not merged away on Save.
    assert copy.property("invalid") is True
    assert copy.conflict.text() == "Same as the schedule above (Daily at 05:00) — remove one."
    assert schedule.summary.property("state") == "warning"
    assert schedule.rows()[0].property("invalid") in (None, False)
    dlg._on_save()
    assert dlg.result() == 0 and dlg.tabs.currentIndex() == 2
    assert 2 in tabs_with_errors(dlg.tabs)
    # Changing the time clears it.
    copy.remove_time("05:00")
    copy.add_time("07:00")
    assert not copy.conflict.text() and copy.property("invalid") is False
