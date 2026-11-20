"""A recipient box: addresses and email groups as removable chips, with autocomplete.

Type to search the email groups (Settings → Email groups) and every address the app already
knows; Enter, Tab, ``,`` or ``;`` adds what you typed, and a pasted list is split. Each chip
has its own ×, and Backspace in the empty box removes the last chip. Text that is neither a
known group nor an address stays in the box, outlined red, so nothing is silently dropped.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, QStringListModel, Qt, Signal
from PySide6.QtWidgets import (
    QCompleter,
    QFrame,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

GROUP_PREFIX = "👥 "
# Light structural check; the service validates addresses fully when the job is saved.
_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
_SEPARATORS = re.compile(r"[,;\n]")


def is_address(text: str) -> bool:
    return bool(_EMAIL_RE.match(text.strip()))


class _FlowLayout(QLayout):
    """Lays widgets out left to right and wraps to the next line (the Qt flow example)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 — Qt override
        self._items.append(item)

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
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and line_height > 0:
                x, y = area.x(), y + line_height + spacing
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + spacing
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


class RecipientField(QFrame):
    """Addresses + email groups for one of To / Cc / Bcc. Emits ``changed`` on any edit."""

    changed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        allow_groups: bool = True,
        placeholder: str = "Type a name or address…",
    ) -> None:
        super().__init__(parent)
        self.setProperty("recipientField", True)
        self._allow_groups = allow_groups
        self._emails: list[str] = []
        self._group_names: list[str] = []
        self._groups: dict[str, list[str]] = {}  # known groups: name -> members
        self._chips: list[QPushButton] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._flow = _FlowLayout(self)
        self._flow.setContentsMargins(4, 3, 4, 3)
        self.edit = QLineEdit()
        self.edit.setFrame(False)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setMinimumWidth(180)
        self.edit.installEventFilter(self)
        self.edit.editingFinished.connect(self.commit_pending)
        self.edit.textEdited.connect(self._on_text_edited)
        self._flow.addWidget(self.edit)

        self._model = QStringListModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.activated.connect(self._on_completed)
        self.edit.setCompleter(self._completer)

    # -- public ------------------------------------------------------------------

    def set_suggestions(self, addresses: list[str], groups: dict[str, list[str]]) -> None:
        """What autocomplete offers: groups first (marked 👥), then known addresses."""
        self._groups = dict(groups)
        choices = [f"{GROUP_PREFIX}{name}" for name in groups] if self._allow_groups else []
        self._model.setStringList([*choices, *addresses])
        self._render()  # group chips show member counts from the new map

    def set_value(self, emails: list[str], groups: list[str] | None = None) -> None:
        self._emails = []
        self._group_names = []
        for email in emails:
            self._append_email(str(email))
        for name in groups or []:
            self._append_group(str(name))
        self.edit.clear()
        self._set_invalid(False)
        self._render()

    def emails(self) -> list[str]:
        return list(self._emails)

    def groups(self) -> list[str]:
        return list(self._group_names)

    def is_empty(self) -> bool:
        return not self._emails and not self._group_names and not self.edit.text().strip()

    def commit_pending(self) -> str | None:
        """Turn the typed text into chips. Returns an error for text that is neither a known
        group nor an address (it stays in the box, outlined red), else None."""
        bad = [part.strip() for part in _SEPARATORS.split(self.edit.text()) if part.strip()]
        bad = [part for part in bad if not self._add_token(part)]
        self.edit.setText(", ".join(bad))
        self._set_invalid(bool(bad))
        self._render()
        if bad:
            what = "a known email group or an address" if self._allow_groups else "an address"
            return f"{', '.join(bad)} is not {what}."
        return None

    # -- behaviour ---------------------------------------------------------------

    def _add_token(self, text: str) -> bool:
        text = text.strip()
        if text.startswith(GROUP_PREFIX.strip()):
            text = text[len(GROUP_PREFIX.strip()) :].strip()
        if self._allow_groups:
            for name in self._groups:
                if name.casefold() == text.casefold():
                    self._append_group(name)
                    return True
        if is_address(text):
            self._append_email(text)
            return True
        return False

    def _append_email(self, email: str) -> None:
        email = email.strip()
        if email and email.casefold() not in {e.casefold() for e in self._emails}:
            self._emails.append(email)

    def _append_group(self, name: str) -> None:
        name = name.strip()
        if name and name.casefold() not in {g.casefold() for g in self._group_names}:
            self._group_names.append(name)

    def _on_text_edited(self, text: str) -> None:
        if _SEPARATORS.search(text):
            # Everything before the last separator is complete; keep typing the rest.
            *done, rest = _SEPARATORS.split(text)
            bad = [part.strip() for part in done if part.strip() and not self._add_token(part)]
            self.edit.setText(", ".join([*bad, rest.strip()]) if bad else rest.lstrip())
            self._set_invalid(bool(bad))
            self._render()
        elif self.property("invalid"):
            self._set_invalid(False)

    def _on_completed(self, text: str) -> None:
        if self._add_token(text):
            self._render()
        # QCompleter writes the chosen text into the box after this signal; clear it then.
        self.edit.clear()
        self.edit.setFocus()
        _clear_later(self.edit)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.edit and event.type() == QEvent.Type.KeyPress:
            key = event.key()  # type: ignore[attr-defined]
            popup = self._completer.popup()
            popup_open = popup is not None and popup.isVisible()
            if key == Qt.Key.Key_Backspace and not self.edit.text():
                self._remove_last()
                return True
            if key == Qt.Key.Key_Tab and self.edit.text().strip() and not popup_open:
                self.commit_pending()
                return True
        return super().eventFilter(watched, event)

    def _remove_last(self) -> None:
        if self._group_names:
            self._group_names.pop()
        elif self._emails:
            self._emails.pop()
        else:
            return
        self._render()

    def _remove(self, kind: str, value: str) -> None:
        if kind == "group":
            self._group_names = [g for g in self._group_names if g != value]
        else:
            self._emails = [e for e in self._emails if e != value]
        self._render()

    def _set_invalid(self, invalid: bool) -> None:
        self.setProperty("invalid", invalid)
        self.setToolTip(
            "Not a known email group or address — fix it, or remove it." if invalid else ""
        )
        self.style().unpolish(self)
        self.style().polish(self)

    def _render(self) -> None:
        for chip in self._chips:
            self._flow.removeWidget(chip)
            # Hidden first: until deleteLater runs, an unparented-from-layout chip would sit
            # on top of the field at a default size and swallow clicks.
            chip.hide()
            chip.deleteLater()
        self._chips = []
        self._flow.removeWidget(self.edit)
        for name in self._group_names:
            members = self._groups.get(name)
            for known in self._groups:
                if known.casefold() == name.casefold():
                    members = self._groups[known]
            count = str(len(members)) if members is not None else "?"
            chip = self._chip(f"{GROUP_PREFIX}{name} ({count})", "group", name)
            chip.setProperty("groupChip", True)
            chip.setToolTip(
                f"Email group {name}:\n" + "\n".join(members)
                if members is not None
                else f"Email group {name!r} doesn't exist any more — remove it."
            )
        for email in self._emails:
            self._chip(email, "email", email)
        self._flow.addWidget(self.edit)
        self.updateGeometry()
        self.changed.emit()

    def _chip(self, text: str, kind: str, value: str) -> QPushButton:
        chip = QPushButton(f"{text}  ×")
        chip.setProperty("recipientChip", True)
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.setToolTip(f"Remove {value}")
        chip.setAccessibleName(f"Remove {value}")
        chip.clicked.connect(lambda *_: self._remove(kind, value))
        self._flow.addWidget(chip)
        self._chips.append(chip)
        return chip


def _clear_later(edit: QLineEdit) -> None:
    from PySide6.QtCore import QTimer

    QTimer.singleShot(0, edit.clear)


def header_recipients(
    to: RecipientField, cc: RecipientField, groups: dict[str, list[str]]
) -> dict[str, list[str]]:
    """To and Cc as the email shows them: groups expanded, each address once, To first —
    the same rule the sender applies (``core.email.recipients.resolve``)."""
    by_name = {name.casefold(): members for name, members in groups.items()}
    seen: set[str] = set()
    result: dict[str, list[str]] = {}
    for key, box in (("to", to), ("cc", cc)):
        expanded = [m for g in box.groups() for m in by_name.get(g.casefold(), [])]
        result[key] = []
        for address in [*box.emails(), *expanded]:
            if address.casefold() not in seen:
                seen.add(address.casefold())
                result[key].append(address)
    return result


def unique_addresses(fields: list[RecipientField], groups: dict[str, list[str]]) -> list[str]:
    """Every distinct address the fields reach, groups expanded (case-insensitive)."""
    by_name = {name.casefold(): members for name, members in groups.items()}
    seen: dict[str, str] = {}
    for f in fields:
        expanded = [m for g in f.groups() for m in by_name.get(g.casefold(), [])]
        for address in [*f.emails(), *expanded]:
            seen.setdefault(address.casefold(), address)
    return list(seen.values())
