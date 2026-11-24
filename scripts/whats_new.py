"""Draft the next "What's new" section (src/reportflow/ui/help/whats_new.md) from git.

Prints the user-facing commits since the last stable release as a New / Fixed / Faster draft,
for the release's "prepare" commit. It is only a starting point: rewrite each line for someone
who uses the app (what they can do now, or what no longer goes wrong), merge related lines,
drop what they would never notice, and paste it at the top of whats_new.md. A test fails when
the newest section there is older than pyproject.toml's version.

Usage: uv run python scripts/whats_new.py 0.16.0
"""

from __future__ import annotations

import argparse
import re
import subprocess

from packaging.version import InvalidVersion, Version

_GROUPS = {"feat": "New", "fix": "Fixed", "perf": "Faster"}  # the rest is internal


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, encoding="utf-8").strip()


def last_release(tags: list[str]) -> str | None:
    """The newest stable ``vX.Y.Z`` tag among ``tags``."""
    stable = []
    for tag in tags:
        try:
            version = Version(tag.removeprefix("v"))
        except InvalidVersion:
            continue
        if tag.startswith("v") and not version.is_prerelease:
            stable.append((version, tag))
    return max(stable)[1] if stable else None


def draft(version: str, subjects: list[str]) -> str:
    groups: dict[str, list[str]] = {name: [] for name in _GROUPS.values()}
    for subject in subjects:
        match = re.match(r"^(\w+)(?:\([^)]*\))?!?:\s*(.+)$", subject)
        if not match or match.group(1) not in _GROUPS:
            continue
        text = match.group(2)
        groups[_GROUPS[match.group(1)]].append(text[0].upper() + text[1:])
    lines = [f"## {version}", ""]
    for name, items in groups.items():
        if items:
            lines += [f"### {name}", "", *(f"- {item}" for item in dict.fromkeys(items)), ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="the version being prepared, e.g. 0.16.0")
    args = parser.parse_args()
    since = last_release(git("tag", "--merged", "HEAD").splitlines())
    revision = f"{since}..HEAD" if since else "HEAD"
    subjects = git("log", "--reverse", "--no-merges", "--format=%s", revision).splitlines()
    print(f"<!-- draft: commits since {since or 'the first commit'} -->")
    print(draft(args.version, subjects))


if __name__ == "__main__":
    main()
