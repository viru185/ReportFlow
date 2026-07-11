"""Unit tests for file-dialog starting-location helpers."""

from __future__ import annotations

from reportflow.ui.fs_util import downloads_dir, open_start_dir, save_start_path


def test_downloads_dir_is_a_dir():
    assert downloads_dir().is_dir()


def test_open_start_dir_uses_selected_file_folder(tmp_path):
    f = tmp_path / "book.xlsx"
    f.write_text("x", encoding="utf-8")
    assert open_start_dir(str(f)) == str(tmp_path)


def test_open_start_dir_defaults_to_downloads():
    assert open_start_dir(None) == str(downloads_dir())
    assert open_start_dir("Z:/nope/missing.xlsx") == str(downloads_dir())


def test_save_start_path_appends_filename(tmp_path):
    assert save_start_path(str(tmp_path), "out.zip") == str(tmp_path / "out.zip")
    assert save_start_path(None, "out.zip").endswith("out.zip")
