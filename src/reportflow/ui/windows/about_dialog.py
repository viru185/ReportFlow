"""About — what is running, where its files are, and one click to copy it all for support.

Everything here is read-only text, never a box that looks editable. The service facts (its
version, the account it runs as, schedule, PI DataLink trust) are fetched in the background,
so the window opens instantly even when the service is slow or stopped.
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Callable
from typing import Any

import PySide6
from PySide6.QtCore import Qt, QThread, Signal, qVersion
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from reportflow import __about__ as about
from reportflow.core import paths
from reportflow.ui.api_client import ApiClient, ApiError
from reportflow.ui.assets import asset_icon, logo_pixmap
from reportflow.ui.feedback import repolish, toast
from reportflow.ui.kit import Button, PathLabel, Tag
from reportflow.ui.widgets import section_title

_FETCH_TIMEOUT = 4.0  # seconds: About must never hang on a stopped service
_RUNNING: set[_FactsThread] = set()  # fetches still in flight (kept alive until finished)


def _windows_text() -> str:
    release, version = platform.release(), platform.version()
    build = version.rsplit(".", 1)[-1] if version else ""
    return f"{platform.system()} {release}" + (f" (build {build})" if build else "")


def runtime_text() -> str:
    return f"Python {platform.python_version()} · Qt {qVersion()} · {_windows_text()}"


def _program_folder() -> str:
    return str(paths.install_dir()) if getattr(sys, "frozen", False) else sys.executable


def service_facts(api: Any) -> dict[str, Any]:
    """What the service says about itself; ``{"error": …}`` when it can't be reached."""
    facts: dict[str, Any] = {}
    try:
        facts["status"] = api.system_status(quiet=True)
    except ApiError as e:
        return {"error": str(e)}
    try:
        facts["trust"] = api.pi_trust_status()
    except (ApiError, AttributeError):
        pass
    return facts


class _FactsThread(QThread):
    done = Signal(dict)

    def __init__(self, api: Any) -> None:
        super().__init__()
        self._api = api

    def run(self) -> None:
        # A real client gets its own short-lived connection: the dashboard's client is busy
        # on the UI thread, and an About page must not wait 30 s for a stopped service.
        if isinstance(self._api, ApiClient):
            client = ApiClient(self._api.base_url, timeout=_FETCH_TIMEOUT)
            try:
                self.done.emit(service_facts(client))
            finally:
                client.close()
        else:
            self.done.emit(service_facts(self._api))


def _value(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class AboutDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        api: Any = None,
        on_help: Callable[[], None] | None = None,
        on_whats_new: Callable[[], None] | None = None,
        on_check_updates: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {about.NAME}")
        self.resize(600, 560)
        self._api = api
        self._facts: dict[str, Any] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # -- who --
        header = QHBoxLayout()
        header.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(56))
        header.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title = QLabel(about.NAME)
        title.setProperty("h1", True)
        title_row.addWidget(title)
        if "-" in about.VERSION:  # 0.14.0-beta
            title_row.addWidget(Tag(about.VERSION.split("-", 1)[1].capitalize(), kind="info"))
        title_row.addStretch(1)
        title_box.addLayout(title_row)
        version = QLabel(f"Version {about.VERSION}")
        version.setProperty("muted", True)
        title_box.addWidget(version)
        header.addLayout(title_box, 1)
        layout.addLayout(header)
        summary = QLabel(about.SUMMARY)
        summary.setWordWrap(True)
        summary.setProperty("muted", True)
        layout.addWidget(summary)

        # -- the service --
        layout.addWidget(section_title("Service"))
        service = QFormLayout()
        service.setHorizontalSpacing(16)
        service.setVerticalSpacing(8)
        self.service_state = _value("Checking…")
        self.service_version = _value("—")
        self.service_account = _value("—")
        self.service_schedule = _value("—")
        self.pi_trust = _value("—")
        for label, widget in (
            ("Status", self.service_state),
            ("Version", self.service_version),
            ("Runs as", self.service_account),
            ("Schedule", self.service_schedule),
            ("PI DataLink", self.pi_trust),
        ):
            service.addRow(self._key(label), widget)
        layout.addLayout(service)

        # -- where things are --
        layout.addWidget(section_title("Folders"))
        folders = QFormLayout()
        folders.setHorizontalSpacing(16)
        folders.setVerticalSpacing(6)
        self.folders = {
            "Data": PathLabel(str(paths.data_root())),
            "Logs": PathLabel(str(paths.logs_dir())),
            "Program": PathLabel(_program_folder()),
        }
        for name, path_label in self.folders.items():
            folders.addRow(self._key(name), path_label)
        layout.addLayout(folders)

        layout.addWidget(section_title("System"))
        self.runtime = _value(runtime_text())
        self.runtime.setProperty("muted", True)
        layout.addWidget(self.runtime)
        layout.addStretch(1)

        # -- actions (no Close: the title bar has one, and Esc closes) --
        actions = QHBoxLayout()
        actions.setSpacing(8)
        if on_help is not None:
            guide = Button("User guide", icon=asset_icon("list.svg"))
            guide.clicked.connect(on_help)
            actions.addWidget(guide)
        if on_whats_new is not None:
            whats_new = Button("What's new", icon=asset_icon("new.svg"))
            whats_new.clicked.connect(on_whats_new)
            actions.addWidget(whats_new)
        if on_check_updates is not None:
            updates = Button("Check for updates…", icon=asset_icon("refresh.svg"))
            updates.clicked.connect(on_check_updates)
            actions.addWidget(updates)
        actions.addStretch(1)
        copy = Button(
            "Copy details for support",
            variant="primary",
            tooltip="Copies everything on this page, ready to paste into an email to support.",
        )
        copy.clicked.connect(self.copy_details)
        actions.addWidget(copy)
        layout.addLayout(actions)

        if api is not None:
            # Not a child of the dialog: closing About mid-fetch must neither wait for the
            # service nor destroy a running thread (Qt aborts on that). The thread finishes
            # on its own; a closed dialog simply no longer receives the answer.
            thread = _FactsThread(api)
            _RUNNING.add(thread)
            thread.done.connect(self._show_facts)
            thread.finished.connect(lambda t=thread: _RUNNING.discard(t))
            thread.finished.connect(thread.deleteLater)
            thread.start()
        else:
            self._show_facts({"error": "not connected"})

    def _key(self, text: str) -> QLabel:
        """A row name; every row name is as wide as the widest, so the values line up
        across the Service and Folders sections."""
        label = QLabel(text)
        label.setProperty("muted", True)
        label.setMinimumWidth(label.fontMetrics().horizontalAdvance("PI DataLink") + 8)
        return label

    # -- service facts --

    def _show_facts(self, facts: dict[str, Any]) -> None:
        self._facts = facts
        if "error" in facts:
            self._set(self.service_state, "● Not reachable — is the ReportFlow service running?")
            self.service_state.setProperty("tone", "danger")
            repolish(self.service_state)
            for label in (
                self.service_version,
                self.service_account,
                self.service_schedule,
                self.pi_trust,
            ):
                self._set(label, "—")
            return
        status = facts.get("status") or {}
        base = getattr(self._api, "base_url", "")
        self._set(self.service_state, f"● Connected · {base}" if base else "● Connected")
        self.service_state.setProperty("tone", "success")
        repolish(self.service_state)
        version = str(status.get("version") or "—")
        if version not in ("—", about.VERSION):
            self._set(
                self.service_version,
                f"{version} — this app is {about.VERSION}; install the same version of both.",
            )
            self.service_version.setProperty("tone", "warning")
        else:
            self._set(self.service_version, version)
            self.service_version.setProperty("tone", "")
        repolish(self.service_version)
        account = str(status.get("service_account") or "unknown")
        if status.get("service_account_is_system"):
            account += " (LocalSystem — PI DataLink can't load; Settings → Service account)"
        self._set(self.service_account, account)
        triggers = len(status.get("scheduled_jobs") or [])
        active = len(status.get("active_runs") or [])
        self._set(
            self.service_schedule,
            f"{triggers} scheduled trigger{'s' if triggers != 1 else ''} · "
            f"{active} run{'s' if active != 1 else ''} in progress",
        )
        trust = facts.get("trust")
        if not trust:
            self._set(self.pi_trust, "—")
            return
        addins = trust.get("addins") or []
        labels = list(dict.fromkeys(str(a.get("label") or a.get("name")) for a in addins))
        missing = [str(a.get("label") or a.get("name")) for a in addins if not a.get("trusted")]
        if not addins:
            self._set(self.pi_trust, "Not installed on this machine")
            tone = ""
        elif missing:
            self._set(
                self.pi_trust,
                f"Not trusted: {', '.join(dict.fromkeys(missing))} — Settings → Service account",
            )
            tone = "danger"
        else:
            self._set(self.pi_trust, f"Trusted: {', '.join(labels)}")
            tone = "success"
        self.pi_trust.setProperty("tone", tone)
        repolish(self.pi_trust)

    @staticmethod
    def _set(label: QLabel, text: str) -> None:
        label.setText(text)

    # -- support --

    def details_text(self) -> str:
        lines = [
            f"{about.NAME} {about.VERSION}",
            f"Service: {self.service_state.text().lstrip('● ')}",
            f"Service version: {self.service_version.text()}",
            f"Runs as: {self.service_account.text()}",
            f"Schedule: {self.service_schedule.text()}",
            f"PI DataLink: {self.pi_trust.text()}",
        ]
        lines += [f"{name} folder: {label.path()}" for name, label in self.folders.items()]
        lines.append(f"System: {self.runtime.text()} · PySide6 {PySide6.__version__}")
        return "\n".join(lines)

    def copy_details(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.details_text())
        toast(self, "Details copied — paste them into your email to support.", "success")
