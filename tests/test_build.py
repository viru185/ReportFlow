"""reportflow-build: target selection and the checks that run before anything slow."""

from __future__ import annotations

from importlib.metadata import entry_points
from pathlib import Path

import pytest

from reportflow import build


def _fake_dist(root: Path, versions: dict[str, str | None]) -> Path:
    """dist/<target>/reportflow-<target>.exe plus its version-stamped dist-info."""
    for target, version in versions.items():
        folder = root / target
        (folder / "_internal").mkdir(parents=True)
        (folder / f"reportflow-{target}.exe").write_bytes(b"MZ")
        if version:
            (folder / "_internal" / f"reportflow-{version}.dist-info").mkdir()
    return root


def test_reportflow_build_is_a_console_script():
    (script,) = entry_points(group="console_scripts", name="reportflow-build")
    assert script.value == "reportflow.build:main"


@pytest.mark.parametrize(
    ("targets", "steps"),
    [
        ([], ["worker", "service", "ui"]),
        (["service"], ["service"]),
        (["ui", "worker"], ["worker", "ui"]),
        (["installer", "ui"], ["ui", "installer"]),
        (["all"], ["worker", "service", "ui", "installer"]),
        (["installer"], ["installer"]),
    ],
)
def test_plan_builds_exes_before_the_installer(targets, steps):
    assert build.plan(targets) == steps


def test_unknown_target_is_an_error_not_a_full_build(capsys):
    with pytest.raises(SystemExit):
        build.parse(["sevice"])
    assert "unknown target sevice" in capsys.readouterr().err


def test_beta_versions_match_their_dist_info_spelling():
    assert build.same_version("0.12.0-beta", "0.12.0b0")
    assert not build.same_version("0.12.0-beta", "0.11.2b0")
    assert not build.same_version("0.12.0-beta", "an unknown version")
    assert build.numeric_version("0.12.0-beta") == "0.12.0"
    assert build.numeric_version("0.11.4") == "0.11.4"


def test_installer_accepts_exes_from_this_version(tmp_path, monkeypatch):
    dist = _fake_dist(tmp_path, {"worker": "0.12.0b0", "service": "0.12.0b0", "ui": "0.12.0b0"})
    monkeypatch.setattr(build, "DIST", dist)
    build.check_exes("0.12.0-beta")


def test_installer_refuses_stale_or_missing_exes(tmp_path, monkeypatch):
    dist = _fake_dist(tmp_path, {"worker": "0.12.0b0", "service": "0.11.2b0"})
    monkeypatch.setattr(build, "DIST", dist)
    with pytest.raises(build.BuildError) as err:
        build.check_exes("0.12.0-beta")
    message = str(err.value)
    assert "dist\\service was built from 0.11.2b0, not 0.12.0-beta" in message
    assert "dist\\ui\\reportflow-ui.exe is missing" in message
    assert "uv run reportflow-build service ui installer" in message


def test_all_stale_suggests_all(tmp_path, monkeypatch):
    dist = _fake_dist(tmp_path, {"worker": "0.11.2b0", "service": "0.11.2b0", "ui": None})
    monkeypatch.setattr(build, "DIST", dist)
    with pytest.raises(build.BuildError) as err:
        build.check_exes("0.12.0-beta")
    assert "dist\\ui was built from an unknown version" in str(err.value)
    assert "uv run reportflow-build all" in str(err.value)


def test_iscc_can_be_given_as_a_folder_or_the_exe(tmp_path):
    iscc = tmp_path / "ISCC.exe"
    iscc.write_bytes(b"MZ")
    assert build.find_iscc(str(tmp_path)) == iscc
    assert build.find_iscc(str(iscc)) == iscc
    with pytest.raises(build.BuildError, match="ISCC.exe not found"):
        build.find_iscc(str(tmp_path / "nowhere"))


def test_missing_nssm_fails_before_any_exe_is_built(tmp_path, monkeypatch, capsys):
    def must_not_build(target):
        raise AssertionError(f"built {target} before the installer prerequisites were checked")

    monkeypatch.setattr(build, "NSSM", tmp_path / "nssm.exe")
    monkeypatch.setattr(build, "build_exe", must_not_build)
    assert build.main(["all"]) == 1
    assert "BUILD FAILED: missing" in capsys.readouterr().err
