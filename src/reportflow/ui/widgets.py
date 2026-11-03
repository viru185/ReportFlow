"""Shared presentation helpers; checkboxes retain the model's existing state/signals."""

from typing import Any

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtWidgets import (
    QApplication,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QWidget,
)


class CenteredCheckDelegate(QStyledItemDelegate):
    """Use the same centered rectangle for painting and mouse hit testing."""

    @staticmethod
    def indicator_rect(option: Any) -> QRect:
        style = option.widget.style() if option.widget else QApplication.style()
        size = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth)
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
            QStyle.PrimitiveElement.PE_IndicatorCheckBox, button, painter, option.widget
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
    """Keep dialog actions visible when content exceeds a small screen."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(content)
    return scroll
