"""The Help guide: a Markdown user guide with sections, search and every fact kept."""

from __future__ import annotations

import pytest

from reportflow.core.email.render import PLACEHOLDERS
from reportflow.core.output_names import OUTPUT_NAME_TOKENS
from reportflow.ui.windows.help_dialog import HelpDialog, load_guide

# Every section other screens (or links in the guide) point at.
ANCHORS = [
    "quickstart",
    "start",
    "jobs",
    "attachments",
    "output",
    "oldreports",
    "schedule",
    "email",
    "groups",
    "template",
    "placeholders",
    "runs",
    "stop",
    "logs",
    "settings",
    "transfer",
    "updates",
    "advanced",
    "shortcuts",
    "troubleshooting",
    "pidatalink",
    "pidatalink-fails",
    "dryrun",
    "emailalerts",
    "exportlogs",
]

# Facts the old HTML guide taught; the rewrite for everyday users must keep each one.
KEPT_FACTS = [
    "run history and email template move with it",
    "Sheets are stored by",
    "Remove them from the file",
    "Keep them, hidden",
    "Keep them, visible",
    "If a workbook fails",
    "Your input files are never modified",
    "Combine selected sheets into one PDF",
    "at least one visible Excel sheet is required",
    "{job}_{datetime}",
    "Sales_20261007_061500",
    "overwritten by a second run on the same day",
    "_{workbook}",
    "Custom (cron)",
    "minute hour day-of-month month day-of-week",
    "Two schedules may not fire at the same moment",
    "[TEST]",
    "Move to production",
    "Failures never send email",
    "email:",
    "To comes first, then Cc, then Bcc",
    "A group a job still uses can't be deleted",
    "Keep linked to this file",
    "the email is still sent with the default template",
    "Dates are the date the run",
    "an unknown name comes out empty",
    "%H:%M",
    "Build only",
    "next: tomorrow",
    "last: success 2h ago",
    "Open last report",
    "Duplicate",
    "Resume",
    "Failed runs are never retried automatically",
    "Application logs",
    "Send logs to support",
    "Delete old logs",
    "Delete ALL logs",
    "Open data folder",
    "Test connection",
    "Support email",
    "Use current Windows user",
    "Validate & apply",
    "Import as copy",
    "The SMTP password never travels",
    "Check for updates when the app starts",
    "pre-releases",
    "Default time limit",
    "30–60 min",
    "moves on as soon as the data stops changing",
    "Concurrency group",
    "Freeze formulas",
    "Fail if a sheet comes out empty",
    "Fail if a sheet has error cells (strict)",
    "Blank out values",
    "Debug logging",
    "cannot load when the service runs as LocalSystem",
    "#NAME?",
    "set-service-account.ps1",
    "Fix PI DataLink",
    "connected=True",
    "Mark-of-the-Web",
    "Unblock",
    "Require PI DataLink",
    "pi_diagnostics",
    "The add-in could not be installed",
    "0x80070005",
    "manually pasted values",
    "Dry run",
    "Email failed",
    "description of the problem",
]


@pytest.fixture
def guide(qtbot):
    dlg = HelpDialog()
    qtbot.addWidget(dlg)
    return dlg


def test_every_section_is_there_and_reachable(guide):
    _markdown, sections = load_guide()
    assert [s.id for s in sections] == ANCHORS
    assert set(guide._positions) == set(ANCHORS)  # each id found on a rendered heading
    assert "{#" not in guide.browser.toPlainText()  # the markers never show


def test_no_fact_of_the_old_guide_was_lost(guide):
    text = guide.browser.toPlainText()
    missing = [fact for fact in KEPT_FACTS if fact not in text]
    assert not missing


def test_generated_tables_follow_the_app(guide):
    text = guide.browser.toPlainText()
    for _group, _label, token, _about in PLACEHOLDERS:
        assert token in text  # including {{ attachments | join(", ") }} — no stray "\\|"
    for _label, token, _about in OUTPUT_NAME_TOKENS:
        assert token in text
    assert "\\|" not in text
    assert "07-Oct-2026" in text and "Daily production report — 07-Oct-2026" in text


def test_opens_at_a_section_and_links_jump(qtbot, guide):
    guide.show()
    qtbot.waitExposed(guide)
    guide.go_to("groups")
    assert guide.current_section() == "groups"
    assert guide.toc.currentItem().data(0x0100) == "groups"
    from PySide6.QtCore import QUrl

    guide._on_link(QUrl("#placeholders"))
    assert guide.current_section() == "placeholders"
    dlg = HelpDialog(anchor="schedule")
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    qtbot.waitUntil(lambda: dlg.current_section() == "schedule", timeout=2000)


def test_search_filters_sections_and_highlights(guide):
    guide.search.setText("Mark-of-the-Web")
    visible = [
        guide.toc.item(i).data(0x0100)
        for i in range(guide.toc.count())
        if not guide.toc.item(i).isHidden()
    ]
    assert visible == ["pidatalink"]
    assert guide.browser.extraSelections()
    assert guide.matches.text().startswith("1 match")
    guide.search.setText("")
    assert all(not guide.toc.item(i).isHidden() for i in range(guide.toc.count()))
    assert not guide.browser.textCursor().hasSelection()  # the last match isn't left selected


def test_a_search_with_no_match_says_so(guide):
    guide.search.setText("group")
    assert guide.browser.textCursor().hasSelection()
    guide.search.setText("zzqx")
    assert guide.matches.text() == "Nothing in the guide matches “zzqx”."
    assert guide.toc.isHidden() and not guide.browser.extraSelections()
    assert not guide.browser.textCursor().hasSelection()  # no stale highlight
    guide.search.setText("")
    assert not guide.toc.isHidden() and guide.matches.isHidden()


def test_callouts_are_boxed_and_the_guide_never_scrolls_sideways(qtbot, guide):
    from PySide6.QtGui import QTextFrame

    children = guide.browser.document().rootFrame().childFrames()
    frames = [f for f in children if type(f) is QTextFrame]  # tables are frames too
    assert len(frames) >= 8  # every 💡 tip and ⚠ note sits in its own padded box
    assert all(f.frameFormat().padding() == 12 for f in frames)
    guide.resize(720, 480)
    guide.show()
    qtbot.waitExposed(guide)
    guide.go_to("placeholders")
    bar = guide.browser.horizontalScrollBar()
    assert bar.maximum() == 0
