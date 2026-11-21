"""The "Insert placeholder" picker — one small window per field that takes placeholders.

Every field that understands placeholders (the email subject, the email body, the output
file name) gets an "Insert placeholder" button. It opens a picker listing exactly the
placeholders that field supports — searchable, grouped, each with what it does and an example
of what it becomes. Double-click a row, press Enter or click Insert to put it at the cursor;
the picker stays open, so placeholders can be added one by one.

The lists come from the single sources of truth: ``core.email.render.PLACEHOLDERS`` for email
and ``core.output_names.OUTPUT_NAME_TOKENS`` for file names — the Help guide uses them too.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeyEvent, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from reportflow.core.email.render import PLACEHOLDERS, render_subject, sample_context
from reportflow.core.output_names import OUTPUT_NAME_TOKENS, expand_output_name
from reportflow.ui.feedback import InlineNotice

Target = QLineEdit | QPlainTextEdit | QTextEdit
# A field, or a function returning the field to use now (e.g. the current editor tab).
TargetRef = Target | Callable[[], Target]
NB_HYPHEN = "\u2011"
_INLINE_TOKEN = 22  # longer tokens go on their own line


@dataclass(frozen=True)
class Placeholder:
    group: str
    label: str
    token: str
    description: str
    example: str = ""  # what it becomes, e.g. "07-Oct-2026" ("" for whole blocks)


def email_placeholders(*, subject: bool = False, now: datetime | None = None) -> list[Placeholder]:
    """Placeholders for the email body — or the subject line (no HTML blocks there)."""
    context = sample_context(now=now)
    result = []
    for group, label, token, description in PLACEHOLDERS:
        if group == "Blocks":
            if subject:
                continue
            example = ""
        else:
            example = render_subject(token, context)
        result.append(Placeholder(group, label, token, description, example))
    return result


def output_name_placeholders(
    *, job_name: str = "", now: datetime | None = None
) -> list[Placeholder]:
    """Tokens for the output file name, with examples for this job."""
    now = now or datetime.now()
    job = job_name.strip() or "Daily report"
    return [
        Placeholder(
            "File name",
            label,
            token,
            description,
            expand_output_name(token, job_name=job, run_id="a1b2c3d4", now=now, workbook="Sales"),
        )
        for label, token, description in OUTPUT_NAME_TOKENS
    ]


def _resolve(target: TargetRef) -> Target:
    return target if isinstance(target, QLineEdit | QPlainTextEdit | QTextEdit) else target()


def insert_at_cursor(target: Target, text: str) -> None:
    if isinstance(target, QLineEdit):
        target.insert(text)
    else:
        target.insertPlainText(text)


class _Row(QFrame):
    """One placeholder: name and token on top, what it does and an example below, Insert."""

    def __init__(self, item: Placeholder, on_insert: Callable[[Placeholder], None]) -> None:
        super().__init__()
        self.setObjectName("placeholderRow")
        self.item = item
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 8, 6)
        row.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel(item.label)
        name.setObjectName("placeholderName")
        name.setTextFormat(Qt.TextFormat.PlainText)
        token = QLabel(item.token)
        token.setObjectName("placeholderToken")
        # Plain text: a block such as <ul>…</ul> must show as written, not as a list.
        token.setTextFormat(Qt.TextFormat.PlainText)
        token.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        if len(item.token) > _INLINE_TOKEN:
            # A long token gets its own line instead of being cut off.
            token.setWordWrap(True)  # whole blocks are long: show all of it, wrapped
            text.addWidget(name)
            text.addWidget(token)
        else:
            top = QHBoxLayout()
            top.setSpacing(8)
            top.addWidget(name)
            top.addWidget(token)
            top.addStretch(1)
            text.addLayout(top)
        detail = item.description
        if item.example:
            # Non-breaking hyphens: an example like 20-Nov-2026 never splits across lines.
            detail += f"  →  {item.example.replace('-', NB_HYPHEN)}"
        about = QLabel(detail)
        about.setObjectName("placeholderAbout")
        about.setTextFormat(Qt.TextFormat.PlainText)
        about.setWordWrap(True)
        text.addWidget(about)
        row.addLayout(text, 1)
        self.insert_button = QPushButton("Insert")
        self.insert_button.setObjectName("placeholderInsert")
        self.insert_button.setAutoDefault(False)
        self.insert_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.insert_button.setToolTip(f"Insert {item.token} at the cursor")
        self.insert_button.clicked.connect(lambda: on_insert(item))
        row.addWidget(self.insert_button, 0, Qt.AlignmentFlag.AlignVCenter)


class PlaceholderPicker(QDialog):
    """A tool window that inserts placeholders into ``target`` at its cursor."""

    def __init__(
        self,
        target: TargetRef,
        items: list[Placeholder],
        *,
        field_name: str,
        parent: QWidget | None = None,
        read_only_message: str = "This field can't be edited right now.",
    ) -> None:
        super().__init__(parent or _resolve(target).window())
        self._read_only_message = read_only_message
        self.setObjectName("placeholderPicker")
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowTitle(f"Insert placeholder — {field_name}")
        self.setModal(False)
        self._target = target
        self._field_name = field_name
        self.resize(460, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search placeholders…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.setObjectName("placeholderList")
        self.list.setSpacing(0)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        # Rows follow the list's width (descriptions wrap) — never a sideways scroll.
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.itemDoubleClicked.connect(self._insert_item)
        self.list.itemActivated.connect(self._insert_item)
        layout.addWidget(self.list, 1)

        self.notice = InlineNotice()
        footer = QHBoxLayout()
        footer.addWidget(self.notice, 1)
        done = QPushButton("Done")
        done.setAutoDefault(False)
        done.clicked.connect(self.close)
        footer.addWidget(done)
        layout.addLayout(footer)

        self._rows: list[tuple[QListWidgetItem, _Row]] = []
        self._headers: dict[str, QListWidgetItem] = {}
        self._fill(items)

    # -- content --

    def _fill(self, items: list[Placeholder]) -> None:
        for group in dict.fromkeys(i.group for i in items):
            header = QListWidgetItem()  # the label below draws the name, once
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setData(Qt.ItemDataRole.UserRole, None)
            self.list.addItem(header)
            label = QLabel(group.upper())
            label.setObjectName("placeholderGroup")
            self.list.setItemWidget(header, label)
            header.setSizeHint(label.sizeHint())
            self._headers[group] = header
            for item in (i for i in items if i.group == group):
                entry = QListWidgetItem()
                entry.setData(Qt.ItemDataRole.UserRole, item)
                self.list.addItem(entry)
                row = _Row(item, self.insert)
                self.list.setItemWidget(entry, row)
                self._rows.append((entry, row))
        self._fit_rows()
        self._select_first_visible()

    def _fit_rows(self) -> None:
        """Size every row to the list's current width, wrapping its description."""
        viewport = self.list.viewport()
        width = max(200, (viewport.width() if viewport is not None else 400) - 4)
        for entry, row in self._rows:
            row.setFixedWidth(width)
            layout = row.layout()
            height = layout.totalHeightForWidth(width) if layout is not None else -1
            entry.setSizeHint(QSize(width, height if height > 0 else row.sizeHint().height()))

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_rows()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self._fit_rows()

    def items(self) -> list[Placeholder]:
        return [row.item for _, row in self._rows]

    def visible_tokens(self) -> list[str]:
        return [row.item.token for entry, row in self._rows if not entry.isHidden()]

    def _filter(self, text: str) -> None:
        needle = text.strip().casefold()
        shown_groups: set[str] = set()
        for entry, row in self._rows:
            item = row.item
            hay = f"{item.label} {item.token} {item.description} {item.example}".casefold()
            visible = needle in hay
            entry.setHidden(not visible)
            if visible:
                shown_groups.add(item.group)
        for group, header in self._headers.items():
            header.setHidden(group not in shown_groups)
        self._select_first_visible()

    def _select_first_visible(self) -> None:
        for entry, _row in self._rows:
            if not entry.isHidden():
                self.list.setCurrentItem(entry)
                return

    # -- inserting --

    def _insert_item(self, entry: QListWidgetItem) -> None:
        item = entry.data(Qt.ItemDataRole.UserRole)
        if isinstance(item, Placeholder):
            self.insert(item)

    def insert(self, item: Placeholder) -> None:
        target = _resolve(self._target)
        if target.isReadOnly():
            self.notice.show_notice(self._read_only_message, "warning")
            return
        insert_at_cursor(target, item.token)
        self.notice.show_notice(f"Inserted {item.token} into {self._field_name}.", "success")

    def eventFilter(self, watched: object, event: object) -> bool:  # noqa: N802
        # Up/Down/Enter in the search box drive the list, so the keyboard alone is enough.
        if watched is self.search and isinstance(event, QKeyEvent):
            if event.type() == QKeyEvent.Type.KeyPress:
                key = event.key()
                if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                    self._step(1 if key == Qt.Key.Key_Down else -1)
                    return True
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    current = self.list.currentItem()
                    if current is not None and not current.isHidden():
                        self._insert_item(current)
                    return True
        return super().eventFilter(watched, event)  # type: ignore[arg-type]

    def _step(self, delta: int) -> None:
        visible = [entry for entry, _ in self._rows if not entry.isHidden()]
        if not visible:
            return
        current = self.list.currentItem()
        index = visible.index(current) if current in visible else -1
        target = visible[max(0, min(len(visible) - 1, index + delta))]
        self.list.setCurrentItem(target)
        self.list.scrollToItem(target)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            current = self.list.currentItem()
            if current is not None:
                self._insert_item(current)
            event.accept()
            return
        super().keyPressEvent(event)

    def place_near(self, anchor: QWidget) -> None:
        """Open beside the button that opened it, kept on the screen."""
        point = anchor.mapToGlobal(QPoint(anchor.width() + 8, 0))
        screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = min(point.x(), area.right() - self.width())
            y = min(max(point.y() - 40, area.top()), area.bottom() - self.height())
            if x < area.left():
                x = area.left()
            point = QPoint(x, y)
        self.move(point)


class PlaceholderButton(QPushButton):
    """ "{ } Insert placeholder" next to a field; opens (or re-shows) its picker."""

    def __init__(
        self,
        target: TargetRef,
        items: Callable[[], list[Placeholder]],
        *,
        field_name: str,
        parent: QWidget | None = None,
        read_only_message: str = "This field can't be edited right now.",
    ) -> None:
        super().__init__("{ }  Insert placeholder", parent)
        self.setObjectName("placeholderButton")
        self.setAutoDefault(False)
        self.setToolTip(f"Pick a placeholder to insert into the {field_name.lower()}")
        self._target = target
        self._items = items
        self._field_name = field_name
        self._read_only_message = read_only_message
        self.picker: PlaceholderPicker | None = None
        self.clicked.connect(self.open_picker)

    def open_picker(self) -> PlaceholderPicker:
        if self.picker is None:
            self.picker = PlaceholderPicker(
                self._target,
                self._items(),
                field_name=self._field_name,
                parent=self.window(),
                read_only_message=self._read_only_message,
            )
            self.picker.place_near(self)
        self.picker.show()
        self.picker.raise_()
        self.picker.activateWindow()
        QTimer.singleShot(0, self.picker.search.setFocus)
        return self.picker
