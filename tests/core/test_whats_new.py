"""The bundled "What's new" notes and the script that drafts them (0.16)."""

from __future__ import annotations

import re
import runpy
import tomllib
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]
NOTES = ROOT / "src" / "reportflow" / "ui" / "help" / "whats_new.md"
script = runpy.run_path(str(ROOT / "scripts" / "whats_new.py"))


def _versions() -> list[str]:
    return re.findall(r"^## (\d+(?:\.\d+)*)\s*$", NOTES.read_text(encoding="utf-8"), re.M)


def test_the_notes_cover_this_version():
    """A version bump without its What's new section fails here, not in front of users."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    current = Version(Version(project["project"]["version"]).base_version)
    versions = _versions()
    assert versions, "whats_new.md has no '## X.Y.Z' sections"
    assert Version(versions[0]) >= current, (
        f"whats_new.md starts at {versions[0]} but pyproject.toml is {current}: write the "
        "new section (scripts/whats_new.py drafts it)"
    )


def test_the_ui_build_bundles_every_help_file():
    """A Markdown file the spec forgets is missing from the installed app."""
    spec = (ROOT / "packaging" / "pyinstaller" / "ui.spec").read_text(encoding="utf-8")
    for page in (ROOT / "src" / "reportflow" / "ui" / "help").glob("*.md"):
        assert f'"{page.name}"' in spec, f"{page.name} is not in ui.spec's datas"


def test_the_notes_are_newest_first_and_each_version_once():
    versions = [Version(v) for v in _versions()]
    assert versions == sorted(versions, reverse=True)
    assert len(set(versions)) == len(versions)


def test_the_draft_keeps_only_what_users_notice():
    text = script["draft"](
        "0.16.0",
        [
            "feat(ui): stop a running job",
            "fix(worker): freeze formulas to values without the clipboard",
            "perf: faster sheet scan",
            "chore(release): 0.16.0-beta",
            "docs: the user guide",
            "test: more cases",
            "feat(ui): stop a running job",  # the same subject twice
            "Merge branch 'dev'",
        ],
    )
    assert text.splitlines()[0] == "## 0.16.0"
    assert "### New\n\n- Stop a running job\n" in text
    assert "### Fixed\n\n- Freeze formulas to values without the clipboard\n" in text
    assert "### Faster\n\n- Faster sheet scan\n" in text
    assert "0.16.0-beta" not in text and "user guide" not in text and "Merge" not in text
    assert text.count("Stop a running job") == 1


def test_the_draft_starts_after_the_last_stable_release():
    tags = ["v0.14.1", "v0.15.0-beta", "v0.15.0", "v0.16.0-beta", "vbad", "nightly"]
    assert script["last_release"](tags) == "v0.15.0"
    assert script["last_release"]([]) is None
