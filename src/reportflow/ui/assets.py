"""Locate bundled UI assets (logo) in both source checkouts and frozen builds.

If the logo file is missing (e.g. before ``packaging/make_logo.py`` has run), a simple
programmatic mark is drawn instead so the UI never shows a blank icon.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap


def _assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller: datas land under _MEIPASS (the _internal dir for onedir builds).
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "assets"
    return Path(__file__).resolve().parents[3] / "assets"


def logo_path() -> Path | None:
    p = _assets_dir() / "reportflow.png"
    return p if p.exists() else None


def _fallback_pixmap(size: int) -> QPixmap:
    """A drawn placeholder: blue rounded square with a white 'R'."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#2563eb"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
    painter.setPen(QColor("white"))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(int(size * 0.62))
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "R")
    painter.end()
    return pix


def logo_pixmap(size: int = 32) -> QPixmap:
    path = logo_path()
    if path is not None:
        pix = QPixmap(str(path))
        if not pix.isNull():
            return pix.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
    return _fallback_pixmap(size)


def app_icon() -> QIcon:
    return QIcon(logo_pixmap(256))
