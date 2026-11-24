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
from reportflow.core.ipc.contract import FAILURE_STATUSES


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
# Tones: bright text on a deep tinted surface (pills, banners, tags).
SUCCESS = "#4ade80"
SUCCESS_BG = "#14331f"
WARNING = "#fbbf24"
WARNING_BG = "#3a2c10"
WARNING_BORDER = "#6b4f12"
DANGER = "#f87171"
DANGER_BG = "#3b1a1a"
DANGER_BORDER = "#7f1d1d"
INFO = "#9cc3f5"
INFO_BG = "#172c48"
INFO_BORDER = "#355d8c"
NEUTRAL = "#c3c8d4"
NEUTRAL_BG = "#2b2f3a"
SELECTED_BG = "#1f3350"  # a selected row in any list
RAISED_BG = "#262b36"  # toasts and popovers float above cards

STATUS_COLORS: dict[str, tuple[str, str]] = {
    # status -> (foreground, background) — bright text on a deep tinted pill
    "success": (SUCCESS, SUCCESS_BG),
    "failed": (DANGER, DANGER_BG),
    "timed_out": (DANGER, DANGER_BG),
    "crashed": (DANGER, DANGER_BG),
    "running": (WARNING, WARNING_BG),
    "interrupted": (DANGER, DANGER_BG),
    "stopped": (NEUTRAL, NEUTRAL_BG),  # a user stopped it: not a failure
    "never": (NEUTRAL, NEUTRAL_BG),
}
# status -> the tone its pill uses (QLabel[badge="…"] in the QSS)
_STATUS_TONES = {
    "success": "success",
    "failed": "danger",
    "timed_out": "danger",
    "crashed": "danger",
    "running": "warning",
    "interrupted": "danger",
    "stopped": "neutral",
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
    background: {INFO_BG};
    border: 1px solid {INFO_BORDER};
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 14px;
    font-weight: 600;
}}
QLabel#scheduleOverview[state="warning"] {{
    background: {WARNING_BG};
    border-color: {WARNING_BORDER};
    color: {WARNING};
}}
QFrame[timePill="true"] {{
    background: #172c48;
    border: 1px solid #507eaf;
    border-radius: 13px;
}}
QFrame[timePill="true"][flash="true"] {{
    background: #1d4170;
    border-color: {ACCENT_HOVER};
}}
QLabel#timePillText {{
    color: #dbeafe;
    font-weight: 600;
}}
QLabel#timePopoverTitle, QLabel[popoverTitle="true"] {{
    font-weight: 600;
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
QFrame[recipientChip="true"][selected="true"] {{
    background: {ACCENT};
    border-color: {ACCENT_HOVER};
}}
QFrame[recipientChip="true"][selected="true"] QLabel#chipText {{
    color: #ffffff;
}}
QFrame[recipientChip="true"][selected="true"] QToolButton#chipRemove {{
    color: #dbeafe;
}}
QFrame[recipientField="true"][dropTarget="true"] {{
    border-color: {ACCENT};
}}
QFrame#chipDropCaret {{
    background: {ACCENT_HOVER};
    border: none;
    border-radius: 1px;
}}
QFrame[recipientField="true"] QLineEdit[chipEditor="true"] {{
    background: #2a303c;
    color: {TEXT};
    border: 1px solid {ACCENT};
    border-radius: 12px;
    padding: 0 9px;
    min-height: 22px;  /* + border = the chip's 24 px (text boxes are 24 + border elsewhere) */
    selection-background-color: {ACCENT};
}}
QFrame[recipientField="true"] QLineEdit[chipEditor="true"][invalid="true"] {{
    border-color: {ERROR};
}}
QFrame[recipientChip="true"] QLabel#chipText {{
    color: {TEXT};
}}
QFrame[groupChip="true"] QLabel#chipText {{
    color: #dbeafe;
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
/* -- button variants (ui/kit/buttons.py) -- */
QPushButton[variant="primary"] {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
    color: #ffffff;
}}
QPushButton[variant="primary"]:pressed {{
    background: #2563eb;
}}
QPushButton[variant="primary"]:disabled {{
    background: {CARD_BG};
    border-color: {BORDER};
    color: {TEXT_MUTED};
}}
QPushButton[variant="quiet"], QPushButton[variant="quiet-danger"] {{
    background: transparent;
    border-color: transparent;
    color: {TEXT_MUTED};
}}
QPushButton[variant="quiet"]:hover {{
    background: {FIELD_BG};
    color: {TEXT};
}}
QPushButton[variant="quiet-danger"]:hover, QPushButton[variant="danger"]:hover {{
    background: {DANGER_BG};
    border-color: {DANGER_BORDER};
    color: {DANGER};
}}
QPushButton[variant="dashed"] {{
    background: transparent;
    border: 1px dashed {BORDER_HOVER};
    color: {ACCENT_HOVER};
}}
QPushButton[variant="dashed"]:hover {{
    border-color: {ACCENT};
    background: rgba(59, 130, 246, 0.08);
}}
QPushButton[small="true"] {{
    padding: 3px 10px;
    min-height: 16px;
}}
QPushButton[pill="true"] {{
    border-radius: 13px;
    padding: 2px 12px;
    min-height: 20px;
}}
QToolButton[variant="icon"], QToolButton[variant="icon-danger"] {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 0;
    color: {TEXT_MUTED};
}}
QToolButton[variant="icon"]:hover, QToolButton[variant="icon-danger"]:hover {{
    background: {FIELD_BG};
    border-color: {BORDER_HOVER};
    color: {TEXT};
}}
QToolButton[variant="icon-danger"]:hover {{
    background: {DANGER_BG};
    border-color: {DANGER_BORDER};
    color: {DANGER};
}}
QToolButton[variant="icon"]:disabled {{
    color: {BORDER_HOVER};
}}
QToolButton[variant="close"], QToolButton[variant="dismiss"] {{
    background: transparent;
    border: none;
    border-radius: 9px;
    color: {TEXT_MUTED};
    font-size: 14px;
    padding: 0;
}}
QToolButton[variant="close"]:hover {{
    background: #3b2326;
    color: {DANGER};
}}
QToolButton[variant="dismiss"]:hover {{
    background: rgba(255, 255, 255, 0.08);
    color: {TEXT};
}}
QToolButton[variant="tool"] {{
    padding: 6px 10px;
    min-height: 20px;
    min-width: 16px;
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
/* Dropdown lists drop BELOW the field (not over it) in a rounded panel; the rows are drawn
   by kit.views.PopupItemDelegate. The popup window is translucent (kit.popups.round_popup),
   so the radius here is the real shape. */
QComboBox {{
    combobox-popup: 0;
}}
QFrame#popupContainer {{
    background: transparent;
    border: none;
}}
QListView#popupList {{
    background: {CARD_BG};
    color: {TEXT};
    border: 1px solid {BORDER_HOVER};
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}
/* A completer's list is itself the popup window and paints its own panel (kit.PopupList). */
QListView#completerPopup {{
    background: transparent;
    border: none;
    padding: 0;
    outline: none;
}}
/* -- lists and tables: inner padding keeps a selected row clear of the rounded frame -- */
QListWidget {{
    padding: 4px;
    outline: none;
}}
QListWidget::item {{
    color: {TEXT};
    padding: 4px 6px;
    border-radius: 6px;
}}
QListWidget::item:hover {{
    background: rgba(255, 255, 255, 0.04);
}}
QListWidget::item:selected {{
    background: {SELECTED_BG};
    color: {TEXT};
}}
QTableWidget {{
    gridline-color: {BORDER};
    padding: 4px;
    outline: none;
}}
QTableWidget::item {{
    color: {TEXT};
}}
QTableWidget::item:selected {{
    background: {SELECTED_BG};
    color: {TEXT};
}}
QTableWidget::item:disabled {{
    color: {TEXT_MUTED};
}}
QHeaderView {{
    background: transparent;
}}
QHeaderView::section {{
    background: transparent;
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px 8px;
    font-weight: 600;
}}
QTableCornerButton::section {{
    background: transparent;
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
/* The selected tab is the page's own colour and covers the panel's top line, so it reads
   as part of the page; the panel's top-left corner is square because the first tab sits
   right on it (a rounded one poked out under the tab). */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    border-top-left-radius: 0;
    background: {BG};
    top: -1px;
}}
QTabBar::tab {{
    background: {CARD_BG};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 5px 16px;
    margin-right: 2px;
}}
QTabBar::tab:hover:!selected {{
    color: {TEXT};
}}
QTabBar::tab:selected {{
    background: {BG};
    color: {TEXT};
    border-bottom-color: {BG};
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
/* Menus and tooltips are translucent windows (kit.popups.round_popup / kit.chrome), so
   these radii are their real shape. */
QMenu {{
    background: {CARD_BG};
    color: {TEXT};
    border: 1px solid {BORDER_HOVER};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 28px 6px 12px;
    border-radius: 6px;
    background: transparent;
}}
QMenu::item:selected {{
    background: {SELECTED_BG};
    color: {TEXT};
}}
QMenu::item:disabled {{
    color: {TEXT_MUTED};
}}
QMenu::icon {{
    padding-left: 8px;
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 8px;
}}
QStatusBar {{
    background: {CARD_BG};
    border-top: 1px solid {BORDER};
    color: {TEXT_MUTED};
}}
QToolTip {{
    background: {RAISED_BG};
    color: {TEXT};
    border: 1px solid {BORDER_HOVER};
    border-radius: 6px;
    padding: 6px 10px;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
/* Slim, minimal scrollbars: no track, no arrows, a thin rounded thumb that brightens under
   the pointer and turns accent while dragged. */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 0.16);
    border-radius: 3px;
    min-height: 32px;
    margin: 0 2px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(255, 255, 255, 0.16);
    border-radius: 3px;
    min-width: 32px;
    margin: 2px 0;
}}
QScrollBar::handle:hover {{
    background: rgba(255, 255, 255, 0.32);
}}
QScrollBar::handle:pressed {{
    background: rgba(96, 165, 250, 0.7);
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
    border: none;
    background: none;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}
QAbstractScrollArea::corner {{
    background: transparent;
    border: none;
}}
QFrame[card="true"] {{
    background: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame[card="true"][invalid="true"] {{
    border-color: {ERROR};
}}
QFrame[card="true"]:focus {{
    border-color: {ACCENT_HOVER};
}}
QFrame[card="true"][flash="true"] {{
    background: #1d2a3d;
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
/* -- popovers (kit.popups.Popover): a translucent window around a rounded panel -- */
QFrame[popover="true"] {{
    background: transparent;
    border: none;
}}
QFrame[popoverPanel="true"] {{
    background: {CARD_BG};
    border: 1px solid {BORDER_HOVER};
    border-radius: 10px;
}}
/* -- pills: status / stage badges and small tags (kit.labels.Tag) -- */
QLabel[badge], QLabel[tag] {{
    border-radius: 8px;
    padding: 2px 10px;
    font-weight: 600;
}}
QLabel[tag] {{
    border-radius: 7px;
    padding: 1px 8px;
    font-size: 11px;
}}
QLabel[badge="success"], QLabel[tag="success"] {{
    color: {SUCCESS};
    background: {SUCCESS_BG};
}}
QLabel[badge="warning"], QLabel[tag="warning"] {{
    color: {WARNING};
    background: {WARNING_BG};
}}
QLabel[badge="danger"], QLabel[tag="danger"] {{
    color: {DANGER};
    background: {DANGER_BG};
}}
QLabel[badge="info"], QLabel[tag="info"] {{
    color: {INFO};
    background: {INFO_BG};
}}
QLabel[badge="neutral"], QLabel[tag="neutral"] {{
    color: {NEUTRAL};
    background: {NEUTRAL_BG};
}}
QLabel[badge="muted"] {{
    color: {TEXT_MUTED};
    background: {NEUTRAL_BG};
}}
/* -- text tones and sizes for plain labels -- */
QLabel[tone="success"] {{
    color: {SUCCESS};
}}
QLabel[tone="warning"] {{
    color: {WARNING};
}}
QLabel[tone="danger"] {{
    color: {ERROR};
}}
QLabel[size="title"] {{
    font-size: 15px;
    font-weight: 700;
}}
QLabel[size="stat"] {{
    font-size: 14px;
    font-weight: 700;
}}
QLabel[size="small"] {{
    font-size: 12px;
}}
QLabel[size="tiny"] {{
    font-size: 11px;
}}
/* -- banners: a tinted strip with a message (and maybe a button) -- */
QFrame[banner="danger"] {{
    background: {DANGER_BG};
    border: 1px solid {DANGER_BORDER};
    border-radius: 6px;
}}
QFrame[banner="warning"] {{
    background: {WARNING_BG};
    border: 1px solid {WARNING_BORDER};
    border-radius: 6px;
}}
QFrame[banner="danger"] QLabel {{
    color: #fecaca;
}}
QFrame[banner="warning"] QLabel {{
    color: #fde68a;
}}
QLabel[banner="danger"] {{
    background: {DANGER_BG};
    color: #fca5a5;
    border: 1px solid {DANGER_BORDER};
    border-radius: 6px;
    padding: 6px 10px;
}}
/* -- workbook list (ui/windows/workbook_panel.py) -- */
QListWidget#workbookItems::item {{
    margin: 1px 0;
    padding: 0;
}}
QListWidget#workbookItems::item:hover {{
    background: transparent;
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
    color: {WARNING};
}}
QLabel#workbookStatus[kind="busy"] {{
    color: {ACCENT_HOVER};
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
/* -- segmented toggle (e.g. Preview as Testing | Production) -- */
QPushButton[segment="true"][segmentPos="first"] {{
    border-top-right-radius: 0;
    border-bottom-right-radius: 0;
}}
QPushButton[segment="true"][segmentPos="mid"] {{
    border-radius: 0;
    border-left: none;
}}
/* Two selected neighbours keep a thin divider, so "Tue" and "Wed" stay two days. */
QPushButton[segment="true"][segmentPos="mid"]:checked,
QPushButton[segment="true"][segmentPos="last"]:checked {{
    border-left: 1px solid rgba(255, 255, 255, 0.28);
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
/* Emails are designed on white: the template preview is a deliberate light island. */
QTextBrowser#emailPreview {{
    background: #ffffff;
    color: #1a1a1a;
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 8px;
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
    color: {WARNING};
}}
QLabel#inlineNotice[kind="error"] {{
    color: {ERROR};
}}
QLabel#inlineNotice[kind="success"] {{
    color: {SUCCESS};
}}
QFrame#toast {{
    background: {RAISED_BG};
    border: 1px solid #424a5a;
    border-radius: 8px;
}}
QLabel#toastText {{
    color: {TEXT};
}}
QLabel#toastIcon {{
    border-radius: 10px;
    color: #10131a;
    font-weight: 700;
}}
QLabel#toastIcon[kind="success"] {{
    background: {SUCCESS};
}}
QLabel#toastIcon[kind="info"] {{
    background: {ACCENT_HOVER};
}}
QLabel#toastIcon[kind="warning"] {{
    background: {WARNING};
}}
QLabel#toastIcon[kind="error"] {{
    background: {DANGER};
}}
QFrame#toast QPushButton {{
    color: {ACCENT_HOVER};
    font-weight: 600;
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
    # Round the menus and tooltips Qt makes itself, and smooth every scroll area.
    from reportflow.ui.kit.chrome import install_chrome

    install_chrome(app)


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
    if s in FAILURE_STATUSES:
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
    label = QLabel(text)
    label.setProperty("badge", _STATUS_TONES.get((status or "").lower(), "neutral"))
    return label


def stage_badge(stage: str, *, muted: bool = False) -> QLabel:
    """Lifecycle pill: amber Testing (emails testers) / green Production (emails the client).

    ``muted`` greys it out on a paused job's card, so the whole card reads as asleep.
    """
    live = stage == "live"
    label = QLabel(stage_label(stage))
    # A property, not an inline stylesheet: an inline one also restyles the pill's tooltip
    # (it used to show amber text on a square brown box).
    label.setProperty("badge", "muted" if muted else "success" if live else "warning")
    label.setObjectName("jobStage")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setFixedWidth(96)
    label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    label.setToolTip(
        "Runs email the Production recipients."
        if live
        else "Runs email only the Test recipients until you click Move to production."
    )
    return label


def connection_pill(connected: bool) -> str:
    """Rich-text for the header connection indicator."""
    if connected:
        return f'<span style="color:{SUCCESS};">●</span> Connected'
    return f'<span style="color:{DANGER};">●</span> Service not reachable'
