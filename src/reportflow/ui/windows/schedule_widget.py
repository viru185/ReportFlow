"""Visual schedule builder: a list of rules — Daily / Weekly / Monthly / Custom (cron).

A job can combine rules, e.g. "daily at 06:00" plus "every Sunday at 10:00". Each rule has
its own run-times (several per day are fine); every time is a chip with its own ✕, and each
rule its own Delete. No rules = manual only. Compiles to a list of cron expressions via the
pure ``schedule_compile`` helpers.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTime, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.schedule_compile import (
    WEEKDAYS,
    ScheduleRule,
    compile_rules,
    describe,
    parse_crons,
)
from reportflow.ui.widgets import section_title

_KINDS = [
    ("Daily", "daily"),
    ("Weekly", "weekly"),
    ("Monthly", "monthly"),
    ("Custom (cron)", "cron"),
]


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


class _RuleRow(QFrame):
    """One schedule rule. Emits ``changed`` on any edit; ``remove_requested`` on Delete."""

    changed = Signal()
    remove_requested = Signal(object)

    def __init__(self, rule: ScheduleRule, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)  # the app QSS styles card frames
        self._times: list[str] = list(rule.times)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.kind = QComboBox()
        for label, key in _KINDS:
            self.kind.addItem(label, key)
        self.kind.setCurrentIndex(max(self.kind.findData(rule.kind), 0))
        self.kind.currentIndexChanged.connect(self._on_kind_changed)
        delete = QPushButton("Delete schedule")
        delete.setToolTip("Delete this schedule")
        delete.clicked.connect(lambda *_: self.remove_requested.emit(self))
        top.addWidget(self.kind)
        top.addStretch()
        top.addWidget(delete)
        lay.addLayout(top)

        self.weekday_row = QWidget()
        wd_lay = QHBoxLayout(self.weekday_row)
        wd_lay.setContentsMargins(0, 0, 0, 0)
        wd_lay.setSpacing(12)
        self.weekday_checks: dict[str, QCheckBox] = {}
        for day in WEEKDAYS:
            cb = QCheckBox(day.capitalize())
            cb.setChecked(day in rule.weekdays)
            cb.toggled.connect(self.changed)
            self.weekday_checks[day] = cb
            wd_lay.addWidget(cb)
        wd_lay.addStretch()
        lay.addWidget(self.weekday_row)

        self.month_days = QLineEdit(", ".join(str(d) for d in rule.month_days))
        self.month_days.setPlaceholderText("Days of the month, e.g. 1, 15")
        self.month_days.setToolTip(
            "Comma-separated days, e.g. 1, 15. Days absent from a month are skipped."
        )
        self.month_days.textChanged.connect(self.changed)
        self.month_row = QWidget()
        month_lay = QHBoxLayout(self.month_row)
        month_lay.setContentsMargins(0, 0, 0, 0)
        month_lay.setSpacing(8)
        month_lay.addWidget(QLabel("Days of the month:"))
        month_lay.addWidget(self.month_days)
        lay.addWidget(self.month_row)

        self.times_row = QWidget()
        times_lay = QVBoxLayout(self.times_row)
        times_lay.setContentsMargins(0, 0, 0, 0)
        times_lay.setSpacing(12)
        times_lay.addWidget(section_title("Added run times"))
        # Chips live in their own layout so they can be rebuilt without touching the picker.
        self._chips = QGridLayout()
        self._chips.setSpacing(8)
        self._chips.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._chips.setColumnStretch(4, 1)
        times_lay.addLayout(self._chips)
        self.time_edit = QTimeEdit(QTime(6, 0))
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setToolTip("Pick a run time, then click Add. Add several to run more often.")
        self.add_time_button = QPushButton("Add time")
        add_time = self.add_time_button
        add_time.setAutoDefault(False)
        add_time.setToolTip("Add this run time")
        add_time.clicked.connect(self._add_time)
        picker = QHBoxLayout()
        picker.setSpacing(8)
        picker.addWidget(QLabel("New time"))
        picker.addWidget(self.time_edit)
        picker.addWidget(add_time)
        picker.addStretch()
        self.picker_row = QWidget()
        picker_layout = QVBoxLayout(self.picker_row)
        picker_layout.setContentsMargins(0, 0, 0, 0)
        picker_layout.setSpacing(8)
        picker_layout.addLayout(picker)
        self.time_hint = QLabel()
        self.time_hint.setProperty("muted", True)
        self.time_hint.setWordWrap(True)
        picker_layout.addWidget(self.time_hint)
        self.time_edit.timeChanged.connect(self._update_time_picker)
        # Give saved times the first reading position, above the editing controls.
        lay.insertWidget(1, self.times_row)
        lay.addWidget(self.picker_row)

        self.cron_edit = QPlainTextEdit("\n".join(rule.crons))
        self.cron_edit.setPlaceholderText("0 6 * * MON-FRI\n30 18 1,15 * *")
        self.cron_edit.setToolTip(
            "One cron expression per line: minute hour day-of-month month day-of-week."
        )
        self.cron_edit.setMaximumHeight(70)
        self.cron_edit.textChanged.connect(self.changed)
        lay.addWidget(self.cron_edit)

        self._render_chips()
        self._on_kind_changed()

    def _on_kind_changed(self) -> None:
        kind = self.kind.currentData()
        self.weekday_row.setVisible(kind == "weekly")
        self.month_row.setVisible(kind == "monthly")
        self.times_row.setVisible(kind != "cron")
        self.picker_row.setVisible(kind != "cron")
        self.cron_edit.setVisible(kind == "cron")
        self.changed.emit()

    def _render_chips(self) -> None:
        while self._chips.count():
            item = self._chips.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        if not self._times:
            none = QLabel("No run times selected. Choose a time below and click Add time.")
            none.setProperty("muted", True)
            self._chips.addWidget(none, 0, 0)
        for i, t in enumerate(self._times):
            chip = QPushButton(f"{t}  ×")
            chip.setAutoDefault(False)
            chip.setAccessibleName(f"Remove run time {t}")
            chip.setToolTip(f"Remove {t}")
            chip.setProperty("timeChip", True)
            chip.setMinimumWidth(100)
            chip.clicked.connect(self._remover(t))
            self._chips.addWidget(chip, i // 4, i % 4)
        self._update_time_picker()

    def _update_time_picker(self) -> None:
        duplicate = self.time_edit.time().toString("HH:mm") in self._times
        self.add_time_button.setEnabled(not duplicate)
        self.time_hint.setText(
            "This time is already selected. Choose a different time to add another run."
            if duplicate
            else "The time above is included only after you click Add time."
        )

    def _remover(self, t: str) -> Callable[..., None]:
        def remove(*_: object) -> None:
            if t in self._times:
                self._times.remove(t)
            self._render_chips()
            self.changed.emit()

        return remove

    def _add_time(self) -> None:
        t = self.time_edit.time().toString("HH:mm")
        if t not in self._times:
            self._times.append(t)
            self._times.sort()
            self._render_chips()
        self.changed.emit()

    def times(self) -> list[str]:
        return list(self._times)

    def to_rule(self) -> ScheduleRule:
        kind = self.kind.currentData()
        if kind == "cron":
            crons = [line for line in self.cron_edit.toPlainText().splitlines() if line.strip()]
            return ScheduleRule(kind="cron", crons=crons)
        return ScheduleRule(
            kind=kind,
            times=self.times(),
            weekdays=[d for d, cb in self.weekday_checks.items() if cb.isChecked()],
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
        layout.setSpacing(16)

        layout.addWidget(section_title("Schedule overview"))
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
        self._rules_lay.setSpacing(16)
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
            self.summary.setStyleSheet("color: #fbbf24;")
            return
        self.summary.setStyleSheet("")
        self.summary.setText(describe(crons) if crons else "Manual only — no scheduled runs")

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
