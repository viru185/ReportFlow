"""Recipient boxes: addresses and email groups as chips, with autocomplete.

Type to search the email groups (Settings → Email groups) and every address the app already
knows. While suggestions show, the first one is highlighted and Enter or Tab adds it (arrow
keys pick another); otherwise Enter, Tab, ``,`` or ``;`` adds what you typed, and a pasted
list is split. Each chip has its own ×, which is the only click that removes it, and
Backspace in the empty box removes the last chip. Text that is neither a known group nor an
address stays in the box, outlined red, so nothing is silently dropped. Enter never reaches
the dialog (it used to press Save).

The order of the chips is the order the email lists people in (0.15 — corporate readers care
who is named first), so chips can be arranged:

- drag a chip to another place, or into another box of the same list (To → Cc); an accent
  caret shows where it lands;
- double-click an address (or F2 / Enter on it, or "Edit address" in its menu) to edit it in
  place — Enter or clicking away saves, Esc cancels, emptying it removes it. Double-clicking
  a group's chip edits the group;
- right-click a chip: Edit, Copy, Move to To / Cc / Bcc, Remove;
- keyboard: ← in the empty box selects the last chip; ←/→ walk the chips, Alt+←/→ move the
  selected one, Delete removes it, Esc goes back to typing.

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

Moving or editing a chip follows the same rules. They apply to what the user does; loading a
saved job (``set_entries``) never changes it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import (
    QByteArray,
    QEvent,
    QMimeData,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRect,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCompleter,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStyleOptionViewItem,
    QWidget,
)

from reportflow.ui.assets import asset_icon
from reportflow.ui.feedback import InlineNotice, flash, repolish
from reportflow.ui.kit import IconButton, Menu, PopupItemDelegate, styled_completer
from reportflow.ui.style import TEXT, TEXT_MUTED
from reportflow.ui.widgets import FlowLayout

GROUP_PREFIX = "👥 "
# Light structural check; the service validates addresses fully when the job is saved.
_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
_SEPARATORS = re.compile(r"[,;\n]")

EMAIL = "email"
GROUP = "group"

CHIP_MIME = "application/x-reportflow-recipient"


def is_address(text: str) -> bool:
    return bool(_EMAIL_RE.match(text.strip()))


class _Chip(QFrame):
    """One recipient: its text, and a × that removes it. The box it sits in handles the
    rest (drag, double-click, menu, keys) through an event filter."""

    remove_requested = Signal()

    HEIGHT = 24  # fits the 30 px text line, so a box with chips is as tall as an empty one

    def __init__(self, text: str, value: str, *, group: bool) -> None:
        super().__init__()
        self.kind = GROUP if group else EMAIL
        self.value = value
        self.setProperty("recipientChip", True)
        self.setFixedHeight(self.HEIGHT)
        # Click selects a chip (focus ring); it is not a Tab stop — ← from the box gets here.
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
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
        self.setAccessibleName(text)

    def set_selected(self, selected: bool) -> None:
        """The keyboard is on this chip: solid accent with white text (a group chip is
        blue too, so a ring alone would read as "group")."""
        if bool(self.property("selected")) == selected:
            return
        self.setProperty("selected", selected)
        # A property on the chip restyles its text only once the children are repolished.
        for widget in (self, self.label, self.close_button):
            repolish(widget)


class _ChipEditor(QLineEdit):
    """An address chip being edited: the same pill shape, now a text box that grows with
    the text. The box handles its keys (Enter saves, Esc cancels)."""

    def __init__(self, text: str, max_width: int) -> None:
        super().__init__(text)
        self.setProperty("chipEditor", True)
        self.setFixedHeight(_Chip.HEIGHT)
        self.setAcceptDrops(False)
        self._max_width = max_width
        self.textChanged.connect(self._fit)
        self._fit()
        self.selectAll()

    def _fit(self) -> None:
        width = self.fontMetrics().horizontalAdvance(self.text() or " ") + 30
        self.setFixedWidth(max(140, min(width, self._max_width)))


@dataclass
class _DragState:
    """The chip being dragged. Qt hands a drop handler only MIME data, so the box it came
    from is kept here; ``target`` is where it was dropped (applied after the drag ends)."""

    source: RecipientField | None = None
    kind: str = ""
    value: str = ""
    target: tuple[RecipientField, int] | None = None


_drag = _DragState()


@dataclass
class Verdict:
    """The answer to "may this be added?" from :class:`RecipientSet`."""

    accept: bool
    message: str = ""
    flash: list[tuple[RecipientField, str, str]] = field(default_factory=list)
    # (box, address) pairs a newly added group now covers — removed when it is added
    remove: list[tuple[RecipientField, str]] = field(default_factory=list)


# A chip a rule check should look past: the one being moved or edited.
Ignore = tuple["RecipientField", str, str] | None


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
        self._press: tuple[_Chip, QPoint] | None = None  # a chip pressed: maybe a drag
        self._editor: _ChipEditor | None = None
        self._editing: tuple[str, str] | None = None  # (kind, value) of the chip in the editor
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setAcceptDrops(True)

        self._flow = FlowLayout(self)
        self._flow.setContentsMargins(4, 3, 4, 3)
        self.edit = QLineEdit()
        self.edit.setFrame(False)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setMinimumWidth(180)
        # Drops go to the box (a chip being moved), not into the text.
        self.edit.setAcceptDrops(False)
        self.edit.textEdited.connect(self._on_text_edited)
        self._flow.addWidget(self.edit)

        # Where a dragged chip will land: a thin accent bar between chips (not in the layout).
        self._caret = QFrame(self)
        self._caret.setObjectName("chipDropCaret")
        self._caret.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._caret.hide()

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
        self.edit.installEventFilter(self)  # Enter/Tab/Backspace/←, and commit on focus-out

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
        """Addresses (and groups) — for boxes that hold only addresses, like a group's
        members. A job's To/Cc/Bcc keeps its order with :meth:`set_entries`."""
        self.set_entries([*({"group": g} for g in groups or []), *emails])

    def set_entries(self, entries: list[str | dict[str, str]]) -> None:
        """Show saved recipients as they are, in their order — an address is a string, a
        group ``{"group": name}``. The add rules never rewrite a saved job."""
        self._close_editor()
        for kind, value in list(self._tokens):
            self._drop_chip(kind, value)
        self._tokens = []
        for entry in entries:
            if isinstance(entry, dict):
                self._insert(GROUP, str(entry.get("group") or "").strip(), notify=False)
            else:
                self._insert(EMAIL, str(entry).strip(), notify=False)
        self.edit.clear()
        self._set_invalid(False)
        self.changed.emit()

    def entries(self) -> list[str | dict[str, str]]:
        """Everything in the box, in the order shown (and sent)."""
        return [value if kind == EMAIL else {"group": value} for kind, value in self._tokens]

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

    def chips(self) -> list[_Chip]:
        """The chips in the order shown."""
        return [c for kind, value in self._tokens if (c := self.chip(kind, value)) is not None]

    def commit_pending(self) -> str | None:
        """Finish an edit in progress, and turn the typed text into chips. Returns an error
        for text that is neither a known group nor an address (it stays, outlined red)."""
        problem = self._finish_edit(save=True)
        if problem:
            return problem
        return self._commit_typed()

    def _commit_typed(self) -> str | None:
        """Turn what was typed in the box into chips (Enter, Tab, leaving the box). An edit
        of a chip has its own keys and focus handling, so it isn't touched here."""
        parts = [part.strip() for part in _SEPARATORS.split(self.edit.text()) if part.strip()]
        refused: list[str] = []
        bad = [part for part in parts if self._add_token(part, refused) == "unknown"]
        self.edit.setText(", ".join(bad))
        self._set_invalid(bool(bad))
        self._report(refused)
        if bad:
            return f"{', '.join(bad)} is not {self._what()}."
        return None

    def _what(self) -> str:
        return "a known email group or an address" if self._allow_groups else "an address"

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
            _flash_all(verdict)
            return "refused"
        removed = _take_covered(verdict)
        self._insert(kind, value)
        self._after_rules(verdict, removed, undo=lambda: self._remove_token(kind, value))
        return "added"

    def _after_rules(
        self,
        verdict: Verdict,
        removed: list[tuple[RecipientField, str, int]],
        *,
        undo: Callable[[], None],
    ) -> None:
        """Tell the user what the rules did (with Undo when people were taken out)."""
        if not verdict.message:
            self._clear_notice()  # an old "already in …" note no longer applies
            return

        def undo_all() -> None:
            undo()
            for box, address, index in removed:
                box._insert(EMAIL, address, index=index)

        self._notify(verdict.message, "info", ("Undo", undo_all) if removed else None)

    def _vet(self, kind: str, value: str, *, ignore: Ignore = None) -> Verdict:
        if self._set is not None:
            return self._set.vet(self, kind, value, ignore=ignore)
        if self.has(kind, value) and not _ignored(ignore, self, kind, value):
            return Verdict(False, f"{value} is already added.", flash=[(self, kind, value)])
        return Verdict(True)

    def _insert(
        self, kind: str, value: str, *, notify: bool = True, index: int | None = None
    ) -> None:
        if not value or self.has(kind, value):
            return
        index = len(self._tokens) if index is None else max(0, min(index, len(self._tokens)))
        self._tokens.insert(index, (kind, value))
        self._add_chip(kind, value, position=index)
        self.updateGeometry()
        if notify:
            self.changed.emit()

    def _add_chip(self, kind: str, value: str, *, position: int) -> None:
        chip = _Chip(value, value, group=kind == GROUP)
        chip.remove_requested.connect(lambda k=kind, v=value: self._remove_token(k, v))
        chip.installEventFilter(self)  # drag, double-click, menu, keys
        self._chips[(kind, value.casefold())] = chip
        # Chips sit before the text box, in token order.
        self._flow.insertWidget(position, chip)
        if kind == GROUP:
            self._update_group_chip(value)
        else:
            chip.set_text(
                value, f"{value}\n\nDouble-click to edit · drag to move · right-click for more"
            )

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
                "this group · drag to move.",
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
        if self._editing is not None and self._editing[0] == kind:
            if self._editing[1].casefold() == key:
                self._close_editor()
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

    # -- arranging -----------------------------------------------------------------

    def index_of(self, kind: str, value: str) -> int:
        key = value.casefold()
        return next(
            (i for i, (k, v) in enumerate(self._tokens) if k == kind and v.casefold() == key),
            -1,
        )

    def move_entry(self, kind: str, value: str, index: int) -> bool:
        """Move a chip within this box. ``index`` is where it goes in the list as it is now
        (the caret's place: 0 = first, len = last), so its own place and the one after it
        change nothing."""
        old = self.index_of(kind, value)
        if old < 0:
            return False
        new = index - 1 if index > old else index
        new = max(0, min(new, len(self._tokens) - 1))
        if new == old:
            return False
        self._tokens.insert(new, self._tokens.pop(old))
        chip = self.chip(kind, value)
        if chip is not None:
            self._flow.removeWidget(chip)
            self._flow.insertWidget(new, chip)
            chip.show()
        self.updateGeometry()
        self.changed.emit()
        return True

    def move_to(
        self, target: RecipientField, kind: str, value: str, index: int | None = None
    ) -> bool:
        """Move a chip into another box of the same list (To → Cc …), at ``index`` there
        (None: last). The add rules apply: a refused move changes nothing and says why."""
        if target is self:
            return self.move_entry(kind, value, len(self._tokens) if index is None else index)
        if kind == GROUP and not target.allow_groups:
            return False
        old = self.index_of(kind, value)
        if old < 0:
            return False
        # Where it lands: before the chip the caret was in front of (rules may remove others).
        anchors = target._tokens[index:] if index is not None else []
        verdict = target._vet(kind, value, ignore=(self, kind, value))
        if not verdict.accept:
            target._notify(verdict.message)
            _flash_all(verdict)
            return False
        self._remove_token(kind, value, notify=False)
        removed = _take_covered(verdict)
        at = next(
            (i for i, token in enumerate(target._tokens) if token in anchors),
            len(target._tokens),
        )
        target._insert(kind, value, notify=False, index=at)
        self.changed.emit()
        target.changed.emit()
        moved = target.chip(kind, value)
        if moved is not None:
            moved.setFocus(Qt.FocusReason.OtherFocusReason)
            flash(moved, times=1)

        def undo() -> None:
            target._remove_token(kind, value)
            self._insert(kind, value, index=old)

        target._after_rules(verdict, removed, undo=undo)
        return True

    def _boxes(self) -> dict[str, RecipientField]:
        return self._set.fields if self._set is not None else {"": self}

    def _neighbour_box_names(self, kind: str) -> list[tuple[str, RecipientField]]:
        """The other boxes of this list a chip of ``kind`` can move to."""
        return [
            (name, box)
            for name, box in self._boxes().items()
            if box is not self and (kind != GROUP or box.allow_groups)
        ]

    # -- editing in place ----------------------------------------------------------

    def begin_edit(self, kind: str, value: str) -> _ChipEditor | None:
        """Turn an address chip back into text, in the same place (double-click, F2)."""
        if kind != EMAIL:
            return None
        chip = self.chip(kind, value)
        if chip is None:
            return None
        if self._finish_edit(save=True):
            return None  # another edit can't be saved yet: it stays open, outlined red
        index = self.index_of(kind, value)
        margins = self._flow.contentsMargins()
        room = max(160, self.width() - margins.left() - margins.right())
        editor = _ChipEditor(value, room)
        editor.installEventFilter(self)
        self._editor, self._editing = editor, (kind, value)
        self._flow.removeWidget(chip)
        self._flow.insertWidget(index, editor)
        editor.show()
        # Focus first, then hide the chip: a hidden focused chip would hand the keyboard to
        # the typing box for a moment, and leaving that box commits.
        editor.setFocus(Qt.FocusReason.OtherFocusReason)
        chip.hide()
        self.updateGeometry()
        return editor

    def _close_editor(self) -> tuple[str, str] | None:
        """Take the editor out and put its chip back where it was (if still there)."""
        editor, editing = self._editor, self._editing
        if editor is None or editing is None:
            return None
        self._editor = self._editing = None
        editor.removeEventFilter(self)
        self._flow.removeWidget(editor)
        editor.hide()
        editor.deleteLater()
        chip = self.chip(*editing)
        index = self.index_of(*editing)
        if chip is not None and index >= 0:
            self._flow.insertWidget(index, chip)
            chip.show()
        self.updateGeometry()
        return editing

    def _finish_edit(self, *, save: bool, refocus: bool = False) -> str | None:
        """Save (or cancel) an edit in progress. Returns why the text can't be saved — the
        editor then stays open, outlined red (and keeps the keyboard if ``refocus``: Enter
        was pressed, rather than a click elsewhere) — else None."""
        editor, editing = self._editor, self._editing
        if editor is None or editing is None:
            return None
        kind, value = editing
        parts = [p.strip() for p in _SEPARATORS.split(editor.text()) if p.strip()]
        if not save or parts == [value]:
            self._close_editor()
            return None
        if not parts:  # emptied: the person is removed, as if × were clicked
            self._close_editor()
            self._remove_token(kind, value)
            return None
        found = self._classify(parts[0])
        if found is None:
            return self._edit_problem(f"{parts[0]} is not {self._what()}.", refocus=refocus)
        new_kind, new_value = found
        verdict = self._vet(new_kind, new_value, ignore=(self, kind, value))
        if not verdict.accept:
            _flash_all(verdict)
            return self._edit_problem(verdict.message, refocus=refocus)
        index = self.index_of(kind, value)
        after = self._tokens[index + 1 :]  # it stays in front of these, whatever is removed
        self._close_editor()
        removed = _take_covered(verdict)
        self._remove_token(kind, value, notify=False)
        index = next(
            (i for i, token in enumerate(self._tokens) if token in after), len(self._tokens)
        )
        self._insert(new_kind, new_value, notify=False, index=index)
        refused: list[str] = []
        for extra in parts[1:]:  # a pasted list: the rest go after it
            self._add_token(extra, refused)
        self._report(refused)
        self.changed.emit()
        chip = self.chip(new_kind, new_value)
        if chip is not None and self.isVisible():
            chip.setFocus(Qt.FocusReason.OtherFocusReason)

        def undo() -> None:
            self._remove_token(new_kind, new_value)
            self._insert(kind, value, index=index)

        self._after_rules(verdict, removed, undo=undo)
        return None

    def _edit_problem(self, message: str, *, refocus: bool) -> str:
        if self._editor is not None:
            self._editor.setProperty("invalid", True)
            repolish(self._editor)
            if refocus:
                self._editor.setFocus(Qt.FocusReason.OtherFocusReason)
        self._notify(message)
        return message

    # -- dragging ------------------------------------------------------------------

    def _start_drag(self, chip: _Chip, hot_spot: QPoint) -> None:
        kind, value = chip.kind, chip.value
        _drag.source, _drag.kind, _drag.value, _drag.target = self, kind, value, None
        mime = QMimeData()
        mime.setData(CHIP_MIME, QByteArray(value.encode("utf-8")))
        drag = QDrag(chip)
        drag.setMimeData(mime)
        drag.setPixmap(_lifted(chip.grab()))
        drag.setHotSpot(hot_spot)
        ghost = QGraphicsOpacityEffect(chip)
        ghost.setOpacity(0.35)  # it stays in place, faded, until it lands
        chip.setGraphicsEffect(ghost)
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            chip.setGraphicsEffect(None)  # type: ignore[arg-type]
            target = _drag.target
            _drag.source, _drag.target = None, None
            for box in self._boxes().values():
                box._hide_drop_cue()
        if target is not None:
            # Applied after the drag loop ends: chips are only rebuilt from the main loop.
            box, index = target
            self.move_to(box, kind, value, index)

    def _accepts_drag(self) -> bool:
        source = _drag.source
        if source is None:
            return False
        if source is not self and (self._set is None or source._set is not self._set):
            return False  # Production and Test are separate lists
        return _drag.kind != GROUP or self._allow_groups

    def drop_index(self, pos: QPoint) -> int:
        """Where a chip dropped at ``pos`` (this box's coordinates) goes: the caret sits
        before the chip under the pointer's left half, after it on the right half."""
        chips = self.chips()
        if not chips:
            return 0
        rows: list[list[tuple[int, QRect]]] = []
        for i, chip in enumerate(chips):
            rect = chip.geometry()
            if rows and rows[-1][0][1].top() == rect.top():
                rows[-1].append((i, rect))
            else:
                rows.append([(i, rect)])
        gap = self._flow.spacing()
        for row in rows:
            top, bottom = row[0][1].top() - gap, row[0][1].bottom() + gap
            if pos.y() < top:
                return row[0][0]
            if pos.y() <= bottom:
                for i, rect in row:
                    if pos.x() < rect.center().x():
                        return i
                return row[-1][0] + 1
        return len(chips)

    def _show_drop_cue(self, index: int) -> None:
        self.setProperty("dropTarget", _drag.source is not self)
        repolish(self)
        chips = self.chips()
        source_index = self.index_of(_drag.kind, _drag.value) if _drag.source is self else -1
        if source_index >= 0 and index in (source_index, source_index + 1):
            self._caret.hide()  # dropping here changes nothing
            return
        gap = self._flow.spacing()
        if not chips:
            margins = self._flow.contentsMargins()
            x, top = margins.left(), self.edit.geometry().top() + 3
        elif index < len(chips):
            rect = chips[index].geometry()
            x, top = rect.left() - gap // 2 - 1, rect.top()
        else:
            rect = chips[-1].geometry()
            x, top = rect.right() + gap // 2, rect.top()
        self._caret.setGeometry(max(1, x), top, 2, _Chip.HEIGHT)
        self._caret.raise_()
        self._caret.show()

    def _hide_drop_cue(self) -> None:
        self._caret.hide()
        if self.property("dropTarget"):
            self.setProperty("dropTarget", False)
            repolish(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasFormat(CHIP_MIME) and self._accepts_drag():
            event.acceptProposedAction()
            self._show_drop_cue(self.drop_index(event.position().toPoint()))
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if event.mimeData().hasFormat(CHIP_MIME) and self._accepts_drag():
            event.acceptProposedAction()
            self._show_drop_cue(self.drop_index(event.position().toPoint()))
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self._hide_drop_cue()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._hide_drop_cue()
        if not (event.mimeData().hasFormat(CHIP_MIME) and self._accepts_drag()):
            event.ignore()
            return
        _drag.target = (self, self.drop_index(event.position().toPoint()))
        event.acceptProposedAction()

    # -- chip menu and keys --------------------------------------------------------

    def _chip_menu(self, chip: _Chip, at: QPoint) -> None:
        menu, actions = self.chip_menu(chip)
        chosen = menu.exec(at)
        # Run after the menu closes: an action may rebuild the chip the menu came from.
        for action, run in actions:
            if chosen is not None and action is chosen:
                run()

    def chip_menu(self, chip: _Chip) -> tuple[Menu, list[tuple[object, Callable[[], object]]]]:
        """A chip's right-click menu, and what each entry does."""
        kind, value = chip.kind, chip.value
        menu = Menu(self)
        actions: list[tuple[object, Callable[[], object]]] = []

        def add(icon: str | None, text: str, run: Callable[[], object]) -> Any:
            action = menu.addAction(asset_icon(icon), text) if icon else menu.addAction(text)
            actions.append((action, run))
            return action

        if kind == EMAIL:
            add("edit.svg", "Edit address", lambda: self.begin_edit(kind, value))
            add("copy.svg", "Copy address", lambda: _copy(value))
        else:
            add("edit.svg", "Edit group…", lambda: self.group_edit_requested.emit(value))
            members = self._group_members(value)
            copy = add("copy.svg", "Copy addresses", lambda: _copy("; ".join(members or [])))
            copy.setEnabled(bool(members))
        others = self._neighbour_box_names(kind)
        if others:
            menu.addSeparator()
            for name, box in others:
                add(None, f"Move to {name}", _bind(self.move_to, box, kind, value))
        menu.addSeparator()
        add("trash.svg", "Remove", lambda: self._remove_token(kind, value))
        return menu, actions

    def _chip_key(self, chip: _Chip, event: QKeyEvent) -> bool:
        key = event.key()
        alt = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
        chips = self.chips()
        i = chips.index(chip) if chip in chips else -1
        if i < 0:
            return False
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = -1 if key == Qt.Key.Key_Left else 1
            if alt:
                if self.move_entry(chip.kind, chip.value, i + (2 if step > 0 else -1)):
                    chip.setFocus(Qt.FocusReason.OtherFocusReason)
                return True
            if 0 <= i + step < len(chips):
                chips[i + step].setFocus(Qt.FocusReason.OtherFocusReason)
            elif step > 0:
                self._focus_typing(at_start=True)
            return True
        if key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            chips[0 if key == Qt.Key.Key_Home else -1].setFocus(Qt.FocusReason.OtherFocusReason)
            return True
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            after = chips[i + 1] if i + 1 < len(chips) else None
            before = chips[i - 1] if i > 0 else None
            self._remove_token(chip.kind, chip.value)
            target = after or before
            if target is not None:
                target.setFocus(Qt.FocusReason.OtherFocusReason)
            else:
                self._focus_typing()
            return True
        if key in (Qt.Key.Key_F2, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if chip.kind == EMAIL:
                self.begin_edit(chip.kind, chip.value)
            else:
                self.group_edit_requested.emit(chip.value)
            return True  # Enter never reaches the dialog's Save
        if key == Qt.Key.Key_Menu or (
            key == Qt.Key.Key_F10 and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self._chip_menu(chip, chip.mapToGlobal(QPoint(0, chip.height())))
            return True
        if key == Qt.Key.Key_Escape:
            self._focus_typing()
            return True  # Esc goes back to typing — it doesn't close the dialog
        text = event.text()
        if (
            text
            and text.isprintable()
            and not event.modifiers()
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        ):
            self._focus_typing()  # typing on a selected chip types into the box
            self.edit.insert(text)
            self._on_text_edited(self.edit.text())
            return True
        return False

    def _focus_typing(self, *, at_start: bool = False) -> None:
        self.edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self.edit.setCursorPosition(0 if at_start else len(self.edit.text()))

    def _chip_event(self, chip: _Chip, event: QEvent) -> bool:
        kind = event.type()
        if kind in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            chip.set_selected(kind == QEvent.Type.FocusIn)
            return False
        if kind == QEvent.Type.MouseButtonPress:
            mouse: QMouseEvent = event  # type: ignore[assignment]
            if mouse.button() == Qt.MouseButton.LeftButton:
                self._press = (chip, mouse.position().toPoint())
            return False
        if kind == QEvent.Type.MouseMove and self._press is not None:
            mouse = event  # type: ignore[assignment]
            pressed, start = self._press
            moved = (mouse.position().toPoint() - start).manhattanLength()
            if (
                pressed is chip
                and mouse.buttons() & Qt.MouseButton.LeftButton
                and moved >= QApplication.startDragDistance()
            ):
                self._press = None
                self._start_drag(chip, start)
                return True
            return False
        if kind == QEvent.Type.MouseButtonRelease:
            self._press = None
            return False
        if kind == QEvent.Type.MouseButtonDblClick:
            mouse = event  # type: ignore[assignment]
            if mouse.button() == Qt.MouseButton.LeftButton:
                if chip.kind == EMAIL:
                    self.begin_edit(chip.kind, chip.value)
                else:
                    self.group_edit_requested.emit(chip.value)
                return True
            return False
        if kind == QEvent.Type.ContextMenu:
            self._chip_menu(chip, event.globalPos())  # type: ignore[attr-defined]
            return True
        if kind == QEvent.Type.KeyPress:
            return self._chip_key(chip, event)  # type: ignore[arg-type]
        return False

    def _editor_event(self, event: QEvent) -> bool:
        kind = event.type()
        if kind == QEvent.Type.KeyPress:
            key = event.key()  # type: ignore[attr-defined]
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab):
                self._finish_edit(save=True, refocus=True)
                return True  # never reaches the dialog's Save
            if key == Qt.Key.Key_Escape:
                editing = self._close_editor()
                chip = self.chip(*editing) if editing else None
                if chip is not None:
                    chip.setFocus(Qt.FocusReason.OtherFocusReason)
                return True  # cancels the edit, not the dialog
            if self._editor is not None and self._editor.property("invalid"):
                self._editor.setProperty("invalid", False)
                repolish(self._editor)
            return False
        if kind == QEvent.Type.FocusOut:
            reason = event.reason()  # type: ignore[attr-defined]
            if reason not in (
                Qt.FocusReason.PopupFocusReason,
                Qt.FocusReason.ActiveWindowFocusReason,
            ):
                # Clicking away saves; text that can't be saved stays, outlined red.
                QTimer.singleShot(0, self, lambda: self._finish_edit(save=True))
        return False

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
            self._commit_typed()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if isinstance(watched, _Chip):
            return self._chip_event(watched, event)
        if watched is not None and watched is self._editor:
            return self._editor_event(event)
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
                self._commit_typed()
        if watched is self.edit and kind == QEvent.Type.KeyPress:
            key = event.key()  # type: ignore[attr-defined]
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                # Enter adds what was typed — and never reaches the dialog's Save button.
                if self.edit.text().strip():
                    self._commit_typed()
                return True
            if key == Qt.Key.Key_Backspace and not self.edit.text():
                self._remove_last()
                return True
            if key == Qt.Key.Key_Tab and self.edit.text().strip():
                self._commit_typed()
                return True
            if (
                key == Qt.Key.Key_Left
                and self.edit.cursorPosition() == 0
                and not self.edit.hasSelectedText()
                and self._tokens
            ):
                self.chips()[-1].setFocus(Qt.FocusReason.OtherFocusReason)  # select the last
                return True
        return super().eventFilter(watched, event)


def _ignored(ignore: Ignore, box: RecipientField, kind: str, value: str) -> bool:
    return (
        ignore is not None
        and ignore[0] is box
        and ignore[1] == kind
        and ignore[2].casefold() == value.casefold()
    )


def _flash_all(verdict: Verdict) -> None:
    for box, kind, value in verdict.flash:
        chip = box.chip(kind, value)
        if chip is not None:
            flash(chip)


def _take_covered(verdict: Verdict) -> list[tuple[RecipientField, str, int]]:
    """Remove the people a newly placed group covers; returns where each one was."""
    removed: list[tuple[RecipientField, str, int]] = []
    for box, address in verdict.remove:
        index = box.index_of(EMAIL, address)
        if index >= 0:
            box._remove_token(EMAIL, address)
            removed.append((box, address, index))
    return removed


def _bind(fn: Callable[..., object], *args: object) -> Callable[[], object]:
    """``fn`` with its arguments fixed now (a lambda in a loop would see the last ones)."""
    return lambda: fn(*args)


def _copy(text: str) -> None:
    clipboard = QGuiApplication.clipboard()
    if clipboard is not None:
        clipboard.setText(text)


def _lifted(pixmap: QPixmap) -> QPixmap:
    """The image that follows the pointer: the chip, slightly see-through."""
    out = QPixmap(pixmap.size())
    out.setDevicePixelRatio(pixmap.devicePixelRatio())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setOpacity(0.9)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return out


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

    def vet(
        self, target: RecipientField, kind: str, value: str, *, ignore: Ignore = None
    ) -> Verdict:
        """May ``value`` go into ``target``? ``ignore`` is the chip being moved or edited:
        it doesn't count as "already there", and a group never removes it."""
        key = value.casefold()
        boxes = list(self.fields.values())
        # Already in the list as this exact chip?
        for box in boxes:
            if box.has(kind, value) and not _ignored(ignore, box, kind, value):
                return Verdict(
                    False,
                    f"{value} is already in {self._where(box)}.",
                    flash=[(box, kind, value)],
                )
        if kind == EMAIL:
            for box in boxes:
                for name in box.groups():
                    if _ignored(ignore, box, GROUP, name):
                        continue
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
                if address.casefold() not in covered or _ignored(ignore, box, EMAIL, address):
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
    """To and Cc as the email shows them: in chip order, each group's members at its place,
    each address once, To first — the rule the sender applies
    (``core.email.recipients.resolve``)."""
    by_name = {name.casefold(): members for name, members in groups.items()}
    seen: set[str] = set()
    result: dict[str, list[str]] = {}
    for key, box in (("to", to), ("cc", cc)):
        result[key] = []
        for entry in box.entries():
            if isinstance(entry, dict):
                addresses = by_name.get(entry["group"].casefold(), [])
            else:
                addresses = [entry]
            for address in addresses:
                if address.casefold() not in seen:
                    seen.add(address.casefold())
                    result[key].append(address)
    return result
