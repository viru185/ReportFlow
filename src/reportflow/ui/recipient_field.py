"""Recipient boxes: addresses and email groups as chips, with autocomplete.

Type to search the email groups (Settings → Email groups) and every address the app already
knows. While suggestions show, the first one is highlighted and Enter or Tab adds it (arrow
keys pick another); otherwise Enter, Tab, ``,`` or ``;`` adds what you typed, and a pasted
list is split. Each chip has its own ×, which is the only thing that removes it, and
Backspace in the empty box removes the last chip. Double-clicking a group's chip edits the
group. Text that is neither a known group nor an address stays in the box, outlined red, so
nothing is silently dropped. Enter never reaches the dialog (it used to press Save).

Picking a suggestion is handled here, not by QCompleter: Qt's own Enter handling also fired
``editingFinished`` and then completed a remembered row number — after the first add had
rebuilt the list, so one Enter added two people (0.13).

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
from typing import Any

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRect,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStyleOptionViewItem,
    QWidget,
)

from reportflow.ui.assets import asset_icon
from reportflow.ui.feedback import InlineNotice, flash
from reportflow.ui.kit import IconButton, PopupItemDelegate, styled_completer
from reportflow.ui.style import TEXT, TEXT_MUTED
from reportflow.ui.widgets import FlowLayout

GROUP_PREFIX = "👥 "
# Light structural check; the service validates addresses fully when the job is saved.
_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
_SEPARATORS = re.compile(r"[,;\n]")

EMAIL = "email"
GROUP = "group"


def is_address(text: str) -> bool:
    return bool(_EMAIL_RE.match(text.strip()))


class _Chip(QFrame):
    """One recipient: its text, and a × that is the only way to remove it. A group's chip
    asks to be edited when double-clicked."""

    remove_requested = Signal()
    edit_requested = Signal()

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
        self.close_button = IconButton(
            "×", f"Remove {value}", variant="close", size=18, focusable=False
        )
        self.close_button.setObjectName("chipRemove")
        self.close_button.clicked.connect(self.remove_requested)
        row.addWidget(self.close_button)

    def set_text(self, text: str, tooltip: str) -> None:
        self.label.setText(text)
        self.label.setToolTip(tooltip)
        self.setToolTip(tooltip)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.property("groupChip") and event.button() == Qt.MouseButton.LeftButton:
            self.edit_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


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
    group_edit_requested = Signal(str)  # a group chip was double-clicked: edit that group

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

        self._flow = FlowLayout(self)
        self._flow.setContentsMargins(4, 3, 4, 3)
        self.edit = QLineEdit()
        self.edit.setFrame(False)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setMinimumWidth(180)
        self.edit.textEdited.connect(self._on_text_edited)
        self._flow.addWidget(self.edit)

        # Groups are listed by name with the people icon (the chips use the same one).
        self._model = QStandardItemModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.activated.connect(self._on_completed)
        # Long addresses fit even when the box is narrow.
        self._popup = styled_completer(self._completer, min_width=300)
        self._popup.setItemDelegate(_SuggestionDelegate(self._popup, self._completer))
        self.edit.setCompleter(self._completer)
        # Installed after QCompleter's own filter, so this one sees keys first. Last in
        # __init__: the filter uses the popup, and the line edit gets events while it is laid out.
        self._popup.installEventFilter(self)
        self.edit.installEventFilter(self)  # Enter/Tab/Backspace, and commit on focus-out

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
                name = choice[len(GROUP_PREFIX) :]
                item = QStandardItem(icon, name)
                members = self._group_members(name)
                item.setData(len(members) if members is not None else -1, _COUNT_ROLE)
                item.setToolTip("Email group: " + ", ".join(members or []))
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
        self._add_chip(kind, value, position=len(self._tokens) - 1)
        self.updateGeometry()
        if notify:
            self.changed.emit()

    def _add_chip(self, kind: str, value: str, *, position: int) -> None:
        chip = _Chip(value, value, group=kind == GROUP)
        chip.remove_requested.connect(lambda k=kind, v=value: self._remove_token(k, v))
        if kind == GROUP:
            chip.edit_requested.connect(lambda v=value: self.group_edit_requested.emit(v))
        self._chips[(kind, value.casefold())] = chip
        # Chips sit before the text box, in token order.
        self._flow.insertWidget(position, chip)
        if kind == GROUP:
            self._update_group_chip(value)
        else:
            chip.set_text(value, value)

    def _group_members(self, name: str) -> list[str] | None:
        return next(
            (m for known, m in self._groups.items() if known.casefold() == name.casefold()),
            None,
        )

    def _update_group_chip(self, name: str) -> None:
        chip = self.chip(GROUP, name)
        if chip is None:
            return
        members = self._group_members(name)
        if members is None:
            chip.set_text(
                f"{name} (?)",
                f"Email group {name!r} doesn't exist any more — remove it, or double-click "
                "to create it again.",
            )
        else:
            chip.set_text(
                f"{name} · {len(members)}",
                f"Email group {name}:\n" + "\n".join(members) + "\n\nDouble-click to edit "
                "this group.",
            )

    def rename_group(self, old: str, new: str) -> None:
        """A group was renamed (Settings, or its chip's editor): show the new name in place."""
        key = old.casefold()
        for i, (kind, value) in enumerate(self._tokens):
            if kind == GROUP and value.casefold() == key:
                if new.casefold() != key and self.has(GROUP, new):
                    self._remove_token(GROUP, value, notify=False)  # already there
                else:
                    self._drop_chip(GROUP, value)
                    self._tokens[i] = (GROUP, new)
                    self._add_chip(GROUP, new, position=i)
                self.updateGeometry()
                self.changed.emit()
                return

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
        """A suggestion was clicked (keys are handled in :meth:`_pick_from_popup`)."""
        self._pick(text)
        # QCompleter writes the chosen text into the box after this signal; clear it then.
        _clear_later(self.edit)

    def _pick(self, text: str) -> None:
        refused: list[str] = []
        self._add_token(text, refused)
        self._report(refused)
        self.edit.clear()
        self._set_invalid(False)
        self.edit.setFocus()

    def _pick_from_popup(self) -> None:
        """Enter or Tab while suggestions show: add the highlighted one — or the first."""
        popup = self._popup
        index = popup.currentIndex()
        model = popup.model()
        if not index.isValid() and model is not None and model.rowCount() > 0:
            index = model.index(0, 0)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "") if index.isValid() else ""
        popup.hide()  # before adding: adding rebuilds the suggestion list
        if text:
            self._pick(text)
        else:
            self.commit_pending()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        kind = event.type()
        if watched is self._popup and kind == QEvent.Type.KeyPress:
            key = event.key()  # type: ignore[attr-defined]
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                self._pick_from_popup()
                return True  # QCompleter never sees it: no second add, no editingFinished
            return False
        if watched is self.edit and kind == QEvent.Type.FocusOut:
            reason = event.reason()  # type: ignore[attr-defined]
            if (
                reason
                not in (
                    Qt.FocusReason.PopupFocusReason,
                    Qt.FocusReason.ActiveWindowFocusReason,
                )
                and not self._popup.isVisible()
            ):
                self.commit_pending()
        if watched is self.edit and kind == QEvent.Type.KeyPress:
            key = event.key()  # type: ignore[attr-defined]
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                # Enter adds what was typed — and never reaches the dialog's Save button.
                if self.edit.text().strip():
                    self.commit_pending()
                return True
            if key == Qt.Key.Key_Backspace and not self.edit.text():
                self._remove_last()
                return True
            if key == Qt.Key.Key_Tab and self.edit.text().strip():
                self.commit_pending()
                return True
        return super().eventFilter(watched, event)


def _clear_later(edit: QLineEdit) -> None:
    QTimer.singleShot(0, edit, edit.clear)


_COUNT_ROLE = Qt.ItemDataRole.UserRole + 7  # a group suggestion's member count


class _SuggestionDelegate(PopupItemDelegate):
    """Suggestion rows: what you typed in bold, a group's size beside its name, and the first
    row highlighted while nothing is picked — it is what Enter adds."""

    def __init__(self, view: QAbstractItemView, completer: QCompleter) -> None:
        super().__init__(view)
        self._view = view
        self._completer = completer

    def is_highlighted(self, option: Any, index: QModelIndex | QPersistentModelIndex) -> bool:
        if super().is_highlighted(option, index):
            return True
        return index.row() == 0 and not self._view.currentIndex().isValid()

    def paint_text(
        self,
        painter: QPainter,
        opt: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
        rect: QRect,
        enabled: bool,
    ) -> None:
        text = opt.text
        count = index.data(_COUNT_ROLE)
        suffix = ""
        if isinstance(count, int) and count >= 0:
            suffix = f"  ·  {count} {'person' if count == 1 else 'people'}"
        metrics = opt.fontMetrics
        room = rect.width() - (metrics.horizontalAdvance(suffix) if suffix else 0)
        shown = metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, max(room, 40))
        needle = self._completer.completionPrefix().strip()
        at = shown.casefold().find(needle.casefold()) if needle else -1
        parts = (
            [
                (shown[:at], False),
                (shown[at : at + len(needle)], True),
                (shown[at + len(needle) :], False),
            ]
            if at >= 0
            else [(shown, False)]
        )
        x = rect.left()
        align = int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        painter.setPen(QColor(TEXT if enabled else TEXT_MUTED))
        for part, bold in parts:
            if not part:
                continue
            font = QFont(opt.font)
            font.setBold(bold)
            painter.setFont(font)
            width = QFontMetrics(font).horizontalAdvance(part)
            painter.drawText(QRect(x, rect.top(), width + 1, rect.height()), align, part)
            x += width
        if suffix:
            painter.setFont(opt.font)
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(QRect(x, rect.top(), rect.right() - x, rect.height()), align, suffix)


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
