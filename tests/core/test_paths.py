from __future__ import annotations

from reportflow.core import paths


def test_data_root_honors_override(temp_data_root):
    assert paths.data_root() == temp_data_root
    assert paths.config_file() == temp_data_root / "config" / "reportflow.toml"


def test_ensure_dirs_creates_tree(temp_data_root):
    paths.ensure_dirs()
    for d in (
        paths.config_dir(),
        paths.logs_dir(),
        paths.state_dir(),
        paths.runs_dir(),
        paths.templates_dir(),
    ):
        assert d.is_dir()


def test_run_dir_under_runs(temp_data_root):
    assert paths.run_dir("abc") == temp_data_root / "runs" / "abc"
