"""Dashboard main window: header + summary cards + job cards, with a menu bar.

Talks only to the local API. Presentation lives here; all actions go through the same
ApiClient methods regardless of where they're triggered (menu, card button, …).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from reportflow import __about__ as about
from reportflow.ui.api_client import ApiClient, ApiError
from reportflow.ui.assets import logo_pixmap
from reportflow.ui.schedule_compile import describe
from reportflow.ui.style import card_frame, connection_pill, status_badge
from reportflow.ui.windows.about_dialog import AboutDialog
from reportflow.ui.windows.help_dialog import HelpDialog
from reportflow.ui.windows.job_editor import JobEditorDialog
from reportflow.ui.windows.log_view import RunHistoryDialog
from reportflow.ui.windows.log_viewer_dialog import LogViewerDialog
from reportflow.ui.windows.settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self, api: ApiClient | None = None) -> None:
        super().__init__()
        self._api = api or ApiClient()
        self._connected = False
        self.setWindowTitle(about.NAME)
        self.resize(920, 640)
        self._build_menu()
        self._build()

        self._timer = QTimer(self)
        self._timer.setInterval(4000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    # -- construction ------------------------------------------------------------

    def _build_menu(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        file_menu.addAction("Settings…", self._open_settings)
        file_menu.addAction("Application logs…", self._open_app_logs)
        file_menu.addAction("Send developer logs", self._send_dev_logs)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        jobs_menu = bar.addMenu("&Jobs")
        jobs_menu.addAction("New job…", self._new_job)
        jobs_menu.addAction("Refresh", self.refresh)

        help_menu = bar.addMenu("&Help")
        help_menu.addAction("Help guide", self._open_help)
        help_menu.addAction(f"About {about.NAME}", self._open_about)

    def _build(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(10)

        # Header: logo + title + connection pill
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(logo_pixmap(34))
        title = QLabel(about.NAME)
        title.setProperty("h1", True)
        self.conn_label = QLabel(connection_pill(False))
        header.addWidget(logo)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.conn_label)
        root.addLayout(header)

        # Summary cards
        cards_row = QHBoxLayout()
        self.card_jobs = self._summary_card("Jobs", "0")
        self.card_active = self._summary_card("Active runs", "0")
        self.card_failures = self._summary_card("Recent failures", "0")
        for card, _value in (self.card_jobs, self.card_active, self.card_failures):
            cards_row.addWidget(card)
        cards_row.addStretch()
        root.addLayout(cards_row)

        # Actions row
        actions = QHBoxLayout()
        new_btn = QPushButton("+ New Job")
        new_btn.setProperty("accent", True)
        new_btn.clicked.connect(self._new_job)
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.clicked.connect(self.refresh)
        actions.addWidget(new_btn)
        actions.addStretch()
        actions.addWidget(refresh_btn)
        root.addLayout(actions)

        # Job cards in a scroll area
        self.jobs_container = QWidget()
        self.jobs_layout = QVBoxLayout(self.jobs_container)
        self.jobs_layout.setContentsMargins(0, 0, 0, 0)
        self.jobs_layout.setSpacing(8)
        self.jobs_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.jobs_container)
        root.addWidget(scroll, 1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Starting…")

    @staticmethod
    def _summary_card(title: str, value: str) -> tuple[QFrame, QLabel]:
        card = card_frame()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 10, 18, 10)
        value_label = QLabel(value)
        value_label.setStyleSheet("font-size: 22px; font-weight: 700;")
        title_label = QLabel(title)
        title_label.setProperty("muted", True)
        lay.addWidget(value_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(title_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        return card, value_label

    # -- data --------------------------------------------------------------------

    def refresh(self) -> None:
        try:
            status = self._api.system_status()
            jobs = self._api.list_jobs()
        except ApiError as e:
            self._connected = False
            self.conn_label.setText(connection_pill(False))
            self.conn_label.setToolTip(str(e))
            self.statusBar().showMessage("Disconnected — is the ReportFlow service running?")
            return
        self._connected = True
        self.conn_label.setText(connection_pill(True))
        self.conn_label.setToolTip("")

        failures = sum(
            1 for j in jobs if (j.get("last_status") or "") in ("failed", "timed_out", "crashed")
        )
        self.card_jobs[1].setText(str(len(jobs)))
        self.card_active[1].setText(str(len(status.get("active_runs", []))))
        self.card_failures[1].setText(str(failures))

        self.statusBar().showMessage(
            f"Connected · v{status.get('version')} · "
            f"{len(status.get('scheduled_jobs', []))} trigger(s) scheduled"
        )
        self._populate(jobs)

    def _populate(self, jobs: list[dict]) -> None:
        # Clear existing cards (keep the trailing stretch).
        while self.jobs_layout.count() > 1:
            item = self.jobs_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

        if not jobs:
            empty = QLabel("No jobs yet — click “+ New Job” to create your first report job.")
            empty.setProperty("muted", True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.jobs_layout.insertWidget(0, empty)
            return

        for i, job in enumerate(jobs):
            self.jobs_layout.insertWidget(i, self._job_card(job))

    def _job_card(self, job: dict[str, Any]) -> QFrame:
        card = card_frame()
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 10)

        info = QVBoxLayout()
        name_row = QHBoxLayout()
        name = QLabel(f"<b>{job.get('name', '')}</b>")
        name_row.addWidget(name)
        if not job.get("enabled", True):
            disabled = QLabel("disabled")
            disabled.setProperty("muted", True)
            name_row.addWidget(disabled)
        name_row.addWidget(status_badge(job.get("last_status")))
        name_row.addStretch()
        info.addLayout(name_row)

        schedule_text = describe(job.get("schedule_crons") or [])
        sheets = job.get("sheet_names") or []
        last_run = job.get("last_run_at") or "never"
        detail = QLabel(f"{schedule_text} · {len(sheets)} sheet(s) · last run: {last_run}")
        detail.setProperty("muted", True)
        info.addWidget(detail)
        lay.addLayout(info, 1)

        def _btn(label: str, tip: str, slot) -> QPushButton:
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            return b

        job_name = job.get("name", "")
        lay.addWidget(
            _btn(
                "▶ Run",
                "Real run — emails production recipients if enabled.",
                lambda *_: self._trigger(job_name, test=False),
            )
        )
        lay.addWidget(
            _btn(
                "🧪 Test",
                "Test run — emails TEST recipients only.",
                lambda *_: self._trigger(job_name, test=True),
            )
        )
        lay.addWidget(_btn("✎ Edit", "Edit this job.", lambda *_: self._edit_job(job_name)))
        lay.addWidget(
            _btn("Logs", "Run history and logs for this job.", lambda *_: self._view_logs(job_name))
        )
        lay.addWidget(_btn("🗑", "Delete this job.", lambda *_: self._delete_job(job_name)))
        return card

    # -- actions -----------------------------------------------------------------

    def _new_job(self) -> None:
        dlg = JobEditorDialog(self._api, None, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._save(dlg, create=True)

    def _edit_job(self, name: str) -> None:
        try:
            job = self._api.get_job(name)["job"]
        except ApiError as e:
            QMessageBox.warning(self, "Error", str(e))
            return
        dlg = JobEditorDialog(self._api, job, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._save(dlg, create=False)

    def _save(self, dlg: JobEditorDialog, *, create: bool) -> None:
        payload = dlg.payload()
        try:
            if create:
                self._api.create_job(payload)
            else:
                self._api.update_job(payload["name"], payload)
            template = dlg.template_html()
            if template is not None:
                self._api.put_email_template(payload["name"], template)
        except ApiError as e:
            QMessageBox.warning(self, "Save failed", str(e))
            return
        self.refresh()

    def _delete_job(self, name: str) -> None:
        confirm = QMessageBox.question(self, "Delete", f"Delete job {name!r}?")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self._api.delete_job(name)
        except ApiError as e:
            QMessageBox.warning(self, "Delete failed", str(e))
            return
        self.refresh()

    def _trigger(self, name: str, *, test: bool) -> None:
        try:
            resp = self._api.test_job(name) if test else self._api.run_job(name)
        except ApiError as e:
            QMessageBox.warning(self, "Run failed", str(e))
            return
        kind = "Test run" if test else "Run"
        self.statusBar().showMessage(f"{kind} started for {name} (run {resp['run_id']})")
        RunHistoryDialog(self._api, name, self).exec()

    def _view_logs(self, name: str | None = None) -> None:
        RunHistoryDialog(self._api, name, self).exec()

    def _open_app_logs(self) -> None:
        LogViewerDialog(self._api, self).exec()

    def _open_settings(self) -> None:
        SettingsDialog(self._api, self).exec()

    def _open_help(self) -> None:
        HelpDialog(self).exec()

    def _open_about(self) -> None:
        AboutDialog(self, api_base_url=self._api.base_url, connected=self._connected).exec()

    def _send_dev_logs(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Send developer logs",
            "Send the full log bundle to the developer recipients?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            resp = self._api.send_dev_logs()
        except ApiError as e:
            QMessageBox.warning(self, "Send failed", str(e))
            return
        QMessageBox.information(
            self, "Sent", f"Bundle sent to: {', '.join(resp.get('recipients', []))}"
        )
