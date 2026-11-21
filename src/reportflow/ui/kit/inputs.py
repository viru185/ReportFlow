"""Inputs that pick a value: dropdowns, number and time fields.

Shared behaviour:

- **The wheel never changes a value by accident.** Scrolling a form with the mouse wheel used
  to change whichever dropdown or number field passed under the pointer. These fields only
  take the wheel once they have focus (clicked or tabbed into); otherwise the page scrolls.
- **Dropdown lists** open *below* the field in a rounded panel, rows drawn by
  :class:`~reportflow.ui.kit.views.PopupItemDelegate`, scrolling smoothly.
- A long item never makes a form wider: the closed field sizes to a few characters and
  elides; the open list is as wide as its longest item.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTime
from PySide6.QtGui import QPaintEvent, QWheelEvent
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QListView,
    QSpinBox,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
    QTimeEdit,
    QWidget,
)

from reportflow.ui.kit.popups import round_popup
from reportflow.ui.kit.views import PopupItemDelegate, PopupList, smooth_scroll

_POPUP_GAP = 4


class ComboBox(QComboBox):
    """A dropdown with the app's rounded list; wheel only when focused."""

    def __init__(self, parent: QWidget | None = None, *, min_chars: int = 10) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(min_chars)
        view = QListView()
        view.setObjectName("popupList")
        view.setMouseTracking(True)
        view.setUniformItemSizes(True)
        view.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        view.setItemDelegate(PopupItemDelegate(view))
        self.setView(view)
        smooth_scroll(view)
        container = view.window()
        if container is not None and container is not self.window():
            container.setObjectName("popupContainer")
            round_popup(container)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if not self.hasFocus():
            event.ignore()  # the page under it scrolls instead
            return
        super().wheelEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        """Like Qt's, but a long choice is shortened in the middle ("Aditya_PI…Oct.xlsx")
        instead of being cut off at the field's edge."""
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        field = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            self,
        )
        option.currentText = self.fontMetrics().elidedText(
            option.currentText, Qt.TextElideMode.ElideMiddle, max(field.width() - 4, 0)
        )
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)

    def showPopup(self) -> None:  # noqa: N802
        view = self.view()
        if view is not None:
            view.setMinimumWidth(max(self.width(), view.sizeHintForColumn(0) + 24))
        super().showPopup()
        container = view.window() if view is not None else None
        if container is None or container is self.window():
            return
        below = self.mapToGlobal(QPoint(0, self.height() + _POPUP_GAP))
        screen = self.screen().availableGeometry()
        if below.y() + container.height() <= screen.bottom():
            container.move(below.x(), below.y())
        else:  # no room under it: open above
            top = self.mapToGlobal(QPoint(0, 0)).y() - container.height() - _POPUP_GAP
            container.move(below.x(), top)


def styled_completer(completer: QCompleter, *, min_width: int = 0) -> PopupList:
    """Give a QCompleter the app's dropdown list (rounded, smooth, same rows)."""
    popup = completer.popup()
    if not isinstance(popup, PopupList):
        popup = PopupList()
        completer.setPopup(popup)  # the completer takes ownership and makes it a popup
        # setPopup installs Qt's own row delegate; put the app's rows back.
        popup.setItemDelegate(PopupItemDelegate(popup))
    completer.setMaxVisibleItems(8)
    if min_width:
        popup.setMinimumWidth(min_width)
    round_popup(popup)
    smooth_scroll(popup)
    return popup


class SpinBox(QSpinBox):
    """A number field; wheel only when focused."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)


class TimeEdit(QTimeEdit):
    """A 24-hour HH:mm time field; wheel only when focused."""

    def __init__(self, time: QTime | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if time is not None:
            self.setTime(time)
        self.setDisplayFormat("HH:mm")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)
