"""The release workflow refuses a tag that disagrees with pyproject.toml's version."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_release_tag.py"
_spec = importlib.util.spec_from_file_location("check_release_tag", _SCRIPT)
assert _spec is not None and _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


@pytest.mark.parametrize(
    ("tag", "version", "ok"),
    [
        ("v0.11.0", "0.11.0", True),
        ("v0.11.0-beta.1", "0.11.0-beta.1", True),
        ("v0.11.0-beta.1", "0.11.0b1", True),  # the normalized spelling is the same version
        ("v0.11.0-beta.2", "0.11.0b1", False),
        ("v0.11.0", "0.11.0b1", False),
        ("not-a-version", "0.11.0", False),
    ],
)
def test_tag_matches(tag, version, ok):
    assert check.tag_matches(tag, version) is ok


def test_current_pyproject_is_a_valid_version():
    import tomllib

    from packaging.version import Version

    data = tomllib.loads((_SCRIPT.parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    Version(data["project"]["version"])  # must parse as PEP 440
