"""Shared UI style: a complete DARK theme (palette + QSS + widget helpers).

ReportFlow is deliberately dark-themed and independent of the OS light/dark setting.
``apply_theme(app)`` is the single entry point: it activates the Fusion style (so the
OS-native style can't inject its own colors), installs a matching dark ``QPalette`` (for
anything QSS doesn't reach, e.g. hyperlink color), and applies the app-wide QSS in which
every widget sets BOTH its text color and background — no combination is ever left to the
system palette, which is what previously produced white-on-white text on Windows dark mode.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QFrame, QLabel


def _check_svg_url() -> str:
    """QSS url() for the white checkmark used by checked indicators ('' if missing)."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "assets"
    else:
        base = Path(__file__).resolve().parents[3] / "assets"
    svg = base / "check.svg"
    return svg.as_posix() if svg.exists() else ""


# -- palette ----------------------------------------------------------------------

BG = "#16181d"  # window background
CARD_BG = "#1f2229"  # cards, menus, bars
FIELD_BG = "#262a33"  # inputs / editors / lists
BORDER = "#363b47"
TEXT = "#e6e9f0"
TEXT_MUTED = "#9aa1b0"
ACCENT = "#3b82f6"  # primary blue
ACCENT_HOVER = "#60a5fa"
LINK = "#60a5fa"

STATUS_COLORS: dict[str, tuple[str, str]] = {
    # status -> (foreground, background) — bright text on a deep tinted pill
    "success": ("#4ade80", "#14331f"),
    "failed": ("#f87171", "#3b1a1a"),
    "timed_out": ("#f87171", "#3b1a1a"),
    "crashed": ("#f87171", "#3b1a1a"),
    "running": ("#fbbf24", "#3a2c10"),
    "never": ("#c3c8d4", "#2b2f3a"),
}


def status_colors(status: str | None) -> tuple[str, str]:
    return STATUS_COLORS.get((status or "never").lower(), STATUS_COLORS["never"])


# Foreground colour per loguru level, used to tint the level token (and whole lines when the
# line can't be parsed into segments). INFO keeps the default text colour so ordinary lines
# aren't over-coloured; only notable levels stand out.
LOG_LEVEL_COLORS: dict[str, str] = {
    "TRACE": TEXT_MUTED,
    "DEBUG": "#7f8896",
    "INFO": TEXT,
    "SUCCESS": "#4ade80",
    "WARNING": "#fbbf24",
    "ERROR": "#f87171",
    "CRITICAL": "#f87171",
}

# Segment colours for the console-style per-token colouring (date | level | location | msg).
LOG_TIME = "#6b8bd6"  # muted blue for the timestamp
LOG_LOCATION = TEXT_MUTED  # module:function:line


# -- app-wide stylesheet ------------------------------------------------------------

_CHECK_URL = _check_svg_url()

APP_QSS = f"""
QMainWindow, QDialog, QMessageBox {{
    background: {BG};
    color: {TEXT};
}}
QWidget {{
    color: {TEXT};
}}
QLabel {{
    color: {TEXT};
    background: transparent;
}}
QLabel[muted="true"] {{
    color: {TEXT_MUTED};
}}
QLabel[h1="true"] {{
    font-size: 18px;
    font-weight: 700;
    color: {TEXT};
}}
QGroupBox {{
    background: {CARD_BG};
    color: {TEXT};
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
    color: {ACCENT_HOVER};
}}
QPushButton {{
    background: {FIELD_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 14px;
}}
QPushButton:hover {{
    border-color: {ACCENT};
    color: {ACCENT_HOVER};
}}
QPushButton:pressed {{
    background: {BG};
}}
QPushButton:disabled {{
    color: {TEXT_MUTED};
    background: {CARD_BG};
}}
QPushButton[accent="true"] {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton[accent="true"]:hover {{
    background: {ACCENT_HOVER};
}}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QTextBrowser, QListWidget,
QTimeEdit {{
    background: {FIELD_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 6px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTimeEdit:focus {{
    border-color: {ACCENT};
}}
QLineEdit:read-only {{
    color: {TEXT_MUTED};
}}
QLineEdit::placeholder {{
    color: {TEXT_MUTED};
}}
QComboBox QAbstractItemView {{
    background: {CARD_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QListWidget::item {{
    color: {TEXT};
    padding: 2px;
}}
QListWidget::item:selected {{
    background: {ACCENT};
    color: #ffffff;
}}
QCheckBox, QRadioButton {{
    color: {TEXT};
    background: transparent;
    spacing: 6px;
}}
QCheckBox:disabled, QRadioButton:disabled {{
    color: {TEXT_MUTED};
}}
QCheckBox::indicator, QGroupBox::indicator, QListView::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {TEXT_MUTED};
    border-radius: 4px;
    background: {FIELD_BG};
}}
QCheckBox::indicator:hover, QGroupBox::indicator:hover, QListView::indicator:hover {{
    border-color: {ACCENT_HOVER};
}}
QCheckBox::indicator:checked, QGroupBox::indicator:checked, QListView::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: url("{_CHECK_URL}");
}}
QCheckBox::indicator:disabled, QListView::indicator:disabled {{
    border-color: {BORDER};
    background: {CARD_BG};
}}
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {TEXT_MUTED};
    border-radius: 8px;
    background: {FIELD_BG};
}}
QRadioButton::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    background: {FIELD_BG};
}}
QTabBar::tab {{
    background: {CARD_BG};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 5px 16px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: {FIELD_BG};
    color: {TEXT};
}}
QMenuBar {{
    background: {CARD_BG};
    color: {TEXT};
    border-bottom: 1px solid {BORDER};
}}
QMenuBar::item {{
    background: transparent;
    color: {TEXT};
    padding: 4px 10px;
}}
QMenuBar::item:selected {{
    background: {FIELD_BG};
    color: {ACCENT_HOVER};
}}
QMenu {{
    background: {CARD_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
}}
QMenu::item {{
    padding: 5px 24px 5px 16px;
}}
QMenu::item:selected {{
    background: {ACCENT};
    color: #ffffff;
}}
QStatusBar {{
    background: {CARD_BG};
    border-top: 1px solid {BORDER};
    color: {TEXT_MUTED};
}}
QToolTip {{
    background: {FIELD_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 5px 8px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: {BG};
    width: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 24px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background: {TEXT_MUTED};
}}
QScrollBar:horizontal {{
    background: {BG};
    height: 12px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 5px;
    min-width: 24px;
    margin: 2px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}
QFrame[card="true"] {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame[card="true"][edge="success"] {{
    border-left: 3px solid #4ade80;
}}
QFrame[card="true"][edge="failed"] {{
    border-left: 3px solid #e06c6c;
}}
QFrame[card="true"][edge="running"] {{
    border-left: 3px solid #fbbf24;
}}
QFrame[card="true"][edge="muted"] {{
    border-left: 3px solid #3a3f4d;
}}
QToolButton {{
    background: {FIELD_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 10px;
}}
QToolButton:hover {{
    border-color: {ACCENT};
    color: {ACCENT_HOVER};
}}
QToolButton:pressed {{
    background: {BG};
}}
QToolButton::menu-indicator {{
    image: none;
}}
"""


def apply_theme(app: QApplication) -> None:
    """Activate the ReportFlow dark theme: Fusion style + dark palette + app QSS."""
    app.setStyle("Fusion")

    palette = QPalette()
    groups = (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive)
    roles = {
        QPalette.ColorRole.Window: BG,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: FIELD_BG,
        QPalette.ColorRole.AlternateBase: CARD_BG,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: FIELD_BG,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.ToolTipBase: FIELD_BG,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: TEXT_MUTED,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Link: LINK,
        QPalette.ColorRole.LinkVisited: LINK,
        QPalette.ColorRole.BrightText: "#ffffff",
    }
    for group in groups:
        for role, color in roles.items():
            palette.setColor(group, role, QColor(color))
    disabled = QPalette.ColorGroup.Disabled
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(disabled, role, QColor(TEXT_MUTED))
    app.setPalette(palette)

    app.setStyleSheet(APP_QSS)


# -- widget helpers -----------------------------------------------------------------


def card_frame(edge: str | None = None) -> QFrame:
    """A rounded card container styled by the app QSS.

    ``edge`` paints a coloured left border ("success" / "failed" / "running" / "muted") —
    the quiet replacement for an always-on status pill on job cards."""
    frame = QFrame()
    frame.setProperty("card", True)
    if edge:
        frame.setProperty("edge", edge)
    return frame


def status_edge(status: str | None, *, paused: bool = False) -> str:
    """Map a job's last run status to a card edge colour key."""
    if paused:
        return "muted"
    s = (status or "").lower()
    if s == "success":
        return "success"
    if s in ("failed", "timed_out", "crashed"):
        return "failed"
    if s == "running":
        return "running"
    return "muted"


def status_badge(status: str | None, suffix: str = "") -> QLabel:
    """A small colored pill for a run/job status; ``suffix`` appends live detail
    (e.g. the elapsed seconds while a run is in flight)."""
    text = (status or "never run").replace("_", " ")
    if suffix:
        text = f"{text} {suffix}"
    fg, bg = status_colors(status)
    label = QLabel(text)
    label.setStyleSheet(
        f"color: {fg}; background: {bg}; border-radius: 8px; padding: 2px 10px; font-weight: 600;"
    )
    return label


def disabled_badge() -> QLabel:
    """Grey pill marking a job whose scheduling is paused (manual runs still work)."""
    label = QLabel("⏸ PAUSED")
    label.setToolTip("Scheduling is paused — click ▸ Resume to re-enable. Manual runs still work.")
    label.setStyleSheet(
        "color: #c3c8d4; background: #2b2f3a; border-radius: 8px; padding: 2px 10px; "
        "font-weight: 600;"
    )
    return label


def stage_badge(stage: str) -> QLabel:
    """Lifecycle pill: amber TESTING (emails testers) / green LIVE (emails the client)."""
    live = stage == "live"
    fg, bg = ("#4ade80", "#14331f") if live else ("#fbbf24", "#3a2c10")
    label = QLabel("LIVE" if live else "TESTING")
    label.setToolTip(
        "Runs email the Production recipients."
        if live
        else "Runs email only the Test recipients until you click Go live."
    )
    label.setStyleSheet(
        f"color: {fg}; background: {bg}; border-radius: 8px; padding: 2px 10px; font-weight: 600;"
    )
    return label


def connection_pill(connected: bool) -> str:
    """Rich-text for the header connection indicator."""
    if connected:
        return '<span style="color:#4ade80;">●</span> Connected'
    return '<span style="color:#f87171;">●</span> Service not reachable'
