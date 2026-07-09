"""Dashboard main window: slim header + stat strip + job cards, with a menu bar.

Talks only to the local API. Presentation lives here; all actions go through the same
ApiClient methods regardless of where they're triggered (menu, card button, …).
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger
from PySide6.QtCore import Qt, QThread, QTimer, Signal
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
from reportflow.core import paths
from reportflow.ui.api_client import ApiClient, ApiError
from reportflow.ui.assets import logo_pixmap
from reportflow.ui.schedule_compile import describe
from reportflow.ui.style import TEXT_MUTED, card_frame, connection_pill, status_badge
from reportflow.ui.updater import UpdateInfo, check_latest
from reportflow.ui.windows.about_dialog import AboutDialog
from reportflow.ui.windows.help_dialog import HelpDialog
from reportflow.ui.windows.job_editor import JobEditorDialog
from reportflow.ui.windows.log_view import RunHistoryDialog
from reportflow.ui.windows.log_viewer_dialog import LogViewerDialog
from reportflow.ui.windows.settings_dialog import SettingsDialog
from reportflow.ui.windows.transfer_dialogs import (
    export_jobs_flow,
    export_settings_flow,
    import_jobs_flow,
    import_settings_flow,
)
from reportflow.ui.windows.update_dialog import UpdateDialog


class _UpdateCheckThread(QThread):
    found = Signal(object)  # UpdateInfo

    def run(self) -> None:
        info = check_latest()
        if info is not None:
            self.found.emit(info)


class MainWindow(QMainWindow):
    def __init__(self, api: ApiClient | None = None) -> None:
        super().__init__()
        self._api = api or ApiClient()
        self._connected = False
        self._update_thread: _UpdateCheckThread | None = None
        self.setWindowTitle(about.NAME)
        self.resize(920, 620)
        self._build_menu()
        self._build()

        self._timer = QTimer(self)
        self._timer.setInterval(4000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()
        QTimer.singleShot(1500, self._startup_update_check)

    # -- construction ------------------------------------------------------------

    def _build_menu(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        file_menu.addAction("Settings…", self._open_settings)
        file_menu.addSeparator()
        file_menu.addAction("Export jobs…", self._export_jobs)
        file_menu.addAction("Import jobs…", self._import_jobs)
        file_menu.addAction("Export settings…", self._export_settings)
        file_menu.addAction("Import settings…", self._import_settings)
        file_menu.addSeparator()
        file_menu.addAction("Open data folder", self._open_data_folder)
        file_menu.addAction("Application logs…", self._open_app_logs)
        file_menu.addAction("Send logs to support…", self._send_support_logs)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        jobs_menu = bar.addMenu("&Jobs")
        jobs_menu.addAction("New job…", self._new_job)
        jobs_menu.addAction("Refresh", self.refresh)

        help_menu = bar.addMenu("&Help")
        help_menu.addAction("Help guide", self._open_help)
        help_menu.addAction("Check for updates…", self._manual_update_check)
        help_menu.addAction(f"About {about.NAME}", self._open_about)

    def _build(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        # Header: logo + title + stat strip + connection pill, one tight row.
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(logo_pixmap(24))
        title = QLabel(about.NAME)
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        header.addWidget(logo)
        header.addWidget(title)
        header.addSpacing(16)

        self.card_jobs = self._stat_pill("Jobs")
        self.card_active = self._stat_pill("Active")
        self.card_failures = self._stat_pill("Failures")
        for pill, _value in (self.card_jobs, self.card_active, self.card_failures):
            header.addWidget(pill)
        header.addStretch()
        self.conn_label = QLabel(connection_pill(False))
        header.addWidget(self.conn_label)
        root.addLayout(header)

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
        self.jobs_layout.setSpacing(6)
        self.jobs_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.jobs_container)
        root.addWidget(scroll, 1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Starting…")

    @staticmethod
    def _stat_pill(label: str) -> tuple[QFrame, QLabel]:
        pill = card_frame()
        lay = QHBoxLayout(pill)
        lay.setContentsMargins(10, 3, 10, 3)
        lay.setSpacing(6)
        value_label = QLabel("0")
        value_label.setStyleSheet("font-size: 14px; font-weight: 700;")
        word = QLabel(label)
        word.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        lay.addWidget(value_label)
        lay.addWidget(word)
        return pill, value_label

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

        config_error = status.get("config_error")
        if config_error:
            message = (
                "⚠ The configuration file is invalid — jobs are NOT loaded until it is "
                f"fixed or re-saved from Settings. ({config_error})"
            )
            self.statusBar().showMessage(message)
            self.conn_label.setToolTip(message)
        else:
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
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(6)

        info = QVBoxLayout()
        info.setSpacing(1)
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
            b.setStyleSheet("padding: 3px 10px;")
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
            _btn(
                "Logs",
                "Run history and logs for this job.",
                lambda *_: self._view_logs(job_name),
            )
        )
        lay.addWidget(_btn("🗑", "Delete this job.", lambda *_: self._delete_job(job_name)))
        return card

    # -- job actions --------------------------------------------------------------

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
        logger.info("{} job {!r}", "Creating" if create else "Updating", payload.get("name"))
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
        logger.info("Deleting job {!r}", name)
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
        logger.info("{} started for {!r}: run {}", kind, name, resp.get("run_id"))
        self.statusBar().showMessage(f"{kind} started for {name} (run {resp['run_id']})")
        RunHistoryDialog(self._api, name, self).exec()

    def _view_logs(self, name: str | None = None) -> None:
        RunHistoryDialog(self._api, name, self).exec()

    # -- file menu actions ---------------------------------------------------------

    def _open_settings(self) -> None:
        SettingsDialog(self._api, self).exec()

    def _open_app_logs(self) -> None:
        LogViewerDialog(self._api, self).exec()

    def _open_data_folder(self) -> None:
        os.startfile(str(paths.data_root()))  # noqa: S606 — deliberate shell open

    def _export_jobs(self) -> None:
        export_jobs_flow(self._api, self)

    def _import_jobs(self) -> None:
        if import_jobs_flow(self._api, self):
            self.refresh()

    def _export_settings(self) -> None:
        export_settings_flow(self._api, self)

    def _import_settings(self) -> None:
        import_settings_flow(self._api, self)

    def _send_support_logs(self) -> None:
        try:
            recipients = ", ".join(
                self._api.get_config().get("test", {}).get("developer_bundle_recipients", [])
            )
        except ApiError:
            recipients = "the configured support email"
        confirm = QMessageBox.question(
            self,
            "Send logs to support",
            "Send the full diagnostic bundle (logs + sanitized settings, no passwords) "
            f"to {recipients or 'the configured support email'}?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            resp = self._api.send_dev_logs()
        except ApiError as e:
            QMessageBox.warning(self, "Send failed", str(e))
            return
        QMessageBox.information(
            self, "Sent", f"Diagnostic bundle sent to: {', '.join(resp.get('recipients', []))}"
        )

    # -- help menu actions ----------------------------------------------------------

    def _open_help(self) -> None:
        HelpDialog(self).exec()

    def _open_about(self) -> None:
        AboutDialog(self, api_base_url=self._api.base_url, connected=self._connected).exec()

    # -- updates ---------------------------------------------------------------------

    def _startup_update_check(self) -> None:
        try:
            enabled = bool(
                self._api.get_config().get("ui", {}).get("check_updates_on_startup", True)
            )
        except ApiError:
            enabled = True  # config unavailable — the check itself fails silently offline
        if not enabled:
            return
        self._run_update_check(silent=True)

    def _manual_update_check(self) -> None:
        self._run_update_check(silent=False)

    def _run_update_check(self, *, silent: bool) -> None:
        if self._update_thread is not None and self._update_thread.isRunning():
            return
        thread = _UpdateCheckThread(self)
        thread.found.connect(self._on_update_found)
        if not silent:
            thread.finished.connect(lambda: self._notify_up_to_date(thread))
        self._update_thread = thread
        thread.start()

    def _notify_up_to_date(self, thread: _UpdateCheckThread) -> None:
        # Manual check with no newer version found -> tell the user explicitly.
        if not getattr(thread, "_reported", False):
            QMessageBox.information(
                self, "Check for updates", f"You are running the latest version ({about.VERSION})."
            )

    def _on_update_found(self, info: UpdateInfo) -> None:
        logger.info("Update available: v{} (current v{})", info.version, about.VERSION)
        if self._update_thread is not None:
            self._update_thread._reported = True  # type: ignore[attr-defined]
        UpdateDialog(info, self).exec()
