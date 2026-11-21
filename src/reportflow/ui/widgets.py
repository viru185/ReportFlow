"""Shared presentation helpers; checkboxes retain the model's existing state/signals."""

from typing import Any

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QWidget,
    QWidgetItem,
)


def space_layout(layout: QLayout | None, *, margin: int = 16) -> None:
    """Apply explicit gaps; nested Qt forms otherwise inherit zero horizontal spacing."""
    if layout is None:
        return
    layout.setContentsMargins(margin, margin, margin, margin)
    if isinstance(layout, QFormLayout):
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(12)
        layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    else:
        layout.setSpacing(8 if isinstance(layout, QHBoxLayout) else 16)
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is not None and item.layout() is not None:
            space_layout(item.layout(), margin=0)


def section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("section", True)
    # A label with stylesheet padding counts as framed, and Qt then indents its text by
    # half an "x" — the title sat ~6 px right of the fields under it.
    label.setIndent(0)
    return label


class CenteredCheckDelegate(QStyledItemDelegate):
    """Use the same centered rectangle for painting and mouse hit testing."""

    @staticmethod
    def indicator_rect(option: Any) -> QRect:
        style = option.widget.style() if option.widget else QApplication.style()
        size = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, None, option.widget)
        rect = QRect(0, 0, size, size)
        rect.moveCenter(option.rect.center())
        return rect

    def paint(self, painter: Any, option: Any, index: Any) -> None:
        button = QStyleOptionButton()
        button.rect = self.indicator_rect(option)
        button.state = (
            QStyle.StateFlag.State_On
            if index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked.value
            else QStyle.StateFlag.State_Off
        )
        if index.flags() & Qt.ItemFlag.ItemIsEnabled:
            button.state |= QStyle.StateFlag.State_Enabled
        if option.state & QStyle.StateFlag.State_HasFocus:
            button.state |= QStyle.StateFlag.State_HasFocus
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck, button, painter, option.widget
        )

    def editorEvent(self, event: Any, model: Any, option: Any, index: Any) -> bool:
        if not index.flags() & Qt.ItemFlag.ItemIsEnabled:
            return False
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            if event.button() != Qt.MouseButton.LeftButton or not self.indicator_rect(
                option
            ).contains(event.position().toPoint()):
                return False
            if event.type() == QEvent.Type.MouseButtonPress:
                return True
        elif event.type() == QEvent.Type.KeyPress:
            if event.key() not in (Qt.Key.Key_Space, Qt.Key.Key_Select):
                return False
        else:
            return False
        checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked.value
        return model.setData(
            index,
            Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked,
            Qt.ItemDataRole.CheckStateRole,
        )


def scroll_page(content: QWidget) -> QScrollArea:
    """Keep dialog actions visible when content exceeds a small screen. Pages scroll
    vertically only — content wider than the window is a layout bug, not a scroll."""
    from reportflow.ui.kit.views import ScrollArea

    return ScrollArea(content)


class FlowLayout(QLayout):
    """Lays widgets out left to right and wraps to the next line (the Qt flow example)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 — Qt override
        self._items.append(item)

    def insertWidget(self, index: int, widget: QWidget) -> None:  # noqa: N802
        self.addChildWidget(widget)
        self._items.insert(index, QWidgetItem(widget))
        self.invalidate()

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect: QRect, *, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = area.x(), area.y(), 0
        spacing = self.spacing()
        rows: list[list[tuple[QLayoutItem, QSize, int]]] = [[]]
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and line_height > 0:
                x, y = area.x(), y + line_height + spacing
                line_height = 0
                rows.append([])
            rows[-1].append((item, hint, x))
            x += hint.width() + spacing
            line_height = max(line_height, hint.height())
        if apply:
            # Centre each item on its row, so chips and the text box share one baseline.
            top = area.y()
            for row in rows:
                height = max((hint.height() for _, hint, _ in row), default=0)
                for item, hint, left in row:
                    offset = (height - hint.height()) // 2
                    item.setGeometry(QRect(QPoint(left, top + offset), hint))
                top += height + spacing
        return y + line_height - rect.y() + margins.bottom()
