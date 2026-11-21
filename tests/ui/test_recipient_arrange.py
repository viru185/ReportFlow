"""Arranging recipient chips (0.15): the order is the order the email lists people in.

Drag a chip (within a box or into another box of the same list), edit an address in place,
the chip's right-click menu, and the chip keys.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from reportflow.ui import recipient_field as rf
from reportflow.ui.recipient_field import (
    CHIP_MIME,
    EMAIL,
    GROUP,
    RecipientField,
    RecipientSet,
    header_recipients,
)

from .test_ui import _type

GROUPS = {
    "Plant leads": ["a@corp.example.com", "b@corp.example.com"],
    "Energy team": ["b@corp.example.com", "c@corp.example.com"],
}
BOSS, MARY, OPS = "boss@corp.example.com", "mary@corp.example.com", "ops@corp.example.com"


@pytest.fixture
def prod(qtbot):
    from reportflow.ui.feedback import InlineNotice

    to, cc, bcc = RecipientField(), RecipientField(), RecipientField()
    for box in (to, cc, bcc):
        qtbot.addWidget(box)
        box.resize(900, 40)
        box.show()
    notice = InlineNotice()
    qtbot.addWidget(notice)
    rs = RecipientSet({"To": to, "Cc": cc, "Bcc": bcc}, groups=GROUPS, notice=notice)
    return rs, to, cc, bcc, notice


def _values(box: RecipientField) -> list[str]:
    return [value for _kind, value in box._tokens]


def _drop(source: RecipientField, kind: str, value: str, target: RecipientField, at: QPoint):
    """What a real drag does: drag enter + drop on ``target``, then the move once the drag
    loop has ended (``_start_drag``) — Qt can't run a real OLE drag in a test."""
    rf._drag.source, rf._drag.kind, rf._drag.value, rf._drag.target = source, kind, value, None
    mime = QMimeData()
    mime.setData(CHIP_MIME, value.encode())
    buttons, mods = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    enter = QDragEnterEvent(at, Qt.DropAction.MoveAction, mime, buttons, mods)
    QApplication.sendEvent(target, enter)
    accepted = enter.isAccepted()
    caret = target._caret.isVisibleTo(target)
    drop = QDropEvent(QPointF(at), Qt.DropAction.MoveAction, mime, buttons, mods)
    QApplication.sendEvent(target, drop)
    landed = rf._drag.target
    rf._drag.source, rf._drag.target = None, None
    if landed is not None:
        box, index = landed
        source.move_to(box, kind, value, index)
    return accepted, caret


def _left_half(box: RecipientField, value: str, kind: str = EMAIL) -> QPoint:
    rect = box.chip(kind, value).geometry()
    return QPoint(rect.left() + 3, rect.center().y())


def _right_half(box: RecipientField, value: str, kind: str = EMAIL) -> QPoint:
    rect = box.chip(kind, value).geometry()
    return QPoint(rect.right() - 3, rect.center().y())


def test_dragging_a_chip_reorders_the_box_and_the_email(qtbot, prod):
    _rs, to, cc, _bcc, _notice = prod
    for text in (BOSS, "Plant leads", MARY):
        _type(to, text)
    QApplication.processEvents()
    # Mary in front of the boss: the caret's place is the left half of the boss's chip.
    assert to.drop_index(_left_half(to, BOSS)) == 0
    assert to.drop_index(_right_half(to, BOSS)) == 1
    assert to.drop_index(QPoint(to.width() - 5, 10)) == 3  # past the last chip
    accepted, caret = _drop(to, EMAIL, MARY, to, _left_half(to, BOSS))
    assert accepted and caret
    assert _values(to) == [MARY, BOSS, "Plant leads"]
    # The email follows the chips: a group's members go out at its place.
    assert header_recipients(to, cc, GROUPS)["to"] == [
        MARY,
        BOSS,
        "a@corp.example.com",
        "b@corp.example.com",
    ]
    assert to.entries() == [MARY, BOSS, {"group": "Plant leads"}]


def test_dropping_a_chip_on_its_own_place_changes_nothing(qtbot, prod):
    _rs, to, *_ = prod
    _type(to, f"{BOSS}, {MARY}")
    QApplication.processEvents()
    changed: list[int] = []
    to.changed.connect(lambda: changed.append(1))
    accepted, caret = _drop(to, EMAIL, BOSS, to, _right_half(to, BOSS))
    assert accepted and not caret  # no caret where nothing would move
    assert _values(to) == [BOSS, MARY] and not changed


def test_a_chip_dragged_into_cc_moves_there_at_the_caret(qtbot, prod):
    _rs, to, cc, _bcc, _notice = prod
    _type(to, f"{BOSS}, {MARY}")
    _type(cc, OPS)
    QApplication.processEvents()
    _drop(to, EMAIL, MARY, cc, _left_half(cc, OPS))
    assert _values(to) == [BOSS] and _values(cc) == [MARY, OPS]
    assert cc.property("dropTarget") is False  # the drop highlight is gone again


def test_production_and_test_lists_dont_take_each_others_chips(qtbot, prod):
    _rs, to, *_ = prod
    other = RecipientField()
    qtbot.addWidget(other)
    RecipientSet({"To": other}, groups=GROUPS)
    _type(to, BOSS)
    accepted, _caret = _drop(to, EMAIL, BOSS, other, QPoint(5, 5))
    assert not accepted and _values(to) == [BOSS] and _values(other) == []


def test_a_move_follows_the_one_person_once_rules(qtbot, prod):
    _rs, to, cc, _bcc, notice = prod
    _type(to, "a@corp.example.com, x@corp.example.com")
    _type(cc, "Plant leads")  # a@ stays in To, the higher box
    assert _values(to) == ["a@corp.example.com", "x@corp.example.com"]
    # Into Cc, where the group already covers a@: refused, nothing changes.
    assert not to.move_to(cc, EMAIL, "a@corp.example.com")
    assert notice.plain == "a@corp.example.com is already in the group Plant leads (Cc)."
    assert _values(to) == ["a@corp.example.com", "x@corp.example.com"]
    # The group up into To takes over a@ there — with Undo putting everything back.
    assert cc.move_to(to, GROUP, "Plant leads", 0)
    assert _values(to) == ["Plant leads", "x@corp.example.com"] and _values(cc) == []
    assert "Removed a@corp.example.com — now covered by Plant leads." in notice.plain
    notice.linkActivated.emit("action")  # Undo
    assert _values(to) == ["a@corp.example.com", "x@corp.example.com"]
    assert _values(cc) == ["Plant leads"]


def test_double_click_edits_an_address_in_place(qtbot, prod):
    _rs, to, *_ = prod
    _type(to, f"{BOSS}, mary@corp.exmaple.com, {OPS}")
    chip = to.chip(EMAIL, "mary@corp.exmaple.com")
    qtbot.mouseDClick(chip.label, Qt.MouseButton.LeftButton)
    editor = to._editor
    assert editor is not None and editor.text() == "mary@corp.exmaple.com"
    assert editor.selectedText() == editor.text()  # ready to retype
    assert to._flow.indexOf(editor) == 1  # in the chip's own place
    editor.setText(MARY)
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert to._editor is None
    assert _values(to) == [BOSS, MARY, OPS]  # same place, fixed address


def test_esc_cancels_an_edit_and_emptying_it_removes_the_person(qtbot, prod):
    _rs, to, *_ = prod
    _type(to, f"{BOSS}, {MARY}")
    editor = to.begin_edit(EMAIL, BOSS)
    editor.setText("someone@else.example.com")
    qtbot.keyClick(editor, Qt.Key.Key_Escape)
    assert _values(to) == [BOSS, MARY] and to.chip(EMAIL, BOSS).isVisibleTo(to)
    editor = to.begin_edit(EMAIL, BOSS)
    editor.setText("")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert _values(to) == [MARY]


def test_an_edit_that_cant_be_saved_stays_red_and_blocks_save(qtbot, prod):
    _rs, to, cc, _bcc, notice = prod
    _type(to, f"{BOSS}, {MARY}")
    _type(cc, OPS)
    editor = to.begin_edit(EMAIL, MARY)
    editor.setText("mary@")
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert to._editor is editor and editor.property("invalid") is True
    assert notice.plain == "mary@ is not a known email group or an address."
    # Save checks the boxes first: the half-typed edit is reported, not dropped.
    assert to.commit_pending() == "mary@ is not a known email group or an address."
    # Turning her into someone already in the list is refused the same way.
    editor.setText(OPS.upper())
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert notice.plain == f"{OPS.upper()} is already in Cc."
    assert _values(to) == [BOSS, MARY]
    # Only the case changed: that's the same person, saved as typed.
    editor.setText(MARY.upper())
    qtbot.keyClick(editor, Qt.Key.Key_Return)
    assert _values(to) == [BOSS, MARY.upper()]


def test_the_chip_menu(qtbot, prod):
    _rs, to, cc, _bcc, _notice = prod
    _type(to, f"Plant leads, {BOSS}")
    menu, actions = to.chip_menu(to.chip(EMAIL, BOSS))
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == ["Edit address", "Copy address", "Move to Cc", "Move to Bcc", "Remove"]
    group_menu, _ = to.chip_menu(to.chip(GROUP, "Plant leads"))
    texts = [a.text() for a in group_menu.actions() if not a.isSeparator()]
    assert texts[:2] == ["Edit group…", "Copy addresses"]
    # Copy, and Move to Cc.
    dict((a.text(), run) for a, run in actions)["Copy address"]()
    assert QApplication.clipboard().text() == BOSS
    dict((a.text(), run) for a, run in actions)["Move to Cc"]()
    assert _values(to) == ["Plant leads"] and _values(cc) == [BOSS]


def test_a_group_members_box_has_no_move_entries(qtbot):
    members = RecipientField(allow_groups=False)
    qtbot.addWidget(members)
    RecipientSet({"Members": members}, single_name="this group")
    _type(members, f"{BOSS}, {MARY}")
    menu, _ = members.chip_menu(members.chip(EMAIL, BOSS))
    assert [a.text() for a in menu.actions() if not a.isSeparator()] == [
        "Edit address",
        "Copy address",
        "Remove",
    ]
    # ... but its people can be put in order like any other box.
    assert members.move_entry(EMAIL, MARY, 0)
    assert members.emails() == [MARY, BOSS]


def test_chip_keys(qtbot, prod):
    _rs, to, *_ = prod
    _type(to, f"{BOSS}, {MARY}, {OPS}")
    with qtbot.waitActive(to):  # keyboard focus needs an active window, even offscreen
        to.activateWindow()
    # ← at the start of the box selects the last chip.
    qtbot.keyClick(to.edit, Qt.Key.Key_Left)
    assert to.focusWidget() is to.chip(EMAIL, OPS)
    qtbot.keyClick(to.chip(EMAIL, OPS), Qt.Key.Key_Left)
    assert to.focusWidget() is to.chip(EMAIL, MARY)
    # Alt+← / Alt+→ move the selected chip.
    qtbot.keyClick(to.chip(EMAIL, MARY), Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    assert _values(to) == [MARY, BOSS, OPS] and to.focusWidget() is to.chip(EMAIL, MARY)
    qtbot.keyClick(to.chip(EMAIL, MARY), Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    assert _values(to) == [MARY, BOSS, OPS]  # already first
    qtbot.keyClick(to.chip(EMAIL, BOSS), Qt.Key.Key_Right, Qt.KeyboardModifier.AltModifier)
    assert _values(to) == [MARY, OPS, BOSS]
    # Delete removes it and selects the next one; F2 edits.
    qtbot.keyClick(to.chip(EMAIL, OPS), Qt.Key.Key_Delete)
    assert _values(to) == [MARY, BOSS] and to.focusWidget() is to.chip(EMAIL, BOSS)
    qtbot.keyClick(to.chip(EMAIL, BOSS), Qt.Key.Key_F2)
    assert to._editor is not None and to._editor.text() == BOSS
    qtbot.keyClick(to._editor, Qt.Key.Key_Escape)
    # Esc on a chip goes back to typing; typing on a chip types into the box.
    qtbot.keyClick(to.chip(EMAIL, BOSS), Qt.Key.Key_Escape)
    assert to.focusWidget() is to.edit
    qtbot.keyClick(to.chip(EMAIL, BOSS), Qt.Key.Key_O)
    assert to.edit.text() == "o"


def test_keys_on_a_chip_never_reach_the_job_editor(qtbot):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    from .test_ui import FakeApi, _sample_job_dict

    dlg = JobEditorDialog(FakeApi(), _sample_job_dict())
    qtbot.addWidget(dlg)
    dlg.show()
    chip = dlg.prod_to.chips()[0]
    for key in (Qt.Key.Key_Return, Qt.Key.Key_Escape):
        qtbot.keyClick(chip, key)
        if dlg.prod_to._editor is not None:
            qtbot.keyClick(dlg.prod_to._editor, Qt.Key.Key_Escape)
        assert dlg.isVisible() and dlg.result() == 0
