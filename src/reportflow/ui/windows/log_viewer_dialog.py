"""Full application log viewer: Service / Worker / UI rolling logs with tail + refresh."""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.api_client import ApiClient, ApiError


class LogViewerDialog(QDialog):
    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self.setWindowTitle("Application logs")
        self.resize(820, 560)

        self.process = QComboBox()
        self.process.addItems(["service", "worker", "ui"])
        self.process.setToolTip("Which process's rolling log to view.")
        self.process.currentIndexChanged.connect(lambda *_: self.reload())

        self.tail = QSpinBox()
        self.tail.setRange(50, 5000)
        self.tail.setValue(500)
        self.tail.setSingleStep(100)
        self.tail.setToolTip("How many of the most recent log lines to show.")

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.reload)

        top = QHBoxLayout()
        top.addWidget(QLabel("Process:"))
        top.addWidget(self.process)
        top.addWidget(QLabel("Lines:"))
        top.addWidget(self.tail)
        top.addWidget(refresh)
        top.addStretch()

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.text.setFont(mono)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.text)

        self.reload()

    def reload(self) -> None:
        try:
            log = self._api.system_logs(self.process.currentText(), self.tail.value())
        except ApiError as e:
            self.text.setPlainText(f"(could not load logs: {e})")
            return
        self.text.setPlainText(log or "(log is empty)")
        scrollbar = self.text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
