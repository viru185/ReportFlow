"""Edit one email group from wherever it is used — double-click its chip in a job.

A group belongs to Settings → Email groups and is shared by every job that uses it, so the
window says who else uses it and saves straight to the service (a rename is carried into
every saved job by the service, ``PUT /email-groups`` with ``renamed_from``). The job open in
the editor renames its own chips when this window closes (``JobEditorDialog._edit_group``).

:func:`group_name_problem` is the one rule for group names, used here and in Settings.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from PySide6.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from reportflow.ui.api_client import ApiError
from reportflow.ui.feedback import (
    FormDialog,
    InlineNotice,
    clear_field_error,
    set_field_error,
)
from reportflow.ui.kit import set_variant
from reportflow.ui.recipient_field import RecipientField, RecipientSet
from reportflow.ui.suggestions import jobs_using_group, known_addresses
from reportflow.ui.widgets import space_layout


def group_name_problem(name: str, taken: Iterable[str]) -> str | None:
    """Why ``name`` can't be a group's name (``taken``: the OTHER groups' names), or None."""
    name = name.strip()
    if not name:
        return "Give the group a name."
    if any(c in name for c in ",;@"):
        return "A group name can't contain , ; or @."
    if name.casefold() in {t.casefold() for t in taken}:
        return f"Another group is already called {name}."
    return None


class EmailGroupDialog(FormDialog):
    """Name and members of one email group. After ``exec()`` returns Accepted,
    ``saved_name`` / ``saved_members`` hold what was saved."""

    def __init__(self, api: Any, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, settings_key="email_group")
        self._api = api
        self.setWindowTitle(f"Email group — {name}")
        self.setMinimumWidth(520)
        self.resize(600, 380)
        config = api.get_config()  # ApiError goes to the caller: nothing to edit offline
        # (name, members) of every group, as the service has them now.
        self._groups: list[tuple[str, list[str]]] = [
            (str(g["name"]), [str(m) for m in g.get("members") or []])
            for g in (config.get("email") or {}).get("groups") or []
        ]
        found = next((g for g in self._groups if g[0].casefold() == name.casefold()), None)
        self._original: str | None = found[0] if found else None
        self.saved_name = ""
        self.saved_members: list[str] = []

        layout = QVBoxLayout(self)
        intro = QLabel(
            "A group is shared: what you change here applies to every job that uses it, as "
            "soon as you click Save."
        )
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.name = QLineEdit(found[0] if found else name)
        self.name.setPlaceholderText("e.g. Plant managers")
        self.name.textEdited.connect(lambda *_: clear_field_error(self.name))
        self.members = RecipientField(allow_groups=False, placeholder="Type or paste addresses…")
        self.members.setToolTip(
            "The group's addresses. Type to search addresses the app already knows; Enter, "
            "Tab, comma or semicolon adds it, and a pasted list is split."
        )
        self.members.changed.connect(lambda: clear_field_error(self.members))
        self.notice = InlineNotice()
        self._members_set = RecipientSet(
            {"Members": self.members},
            addresses=known_addresses(config),
            notice=self.notice,
            single_name="this group",
        )
        self.members.set_value(found[1] if found else [])
        used = jobs_using_group(config, self._original) if self._original else []
        self.used_by = used
        if self._original is None:
            used_text = f"There is no group called {name} any more — Save creates it again."
        elif used:
            used_text = f"Used by {len(used)} job{'s' if len(used) != 1 else ''}: {', '.join(used)}"
        else:
            used_text = "Not used by any saved job yet."
        self.used = QLabel(used_text)
        self.used.setWordWrap(True)
        self.used.setProperty("muted", True)
        layout.addWidget(self.used)  # right under the intro: who else this change reaches
        form.addRow("Name", self.name)
        form.addRow("Members", self.members)
        form.addRow("", self.notice)
        layout.addLayout(form)
        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save = buttons.button(QDialogButtonBox.StandardButton.Save)
        set_variant(save, "primary")
        buttons.accepted.connect(self.save_form)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        space_layout(layout)
        self.finish_form(save)

    # -- FormDialog --

    def dirty_key(self) -> str:
        return json.dumps(
            [self.name.text().strip(), self.members.emails(), self.members.edit.text().strip()]
        )

    def help_anchor(self) -> str | None:
        return "groups"

    def save_form(self) -> None:
        problem = self.members.commit_pending()
        if problem:
            set_field_error(self.members, problem, "groups")
            return
        name = self.name.text().strip()
        others = [group for group, _members in self._groups if group != self._original]
        problem = group_name_problem(name, others)
        if problem:
            set_field_error(self.name, problem, "groups")
            self.name.setFocus()
            return
        members = self.members.emails()
        if not members:
            set_field_error(self.members, "Add at least one address.", "groups")
            return
        payload: list[dict[str, Any]] = []
        for group, group_members in self._groups:
            if group == self._original:
                renamed = self._original if self._original != name else None
                payload.append({"name": name, "members": members, "renamed_from": renamed})
            else:
                payload.append({"name": group, "members": group_members, "renamed_from": None})
        if self._original is None:
            payload.append({"name": name, "members": members, "renamed_from": None})
        try:
            self._api.put_email_groups(payload)
        except ApiError as e:
            self.notice.show_notice(f"Couldn't save the group: {e}", "error", timeout_ms=0)
            return
        self.saved_name = name
        self.saved_members = members
        self.accept()
