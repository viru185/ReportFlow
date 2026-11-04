"""About dialog — application identity and environment information."""

from __future__ import annotations

import platform
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from reportflow import __about__ as about
from reportflow.core import paths
from reportflow.ui.assets import logo_pixmap
from reportflow.ui.widgets import section_title, space_layout


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
        self.resize(560, 480)

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

        status = "—" if connected is None else ("connected" if connected else "not reachable")
        layout.addWidget(section_title("Environment"))
        environment = QFormLayout()
        for label, value in (
            (
                "Runtime",
                f"Python {platform.python_version()} · {platform.system()} {platform.release()}",
            ),
            ("Data directory", str(paths.data_root())),
            ("Service API", f"{api_base_url or '—'} ({status})"),
            ("Executable", sys.executable),
        ):
            if label in ("Data directory", "Executable"):
                path_field = QPlainTextEdit(value)
                path_field.setReadOnly(True)
                path_field.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
                path_field.setFixedHeight(60)
                path_field.setAccessibleName(label)
                environment.addRow(label, path_field)
            else:
                field = QLabel(value)
                field.setTextFormat(Qt.TextFormat.PlainText)
                field.setProperty("muted", True)
                field.setWordWrap(True)
                field.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                environment.addRow(label, field)
        layout.addLayout(environment)
        layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.clicked.connect(lambda *_: self.accept())
        layout.addWidget(buttons)
        space_layout(layout)
