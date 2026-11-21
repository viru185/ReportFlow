"""Labels that never push a layout wider than its window.

A plain QLabel holding a file path with no spaces is as wide as the whole path — that is
what made the job editor scroll sideways on real (long) paths. These labels shorten text
instead (with the full text in a tooltip), or make it breakable.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontMetrics, QGuiApplication, QPainter, QPaintEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from reportflow.ui.assets import asset_icon
from reportflow.ui.kit.buttons import IconButton

_ZWSP = "​"


def breakable(text: str) -> str:
    """``text`` with invisible break points after path separators and underscores, so a
    word-wrapped label can wrap a long path instead of growing to its full width."""
    for sep in ("\\", "/", "_"):
        text = text.replace(sep, sep + _ZWSP)
    return text


class ElidedLabel(QLabel):
    """A one-line label that shortens long text — in the middle by default
    ("Aditya_PI_Vis…31_Oct.xlsx"), so a file's start and extension both stay visible."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle,
        max_hint: int = 320,
    ) -> None:
        super().__init__(parent)
        self._full = text
        self._mode = mode
        self._max_hint = max_hint
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(24)
        super().setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        super().setText(text)
        self.update()

    def full_text(self) -> str:
        return self._full

    def is_elided(self) -> bool:
        return QFontMetrics(self.font()).horizontalAdvance(self._full) > self.width()

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(min(hint.width(), self._max_hint), hint.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(24, super().minimumSizeHint().height())

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.setFont(self.font())
        rect = self.contentsRect()
        metrics = QFontMetrics(self.font())
        shown = metrics.elidedText(self._full, self._mode, rect.width())
        align = self.alignment()
        if not align & Qt.AlignmentFlag.AlignVertical_Mask:
            align |= Qt.AlignmentFlag.AlignVCenter
        painter.drawText(rect, int(align), shown)


def open_folder(path: str) -> None:
    """Show ``path`` (a folder, or the folder holding a file) in Explorer."""
    target = Path(path)
    if target.is_file():
        subprocess.Popen(["explorer", "/select,", str(target)])  # noqa: S603,S607
    elif target.exists() and hasattr(os, "startfile"):
        os.startfile(str(target))  # noqa: S606 — Windows only, the user's own folder


class PathLabel(QWidget):
    """A file or folder path as plain text (never a box that looks editable), shortened in
    the middle, with icon buttons to copy it and to open its folder."""

    def __init__(
        self,
        path: str = "",
        parent: QWidget | None = None,
        *,
        copy: bool = True,
        open_button: bool = True,
        muted: bool = True,
    ) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.label = ElidedLabel(path)
        self.label.setObjectName("pathText")
        if muted:
            self.label.setProperty("muted", True)
        row.addWidget(self.label, 1)
        self.copy_button: IconButton | None = None
        self.open_button: IconButton | None = None
        if copy:
            self.copy_button = IconButton(
                asset_icon("copy.svg"), "Copy path", size=24, icon_size=14
            )
            self.copy_button.clicked.connect(self._copy)
            row.addWidget(self.copy_button)
        if open_button:
            self.open_button = IconButton(
                asset_icon("folder.svg"), "Open in Explorer", size=24, icon_size=14
            )
            self.open_button.clicked.connect(lambda: open_folder(self.path()))
            row.addWidget(self.open_button)
        self.set_path(path)

    def set_path(self, path: str) -> None:
        self.label.setText(path)
        self.label.setToolTip(path)
        for button in (self.copy_button, self.open_button):
            if button is not None:
                button.setEnabled(bool(path))

    def path(self) -> str:
        return self.label.full_text()

    def text(self) -> str:
        """The full path (like ``QLabel.text``)."""
        return self.path()

    def _copy(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.path())
        from reportflow.ui.feedback import toast

        toast(self, "Path copied.", "success")


class Tag(QLabel):
    """A small rounded label ("emailed", "kept on disk", "Beta"). ``kind``: neutral, info,
    success, warning, danger."""

    def __init__(self, text: str, parent: QWidget | None = None, *, kind: str = "neutral") -> None:
        super().__init__(text, parent)
        self.setProperty("tag", kind)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_kind(self, kind: str) -> None:
        self.setProperty("tag", kind)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
