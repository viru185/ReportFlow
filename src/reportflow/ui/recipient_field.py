"""Recipient boxes: addresses and email groups as chips, with autocomplete.

Type to search the email groups (Settings → Email groups) and every address the app already
knows; Enter, Tab, ``,`` or ``;`` adds what you typed, and a pasted list is split. Each chip
has its own ×, which is the only thing that removes it, and Backspace in the empty box removes
the last chip. Text that is neither a known group nor an address stays in the box, outlined
red, so nothing is silently dropped. Enter never reaches the dialog (it used to press Save).

A :class:`RecipientSet` ties the To/Cc/Bcc boxes of one recipient list together, because each
person is emailed once (``core.email.recipients.resolve``):

- adding someone already in the list — directly or through a group — is refused, with a note
  saying where they already are, and their chip flashes;
- adding a group removes the separately added people it now covers (with Undo), except
  people in a HIGHER box (To above Cc above Bcc), who stay where they are;
- suggestions only offer what isn't in the list yet.

The rules apply to what the user adds; loading a saved job (``set_value``) never changes it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QWidget,
    QWidgetItem,
)

from reportflow.ui.assets import asset_icon
from reportflow.ui.feedback import InlineNotice, flash

GROUP_PREFIX = "👥 "
# Light structural check; the service validates addresses fully when the job is saved.
_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
_SEPARATORS = re.compile(r"[,;\n]")

EMAIL = "email"
GROUP = "group"


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


class _Chip(QFrame):
    """One recipient: its text, and a × that is the only way to remove it."""

    remove_requested = Signal()

    HEIGHT = 24  # fits the 30 px text line, so a box with chips is as tall as an empty one

    def __init__(self, text: str, value: str, *, group: bool) -> None:
        super().__init__()
        self.setProperty("recipientChip", True)
        self.setFixedHeight(self.HEIGHT)
        row = QHBoxLayout(self)
        row.setContentsMargins(8 if group else 10, 0, 3, 0)
        row.setSpacing(4)
        if group:
            self.setProperty("groupChip", True)
            icon = QLabel()
            icon.setObjectName("chipIcon")
            icon.setPixmap(asset_icon("group.svg").pixmap(14, 14))
            row.addWidget(icon)
        self.label = QLabel(text)
        self.label.setObjectName("chipText")
        row.addWidget(self.label)
        self.close_button = QToolButton()
        self.close_button.setObjectName("chipRemove")
        self.close_button.setText("×")
        self.close_button.setFixedSize(18, 18)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setToolTip(f"Remove {value}")
        self.close_button.setAccessibleName(f"Remove {value}")
        self.close_button.clicked.connect(self.remove_requested)
        row.addWidget(self.close_button)

    def set_text(self, text: str, tooltip: str) -> None:
        self.label.setText(text)
        self.label.setToolTip(tooltip)
        self.setToolTip(tooltip)


@dataclass
class Verdict:
    """The answer to "may this be added?" from :class:`RecipientSet`."""

    accept: bool
    message: str = ""
    flash: list[tuple[RecipientField, str, str]] = field(default_factory=list)
    # (box, address) pairs a newly added group now covers — removed when it is added
    remove: list[tuple[RecipientField, str]] = field(default_factory=list)


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
        self._tokens: list[tuple[str, str]] = []  # (kind, value) in the order shown
        self._chips: dict[tuple[str, str], _Chip] = {}  # (kind, casefolded value) -> chip
        self._groups: dict[str, list[str]] = {}  # known groups: name -> members
        self._set: RecipientSet | None = None
        self.notice: InlineNotice | None = None  # where a lone field reports refusals
        self._help_tip = ""
        self._choices: list[str] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._flow = _FlowLayout(self)
        self._flow.setContentsMargins(4, 3, 4, 3)
        self.edit = QLineEdit()
        self.edit.setFrame(False)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setMinimumWidth(180)
        self.edit.installEventFilter(self)
        self.edit.editingFinished.connect(self.commit_pending)  # on focus-out
        self.edit.textEdited.connect(self._on_text_edited)
        self._flow.addWidget(self.edit)

        # Groups are listed by name with the people icon (the chips use the same one).
        self._model = QStandardItemModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.activated.connect(self._on_completed)
        popup = self._completer.popup()
        if popup is not None:
            popup.setObjectName("completerPopup")
            popup.setMinimumWidth(300)  # long addresses fit even when the box is narrow
        self.edit.setCompleter(self._completer)

    # -- public ------------------------------------------------------------------

    @property
    def allow_groups(self) -> bool:
        return self._allow_groups

    def set_suggestions(self, addresses: list[str], groups: dict[str, list[str]]) -> None:
        """For a field without a :class:`RecipientSet`: what autocomplete offers."""
        self.set_groups(groups)
        choices = [f"{GROUP_PREFIX}{name}" for name in groups] if self._allow_groups else []
        self.set_choices([*choices, *addresses])

    def set_groups(self, groups: dict[str, list[str]]) -> None:
        self._groups = dict(groups)
        for kind, value in self._tokens:
            if kind == GROUP:
                self._update_group_chip(value)

    def set_choices(self, choices: list[str]) -> None:
        """Addresses, and groups marked with :data:`GROUP_PREFIX`."""
        # Resetting the model closes an open popup, so only touch it when the list changed.
        if choices == self._choices:
            return
        self._choices = list(choices)
        self._model.clear()
        icon = asset_icon("group.svg")
        for choice in self._choices:
            if choice.startswith(GROUP_PREFIX):
                item = QStandardItem(icon, choice[len(GROUP_PREFIX) :])
                item.setToolTip("Email group")
            else:
                item = QStandardItem(choice)
            item.setEditable(False)
            self._model.appendRow(item)

    def choices(self) -> list[str]:
        return list(self._choices)

    def set_value(self, emails: list[str], groups: list[str] | None = None) -> None:
        """Show saved recipients as they are — the add rules never rewrite a saved job."""
        for kind, value in list(self._tokens):
            self._drop_chip(kind, value)
        self._tokens = []
        for name in groups or []:
            self._insert(GROUP, str(name).strip(), notify=False)
        for email in emails:
            self._insert(EMAIL, str(email).strip(), notify=False)
        self.edit.clear()
        self._set_invalid(False)
        self.changed.emit()

    def emails(self) -> list[str]:
        return [value for kind, value in self._tokens if kind == EMAIL]

    def groups(self) -> list[str]:
        return [value for kind, value in self._tokens if kind == GROUP]

    def has(self, kind: str, value: str) -> bool:
        return (kind, value.casefold()) in self._chips

    def is_empty(self) -> bool:
        return not self._tokens and not self.edit.text().strip()

    def chip(self, kind: str, value: str) -> _Chip | None:
        return self._chips.get((kind, value.casefold()))

    def commit_pending(self) -> str | None:
        """Turn the typed text into chips. Returns an error for text that is neither a known
        group nor an address (it stays in the box, outlined red), else None."""
        parts = [part.strip() for part in _SEPARATORS.split(self.edit.text()) if part.strip()]
        refused: list[str] = []
        bad = [part for part in parts if self._add_token(part, refused) == "unknown"]
        self.edit.setText(", ".join(bad))
        self._set_invalid(bool(bad))
        self._report(refused)
        if bad:
            what = "a known email group or an address" if self._allow_groups else "an address"
            return f"{', '.join(bad)} is not {what}."
        return None

    # -- adding ------------------------------------------------------------------

    def _classify(self, text: str) -> tuple[str, str] | None:
        text = text.strip()
        if text.startswith(GROUP_PREFIX.strip()):
            text = text[len(GROUP_PREFIX.strip()) :].strip()
        if self._allow_groups:
            for name in self._groups:
                if name.casefold() == text.casefold():
                    return GROUP, name
        if is_address(text):
            return EMAIL, text
        return None

    def _add_token(self, text: str, refused: list[str]) -> str:
        """Add what the user typed. Returns "added", "refused" (a duplicate — the reason is
        appended to ``refused``) or "unknown" (neither a group nor an address)."""
        found = self._classify(text)
        if found is None:
            return "unknown"
        kind, value = found
        verdict = self._vet(kind, value)
        if not verdict.accept:
            refused.append(verdict.message)
            for box, k, v in verdict.flash:
                chip = box.chip(k, v)
                if chip is not None:
                    flash(chip)
            return "refused"
        for box, address in verdict.remove:
            box._remove_token(EMAIL, address, notify=False)
        self._insert(kind, value)
        if not verdict.message:
            self._clear_notice()  # an old "already in …" note no longer applies
        if verdict.message:
            removed = verdict.remove

            def undo() -> None:
                self._remove_token(kind, value)
                for box, address in removed:
                    box._insert(EMAIL, address)

            self._notify(verdict.message, "info", ("Undo", undo) if removed else None)
        return "added"

    def _vet(self, kind: str, value: str) -> Verdict:
        if self._set is not None:
            return self._set.vet(self, kind, value)
        if self.has(kind, value):
            return Verdict(False, f"{value} is already added.", flash=[(self, kind, value)])
        return Verdict(True)

    def _insert(self, kind: str, value: str, *, notify: bool = True) -> None:
        if not value or self.has(kind, value):
            return
        self._tokens.append((kind, value))
        chip = _Chip(value, value, group=kind == GROUP)
        chip.remove_requested.connect(lambda k=kind, v=value: self._remove_token(k, v))
        self._chips[(kind, value.casefold())] = chip
        # Chips sit before the text box, in the order they were added.
        self._flow.insertWidget(self._flow.count() - 1, chip)
        if kind == GROUP:
            self._update_group_chip(value)
        else:
            chip.set_text(value, value)
        self.updateGeometry()
        if notify:
            self.changed.emit()

    def _update_group_chip(self, name: str) -> None:
        chip = self.chip(GROUP, name)
        if chip is None:
            return
        members = next(
            (m for known, m in self._groups.items() if known.casefold() == name.casefold()),
            None,
        )
        if members is None:
            chip.set_text(
                f"{name} (?)",
                f"Email group {name!r} doesn't exist any more — remove it.",
            )
        else:
            chip.set_text(
                f"{name} · {len(members)}",
                f"Email group {name}:\n" + "\n".join(members),
            )

    # -- removing ----------------------------------------------------------------

    def _remove_token(self, kind: str, value: str, *, notify: bool = True) -> None:
        key = value.casefold()
        before = len(self._tokens)
        self._tokens = [(k, v) for k, v in self._tokens if not (k == kind and v.casefold() == key)]
        if len(self._tokens) == before:
            return
        self._drop_chip(kind, value)
        self.updateGeometry()
        if notify:
            self.changed.emit()

    def _drop_chip(self, kind: str, value: str) -> None:
        chip = self._chips.pop((kind, value.casefold()), None)
        if chip is None:
            return
        self._flow.removeWidget(chip)
        # Hidden first: until deleteLater runs, a chip taken out of the layout would sit on
        # top of the field at its old place and swallow clicks.
        chip.hide()
        chip.deleteLater()

    def _remove_last(self) -> None:
        if self._tokens:
            kind, value = self._tokens[-1]
            self._remove_token(kind, value)

    # -- feedback ----------------------------------------------------------------

    def _notify(
        self,
        message: str,
        kind: str = "warning",
        action: tuple[str, Callable[[], None]] | None = None,
    ) -> None:
        notice = self._set.notice if self._set is not None else self.notice
        if notice is not None:
            notice.show_notice(message, kind, action=action)
        else:
            self.setToolTip(message)

    def _clear_notice(self) -> None:
        notice = self._set.notice if self._set is not None else self.notice
        if notice is not None:
            notice.clear_notice()

    def _report(self, refused: list[str]) -> None:
        if len(refused) == 1:
            self._notify(refused[0])
        elif refused:
            self._notify(f"{len(refused)} were skipped — already included. " + " ".join(refused))

    def _set_invalid(self, invalid: bool) -> None:
        if invalid and not self.property("invalid"):
            self._help_tip = self.toolTip()  # keep the field's own help for later
        self.setProperty("invalid", invalid)
        self.setToolTip(
            "Not a known email group or address — fix it, or remove it."
            if invalid
            else self._help_tip
        )
        self.style().unpolish(self)
        self.style().polish(self)

    # -- typing ------------------------------------------------------------------

    def _on_text_edited(self, text: str) -> None:
        if _SEPARATORS.search(text):
            # Everything before the last separator is complete; keep typing the rest.
            *done, rest = _SEPARATORS.split(text)
            refused: list[str] = []
            bad = [
                part.strip()
                for part in done
                if part.strip() and self._add_token(part, refused) == "unknown"
            ]
            self.edit.setText(", ".join([*bad, rest.strip()]) if bad else rest.lstrip())
            self._set_invalid(bool(bad))
            self._report(refused)
        elif self.property("invalid"):
            self._set_invalid(False)

    def _on_completed(self, text: str) -> None:
        refused: list[str] = []
        self._add_token(text, refused)
        self._report(refused)
        # QCompleter writes the chosen text into the box after this signal; clear it then.
        self.edit.clear()
        self.edit.setFocus()
        _clear_later(self.edit)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if watched is self.edit and event.type() == QEvent.Type.KeyPress:
            key = event.key()  # type: ignore[attr-defined]
            popup = self._completer.popup()
            popup_open = popup is not None and popup.isVisible()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not popup_open:
                # Enter adds what was typed — and never reaches the dialog's Save button.
                if self.edit.text().strip():
                    self.commit_pending()
                return True
            if key == Qt.Key.Key_Backspace and not self.edit.text():
                self._remove_last()
                return True
            if key == Qt.Key.Key_Tab and self.edit.text().strip() and not popup_open:
                self.commit_pending()
                return True
        return super().eventFilter(watched, event)


def _clear_later(edit: QLineEdit) -> None:
    from PySide6.QtCore import QTimer

    QTimer.singleShot(0, edit, edit.clear)


class RecipientSet(QObject):
    """The To/Cc/Bcc boxes of one recipient list (or one email group's members).

    ``fields`` is ordered by precedence — To first — like the sender's de-duplication."""

    def __init__(
        self,
        fields: dict[str, RecipientField],
        *,
        groups: dict[str, list[str]] | None = None,
        addresses: list[str] | None = None,
        notice: InlineNotice | None = None,
        single_name: str = "this list",
    ) -> None:
        super().__init__(next(iter(fields.values())))
        self.fields = dict(fields)
        self.notice = notice
        self._single_name = single_name
        self._groups: dict[str, list[str]] = {}
        self._addresses = list(addresses or [])
        for box in self.fields.values():
            box._set = self
            box.changed.connect(self.refresh_suggestions)
        self.set_groups(groups or {})

    # -- configuration --

    def set_groups(self, groups: dict[str, list[str]]) -> None:
        self._groups = dict(groups)
        for box in self.fields.values():
            box.set_groups(self._groups)
        self.refresh_suggestions()

    def set_addresses(self, addresses: list[str]) -> None:
        self._addresses = list(addresses)
        self.refresh_suggestions()

    # -- rules --

    def _members(self, name: str) -> set[str]:
        for known, members in self._groups.items():
            if known.casefold() == name.casefold():
                return {m.casefold() for m in members}
        return set()

    def _where(self, box: RecipientField) -> str:
        if len(self.fields) == 1:
            return self._single_name
        return next(name for name, f in self.fields.items() if f is box)

    def _rank(self, box: RecipientField) -> int:
        return list(self.fields.values()).index(box)

    def vet(self, target: RecipientField, kind: str, value: str) -> Verdict:
        key = value.casefold()
        boxes = list(self.fields.values())
        # Already in the list as this exact chip?
        for box in boxes:
            if box.has(kind, value):
                return Verdict(
                    False,
                    f"{value} is already in {self._where(box)}.",
                    flash=[(box, kind, value)],
                )
        if kind == EMAIL:
            for box in boxes:
                for name in box.groups():
                    if key in self._members(name):
                        return Verdict(
                            False,
                            f"{value} is already in the group {name} ({self._where(box)}).",
                            flash=[(box, GROUP, name)],
                        )
            return Verdict(True)
        # A group: people it covers that were added on their own.
        covered = self._members(value)
        removed: list[tuple[RecipientField, str]] = []
        kept: list[str] = []
        for box in boxes:
            for address in box.emails():
                if address.casefold() not in covered:
                    continue
                if self._rank(box) < self._rank(target):
                    kept.append(f"{address} stays in {self._where(box)}")
                else:
                    removed.append((box, address))
        parts = []
        if removed:
            names = ", ".join(address for _, address in removed)
            parts.append(f"Removed {names} — now covered by {value}.")
        if kept:
            parts.append("; ".join(kept) + ".")
        return Verdict(True, " ".join(parts), remove=removed)

    # -- suggestions --

    def refresh_suggestions(self) -> None:
        """Offer only what isn't in the list yet — directly or through a group."""
        used_groups = {g.casefold() for box in self.fields.values() for g in box.groups()}
        taken = {e.casefold() for box in self.fields.values() for e in box.emails()}
        for name in used_groups:
            taken |= self._members(name)
        addresses = [a for a in self._addresses if a.casefold() not in taken]
        group_choices = [
            f"{GROUP_PREFIX}{name}" for name in self._groups if name.casefold() not in used_groups
        ]
        for box in self.fields.values():
            box.set_choices([*(group_choices if box.allow_groups else []), *addresses])


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
