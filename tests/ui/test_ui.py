"""Offscreen PySide6 tests with a mock API client (no service, no Excel)."""

from __future__ import annotations

from reportflow.ui.api_client import ApiError


class FakeApi:
    base_url = "http://127.0.0.1:8787"

    def __init__(self, *, jobs=None, sheets=None, connected=True, is_system=False, runs=None):
        self._jobs = jobs or []
        self._sheets = sheets or ["Summary", "Detail"]
        self._connected = connected
        self._is_system = is_system
        self._runs = runs or []
        self.saved_settings = None
        self.saved_template = None
        self.triggered = []
        self.exported = False

    def _check(self):
        if not self._connected:
            raise ApiError("service not reachable")

    config_error = None

    def system_status(self):
        self._check()
        return {
            "version": "0.2.0",
            "active_runs": ["r1"],
            "scheduled_jobs": ["a#0", "a#1"],
            "config_error": self.config_error,
            "service_account": "WORKGROUP\\HOST$" if self._is_system else "CORP\\pi_reports",
            "service_account_is_system": self._is_system,
        }

    def run_job(self, name):
        self.triggered.append(("run", name))
        return {"run_id": "r-run"}

    def dry_run_job(self, name):
        self.triggered.append(("dry", name))
        return {"run_id": "r-dry"}

    def set_job_stage(self, name, stage):
        self.staged = (name, stage)
        return {"ok": True, "name": name, "stage": stage}

    def list_runs(self, job=None, limit=50):
        return self._runs

    def get_run_log(self, run_id):
        return {"log": "line\n" * 200}

    def export_logs(self, note=""):
        self.exported = True
        self.export_note = note
        return {"bundle": self._bundle}

    def send_dev_logs(self, note=""):
        self.sent_note = note
        return {"recipients": ["dev@x.com"]}

    def purge_logs(self, older_than_days=None, *, everything=False):
        self.purged = (older_than_days, everything)
        return {
            "ok": True,
            "run_dirs": 3,
            "bundles": 1,
            "log_files": 2,
            "db_rows": 3,
            "bytes_freed": 5_000_000,
        }

    def get_service_account(self):
        return {
            "account": "WORKGROUP\\HOST$" if self._is_system else "CORP\\pi_reports",
            "is_system": self._is_system,
        }

    def set_service_account(self, user, password):
        self.applied_account = (user, password)
        return {"ok": True, "account": user, "restarting": True}

    def list_jobs(self):
        self._check()
        return self._jobs

    def get_job(self, name):
        for j in self._jobs:
            if j.get("name") == name:
                return {"job": dict(j)}
        raise ApiError(f"unknown job: {name}", 404)

    def update_job(self, name, job):
        self.updated_job = (name, job)
        return {"ok": True, "name": name}

    def delete_job(self, name):
        self.deleted_job = name
        return {"ok": True}

    def create_job(self, job):
        self.created_job = job
        return {"ok": True, "name": job.get("name")}

    def workbook_sheets(self, path):
        return self._sheets

    def get_config(self):
        return {
            "smtp": {
                "host": "smtp.x.com",
                "port": 587,
                "use_starttls": True,
                "from_address": "rf@x.com",
                "username": "rf@x.com",
            },
            "test": {"recipients": ["dev@x.com"], "developer_bundle_recipients": ["dev@x.com"]},
            "app": {
                "api_host": "127.0.0.1",
                "api_port": 8787,
                "max_global_concurrency": 4,
                "default_timeout_seconds": 900,
                "log_retention_days": 30,
            },
            # Startup update checks stay off in tests so no thread hits the network.
            "ui": {"api_base_url": "http://127.0.0.1:8787", "check_updates_on_startup": False},
        }

    def smtp_password_status(self):
        return True

    def smtp_test(self, smtp):
        self.smtp_tested = smtp
        return {"ok": True}

    def update_settings(self, sections):
        self.saved_settings = sections
        return {"ok": True}

    def get_email_template(self, job_name):
        return {"content": "", "exists": False}

    def put_email_template(self, job_name, content):
        self.saved_template = (job_name, content)
        return {"ok": True}

    def system_logs(self, process="service", tail=500):
        return f"log line from {process}"


def _check_all(dialog):
    """Include every sheet of the workbook shown in the editor."""
    from PySide6.QtCore import Qt

    for r in range(dialog.sheets.rowCount()):
        dialog.sheets.item(r, 1).setCheckState(Qt.CheckState.Checked)


def _sheet_cell(dialog, sheet, col):
    """The sheet table's checkbox item for ``sheet`` in column 1 Include / 2 PDF / 3 Hidden."""
    for r in range(dialog.sheets.rowCount()):
        if dialog.sheets.item(r, 0).text() == sheet:
            return dialog.sheets.item(r, col)
    raise AssertionError(f"no row for sheet {sheet!r}")


def _sample_job_dict():
    # Doubles as the API's job (editor) and its summary (dashboard card).
    return {
        "name": "daily",
        "enabled": True,
        "stage": "testing",
        "prod_recipients": ["boss@corp.example.com"],
        "workbooks": [
            {
                "input_excel_path": "C:/t.xlsx",
                "sheets": [{"name": "Summary", "pdf": True, "hidden": False}],
                "unselected_sheets": "remove",
            }
        ],
        "workbook_count": 1,
        "sheet_count": 1,
        "output_dir": "C:/reports",
        "output_name": "{job}_{date}",
        "schedule_crons": ["0 6 * * *", "0 18 * * *"],
        "prod": {"to": ["boss@corp.example.com"], "cc": ["ops@corp.example.com"]},
        "test": {"to": ["dev@corp.example.com"]},
        "notes": "hello",
        "last_status": "success",
        "last_run_at": "2026-07-07T06:00:00",
    }


# -- job editor -----------------------------------------------------------------


def test_editor_builds_payload_with_new_fields(qtbot):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    dlg = JobEditorDialog(FakeApi())
    qtbot.addWidget(dlg)

    dlg.name.setText("daily")
    dlg.input_excel.setText("C:/t.xlsx")
    dlg.output_dir.setText("C:/reports")
    dlg._discover_sheets()
    _check_all(dlg)
    dlg.prod_to.setText("boss@corp.example.com, mgr@corp.example.com")
    dlg.test_to.setText("dev@corp.example.com")
    dlg.test_cc.setText("qa@corp.example.com")
    dlg.schedule.load(["0 6 * * *"])

    payload = dlg.payload()
    [wb] = payload["workbooks"]
    assert wb["input_excel_path"] == "C:/t.xlsx"
    assert payload["output_dir"] == "C:/reports"
    assert payload["output_name"] is None  # left empty -> default stem
    assert [s["name"] for s in wb["sheets"]] == ["Summary", "Detail"]
    assert all(s["pdf"] and not s["hidden"] for s in wb["sheets"])  # PDF on, visible
    assert payload["on_workbook_failure"] == "fail_run"
    assert payload["schedule_crons"] == ["0 6 * * *"]
    assert payload["prod"]["to"] == ["boss@corp.example.com", "mgr@corp.example.com"]
    assert payload["test"]["cc"] == ["qa@corp.example.com"]
    assert payload["prod"]["bcc"] == []
    assert payload["timeout_seconds"] is None
    assert payload["concurrency_group"] is None


def test_editor_loads_existing_job(qtbot):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    dlg = JobEditorDialog(FakeApi(), _sample_job_dict())
    qtbot.addWidget(dlg)

    assert dlg.name.text() == "daily"
    assert dlg.name.isReadOnly()  # name is the key
    assert dlg.output_dir.text() == "C:/reports"
    assert dlg.prod_cc.text() == "ops@corp.example.com"
    assert dlg._checked_sheet_names() == ["Summary"]
    assert dlg.payload()["notes"] == "hello"
    # schedule round-trips through the widget
    assert dlg.payload()["schedule_crons"] == ["0 6 * * *", "0 18 * * *"]


def test_editor_new_job_discovery_checks_all_sheets(qtbot):
    from PySide6.QtCore import Qt

    from reportflow.ui.windows.job_editor import JobEditorDialog

    dlg = JobEditorDialog(FakeApi())
    qtbot.addWidget(dlg)
    dlg.input_excel.setText("C:/t.xlsx")
    dlg._discover_sheets()
    # New job: everything ticked by default (export-all is the common case).
    assert dlg._checked_sheet_names() == ["Summary", "Detail"]

    # A deliberate partial selection survives re-discovery (no re-check-all).
    _sheet_cell(dlg, "Detail", 1).setCheckState(Qt.CheckState.Unchecked)
    dlg._discover_sheets()
    assert dlg._checked_sheet_names() == ["Summary"]


def test_editor_output_example_updates(qtbot):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    dlg = JobEditorDialog(FakeApi())
    qtbot.addWidget(dlg)
    dlg.name.setText("sales")
    dlg.output_name.setText("{job}_custom")
    assert "sales_custom.xlsx" in dlg.output_example.text()
    assert "overwrites" in dlg.output_example.text()  # no time token -> same-day warning
    dlg.output_name.setText("{job}_{date}_{time}")
    assert "overwrites" not in dlg.output_example.text()
    dlg.output_name.clear()  # the default carries the time
    assert "overwrites" not in dlg.output_example.text()


# -- schedule widget -------------------------------------------------------------


def test_schedule_widget_round_trip(qtbot):
    from reportflow.ui.windows.schedule_widget import ScheduleWidget

    w = ScheduleWidget()
    qtbot.addWidget(w)

    w.load(["0 6 * * MON,WED", "30 18 * * MON,WED"])
    [rule] = w.to_rules()
    assert rule.kind == "weekly"
    assert rule.weekdays == ["MON", "WED"]
    assert rule.times == ["06:00", "18:30"]
    assert w.to_crons() == ["0 6 * * MON,WED", "30 18 * * MON,WED"]


def test_schedule_widget_manual_default(qtbot):
    from reportflow.ui.windows.schedule_widget import ScheduleWidget

    w = ScheduleWidget()
    qtbot.addWidget(w)
    assert w.to_crons() == []
    assert not w.manual_hint.isHidden()


def test_schedule_widget_advanced_fallback(qtbot):
    from reportflow.ui.windows.schedule_widget import ScheduleWidget

    w = ScheduleWidget()
    qtbot.addWidget(w)
    w.load(["*/5 * * * *"])
    assert [r.kind for r in w.to_rules()] == ["cron"]
    assert w.to_crons() == ["*/5 * * * *"]


def test_schedule_widget_combines_rules_and_deletes_in_one_click(qtbot):
    from PySide6.QtCore import QTime
    from PySide6.QtWidgets import QPushButton

    from reportflow.ui.schedule_compile import ScheduleRule
    from reportflow.ui.windows.schedule_widget import ScheduleWidget

    w = ScheduleWidget()
    qtbot.addWidget(w)
    daily = w.add_rule(ScheduleRule(kind="daily"))
    daily.time_edit.setTime(QTime(6, 0))
    daily._add_time()
    daily.time_edit.setTime(QTime(18, 0))
    daily._add_time()
    sunday = w.add_rule(ScheduleRule(kind="weekly"))
    sunday.weekday_checks["SUN"].setChecked(True)
    sunday.time_edit.setTime(QTime(10, 0))
    sunday._add_time()
    assert w.to_crons() == ["0 6 * * *", "0 18 * * *", "0 10 * * SUN"]
    assert w.summary.text() == "Daily at 06:00, 18:00; Weekly Sun at 10:00"

    # Each time chip deletes itself — no "select, then Remove selected".
    chip = next(b for b in daily.findChildren(QPushButton) if b.text().startswith("18:00"))
    chip.click()
    assert daily.times() == ["06:00"]

    # A whole rule goes with its own Delete.
    delete = next(b for b in sunday.findChildren(QPushButton) if "Delete" in b.text())
    delete.click()
    assert w.to_crons() == ["0 6 * * *"]

    # An overlap is explained right under the rules, and blocks saving.
    clash = w.add_rule(ScheduleRule(kind="weekly", weekdays=["SUN"], times=["06:00"]))
    assert "already in the daily schedule" in w.summary.text()
    clash.remove_requested.emit(clash)
    assert w.summary.text() == "Daily at 06:00"


# -- main window ------------------------------------------------------------------


def test_main_window_dashboard_cards(qtbot):
    from reportflow.ui.windows.main_window import MainWindow

    win = MainWindow(FakeApi(jobs=[_sample_job_dict()]))
    qtbot.addWidget(win)

    assert win.card_jobs[1].text() == "1"
    assert win.card_active[1].text() == "1"
    assert win.card_failures[1].text() == "0"
    # one job card + trailing stretch
    assert win.jobs_layout.count() == 2
    assert "Connected" in win.conn_label.text()


def test_main_window_card_counts_files_and_sheets(qtbot):
    from PySide6.QtWidgets import QLabel

    from reportflow.ui.windows.main_window import MainWindow

    multi = dict(_sample_job_dict(), workbook_count=2, sheet_count=7)
    win = MainWindow(FakeApi(jobs=[multi]))
    qtbot.addWidget(win)
    assert any("2 files · 7 sheet(s)" in w.text() for w in win.findChildren(QLabel))


def test_main_window_failure_count(qtbot):
    from reportflow.ui.windows.main_window import MainWindow

    failed = dict(_sample_job_dict(), name="bad", last_status="failed")
    win = MainWindow(FakeApi(jobs=[_sample_job_dict(), failed]))
    qtbot.addWidget(win)
    assert win.card_failures[1].text() == "1"


def test_main_window_disconnected_state(qtbot):
    from reportflow.ui.windows.main_window import MainWindow

    win = MainWindow(FakeApi(connected=False))
    qtbot.addWidget(win)
    assert "not reachable" in win.conn_label.text()


def test_main_window_surfaces_config_error(qtbot):
    from reportflow.ui.windows.main_window import MainWindow

    api = FakeApi(jobs=[])
    api.config_error = "could not parse reportflow.toml: Illegal character"
    win = MainWindow(api)
    qtbot.addWidget(win)

    assert "configuration file is invalid" in win.statusBar().currentMessage()
    assert "Illegal character" in win.conn_label.toolTip()


def _card_frames(win):
    from PySide6.QtWidgets import QFrame

    return [f for f in win.jobs_container.findChildren(QFrame) if f.property("card")]


def _card_menu(win):
    """The ⋯ menu of the first job card."""
    from PySide6.QtWidgets import QToolButton

    buttons = win.jobs_container.findChildren(QToolButton)
    assert buttons, "job card has no ⋯ menu button"
    return buttons[0].menu()


def test_main_window_testing_card_buttons_and_pill(qtbot):
    from PySide6.QtWidgets import QLabel, QPushButton

    from reportflow.ui.windows.main_window import MainWindow

    win = MainWindow(FakeApi(jobs=[_sample_job_dict()]))  # stage: testing
    qtbot.addWidget(win)
    labels = [b.text() for b in win.jobs_container.findChildren(QPushButton)]
    # Daily single-click actions + the promote button; nothing else visible on the card.
    assert any("Run" in t for t in labels)
    assert any("Build only" in t for t in labels)
    assert any("Go live" in t for t in labels)
    assert len(labels) == 3  # everything occasional lives behind ⋯
    assert any(w.text() == "TESTING" for w in win.findChildren(QLabel))
    # The last-run status lives on the card edge + detail line, not in a pill.
    assert _card_frames(win)[0].property("edge") == "success"
    assert not any(w.text().startswith("success") for w in win.findChildren(QLabel))


def test_main_window_card_more_menu_holds_occasional_actions(qtbot):
    from reportflow.ui.windows.main_window import MainWindow

    win = MainWindow(FakeApi(jobs=[_sample_job_dict()]))  # enabled, testing
    qtbot.addWidget(win)
    texts = [a.text() for a in _card_menu(win).actions() if a.text()]
    assert texts == ["📂 Open last report", "✎ Edit", "Logs", "⧉ Duplicate", "⏸ Pause", "🗑 Delete"]


def test_main_window_card_menu_delete_action_wired(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from reportflow.ui.windows.main_window import MainWindow

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    api = FakeApi(jobs=[_sample_job_dict()])
    win = MainWindow(api)
    qtbot.addWidget(win)
    delete = next(a for a in _card_menu(win).actions() if "Delete" in a.text())
    delete.trigger()
    assert api.deleted_job == "daily"


def test_main_window_refresh_keeps_open_card_menu(qtbot, monkeypatch):
    """The 4 s auto-refresh must not rebuild the cards while a ⋯ menu is open (it used
    to delete the card — and the open menu with it — under the user's cursor)."""
    from PySide6.QtWidgets import QApplication

    from reportflow.ui.windows.main_window import MainWindow

    api = FakeApi(jobs=[_sample_job_dict()])
    win = MainWindow(api)
    qtbot.addWidget(win)
    rebuilds = []
    original_populate = win._populate

    def counting_populate(jobs):
        rebuilds.append(1)
        original_populate(jobs)

    monkeypatch.setattr(win, "_populate", counting_populate)

    api._jobs = [dict(_sample_job_dict(), last_status="failed")]  # data changed meanwhile
    monkeypatch.setattr(QApplication, "activePopupWidget", staticmethod(lambda: object()))
    win.refresh()
    assert rebuilds == []  # deferred while the menu is open
    assert win.card_failures[1].text() == "1"  # header stats still update

    monkeypatch.setattr(QApplication, "activePopupWidget", staticmethod(lambda: None))
    _card_menu(win).aboutToHide.emit()
    qtbot.waitUntil(lambda: rebuilds == [1])  # the pending rebuild runs once it closes


def test_main_window_refresh_skips_identical_rebuild(qtbot, monkeypatch):
    from reportflow.ui.windows.main_window import MainWindow

    win = MainWindow(FakeApi(jobs=[_sample_job_dict()]))
    qtbot.addWidget(win)
    rebuilds = []
    monkeypatch.setattr(win, "_populate", lambda jobs: rebuilds.append(1))
    win.refresh()  # may rebuild once if the minute rolled over since the constructor
    rebuilds.clear()
    win.refresh()
    assert rebuilds == []  # nothing changed -> no teardown/rebuild


def test_main_window_live_card_hides_go_live(qtbot):
    from PySide6.QtWidgets import QLabel, QPushButton

    from reportflow.ui.windows.main_window import MainWindow

    live = dict(_sample_job_dict(), stage="live")
    win = MainWindow(FakeApi(jobs=[live]))
    qtbot.addWidget(win)
    labels = [b.text() for b in win.findChildren(QPushButton)]
    assert not any("Go live" in t for t in labels)
    assert any(w.text() == "LIVE" for w in win.findChildren(QLabel))


def test_main_window_disabled_card_is_unmissable(qtbot):
    from PySide6.QtWidgets import QLabel, QPushButton

    from reportflow.ui.windows.main_window import MainWindow

    disabled = dict(_sample_job_dict(), enabled=False)
    win = MainWindow(FakeApi(jobs=[disabled]))
    qtbot.addWidget(win)

    # The whole card is dimmed via a graphics effect, with a muted status edge…
    frames = _card_frames(win)
    assert frames and frames[0].graphicsEffect() is not None
    assert frames[0].property("edge") == "muted"
    # …with a loud pill, a paused schedule line, and a one-click Resume.
    labels = [w.text() for w in win.findChildren(QLabel)]
    assert any("⏸ PAUSED" in t for t in labels)
    assert any("schedule paused" in t for t in labels)
    buttons = [b.text() for b in win.jobs_container.findChildren(QPushButton)]
    assert any("Resume" in t for t in buttons)
    # Pause disappears from the menu; Go live stays reachable there (Resume took its slot).
    texts = [a.text() for a in _card_menu(win).actions() if a.text()]
    assert "⏸ Pause" not in texts
    assert "✓ Go live" in texts


def test_main_window_enabled_card_not_dimmed_and_has_pause(qtbot):
    from PySide6.QtWidgets import QPushButton

    from reportflow.ui.windows.main_window import MainWindow

    win = MainWindow(FakeApi(jobs=[_sample_job_dict()]))
    qtbot.addWidget(win)
    frames = _card_frames(win)
    assert frames and frames[0].graphicsEffect() is None
    texts = [a.text() for a in _card_menu(win).actions() if a.text()]
    assert "⏸ Pause" in texts
    buttons = [b.text() for b in win.jobs_container.findChildren(QPushButton)]
    assert not any("Resume" in t for t in buttons)


def test_main_window_pause_and_resume_flip_enabled(qtbot):
    from reportflow.ui.windows.main_window import MainWindow

    api = FakeApi(jobs=[_sample_job_dict()])
    win = MainWindow(api)
    qtbot.addWidget(win)

    win._set_enabled("daily", False)
    name, payload = api.updated_job
    assert name == "daily" and payload["enabled"] is False

    win._set_enabled("daily", True)
    _, payload = api.updated_job
    assert payload["enabled"] is True


def test_main_window_running_card_locks_run_buttons(qtbot):
    from datetime import datetime

    from PySide6.QtWidgets import QLabel, QPushButton

    from reportflow.ui.windows.main_window import MainWindow

    running = dict(
        _sample_job_dict(),
        last_status="running",
        last_run_at=datetime.now().isoformat(timespec="seconds"),
    )
    win = MainWindow(FakeApi(jobs=[running]))
    qtbot.addWidget(win)

    by_text = {b.text(): b for b in win.jobs_container.findChildren(QPushButton)}
    assert not by_text["▶ Run"].isEnabled()
    assert not by_text["👁 Build only"].isEnabled()
    # Occasional actions in ⋯ stay usable while a run is in flight.
    edit = next(a for a in _card_menu(win).actions() if "Edit" in a.text())
    assert edit.isEnabled()
    # The badge carries a live elapsed suffix (e.g. "running · 3s"); the edge turns amber.
    assert any("running ·" in w.text() for w in win.findChildren(QLabel))
    assert _card_frames(win)[0].property("edge") == "running"


def test_main_window_open_last_report(qtbot, tmp_path, monkeypatch):
    from reportflow.ui.windows import main_window as mw

    report = tmp_path / "MD DPR_20260722.xlsx"
    report.write_bytes(b"PK\x03\x04")
    opened = []
    monkeypatch.setattr(mw.subprocess, "Popen", lambda args, **k: opened.append(args) or None)
    win = mw.MainWindow(FakeApi(jobs=[]))
    qtbot.addWidget(win)

    win._open_last_report({"last_output_xlsx": str(report)})
    assert opened and opened[0][0] == "explorer" and str(report) in opened[0]

    win._open_last_report({"last_output_xlsx": None})
    assert "No successful report yet" in win.statusBar().currentMessage()


def test_duplicate_prefills_editor_as_fresh_testing_job(qtbot):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    source = dict(
        _sample_job_dict(),
        stage="live",
        enabled=False,
        email_template_path="C:/ProgramData/ReportFlow/templates/jobs/daily.html",
    )
    dlg = JobEditorDialog(FakeApi(), None, prefill=source)
    qtbot.addWidget(dlg)

    assert dlg.name.text() == "" and not dlg.name.isReadOnly()  # fresh, editable name
    assert dlg.stage.currentData() == "testing" and not dlg.stage.isEnabled()
    assert dlg.enabled.isChecked()
    assert dlg.output_dir.text() == "C:/reports"  # settings copied
    dlg.name.setText("daily_copy")
    payload = dlg.payload()
    assert payload["stage"] == "testing"
    assert "email_template_path" not in payload  # template never shared between jobs
    assert "not copied" in dlg.template_status.text()


def test_main_window_go_live_confirms_and_calls_api(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from reportflow.ui.windows.main_window import MainWindow

    asked = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: asked.append(a) or QMessageBox.StandardButton.Yes),
    )
    api = FakeApi(jobs=[_sample_job_dict()])
    win = MainWindow(api)
    qtbot.addWidget(win)
    win._go_live(_sample_job_dict())
    # The confirm names the production recipients; the API gets the promote.
    assert asked and "boss@corp.example.com" in asked[0][2]
    assert api.staged == ("daily", "live")


def test_main_window_dry_run_triggers_api(qtbot, monkeypatch):
    from reportflow.ui.windows import main_window as mw

    class _StubDialog:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return 0

    monkeypatch.setattr(mw, "RunHistoryDialog", _StubDialog)
    api = FakeApi(jobs=[_sample_job_dict()])
    win = mw.MainWindow(api)
    qtbot.addWidget(win)
    win._trigger("daily", mode="dry")
    assert ("dry", "daily") in api.triggered


def test_main_window_system_banner_reflects_account(qtbot):
    from reportflow.ui.windows.main_window import MainWindow

    sys_win = MainWindow(FakeApi(jobs=[_sample_job_dict()], is_system=True))
    qtbot.addWidget(sys_win)
    assert sys_win.system_banner.isHidden() is False

    ok_win = MainWindow(FakeApi(jobs=[_sample_job_dict()], is_system=False))
    qtbot.addWidget(ok_win)
    assert ok_win.system_banner.isHidden() is True


def test_main_window_email_failed_badge(qtbot):
    from reportflow.ui.windows.main_window import MainWindow

    job = dict(_sample_job_dict(), last_email_failed=True, last_email_note="failed: refused")
    win = MainWindow(FakeApi(jobs=[job]))
    qtbot.addWidget(win)
    from PySide6.QtWidgets import QLabel

    assert any("✉ failed" in w.text() for w in win.findChildren(QLabel))


def test_main_window_export_logs_saves_zip(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

    from reportflow.ui.windows import main_window as mw

    src = tmp_path / "reportflow_logs_x.zip"
    src.write_bytes(b"PK\x03\x04zip")
    api = FakeApi(jobs=[])
    api._bundle = str(src)
    dest = tmp_path / "saved.zip"
    monkeypatch.setattr(
        QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("MURI is empty", True))
    )
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(dest), "zip"))
    )
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))

    win = mw.MainWindow(api)
    qtbot.addWidget(win)
    win._export_logs()
    assert api.exported and dest.exists()
    assert api.export_note == "MURI is empty"  # the user's note rides along


def test_main_window_purge_old_and_all_logs(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from reportflow.ui.windows import main_window as mw

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    shown = []
    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a[2]))
    )

    api = FakeApi(jobs=[])
    win = mw.MainWindow(api)
    qtbot.addWidget(win)

    win._purge_old_logs()
    assert api.purged == (30, False)  # retention days from config
    assert shown and "5.0 MB" in shown[-1] and "3 run folder(s)" in shown[-1]

    win._purge_all_logs()
    assert api.purged == (None, True)


def test_main_window_export_logs_cancel_aborts(qtbot, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from reportflow.ui.windows import main_window as mw

    api = FakeApi(jobs=[])
    monkeypatch.setattr(QInputDialog, "getMultiLineText", staticmethod(lambda *a, **k: ("", False)))
    win = mw.MainWindow(api)
    qtbot.addWidget(win)
    win._export_logs()
    assert api.exported is False  # cancelling the note prompt aborts the export


def test_run_history_email_failure_shows_inline_banner(qtbot):
    """A failed report email surfaces as an inline banner — never a modal that pops during
    live polling."""
    from reportflow.ui.windows.log_view import RunHistoryDialog

    dlg = RunHistoryDialog(FakeApi(runs=[]), "daily")
    qtbot.addWidget(dlg)

    failed = {"run_id": "rF", "status": "success", "email_note": "failed: connection refused"}
    dlg._maybe_flag_email(failed)
    assert dlg.email_banner.isHidden() is False
    assert "failed" in dlg.email_banner.text()

    ok = {"run_id": "rG", "status": "success", "email_note": "sent to 1 recipient(s)"}
    dlg._maybe_flag_email(ok)
    assert dlg.email_banner.isHidden() is True


def test_run_history_shows_warnings(qtbot):
    from reportflow.ui.windows.log_view import RunHistoryDialog

    runs = [
        {
            "run_id": "r1",
            "status": "success",
            "started_at": "t",
            "warnings": ["sheet 'Detailed report': 12 error cell(s) (#REF!) — delivered anyway"],
        }
    ]
    dlg = RunHistoryDialog(FakeApi(runs=runs), "daily")
    qtbot.addWidget(dlg)
    dlg._show_selected()
    assert "warnings:" in dlg.details.text()
    assert "#REF!" in dlg.details.text()


def test_run_history_skips_resetting_unchanged_log(qtbot):
    """The live-log poll must not re-set identical text — that reset yanks the view to the
    top on every refresh (the auto-scroll bug)."""
    from reportflow.ui.windows.log_view import RunHistoryDialog

    runs = [{"run_id": "r1", "status": "success", "started_at": "t"}]
    dlg = RunHistoryDialog(FakeApi(runs=runs), "daily")
    qtbot.addWidget(dlg)

    content = "\n".join(f"line {i}" for i in range(100))
    dlg.log.setPlainText(content)
    dlg._api.get_run_log = lambda rid: {"log": content}
    calls = []
    real = dlg.log.setPlainText
    dlg.log.setPlainText = lambda t: calls.append(t) or real(t)

    dlg._show_selected()
    assert calls == []  # unchanged -> not re-set (scroll preserved)

    dlg._api.get_run_log = lambda rid: {"log": content + "\nnew"}
    dlg._show_selected()
    assert calls  # changed -> re-set


# -- dialogs ----------------------------------------------------------------------


def test_settings_dialog_loads_and_collects(qtbot):
    from reportflow.ui.windows.settings_dialog import SettingsDialog

    api = FakeApi()
    dlg = SettingsDialog(api)
    qtbot.addWidget(dlg)

    assert dlg.smtp_host.text() == "smtp.x.com"
    assert dlg.dev_recipients.text() == "dev@x.com"

    dlg.smtp_host.setText("smtp.new.com")
    dlg._save()
    assert api.saved_settings["smtp"]["host"] == "smtp.new.com"
    assert api.saved_settings["app"]["api_port"] == 8787  # preserved from base
    # The default time limit is edited in minutes and stored in seconds.
    assert dlg.default_timeout.value() == 15
    dlg.default_timeout.setValue(40)
    dlg._save()
    assert api.saved_settings["app"]["default_timeout_seconds"] == 2400


def test_email_template_dialog_simple_wrap_and_preview(qtbot):
    from reportflow.ui.windows.email_template_dialog import EmailTemplateDialog

    dlg = EmailTemplateDialog()
    qtbot.addWidget(dlg)
    dlg.tabs.setCurrentWidget(dlg.simple_edit)
    dlg.simple_edit.setPlainText("Hello {{ job_name }},\n\nStatus: {{ status }}")

    html = dlg.result_html()
    assert "<p>Hello {{ job_name }},</p>" in html
    assert "{% if is_test %}" in html  # scaffold retained

    dlg._preview()
    assert "Sample Job" in dlg.preview.toHtml()


def test_email_template_dialog_html_mode(qtbot):
    from reportflow.ui.windows.email_template_dialog import EmailTemplateDialog

    dlg = EmailTemplateDialog(existing_html="<p>{{ job_name }}</p>")
    qtbot.addWidget(dlg)
    assert dlg.tabs.currentWidget() is dlg.html_edit
    assert dlg.result_html() == "<p>{{ job_name }}</p>"


def test_log_viewer_loads(qtbot):
    from reportflow.ui.windows.log_viewer_dialog import LogViewerDialog

    dlg = LogViewerDialog(FakeApi())
    qtbot.addWidget(dlg)
    assert "log line from service" in dlg.text.toPlainText()


def test_log_viewer_one_click_process_switch(qtbot):
    from reportflow.ui.windows.log_viewer_dialog import LogViewerDialog

    dlg = LogViewerDialog(FakeApi())
    qtbot.addWidget(dlg)
    assert dlg._process == "service"
    dlg._switch_process("worker")
    assert dlg._process == "worker"
    assert "log line from worker" in dlg.text.toPlainText()


def test_log_viewer_level_filter_and_search(qtbot):
    from reportflow.ui.windows.log_viewer_dialog import LogViewerDialog

    dlg = LogViewerDialog(FakeApi())
    qtbot.addWidget(dlg)
    dlg._raw = "2026 | INFO     | m:f:1 - alpha\n2026 | ERROR    | m:f:2 - beta"

    dlg.level.setCurrentText("Error")  # triggers _render
    shown = dlg.text.toPlainText()
    assert "beta" in shown and "alpha" not in shown

    dlg.level.setCurrentText("All")
    dlg.search.setText("alpha")
    shown = dlg.text.toPlainText()
    assert "alpha" in shown and "beta" not in shown


def test_main_window_has_logs_menu(qtbot):
    from reportflow.ui.windows.main_window import MainWindow

    win = MainWindow(FakeApi(jobs=[]))
    qtbot.addWidget(win)
    titles = [a.text() for a in win.menuBar().actions()]
    assert "&File" in titles and "&Logs" in titles and "&Help" in titles


def test_about_dialog_shows_metadata(qtbot):
    from reportflow import __about__ as about
    from reportflow.ui.windows.about_dialog import AboutDialog

    dlg = AboutDialog(api_base_url="http://127.0.0.1:8787", connected=True)
    qtbot.addWidget(dlg)
    assert about.AUTHOR == "Viren Hirpara"
    assert "viru185/ReportFlow" in about.REPO_URL


def test_help_dialog_builds(qtbot):
    from reportflow.ui.windows.help_dialog import HelpDialog

    dlg = HelpDialog()
    qtbot.addWidget(dlg)
    text = dlg.browser.toPlainText()
    assert "Help Guide" in text
    assert "Concurrency group" in text
    assert "Time limit" in text and "Wait for add-in data" in text


def test_editor_time_limit_in_minutes_with_visible_help(qtbot):
    from PySide6.QtWidgets import QLabel

    from reportflow.ui.windows.job_editor import JobEditorDialog

    dlg = JobEditorDialog(FakeApi())
    qtbot.addWidget(dlg)
    # "Default" names the actual Settings default (900 s), not just "(use default)".
    assert dlg.timeout.specialValueText() == "Default (15 min)"
    assert dlg.payload()["timeout_seconds"] is None
    dlg.timeout.setValue(45)
    assert dlg.payload()["timeout_seconds"] == 2700
    # The explanation is on screen, not only in a tooltip.
    texts = [w.text() for w in dlg.findChildren(QLabel)]
    assert any("raise this if runs end as Timed out" in t for t in texts)
    assert any("Raise it if sheets arrive partly empty" in t for t in texts)

    # An older job stored in seconds keeps its exact value unless the limit is changed.
    old = JobEditorDialog(FakeApi(), dict(_sample_job_dict(), timeout_seconds=90))
    qtbot.addWidget(old)
    assert old.timeout.value() == 2  # shown rounded up
    assert old.payload()["timeout_seconds"] == 90
    old.timeout.setValue(30)
    assert old.payload()["timeout_seconds"] == 1800


def test_editor_stage_and_refresh_wait(qtbot):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    dlg = JobEditorDialog(FakeApi())
    qtbot.addWidget(dlg)

    # New jobs are locked to Testing — promotion happens from the card's Go live.
    assert dlg.stage.currentData() == "testing"
    assert not dlg.stage.isEnabled()

    # Extra wait plumbs into the payload; stage rides along.
    dlg.name.setText("j")
    dlg.input_excel.setText("C:/t.xlsx")
    dlg._discover_sheets()
    _check_all(dlg)
    dlg.prod_to.setText("a@x.com")
    dlg.test_to.setText("b@x.com")
    dlg.post_refresh_wait.setValue(120)
    assert dlg.payload()["post_refresh_wait_seconds"] == 120
    assert dlg.payload()["stage"] == "testing"


def test_editor_stage_editable_for_existing_job(qtbot):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    live = dict(_sample_job_dict(), stage="live")
    dlg = JobEditorDialog(FakeApi(), live)
    qtbot.addWidget(dlg)
    assert dlg.stage.isEnabled()
    assert dlg.stage.currentData() == "live"
    # Demote back to testing round-trips through the payload.
    dlg.stage.setCurrentIndex(dlg.stage.findData("testing"))
    assert dlg.payload()["stage"] == "testing"


def test_editor_advanced_output_safety_fields(qtbot):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    dlg = JobEditorDialog(FakeApi())
    qtbot.addWidget(dlg)
    dlg.name.setText("j")
    dlg.input_excel.setText("C:/t.xlsx")
    dlg._discover_sheets()
    _check_all(dlg)
    dlg.prod_to.setText("a@x.com")
    dlg.test_to.setText("b@x.com")

    # Defaults: empty-check on, error-strict OFF (deliver), sheets not included -> Remove.
    payload = dlg.payload()
    assert payload["fail_if_sheet_empty"] is True
    assert payload["fail_if_sheet_has_errors"] is False
    assert payload["workbooks"][0]["unselected_sheets"] == "remove"
    assert payload["post_refresh_wait_seconds"] == 10
    assert payload["blank_out_values"] == []

    # One dropdown covers "keep or remove" and "if kept, hidden or visible".
    for key in ("hide", "keep", "remove"):
        dlg.nonselected_mode.setCurrentIndex(dlg.nonselected_mode.findData(key))
        assert dlg.payload()["workbooks"][0]["unselected_sheets"] == key

    dlg.blank_values.setText("Tag not found, #REF!")
    dlg.fail_if_empty.setChecked(False)
    payload = dlg.payload()
    assert payload["blank_out_values"] == ["Tag not found", "#REF!"]
    assert payload["fail_if_sheet_empty"] is False


def test_editor_loads_legacy_single_workbook_job(qtbot):
    """A pre-0.11 job dict (one file, job-wide flags) still opens correctly."""
    from reportflow.ui.windows.job_editor import JobEditorDialog

    legacy = {k: v for k, v in _sample_job_dict().items() if k != "workbooks"}
    legacy.update(input_excel_path="C:/t.xlsx", sheet_names=["Summary"], generate_pdf=False)

    job = dict(legacy, keep_only_selected_sheets=False, unselected_sheets_mode="remove")
    dlg = JobEditorDialog(FakeApi(), job)
    qtbot.addWidget(dlg)
    assert dlg.nonselected_mode.currentData() == "keep"
    assert dlg.input_excel.text() == "C:/t.xlsx"
    assert dlg.payload()["workbooks"][0]["sheets"] == [
        {"name": "Summary", "pdf": False, "hidden": False}
    ]

    job2 = dict(legacy, keep_only_selected_sheets=True, unselected_sheets_mode="hide")
    dlg2 = JobEditorDialog(FakeApi(), job2)
    qtbot.addWidget(dlg2)
    assert dlg2.nonselected_mode.currentData() == "hide"


def test_editor_per_sheet_pdf_and_hidden(qtbot):
    from PySide6.QtCore import Qt

    from reportflow.ui.windows.job_editor import JobEditorDialog

    dlg = JobEditorDialog(FakeApi(sheets=["Summary", "Detail", "Raw"]))
    qtbot.addWidget(dlg)
    dlg.input_excel.setText("C:/t.xlsx")
    dlg._discover_sheets()
    _sheet_cell(dlg, "Detail", 2).setCheckState(Qt.CheckState.Unchecked)  # no PDF
    _sheet_cell(dlg, "Raw", 3).setCheckState(Qt.CheckState.Checked)  # hidden
    sheets = dlg.payload()["workbooks"][0]["sheets"]
    assert sheets == [
        {"name": "Summary", "pdf": True, "hidden": False},
        {"name": "Detail", "pdf": False, "hidden": False},
        {"name": "Raw", "pdf": True, "hidden": True},
    ]

    # Excluding a sheet greys out its PDF/Hidden boxes and drops it from the payload.
    _sheet_cell(dlg, "Raw", 1).setCheckState(Qt.CheckState.Unchecked)
    assert not _sheet_cell(dlg, "Raw", 2).flags() & Qt.ItemFlag.ItemIsEnabled
    assert [s["name"] for s in dlg.payload()["workbooks"][0]["sheets"]] == ["Summary", "Detail"]

    # Clicking a column title ticks/unticks the whole column (included sheets only).
    dlg._toggle_column(2)
    assert _sheet_cell(dlg, "Detail", 2).checkState() == Qt.CheckState.Checked
    dlg._toggle_column(2)
    assert _sheet_cell(dlg, "Summary", 2).checkState() == Qt.CheckState.Unchecked
    assert _sheet_cell(dlg, "Raw", 2).checkState() == Qt.CheckState.Checked  # excluded: untouched


def test_editor_requires_one_visible_sheet(qtbot):
    from PySide6.QtCore import Qt

    from reportflow.ui.windows.job_editor import JobEditorDialog

    dlg = JobEditorDialog(FakeApi(), _sample_job_dict())
    qtbot.addWidget(dlg)
    assert dlg._validation_error() is None
    _sheet_cell(dlg, "Summary", 3).setCheckState(Qt.CheckState.Checked)  # hide the only one
    tab, message = dlg._validation_error()
    assert tab == 0 and "must stay visible" in message


def test_editor_multiple_workbooks(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from reportflow.ui.windows.job_editor import JobEditorDialog

    api = FakeApi(sheets=["Summary", "Detail"])
    dlg = JobEditorDialog(api, _sample_job_dict())
    qtbot.addWidget(dlg)
    assert not dlg.workbook_tabs.tabsClosable()  # one workbook: nothing to remove
    assert not dlg._output_form.isRowVisible(dlg.on_failure)

    dlg._add_workbook("C:/data/Stock.xlsx")  # switches to it and reads its sheets
    assert dlg.workbook_tabs.count() == 2 and dlg.workbook_tabs.tabText(1) == "Stock.xlsx"
    assert dlg.input_excel.text() == "C:/data/Stock.xlsx"
    assert dlg._checked_sheet_names() == ["Summary", "Detail"]
    assert dlg.workbook_tabs.tabsClosable()
    assert dlg._output_form.isRowVisible(dlg.on_failure)
    dlg.on_failure.setCurrentIndex(dlg.on_failure.findData("send_partial"))
    assert "_Stock" in dlg.output_example.text()  # outputs get told apart by workbook

    # Switching tabs keeps each workbook's own state.
    dlg.workbook_tabs.setCurrentIndex(0)
    assert dlg.input_excel.text() == "C:/t.xlsx"
    assert dlg._checked_sheet_names() == ["Summary"]
    payload = dlg.payload()
    assert [w["input_excel_path"] for w in payload["workbooks"]] == [
        "C:/t.xlsx",
        "C:/data/Stock.xlsx",
    ]
    assert payload["on_workbook_failure"] == "send_partial"

    # The same file twice is refused at save.
    dlg.workbook_tabs.setCurrentIndex(1)
    dlg.input_excel.setText("C:/t.xlsx")
    tab, message = dlg._validation_error()
    assert tab == 1 and "twice" in message

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    dlg._remove_workbook(1)
    assert dlg.workbook_tabs.count() == 1 and len(dlg.payload()["workbooks"]) == 1
    assert not dlg.workbook_tabs.tabsClosable()


def test_settings_debug_toggle_saves(qtbot):
    from reportflow.ui.windows.settings_dialog import SettingsDialog

    api = FakeApi()
    dlg = SettingsDialog(api)
    qtbot.addWidget(dlg)
    assert dlg.debug_logging.isChecked() is False
    dlg.debug_logging.setChecked(True)
    dlg._save()
    assert api.saved_settings["app"]["debug_logging"] is True


def test_update_dialog_shows_from_and_to_versions(qtbot):
    from reportflow import __about__ as about
    from reportflow.ui.updater import UpdateInfo
    from reportflow.ui.windows.update_dialog import UpdateDialog

    info = UpdateInfo(version="9.9.9", notes="", installer_url="https://x/s.exe", size=1)
    dlg = UpdateDialog(info)
    qtbot.addWidget(dlg)
    assert about.VERSION in dlg.windowTitle()
    assert "9.9.9" in dlg.windowTitle()


def test_editor_is_tabbed_not_scrollable(qtbot):
    from PySide6.QtWidgets import QScrollArea, QTabWidget

    from reportflow.ui.windows.job_editor import JobEditorDialog

    dlg = JobEditorDialog(FakeApi())
    qtbot.addWidget(dlg)
    assert isinstance(dlg.tabs, QTabWidget)
    assert dlg.tabs.count() == 5  # General / Output / Schedule / Email / Advanced
    assert not dlg.findChildren(QScrollArea)  # compact: no scrolling anywhere


def test_settings_smtp_test_uses_form_values(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from reportflow.ui.windows import settings_dialog as sd

    # Message boxes are modal and would hang the offscreen test run.
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))

    api = FakeApi()
    dlg = sd.SettingsDialog(api)
    qtbot.addWidget(dlg)
    dlg.smtp_host.setText("smtp.other.com")
    dlg.smtp_password.setText("secret")
    dlg._test_connection()
    assert api.smtp_tested["host"] == "smtp.other.com"
    assert api.smtp_tested["password"] == "secret"


def test_settings_password_eye_toggle(qtbot):
    from PySide6.QtWidgets import QLineEdit

    from reportflow.ui.windows.settings_dialog import SettingsDialog

    dlg = SettingsDialog(FakeApi())
    qtbot.addWidget(dlg)
    assert dlg.smtp_password.echoMode() == QLineEdit.EchoMode.Password
    dlg._pw_toggle.setChecked(True)
    assert dlg.smtp_password.echoMode() == QLineEdit.EchoMode.Normal
    dlg._pw_toggle.setChecked(False)
    assert dlg.smtp_password.echoMode() == QLineEdit.EchoMode.Password


def test_settings_service_account_prefill_and_apply(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from reportflow.ui.windows.settings_dialog import SettingsDialog

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setenv("USERDOMAIN", "CORP")
    monkeypatch.setenv("USERNAME", "pi_user")

    api = FakeApi()
    dlg = SettingsDialog(api)
    qtbot.addWidget(dlg)

    dlg._fill_current_user()
    assert dlg.account_user.text() == "CORP\\pi_user"

    dlg.account_password.setText("pw")
    dlg._apply_service_account()
    assert api.applied_account == ("CORP\\pi_user", "pw")
    assert dlg.account_password.text() == ""  # cleared after apply


def test_settings_service_account_needs_both_fields(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from reportflow.ui.windows.settings_dialog import SettingsDialog

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a)))

    api = FakeApi()
    dlg = SettingsDialog(api)
    qtbot.addWidget(dlg)
    dlg.account_user.setText("CORP\\pi_user")  # no password
    dlg._apply_service_account()
    assert warned and not hasattr(api, "applied_account")


def test_settings_saves_update_toggle(qtbot):
    from reportflow.ui.windows.settings_dialog import SettingsDialog

    api = FakeApi()
    dlg = SettingsDialog(api)
    qtbot.addWidget(dlg)
    assert dlg.check_updates.isChecked() is False  # from FakeApi config
    dlg.check_updates.setChecked(True)
    dlg._save()
    assert api.saved_settings["ui"]["check_updates_on_startup"] is True
    assert api.saved_settings["ui"]["api_base_url"]  # base section preserved


def test_update_dialog_builds_from_info(qtbot):
    from reportflow.ui.updater import UpdateInfo
    from reportflow.ui.windows.update_dialog import UpdateDialog

    info = UpdateInfo(
        version="9.9.9", notes="# Big changes", installer_url="https://x/setup.exe", size=1
    )
    dlg = UpdateDialog(info)
    qtbot.addWidget(dlg)
    assert dlg.update_btn.isEnabled()

    no_asset = UpdateInfo(version="9.9.9", notes="", installer_url=None, size=None)
    dlg2 = UpdateDialog(no_asset)
    qtbot.addWidget(dlg2)
    assert not dlg2.update_btn.isEnabled()


# -- theme -------------------------------------------------------------------------


def test_apply_theme_runs_and_sets_dark_palette(qtbot):
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication

    from reportflow.ui.style import BG, TEXT, apply_theme

    app = QApplication.instance()
    apply_theme(app)
    palette = app.palette()
    assert palette.color(QPalette.ColorRole.Window).name() == BG
    assert palette.color(QPalette.ColorRole.WindowText).name() == TEXT
    assert app.styleSheet()  # QSS applied


def test_status_edge_mapping():
    from reportflow.ui.style import status_edge

    assert status_edge("success") == "success"
    assert status_edge("failed") == "failed"
    assert status_edge("timed_out") == "failed"
    assert status_edge("crashed") == "failed"
    assert status_edge("running") == "running"
    assert status_edge(None) == "muted"
    # A paused card reads "asleep" regardless of how its last run ended.
    assert status_edge("success", paused=True) == "muted"


def test_status_colors_cover_all_run_states():
    from reportflow.core.ipc.contract import RunStatus
    from reportflow.ui.style import STATUS_COLORS, status_colors

    for status in RunStatus:
        assert status.value in STATUS_COLORS, f"missing status color for {status.value}"
    assert status_colors(None) == STATUS_COLORS["never"]
    assert status_colors("unknown-thing") == STATUS_COLORS["never"]
