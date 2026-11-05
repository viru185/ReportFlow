"""Generate one release's notes, using version order across merged Git histories."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from packaging.version import InvalidVersion, Version


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, encoding="utf-8").strip()


def previous_tag(tag: str) -> str | None:
    current = Version(tag.removeprefix("v"))
    candidates = []
    for candidate in git("tag", "--merged", tag).splitlines():
        if not candidate.startswith("v"):
            continue
        try:
            version = Version(candidate[1:])
        except InvalidVersion:
            continue
        if version < current and (current.is_prerelease or not version.is_prerelease):
            candidates.append((version, candidate))
    return max(candidates)[1] if candidates else None


def render_notes(tag: str, date: str, subjects: list[str], previous: str | None) -> str:
    groups: dict[str, list[str]] = {}
    for subject in subjects:
        if subject.startswith("Merge "):
            continue
        match = re.match(r"^(\w+)(?:\([^)]*\))?!?:\s*(.+)$", subject)
        group = "Changes"
        if match:
            kind, subject = match.groups()
            if kind in {"chore", "ci", "test", "docs", "build"}:
                continue
            group = {"feat": "Features", "fix": "Bug fixes", "perf": "Performance"}.get(
                kind, "Changes"
            )
        groups.setdefault(group, []).append(subject[0].upper() + subject[1:])
    lines = [f"## [{tag.removeprefix('v')}] - {date}", ""]
    if previous:
        lines += [f"Changes since {previous}.", ""]
    for group, subjects in groups.items():
        lines += [f"### {group}", ""]
        lines += [f"- {subject}" for subject in dict.fromkeys(subjects)]
        lines.append("")
    if not groups:
        lines += ["Maintenance release.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    previous = previous_tag(args.tag)
    revision = f"{previous}..{args.tag}" if previous else args.tag
    subjects = git("log", "--reverse", "--no-merges", "--format=%s", revision).splitlines()
    date = git("log", "-1", "--format=%cs", args.tag)
    args.output.write_text(render_notes(args.tag, date, subjects, previous), encoding="utf-8")
    print(f"Release notes for {args.tag}, base {previous or 'initial commit'}")


if __name__ == "__main__":
    main()
