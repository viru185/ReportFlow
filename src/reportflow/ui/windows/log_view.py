"""Run history + live log viewer: splitter layout, compact header, filter + search.

Doubles as the history browser and the live run monitor (polls while a run is in-flight).
Log colouring/filtering is shared with the application-log viewer via ``log_format``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.api_client import ApiClient, ApiError
from reportflow.ui.log_format import LogHighlighter, filter_log_text
from reportflow.ui.style import status_badge

_TERMINAL_STATUSES = frozenset({"success", "failed", "timed_out", "crashed"})
_LEVELS = ("All", "Debug", "Info", "Success", "Warning", "Error")


class RunHistoryDialog(QDialog):
    def __init__(self, api: ApiClient, job_name: str | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._job = job_name
        self._raw_log = ""
        self._email_alerted: set[str] = set()  # run_ids we've already flagged
        self.setWindowTitle(f"Run history — {job_name}" if job_name else "Run history")
        self.resize(880, 560)

        # -- left: runs list --
        self.runs = QListWidget()
        self.runs.currentItemChanged.connect(lambda *_: self._show_selected())
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.addWidget(QLabel("Runs"))
        left_lay.addWidget(self.runs)

        # -- right: compact header + email banner + filters + log --
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)

        header_row = QHBoxLayout()
        self.status_badge_holder = QHBoxLayout()  # swapped badge widget lives here
        self._badge: QLabel | None = None
        header_row.addLayout(self.status_badge_holder)
        self.details = QLabel("Select a run")
        self.details.setWordWrap(True)
        header_row.addWidget(self.details, 1)
        right_lay.addLayout(header_row)

        self.email_banner = QLabel("")
        self.email_banner.setWordWrap(True)
        self.email_banner.setStyleSheet(
            "QLabel { background: #3b1a1a; color: #f8b4b4; border: 1px solid #a33; "
            "border-radius: 4px; padding: 4px 8px; }"
        )
        self.email_banner.setVisible(False)
        right_lay.addWidget(self.email_banner)

        self.level = QComboBox()
        self.level.addItems(_LEVELS)
        self.level.setToolTip("Only show log lines at or above this level.")
        self.level.currentIndexChanged.connect(lambda *_: self._render_log())
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip("Filter to matching lines and highlight the text.")
        self.search.textChanged.connect(lambda *_: self._render_log())
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Level:"))
        filter_row.addWidget(self.level)
        filter_row.addWidget(self.search, 1)
        right_lay.addLayout(filter_row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.log.setFont(mono)
        self._highlighter = LogHighlighter(self.log.document())
        right_lay.addWidget(self.log, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([220, 640])

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.reload)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        btns = QHBoxLayout()
        btns.addWidget(refresh)
        btns.addStretch()
        btns.addWidget(close)

        root = QVBoxLayout(self)
        root.addWidget(splitter, 1)
        root.addLayout(btns)

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

        self.reload()

    def reload(self) -> None:
        try:
            runs = self._api.list_runs(self._job, limit=50)
        except ApiError as e:
            self.details.setText(f"Could not load runs: {e}")
            return
        if not hasattr(self, "_seeded"):
            # First load: don't flag runs that already finished before this dialog opened —
            # only surface email failures for transitions we witness.
            self._email_alerted = {
                r["run_id"] for r in runs if r.get("status") in _TERMINAL_STATUSES
            }
            self._seeded = True
        current = self._current_run_id()
        self.runs.clear()
        for r in runs:
            label = f"{r.get('started_at', '?')}  {r['status'].upper()}  {r['run_id']}"
            item = QListWidgetItem(label)
            item.setData(0x0100, r)  # Qt.UserRole
            self.runs.addItem(item)
            if r["run_id"] == current:
                self.runs.setCurrentItem(item)
        if self.runs.currentItem() is None and self.runs.count():
            self.runs.setCurrentRow(0)

    def _current_run_id(self) -> str | None:
        item = self.runs.currentItem()
        return item.data(0x0100)["run_id"] if item else None

    def _set_badge(self, status: str | None) -> None:
        if self._badge is not None:
            self._badge.deleteLater()
        self._badge = status_badge(status)
        self.status_badge_holder.addWidget(self._badge)

    def _show_selected(self) -> None:
        item = self.runs.currentItem()
        if item is None:
            return
        r = item.data(0x0100)
        self._set_badge(r.get("status"))
        warnings = r.get("warnings") or []
        warn_line = (
            f"<br><span style='color:#fbbf24;'>warnings: {'; '.join(warnings)}</span>"
            if warnings
            else ""
        )
        duration = r.get("duration_seconds")
        took = f" · took {duration:.0f}s" if isinstance(duration, int | float) else ""
        self.details.setText(
            f"<b>{r['run_id']}</b> · trigger: {r.get('trigger')} · test: {r.get('is_test')}<br>"
            f"started: {r.get('started_at')} · finished: {r.get('finished_at') or '—'}{took}<br>"
            f"output: {r.get('output_xlsx') or '—'}<br>"
            f"email: {r.get('email_note') or '—'}"
            f"{('<br>error: ' + r['error_summary']) if r.get('error_summary') else ''}"
            f"{warn_line}"
        )
        self._maybe_flag_email(r)
        try:
            self._raw_log = self._api.get_run_log(r["run_id"]).get("log", "")
        except ApiError as e:
            self._raw_log = f"(could not load log: {e})"
        self._render_log(live=r.get("status") == "running")

    def _render_log(self, *, live: bool = False) -> None:
        min_level = self.level.currentText()
        min_level = "" if min_level == "All" else min_level
        search = self.search.text().strip()
        shown = filter_log_text(self._raw_log, min_level=min_level, search=search)
        self._highlighter.set_search(search)
        if shown == self.log.toPlainText():
            return
        bar = self.log.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        self.log.setPlainText(shown)
        if at_bottom or live:
            bar.setValue(bar.maximum())

    def _maybe_flag_email(self, r: dict) -> None:
        """Surface a failed report email as an inline banner (never a modal mid-poll)."""
        note = r.get("email_note") or ""
        if r.get("status") in _TERMINAL_STATUSES and note.startswith("failed:"):
            self.email_banner.setText(
                f"✉ The report email for this run failed to send: {note}\n"
                "Check the SMTP settings (File → Settings) and the recipients."
            )
            self.email_banner.setVisible(True)
        else:
            self.email_banner.setVisible(False)

    def _poll(self) -> None:
        item = self.runs.currentItem()
        if item and item.data(0x0100)["status"] == "running":
            self.reload()
            self._show_selected()
