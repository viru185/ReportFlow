"""Dashboard main window: slim header + stat strip + job cards, with a menu bar.

Talks only to the local API. Presentation lives here; all actions go through the same
ApiClient methods regardless of where they're triggered (menu, card button, …).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
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
from reportflow.ui.fs_util import save_start_path
from reportflow.ui.schedule_compile import describe, friendly_time
from reportflow.ui.style import (
    TEXT_MUTED,
    card_frame,
    connection_pill,
    disabled_badge,
    stage_badge,
    status_badge,
)
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


def _elapsed_text(started_at: str | None) -> str:
    """Human elapsed time since an ISO timestamp — '38s', '2m 10s'; '' when unknown."""
    if not started_at:
        return ""
    try:
        seconds = int((datetime.now() - datetime.fromisoformat(started_at)).total_seconds())
    except ValueError:
        return ""
    if seconds < 0:
        return ""
    if seconds < 120:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60}s"


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

        # File — job actions, tidy Import/Export submenus, settings, exit.
        file_menu = bar.addMenu("&File")
        file_menu.addAction("New Job…", self._new_job)
        file_menu.addAction("Refresh", self.refresh)
        file_menu.addSeparator()
        import_menu = file_menu.addMenu("Import")
        import_menu.addAction("Jobs…", self._import_jobs)
        import_menu.addAction("Settings…", self._import_settings)
        export_menu = file_menu.addMenu("Export")
        export_menu.addAction("Jobs…", self._export_jobs)
        export_menu.addAction("Settings…", self._export_settings)
        file_menu.addSeparator()
        file_menu.addAction("Settings…", self._open_settings)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        # Logs — everything diagnostics-related in one place.
        logs_menu = bar.addMenu("&Logs")
        logs_menu.addAction("Application logs…", self._open_app_logs)
        logs_menu.addSeparator()
        logs_menu.addAction("Export logs to zip…", self._export_logs)
        logs_menu.addAction("Send logs to support…", self._send_support_logs)
        logs_menu.addSeparator()
        logs_menu.addAction("Delete old logs…", self._purge_old_logs)
        logs_menu.addAction("Delete ALL logs…", self._purge_all_logs)
        logs_menu.addSeparator()
        logs_menu.addAction("Open data folder", self._open_data_folder)

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

        # Warning banner shown when the service runs as LocalSystem (VSTO/PI add-ins can't
        # load there → reports come out #NAME?). Hidden until refresh() detects it.
        self.system_banner = QFrame()
        self.system_banner.setStyleSheet(
            "QFrame { background: #5a1e1e; border: 1px solid #a33; border-radius: 4px; }"
        )
        banner_row = QHBoxLayout(self.system_banner)
        banner_row.setContentsMargins(10, 4, 10, 4)
        banner_label = QLabel(
            "⚠ ReportFlow is running as LocalSystem — PI DataLink can't load. "
            "Set a Windows account to fix it."
        )
        banner_label.setWordWrap(True)
        banner_fix = QPushButton("Set account…")
        banner_fix.setProperty("accent", True)
        banner_fix.clicked.connect(self._open_service_account)
        banner_row.addWidget(banner_label, 1)
        banner_row.addWidget(banner_fix)
        self.system_banner.setVisible(False)
        root.addWidget(self.system_banner)

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
        self.system_banner.setVisible(bool(status.get("service_account_is_system")))

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

        enabled = bool(job.get("enabled", True))
        running = (job.get("last_status") or "") == "running"

        info = QVBoxLayout()
        info.setSpacing(1)
        name_row = QHBoxLayout()
        name = QLabel(f"<b>{job.get('name', '')}</b>")
        name_row.addWidget(name)
        name_row.addWidget(stage_badge(job.get("stage", "testing")))
        if not enabled:
            name_row.addWidget(disabled_badge())
        # Elapsed time rides the dashboard's 4s refresh — no extra polling machinery.
        suffix = f"· {_elapsed_text(job.get('last_run_at'))}" if running else ""
        name_row.addWidget(status_badge(job.get("last_status"), suffix))
        if job.get("last_email_failed"):
            email_warn = QLabel("✉ failed")
            email_warn.setStyleSheet("color: #e06c6c; font-size: 11px;")
            email_warn.setToolTip(
                job.get("last_email_note") or "The last run's report email failed to send."
            )
            name_row.addWidget(email_warn)
        name_row.addStretch()
        info.addLayout(name_row)

        schedule_text = (
            "schedule paused" if not enabled else describe(job.get("schedule_crons") or [])
        )
        sheets = job.get("sheet_names") or []
        last_run = job.get("last_run_at") or "never"
        detail_text = f"{schedule_text} · {len(sheets)} sheet(s) · last run: {last_run}"
        next_at = friendly_time(job.get("next_run_at")) if enabled else None
        if next_at:
            detail_text += f" · next: {next_at}"
        detail = QLabel(detail_text)
        detail.setProperty("muted", True)
        info.addWidget(detail)
        lay.addLayout(info, 1)

        def _btn(
            label: str, tip: str, slot, *, accent: bool = False, active: bool = True
        ) -> QPushButton:
            b = QPushButton(label)
            b.setToolTip(tip)
            # No accent glow on a paused card — the dimming should read as "asleep".
            if accent and enabled:
                b.setProperty("accent", True)
            else:
                b.setStyleSheet("padding: 3px 10px;")
            if not active:
                b.setEnabled(False)
                b.setToolTip("Already running — wait for it to finish.")
            b.clicked.connect(slot)
            return b

        job_name = job.get("name", "")
        testing = job.get("stage", "testing") != "live"
        # Two single-click run actions; the job's stage answers "who gets the email".
        run_tip = (
            "Builds the report and emails the TEST recipients (job is in Testing)."
            if testing
            else "Builds the report and emails the Production recipients (job is Live)."
        )
        run_group = QHBoxLayout()
        run_group.setSpacing(2)
        run_group.addWidget(
            _btn(
                "▶ Run",
                run_tip,
                lambda *_: self._trigger(job_name, mode="run"),
                accent=True,
                active=not running,
            )
        )
        run_group.addWidget(
            _btn(
                "👁 Build only",
                "Builds and verifies the report (checks PI DataLink data) without emailing anyone.",
                lambda *_: self._trigger(job_name, mode="dry"),
                active=not running,
            )
        )
        if testing:
            run_group.addWidget(
                _btn(
                    "✓ Go live",
                    "Promote this job: future runs (incl. scheduled) email the Production "
                    "recipients instead of the Test recipients.",
                    lambda *_: self._go_live(job),
                )
            )
        if not enabled:
            resume = _btn(
                "▸ Resume",
                "Re-enable scheduling for this job (one click).",
                lambda *_: self._set_enabled(job_name, True),
            )
            resume.setProperty("accent", True)  # THE call-to-action on a paused card
            run_group.addWidget(resume)
        lay.addLayout(run_group)
        lay.addSpacing(10)
        lay.addWidget(
            _btn(
                "📂",
                "Open the last report's folder (file selected).",
                lambda *_: self._open_last_report(job),
            )
        )
        lay.addWidget(
            _btn(
                "⧉",
                "Duplicate: new job pre-filled from this one — starts in Testing.",
                lambda *_: self._duplicate_job(job_name),
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
        if enabled:
            lay.addWidget(
                _btn(
                    "⏸",
                    "Pause scheduling — manual runs still work. Resume with one click.",
                    lambda *_: self._set_enabled(job_name, False),
                )
            )
        lay.addWidget(_btn("🗑", "Delete this job.", lambda *_: self._delete_job(job_name)))

        if not enabled:
            # One effect dims the ENTIRE card uniformly — pills, text, buttons — so a
            # paused job cannot be mistaken for a live one at any glance distance.
            effect = QGraphicsOpacityEffect(card)
            effect.setOpacity(0.55)
            card.setGraphicsEffect(effect)
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
        if create:
            self.statusBar().showMessage(
                f"Job {payload.get('name')!r} created in Testing — click ▶ Run to build it "
                "and email the test recipients; Go live when you're happy with it."
            )

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

    def _trigger(self, name: str, *, mode: str = "run") -> None:
        api_call = {"run": self._api.run_job, "dry": self._api.dry_run_job}[mode]
        kind = {"run": "Run", "dry": "Build only"}[mode]
        try:
            resp = api_call(name)
        except ApiError as e:
            QMessageBox.warning(self, f"{kind} failed", str(e))
            return
        logger.info("{} started for {!r}: run {}", kind, name, resp.get("run_id"))
        self.statusBar().showMessage(f"{kind} started for {name} (run {resp['run_id']})")
        RunHistoryDialog(self._api, name, self).exec()

    def _go_live(self, job: dict[str, Any]) -> None:
        """Promote a testing job to live after an explicit, recipient-naming confirmation."""
        name = job.get("name", "")
        recipients = ", ".join(job.get("prod_recipients") or []) or "the Production recipients"
        confirm = QMessageBox.question(
            self,
            "Go live",
            f"Go live with {name!r}?\n\n"
            f"Future runs — including scheduled ones — will email:\n{recipients}\n\n"
            "You can move it back to Testing from the job editor's Email tab.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self._api.set_job_stage(name, "live")
        except ApiError as e:
            QMessageBox.warning(self, "Go live failed", str(e))
            return
        logger.info("Job {!r} promoted to live", name)
        self.statusBar().showMessage(f"{name} is now LIVE — future runs email production.")
        self.refresh()

    def _set_enabled(self, name: str, enabled: bool) -> None:
        """One-click Pause/Resume: flip `enabled` through the normal update path (the
        service re-validates and re-schedules)."""
        try:
            job = self._api.get_job(name)["job"]
            job["enabled"] = enabled
            self._api.update_job(name, job)
        except ApiError as e:
            QMessageBox.warning(self, "Resume failed" if enabled else "Pause failed", str(e))
            return
        logger.info("Job {!r} {}", name, "resumed" if enabled else "paused")
        self.statusBar().showMessage(
            f"{name} resumed — next run per its schedule."
            if enabled
            else f"{name} paused — scheduling is off; manual runs still work."
        )
        self.refresh()

    def _open_last_report(self, job: dict[str, Any]) -> None:
        """Open Explorer at the last successful report, file pre-selected."""
        path_text = job.get("last_output_xlsx")
        if not path_text:
            self.statusBar().showMessage("No successful report yet — run the job first.")
            return
        path = Path(path_text)
        if path.exists():
            subprocess.Popen(["explorer", "/select,", str(path)])  # noqa: S603,S607
        elif path.parent.exists():
            os.startfile(str(path.parent))  # noqa: S606 — deliberate shell open
        else:
            self.statusBar().showMessage(f"Last report no longer exists: {path}")

    def _duplicate_job(self, name: str) -> None:
        """New job pre-filled from an existing one (fresh name, starts in Testing)."""
        try:
            job = self._api.get_job(name)["job"]
        except ApiError as e:
            QMessageBox.warning(self, "Duplicate failed", str(e))
            return
        dlg = JobEditorDialog(self._api, None, self, prefill=job)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._save(dlg, create=True)

    def _view_logs(self, name: str | None = None) -> None:
        RunHistoryDialog(self._api, name, self).exec()

    # -- file menu actions ---------------------------------------------------------

    def _open_settings(self) -> None:
        SettingsDialog(self._api, self).exec()

    def _open_service_account(self) -> None:
        dlg = SettingsDialog(self._api, self, focus_service_account=True)
        if dlg.exec():
            self.refresh()

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

    def _ask_dev_note(self, title: str) -> str | None:
        """Prompt for an optional problem description. Returns the note, or None if cancelled."""
        note, ok = QInputDialog.getMultiLineText(
            self,
            title,
            "Describe the problem for the developer (optional — leave blank to skip):",
        )
        return note if ok else None

    def _export_logs(self) -> None:
        """Build the diagnostic zip and let the user save it locally (email may be down)."""
        note = self._ask_dev_note("Export logs to zip")
        if note is None:
            return
        try:
            resp = self._api.export_logs(note)
        except ApiError as e:
            QMessageBox.warning(self, "Export failed", str(e))
            return
        source = Path(resp.get("bundle", ""))
        if not source.exists():
            QMessageBox.warning(self, "Export failed", "The service did not produce a log bundle.")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save logs to zip", save_start_path(None, source.name), "Zip archive (*.zip)"
        )
        if not dest:
            return
        try:
            shutil.copyfile(source, dest)
        except OSError as e:
            QMessageBox.warning(self, "Export failed", f"Could not save the zip: {e}")
            return
        logger.info("Exported diagnostic logs to {}", dest)
        opened = QMessageBox.question(
            self,
            "Logs exported",
            f"Saved the diagnostic bundle to:\n{dest}\n\nOpen the containing folder?",
        )
        if opened == QMessageBox.StandardButton.Yes:
            os.startfile(str(Path(dest).parent))  # noqa: S606 — deliberate shell open

    def _send_support_logs(self) -> None:
        try:
            recipients = ", ".join(
                self._api.get_config().get("test", {}).get("developer_bundle_recipients", [])
            )
        except ApiError:
            recipients = "the configured support email"
        note, ok = QInputDialog.getMultiLineText(
            self,
            "Send logs to support",
            "Send the full diagnostic bundle (logs + sanitized settings, no passwords) "
            f"to {recipients or 'the configured support email'}.\n\n"
            "Describe the problem for the developer (optional):",
        )
        if not ok:
            return
        try:
            resp = self._api.send_dev_logs(note)
        except ApiError as e:
            QMessageBox.warning(self, "Send failed", str(e))
            return
        QMessageBox.information(
            self, "Sent", f"Diagnostic bundle sent to: {', '.join(resp.get('recipients', []))}"
        )

    @staticmethod
    def _purge_summary(stats: dict) -> str:
        mb = stats.get("bytes_freed", 0) / 1e6
        return (
            f"Freed {mb:.1f} MB — {stats.get('run_dirs', 0)} run folder(s), "
            f"{stats.get('bundles', 0)} bundle(s), {stats.get('log_files', 0)} log file(s), "
            f"{stats.get('db_rows', 0)} history row(s)."
        )

    def _purge_old_logs(self) -> None:
        try:
            days = int(self._api.get_config().get("app", {}).get("log_retention_days", 30))
        except ApiError:
            days = 30
        confirm = QMessageBox.question(
            self,
            "Delete old logs",
            f"Delete run folders, log files, and diagnostic bundles older than {days} days "
            f"(the retention setting)?\n\nRun history rows that old are removed too. "
            "Active runs are never touched.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            stats = self._api.purge_logs(days)
        except ApiError as e:
            QMessageBox.warning(self, "Delete failed", str(e))
            return
        QMessageBox.information(self, "Old logs deleted", self._purge_summary(stats))

    def _purge_all_logs(self) -> None:
        confirm = QMessageBox.warning(
            self,
            "Delete ALL logs",
            "This permanently deletes ALL run history, run folders, log files, and "
            "diagnostic bundles — regardless of age. Only runs currently in progress "
            "are kept.\n\nThere is no undo. Delete everything?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            stats = self._api.purge_logs(everything=True)
        except ApiError as e:
            QMessageBox.warning(self, "Delete failed", str(e))
            return
        QMessageBox.information(self, "All logs deleted", self._purge_summary(stats))
        self.refresh()

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
