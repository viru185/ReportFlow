"""Help → What's new, and its one-time showing after an update (0.16)."""

from __future__ import annotations

from reportflow.ui.feedback import recall, remember
from reportflow.ui.windows import whats_new_dialog
from reportflow.ui.windows.whats_new_dialog import (
    SEEN_KEY,
    WhatsNewDialog,
    base_version,
    load_notes,
    note_versions,
)
from reportflow.ui.windows.whats_new_dialog import (
    should_show_after_update as real_should_show,  # the conftest switches it off
)

from .test_ui import FakeApi


def test_base_version_reads_every_spelling():
    for version in ("0.16.0", "0.16.0-beta", "0.16.0b0", "0.16.0+local"):
        assert base_version(version) == "0.16.0"


def test_the_installed_version_is_marked(tmp_path):
    notes = tmp_path / "whats_new.md"
    notes.write_text("# What's new\n\n## 0.16.0\n\n- a\n\n## 0.15.0\n\n- b\n", encoding="utf-8")
    assert "## 0.16.0 — this version\n" in load_notes(notes, installed="0.16.0")
    assert "## 0.16.0 — this version (beta)\n" in load_notes(notes, installed="0.16.0-beta")
    assert "## 0.16.0 — this version (beta)\n" in load_notes(notes, installed="0.16.0b0")
    marked = load_notes(notes, installed="0.15.0")
    assert "## 0.15.0 — this version\n" in marked and "## 0.16.0\n" in marked
    assert note_versions(load_notes(notes, installed="9.9.9")) == ["0.16.0", "0.15.0"]
    assert "missing" in load_notes(tmp_path / "gone.md")


def test_it_shows_once_per_new_version():
    assert recall(SEEN_KEY) is None
    # A fresh install with no jobs: nothing is "new" to someone just starting.
    assert real_should_show(installed="0.16.0", has_jobs=False) is False
    assert recall(SEEN_KEY) == "0.16.0"
    assert real_should_show(installed="0.16.0", has_jobs=True) is False  # already seen
    # The next update shows once, betas included.
    assert real_should_show(installed="0.17.0-beta", has_jobs=False) is True
    assert real_should_show(installed="0.17.0-beta", has_jobs=False) is False


def test_an_update_from_before_0_16_shows_it():
    """Nothing recorded yet, but there are jobs: this install was in use before 0.16."""
    assert real_should_show(installed="0.16.0", has_jobs=True) is True
    assert recall(SEEN_KEY) == "0.16.0"


def test_the_window_shows_the_bundled_notes(qtbot):
    dialog = WhatsNewDialog()
    qtbot.addWidget(dialog)
    text = dialog.browser.toPlainText()
    assert "What's new in ReportFlow" in text
    assert "Stop a running job." in text
    assert note_versions(whats_new_dialog.NOTES_PATH.read_text(encoding="utf-8"))[0] in text


def test_help_menu_and_about_open_it(qtbot, monkeypatch):
    from reportflow.ui.windows.about_dialog import AboutDialog
    from reportflow.ui.windows.main_window import MainWindow

    opened = []
    monkeypatch.setattr(WhatsNewDialog, "exec", lambda self: opened.append(self) or 0)
    window = MainWindow(FakeApi())
    qtbot.addWidget(window)
    from PySide6.QtGui import QAction

    action = next(a for a in window.findChildren(QAction) if a.text() == "What's new")
    action.trigger()
    assert len(opened) == 1
    about = AboutDialog(window, on_whats_new=window._open_whats_new)
    qtbot.addWidget(about)
    from reportflow.ui.kit import Button

    button = next(b for b in about.findChildren(Button) if b.text() == "What's new")
    button.click()
    assert len(opened) == 2


def test_it_opens_by_itself_after_an_update(qtbot, monkeypatch):
    from reportflow.ui.windows.main_window import MainWindow

    calls = []

    def after_update(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(whats_new_dialog, "should_show_after_update", after_update)
    window = MainWindow(FakeApi())
    qtbot.addWidget(window)
    window._whats_new_after_update()
    dialog = window.findChild(WhatsNewDialog)
    assert dialog is not None and dialog.isVisible()
    assert calls == [{"has_jobs": window._job_count > 0}]
    dialog.close()


def test_without_the_service_it_waits_for_the_next_start(qtbot, monkeypatch):
    from reportflow.ui.windows.main_window import MainWindow

    window = MainWindow(FakeApi())
    qtbot.addWidget(window)
    window._connected = False
    monkeypatch.setattr(whats_new_dialog, "should_show_after_update", real_should_show)
    window._whats_new_after_update()
    assert window.findChild(WhatsNewDialog) is None
    assert recall(SEEN_KEY) is None  # nothing recorded: it can still show next time
    remember(SEEN_KEY, None)
