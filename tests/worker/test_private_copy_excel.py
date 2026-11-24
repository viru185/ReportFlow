"""The private copy against real Excel (0.16). Marked ``excel`` (skipped in CI).

The field problem: a workbook someone had open made the run open it read-only (133 runs on
the customer server). With a private copy, the run always gets its own writable workbook.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import xlwings as xw

from reportflow.core.ipc import RunStatus
from reportflow.worker.private_copy import copy_for_run
from reportflow.worker.runner import run_job

from .test_worker_excel import _make_workbook, _request

pytestmark = pytest.mark.excel


# "Someone has it open": another Excel, in its own process (the run's COM teardown would
# disconnect an Excel this test thread opened).
_HOLDER = """
import sys
import xlwings as xw
app = xw.App(visible=False, add_book=False)
try:
    book = app.books.open(sys.argv[1])
    print("read-only" if book.api.ReadOnly else "writable", flush=True)
    sys.stdin.read()
finally:
    app.quit()
"""


def _run_while_open_elsewhere(tmp_path: Path, *, private_copy: bool):
    tmp_path.mkdir(parents=True)
    source = tmp_path / "template.xlsx"
    _make_workbook(source)
    before = source.read_bytes()
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(source)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        assert holder.stdout is not None and holder.stdin is not None
        assert holder.stdout.readline().strip() == "writable"
        result = run_job(_request(tmp_path, ["Summary"], private_copy=private_copy))
        holder.stdin.close()
        holder.wait(timeout=60)
    finally:
        if holder.poll() is None:
            holder.kill()
    return result, before, source.read_bytes()


def test_a_workbook_open_elsewhere_is_no_longer_opened_read_only(tmp_path):
    old, _, _ = _run_while_open_elsewhere(tmp_path / "old", private_copy=False)
    assert any("read-only" in w for w in old.warnings)  # the field problem, reproduced
    new, before, after = _run_while_open_elsewhere(tmp_path / "new", private_copy=True)
    assert new.status is RunStatus.SUCCESS
    assert not any("read-only" in w for w in new.warnings)
    assert after == before  # the original is never written
    assert not (tmp_path / "new" / "inputs").exists()  # the copy is gone afterwards


def test_a_same_folder_link_still_points_at_the_original_folder(tmp_path):
    folder = tmp_path / "reports"
    folder.mkdir()
    app = xw.App(visible=False, add_book=False)
    try:
        app.api.DisplayAlerts = False
        source = app.books.add()
        source.sheets[0].api.Range("A1").Value2 = 42
        source.save(str(folder / "Source.xlsx"))
        main = app.books.add()
        main.sheets[0].api.Range("A1").Formula = "=[Source.xlsx]Sheet1!$A$1"
        main.save(str(folder / "Main.xlsx"))
        main.close()
        source.close()
        copy = copy_for_run(folder / "Main.xlsx", tmp_path / "run", 0)
        opened = app.books.open(str(copy), update_links=False)
        links = [str(link) for link in (opened.api.LinkSources(1) or ())]
        opened.close()
    finally:
        app.quit()
    assert links == [str(folder / "Source.xlsx")]
