"""Run history + log viewer dialog with live polling for in-flight runs."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.api_client import ApiClient, ApiError


class RunHistoryDialog(QDialog):
    def __init__(self, api: ApiClient, job_name: str | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._job = job_name
        self.setWindowTitle(f"Run history — {job_name}" if job_name else "Run history")
        self.resize(760, 520)

        self.runs = QListWidget()
        self.runs.currentItemChanged.connect(lambda *_: self._show_selected())
        self.details = QLabel("Select a run")
        self.details.setWordWrap(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)

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
        self.details.setText(
            f"<b>{r['run_id']}</b> — {r['status'].upper()}<br>"
            f"trigger: {r.get('trigger')} | test: {r.get('is_test')}<br>"
            f"started: {r.get('started_at')} | finished: {r.get('finished_at')}<br>"
            f"output: {r.get('output_xlsx') or '—'}<br>"
            f"error: {r.get('error_summary') or '—'}"
        )
        try:
            self.log.setPlainText(self._api.get_run_log(r["run_id"]).get("log", ""))
        except ApiError as e:
            self.log.setPlainText(f"(could not load log: {e})")

    def _poll(self) -> None:
        item = self.runs.currentItem()
        if item and item.data(0x0100)["status"] == "running":
            self.reload()
            self._show_selected()
