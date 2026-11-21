"""Visual schedule builder: a list of rules — Daily / Weekly / Monthly / Custom (cron).

A job can combine rules, e.g. "daily at 06:00" plus "every Sunday at 10:00". Each rule is a
compact card: its kind, a row of run times (each a small pill with its own ×), and for weekly
rules a Mon…Sun toggle. "+ Add time" opens a small picker that adds the time and closes, so a
time on screen is always a time that will run (the old always-visible picker left people
unsure whether the time in the box was added). No rules = manual only. Compiles to cron
expressions via the pure ``schedule_compile`` helpers.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTime, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.feedback import flash
from reportflow.ui.schedule_compile import (
    WEEKDAYS,
    ScheduleRule,
    compile_rules,
    describe,
    parse_crons,
)
from reportflow.ui.widgets import FlowLayout

_KINDS = [
    ("Daily", "daily"),
    ("Weekly", "weekly"),
    ("Monthly", "monthly"),
    ("Custom (cron)", "cron"),
]
_LABEL_WIDTH = 64  # "Runs at" / "On" line up


def _parse_month_days(text: str) -> list[int]:
    days: list[int] = []
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit() or not 1 <= int(part) <= 31:
            raise ValueError(f"day of the month must be 1-31, got {part!r}")
        days.append(int(part))
    return days


def _row_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("muted", True)
    label.setFixedWidth(_LABEL_WIDTH)
    label.setMinimumHeight(26)  # centred on the first line of pills / toggles
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return label


class _TimePill(QFrame):
    """One run time; only its × removes it."""

    remove_requested = Signal(str)

    def __init__(self, time: str) -> None:
        super().__init__()
        self.time = time
        self.setProperty("timePill", True)
        self.setFixedHeight(26)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 3, 0)
        row.setSpacing(2)
        label = QLabel(time)
        label.setObjectName("timePillText")
        row.addWidget(label)
        remove = QToolButton()
        remove.setObjectName("timePillRemove")
        remove.setText("×")
        remove.setFixedSize(20, 20)
        remove.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.setToolTip(f"Remove {time}")
        remove.setAccessibleName(f"Remove run time {time}")
        remove.clicked.connect(lambda: self.remove_requested.emit(self.time))
        row.addWidget(remove)
        self.remove_button = remove


class _TimePopover(QFrame):
    """The small picker "+ Add time" opens: choose a time, Add (or Enter), and it closes."""

    def __init__(self, row: _RuleRow) -> None:
        super().__init__(row, Qt.WindowType.Popup)
        self.setObjectName("timePopover")
        self._row = row
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        title = QLabel("Add a run time")
        title.setObjectName("timePopoverTitle")
        layout.addWidget(title)
        line = QHBoxLayout()
        line.setSpacing(8)
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setFixedWidth(110)
        self.time_edit.timeChanged.connect(self._check)
        self.time_edit.installEventFilter(self)
        self.add_button = QPushButton("Add")
        self.add_button.setProperty("accent", True)
        self.add_button.setAutoDefault(False)
        self.add_button.clicked.connect(self.submit)
        line.addWidget(self.time_edit)
        line.addWidget(self.add_button)
        layout.addLayout(line)
        self.error = QLabel("")
        self.error.setObjectName("fieldError")
        self.error.hide()
        layout.addWidget(self.error)

    def open_at(self, anchor: QWidget, time: QTime) -> None:
        self.time_edit.setTime(time)
        self._check()
        self.adjustSize()
        self.move(anchor.mapToGlobal(QPoint(0, anchor.height() + 4)))
        self.show()
        self.time_edit.setFocus()
        self.time_edit.selectAll()

    def _text(self) -> str:
        return self.time_edit.time().toString("HH:mm")

    def _check(self) -> None:
        duplicate = self._text() in self._row.times()
        self.add_button.setEnabled(not duplicate)
        self.error.setText(f"{self._text()} is already in this schedule." if duplicate else "")
        self.error.setVisible(duplicate)
        self.adjustSize()

    def submit(self) -> None:
        if self._row.add_time(self._text()):
            self.hide()
        else:
            self._check()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            watched is self.time_edit
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            self.submit()
            return True
        return super().eventFilter(watched, event)


class _RuleRow(QFrame):
    """One schedule rule. Emits ``changed`` on any edit; ``remove_requested`` on Remove."""

    changed = Signal()
    remove_requested = Signal(object)

    def __init__(self, rule: ScheduleRule, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)  # the app QSS styles card frames
        self._times: list[str] = sorted(rule.times)
        self._pills: dict[str, _TimePill] = {}
        self.popover: _TimePopover | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.kind = QComboBox()
        for label, key in _KINDS:
            self.kind.addItem(label, key)
        self.kind.setCurrentIndex(max(self.kind.findData(rule.kind), 0))
        self.kind.setFixedWidth(170)
        self.kind.currentIndexChanged.connect(self._on_kind_changed)
        delete = QPushButton("Remove")
        delete.setObjectName("removeSchedule")
        delete.setToolTip("Remove this schedule")
        delete.setAutoDefault(False)
        delete.clicked.connect(lambda *_: self.remove_requested.emit(self))
        top.addWidget(self.kind)
        top.addStretch()
        top.addWidget(delete)
        lay.addLayout(top)

        # Weekly: one row of day toggles (three letters, so T/S are never ambiguous).
        self.weekday_row = QWidget()
        wd_lay = QHBoxLayout(self.weekday_row)
        wd_lay.setContentsMargins(0, 0, 0, 0)
        wd_lay.setSpacing(0)
        wd_lay.addWidget(_row_label("On"))
        self.weekday_checks: dict[str, QPushButton] = {}
        for i, day in enumerate(WEEKDAYS):
            toggle = QPushButton(day.capitalize())
            toggle.setCheckable(True)
            toggle.setChecked(day in rule.weekdays)
            toggle.setAutoDefault(False)
            toggle.setProperty("segment", True)
            toggle.setProperty(
                "segmentPos", "first" if i == 0 else "last" if i == len(WEEKDAYS) - 1 else "mid"
            )
            toggle.setFixedWidth(52)
            toggle.toggled.connect(lambda *_: self.changed.emit())
            self.weekday_checks[day] = toggle
            wd_lay.addWidget(toggle)
        wd_lay.addStretch()
        lay.addWidget(self.weekday_row)

        self.month_days = QLineEdit(", ".join(str(d) for d in rule.month_days))
        self.month_days.setPlaceholderText("e.g. 1, 15")
        self.month_days.setToolTip(
            "Comma-separated days, e.g. 1, 15. Days absent from a month are skipped."
        )
        self.month_days.setMaximumWidth(260)
        self.month_days.textChanged.connect(self.changed)
        self.month_row = QWidget()
        month_lay = QHBoxLayout(self.month_row)
        month_lay.setContentsMargins(0, 0, 0, 0)
        month_lay.setSpacing(8)
        month_lay.addWidget(_row_label("On days"))
        month_lay.addWidget(self.month_days)
        month_lay.addStretch()
        lay.addWidget(self.month_row)

        # Run times: pills, then "+ Add time" at the end of the same row.
        self.times_row = QWidget()
        times_lay = QHBoxLayout(self.times_row)
        times_lay.setContentsMargins(0, 0, 0, 0)
        times_lay.setSpacing(0)
        runs_at = _row_label("Runs at")
        times_lay.addWidget(runs_at, 0, Qt.AlignmentFlag.AlignTop)
        self._pill_box = QWidget()
        self._flow = FlowLayout(self._pill_box, spacing=6)
        self._flow.setContentsMargins(0, 0, 0, 0)
        self.no_times = QLabel("No run times yet")
        self.no_times.setProperty("muted", True)
        self.add_time_button = QPushButton("+ Add time")
        self.add_time_button.setObjectName("addTime")
        self.add_time_button.setAutoDefault(False)
        self.add_time_button.setToolTip("Add a time this schedule runs at")
        self.add_time_button.clicked.connect(self.open_time_picker)
        self._flow.addWidget(self.no_times)
        self._flow.addWidget(self.add_time_button)
        times_lay.addWidget(self._pill_box, 1)
        lay.addWidget(self.times_row)

        self.cron_edit = QPlainTextEdit("\n".join(rule.crons))
        self.cron_edit.setPlaceholderText("0 6 * * MON-FRI\n30 18 1,15 * *")
        self.cron_edit.setToolTip(
            "One cron expression per line: minute hour day-of-month month day-of-week."
        )
        self.cron_edit.setMaximumHeight(70)
        self.cron_edit.textChanged.connect(self.changed)
        lay.addWidget(self.cron_edit)

        for t in self._times:
            self._add_pill(t)
        self._sync_empty()
        self._on_kind_changed()

    # -- kinds --

    def _on_kind_changed(self) -> None:
        kind = self.kind.currentData()
        self.weekday_row.setVisible(kind == "weekly")
        self.month_row.setVisible(kind == "monthly")
        self.times_row.setVisible(kind != "cron")
        self.cron_edit.setVisible(kind == "cron")
        self.changed.emit()

    # -- run times --

    def times(self) -> list[str]:
        return list(self._times)

    def _next_free_time(self) -> QTime:
        """A sensible first guess: an hour after the last time, never one already added."""
        if not self._times:
            return QTime(6, 0)
        hour, minute = (int(x) for x in self._times[-1].split(":"))
        for step in range(1, 25):
            candidate = QTime((hour + step) % 24, minute)
            if candidate.toString("HH:mm") not in self._times:
                return candidate
        return QTime(6, 0)

    def open_time_picker(self) -> _TimePopover:
        if self.popover is None:
            self.popover = _TimePopover(self)
        self.popover.open_at(self.add_time_button, self._next_free_time())
        return self.popover

    def add_time(self, t: str) -> bool:
        """Add run time ``t`` ("HH:MM"); False when the schedule already has it."""
        if t in self._times:
            return False
        self._times.append(t)
        self._times.sort()
        pill = self._add_pill(t)
        self._sync_empty()
        flash(pill)  # show where it landed
        self.changed.emit()
        return True

    def remove_time(self, t: str) -> None:
        if t not in self._times:
            return
        self._times.remove(t)
        pill = self._pills.pop(t)
        self._flow.removeWidget(pill)
        pill.hide()
        pill.deleteLater()
        self._sync_empty()
        self.changed.emit()

    def pill(self, t: str) -> _TimePill | None:
        return self._pills.get(t)

    def _add_pill(self, t: str) -> _TimePill:
        pill = _TimePill(t)
        pill.remove_requested.connect(self.remove_time)
        self._pills[t] = pill
        # Kept in time order, before the "No run times" label and the Add button.
        self._flow.insertWidget(self._times.index(t), pill)
        self._pill_box.updateGeometry()
        return pill

    def _sync_empty(self) -> None:
        self.no_times.setVisible(not self._times)
        self._flow.invalidate()

    def to_rule(self) -> ScheduleRule:
        kind = self.kind.currentData()
        if kind == "cron":
            crons = [line for line in self.cron_edit.toPlainText().splitlines() if line.strip()]
            return ScheduleRule(kind="cron", crons=crons)
        return ScheduleRule(
            kind=kind,
            times=self.times(),
            weekdays=[d for d, toggle in self.weekday_checks.items() if toggle.isChecked()],
            month_days=_parse_month_days(self.month_days.text()) if kind == "monthly" else [],
        )


class ScheduleWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[_RuleRow] = []
        self._build()

    # -- construction ------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.summary = QLabel("")
        self.summary.setObjectName("scheduleOverview")
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.manual_hint = QLabel(
            "Manual — this job only runs when you click Run. Add a schedule to run it "
            "automatically; add more than one to combine them (e.g. daily, plus Sunday at "
            "another time)."
        )
        self.manual_hint.setProperty("muted", True)
        self.manual_hint.setWordWrap(True)
        layout.addWidget(self.manual_hint)
        zone_hint = QLabel(
            "Times use the ReportFlow server’s local time (24-hour clock). "
            "Each schedule adds runs; overlapping runs are not allowed."
        )
        zone_hint.setProperty("muted", True)
        zone_hint.setWordWrap(True)
        layout.addWidget(zone_hint)

        self._rules_lay = QVBoxLayout()
        self._rules_lay.setSpacing(10)
        layout.addLayout(self._rules_lay)

        add = QPushButton("+ Add schedule")
        add.setToolTip("Add a daily, weekly, monthly or custom schedule to this job.")
        add.clicked.connect(lambda *_: self.add_rule(ScheduleRule(kind="daily")))
        add_row = QHBoxLayout()
        add_row.addWidget(add)
        add_row.addStretch()
        layout.addLayout(add_row)

        self._update_summary()

    # -- behavior ----------------------------------------------------------------

    def add_rule(self, rule: ScheduleRule) -> _RuleRow:
        row = _RuleRow(rule, self)
        row.changed.connect(self._update_summary)
        row.remove_requested.connect(self._remove_row)
        self._rows.append(row)
        self._rules_lay.addWidget(row)
        self._update_summary()
        return row

    def _remove_row(self, row: _RuleRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
            self._rules_lay.removeWidget(row)
            row.deleteLater()
        self._update_summary()

    def _update_summary(self) -> None:
        self.manual_hint.setVisible(not self._rows)
        try:
            crons = self.to_crons()
        except ValueError as e:
            self.summary.setText(f"Check schedule: {e}")
            self._set_summary_state("warning")
            return
        self._set_summary_state("")
        self.summary.setText(describe(crons) if crons else "Manual only — no scheduled runs")

    def _set_summary_state(self, state: str) -> None:
        self.summary.setProperty("state", state)
        self.summary.style().unpolish(self.summary)
        self.summary.style().polish(self.summary)

    # -- public API ----------------------------------------------------------------

    def rows(self) -> list[_RuleRow]:
        return list(self._rows)

    def to_rules(self) -> list[ScheduleRule]:
        return [row.to_rule() for row in self._rows]

    def to_crons(self) -> list[str]:
        """Compile every rule; raises ValueError with a user-facing message."""
        return compile_rules(self.to_rules())

    def load(self, crons: list[str]) -> None:
        for row in list(self._rows):
            self._remove_row(row)
        for rule in parse_crons(crons):
            self.add_rule(rule)
        self._update_summary()
