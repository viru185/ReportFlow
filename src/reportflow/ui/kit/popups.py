"""Floating surfaces: rounded menus and popovers.

A top-level window on Windows is a rectangle; to show a rounded menu, tooltip or popup the
window must be frameless and translucent, so the QSS ``border-radius`` decides the shape and
the corners stay see-through. :func:`round_popup` does that for any popup *before* it is
first shown (Qt can't change it afterwards). ``kit.chrome`` applies it to popups Qt creates
itself (tooltips, text-field context menus).

:class:`Popover` is the small floating panel the app uses instead of extra dialogs (insert a
placeholder, add a time, send a test email): it opens under the button that asked for it,
closes on Esc or a click anywhere else, and gives the keyboard back to that button.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QFrame, QMenu, QVBoxLayout, QWidget


def round_popup(widget: QWidget) -> None:
    """Make a popup window frameless and translucent so its QSS radius shows (idempotent).

    Must run before the window is first shown — the native window is created then."""
    if widget.property("_rf_rounded"):
        return
    widget.setProperty("_rf_rounded", True)
    widget.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    widget.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)


class Menu(QMenu):
    """A context or drop-down menu with rounded corners (styled in ``style.py``)."""

    def __init__(self, parent: QWidget | None = None, title: str = "") -> None:
        super().__init__(title, parent)
        round_popup(self)
        self.setToolTipsVisible(True)


class Popover(QFrame):
    """A rounded floating panel anchored to a widget; Esc or a click outside closes it.

    Put content in :attr:`body` (a QVBoxLayout). ``closed`` fires whenever it hides."""

    closed = Signal()

    def __init__(self, parent: QWidget | None = None, *, name: str = "popover") -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName(name)
        self.setProperty("popover", True)
        round_popup(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.panel = QFrame()
        self.panel.setProperty("popoverPanel", True)
        outer.addWidget(self.panel)
        self.body = QVBoxLayout(self.panel)
        self.body.setContentsMargins(14, 12, 14, 12)
        self.body.setSpacing(10)
        self._anchor: QWidget | None = None
        self._return_focus: QWidget | None = None

    def open_at(
        self, anchor: QWidget, *, focus: QWidget | None = None, align: str = "left"
    ) -> None:
        """Show under ``anchor`` (above it when there's no room), inside the screen.
        ``align="right"`` lines its right edge up with the anchor's (for buttons on the right
        of a form, so the popover opens towards the form instead of off its edge)."""
        self._anchor = anchor
        if self._return_focus is None:
            self._return_focus = anchor
        self.adjustSize()
        self.move(self._position(anchor, align))
        self.show()
        self.raise_()
        self.activateWindow()
        if focus is not None:
            focus.setFocus(Qt.FocusReason.PopupFocusReason)

    def _position(self, anchor: QWidget, align: str = "left") -> QPoint:
        size = self.size().expandedTo(self.minimumSize())
        x0 = anchor.width() - size.width() if align == "right" else 0
        below = anchor.mapToGlobal(QPoint(x0, anchor.height() + 6))
        above = anchor.mapToGlobal(QPoint(x0, -size.height() - 6))
        screen = QGuiApplication.screenAt(below) or anchor.screen()
        area: QRect = screen.availableGeometry() if screen else QRect(0, 0, 10_000, 10_000)
        point = below if below.y() + size.height() <= area.bottom() else above
        x = min(max(point.x(), area.left() + 4), area.right() - size.width() - 4)
        y = min(max(point.y(), area.top() + 4), area.bottom() - size.height() - 4)
        return QPoint(x, y)

    def set_return_focus(self, widget: QWidget | None) -> None:
        """Where the keyboard goes when the popover closes (default: its anchor)."""
        self._return_focus = widget

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def hideEvent(self, event: QEvent) -> None:  # type: ignore[override]  # noqa: N802
        super().hideEvent(event)  # type: ignore[arg-type]
        target = self._return_focus
        if target is not None and target.isVisible():
            target.setFocus(Qt.FocusReason.PopupFocusReason)
        self.closed.emit()
