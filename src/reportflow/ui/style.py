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

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QSizePolicy

from reportflow.core.config.models import stage_label


def _asset_url(name: str) -> str:
    """QSS url() for the white checkmark used by checked indicators ('' if missing)."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "assets"
    else:
        base = Path(__file__).resolve().parents[3] / "assets"
    svg = base / name
    return svg.as_posix() if svg.exists() else ""


# -- palette ----------------------------------------------------------------------

BG = "#16181d"  # window background
CARD_BG = "#1f2229"  # cards, menus, bars
FIELD_BG = "#262a33"  # inputs / editors / lists
BORDER = "#363b47"
BORDER_HOVER = "#4a5263"  # a field the pointer is over
TEXT = "#e6e9f0"
TEXT_MUTED = "#9aa1b0"
ACCENT = "#3b82f6"  # primary blue
ACCENT_HOVER = "#60a5fa"
LINK = "#60a5fa"
ERROR = "#e06c6c"  # invalid field outline, field error text

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

_CHECK_URL = _asset_url("check.svg")
_DOWN_URL = _asset_url("arrow-down.png")
_UP_URL = _asset_url("arrow-up.png")

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
QLabel[section="true"] {{
    font-weight: 600;
    padding-top: 4px;
    padding-bottom: 4px;
}}
QLabel#scheduleOverview {{
    background: #172c48;
    border: 1px solid #355d8c;
    border-radius: 6px;
    padding: 12px;
    font-size: 15px;
    font-weight: 600;
}}
QPushButton[timeChip="true"] {{
    background: #172c48;
    border-color: #507eaf;
    color: #dbeafe;
    font-size: 16px;
    font-weight: 600;
    padding: 8px 12px;
}}
QFrame[recipientField="true"] {{
    background: {FIELD_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QFrame[recipientField="true"][invalid="true"] {{
    border-color: #e06c6c;
}}
QFrame[recipientField="true"] QLineEdit {{
    background: transparent;
    border: none;
    padding: 3px 2px;
}}
QFrame[recipientChip="true"] {{
    background: #2a303c;
    border: 1px solid #434b5c;
    border-radius: 12px;
}}
QFrame[groupChip="true"] {{
    background: #172c48;
    border-color: #507eaf;
}}
QFrame[recipientChip="true"][flash="true"] {{
    background: #1d3a5f;
    border-color: {ACCENT_HOVER};
}}
QFrame[recipientChip="true"] QLabel#chipText {{
    color: {TEXT};
}}
QFrame[groupChip="true"] QLabel#chipText {{
    color: #dbeafe;
}}
QFrame[recipientChip="true"] QToolButton#chipRemove {{
    background: transparent;
    border: none;
    border-radius: 9px;
    color: {TEXT_MUTED};
    font-size: 14px;
    padding: 0;
}}
QFrame[recipientChip="true"] QToolButton#chipRemove:hover {{
    background: #3b2326;
    color: #f87171;
}}
QGroupBox {{
    background: {CARD_BG};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 12px;
    padding: 0;
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
    padding: 6px 12px;
    min-height: 20px;
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
QPushButton[segment="true"]:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: #ffffff;
    font-weight: 600;
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
QPushButton[accent="true"]:disabled {{
    background: {CARD_BG};
    border-color: {BORDER};
    color: {TEXT_MUTED};
}}
QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QTextBrowser, QListWidget,
QTimeEdit, QTableWidget {{
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
QLineEdit, QComboBox {{
    min-height: 24px;
}}
QComboBox {{
    padding-right: 28px;
}}
QLineEdit:read-only {{
    color: {TEXT_MUTED};
}}
QLineEdit::placeholder {{
    color: {TEXT_MUTED};
}}
QPushButton:focus, QToolButton:focus {{
    border-color: {ACCENT_HOVER};
}}
QComboBox:hover, QSpinBox:hover, QTimeEdit:hover {{
    border-color: {BORDER_HOVER};
}}
QComboBox:focus, QSpinBox:focus, QTimeEdit:focus {{
    border-color: {ACCENT};
}}
/* The arrow area sits INSIDE the rounded border and has no fill or separator of its own,
   so no square corner can poke through the field's radius (Fluent-style chevron). */
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 28px;
    border: none;
    background: transparent;
}}
QSpinBox, QTimeEdit {{
    min-height: 24px;
    padding-right: 26px;
}}
QSpinBox::up-button, QTimeEdit::up-button,
QSpinBox::down-button, QTimeEdit::down-button {{
    subcontrol-origin: padding;
    width: 22px;
    border: none;
    background: transparent;
}}
QSpinBox::up-button, QTimeEdit::up-button {{
    subcontrol-position: top right;
    border-top-right-radius: 5px;
}}
QSpinBox::down-button, QTimeEdit::down-button {{
    subcontrol-position: bottom right;
    border-bottom-right-radius: 5px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QTimeEdit::up-button:hover, QTimeEdit::down-button:hover {{
    background: {BORDER};
}}
QComboBox::down-arrow, QSpinBox::down-arrow, QTimeEdit::down-arrow {{
    image: url("{_DOWN_URL}");
    width: 12px;
    height: 12px;
}}
QSpinBox::up-arrow, QTimeEdit::up-arrow {{
    image: url("{_UP_URL}");
    width: 12px;
    height: 12px;
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
QTableWidget {{
    gridline-color: {BORDER};
}}
QTableWidget::item {{
    color: {TEXT};
}}
QTableWidget::item:disabled {{
    color: {TEXT_MUTED};
}}
QHeaderView::section {{
    background: {CARD_BG};
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 3px 6px;
}}
QTableCornerButton::section {{
    background: {CARD_BG};
    border: none;
}}
QCheckBox, QRadioButton {{
    color: {TEXT};
    background: transparent;
    spacing: 6px;
}}
QCheckBox:disabled, QRadioButton:disabled {{
    color: {TEXT_MUTED};
}}
QCheckBox::indicator, QGroupBox::indicator, QListView::indicator, QTableView::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {TEXT_MUTED};
    border-radius: 4px;
    background: {FIELD_BG};
}}
QCheckBox::indicator:hover, QGroupBox::indicator:hover, QListView::indicator:hover,
QTableView::indicator:hover {{
    border-color: {ACCENT_HOVER};
}}
QCheckBox::indicator:checked, QGroupBox::indicator:checked, QListView::indicator:checked,
QTableView::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
    image: url("{_CHECK_URL}");
}}
QCheckBox::indicator:disabled, QListView::indicator:disabled, QTableView::indicator:disabled {{
    border-color: {BORDER};
    background: {CARD_BG};
}}
QTableView::indicator:checked:disabled {{
    /* a not-applicable cell (e.g. PDF of a sheet that isn't included) must not read "on" */
    image: none;
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
QFrame[card="true"]:focus {{
    border-color: {ACCENT_HOVER};
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
QFrame[card="true"][paused="true"] {{
    background: {BG};
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
QListView#completerPopup {{
    background: {CARD_BG};
    color: {TEXT};
    border: 1px solid {BORDER_HOVER};
    border-radius: 6px;
    padding: 4px;
    outline: none;
}}
QListView#completerPopup::item {{
    padding: 5px 8px;
    border-radius: 4px;
}}
QListView#completerPopup::item:hover {{
    background: {FIELD_BG};
}}
QListView#completerPopup::item:selected {{
    background: {ACCENT};
    color: #ffffff;
}}
/* -- workbook list (ui/windows/workbook_panel.py) -- */
QListWidget#workbookItems {{
    padding: 4px;
    outline: none;
}}
QListWidget#workbookItems::item {{
    border-radius: 6px;
    margin: 1px 0;
}}
QListWidget#workbookItems::item:selected {{
    background: #1f3350;
}}
QFrame#workbookRow {{
    background: transparent;
    border-radius: 6px;
}}
QFrame#workbookRow:hover {{
    background: rgba(255, 255, 255, 0.04);
}}
QFrame#workbookRow[flash="true"] {{
    background: #1d3a5f;
}}
QLabel#workbookName {{
    font-weight: 600;
    color: {TEXT};
}}
QLabel#workbookStatus {{
    font-size: 12px;
    color: {TEXT_MUTED};
}}
QLabel#workbookStatus[kind="warning"] {{
    color: #fbbf24;
}}
QLabel#workbookStatus[kind="busy"] {{
    color: {ACCENT_HOVER};
}}
QToolButton#workbookAction {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 0;
    color: {TEXT_MUTED};
}}
QToolButton#workbookAction:hover {{
    background: {FIELD_BG};
    border-color: {BORDER_HOVER};
}}
QToolButton#workbookAction[danger="true"] {{
    font-size: 16px;
}}
QToolButton#workbookAction[danger="true"]:hover {{
    color: #f87171;
    border-color: #7f1d1d;
}}
QLabel#dropHint {{
    font-size: 12px;
}}
QLabel#dropTitle {{
    font-size: 15px;
    font-weight: 600;
}}
QLabel#workbookTitle {{
    font-size: 15px;
    font-weight: 600;
}}
QLabel#workbookPath {{
    font-size: 12px;
}}
QFrame#workbookBanner {{
    background: #3a2c10;
    border: 1px solid #6b4f12;
    border-radius: 6px;
}}
QFrame#workbookBanner QLabel {{
    color: #fde68a;
}}
/* -- segmented toggle (e.g. Preview as Testing | Production) -- */
QPushButton[segment="true"][segmentPos="first"] {{
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
}}
QPushButton[segment="true"][segmentPos="last"] {{
    border-top-left-radius: 0;
    border-bottom-left-radius: 0;
    border-left: none;
}}
QSplitter::handle {{
    background: transparent;
}}
QSplitter::handle:hover {{
    background: {CARD_BG};
}}
QLabel#previewError {{
    background: #3b1a1a;
    color: #fca5a5;
    border: 1px solid #7f1d1d;
    border-radius: 6px;
    padding: 6px 10px;
}}
/* -- placeholder picker (ui/placeholder_picker.py) -- */
QListWidget#placeholderList {{
    padding: 4px;
    outline: none;
}}
QListWidget#placeholderList::item {{
    border-radius: 6px;
    padding: 0;
}}
QListWidget#placeholderList::item:selected {{
    background: #22324a;
}}
QLabel#placeholderGroup {{
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 700;
    padding: 10px 10px 2px 10px;
}}
QLabel#placeholderName {{
    font-weight: 600;
}}
QLabel#placeholderToken {{
    font-family: Consolas, 'Cascadia Mono', monospace;
    color: #9cc3f5;
    background: #1b2638;
    border: 1px solid #2d4466;
    border-radius: 4px;
    padding: 0 6px;
}}
QLabel#placeholderAbout {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QPushButton#placeholderInsert {{
    background: transparent;
    border-color: {BORDER};
    color: {TEXT_MUTED};
    padding: 3px 12px;
    min-height: 16px;
}}
QPushButton#placeholderInsert:hover {{
    border-color: {ACCENT};
    color: {ACCENT_HOVER};
}}
/* -- feedback (ui/feedback.py) -- */
QLineEdit[invalid="true"], QComboBox[invalid="true"], QSpinBox[invalid="true"],
QPlainTextEdit[invalid="true"], QTimeEdit[invalid="true"], QListWidget[invalid="true"] {{
    border-color: {ERROR};
}}
QLabel#fieldError {{
    color: {ERROR};
    font-size: 12px;
}}
QLabel#inlineNotice {{
    font-size: 12px;
    color: {TEXT_MUTED};
}}
QLabel#inlineNotice[kind="warning"] {{
    color: #fbbf24;
}}
QLabel#inlineNotice[kind="error"] {{
    color: {ERROR};
}}
QLabel#inlineNotice[kind="success"] {{
    color: #4ade80;
}}
QFrame#toast {{
    background: #262b36;
    border: 1px solid #424a5a;
    border-radius: 8px;
}}
QLabel#toastText {{
    color: {TEXT};
}}
QPushButton#toastAction {{
    background: transparent;
    border: 1px solid #424a5a;
    color: {ACCENT_HOVER};
    font-weight: 600;
    padding: 3px 10px;
    min-height: 16px;
}}
QPushButton#toastAction:hover {{
    border-color: {ACCENT};
}}
QToolButton#toastClose {{
    background: transparent;
    border: none;
    color: {TEXT_MUTED};
    font-size: 15px;
    padding: 0 4px;
}}
QToolButton#toastClose:hover {{
    color: {TEXT};
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


def status_edge(status: str | None) -> str:
    """Map a job's last run status to a card edge colour key."""
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


def stage_badge(stage: str, *, muted: bool = False) -> QLabel:
    """Lifecycle pill: amber Testing (emails testers) / green Production (emails the client).

    ``muted`` greys it out on a paused job's card, so the whole card reads as asleep.
    """
    live = stage == "live"
    fg, bg = ("#4ade80", "#14331f") if live else ("#fbbf24", "#3a2c10")
    if muted:
        fg, bg = TEXT_MUTED, "#2b2f3a"
    label = QLabel(stage_label(stage))
    label.setObjectName("jobStage")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setFixedWidth(96)
    label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    label.setToolTip(
        "Runs email the Production recipients."
        if live
        else "Runs email only the Test recipients until you click Move to production."
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
