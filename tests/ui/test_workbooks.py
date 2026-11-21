"""The workbook list: add/drop/replace/remove, and sheets read in the background."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent

from reportflow.ui.api_client import ApiError
from reportflow.ui.feedback import toasts
from reportflow.ui.sheet_loader import InlineExecutor, ManualExecutor, PoolExecutor, SheetLoader
from reportflow.ui.windows.job_editor import JobEditorDialog, _SheetRow, merge_sheets

from .test_ui import FakeApi, _sample_job_dict, _sheet_cell


class SheetApi(FakeApi):
    """Sheets per file; ``fail`` maps a file name to the ApiError its read raises."""

    def __init__(self, files=None, fail=None, executor=None, **kw):
        super().__init__(**kw)
        self.files = files or {}
        self.fail = fail or {}
        self.reads: list[str] = []
        self.sheet_executor = executor or InlineExecutor()

    def workbook_sheets(self, path):
        self.reads.append(path)
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        if name in self.fail:
            raise self.fail[name]
        return self.files.get(name, ["Summary", "Detail"])


def _editor(qtbot, api, job=None):
    dlg = JobEditorDialog(api, job)
    qtbot.addWidget(dlg)
    return dlg


# -- merging -------------------------------------------------------------------------


def test_merge_keeps_choices_and_flags_vanished_sheets_in_place():
    rows = [
        _SheetRow("Summary", True, pdf=False),
        _SheetRow("Inputs", True),
        _SheetRow("Raw", False),
        _SheetRow("Detail", True, hidden=True),
    ]
    merged = merge_sheets(rows, ["Summary", "Detail", "New"], tick_all=False)
    assert [(r.name, r.include, r.missing) for r in merged] == [
        ("Summary", True, False),
        ("Inputs", True, True),  # included, gone: kept where it was, flagged
        ("Detail", True, False),
        ("New", False, False),  # a new sheet arrives unticked
    ]
    assert merged[0].pdf is False and merged[2].hidden is True  # choices kept
    # "Raw" was not included and is gone: dropped quietly.


def test_merge_ticks_everything_only_for_a_fresh_workbook_with_nothing_ticked():
    assert all(r.include for r in merge_sheets([], ["A", "B"], tick_all=True))
    assert not any(r.include for r in merge_sheets([], ["A", "B"], tick_all=False))
    kept = merge_sheets([_SheetRow("A", True)], ["A", "B"], tick_all=True)
    assert [r.include for r in kept] == [True, False]


# -- reading in the background ---------------------------------------------------------


def test_a_late_answer_never_overwrites_a_newer_one(qtbot):
    manual = ManualExecutor()
    api = SheetApi(executor=manual, files={"t.xlsx": ["Summary", "Detail"]})
    dlg = _editor(qtbot, api, _sample_job_dict())
    wb = dlg._workbooks[0]
    assert dlg.wb_list.rows()[0].status.text() == "Reading sheets…"
    api.files["t.xlsx"] = ["Summary", "Detail", "Extra"]
    dlg._request_read(wb, force=True)  # a second, newer read
    manual.finish(1)  # the newer one answers first
    manual.finish(0)  # the older one arrives late — dropped
    assert [r.name for r in wb.rows] == ["Summary", "Detail", "Extra"]


def test_an_answer_lands_in_its_own_workbook_even_when_another_is_shown(qtbot):
    manual = ManualExecutor()
    api = SheetApi(executor=manual, files={"a.xlsx": ["A1"], "b.xlsx": ["B1", "B2"]})
    dlg = _editor(qtbot, api)
    dlg.add_workbooks(["C:/a.xlsx", "C:/b.xlsx"])
    assert dlg._current().path == "C:/b.xlsx"
    manual.finish(0)  # a.xlsx answers while b.xlsx is on screen
    assert [r.name for r in dlg._workbooks[0].rows] == ["A1"]
    assert dlg.sheets.rowCount() == 0  # the table still shows b, still reading
    manual.finish(0)
    assert dlg._checked_sheet_names() == ["B1", "B2"]


def test_an_answer_for_a_removed_workbook_goes_nowhere(qtbot):
    manual = ManualExecutor()
    dlg = _editor(qtbot, SheetApi(executor=manual))
    dlg.add_workbooks(["C:/a.xlsx", "C:/b.xlsx"])
    dlg._remove_workbook(0)
    manual.finish_all()
    assert [wb.path for wb in dlg._workbooks] == ["C:/b.xlsx"]
    assert dlg._checked_sheet_names() == ["Summary", "Detail"]


def test_a_stopped_service_is_not_a_missing_file_and_saving_still_works(qtbot):
    api = SheetApi(fail={"t.xlsx": ApiError("service not reachable")})
    dlg = _editor(qtbot, api, _sample_job_dict())
    wb = dlg._workbooks[0]
    assert wb.read == "offline"
    assert "not refreshed" in dlg.wb_list.rows()[0].status.text()
    assert "isn't reachable" in dlg.wb_banner_text.text()
    assert dlg._validation_error() is None  # the saved choices still save


def test_a_missing_file_says_so_and_keeps_the_choices(qtbot):
    api = SheetApi(fail={"t.xlsx": ApiError("can't find it", 404)})
    dlg = _editor(qtbot, api, _sample_job_dict())
    assert dlg.wb_list.rows()[0].status.text() == "⚠ File not found"
    assert dlg.wb_banner.isVisibleTo(dlg) and dlg.wb_banner_replace.isVisibleTo(dlg)
    assert dlg._checked_sheet_names() == ["Summary"]
    assert dlg._validation_error() is None


def test_a_vanished_sheet_is_shown_and_blocks_save_until_unticked(qtbot):
    api = SheetApi(files={"t.xlsx": ["Detail"]})  # "Summary" is gone from the file
    dlg = _editor(qtbot, api, _sample_job_dict())
    assert "not in the file any more" in dlg.sheets.item(0, 0).text()
    assert dlg.wb_list.rows()[0].status.text() == "⚠ 1 sheet missing"
    tab, message = dlg._validation_error()
    assert tab == 0 and "Summary is no longer in the workbook" in message
    dlg.sheets.item(0, 1).setCheckState(Qt.CheckState.Unchecked)
    _sheet_cell(dlg, "Detail", 1).setCheckState(Qt.CheckState.Checked)
    assert dlg._validation_error() is None


def test_selecting_and_returning_to_the_window_reread_at_most_every_few_seconds(qtbot):
    api = SheetApi()
    dlg = _editor(qtbot, api)
    dlg.add_workbooks(["C:/a.xlsx", "C:/b.xlsx"])
    reads = len(api.reads)
    dlg.wb_list.list.setCurrentRow(0)
    dlg._on_reactivated()
    assert len(api.reads) == reads  # read moments ago: not again
    for wb in dlg._workbooks:
        wb.last_read -= 60
    dlg._on_reactivated()
    assert len(api.reads) == reads + 2  # back from Excel: every workbook is read again


def test_opening_and_reading_a_job_is_not_an_unsaved_change(qtbot):
    dlg = _editor(qtbot, SheetApi(), _sample_job_dict())
    assert dlg.sheets.rowCount() == 2  # "Detail" was read in, unticked
    assert not dlg.is_dirty()


def test_real_background_threads_deliver_on_the_ui_thread(qtbot):
    api = SheetApi(executor=PoolExecutor.shared(), files={"t.xlsx": ["One", "Two", "Three"]})
    dlg = _editor(qtbot, api, _sample_job_dict())
    qtbot.waitUntil(lambda: dlg._workbooks[0].read == "ok", timeout=5000)
    names = [r.name for r in dlg._workbooks[0].rows]
    assert names == ["Summary", "One", "Two", "Three"]  # the saved sheet, now flagged missing


def test_the_loader_drops_results_after_close(qtbot):
    manual = ManualExecutor()
    loader = SheetLoader(lambda p: ["A"], manual)
    got = []
    loader.loaded.connect(lambda *a: got.append(a))
    loader.request(1, "C:/a.xlsx")
    loader.close()
    manual.finish_all()
    assert got == []


# -- adding, dropping, replacing, removing ---------------------------------------------


def test_a_new_job_shows_the_drop_zone_and_needs_a_workbook(qtbot):
    dlg = _editor(qtbot, SheetApi())
    assert dlg.wb_stack.currentWidget() is dlg.empty_zone
    dlg.name.setText("j")
    _tab, message = dlg._validation_error()
    assert message.startswith("Add at least one workbook")


def test_dropping_files_adds_the_excel_ones_and_explains_the_rest(qtbot):
    dlg = _editor(qtbot, SheetApi(), _sample_job_dict())
    dlg._add_paths(
        [
            "C:/data/Sales.xlsx",
            "C:/data/notes.pdf",
            "C:/data/~$Sales.xlsx",  # Excel's lock file
            "C:\\T.XLSX",  # already in the job, spelled differently
            "C:/data/Sales.xlsx",  # twice in one drop
        ]
    )
    assert [wb.path for wb in dlg._workbooks] == ["C:/t.xlsx", "C:/data/Sales.xlsx"]
    [message] = toasts(dlg)
    assert "Already in this job: T.XLSX, Sales.xlsx" in message
    assert "Not an Excel workbook (.xlsx, .xlsm): notes.pdf, ~$Sales.xlsx" in message


def test_a_real_drop_event_on_the_general_tab(qtbot):
    dlg = _editor(qtbot, SheetApi())
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("C:/data/Energy.xlsx")])
    page = dlg.tabs.widget(0).widget()
    event = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    assert dlg._drops.eventFilter(page, event)
    qtbot.waitUntil(lambda: len(dlg._workbooks) == 1, timeout=2000)
    assert dlg._workbooks[0].path.endswith("Energy.xlsx")
    assert dlg.wb_stack.currentWidget() is dlg.wb_split


def test_remove_has_undo(qtbot):
    dlg = _editor(qtbot, SheetApi(), _sample_job_dict())
    dlg.add_workbooks(["C:/data/b.xlsx"])
    removed = dlg._workbooks[1]
    dlg._remove_workbook(1)
    assert len(dlg._workbooks) == 1 and "Removed b.xlsx." in toasts(dlg)
    dlg._restore_workbook(1, removed)
    assert [wb.path for wb in dlg._workbooks] == ["C:/t.xlsx", "C:/data/b.xlsx"]


@pytest.mark.parametrize(("width", "orientation"), [(600, "Vertical"), (1100, "Horizontal")])
def test_list_and_sheets_stack_in_a_narrow_window(qtbot, width, orientation):
    dlg = _editor(qtbot, SheetApi(), _sample_job_dict())
    dlg.resize(width, 700)
    dlg.show()
    qtbot.waitExposed(dlg)
    qtbot.waitUntil(lambda: dlg.wb_split.orientation().name == orientation, timeout=2000)
