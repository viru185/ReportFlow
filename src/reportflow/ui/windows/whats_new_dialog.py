"""Help → What's new: the user-facing notes in ``ui/help/whats_new.md`` (0.16).

Written by hand for people who use the app — New / Fixed per version, newest first — and
bundled with it (CHANGELOG.md is regenerated after each build, so a bundled copy of it would
always be one release behind). A test keeps its newest entry in step with pyproject.toml.

The window also opens once by itself the first time a new version runs (see
:func:`should_show_after_update`).
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QTextBrowser, QVBoxLayout, QWidget

from reportflow import __about__ as about
from reportflow.ui.feedback import recall, remember, restore_geometry, save_geometry
from reportflow.ui.kit import Button
from reportflow.ui.windows.help_dialog import style_document

NOTES_PATH = Path(__file__).resolve().parents[1] / "help" / "whats_new.md"
SEEN_KEY = "whats_new/seen"
_VERSION_HEADING = re.compile(r"^## (\d+(?:\.\d+)*)\s*$", re.MULTILINE)


def base_version(version: str) -> str:
    """``0.16.0`` for ``0.16.0``, ``0.16.0-beta`` or ``0.16.0b0``."""
    match = re.match(r"\d+(?:\.\d+)*", version)
    return match.group(0) if match else version


def note_versions(markdown: str) -> list[str]:
    """The versions the notes cover, newest first."""
    return _VERSION_HEADING.findall(markdown)


def load_notes(path: Path = NOTES_PATH, *, installed: str = about.VERSION) -> str:
    """The notes, with the installed version's heading marked."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "# What's new\n\nThe release notes are missing from this installation."
    base = base_version(installed)
    beta = " (beta)" if installed != base and not installed.startswith(base + "+") else ""
    return re.sub(
        rf"^## {re.escape(base)}\s*$",
        f"## {base} — this version{beta}",
        text,
        count=1,
        flags=re.MULTILINE,
    )


def should_show_after_update(*, installed: str = about.VERSION, has_jobs: bool) -> bool:
    """Open What's new once for each new version. A fresh install (nothing seen before, no
    jobs yet) just records the version — there is nothing "new" to someone just starting."""
    base = base_version(installed)
    seen = recall(SEEN_KEY)
    if seen == base:
        return False
    remember(SEEN_KEY, base)
    return bool(seen) or has_jobs


class WhatsNewDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"What's new in {about.NAME}")
        self.resize(760, 680)
        self.setMinimumSize(520, 420)

        self.browser = QTextBrowser()
        self.browser.setObjectName("helpBrowser")  # the Help guide's look
        self.browser.setOpenExternalLinks(True)
        self.browser.setMarkdown(load_notes())
        doc = self.browser.document()
        doc.setDocumentMargin(24)
        style_document(doc)

        # No Close button: the title bar has one, and Esc closes it.
        changelog = Button("Full changelog on GitHub")
        changelog.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(f"{about.REPO_URL}/blob/main/CHANGELOG.md"))
        )
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(changelog)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self.browser, 1)
        layout.addLayout(actions)
        restore_geometry(self, "whats_new")

    def done(self, result: int) -> None:
        save_geometry(self, "whats_new")
        super().done(result)
