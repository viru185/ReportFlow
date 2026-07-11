"""Run history + log viewer dialog with live polling for in-flight runs."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.api_client import ApiClient, ApiError
from reportflow.ui.log_format import LogHighlighter

_TERMINAL_STATUSES = frozenset({"success", "failed", "timed_out", "crashed"})


class RunHistoryDialog(QDialog):
    def __init__(self, api: ApiClient, job_name: str | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._job = job_name
        self._email_alerted: set[str] = set()  # run_ids we've already warned about
        self.setWindowTitle(f"Run history — {job_name}" if job_name else "Run history")
        self.resize(760, 520)

        self.runs = QListWidget()
        self.runs.currentItemChanged.connect(lambda *_: self._show_selected())
        self.details = QLabel("Select a run")
        self.details.setWordWrap(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self._highlighter = LogHighlighter(self.log.document())

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.reload)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)

        left = QVBoxLayout()
        left.addWidget(QLabel("Runs"))
        left.addWidget(self.runs)
        right = QVBoxLayout()
        right.addWidget(self.details)
        right.addWidget(self.log)
        btns = QHBoxLayout()
        btns.addWidget(refresh)
        btns.addStretch()
        btns.addWidget(close)

        body = QHBoxLayout()
        body.addLayout(left, 1)
        body.addLayout(right, 2)
        root = QVBoxLayout(self)
        root.addLayout(body)
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
            # First load: don't pop email alerts for runs that already finished before this
            # dialog opened — only warn about transitions we witness.
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

    def _show_selected(self) -> None:
        item = self.runs.currentItem()
        if item is None:
            return
        r = item.data(0x0100)
        warnings = r.get("warnings") or []
        warn_line = (
            f"<br><span style='color:#fbbf24;'>warnings: {'; '.join(warnings)}</span>"
            if warnings
            else ""
        )
        self.details.setText(
            f"<b>{r['run_id']}</b> — {r['status'].upper()}<br>"
            f"trigger: {r.get('trigger')} | test: {r.get('is_test')}<br>"
            f"started: {r.get('started_at')} | finished: {r.get('finished_at')}<br>"
            f"output: {r.get('output_xlsx') or '—'}<br>"
            f"email: {r.get('email_note') or '—'}<br>"
            f"error: {r.get('error_summary') or '—'}"
            f"{warn_line}"
        )
        try:
            text = self._api.get_run_log(r["run_id"]).get("log", "")
        except ApiError as e:
            text = f"(could not load log: {e})"
        # Only re-set when changed, and keep the view pinned to the newest lines while a run
        # is live or the user is already reading the bottom (setPlainText resets to the top).
        if text != self.log.toPlainText():
            bar = self.log.verticalScrollBar()
            at_bottom = bar.value() >= bar.maximum() - 4
            self.log.setPlainText(text)
            if at_bottom or r.get("status") == "running":
                bar.setValue(bar.maximum())
        self._maybe_alert_email(r)

    def _maybe_alert_email(self, r: dict) -> None:
        """Warn once when a finished run's report email failed (else it fails silently)."""
        if r.get("status") not in _TERMINAL_STATUSES:
            return
        run_id = r.get("run_id", "")
        note = r.get("email_note") or ""
        if note.startswith("failed:") and run_id not in self._email_alerted:
            self._email_alerted.add(run_id)
            QMessageBox.warning(
                self,
                "Report email not sent",
                f"Run {run_id} built its report, but sending the email failed:\n\n{note}\n\n"
                "Check the SMTP settings (File → Settings) and the recipients.",
            )

    def _poll(self) -> None:
        item = self.runs.currentItem()
        if item and item.data(0x0100)["status"] == "running":
            self.reload()
            self._show_selected()
