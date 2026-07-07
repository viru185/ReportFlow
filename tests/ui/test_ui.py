"""Offscreen PySide6 tests with a mock API client (no service, no Excel)."""

from __future__ import annotations

from reportflow.ui.api_client import ApiError


class FakeApi:
    base_url = "http://127.0.0.1:8787"

    def __init__(self, *, jobs=None, sheets=None, connected=True):
        self._jobs = jobs or []
        self._sheets = sheets or ["Summary", "Detail"]
        self._connected = connected
        self.saved_settings = None
        self.saved_template = None

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
        }

    def list_jobs(self):
        self._check()
        return self._jobs

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
    from PySide6.QtCore import Qt

    for i in range(dialog.sheets.count()):
        dialog.sheets.item(i).setCheckState(Qt.CheckState.Checked)


def _sample_job_dict():
    return {
        "name": "daily",
        "enabled": True,
        "input_excel_path": "C:/t.xlsx",
        "output_dir": "C:/reports",
        "output_name": "{job}_{date}",
        "sheet_names": ["Summary"],
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
    assert payload["input_excel_path"] == "C:/t.xlsx"
    assert payload["output_dir"] == "C:/reports"
    assert payload["output_name"] is None  # left empty -> default stem
    assert payload["sheet_names"] == ["Summary", "Detail"]
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


def test_editor_output_example_updates(qtbot):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    dlg = JobEditorDialog(FakeApi())
    qtbot.addWidget(dlg)
    dlg.name.setText("sales")
    dlg.output_name.setText("{job}_custom")
    assert "sales_custom.xlsx" in dlg.output_example.text()


# -- schedule widget -------------------------------------------------------------


def test_schedule_widget_round_trip(qtbot):
    from reportflow.ui.windows.schedule_widget import ScheduleWidget

    w = ScheduleWidget()
    qtbot.addWidget(w)

    w.load(["0 6 * * MON,WED", "30 18 * * MON,WED"])
    spec = w.to_spec()
    assert spec.mode == "weekly"
    assert spec.weekdays == ["MON", "WED"]
    assert spec.times == ["06:00", "18:30"]
    assert w.to_crons() == ["0 6 * * MON,WED", "30 18 * * MON,WED"]


def test_schedule_widget_manual_default(qtbot):
    from reportflow.ui.windows.schedule_widget import ScheduleWidget

    w = ScheduleWidget()
    qtbot.addWidget(w)
    assert w.to_crons() == []


def test_schedule_widget_advanced_fallback(qtbot):
    from reportflow.ui.windows.schedule_widget import ScheduleWidget

    w = ScheduleWidget()
    qtbot.addWidget(w)
    w.load(["*/5 * * * *"])
    assert w.to_spec().mode == "advanced"
    assert w.to_crons() == ["*/5 * * * *"]


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
    assert "Timeout" in text


def test_editor_email_hint_and_refresh_wait(qtbot):
    from reportflow.ui.windows.job_editor import JobEditorDialog

    dlg = JobEditorDialog(FakeApi())
    qtbot.addWidget(dlg)

    # Opt-in unticked -> the hint warns that real runs won't email.
    assert not dlg.send_email.isChecked()
    assert "NOT send email" in dlg.email_hint.text()
    dlg.send_email.setChecked(True)
    assert "will email the production recipients" in dlg.email_hint.text()

    # Extra wait plumbs into the payload.
    dlg.name.setText("j")
    dlg.input_excel.setText("C:/t.xlsx")
    dlg._discover_sheets()
    _check_all(dlg)
    dlg.prod_to.setText("a@x.com")
    dlg.test_to.setText("b@x.com")
    dlg.post_refresh_wait.setValue(120)
    assert dlg.payload()["post_refresh_wait_seconds"] == 120


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


def test_status_colors_cover_all_run_states():
    from reportflow.core.ipc.contract import RunStatus
    from reportflow.ui.style import STATUS_COLORS, status_colors

    for status in RunStatus:
        assert status.value in STATUS_COLORS, f"missing status color for {status.value}"
    assert status_colors(None) == STATUS_COLORS["never"]
    assert status_colors("unknown-thing") == STATUS_COLORS["never"]
