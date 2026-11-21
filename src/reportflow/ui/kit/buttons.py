"""Buttons: one class per kind, so every button in the app looks and behaves the same.

The look lives in ``style.py`` (``QPushButton[variant="…"]``); these classes only set the
variant and the behaviour every button shares — a pointing cursor, an accessible name, and
never being a dialog's "default" button (Enter must not press Save; see ``FormDialog``).

=============  ===========================================================================
variant        use
=============  ===========================================================================
``secondary``  the ordinary button (the default)
``primary``    the one main action of a window or card (Save, + New Job, Update now)
``quiet``      a low-key action that shouldn't compete (Remove on a schedule card)
``danger``     a destructive action; turns red on hover (Delete group)
``dashed``     "add another" (+ Add time, + Add schedule)
=============  ===========================================================================
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QAbstractButton, QPushButton, QToolButton, QWidget

VARIANTS = ("secondary", "primary", "quiet", "danger", "quiet-danger", "dashed", "segment")
ICON_VARIANTS = ("icon", "icon-danger", "close", "dismiss", "tool")


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_variant(button: QAbstractButton, variant: str) -> None:
    """Give any button (e.g. one a QDialogButtonBox made) a kit variant."""
    button.setProperty("variant", variant)
    _repolish(button)


class Button(QPushButton):
    """A push button with a kit ``variant`` (see the module table).

    ``small`` makes it compact (inline row actions); ``pill`` rounds it fully (the schedule's
    time pills row)."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        variant: str = "secondary",
        icon: QIcon | None = None,
        tooltip: str = "",
        small: bool = False,
        pill: bool = False,
    ) -> None:
        super().__init__(text, parent)
        if variant not in VARIANTS:
            raise ValueError(f"unknown button variant {variant!r}")
        self.setProperty("variant", variant)
        if small:
            self.setProperty("small", True)
        if pill:
            self.setProperty("pill", True)
        if icon is not None:
            self.setIcon(icon)
            self.setIconSize(QSize(16, 16))
        if tooltip:
            self.setToolTip(tooltip)
        self.setAccessibleName(text.replace("&&", "&").replace("…", "").strip() or tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoDefault(False)

    def set_variant(self, variant: str) -> None:
        set_variant(self, variant)


class SegmentButton(Button):
    """One checkable part of a segmented control (Mon Tue Wed…, Testing | Production).

    Use :func:`segmented` to join several into one control."""

    def __init__(self, text: str, parent: QWidget | None = None, *, tooltip: str = "") -> None:
        super().__init__(text, parent, variant="segment", tooltip=tooltip)
        self.setCheckable(True)
        self.setProperty("segment", True)


def segmented(buttons: list[SegmentButton]) -> None:
    """Square the inner corners of adjacent segment buttons so they read as one control."""
    for i, button in enumerate(buttons):
        if len(buttons) == 1:
            pos = "only"
        elif i == 0:
            pos = "first"
        elif i == len(buttons) - 1:
            pos = "last"
        else:
            pos = "mid"
        button.setProperty("segmentPos", pos)
        _repolish(button)


class IconButton(QToolButton):
    """A small square button showing only an icon (or a glyph such as ×).

    variants: ``icon`` (quiet, outlined on hover), ``icon-danger`` (turns red on hover),
    ``close`` (a round × that removes something), ``dismiss`` (a round × that only closes),
    ``tool`` (a framed toolbar button, e.g. the job card's ⋯)."""

    def __init__(
        self,
        icon: QIcon | str | None,
        tooltip: str,
        parent: QWidget | None = None,
        *,
        variant: str = "icon",
        size: int = 28,
        icon_size: int = 16,
        focusable: bool = True,
    ) -> None:
        super().__init__(parent)
        if variant not in ICON_VARIANTS:
            raise ValueError(f"unknown icon-button variant {variant!r}")
        self.setProperty("variant", variant)
        if isinstance(icon, QIcon):
            self.setIcon(icon)
            self.setIconSize(QSize(icon_size, icon_size))
        elif isinstance(icon, str):
            self.setText(icon)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        if size:
            self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if not focusable:
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
