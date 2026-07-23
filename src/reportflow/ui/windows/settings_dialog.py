"""Settings dialog: SMTP (incl. password), test & developer recipients, app settings."""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.api_client import ApiClient, ApiError


def _split_csv(text: str) -> list[str]:
    return [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]


class SettingsDialog(QDialog):
    def __init__(
        self,
        api: ApiClient,
        parent: QWidget | None = None,
        *,
        focus_service_account: bool = False,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self.setWindowTitle("Settings")
        self.setMinimumWidth(880)
        self._build()
        self._load()
        if focus_service_account:
            self.account_user.setFocus()

    # -- construction ------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        # SMTP
        smtp_box = QGroupBox("Email server (SMTP)")
        smtp_form = QFormLayout(smtp_box)
        self.smtp_host = QLineEdit()
        self.smtp_host.setToolTip("Your mail server's hostname, e.g. smtp.company.com.")
        self.smtp_port = QSpinBox()
        self.smtp_port.setRange(1, 65535)
        self.smtp_port.setValue(587)
        self.smtp_port.setToolTip("587 for STARTTLS (typical), 465 for SSL, 25 for plain.")
        self.smtp_starttls = QCheckBox("Use STARTTLS")
        self.smtp_starttls.setToolTip("Upgrade the connection to TLS (recommended, port 587).")
        self.smtp_ssl = QCheckBox("Use SSL")
        self.smtp_ssl.setToolTip("Connect over implicit SSL (port 465).")
        self.smtp_from = QLineEdit()
        self.smtp_from.setToolTip("The From address report emails are sent as.")
        self.smtp_user = QLineEdit()
        self.smtp_user.setToolTip(
            "SMTP login username — leave EMPTY for servers that accept mail without "
            "login (e.g. internal relays on port 25). Login is only attempted when both "
            "a username and a password are set."
        )

        self.smtp_password = QLineEdit()
        self.smtp_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.smtp_password.setPlaceholderText("(unchanged)")
        self.smtp_password.setToolTip(
            "Stored encrypted on this machine (Windows DPAPI) — never in the config file. "
            "Leave blank to keep the current password."
        )
        self._pw_toggle = self.smtp_password.addAction(
            self.style().standardIcon(self.style().StandardPixmap.SP_DialogYesButton),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        self._pw_toggle.setToolTip("Show/hide the password while typing.")
        self._pw_toggle.setCheckable(True)
        self._pw_toggle.toggled.connect(self._toggle_password_visible)
        self.password_status = QLabel("")
        self.password_status.setProperty("muted", True)
        clear_pw = QPushButton("Clear stored password")
        clear_pw.clicked.connect(self._clear_password)
        pw_row = QHBoxLayout()
        pw_row.addWidget(self.smtp_password)
        pw_row.addWidget(clear_pw)

        tls_row = QHBoxLayout()
        tls_row.addWidget(self.smtp_starttls)
        tls_row.addWidget(self.smtp_ssl)
        tls_row.addStretch()

        test_btn = QPushButton("Test connection")
        test_btn.setToolTip(
            "Connect to the SMTP server with these settings (and log in when a username "
            "is set) to verify they work — no email is sent."
        )
        test_btn.clicked.connect(self._test_connection)

        smtp_form.addRow("Host", self.smtp_host)
        smtp_form.addRow("Port", self.smtp_port)
        smtp_form.addRow("", tls_row)
        smtp_form.addRow("From address", self.smtp_from)
        smtp_form.addRow("Username", self.smtp_user)
        smtp_form.addRow("Password", pw_row)
        smtp_form.addRow("", self.password_status)
        smtp_form.addRow("", test_btn)

        # Recipients
        rcpt_box = QGroupBox("Test && support email")
        rcpt_form = QFormLayout(rcpt_box)
        self.test_recipients = QLineEdit()
        self.test_recipients.setToolTip(
            "Global fallback recipients for TEST runs when a job has no test recipients "
            "of its own. Comma-separated."
        )
        self.dev_recipients = QLineEdit()
        self.dev_recipients.setToolTip(
            "Receives the diagnostic log bundles sent from File → Send logs to support. "
            "Comma-separated."
        )
        rcpt_form.addRow("Test recipients", self.test_recipients)
        rcpt_form.addRow("Support email", self.dev_recipients)

        # App settings
        app_box = QGroupBox("Application")
        app_form = QFormLayout(app_box)
        self.max_concurrency = QSpinBox()
        self.max_concurrency.setRange(1, 32)
        self.max_concurrency.setToolTip("Maximum number of jobs allowed to run at the same time.")
        self.default_timeout = QSpinBox()
        self.default_timeout.setRange(30, 86400)
        self.default_timeout.setSuffix(" s")
        self.default_timeout.setToolTip(
            "Default per-run time limit; a hung run is killed when it exceeds this."
        )
        self.log_retention = QSpinBox()
        self.log_retention.setRange(1, 365)
        self.log_retention.setSuffix(" days")
        self.log_retention.setToolTip("How long rolling log files are kept.")
        self.check_updates = QCheckBox("Check for updates when the app starts")
        self.check_updates.setToolTip(
            "Silently checks GitHub for a newer version on startup (skipped when offline). "
            "Updates are only ever installed when you click Update."
        )
        self.debug_logging = QCheckBox("Enable debug logging (verbose)")
        self.debug_logging.setToolTip(
            "Writes much more detail to the service, worker, and app log files — useful "
            "when troubleshooting with support. Applies to the service immediately; the "
            "app picks it up on next start."
        )
        app_form.addRow("Max parallel runs", self.max_concurrency)
        app_form.addRow("Default timeout", self.default_timeout)
        app_form.addRow("Log retention", self.log_retention)
        app_form.addRow("", self.check_updates)
        app_form.addRow("", self.debug_logging)

        # Service account — set the Windows user the service (and its Excel workers) run as.
        # PI DataLink and other add-ins only load under a real user, never LocalSystem.
        account_box = QGroupBox("Service account (PI DataLink)")
        account_form = QFormLayout(account_box)
        self.service_account = QLabel("")
        self.service_account.setWordWrap(True)
        self.service_account.setToolTip(
            "The Windows account the ReportFlow service currently runs as."
        )
        self.account_user = QLineEdit()
        self.account_user.setPlaceholderText("DOMAIN\\user or .\\user")
        self.account_user.setToolTip(
            "A Windows account that has PI DataLink installed and PI access. Use DOMAIN\\user "
            "for a domain account, or .\\user for a local one."
        )
        use_current = QPushButton("Use current Windows user")
        use_current.setToolTip("Fill in the account you are logged in as right now.")
        use_current.clicked.connect(self._fill_current_user)
        user_row = QHBoxLayout()
        user_row.addWidget(self.account_user)
        user_row.addWidget(use_current)

        self.account_password = QLineEdit()
        self.account_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.account_password.setToolTip(
            "The account's Windows password. It is validated with Windows and passed straight "
            "to the service configuration — never written to the config file."
        )
        apply_account = QPushButton("Validate && apply")
        apply_account.setProperty("accent", True)
        apply_account.setToolTip(
            "Check the credentials with Windows, then reconfigure the service to run as this "
            "account and restart it. No reinstall or admin prompt needed."
        )
        apply_account.clicked.connect(self._apply_service_account)
        apply_row = QHBoxLayout()
        apply_row.addStretch()
        apply_row.addWidget(apply_account)

        account_form.addRow("Runs as", self.service_account)
        account_form.addRow("User", user_row)
        account_form.addRow("Password", self.account_password)
        account_form.addRow("", apply_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        # Two columns so the whole dialog fits on screen: email-related settings on the
        # left, machine/service settings on the right.
        columns = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(smtp_box)
        left.addWidget(rcpt_box)
        left.addStretch()
        right = QVBoxLayout()
        right.addWidget(app_box)
        right.addWidget(account_box)
        right.addStretch()
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        layout.addLayout(columns)
        layout.addWidget(buttons)

    # -- data --------------------------------------------------------------------

    def _load(self) -> None:
        try:
            cfg = self._api.get_config()
            pw_set = self._api.smtp_password_status()
        except ApiError as e:
            QMessageBox.warning(self, "Settings", f"Could not load settings: {e}")
            return
        smtp = cfg.get("smtp", {})
        self.smtp_host.setText(smtp.get("host", ""))
        self.smtp_port.setValue(int(smtp.get("port", 587)))
        self.smtp_starttls.setChecked(bool(smtp.get("use_starttls", True)))
        self.smtp_ssl.setChecked(bool(smtp.get("use_ssl", False)))
        self.smtp_from.setText(smtp.get("from_address", ""))
        self.smtp_user.setText(smtp.get("username") or "")

        test = cfg.get("test", {})
        self.test_recipients.setText(", ".join(test.get("recipients", [])))
        self.dev_recipients.setText(", ".join(test.get("developer_bundle_recipients", [])))

        app_cfg = cfg.get("app", {})
        self.max_concurrency.setValue(int(app_cfg.get("max_global_concurrency", 4)))
        self.default_timeout.setValue(int(app_cfg.get("default_timeout_seconds", 900)))
        self.log_retention.setValue(int(app_cfg.get("log_retention_days", 30)))

        ui_cfg = cfg.get("ui", {})
        self.check_updates.setChecked(bool(ui_cfg.get("check_updates_on_startup", True)))
        self.debug_logging.setChecked(bool(app_cfg.get("debug_logging", False)))

        self._app_section_base: dict[str, Any] = app_cfg
        self._ui_section_base: dict[str, Any] = ui_cfg
        self.password_status.setText(
            "A password is currently stored." if pw_set else "No password stored yet."
        )

        try:
            status = self._api.system_status()
        except ApiError:
            status = {}
        account = status.get("service_account") or "unknown"
        if status.get("service_account_is_system"):
            self.service_account.setText(
                f"⚠ {account} (LocalSystem) — PI DataLink and other add-ins will NOT load. "
                "Run scripts/set-service-account.ps1 as admin to switch to a PI-enabled user."
            )
            self.service_account.setStyleSheet("color: #e06c6c;")
        else:
            self.service_account.setText(account)
            self.service_account.setStyleSheet("")

    def _fill_current_user(self) -> None:
        domain = os.environ.get("USERDOMAIN", "")
        user = os.environ.get("USERNAME", "")
        self.account_user.setText(f"{domain}\\{user}".strip("\\") if user else "")
        self.account_password.setFocus()

    def _apply_service_account(self) -> None:
        user = self.account_user.text().strip()
        password = self.account_password.text()
        if not user or not password:
            QMessageBox.warning(
                self, "Service account", "Enter both the account (DOMAIN\\user) and its password."
            )
            return
        confirm = QMessageBox.question(
            self,
            "Set service account",
            f"Validate {user!r} and reconfigure the ReportFlow service to run as it?\n\n"
            "The service will restart, briefly interrupting any running job.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            resp = self._api.set_service_account(user, password)
        except ApiError as e:
            QMessageBox.warning(self, "Service account", str(e))
            return
        self.account_password.clear()
        QMessageBox.information(
            self,
            "Service account",
            f"Applied — the service is restarting as {resp.get('account', user)}.\n\n"
            "Give it a few seconds, then run a Build only to confirm PI DataLink connects.",
        )

    def _save(self) -> None:
        sections: dict[str, Any] = {
            "smtp": self._smtp_form_values(),
            "test": {
                "recipients": _split_csv(self.test_recipients.text()),
                "developer_bundle_recipients": _split_csv(self.dev_recipients.text()),
            },
            "app": {
                **getattr(self, "_app_section_base", {}),
                "max_global_concurrency": self.max_concurrency.value(),
                "default_timeout_seconds": self.default_timeout.value(),
                "log_retention_days": self.log_retention.value(),
                "debug_logging": self.debug_logging.isChecked(),
            },
            "ui": {
                **getattr(self, "_ui_section_base", {}),
                "check_updates_on_startup": self.check_updates.isChecked(),
            },
        }
        try:
            self._api.update_settings(sections)
            password = self.smtp_password.text()
            if password:
                self._api.set_smtp_password(password)
        except ApiError as e:
            QMessageBox.warning(self, "Save failed", str(e))
            return
        self.accept()

    def _toggle_password_visible(self, show: bool) -> None:
        self.smtp_password.setEchoMode(
            QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        )

    def _smtp_form_values(self) -> dict[str, Any]:
        return {
            "host": self.smtp_host.text().strip(),
            "port": self.smtp_port.value(),
            "use_starttls": self.smtp_starttls.isChecked(),
            "use_ssl": self.smtp_ssl.isChecked(),
            "from_address": self.smtp_from.text().strip(),
            "username": self.smtp_user.text().strip() or None,
        }

    def _test_connection(self) -> None:
        payload = {**self._smtp_form_values(), "password": self.smtp_password.text() or None}
        try:
            self._api.smtp_test(payload)
        except ApiError as e:
            QMessageBox.warning(self, "SMTP test failed", str(e))
            return
        QMessageBox.information(
            self, "SMTP test", "Connection successful — the SMTP settings work."
        )

    def _clear_password(self) -> None:
        confirm = QMessageBox.question(self, "Clear password", "Remove the stored SMTP password?")
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self._api.clear_smtp_password()
        except ApiError as e:
            QMessageBox.warning(self, "Clear failed", str(e))
            return
        self.password_status.setText("No password stored yet.")
        self.smtp_password.clear()
