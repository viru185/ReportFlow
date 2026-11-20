"""Settings dialog: SMTP (incl. password), test & developer recipients, app settings."""

from __future__ import annotations

import os
import time
from collections.abc import Iterable
from typing import Any

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.api_client import ApiClient, ApiError
from reportflow.ui.recipient_field import RecipientField
from reportflow.ui.suggestions import jobs_using_group, known_addresses
from reportflow.ui.widgets import scroll_page, space_layout

# After an account change the service exits and Windows starts it again under the new
# logon; wait this long for it to answer as that account before telling the user.
_RESTART_WAIT_SECONDS = 60.0
_RESTART_POLL_MS = 2000


def _user_part(account: str) -> str:
    # A local ".\user" comes back as "MACHINE\user": compare the user name only.
    return account.rsplit("\\", 1)[-1].strip().casefold()


def _addin_labels(addins: Iterable[dict[str, Any]]) -> list[str]:
    """Each PI add-in once, in the service's order ("PI DataLink (64-bit Excel)", …)."""
    return list(dict.fromkeys(str(a.get("label") or a["name"]) for a in addins))


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
        self.setMinimumWidth(620)
        self.resize(800, 680)
        self._build()
        self._load()
        if focus_service_account:
            self.settings_tabs.setCurrentIndex(2)
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
        test_row = QHBoxLayout()
        test_row.addWidget(test_btn)
        test_row.addStretch()

        smtp_form.addRow("Host", self.smtp_host)
        smtp_form.addRow("Port", self.smtp_port)
        smtp_form.addRow("", tls_row)
        smtp_form.addRow("From address", self.smtp_from)
        smtp_form.addRow("Username", self.smtp_user)
        smtp_form.addRow("Password", pw_row)
        smtp_form.addRow("", self.password_status)
        smtp_form.addRow("", test_row)

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
        self.default_timeout.setRange(1, 24 * 60)
        self.default_timeout.setSuffix(" min")
        self.default_timeout.setToolTip(
            "The longest a run may take when its job leaves Time limit at Default. When it "
            "is reached the run is stopped and marked Timed out — raise it (here, or per job "
            "in Edit → Advanced) for big reports that pull a lot of PI data."
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
        app_form.addRow("Default time limit", self.default_timeout)
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

        account_hint = QLabel(
            "Updates preserve the existing service account. Changing it here is a separate "
            "operation: Validate & apply restarts the service. Save does not change the account."
        )
        account_hint.setWordWrap(True)
        account_hint.setProperty("muted", True)
        # Windows only loads PI DataLink for an account that trusts it. A desktop user grants
        # that by accepting a one-time prompt; a service account never sees the prompt, so
        # PI cells silently keep their last-saved values (Merian, Nov 2026).
        self.pi_trust_status = QLabel("")
        self.pi_trust_status.setWordWrap(True)
        trust_pi = QPushButton("Trust PI DataLink for this account")
        trust_pi.setToolTip(
            "Windows only loads PI DataLink for an account that has accepted its one-time "
            "trust prompt. The service account never sees that prompt, so this records the "
            "same trust for it — only for the PI add-ins an administrator installed."
        )
        trust_pi.clicked.connect(self._trust_pi_addins)
        trust_row = QHBoxLayout()
        trust_row.addWidget(self.pi_trust_status, 1)
        trust_row.addWidget(trust_pi)

        account_form.addRow(account_hint)
        account_form.addRow("Runs as", self.service_account)
        account_form.addRow("User", user_row)
        account_form.addRow("Password", self.account_password)
        account_form.addRow("", apply_row)
        account_form.addRow("PI DataLink", trust_row)

        groups_box = self._build_email_groups()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setProperty("accent", True)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        self.settings_tabs = QTabWidget()
        for form in (smtp_form, rcpt_form, app_form, account_form, self._group_form):
            space_layout(form)
        for spin in (
            self.smtp_port,
            self.max_concurrency,
            self.default_timeout,
            self.log_retention,
        ):
            spin.setMaximumWidth(220)
        for title, boxes in (
            ("Email", [smtp_box, rcpt_box]),
            ("Application", [app_box]),
            ("Service account", [account_box]),
            # Last, so "Service account" keeps its index (focus_service_account).
            ("Email groups", [groups_box]),
        ):
            page = QWidget()
            page_layout = QVBoxLayout(page)
            for box in boxes:
                page_layout.addWidget(box)
            page_layout.addStretch()
            space_layout(page_layout)
            self.settings_tabs.addTab(scroll_page(page), title)
        layout.addWidget(self.settings_tabs)
        layout.addWidget(buttons)
        space_layout(layout)

    def _build_email_groups(self) -> QGroupBox:
        """A named list of addresses a job can put in To/Cc/Bcc instead of each address."""
        box = QGroupBox("Email groups")
        outer = QVBoxLayout(box)
        hint = QLabel(
            "Give a list of addresses a name, then use that name in any job's To, Cc or Bcc. "
            "Change the group here and every job that uses it follows. Someone who is in two "
            "groups on the same email still gets it once."
        )
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        outer.addWidget(hint)

        row = QHBoxLayout()
        left = QVBoxLayout()
        self.group_list = QListWidget()
        self.group_list.setMinimumWidth(200)
        self.group_list.currentRowChanged.connect(self._show_group)
        new_group = QPushButton("+ New group")
        new_group.clicked.connect(self._new_group)
        self.delete_group = QPushButton("Delete")
        self.delete_group.clicked.connect(self._delete_group)
        group_buttons = QHBoxLayout()
        group_buttons.addWidget(new_group)
        group_buttons.addWidget(self.delete_group)
        left.addWidget(self.group_list)
        left.addLayout(group_buttons)

        right = QWidget()
        self._group_form = QFormLayout(right)
        self.group_name = QLineEdit()
        self.group_name.setPlaceholderText("e.g. Plant managers")
        self.group_name.textEdited.connect(self._group_name_edited)
        self.group_members = RecipientField(
            allow_groups=False, placeholder="Type or paste addresses…"
        )
        self.group_members.setToolTip(
            "The group's addresses. Type to search addresses the app already knows; Enter, "
            "Tab, comma or semicolon adds it, and a pasted list is split."
        )
        self.group_members.changed.connect(self._group_members_edited)
        self.group_used = QLabel("")
        self.group_used.setWordWrap(True)
        self.group_used.setProperty("muted", True)
        self._group_form.addRow("Name", self.group_name)
        self._group_form.addRow("Members", self.group_members)
        self._group_form.addRow("", self.group_used)
        row.addLayout(left)
        row.addWidget(right, 1)
        outer.addLayout(row)
        self._groups: list[dict[str, Any]] = []
        self._groups_changed = False
        self._show_group(-1)
        return box

    def _load_email_groups(self, cfg: dict[str, Any]) -> None:
        self._config = cfg
        self._groups = [
            {"name": g["name"], "members": list(g.get("members") or []), "original": g["name"]}
            for g in (cfg.get("email") or {}).get("groups") or []
        ]
        self.group_members.set_suggestions(known_addresses(cfg), {})
        self._groups_changed = False
        self._refresh_group_list(0 if self._groups else -1)

    def _refresh_group_list(self, select: int) -> None:
        self.group_list.blockSignals(True)
        self.group_list.clear()
        for g in self._groups:
            self.group_list.addItem(f"{g['name'] or '(unnamed)'}  ({len(g['members'])})")
        self.group_list.blockSignals(False)
        self.group_list.setCurrentRow(select)
        self._show_group(select)

    def _current_group(self) -> dict[str, Any] | None:
        row = self.group_list.currentRow()
        return self._groups[row] if 0 <= row < len(self._groups) else None

    def _show_group(self, row: int) -> None:
        group = self._groups[row] if 0 <= row < len(self._groups) else None
        for widget in (self.group_name, self.group_members, self.delete_group):
            widget.setEnabled(group is not None)
        self._showing_group = True
        self.group_name.setText(group["name"] if group else "")
        self.group_members.set_value(group["members"] if group else [])
        self._showing_group = False
        if group is None:
            self.group_used.setText("")
            return
        used = jobs_using_group(self._config, group["original"]) if group["original"] else []
        self.group_used.setText(
            f"Used by {len(used)} job(s): {', '.join(used)}" if used else "Not used by any job yet."
        )

    def _group_name_edited(self, text: str) -> None:
        group = self._current_group()
        if group is not None:
            group["name"] = text.strip()
            self._groups_changed = True
            item = self.group_list.currentItem()
            if item is not None:
                item.setText(f"{group['name'] or '(unnamed)'}  ({len(group['members'])})")

    def _group_members_edited(self) -> None:
        group = self._current_group()
        if group is None or getattr(self, "_showing_group", False):
            return
        group["members"] = self.group_members.emails()
        self._groups_changed = True
        item = self.group_list.currentItem()
        if item is not None:
            item.setText(f"{group['name'] or '(unnamed)'}  ({len(group['members'])})")

    def _new_group(self) -> None:
        self._groups.append({"name": "", "members": [], "original": None})
        self._groups_changed = True
        self._refresh_group_list(len(self._groups) - 1)
        self.group_name.setFocus()

    def _delete_group(self) -> None:
        group = self._current_group()
        if group is None:
            return
        used = jobs_using_group(self._config, group["original"]) if group["original"] else []
        if used:
            QMessageBox.warning(
                self,
                "Email groups",
                f"{group['original']!r} is used by: {', '.join(used)}.\n\nRemove it from "
                "those jobs first, so their emails don't lose recipients.",
            )
            return
        confirm = QMessageBox.question(
            self, "Email groups", f"Delete the email group {group['name'] or '(unnamed)'!r}?"
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        row = self.group_list.currentRow()
        del self._groups[row]
        self._groups_changed = True
        self._refresh_group_list(min(row, len(self._groups) - 1))

    def _email_groups_problem(self) -> str | None:
        problem = self.group_members.commit_pending() if self._current_group() else None
        if problem:
            return f"Email group members: {problem}"
        names: set[str] = set()
        for g in self._groups:
            if not g["name"]:
                return "Every email group needs a name."
            if any(c in g["name"] for c in ",;@"):
                return f"Email group names can't contain , ; or @: {g['name']!r}"
            if g["name"].casefold() in names:
                return f"Two email groups are named {g['name']!r}."
            names.add(g["name"].casefold())
            if not g["members"]:
                return f"The email group {g['name']!r} has no addresses."
        return None

    def _email_groups_payload(self) -> list[dict[str, Any]]:
        return [
            {
                "name": g["name"],
                "members": g["members"],
                "renamed_from": g["original"]
                if g["original"] and g["original"] != g["name"]
                else None,
            }
            for g in self._groups
        ]

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
        # Stored in seconds; edited in minutes (rounded up so a limit never shrinks).
        self.default_timeout.setValue(-(-int(app_cfg.get("default_timeout_seconds", 900)) // 60))
        self.log_retention.setValue(int(app_cfg.get("log_retention_days", 30)))

        ui_cfg = cfg.get("ui", {})
        self.check_updates.setChecked(bool(ui_cfg.get("check_updates_on_startup", False)))
        self.debug_logging.setChecked(bool(app_cfg.get("debug_logging", False)))

        self._app_section_base: dict[str, Any] = app_cfg
        self._ui_section_base: dict[str, Any] = ui_cfg
        self._load_email_groups(cfg)
        self.password_status.setText(
            "A password is currently stored." if pw_set else "No password stored yet."
        )

        self._show_service_account()
        self._show_pi_trust()

    def _show_service_account(self) -> None:
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

    def _show_pi_trust(self) -> None:
        try:
            status = self._api.pi_trust_status()
        except ApiError:
            self.pi_trust_status.setText("Unknown — the service is not reachable.")
            return
        addins = status.get("addins") or []
        account = status.get("account") or "the service account"
        if not addins:
            self.pi_trust_status.setText("No PI add-ins are installed on this machine.")
            self.pi_trust_status.setStyleSheet("")
            return
        missing = _addin_labels(a for a in addins if not a.get("trusted"))
        if missing:
            self.pi_trust_status.setText(
                f"⚠ Not trusted for {account}: {', '.join(missing)} — PI cells will keep their "
                "last-saved values."
            )
            self.pi_trust_status.setStyleSheet("color: #e06c6c;")
        else:
            names = ", ".join(_addin_labels(addins))
            self.pi_trust_status.setText(f"✓ Trusted for {account}: {names}")
            self.pi_trust_status.setStyleSheet("color: #4ade80;")

    def _trust_pi_addins(self) -> None:
        try:
            resp = self._api.trust_pi_addins()
        except ApiError as e:
            QMessageBox.warning(self, "Trust PI DataLink", str(e))
            return
        results = resp.get("results") or []
        if not results:
            QMessageBox.information(
                self, "Trust PI DataLink", "No PI add-ins are installed on this machine."
            )
            return
        lines = "\n".join(f"• {r.get('label') or r['name']}: {r['result']}" for r in results)
        failed = any(str(r["result"]).startswith("failed") for r in results)
        (QMessageBox.warning if failed else QMessageBox.information)(
            self,
            "Trust PI DataLink",
            f"For {resp.get('account', 'the service account')}:\n{lines}\n\n"
            "Run a Build only to confirm PI DataLink connects.",
        )
        self._show_pi_trust()

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
        account = str(resp.get("account") or user)
        if self._wait_for_account(account):
            self._show_service_account()
            self._show_pi_trust()
            QMessageBox.information(
                self,
                "Service account",
                f"The service is now running as {account}.\n\n"
                "Run a Build only to confirm PI DataLink connects.",
            )
        else:
            QMessageBox.warning(
                self,
                "Service account",
                f"The account was changed to {account}, but the service hasn't come back "
                "as that account yet.\n\nRestart the 'ReportFlow' service (Windows Services) "
                "to finish switching.",
            )

    def _wait_for_account(self, account: str) -> bool:
        """Poll the service until it answers as ``account`` — True — or the wait runs out."""
        progress = QProgressDialog(
            f"Restarting the ReportFlow service as {account}…", "", 0, 0, self
        )
        progress.setWindowTitle("Service account")
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()
        deadline = time.monotonic() + _RESTART_WAIT_SECONDS
        want = _user_part(account)
        loop = QEventLoop(self)
        outcome = {"ok": False}

        def poll() -> None:
            try:
                running = str(self._api.system_status().get("service_account") or "")
            except ApiError:
                running = ""  # down while Windows restarts it — keep waiting
            if running and _user_part(running) == want:
                outcome["ok"] = True
                loop.quit()
            elif time.monotonic() >= deadline:
                loop.quit()

        # The first poll comes a full interval later: the service only exits after ~1.5 s.
        timer = QTimer(self)
        timer.timeout.connect(poll)
        timer.start(_RESTART_POLL_MS)
        loop.exec()
        timer.stop()
        progress.close()
        return outcome["ok"]

    def _save(self) -> None:
        group_problem = self._email_groups_problem()
        if group_problem:
            self.settings_tabs.setCurrentIndex(self.settings_tabs.count() - 1)
            QMessageBox.warning(self, "Email groups", group_problem)
            return
        sections: dict[str, Any] = {
            "smtp": self._smtp_form_values(),
            "test": {
                "recipients": _split_csv(self.test_recipients.text()),
                "developer_bundle_recipients": _split_csv(self.dev_recipients.text()),
            },
            "app": {
                **getattr(self, "_app_section_base", {}),
                "max_global_concurrency": self.max_concurrency.value(),
                "default_timeout_seconds": self.default_timeout.value() * 60,
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
            if self._groups_changed:
                self._api.put_email_groups(self._email_groups_payload())
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
