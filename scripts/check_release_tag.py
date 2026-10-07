"""Fail a release whose git tag disagrees with pyproject.toml's version (run by release.yml).

The app reads its version from the package metadata, so a tag that doesn't match would
publish an installer reporting the wrong version. Compared as PEP 440 versions: the tag
``v0.11.0-beta.1`` matches ``version = "0.11.0-beta.1"`` (or the normalized ``0.11.0b1``).

Usage: python scripts/check_release_tag.py v0.11.0-beta.1
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from packaging.version import InvalidVersion, Version

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def tag_matches(tag: str, project_version: str) -> bool:
    try:
        return Version(tag.lstrip("vV")) == Version(project_version)
    except InvalidVersion:
        return False


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    tag = argv[1]
    project_version = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    if not tag_matches(tag, project_version):
        print(f"tag {tag} does not match pyproject.toml version {project_version}")
        return 1
    print(f"tag {tag} matches pyproject.toml version {project_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
