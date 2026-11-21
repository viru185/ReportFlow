"""Non-blocking feedback and the shared behaviour of editing dialogs.

- :func:`toast` — a small notice that fades in at the top of its window and fades out on its
  own (optionally with one action such as "Undo"). It replaces "OK" message boxes for
  information and success messages; real decisions stay as dialogs.
- :class:`InlineNotice` — one line of muted/warning text under a group of fields, for
  feedback that belongs to those fields (e.g. "a@x.com is already in Cc"). It reserves its
  height, so the layout never jumps when a message appears.
- :func:`set_field_error` / :func:`clear_field_error` and :func:`mark_tab_errors` — validation
  shown on the field itself and as a red dot on its tab, instead of an OK popup.
- :class:`FormDialog` — the editor, Settings and the template dialog: Enter never closes the
  form, Ctrl+S saves, F1 opens Help, Esc/Cancel/× ask before discarding real edits, and the
  dialog reopens at the size it was left at.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from typing import Any, cast

from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QSettings,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QBoxLayout,
    QDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QWidget,
)

from reportflow.ui.kit.buttons import Button, IconButton
from reportflow.ui.style import ACCENT_HOVER, DANGER, SUCCESS, WARNING

ERROR_COLOR = DANGER

# kind -> (glyph, accent colour)
_KINDS: dict[str, tuple[str, str]] = {
    "success": ("✓", SUCCESS),
    "info": ("i", ACCENT_HOVER),
    "warning": ("!", WARNING),
    "error": ("✕", ERROR_COLOR),
}
_TOAST_MS = {"success": 3500, "info": 3500, "warning": 6000, "error": 7000}
_MAX_TOASTS = 3
_TEXT_MAX = 440  # px; longer messages wrap


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def flash(widget: QWidget, *, times: int = 2, ms: int = 220) -> None:
    """Briefly highlight ``widget`` (``flash`` property), e.g. the chip a duplicate points at."""

    def step(n: int) -> None:
        widget.setProperty("flash", n % 2 == 0)
        repolish(widget)
        if n + 1 < times * 2:
            QTimer.singleShot(ms, widget, lambda: step(n + 1))

    step(0)


# -- toasts ---------------------------------------------------------------------------


class Toast(QFrame):
    """One notice. Created and laid out by :class:`_ToastHost`; use :func:`toast`."""

    def __init__(
        self,
        host: _ToastHost,
        text: str,
        kind: str,
        action: tuple[str, Callable[[], None]] | None,
    ) -> None:
        super().__init__(host.window)
        self._host = host
        self.kind = kind if kind in _KINDS else "info"
        self.text = text
        self.setObjectName("toast")
        self.setProperty("kind", self.kind)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        glyph, _color = _KINDS[self.kind]

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 8, 10)
        row.setSpacing(10)
        icon = QLabel(glyph)
        icon.setObjectName("toastIcon")
        icon.setProperty("kind", self.kind)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(20, 20)
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        label = QLabel(text)
        label.setObjectName("toastText")
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        # A word-wrapped label otherwise reports a narrow hint and breaks short messages.
        natural = label.fontMetrics().horizontalAdvance(text) + 4
        label.setMinimumWidth(min(natural, _TEXT_MAX))
        label.setMaximumWidth(_TEXT_MAX)
        self.label = label
        row.addWidget(label, 1)
        self.action_button: QPushButton | None = None
        if action is not None:
            caption, callback = action
            button = Button(caption, small=True)

            def run() -> None:
                self.dismiss()
                callback()

            button.clicked.connect(run)
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
            self.action_button = button
        close = IconButton("×", "Dismiss", variant="dismiss", size=20, focusable=False)
        close.clicked.connect(self.dismiss)
        row.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(shadow)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        self._timer.start(_TOAST_MS[self.kind])
        self._closing = False

    def enterEvent(self, event: Any) -> None:  # hovering keeps it readable
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: Any) -> None:
        if not self._closing:
            self._timer.start(1500)
        super().leaveEvent(event)

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        # The drop shadow and a fade can't share the one graphics effect a widget may have,
        # so the fade swaps the shadow for an opacity effect.
        fade = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(fade)
        anim = QPropertyAnimation(fade, b"opacity", self)
        anim.setDuration(180)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(self._remove)
        anim.start()

    def _remove(self) -> None:
        self._host.forget(self)
        self.hide()
        self.deleteLater()


class _ToastHost(QObject):
    """Stacks a window's toasts at its top centre and keeps them there on resize."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.window = window
        self.toasts: list[Toast] = []
        window.installEventFilter(self)

    def add(self, item: Toast) -> None:
        self.toasts.append(item)
        while len(self.toasts) > _MAX_TOASTS:
            oldest = self.toasts.pop(0)
            oldest.hide()
            oldest.deleteLater()
        item.adjustSize()
        item.show()
        item.raise_()
        self.layout()

    def forget(self, item: Toast) -> None:
        if item in self.toasts:
            self.toasts.remove(item)
        self.layout()

    def layout(self) -> None:
        top = 12
        if isinstance(self.window, QMainWindow) and self.window.menuBar().isVisible():
            top += self.window.menuBar().height()
        # One width for the whole stack, so the notices line up as a column.
        widest = max((t.sizeHint().width() for t in self.toasts), default=0)
        width = min(widest, max(240, self.window.width() - 32))
        y = top
        for item in self.toasts:
            height = item.heightForWidth(width) if item.hasHeightForWidth() else -1
            item.resize(width, height if height > 0 else item.sizeHint().height())
            item.move((self.window.width() - width) // 2, y)
            item.raise_()
            y += item.height() + 8

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.window and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.layout()
        return False


def _host_for(widget: QWidget) -> _ToastHost:
    window = widget.window()
    host = window.findChild(_ToastHost, options=Qt.FindChildOption.FindDirectChildrenOnly)
    return host if isinstance(host, _ToastHost) else _ToastHost(window)


def toast(
    parent: QWidget,
    text: str,
    kind: str = "info",
    action: tuple[str, Callable[[], None]] | None = None,
) -> Toast:
    """Show a fading notice at the top of ``parent``'s window; returns it (tests read it)."""
    host = _host_for(parent)
    item = Toast(host, text, kind, action)
    host.add(item)
    return item


def toasts(widget: QWidget) -> list[str]:
    """The texts of the notices currently shown on ``widget``'s window (oldest first)."""
    window = widget.window()
    host = window.findChild(_ToastHost, options=Qt.FindChildOption.FindDirectChildrenOnly)
    if not isinstance(host, _ToastHost):
        return []
    return [t.text for t in host.toasts if not t._closing]


# -- inline notices -------------------------------------------------------------------


class InlineNotice(QLabel):
    """One reserved line of feedback under a group of fields; clears itself after a while."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("inlineNotice")
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setProperty("kind", "idle")
        self.setMinimumHeight(self.fontMetrics().height() + 4)
        self._action: Callable[[], None] | None = None
        self.linkActivated.connect(self._on_link)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear_notice)
        self.plain = ""

    def show_notice(
        self,
        text: str,
        kind: str = "info",
        *,
        action: tuple[str, Callable[[], None]] | None = None,
        timeout_ms: int = 6000,
    ) -> None:
        self.plain = text
        body = html.escape(text)
        self._action = None
        if action is not None:
            caption, callback = action
            self._action = callback
            body += f' &nbsp;<a href="action">{html.escape(caption)}</a>'
        self.setText(body)
        self.setProperty("kind", kind)
        repolish(self)
        if timeout_ms > 0:
            self._timer.start(timeout_ms)
        else:
            self._timer.stop()  # stays until it's fixed (e.g. a validation message)

    def clear_notice(self) -> None:
        self._timer.stop()
        self.plain = ""
        self._action = None
        self.setText("")
        self.setProperty("kind", "idle")
        repolish(self)

    def _on_link(self, _href: str) -> None:
        callback = self._action
        self.clear_notice()
        if callback is not None:
            callback()


# -- field errors and tab dots --------------------------------------------------------


def _find_layout(root: QLayout | None, widget: QWidget) -> QLayout | None:
    if root is None:
        return None
    if root.indexOf(widget) >= 0:
        return root
    for i in range(root.count()):
        item = root.itemAt(i)
        child = item.layout() if item is not None else None
        found = _find_layout(child, widget)
        if found is not None:
            return found
    return None


def _parent_layout(root: QLayout | None, child: QLayout) -> QLayout | None:
    if root is None:
        return None
    for i in range(root.count()):
        item = root.itemAt(i)
        sub = item.layout() if item is not None else None
        if sub is child:
            return root
        found = _parent_layout(sub, child)
        if found is not None:
            return found
    return None


def _error_label(widget: QWidget) -> QLabel | None:
    """The message label under ``widget``, created on first use (None if it can't be placed).

    In a form, the field (or the horizontal row it sits in, e.g. a field plus its button) is
    moved into a small holder with the label 4 px below — closer than a whole form row."""
    label = getattr(widget, "_rf_error_label", None)
    if isinstance(label, QLabel):
        return label
    parent = widget.parentWidget()
    root = parent.layout() if parent else None
    inner = _find_layout(root, widget)
    if inner is None:
        return None
    target: QWidget | QLayout = widget
    container: QLayout = inner
    horizontal = (QBoxLayout.Direction.LeftToRight, QBoxLayout.Direction.RightToLeft)
    if isinstance(inner, QBoxLayout) and inner.direction() in horizontal:
        outer = _parent_layout(root, inner)
        if outer is None:
            return None
        target, container = inner, outer
    label = QLabel()
    label.setObjectName("fieldError")
    label.setWordWrap(True)
    label.hide()
    if isinstance(container, QFormLayout):
        position = (
            container.getWidgetPosition(target)
            if isinstance(target, QWidget)
            else container.getLayoutPosition(target)
        )
        row, role = cast(tuple[int, QFormLayout.ItemRole], position)
        if row < 0:
            return None
        holder = QWidget()
        box = QBoxLayout(QBoxLayout.Direction.TopToBottom, holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        if isinstance(target, QWidget):
            container.removeWidget(target)
            box.addWidget(target)
        else:
            container.removeItem(target)
            target.setParent(None)  # type: ignore[call-overload]
            box.addLayout(target)
        box.addWidget(label)
        container.setWidget(row, role, holder)
    elif isinstance(container, QBoxLayout):
        container.insertWidget(container.indexOf(target) + 1, label)
    else:
        return None
    widget._rf_error_label = label  # type: ignore[attr-defined]
    return label


def set_field_error(widget: QWidget, message: str) -> None:
    """Outline ``widget`` in red and show ``message`` right under it."""
    widget.setProperty("invalid", True)
    repolish(widget)
    label = _error_label(widget)
    if label is not None:
        label.setText(message)
        label.show()
    else:
        widget.setToolTip(message)


def clear_field_error(widget: QWidget) -> None:
    widget.setProperty("invalid", False)
    repolish(widget)
    label = getattr(widget, "_rf_error_label", None)
    if isinstance(label, QLabel):
        label.hide()
        label.setText("")


def field_error(widget: QWidget) -> str:
    """The error currently shown under ``widget`` ('' when none) — for tests."""
    label = getattr(widget, "_rf_error_label", None)
    if isinstance(label, QLabel) and not label.isHidden():
        return label.text()
    return ""


def _dot_icon() -> QIcon:
    pixmap = QPixmap(QSize(16, 16))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(ERROR_COLOR))
    painter.drawEllipse(3, 3, 10, 10)
    painter.end()
    return QIcon(pixmap)


def mark_tab_errors(tabs: QTabWidget, indexes: set[int]) -> None:
    """Put a red dot on the tabs with problems and clear it from the rest."""
    dot = _dot_icon() if indexes else QIcon()
    tabs.setIconSize(QSize(10, 10))
    for i in range(tabs.count()):
        tabs.setTabIcon(i, dot if i in indexes else QIcon())


def tabs_with_errors(tabs: QTabWidget) -> set[int]:
    return {i for i in range(tabs.count()) if not tabs.tabIcon(i).isNull()}


# -- dialogs --------------------------------------------------------------------------


def confirm_discard(parent: QWidget) -> bool:
    """Ask before throwing away edits. True = discard (patched to True in tests)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Discard changes?")
    box.setText("You have changes that aren't saved.")
    box.setInformativeText("Discard them, or keep editing?")
    discard = box.addButton("Discard changes", QMessageBox.ButtonRole.DestructiveRole)
    keep = box.addButton("Keep editing", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(keep)
    box.setEscapeButton(keep)
    box.exec()
    return box.clickedButton() is discard


def _settings() -> QSettings:
    return QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "ReportFlow", "ui")


def remember(key: str, value: object) -> None:
    """Keep a small per-user preference (e.g. the last test-email address)."""
    _settings().setValue(key, value)


def recall(key: str) -> object:
    """A preference kept with :func:`remember` (None when never set)."""
    return _settings().value(key)


def restore_geometry(widget: QWidget, key: str) -> bool:
    data = _settings().value(f"geometry/{key}")
    if isinstance(data, QByteArray) and not data.isEmpty():
        return bool(widget.restoreGeometry(data))
    return False


def save_geometry(widget: QWidget, key: str) -> None:
    _settings().setValue(f"geometry/{key}", widget.saveGeometry())


class FormDialog(QDialog):
    """An editing dialog that never closes on Enter and never loses edits silently.

    Subclasses build their widgets, then call :meth:`finish_form`, and override
    :meth:`dirty_key` (what would be saved, as a string) and :meth:`save_form`.
    """

    def __init__(self, parent: QWidget | None = None, *, settings_key: str) -> None:
        super().__init__(parent)
        self._settings_key = settings_key
        self._baseline: str | None = None
        self._save_button: QPushButton | None = None
        self.save_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Save), self)
        self.save_shortcut.activated.connect(self._shortcut_save)
        self.help_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F1), self)
        self.help_shortcut.activated.connect(self.open_help)

    def finish_form(self, save_button: QPushButton | None = None) -> None:
        """Call at the end of ``__init__``: buttons, remembered size, and the clean state."""
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        if save_button is not None:
            self._save_button = save_button
            save_button.setToolTip("Save (Ctrl+S)")
        restore_geometry(self, self._settings_key)
        self.mark_clean()

    # -- overridables --
    def dirty_key(self) -> str:
        return ""

    def save_form(self) -> None:
        self.accept()

    def help_anchor(self) -> str | None:
        """The Help section F1 opens (e.g. for the current tab); None = the top."""
        return None

    # -- state --
    def mark_clean(self) -> None:
        self._baseline = self._safe_key()

    def is_dirty(self) -> bool:
        return self._baseline is not None and self._safe_key() != self._baseline

    def _safe_key(self) -> str:
        try:
            return self.dirty_key()
        except Exception as exc:  # noqa: BLE001 — a half-typed form must still compare
            return f"<unsaved: {exc!r}>"

    # -- behaviour --
    def _shortcut_save(self) -> None:
        if self._save_button is None or self._save_button.isEnabled():
            self.save_form()

    def open_help(self) -> None:
        from reportflow.ui.windows.help_dialog import HelpDialog

        HelpDialog(self, anchor=self.help_anchor()).exec()

    def keyPressEvent(self, event: Any) -> None:
        # Enter in a single-line field must never press Save (or anything else).
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def reject(self) -> None:
        # Cancel, Esc and the title-bar × all land here.
        if self.isVisible() and self.is_dirty() and not confirm_discard(self):
            return
        super().reject()

    def done(self, result: int) -> None:
        if self.isVisible():
            save_geometry(self, self._settings_key)
        super().done(result)
