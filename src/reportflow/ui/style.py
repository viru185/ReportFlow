"""Shared UI style: palette constants, app-wide QSS, and small widget helpers.

Applied once via ``app.setStyleSheet(APP_QSS)`` in ``ui.__main__`` so every window and dialog
inherits it. Status colors are the single source of truth for run/job state everywhere.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel

# -- palette ----------------------------------------------------------------------

ACCENT = "#2563eb"  # primary blue
ACCENT_DARK = "#1e40af"
BG = "#f5f6fa"
CARD_BG = "#ffffff"
BORDER = "#d9dce3"
TEXT = "#1f2430"
TEXT_MUTED = "#6b7280"

STATUS_COLORS: dict[str, tuple[str, str]] = {
    # status -> (foreground, background)
    "success": ("#166534", "#dcfce7"),
    "failed": ("#991b1b", "#fee2e2"),
    "timed_out": ("#991b1b", "#fee2e2"),
    "crashed": ("#991b1b", "#fee2e2"),
    "running": ("#92400e", "#fef3c7"),
    "never": ("#374151", "#e5e7eb"),
}


def status_colors(status: str | None) -> tuple[str, str]:
    return STATUS_COLORS.get((status or "never").lower(), STATUS_COLORS["never"])


# -- app-wide stylesheet ------------------------------------------------------------

APP_QSS = f"""
QMainWindow, QDialog {{
    background: {BG};
}}
QLabel {{
    color: {TEXT};
}}
QGroupBox {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 12px;
    padding: 10px 8px 8px 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {ACCENT_DARK};
}}
QPushButton {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 14px;
}}
QPushButton:hover {{
    border-color: {ACCENT};
    color: {ACCENT_DARK};
}}
QPushButton:disabled {{
    color: {TEXT_MUTED};
}}
QPushButton[accent="true"] {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: white;
    font-weight: 600;
}}
QPushButton[accent="true"]:hover {{
    background: {ACCENT_DARK};
}}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QListWidget, QTimeEdit {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 6px;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTimeEdit:focus {{
    border-color: {ACCENT};
}}
QMenuBar {{
    background: {CARD_BG};
    border-bottom: 1px solid {BORDER};
}}
QStatusBar {{
    background: {CARD_BG};
    border-top: 1px solid {BORDER};
    color: {TEXT_MUTED};
}}
QToolTip {{
    background: {TEXT};
    color: white;
    border: none;
    padding: 5px 8px;
}}
QFrame[card="true"] {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QLabel[muted="true"] {{
    color: {TEXT_MUTED};
}}
QLabel[h1="true"] {{
    font-size: 18px;
    font-weight: 700;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
"""


# -- widget helpers -----------------------------------------------------------------


def card_frame() -> QFrame:
    """A white rounded card container styled by the app QSS."""
    frame = QFrame()
    frame.setProperty("card", True)
    return frame


def status_badge(status: str | None) -> QLabel:
    """A small colored pill for a run/job status."""
    text = (status or "never run").replace("_", " ")
    fg, bg = status_colors(status)
    label = QLabel(text)
    label.setStyleSheet(
        f"color: {fg}; background: {bg}; border-radius: 8px; padding: 2px 10px; font-weight: 600;"
    )
    return label


def connection_pill(connected: bool) -> str:
    """Rich-text for the header connection indicator."""
    if connected:
        return '<span style="color:#166534;">●</span> Connected'
    return '<span style="color:#991b1b;">●</span> Service not reachable'
