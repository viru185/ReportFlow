"""Main window: job list, actions, health banner. Talks only to the local API."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.api_client import ApiClient, ApiError
from reportflow.ui.windows.job_editor import JobEditorDialog
from reportflow.ui.windows.log_view import RunHistoryDialog

_COLUMNS = ["Job", "Enabled", "Schedule", "Last status", "Last run"]


class MainWindow(QMainWindow):
    def __init__(self, api: ApiClient | None = None) -> None:
        super().__init__()
        self._api = api or ApiClient()
        self.setWindowTitle("ReportFlow")
        self.resize(880, 520)
        self._build()

        self._timer = QTimer(self)
        self._timer.setInterval(4000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def _build(self) -> None:
        self.banner = QLabel("")
        self.banner.setStyleSheet("color: white; background: #b00; padding: 4px;")
        self.banner.hide()

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(lambda *_: self._edit_job())

        def _btn(label, slot):
            b = QPushButton(label)
            b.clicked.connect(slot)
            return b

        buttons = QHBoxLayout()
        for label, slot in [
            ("New", self._new_job),
            ("Edit", self._edit_job),
            ("Delete", self._delete_job),
            ("Run now", lambda: self._trigger(test=False)),
            ("Test run", lambda: self._trigger(test=True)),
            ("View logs", self._view_logs),
            ("Send dev logs", self._send_dev_logs),
            ("Refresh", self.refresh),
        ]:
            buttons.addWidget(_btn(label, slot))
        buttons.addStretch()

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.banner)
        layout.addLayout(buttons)
        layout.addWidget(self.table)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Starting…")

    # -- data --------------------------------------------------------------------

    def refresh(self) -> None:
        try:
            status = self._api.system_status()
            jobs = self._api.list_jobs()
        except ApiError as e:
            self.banner.setText(f"Service not reachable — {e}")
            self.banner.show()
            self.statusBar().showMessage("Disconnected")
            return
        self.banner.hide()
        self.statusBar().showMessage(
            f"Connected · v{status.get('version')} · "
            f"{len(status.get('active_runs', []))} active · "
            f"{len(status.get('scheduled_jobs', []))} scheduled"
        )
        self._populate(jobs)

    def _populate(self, jobs: list[dict]) -> None:
        selected = self._selected_job_name()
        self.table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            values = [
                job.get("name", ""),
                "yes" if job.get("enabled") else "no",
                job.get("schedule_cron") or "—",
                (job.get("last_status") or "—"),
                (job.get("last_run_at") or "—"),
            ]
            for col, val in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(val)))
            if job.get("name") == selected:
                self.table.selectRow(row)

    def _selected_job_name(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.text() if item is not None else None

    # -- actions -----------------------------------------------------------------

    def _new_job(self) -> None:
        dlg = JobEditorDialog(self._api, None, self)
        if dlg.exec() == JobEditorDialog.DialogCode.Accepted:
            self._save(dlg.payload(), create=True)

    def _edit_job(self) -> None:
        name = self._require_selection()
        if not name:
            return
        try:
            job = self._api.get_job(name)["job"]
        except ApiError as e:
            QMessageBox.warning(self, "Error", str(e))
            return
        dlg = JobEditorDialog(self._api, job, self)
        if dlg.exec() == JobEditorDialog.DialogCode.Accepted:
            self._save(dlg.payload(), create=False)

    def _save(self, payload: dict, *, create: bool) -> None:
        try:
            if create:
                self._api.create_job(payload)
            else:
                self._api.update_job(payload["name"], payload)
        except ApiError as e:
            QMessageBox.warning(self, "Save failed", str(e))
            return
        self.refresh()

    def _delete_job(self) -> None:
        name = self._require_selection()
        if not name:
            return
        confirm = QMessageBox.question(self, "Delete", f"Delete job {name!r}?")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self._api.delete_job(name)
        except ApiError as e:
            QMessageBox.warning(self, "Delete failed", str(e))
            return
        self.refresh()

    def _trigger(self, *, test: bool) -> None:
        name = self._require_selection()
        if not name:
            return
        try:
            resp = self._api.test_job(name) if test else self._api.run_job(name)
        except ApiError as e:
            QMessageBox.warning(self, "Run failed", str(e))
            return
        kind = "Test run" if test else "Run"
        self.statusBar().showMessage(f"{kind} started for {name} (run {resp['run_id']})")
        RunHistoryDialog(self._api, name, self).exec()

    def _view_logs(self) -> None:
        RunHistoryDialog(self._api, self._selected_job_name(), self).exec()

    def _send_dev_logs(self) -> None:
        if (
            QMessageBox.question(
                self, "Send developer logs", "Send the full log bundle to the developer recipients?"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            resp = self._api.send_dev_logs()
        except ApiError as e:
            QMessageBox.warning(self, "Send failed", str(e))
            return
        QMessageBox.information(
            self, "Sent", f"Bundle sent to: {', '.join(resp.get('recipients', []))}"
        )

    def _require_selection(self) -> str | None:
        name = self._selected_job_name()
        if not name:
            QMessageBox.information(self, "No selection", "Select a job first.")
        return name
