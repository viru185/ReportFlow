"""About / Project Info dialog — app identity, developer links, and support info."""

from __future__ import annotations

import platform
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from reportflow import __about__ as about
from reportflow.core import paths
from reportflow.ui.assets import logo_pixmap


class AboutDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        api_base_url: str = "",
        connected: bool | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {about.NAME}")
        self.setFixedWidth(460)

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(logo_pixmap(56))
        header.addWidget(logo)
        title_box = QVBoxLayout()
        title = QLabel(about.NAME)
        title.setProperty("h1", True)
        version = QLabel(f"Version {about.VERSION}")
        version.setProperty("muted", True)
        title_box.addWidget(title)
        title_box.addWidget(version)
        header.addLayout(title_box)
        header.addStretch()
        layout.addLayout(header)

        summary = QLabel(about.SUMMARY)
        summary.setWordWrap(True)
        layout.addWidget(summary)

        links = QLabel(
            f"Developer: <b>{about.AUTHOR}</b><br>"
            f'Repository: <a href="{about.REPO_URL}">{about.REPO_URL}</a><br>'
            f'GitHub: <a href="{about.GITHUB_URL}">{about.GITHUB_URL}</a><br>'
            f'LinkedIn: <a href="{about.LINKEDIN_URL}">{about.LINKEDIN_URL}</a>'
        )
        links.setOpenExternalLinks(True)
        links.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        layout.addWidget(links)

        status = "—" if connected is None else ("connected" if connected else "not reachable")
        env = QLabel(
            f"Python {platform.python_version()} · {platform.system()} {platform.release()}<br>"
            f"Data directory: {paths.data_root()}<br>"
            f"Service API: {api_base_url or '—'} ({status})<br>"
            f"Executable: {sys.executable}"
        )
        env.setProperty("muted", True)
        env.setWordWrap(True)
        env.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(env)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.clicked.connect(lambda *_: self.accept())
        layout.addWidget(buttons)
