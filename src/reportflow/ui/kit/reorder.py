"""Drag to reorder a vertical list of rows: a job's workbooks, a job's schedules, the
dashboard's job cards (0.15).

The established pattern (Notion, Linear, Trello's lists): every row gets a grip (⠿) in its
left margin, shown while the row is hovered or holds the keyboard. The grip sits over the
margin, so nothing in the row moves, and clicks, double-clicks and a card's buttons behave
as before. Dragging the grip lifts the row — it stays in place, faded — and an accent line
with a dot at its start shows where it will land; near the top or bottom of a scrolling list,
the list scrolls. **Alt+↑ / Alt+↓** move the row that has the keyboard.

The host owns the order: :class:`Reorder` only reports ``moved(from, to)`` (``to`` is the
row's final index) and the host rebuilds or reorders its rows.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import (
    QByteArray,
    QEvent,
    QMimeData,
    QObject,
    QPoint,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDrag,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QGraphicsOpacityEffect,
    QWidget,
)

from reportflow.ui.style import ACCENT_HOVER, TEXT, TEXT_MUTED

ROW_MIME = "application/x-reportflow-row"
_EDGE = 32  # px from a scrolling list's top/bottom where a drag scrolls it


class DragHandle(QWidget):
    """The ⠿ grip in a row's left margin. Painted only while :attr:`shown`; it keeps its
    place either way, so showing it never moves anything."""

    WIDTH = 12
    HEIGHT = 22

    def __init__(self, reorder: Reorder, row: QWidget, tooltip: str) -> None:
        super().__init__(row)
        self._reorder = reorder
        self._row = row
        self.shown = False
        self._hover = False
        self._press: QPoint | None = None
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(tooltip)
        self.setAccessibleName("Drag to reorder")

    def set_shown(self, shown: bool) -> None:
        if shown != self.shown:
            self.shown = shown
            self.update()

    def enterEvent(self, event: QEvent) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        start = self._press
        if start is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        if (event.position().toPoint() - start).manhattanLength() >= (
            QApplication.startDragDistance()
        ):
            self._press = None
            self._reorder.start_drag(self._row, self.mapTo(self._row, start))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._press = None
        super().mouseReleaseEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        if not self.shown:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 18))
            painter.drawRoundedRect(QRectF(self.rect()), 4, 4)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(TEXT if self._hover else TEXT_MUTED))
        dot, gap = 2.6, 2.8
        width, height = 2 * dot + gap, 3 * dot + 2 * gap
        x0 = (self.width() - width) / 2
        y0 = (self.height() - height) / 2
        for col in range(2):
            for line in range(3):
                painter.drawEllipse(
                    QRectF(x0 + col * (dot + gap), y0 + line * (dot + gap), dot, dot)
                )
        painter.end()


class _DropLine(QWidget):
    """Where the dragged row will land: an accent line with a ring at its start."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setObjectName("rowDropLine")
        self.hide()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(ACCENT_HOVER)
        mid = self.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(6, mid - 1, self.width() - 6, 2), 1, 1)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = painter.pen()
        pen.setStyle(Qt.PenStyle.SolidLine)
        pen.setColor(color)
        pen.setWidthF(2)
        painter.setPen(pen)
        painter.drawEllipse(QRectF(1, mid - 3, 6, 6))
        painter.end()


class Reorder(QObject):
    """Drag-to-reorder for the rows ``rows()`` returns (top to bottom), all inside
    ``container``, which receives the drops. ``scroll``: the area to scroll near its edges.
    ``active(row)``: also show the grip when this is true (e.g. the selected row)."""

    moved = Signal(int, int)

    def __init__(
        self,
        container: QWidget,
        rows: Callable[[], Sequence[QWidget]],
        *,
        scroll: QAbstractScrollArea | None = None,
        active: Callable[[QWidget], bool] | None = None,
    ) -> None:
        super().__init__(container)
        self._container = container
        self._rows = rows
        self._scroll = scroll
        self._active = active
        self._line = _DropLine(container)
        self._dragging: QWidget | None = None
        self._target: int | None = None
        self._scroll_step = 0
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(30)
        self._scroll_timer.timeout.connect(self._auto_scroll)
        container.setAcceptDrops(True)
        container.installEventFilter(self)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            # A bound method: the connection ends with this object (a lambda would outlive
            # a closed editor and call into deleted rows).
            app.focusChanged.connect(self._focus_changed)

    @property
    def dragging(self) -> bool:
        """A row is being dragged — the host must not rebuild its rows meanwhile."""
        return self._dragging is not None

    def _focus_changed(self, _old: object, _new: object) -> None:
        self.refresh()

    # -- rows ------------------------------------------------------------------------

    def attach(
        self,
        row: QWidget,
        *,
        tooltip: str = "Drag to reorder · Alt+↑ / Alt+↓",
        inset: int = 1,
        centre_on: Callable[[], QRect] | None = None,
    ) -> DragHandle:
        """Give ``row`` its grip, in the left margin ``inset`` px from the edge, centred on
        the row (or on ``centre_on()``, a rect in row coordinates — e.g. its first line)."""
        handle = DragHandle(self, row, tooltip)
        row.setProperty("_rf_handle_inset", inset)
        row._rf_handle = handle  # type: ignore[attr-defined]
        row._rf_handle_centre = centre_on  # type: ignore[attr-defined]
        row.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        row.installEventFilter(self)
        self._place(row)
        handle.raise_()
        handle.show()
        self.refresh()
        return handle

    def keys(self, widget: QWidget, index: Callable[[], int]) -> None:
        """Alt+↑ / Alt+↓ on ``widget`` or anything in it move row ``index()``."""
        for sequence, step in (("Alt+Up", -1), ("Alt+Down", 1)):
            shortcut = QShortcut(QKeySequence(sequence), widget)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda s=step: self.step(index(), s))

    def step(self, index: int, step: int) -> bool:
        """Move row ``index`` one place up (-1) or down (+1); False at either end."""
        count = len(self._rows())
        if 0 <= index < count and 0 <= index + step < count:
            self._emit_moved(index, index + step)
            return True
        return False

    def _emit_moved(self, source: int, target: int) -> None:
        # After the event that asked for it has returned: the host rebuilds its rows, and a
        # row (or its shortcut) must not be deleted inside its own event handler.
        QTimer.singleShot(0, self, lambda: self.moved.emit(source, target))

    def refresh(self) -> None:
        """Show each grip while its row is hovered, holds the keyboard, or is active —
        never when there is only one row (nothing to reorder)."""
        rows = self._rows()
        focus = QApplication.focusWidget()
        for row in rows:
            handle = getattr(row, "_rf_handle", None)
            if not isinstance(handle, DragHandle):
                continue
            shown = len(rows) > 1 and (
                bool(row.property("_rf_hover"))
                or (focus is not None and (focus is row or row.isAncestorOf(focus)))
                or (self._active is not None and self._active(row))
                or row is self._dragging
            )
            handle.set_shown(shown)
            handle.setEnabled(len(rows) > 1)

    def _place(self, row: QWidget) -> None:
        handle = getattr(row, "_rf_handle", None)
        if not isinstance(handle, DragHandle):
            return
        centre = getattr(row, "_rf_handle_centre", None)
        y = centre().center().y() if centre is not None else row.height() // 2
        inset = int(row.property("_rf_handle_inset") or 0)
        handle.move(inset, max(0, y - handle.height() // 2))

    # -- dragging --------------------------------------------------------------------

    def start_drag(self, row: QWidget, hot_spot: QPoint) -> None:
        rows = self._rows()
        if row not in rows or len(rows) < 2:
            return
        source = rows.index(row)
        self._dragging, self._target = row, None
        mime = QMimeData()
        mime.setData(ROW_MIME, QByteArray(str(source).encode()))
        drag = QDrag(row)
        drag.setMimeData(mime)
        drag.setPixmap(_lifted(row.grab()))
        drag.setHotSpot(hot_spot)
        ghost = QGraphicsOpacityEffect(row)
        ghost.setOpacity(0.35)  # it stays in place, faded, until it lands
        row.setGraphicsEffect(ghost)
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            row.setGraphicsEffect(None)  # type: ignore[arg-type]
            target, self._target, self._dragging = self._target, None, None
            self._line.hide()
            self._scroll_timer.stop()
            self.refresh()
        if target is not None:
            self.land(source, target)

    def land(self, source: int, target: int) -> None:
        """A drop: row ``source`` goes to the line's place ``target`` (0 … len, in the list
        as it is now). Its own place, and the one just below it, change nothing."""
        final = target - 1 if target > source else target
        if final != source:
            self._emit_moved(source, final)

    def drop_index(self, pos: QPoint) -> int:
        """Where a row dropped at ``pos`` (container coordinates) goes: above the first
        row whose middle is below the pointer (0 … len)."""
        for i, row in enumerate(self._rows()):
            if pos.y() < self._rect(row).center().y():
                return i
        return len(self._rows())

    def _rect(self, row: QWidget) -> QRect:
        return QRect(row.mapTo(self._container, QPoint(0, 0)), row.size())

    def _show_line(self, index: int) -> None:
        rows = self._rows()
        source = rows.index(self._dragging) if self._dragging in rows else -1
        if not rows or index in (source, source + 1):
            self._line.hide()  # dropping here changes nothing
            return
        if index < len(rows):
            top = self._rect(rows[index]).top()
            above = self._rect(rows[index - 1]).bottom() if index > 0 else top - 4
            y = (above + top + 1) // 2
        else:
            y = self._rect(rows[-1]).bottom() + 3
        first = self._rect(rows[0])
        left = max(0, first.left() - 4)  # the ring at its start must not be clipped
        self._line.setGeometry(left, y - 4, first.right() + 1 - left, 8)
        self._line.raise_()
        self._line.show()

    def _scroll_area(self) -> QAbstractScrollArea | None:
        """The given scroll area, else the nearest one around the container."""
        if self._scroll is not None:
            return self._scroll
        parent = self._container.parentWidget()
        while parent is not None and not isinstance(parent, QAbstractScrollArea):
            parent = parent.parentWidget()
        return parent

    def _auto_scroll(self) -> None:
        area = self._scroll_area()
        bar = area.verticalScrollBar() if area is not None else None
        if bar is None or not self._scroll_step:
            self._scroll_timer.stop()
            return
        bar.setValue(bar.value() + self._scroll_step)
        # The pointer hasn't moved, but the rows under it have: update the line.
        pos = self._container.mapFromGlobal(QCursor.pos())
        self._target = None
        self._show_line(self.drop_index(pos))

    def _edge_scroll(self, pos: QPoint) -> None:
        area = self._scroll_area()
        if area is None:
            return
        viewport = area.viewport()
        if viewport is None:
            return
        y = self._container.mapTo(viewport, pos).y()
        if y < _EDGE:
            self._scroll_step = -max(4, (_EDGE - y) // 2)
        elif y > viewport.height() - _EDGE:
            self._scroll_step = max(4, (y - viewport.height() + _EDGE) // 2)
        else:
            self._scroll_step = 0
        if self._scroll_step and not self._scroll_timer.isActive():
            self._scroll_timer.start()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        kind = event.type()
        if watched is self._container and kind in (
            QEvent.Type.DragEnter,
            QEvent.Type.DragMove,
            QEvent.Type.Drop,
        ):
            mime = event.mimeData()  # type: ignore[attr-defined]
            if self._dragging is None or not mime.hasFormat(ROW_MIME):
                return False  # files dropped from Explorer etc. are someone else's
            pos = event.position().toPoint()  # type: ignore[attr-defined]
            index = self.drop_index(pos)
            event.acceptProposedAction()  # type: ignore[attr-defined]
            if kind == QEvent.Type.Drop:
                self._target = index
                self._line.hide()
                self._scroll_timer.stop()
            else:
                self._show_line(index)
                self._edge_scroll(pos)
            return True
        if watched is self._container and kind == QEvent.Type.DragLeave:
            if self._dragging is not None:
                self._line.hide()
                self._scroll_timer.stop()
            return False
        if isinstance(watched, QWidget) and watched is not self._container:
            if kind in (QEvent.Type.Enter, QEvent.Type.HoverEnter):
                watched.setProperty("_rf_hover", True)
                self.refresh()
            elif kind in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
                watched.setProperty("_rf_hover", False)
                self.refresh()
            elif kind in (QEvent.Type.Resize, QEvent.Type.LayoutRequest, QEvent.Type.Show):
                self._place(watched)
        return False


def _lifted(pixmap: QPixmap) -> QPixmap:
    """The image that follows the pointer: the row, slightly see-through."""
    out = QPixmap(pixmap.size())
    out.setDevicePixelRatio(pixmap.devicePixelRatio())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setOpacity(0.92)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return out
