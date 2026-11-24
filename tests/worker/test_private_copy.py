"""The private copy of each workbook (0.16) — without Excel."""

from __future__ import annotations

import os
import stat
import zipfile
from pathlib import Path

import pytest

from reportflow.core.config.models import AppConfig
from reportflow.core.email.redaction import build_log_bundle
from reportflow.worker.private_copy import (
    PrivateCopyError,
    copy_for_run,
    relink_same_folder,
    remove_run_copies,
)

_RELS = "xl/externalLinks/_rels/externalLink1.xml.rels"


def _workbook(path: Path, rels: str | None = None) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/workbook.xml", "<workbook/>")
        if rels is not None:
            zf.writestr(_RELS, rels)


def _rels(*relationships: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(relationships)
        + "</Relationships>"
    )


def _link(target: str, rid: str = "rId1") -> str:
    return (
        f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        f'relationships/externalLinkPath" Target="{target}" TargetMode="External"/>'
    )


def test_the_copy_lands_in_the_run_folder_and_the_original_is_untouched(tmp_path):
    source = tmp_path / "plant" / "PI_Point_Health.xlsm"
    source.parent.mkdir()
    _workbook(source)
    os.chmod(source, stat.S_IREAD)  # read-only on disk: the copy must still be writable
    before = (source.read_bytes(), source.stat().st_mtime)
    try:
        copy = copy_for_run(source, tmp_path / "runs" / "r1", 0)
        assert copy == tmp_path / "runs" / "r1" / "inputs" / "0" / "PI_Point_Health.xlsm"
        assert copy.read_bytes() == before[0]
        assert os.access(copy, os.W_OK)
        assert (source.read_bytes(), source.stat().st_mtime) == before
    finally:
        os.chmod(source, stat.S_IREAD | stat.S_IWRITE)
    remove_run_copies(tmp_path / "runs" / "r1")
    assert not (tmp_path / "runs" / "r1" / "inputs").exists()


def test_a_missing_workbook_is_reported_plainly(tmp_path):
    with pytest.raises(PrivateCopyError, match="workbook template not found"):
        copy_for_run(tmp_path / "gone.xlsx", tmp_path / "run", 0)


def test_same_folder_links_point_back_at_the_original_folder(tmp_path):
    original = tmp_path / "E" / "reports"
    copy = tmp_path / "run" / "Main.xlsx"
    copy.parent.mkdir(parents=True)
    rels = _rels(
        _link("Source.xlsx", "rId1"),  # same folder: relative
        _link("../data/Prices%20&amp;%20Rates.xlsx", "rId2"),
        _link("file:///\\\\server\\share\\Other.xlsx", "rId3"),  # absolute: untouched
        _link("https://corp.example.com/book.xlsx", "rId4"),
    )
    _workbook(copy, rels)
    with zipfile.ZipFile(copy) as zf:
        others_before = {n: zf.read(n) for n in zf.namelist() if n != _RELS}
    assert relink_same_folder(copy, original) == 2
    with zipfile.ZipFile(copy) as zf:
        text = zf.read(_RELS).decode("utf-8")
        others_after = {n: zf.read(n) for n in zf.namelist() if n != _RELS}
    assert f'Target="file:///{original / "Source.xlsx"}"' in text
    assert f"file:///{tmp_path / 'E' / 'data' / 'Prices%20&amp;%20Rates.xlsx'}" in text
    assert 'Target="file:///\\\\server\\share\\Other.xlsx"' in text
    assert 'Target="https://corp.example.com/book.xlsx"' in text
    assert others_after == others_before  # nothing else in the file changes


def test_a_workbook_without_links_is_not_rewritten(tmp_path):
    copy = tmp_path / "Main.xlsx"
    _workbook(copy)
    before = copy.read_bytes()
    assert relink_same_folder(copy, tmp_path) == 0
    assert copy.read_bytes() == before


def test_export_logs_never_includes_a_runs_workbook_copies(tmp_path):
    from reportflow.core import paths

    run_dir = paths.run_dir("r1")
    (run_dir / "inputs" / "0").mkdir(parents=True)
    (run_dir / "inputs" / "0" / "Customer data.xlsx").write_bytes(b"secret")
    (run_dir / "worker.log").write_text("log", encoding="utf-8")
    bundle = build_log_bundle(tmp_path / "bundle.zip", AppConfig(), run_ids=["r1"])
    with zipfile.ZipFile(bundle) as zf:
        names = zf.namelist()
    assert "runs/r1/worker.log" in [n.replace("\\", "/") for n in names]
    assert not any("inputs" in n for n in names)
