"""Visual schedule builder: Manual / Daily / Weekly / Monthly / Advanced (cron).

Daily/Weekly/Monthly share a times list (add several run-times per day). Compiles to a
list of cron expressions via the pure ``schedule_compile`` helpers.
"""

from __future__ import annotations

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.schedule_compile import (
    WEEKDAYS,
    ScheduleSpec,
    compile_spec,
    describe,
    parse_crons,
)

_MODES = [
    ("Manual (no schedule)", "manual"),
    ("Daily", "daily"),
    ("Weekly", "weekly"),
    ("Monthly", "monthly"),
    ("Advanced (cron)", "advanced"),
]


class ScheduleWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build()

    # -- construction ------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.mode = QComboBox()
        for label, _key in _MODES:
            self.mode.addItem(label)
        self.mode.setToolTip(
            "Manual: run only via the Run/Test buttons. Daily/Weekly/Monthly: pick run "
            "times below. Advanced: raw cron expressions, one per line."
        )
        self.mode.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode)

        self.stack = QStackedWidget()

        # Page 0: manual — nothing to configure.
        manual_page = QWidget()
        manual_lay = QVBoxLayout(manual_page)
        manual_hint = QLabel("This job only runs when you click Run or Test.")
        manual_hint.setProperty("muted", True)
        manual_lay.addWidget(manual_hint)
        manual_lay.addStretch()

        # Page 1: preset (daily/weekly/monthly) — times + day pickers.
        preset_page = QWidget()
        preset_lay = QVBoxLayout(preset_page)

        self.weekday_row = QWidget()
        wd_lay = QHBoxLayout(self.weekday_row)
        wd_lay.setContentsMargins(0, 0, 0, 0)
        self.weekday_checks: dict[str, QCheckBox] = {}
        for day in WEEKDAYS:
            cb = QCheckBox(day.capitalize())
            self.weekday_checks[day] = cb
            wd_lay.addWidget(cb)
        wd_lay.addStretch()
        preset_lay.addWidget(self.weekday_row)

        self.monthday_row = QWidget()
        md_lay = QGridLayout(self.monthday_row)
        md_lay.setContentsMargins(0, 0, 0, 0)
        self.monthday_checks: dict[int, QCheckBox] = {}
        for d in range(1, 32):
            cb = QCheckBox(str(d))
            self.monthday_checks[d] = cb
            md_lay.addWidget(cb, (d - 1) // 8, (d - 1) % 8)
        preset_lay.addWidget(self.monthday_row)

        times_row = QHBoxLayout()
        self.time_edit = QTimeEdit(QTime(6, 0))
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setToolTip(
            "Pick a run time, then click Add. Add several for multiple runs per day."
        )
        add_time = QPushButton("Add time")
        add_time.clicked.connect(self._add_time)
        remove_time = QPushButton("Remove selected")
        remove_time.clicked.connect(self._remove_time)
        times_row.addWidget(QLabel("Run at:"))
        times_row.addWidget(self.time_edit)
        times_row.addWidget(add_time)
        times_row.addWidget(remove_time)
        times_row.addStretch()
        preset_lay.addLayout(times_row)

        self.times_list = QListWidget()
        self.times_list.setMaximumHeight(84)
        self.times_list.setToolTip("The job runs at each of these times.")
        preset_lay.addWidget(self.times_list)

        # Page 2: advanced — raw cron lines.
        advanced_page = QWidget()
        adv_lay = QVBoxLayout(advanced_page)
        self.cron_edit = QPlainTextEdit()
        self.cron_edit.setPlaceholderText("0 6 * * MON-FRI\n30 18 1,15 * *")
        self.cron_edit.setToolTip(
            "One cron expression per line: minute hour day-of-month month day-of-week."
        )
        self.cron_edit.setMaximumHeight(90)
        adv_lay.addWidget(QLabel("Cron expressions (one per line):"))
        adv_lay.addWidget(self.cron_edit)

        self.stack.addWidget(manual_page)
        self.stack.addWidget(preset_page)
        self.stack.addWidget(advanced_page)
        layout.addWidget(self.stack)

        self.summary = QLabel("")
        self.summary.setProperty("muted", True)
        layout.addWidget(self.summary)

        self._on_mode_changed()

    # -- behavior ----------------------------------------------------------------

    def _mode_key(self) -> str:
        return _MODES[self.mode.currentIndex()][1]

    def _on_mode_changed(self) -> None:
        key = self._mode_key()
        if key == "manual":
            self.stack.setCurrentIndex(0)
        elif key == "advanced":
            self.stack.setCurrentIndex(2)
        else:
            self.stack.setCurrentIndex(1)
            self.weekday_row.setVisible(key == "weekly")
            self.monthday_row.setVisible(key == "monthly")
        self._update_summary()

    def _add_time(self) -> None:
        t = self.time_edit.time().toString("HH:mm")
        existing = [self.times_list.item(i).text() for i in range(self.times_list.count())]
        if t not in existing:
            self.times_list.addItem(t)
            self.times_list.sortItems()
        self._update_summary()

    def _remove_time(self) -> None:
        for item in self.times_list.selectedItems():
            self.times_list.takeItem(self.times_list.row(item))
        self._update_summary()

    def _times(self) -> list[str]:
        return [self.times_list.item(i).text() for i in range(self.times_list.count())]

    def _update_summary(self) -> None:
        try:
            self.summary.setText(describe(self.to_crons()))
        except ValueError:
            self.summary.setText("")

    # -- public API ----------------------------------------------------------------

    def to_spec(self) -> ScheduleSpec:
        key = self._mode_key()
        if key == "manual":
            return ScheduleSpec(mode="manual")
        if key == "advanced":
            crons = [line for line in self.cron_edit.toPlainText().splitlines() if line.strip()]
            return ScheduleSpec(mode="advanced", crons=crons)
        weekdays = [d for d, cb in self.weekday_checks.items() if cb.isChecked()]
        month_days = [d for d, cb in self.monthday_checks.items() if cb.isChecked()]
        return ScheduleSpec(mode=key, times=self._times(), weekdays=weekdays, month_days=month_days)  # type: ignore[arg-type]

    def to_crons(self) -> list[str]:
        """Compile the current selection; raises ValueError with a user-facing message."""
        return compile_spec(self.to_spec())

    def load(self, crons: list[str]) -> None:
        spec = parse_crons(crons)
        keys = [k for _label, k in _MODES]
        self.mode.setCurrentIndex(keys.index(spec.mode))
        self.times_list.clear()
        for t in spec.times:
            self.times_list.addItem(t)
        for day, cb in self.weekday_checks.items():
            cb.setChecked(day in spec.weekdays)
        for d, cb in self.monthday_checks.items():
            cb.setChecked(d in spec.month_days)
        self.cron_edit.setPlainText("\n".join(spec.crons))
        self._on_mode_changed()
