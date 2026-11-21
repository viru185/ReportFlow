"""Editing an email group from its chip: shared, saved at once, renamed in the open job."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialog

from reportflow.ui.feedback import field_error, toasts
from reportflow.ui.group_editor import EmailGroupDialog, group_name_problem
from reportflow.ui.recipient_field import GROUP

from .test_ui import FakeApi, _groups_config, _sample_job_dict


def _api() -> FakeApi:
    api = FakeApi()
    api.get_config = lambda: {**FakeApi().get_config(), **_groups_config()}
    api.sent_groups = []  # type: ignore[attr-defined]
    api.put_email_groups = lambda groups: api.sent_groups.append(groups)  # type: ignore[attr-defined]
    return api


def test_group_name_rules():
    assert group_name_problem("", []) == "Give the group a name."
    assert "can't contain" in group_name_problem("a,b", [])
    assert "already called" in group_name_problem("plant LEADS", ["Plant leads"])
    assert group_name_problem("Plant managers", ["Plant leads"]) is None


def test_the_dialog_says_the_group_is_shared_and_who_uses_it(qtbot):
    dlg = EmailGroupDialog(_api(), "plant leads")  # any case finds it
    qtbot.addWidget(dlg)
    assert dlg.name.text() == "Plant leads"
    assert dlg.members.emails() == ["a@corp.example.com", "b@corp.example.com"]
    assert dlg.used.text() == "Used by 1 job: daily"
    assert not dlg.is_dirty()


def test_saving_renames_and_carries_jobs_along(qtbot):
    api = _api()
    dlg = EmailGroupDialog(api, "Plant leads")
    qtbot.addWidget(dlg)
    dlg.name.setText("Plant managers")
    dlg.members.edit.setText("d@corp.example.com")
    dlg.save_form()
    assert dlg.result() == QDialog.DialogCode.Accepted
    sent = {g["name"]: g for g in api.sent_groups[-1]}
    assert sent["Plant managers"]["renamed_from"] == "Plant leads"
    assert sent["Plant managers"]["members"][-1] == "d@corp.example.com"
    assert sent["Energy team"]["renamed_from"] is None  # the other group untouched


@pytest.mark.parametrize(
    ("name", "message"),
    [("Energy team", "Another group is already called Energy team."), ("", "Give the group")],
)
def test_a_bad_name_is_shown_on_the_field(qtbot, name, message):
    api = _api()
    dlg = EmailGroupDialog(api, "Plant leads")
    qtbot.addWidget(dlg)
    dlg.name.setText(name)
    dlg.save_form()
    assert message in field_error(dlg.name)
    assert not api.sent_groups and dlg.result() == 0


def test_double_clicking_a_chip_edits_the_group_and_the_job_follows(qtbot, monkeypatch):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    api = _api()
    job = _sample_job_dict()
    job["test"] = {"to": ["dev@corp.example.com"], "to_groups": ["Plant leads"]}
    editor = JobEditorDialog(api, job)
    qtbot.addWidget(editor)

    def rename_and_save(dialog: EmailGroupDialog) -> int:
        dialog.name.setText("Plant managers")
        dialog.save_form()
        return dialog.result()

    monkeypatch.setattr(EmailGroupDialog, "exec", rename_and_save)
    editor.test_to.group_edit_requested.emit("Plant leads")
    assert editor.test_to.groups() == ["Plant managers"]
    assert editor.test_to.chip(GROUP, "Plant managers").label.text() == "Plant managers · 2"
    assert "Plant managers" in editor._email_groups
    assert any("Saved the group Plant managers" in t for t in toasts(editor))
    assert editor.payload()["test"]["to_groups"] == ["Plant managers"]
