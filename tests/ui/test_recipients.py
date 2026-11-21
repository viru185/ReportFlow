"""Recipient chips and lists: × only, Enter, one person once per list, focused suggestions."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt

from reportflow.ui.recipient_field import GROUP, GROUP_PREFIX, RecipientField, RecipientSet

from .test_ui import FakeApi, _groups_config, _type

GROUPS = {
    "Plant leads": ["a@corp.example.com", "b@corp.example.com"],
    "Energy team": ["b@corp.example.com", "c@corp.example.com"],
}
KNOWN = [
    "a@corp.example.com",
    "b@corp.example.com",
    "c@corp.example.com",
    "boss@corp.example.com",
    "ops@corp.example.com",
]


@pytest.fixture
def prod(qtbot):
    from reportflow.ui.feedback import InlineNotice

    to, cc, bcc = RecipientField(), RecipientField(), RecipientField()
    for box in (to, cc, bcc):
        qtbot.addWidget(box)
    notice = InlineNotice()
    qtbot.addWidget(notice)
    rs = RecipientSet(
        {"To": to, "Cc": cc, "Bcc": bcc}, groups=GROUPS, addresses=KNOWN, notice=notice
    )
    return rs, to, cc, bcc, notice


def test_only_the_x_removes_a_chip(qtbot, prod):
    _rs, to, *_ = prod
    to.show()
    _type(to, "boss@corp.example.com")
    chip = to.chip("email", "boss@corp.example.com")
    qtbot.mouseClick(chip.label, Qt.MouseButton.LeftButton, pos=QPoint(4, 4))
    assert to.emails() == ["boss@corp.example.com"]  # the body does nothing
    qtbot.mouseClick(chip.close_button, Qt.MouseButton.LeftButton)
    assert to.emails() == []
    # The × can't take keyboard focus, so it can never become a dialog's default button.
    assert chip.close_button.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_enter_adds_the_typed_address_and_is_consumed(qtbot, prod):
    _rs, to, *_ = prod
    to.edit.setText("ops@corp.example.com")
    qtbot.keyClick(to.edit, Qt.Key.Key_Return)
    assert to.emails() == ["ops@corp.example.com"] and to.edit.text() == ""


def test_a_person_already_in_the_list_is_refused_with_a_note(qtbot, prod):
    _rs, to, cc, _bcc, notice = prod
    _type(to, "boss@corp.example.com")
    _type(cc, "BOSS@corp.example.com")
    assert cc.emails() == []
    assert notice.plain == "BOSS@corp.example.com is already in To."
    # The chip it points at flashes.
    assert to.chip("email", "boss@corp.example.com").property("flash") is True


def test_an_address_a_group_covers_is_refused(qtbot, prod):
    _rs, to, cc, _bcc, notice = prod
    _type(to, "Plant leads")
    _type(cc, "a@corp.example.com")
    assert cc.emails() == []
    assert notice.plain == "a@corp.example.com is already in the group Plant leads (To)."


def test_adding_a_group_takes_over_the_people_it_covers_with_undo(qtbot, prod):
    _rs, to, cc, bcc, notice = prod
    _type(cc, "a@corp.example.com, ops@corp.example.com")
    _type(bcc, "b@corp.example.com")
    _type(to, "Plant leads")
    assert to.groups() == ["Plant leads"]
    assert cc.emails() == ["ops@corp.example.com"] and bcc.emails() == []
    assert notice.plain.startswith("Removed a@corp.example.com, b@corp.example.com")
    notice.linkActivated.emit("action")  # Undo
    assert to.groups() == []
    # 0.15: Undo puts people back where they were, not at the end.
    assert cc.emails() == ["a@corp.example.com", "ops@corp.example.com"]
    assert bcc.emails() == ["b@corp.example.com"]


def test_a_group_added_lower_down_never_demotes_someone_from_to(qtbot, prod):
    _rs, to, _cc, bcc, notice = prod
    _type(to, "a@corp.example.com")
    _type(bcc, "Plant leads")
    assert to.emails() == ["a@corp.example.com"]  # stays in To
    assert bcc.groups() == ["Plant leads"]
    assert "a@corp.example.com stays in To" in notice.plain


def test_suggestions_offer_only_what_is_not_in_the_list(qtbot, prod):
    _rs, to, cc, *_ = prod
    assert f"{GROUP_PREFIX}Plant leads" in cc.choices()
    _type(to, "Plant leads, ops@corp.example.com")
    for box in (to, cc):
        choices = box.choices()
        assert f"{GROUP_PREFIX}Plant leads" not in choices  # already used
        assert "ops@corp.example.com" not in choices  # already a chip
        assert "a@corp.example.com" not in choices  # covered by the group
        assert "c@corp.example.com" in choices
    # Removing the group offers its people again.
    to._remove_token(GROUP, "Plant leads")
    assert "a@corp.example.com" in cc.choices()


def test_loading_a_saved_overlap_leaves_it_untouched(qtbot, prod):
    _rs, to, cc, *_ = prod
    to.set_value([], ["Plant leads"])
    cc.set_value(["a@corp.example.com"])
    assert cc.emails() == ["a@corp.example.com"]  # the rules only apply to new adds


def test_invalid_text_keeps_the_fields_own_tooltip_afterwards(qtbot):
    field = RecipientField()
    qtbot.addWidget(field)
    field.setToolTip("Production To — required.")
    assert _type(field, "nope")
    assert "Not a known" in field.toolTip()
    field.edit.setText("")
    field._set_invalid(False)
    assert field.toolTip() == "Production To — required."


# -- in the dialogs -------------------------------------------------------------------


def test_enter_in_a_recipient_box_never_closes_the_job_editor(qtbot):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    api = FakeApi()
    api.get_config = lambda: {**FakeApi().get_config(), **_groups_config()}
    dlg = JobEditorDialog(api)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    dlg.prod_to.edit.setText("boss@corp.example.com")
    qtbot.keyClick(dlg.prod_to.edit, Qt.Key.Key_Return)
    qtbot.keyClick(dlg.prod_to.edit, Qt.Key.Key_Return)  # again, on the empty box
    assert dlg.isVisible() and dlg.result() == 0
    assert dlg.prod_to.emails() == ["boss@corp.example.com"]


def test_settings_group_members_enter_and_duplicates(qtbot):
    from reportflow.ui.windows.settings_dialog import SettingsDialog

    api = FakeApi()
    api.get_config = lambda: {**FakeApi().get_config(), **_groups_config()}
    dlg = SettingsDialog(api)
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    dlg.settings_tabs.setCurrentIndex(dlg.settings_tabs.count() - 1)
    members = dlg.group_members
    members.edit.setText("new@corp.example.com")
    qtbot.keyClick(members.edit, Qt.Key.Key_Return)  # used to press Save and close Settings
    assert dlg.isVisible() and "new@corp.example.com" in members.emails()
    _type(members, "a@corp.example.com")  # already a member of "Plant leads"
    assert dlg.group_notice.plain == "a@corp.example.com is already in this group."
    assert "a@corp.example.com" not in members.choices()


def test_a_successful_add_clears_an_old_note(qtbot, prod):
    _rs, to, cc, _bcc, notice = prod
    _type(to, "boss@corp.example.com")
    _type(cc, "boss@corp.example.com")
    assert notice.plain
    _type(cc, "ops@corp.example.com")
    assert notice.plain == ""


def test_group_suggestions_are_listed_by_name_with_an_icon(qtbot, prod):
    _rs, to, *_ = prod
    model = to._completer.model()
    names = [model.index(i, 0).data() for i in range(model.rowCount())]
    assert "Plant leads" in names  # no emoji prefix in the list
    row = names.index("Plant leads")
    assert model.index(row, 0).data(Qt.ItemDataRole.DecorationRole) is not None
    to._on_completed("Plant leads")  # picking it by name adds the group
    assert to.groups() == ["Plant leads"]


# -- picking from the suggestion list (the 0.13 "one Enter adds two people" bug) ----------

SIMILAR = ["viren.hirpara@cerebulb.com", "viren.hirpara@gmail.com", "virendra@corp.example.com"]


@pytest.fixture
def typing(qtbot):
    """A To box offering three similar addresses, with "vire" typed and suggestions open."""
    from reportflow.ui.feedback import InlineNotice

    to, cc = RecipientField(), RecipientField()
    notice = InlineNotice()
    for widget in (to, cc, notice):
        qtbot.addWidget(widget)
    RecipientSet({"To": to, "Cc": cc}, groups=GROUPS, addresses=SIMILAR, notice=notice)
    to.show()
    qtbot.waitExposed(to)
    to.edit.setFocus()
    qtbot.keyClicks(to.edit, "vire")
    popup = to._completer.popup()
    qtbot.waitUntil(popup.isVisible, timeout=2000)
    return to, popup


def test_one_enter_adds_exactly_the_highlighted_suggestion(qtbot, typing):
    to, popup = typing
    qtbot.keyClick(popup, Qt.Key.Key_Down)  # highlight the first: cerebulb
    qtbot.keyClick(popup, Qt.Key.Key_Return)
    assert to.emails() == ["viren.hirpara@cerebulb.com"]  # not gmail as well
    assert to.edit.text() == "" and not popup.isVisible()


def test_enter_with_nothing_highlighted_adds_the_first_match(qtbot, typing):
    to, popup = typing
    assert not popup.currentIndex().isValid()
    # The first row is drawn highlighted, so the user can see what Enter will add.
    delegate = popup.itemDelegate()
    first = popup.model().index(0, 0)
    assert delegate.is_highlighted(
        popup.viewOptions() if hasattr(popup, "viewOptions") else _opt(), first
    )
    qtbot.keyClick(popup, Qt.Key.Key_Return)
    assert to.emails() == ["viren.hirpara@cerebulb.com"]


def test_tab_picks_too_and_the_list_then_offers_the_rest(qtbot, typing):
    to, popup = typing
    qtbot.keyClick(popup, Qt.Key.Key_Down)
    qtbot.keyClick(popup, Qt.Key.Key_Down)  # gmail
    qtbot.keyClick(popup, Qt.Key.Key_Tab)
    assert to.emails() == ["viren.hirpara@gmail.com"]
    assert "viren.hirpara@gmail.com" not in to.choices()


def test_leaving_the_box_adds_a_typed_address(qtbot, prod):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent
    from PySide6.QtWidgets import QApplication

    _rs, to, *_ = prod
    to.edit.setText("late@corp.example.com")
    # Offscreen windows are never active, so send the focus change the user would cause.
    QApplication.sendEvent(
        to.edit, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.TabFocusReason)
    )
    assert to.emails() == ["late@corp.example.com"]
    # Switching to another window keeps the half-typed text as it is.
    to.edit.setText("half@")
    QApplication.sendEvent(
        to.edit, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.ActiveWindowFocusReason)
    )
    assert to.edit.text() == "half@" and not to.property("invalid")


def test_double_clicking_a_group_chip_asks_to_edit_it(qtbot, prod):
    _rs, to, *_ = prod
    to.show()
    _type(to, "Plant leads")
    asked: list[str] = []
    to.group_edit_requested.connect(asked.append)
    chip = to.chip(GROUP, "Plant leads")
    qtbot.mouseDClick(chip.label, Qt.MouseButton.LeftButton)
    assert asked == ["Plant leads"]
    assert "Double-click to edit" in chip.toolTip()


def test_a_renamed_group_keeps_its_place(qtbot, prod):
    _rs, to, *_ = prod
    _type(to, "boss@corp.example.com")
    _type(to, "Plant leads")
    _type(to, "ops@corp.example.com")
    to.rename_group("Plant leads", "Plant managers")
    assert [v for _k, v in to._tokens] == [
        "boss@corp.example.com",
        "Plant managers",
        "ops@corp.example.com",
    ]


def _opt():
    from PySide6.QtWidgets import QStyleOptionViewItem

    return QStyleOptionViewItem()
