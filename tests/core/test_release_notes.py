"""Keep beta notes incremental even when merged branches contain old tags."""

import runpy
from pathlib import Path

import pytest

notes = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/release_notes.py"))


@pytest.mark.parametrize(
    ("current", "expected"),
    [("v0.11.4-beta", "v0.11.3-beta"), ("v0.12.0", "v0.10.1"), ("v0.1.0", None)],
)
def test_previous_tag_uses_version_order_and_final_excludes_betas(current, expected, monkeypatch):
    function = notes["previous_tag"]
    monkeypatch.setitem(
        function.__globals__,
        "git",
        lambda *args: "v0.4.3\nv0.10.1\nv0.11.2-beta\nv0.11.3-beta\nv0.11.4-beta\nv0.99.0\nvbad",
    )
    assert function(current) == expected


def test_notes_have_one_version_and_omit_internal_commits():
    text = notes["render_notes"](
        "v0.11.4-beta",
        "2026-11-05",
        [
            "feat(ui): Add card shortcuts",
            "fix(ui): Show running status",
            "chore(release): Bump",
            "ci: Publish numbered betas",
            "test: Correct a fixture",
            "docs: Update changelog",
            "Merge old branch",
            "Improve local SMTP capture",
        ],
        "v0.11.3-beta",
    )
    assert text.count("## [") == 1
    assert "Changes since v0.11.3-beta" in text
    assert "Add card shortcuts" in text and "Show running status" in text
    assert "Improve local SMTP capture" in text
    assert all(term not in text for term in ["Bump", "numbered", "fixture", "Merge", "changelog"])
