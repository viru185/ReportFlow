"""Offscreen PySide6 tests with a mock API client (no service, no Excel)."""

from __future__ import annotations

from reportflow.ui.api_client import ApiError


class FakeApi:
    def __init__(self, *, jobs=None, sheets=None, connected=True):
        self._jobs = jobs or []
        self._sheets = sheets or ["Summary", "Detail"]
        self._connected = connected

    def system_status(self):
        if not self._connected:
            raise ApiError("service not reachable")
        return {"version": "0.1.0", "active_runs": [], "scheduled_jobs": []}

    def list_jobs(self):
        if not self._connected:
            raise ApiError("service not reachable")
        return self._jobs

    def workbook_sheets(self, path):
        return self._sheets


def _check_all(dialog):
    from PySide6.QtCore import Qt

    for i in range(dialog.sheets.count()):
        dialog.sheets.item(i).setCheckState(Qt.CheckState.Checked)


def test_editor_builds_payload_with_recipients(qtbot):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    dlg = JobEditorDialog(FakeApi())
    qtbot.addWidget(dlg)

    dlg.name.setText("daily")
    dlg.workbook.setText("C:/t.xlsx")
    dlg.output_xlsx.setText("C:/out/{run_id}.xlsx")
    dlg.output_pdf.setText("C:/out/{run_id}_{sheet}.pdf")
    dlg._discover_sheets()
    _check_all(dlg)
    dlg.prod_to.setText("boss@corp.example.com, mgr@corp.example.com")
    dlg.test_to.setText("dev@corp.example.com")
    dlg.test_cc.setText("qa@corp.example.com")

    payload = dlg.payload()
    assert payload["name"] == "daily"
    assert payload["sheet_names"] == ["Summary", "Detail"]
    assert payload["prod"]["to"] == ["boss@corp.example.com", "mgr@corp.example.com"]
    assert payload["test"]["cc"] == ["qa@corp.example.com"]
    assert payload["prod"]["bcc"] == []  # optional, left empty
    assert payload["timeout_seconds"] is None  # 0 -> use default
    assert payload["concurrency_group"] is None


def test_editor_loads_existing_job(qtbot):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    job = {
        "name": "daily",
        "enabled": True,
        "workbook_template_path": "C:/t.xlsx",
        "output_xlsx_path": "C:/out.xlsx",
        "output_pdf_path": "C:/{sheet}.pdf",
        "sheet_names": ["Summary"],
        "prod": {"to": ["boss@corp.example.com"], "cc": ["ops@corp.example.com"]},
        "test": {"to": ["dev@corp.example.com"]},
        "notes": "hello",
    }
    dlg = JobEditorDialog(FakeApi(), job)
    qtbot.addWidget(dlg)

    assert dlg.name.text() == "daily"
    assert dlg.name.isReadOnly()  # name is the key
    assert dlg.prod_cc.text() == "ops@corp.example.com"
    assert dlg._checked_sheet_names() == ["Summary"]
    assert dlg.payload()["notes"] == "hello"


def test_main_window_populates_jobs(qtbot):
    from reportflow.ui.windows.main_window import MainWindow

    jobs = [
        {
            "name": "daily",
            "enabled": True,
            "schedule_cron": "0 6 * * *",
            "last_status": "success",
            "last_run_at": "2026-07-07T06:00:00",
        },
    ]
    win = MainWindow(FakeApi(jobs=jobs))
    qtbot.addWidget(win)

    assert win.table.rowCount() == 1
    assert win.table.item(0, 0).text() == "daily"
    assert win.banner.isHidden()


def test_main_window_shows_disconnected_banner(qtbot):
    from reportflow.ui.windows.main_window import MainWindow

    win = MainWindow(FakeApi(connected=False))
    qtbot.addWidget(win)

    assert not win.banner.isHidden()  # banner shown (isVisible needs the window shown)
    assert "not reachable" in win.banner.text()
