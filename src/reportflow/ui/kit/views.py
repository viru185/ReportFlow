"""Scrolling containers and item views: smooth wheel scrolling, no sideways scrolling.

- :func:`smooth_scroll` animates each mouse-wheel step (about 160 ms, easing out) instead of
  jumping three lines at a time. Touchpads already send smooth pixel deltas, so those pass
  through untouched, and a view at its end lets the wheel scroll the page around it.
- :class:`ScrollArea` is a page that only ever scrolls vertically: a form wider than the
  window is a layout bug to fix, not something to scroll sideways to.
- :class:`ListWidget` / :class:`TableWidget` scroll by pixel and keep their selection clear of
  the rounded frame (the QSS gives them inner padding; see ``style.py``).
- :class:`PopupItemDelegate` draws the rows of every dropdown list the same way.
- :class:`PopupList` is a dropdown list that is itself the popup window (a QCompleter's):
  it paints its own rounded panel, because a translucent top-level scroll area paints no
  stylesheet background or border at all.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRect,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QFrame,
    QListView,
    QListWidget,
    QScrollArea,
    QScrollBar,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QWidget,
)

from reportflow.ui.style import ACCENT, BORDER_HOVER, CARD_BG, SELECTED_BG, TEXT, TEXT_MUTED

_SMOOTH_MS = 160


class _SmoothWheel(QObject):
    """Animates wheel scrolling of one scroll area (installed on its viewport)."""

    def __init__(self, area: QAbstractScrollArea) -> None:
        super().__init__(area)
        self._area = area
        self._anims: dict[Qt.Orientation, QVariantAnimation] = {}
        self._targets: dict[Qt.Orientation, float] = {}
        viewport = area.viewport()
        if viewport is not None:
            viewport.installEventFilter(self)

    def _bar(self, orientation: Qt.Orientation) -> QScrollBar | None:
        if orientation == Qt.Orientation.Horizontal:
            return self._area.horizontalScrollBar()
        return self._area.verticalScrollBar()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.Wheel:
            return False
        assert isinstance(event, QWheelEvent)
        if not event.pixelDelta().isNull():
            return False  # a touchpad: already smooth
        delta = event.angleDelta()
        horizontal = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier) or (
            delta.x() != 0 and delta.y() == 0
        )
        orientation = Qt.Orientation.Horizontal if horizontal else Qt.Orientation.Vertical
        notches = (delta.x() or delta.y()) / 120.0 if horizontal else delta.y() / 120.0
        bar = self._bar(orientation)
        if bar is None or not notches or bar.maximum() <= bar.minimum():
            return False
        if bar.singleStep() < 4:
            return False  # a view that scrolls by line or item: Qt's own stepping fits it
        anim = self._anims.get(orientation)
        running = anim is not None and anim.state() == QVariantAnimation.State.Running
        start = self._targets.get(orientation, bar.value()) if running else bar.value()
        step = min(
            float(bar.singleStep() * QApplication.wheelScrollLines()),
            max(bar.pageStep() * 0.8, 16.0),
        )
        target = max(bar.minimum(), min(bar.maximum(), start - notches * step))
        if target == bar.value() and not running:
            return False  # at the end: let the page around this view scroll instead
        self._targets[orientation] = target
        if anim is None:
            anim = QVariantAnimation(self)
            anim.setDuration(_SMOOTH_MS)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.valueChanged.connect(lambda v, b=bar: b.setValue(round(float(v))))
            self._anims[orientation] = anim
        anim.stop()
        anim.setStartValue(float(bar.value()))
        anim.setEndValue(float(target))
        anim.start()
        event.accept()
        return True


def smooth_scroll(area: QAbstractScrollArea) -> None:
    """Give ``area`` smooth wheel scrolling (idempotent)."""
    if area.property("_rf_smooth"):
        return
    area.setProperty("_rf_smooth", True)
    if isinstance(area, QAbstractItemView):
        area.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        area.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    _SmoothWheel(area)


class ScrollArea(QScrollArea):
    """A frameless page that scrolls vertically only and resizes its content to fit."""

    def __init__(self, content: QWidget | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        smooth_scroll(self)
        if content is not None:
            self.setWidget(content)

    def setWidget(self, widget: QWidget) -> None:  # noqa: N802
        super().setWidget(widget)
        # QScrollArea.setWidget turns the page's autoFillBackground ON. That square fill
        # painted over the rounded corners of the frame around the page — the tab panel's
        # corner arcs went missing (owner's screenshots, 0.14). The page shows what is
        # behind it instead; the frame already paints the same background.
        widget.setAutoFillBackground(False)


class ListWidget(QListWidget):
    """A list with pixel scrolling, no sideways scrolling and no dotted focus rectangle."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        smooth_scroll(self)


class TableWidget(QTableWidget):
    """A table with pixel scrolling and a flat header (the QSS gives it no fill)."""

    def __init__(self, rows: int = 0, columns: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(rows, columns, parent)
        self.setShowGrid(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        smooth_scroll(self)


class PopupItemDelegate(QStyledItemDelegate):
    """Rows of a dropdown list: 30 px, rounded, a hover tint, and the selected row tinted with
    a small accent pill on its left (the Windows 11 / Fluent list look)."""

    ROW_HEIGHT = 30

    def sizeHint(  # noqa: N802
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        hint = super().sizeHint(option, index)
        return QSize(hint.width() + 16, max(hint.height(), self.ROW_HEIGHT))

    def is_highlighted(self, option: Any, index: QModelIndex | QPersistentModelIndex) -> bool:
        return bool(option.state & QStyle.StateFlag.State_Selected)

    def paint(
        self, painter: QPainter, option: Any, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(opt.rect).adjusted(2, 1, -2, -1)
        selected = self.is_highlighted(opt, index)
        hovered = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        enabled = bool(opt.state & QStyle.StateFlag.State_Enabled)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(SELECTED_BG))
            painter.drawRoundedRect(rect, 6, 6)
            pill = QRectF(rect.left() + 1, rect.center().y() - 7, 3, 14)
            painter.setBrush(QColor(ACCENT))
            painter.drawRoundedRect(pill, 1.5, 1.5)
        elif hovered and enabled:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 14))
            painter.drawRoundedRect(rect, 6, 6)
        x = int(rect.left()) + 12
        if not opt.icon.isNull():
            size = 16
            icon_rect = QRect(x, int(rect.center().y()) - size // 2, size, size)
            opt.icon.paint(painter, icon_rect)
            x += size + 8
        text_rect = QRect(x, int(rect.top()), int(rect.right()) - x - 8, int(rect.height()))
        self.paint_text(painter, opt, index, text_rect, enabled)
        painter.restore()

    def paint_text(
        self,
        painter: QPainter,
        opt: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
        rect: QRect,
        enabled: bool,
    ) -> None:
        painter.setPen(QColor(TEXT if enabled else TEXT_MUTED))
        painter.setFont(opt.font)
        shown = opt.fontMetrics.elidedText(opt.text, Qt.TextElideMode.ElideMiddle, rect.width())
        painter.drawText(
            rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), shown
        )


class PopupList(QListView):
    """The list a QCompleter pops up, drawn as the app's rounded dropdown panel.

    The popup window is translucent (``kit.popups.round_popup``) so its corners can be
    see-through; this class paints the panel — background and border — itself."""

    RADIUS = 8
    # QCompleter sizes its popup as rows + 6 px, so 3 px top and bottom fit it exactly.
    PAD_X, PAD_Y = 4, 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("completerPopup")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setViewportMargins(self.PAD_X, self.PAD_Y, self.PAD_X, self.PAD_Y)
        viewport = self.viewport()
        if viewport is not None:
            viewport.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setItemDelegate(PopupItemDelegate(self))

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Paint:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(BORDER_HOVER), 1.0))
            painter.setBrush(QColor(CARD_BG))
            painter.drawRoundedRect(
                QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self.RADIUS, self.RADIUS
            )
            painter.end()
        return super().event(event)
