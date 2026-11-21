"""The job editor's workbook list: one row per Excel file, the empty drop zone, and drops.

The list replaces the old tab strip, which elided names to "…" once a job had a few files.
Each row shows the file's name and what the editor knows about it ("3 of 5 sheets", "Reading
sheets…", "⚠ File not found"); the selected or hovered row offers Replace… and Remove. One
"+ Add workbooks…" button sits under the list, and Excel files can be dropped anywhere on the
General tab. A job without workbooks shows a large drop zone instead of an empty list.

The editor owns the state; this module only shows it (``RowView``) and reports what the user
asked for through signals.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.assets import asset_icon
from reportflow.ui.feedback import flash
from reportflow.ui.style import ACCENT_HOVER, BORDER_HOVER, CARD_BG, TEXT, TEXT_MUTED

EXCEL_SUFFIXES = (".xlsx", ".xlsm")


@dataclass(frozen=True)
class RowView:
    """How one workbook is shown in the list."""

    name: str
    path: str
    status: str
    kind: str = "muted"  # "muted" | "warning" | "busy"
    tooltip: str = ""


class ElidedLabel(QLabel):
    """A one-line label that shortens long text in the middle ("Utkal_PI…31_Oct.xlsx")."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle,
    ) -> None:
        super().__init__(parent)
        self._full = text
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)
        super().setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        super().setText(text)
        self.update()

    def full_text(self) -> str:
        return self._full

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(min(hint.width(), 240), hint.height())

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        metrics = QFontMetrics(self.font())
        shown = metrics.elidedText(self._full, self._mode, self.width())
        painter.setFont(self.font())
        painter.drawText(self.rect(), int(self.alignment() | Qt.AlignmentFlag.AlignVCenter), shown)


class _Row(QFrame):
    """One workbook: icon, name, status — and Replace / Remove on the hovered or selected row."""

    replace_clicked = Signal()
    remove_clicked = Signal()

    def __init__(self, view: RowView) -> None:
        super().__init__()
        self.setObjectName("workbookRow")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._selected = False
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 6, 8)
        row.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(asset_icon("workbook.svg").pixmap(20, 20))
        icon.setFixedSize(20, 20)
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.name = ElidedLabel()
        self.name.setObjectName("workbookName")
        self.status = ElidedLabel(mode=Qt.TextElideMode.ElideRight)
        self.status.setObjectName("workbookStatus")
        text.addWidget(self.name)
        text.addWidget(self.status)
        row.addLayout(text, 1)
        self.replace_button = self._tool("replace.svg", "Replace this workbook with another file…")
        self.replace_button.clicked.connect(self.replace_clicked)
        self.remove_button = self._tool(None, "Remove this workbook from the job")
        self.remove_button.setText("×")
        self.remove_button.setProperty("danger", True)
        self.remove_button.clicked.connect(self.remove_clicked)
        row.addWidget(self.replace_button, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.remove_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.update_view(view)
        self._show_actions(False)

    @staticmethod
    def _tool(icon: str | None, tip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("workbookAction")
        if icon:
            button.setIcon(asset_icon(icon))
            button.setIconSize(QSize(16, 16))
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.setFixedSize(28, 28)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        policy = button.sizePolicy()
        policy.setRetainSizeWhenHidden(True)  # showing them never re-elides the name
        button.setSizePolicy(policy)
        return button

    def update_view(self, view: RowView) -> None:
        self.name.setText(view.name)
        self.status.setText(view.status)
        self.status.setProperty("kind", view.kind)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.setToolTip(view.tooltip or view.path)

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._show_actions(selected or self.underMouse())

    def _show_actions(self, show: bool) -> None:
        self.replace_button.setVisible(show)
        self.remove_button.setVisible(show)

    def enterEvent(self, event: QEvent) -> None:  # noqa: N802
        self._show_actions(True)
        super().enterEvent(event)  # type: ignore[arg-type]

    def leaveEvent(self, event: QEvent) -> None:  # noqa: N802
        self._show_actions(self._selected)
        super().leaveEvent(event)


class WorkbookList(QFrame):
    """The list of the job's workbooks, with the Add button under it."""

    current_changed = Signal(int)
    add_requested = Signal()
    replace_requested = Signal(int)
    remove_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workbookList")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.list = QListWidget()
        self.list.setObjectName("workbookItems")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.currentRowChanged.connect(self._on_current)
        self.list.installEventFilter(self)
        layout.addWidget(self.list, 1)
        self.add_button = QPushButton("+  Add workbooks…")
        self.add_button.setObjectName("addWorkbooks")
        self.add_button.setToolTip(
            "Add Excel files to this job — pick several at once. Every workbook is built on "
            "each run and all the files go out in one email."
        )
        self.add_button.clicked.connect(self.add_requested)
        layout.addWidget(self.add_button)
        hint = QLabel("or drop Excel files here")
        hint.setProperty("muted", True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setObjectName("dropHint")
        layout.addWidget(hint)

    # -- rows --

    def rows(self) -> list[_Row]:
        result = []
        for i in range(self.list.count()):
            widget = self.list.itemWidget(self.list.item(i))
            if isinstance(widget, _Row):
                result.append(widget)
        return result

    def count(self) -> int:
        return self.list.count()

    def set_rows(self, views: list[RowView], current: int) -> None:
        self.list.blockSignals(True)
        try:
            self.list.clear()
            for view in views:
                self._append(view)
        finally:
            self.list.blockSignals(False)
        self.set_current(current)

    def insert_row(self, index: int, view: RowView) -> None:
        self.list.blockSignals(True)
        try:
            self._append(view, index)
        finally:
            self.list.blockSignals(False)

    def _append(self, view: RowView, index: int | None = None) -> None:
        item = QListWidgetItem()
        row = _Row(view)
        row.replace_clicked.connect(lambda r=row: self.replace_requested.emit(self._index_of(r)))
        row.remove_clicked.connect(lambda r=row: self.remove_requested.emit(self._index_of(r)))
        item.setSizeHint(QSize(0, row.sizeHint().height()))
        if index is None:
            self.list.addItem(item)
        else:
            self.list.insertItem(index, item)
        self.list.setItemWidget(item, row)

    def _index_of(self, row: _Row) -> int:
        for i in range(self.list.count()):
            if self.list.itemWidget(self.list.item(i)) is row:
                return i
        return -1

    def remove_row(self, index: int) -> None:
        self.list.blockSignals(True)
        try:
            item = self.list.takeItem(index)
            del item
        finally:
            self.list.blockSignals(False)

    def update_row(self, index: int, view: RowView) -> None:
        item = self.list.item(index)
        row = self.list.itemWidget(item) if item is not None else None
        if isinstance(row, _Row):
            row.update_view(view)

    def set_current(self, index: int) -> None:
        self.list.blockSignals(True)
        try:
            self.list.setCurrentRow(index)
        finally:
            self.list.blockSignals(False)
        self._mark_selected(index)

    def current(self) -> int:
        return self.list.currentRow()

    def flash(self, index: int) -> None:
        item = self.list.item(index)
        row = self.list.itemWidget(item) if item is not None else None
        if isinstance(row, _Row):
            self.list.scrollToItem(item)
            flash(row)

    # -- behaviour --

    def _on_current(self, index: int) -> None:
        self._mark_selected(index)
        self.current_changed.emit(index)

    def _mark_selected(self, index: int) -> None:
        for i, row in enumerate(self.rows()):
            row.set_selected(i == index)

    def _context_menu(self, pos: QPoint) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        index = self.list.row(item)
        menu = QMenu(self)
        menu.addAction("Replace with another file…", lambda: self.replace_requested.emit(index))
        menu.addAction("Remove from this job", lambda: self.remove_requested.emit(index))
        viewport = self.list.viewport()
        if viewport is not None:
            menu.exec(viewport.mapToGlobal(pos))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            watched is self.list
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Delete  # type: ignore[attr-defined]
            and self.list.currentRow() >= 0
        ):
            self.remove_requested.emit(self.list.currentRow())
            return True
        return super().eventFilter(watched, event)


class EmptyDropZone(QWidget):
    """What a job without workbooks shows: a big, friendly place to drop or pick files."""

    add_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("emptyDropZone")
        self.setMinimumHeight(220)
        self._hover = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(10)
        layout.addStretch(1)
        icon = QLabel()
        icon.setPixmap(asset_icon("workbook.svg").pixmap(44, 44))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        title = QLabel("Add the Excel workbooks for this report")
        title.setObjectName("dropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        hint = QLabel("Drop .xlsx or .xlsm files here — several at once — or")
        hint.setProperty("muted", True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        button = QPushButton("+  Add workbooks…")
        button.setProperty("accent", True)
        button.clicked.connect(self.add_requested)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(1)
        self.add_button = button

    def set_hover(self, hover: bool) -> None:
        self._hover = hover
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(ACCENT_HOVER if self._hover else BORDER_HOVER))
        pen.setWidthF(1.5)
        pen.setDashPattern([5.0, 4.0])
        painter.setPen(pen)
        painter.setBrush(QColor(28, 40, 60, 90) if self._hover else Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)


class DropOverlay(QWidget):
    """Covers the General tab while files are dragged over it: "Drop to add workbooks"."""

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def cover(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.raise_()
        self.show()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(16, 20, 28, 225))
        pen = QPen(QColor(ACCENT_HOVER))
        pen.setWidthF(2.0)
        pen.setDashPattern([6.0, 4.0])
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(12, 12, -12, -12), 12, 12)
        # The message sits on a solid card, so nothing behind it shows through.
        card = QRectF(0, 0, 340, 104)
        card.moveCenter(QRectF(self.rect()).center())
        painter.setPen(QPen(QColor(ACCENT_HOVER), 1.0))
        painter.setBrush(QColor(CARD_BG))
        painter.drawRoundedRect(card, 10, 10)
        font = painter.font()
        base = font.pointSizeF()
        font.setPointSizeF(base + 4)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(TEXT))
        title = QRectF(card.left(), card.top() + 18, card.width(), 36)
        painter.drawText(title, int(Qt.AlignmentFlag.AlignCenter), "Drop to add workbooks")
        font.setPointSizeF(base)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor(TEXT_MUTED))
        below = QRectF(card.left(), card.top() + 58, card.width(), 28)
        painter.drawText(below, int(Qt.AlignmentFlag.AlignCenter), ".xlsx and .xlsm files")


def local_files(event: object) -> list[str]:
    """The local file paths a drag carries (empty when it carries none)."""
    mime = event.mimeData() if hasattr(event, "mimeData") else None  # type: ignore[union-attr]
    if mime is None or not mime.hasUrls():
        return []
    return [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]


class FileDropFilter(QObject):
    """Makes ``target`` accept dropped files, showing ``overlay`` while they hover."""

    def __init__(
        self,
        target: QWidget,
        overlay: DropOverlay,
        on_drop: Callable[[list[str]], None],
        *,
        zone: EmptyDropZone | None = None,
    ) -> None:
        super().__init__(target)
        self._overlay = overlay
        self._on_drop = on_drop
        self._zone = zone
        target.setAcceptDrops(True)
        target.installEventFilter(self)

    def _show(self, show: bool) -> None:
        if self._zone is not None and self._zone.isVisible():
            self._zone.set_hover(show)  # the empty zone lights up instead of an overlay
            self._overlay.hide()
        elif show:
            self._overlay.cover()
        else:
            self._overlay.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        kind = event.type()
        if kind in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if local_files(event):
                event.acceptProposedAction()  # type: ignore[attr-defined]
                self._show(True)
                return True
        elif kind == QEvent.Type.DragLeave:
            self._show(False)
            return True
        elif kind == QEvent.Type.Drop:
            self._show(False)
            paths = local_files(event)
            if paths:
                event.acceptProposedAction()  # type: ignore[attr-defined]
                QTimer.singleShot(0, lambda: self._on_drop(paths))  # after the drop returns
                return True
        return super().eventFilter(watched, event)


def is_excel_path(path: str) -> bool:
    p = Path(path)
    return p.suffix.lower() in EXCEL_SUFFIXES and not p.name.startswith("~$")
