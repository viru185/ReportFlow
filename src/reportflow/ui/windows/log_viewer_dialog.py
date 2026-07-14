"""Full application log viewer: Service / Worker / UI rolling logs.

One-click process switch, colour by level, a level filter and a text search (grep + highlight).
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.api_client import ApiClient, ApiError
from reportflow.ui.log_format import LogHighlighter, filter_log_text
from reportflow.ui.style import ACCENT

_PROCESSES = ("service", "worker", "ui")
_PROCESS_LABELS = {"service": "Service", "worker": "Worker", "ui": "UI"}
_LEVELS = ("All", "Debug", "Info", "Success", "Warning", "Error")


class LogViewerDialog(QDialog):
    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._raw = ""
        self.setWindowTitle("Application logs")
        self.resize(860, 580)

        # One-click process switch (segmented toggle buttons instead of a 2-click dropdown),
        # on its own labelled row so it reads as a mode selector, not a toolbar button.
        self._process = "service"
        self._proc_group = QButtonGroup(self)
        self._proc_group.setExclusive(True)
        proc_row = QHBoxLayout()
        proc_row.setSpacing(5)
        proc_label = QLabel("Show log for:")
        proc_label.setProperty("muted", True)
        proc_row.addWidget(proc_label)
        proc_row.addSpacing(6)
        for name in _PROCESSES:
            btn = QPushButton(_PROCESS_LABELS[name])
            btn.setCheckable(True)
            btn.setChecked(name == self._process)
            btn.setToolTip(f"Show the {_PROCESS_LABELS[name]} log.")
            btn.setStyleSheet(
                f"QPushButton:checked {{ background: {ACCENT}; color: #ffffff; "
                f"border-color: {ACCENT}; }}"
            )
            btn.clicked.connect(lambda _=False, n=name: self._switch_process(n))
            self._proc_group.addButton(btn)
            proc_row.addWidget(btn)
        proc_row.addStretch()

        self.level = QComboBox()
        self.level.addItems(_LEVELS)
        self.level.setToolTip("Only show lines at or above this level.")
        self.level.currentIndexChanged.connect(lambda *_: self._render())

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip("Filter to matching lines and highlight the text.")
        self.search.textChanged.connect(lambda *_: self._render())

        self.tail = QSpinBox()
        self.tail.setRange(50, 5000)
        self.tail.setValue(500)
        self.tail.setSingleStep(100)
        self.tail.setToolTip("How many of the most recent log lines to fetch.")

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.reload)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Level:"))
        filters.addWidget(self.level)
        filters.addWidget(self.search, 1)
        filters.addWidget(QLabel("Lines:"))
        filters.addWidget(self.tail)
        filters.addWidget(refresh)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.text.setFont(mono)
        self._highlighter = LogHighlighter(self.text.document())

        layout = QVBoxLayout(self)
        layout.addLayout(proc_row)
        layout.addLayout(filters)
        layout.addWidget(self.text)

        self.reload()

    def _switch_process(self, name: str) -> None:
        self._process = name
        self.reload()

    def reload(self) -> None:
        try:
            self._raw = self._api.system_logs(self._process, self.tail.value())
        except ApiError as e:
            self._raw = ""
            self.text.setPlainText(f"(could not load logs: {e})")
            return
        self._render()

    def _render(self) -> None:
        min_level = self.level.currentText()
        min_level = "" if min_level == "All" else min_level
        search = self.search.text().strip()
        shown = filter_log_text(self._raw or "", min_level=min_level, search=search)
        self._highlighter.set_search(search)
        self.text.setPlainText(shown or "(no matching log lines)")
        scrollbar = self.text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
