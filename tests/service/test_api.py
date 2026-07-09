"""API smoke tests via FastAPI TestClient + fake worker (no Excel, no real SMTP)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from reportflow.core.config.loader import save_config
from reportflow.core.config.models import AppConfig, SmtpConfig, TestSettings
from reportflow.service.api import ServiceState, create_app

FAKE = str(Path(__file__).parent / "fake_worker.py")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTFLOW_FAKE_MODE", "success")
    # Pre-seed a config whose SMTP points at a refused port so any email attempt fails fast.
    save_config(
        AppConfig(
            smtp=SmtpConfig(host="127.0.0.1", port=1, use_starttls=False, username=""),
            test=TestSettings(recipients=["dev@corp.example.com"]),
        )
    )
    state = ServiceState(worker_command=[sys.executable, FAKE])
    app = create_app(state)
    with TestClient(app) as c:
        yield c, tmp_path


def _make_wb(path: Path) -> None:
    wb = openpyxl.Workbook()
    wb.active.title = "Summary"
    wb.create_sheet("Detail")
    wb.save(path)


def _job_payload(tmp_path: Path) -> dict:
    return {
        "name": "daily",
        "input_excel_path": str(tmp_path / "t.xlsx"),
        "output_dir": str(tmp_path / "out"),
        "output_name": "{run_id}",
        "sheet_names": ["Summary", "Detail"],
        "prod": {"to": ["boss@corp.example.com"]},
        "test": {"to": ["dev@corp.example.com"]},
    }


def test_health_and_status(client):
    c, _ = client
    assert c.get("/health").json()["status"] == "ok"
    assert "version" in c.get("/system/status").json()


def test_workbook_sheet_discovery(client):
    c, tmp_path = client
    wb = tmp_path / "t.xlsx"
    _make_wb(wb)
    resp = c.post("/workbook/sheets", json={"path": str(wb)})
    assert resp.status_code == 200
    assert resp.json()["sheets"] == ["Summary", "Detail"]


def test_workbook_missing_returns_400(client):
    c, tmp_path = client
    resp = c.post("/workbook/sheets", json={"path": str(tmp_path / "nope.xlsx")})
    assert resp.status_code == 400


def test_job_crud_and_uniqueness(client):
    c, tmp_path = client
    _make_wb(tmp_path / "t.xlsx")
    payload = _job_payload(tmp_path)

    assert c.post("/jobs", json=payload).status_code == 201
    assert c.post("/jobs", json=payload).status_code == 409  # duplicate
    assert any(j["name"] == "daily" for j in c.get("/jobs").json())

    payload["notes"] = "edited"
    assert c.put("/jobs/daily", json=payload).status_code == 200
    assert c.get("/jobs/daily").json()["job"]["notes"] == "edited"

    assert c.delete("/jobs/daily").status_code == 200
    assert c.get("/jobs/daily").status_code == 404


def test_run_now_completes(client):
    c, tmp_path = client
    _make_wb(tmp_path / "t.xlsx")
    c.post("/jobs", json=_job_payload(tmp_path))

    run_id = c.post("/jobs/daily/run").json()["run_id"]

    status = None
    for _ in range(50):
        status = c.get(f"/runs/{run_id}").json()["status"]
        if status != "running":
            break
        time.sleep(0.2)
    assert status == "success"

    runs = c.get("/runs", params={"job": "daily"}).json()
    assert runs and runs[0]["run_id"] == run_id
    assert c.get(f"/runs/{run_id}/log").status_code == 200


def test_email_preview(client):
    c, _ = client
    html = c.post("/email/preview", json={}).json()["html"]
    assert "<" in html and "ReportFlow" in html


def test_config_endpoint_has_no_secrets(client):
    c, _ = client
    cfg = c.get("/config").json()
    assert "smtp" in cfg
    assert "password" not in str(cfg).lower()


def test_smtp_test_success_against_local_server(client):
    import socket

    from aiosmtpd.controller import Controller

    class _Ok:
        async def handle_DATA(self, server, session, envelope):
            return "250 OK"

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    controller = Controller(_Ok(), hostname="127.0.0.1", port=port)
    controller.start()
    try:
        c, _ = client
        resp = c.post(
            "/system/smtp-test",
            json={"host": "127.0.0.1", "port": port, "use_starttls": False, "username": ""},
        )
        assert resp.status_code == 200 and resp.json()["ok"] is True
    finally:
        controller.stop()


def test_smtp_test_failure_reports_reason(client):
    c, _ = client
    resp = c.post(
        "/system/smtp-test",
        json={"host": "127.0.0.1", "port": 1, "use_starttls": False, "username": ""},
    )
    assert resp.status_code == 400
    assert "could not connect" in resp.json()["detail"]


def test_smtp_test_username_without_password_skips_login(client):
    """Anonymous relays (port 25) must be testable even when a username is filled in
    but no password exists — login is simply skipped."""
    import socket

    from aiosmtpd.controller import Controller

    class _Ok:
        async def handle_DATA(self, server, session, envelope):
            return "250 OK"

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    controller = Controller(_Ok(), hostname="127.0.0.1", port=port)
    controller.start()
    try:
        c, _ = client
        resp = c.post(
            "/system/smtp-test",
            json={
                "host": "127.0.0.1",
                "port": port,
                "use_starttls": False,
                "username": "no-reply@corp.example.com",  # set, but no password anywhere
            },
        )
        assert resp.status_code == 200 and resp.json()["ok"] is True
    finally:
        controller.stop()


def test_smtp_test_requires_host(client):
    c, _ = client
    resp = c.post("/system/smtp-test", json={"host": "", "username": ""})
    assert resp.status_code == 400
    assert "host" in resp.json()["detail"].lower()


def test_invalid_config_is_surfaced_and_backed_up(monkeypatch):
    """A corrupt config file must be visible in /system/status, preserved as a backup,
    and cleared once valid settings are saved."""
    from reportflow.core import paths

    paths.ensure_dirs()
    cfg_file = paths.config_file()
    cfg_file.write_text('config_version = 1\n[smtp]\nhost = "broken\n', encoding="utf-8")

    state = ServiceState(worker_command=[sys.executable, FAKE])
    app = create_app(state)
    with TestClient(app) as c:
        status = c.get("/system/status").json()
        assert status["config_error"] is not None
        assert "reportflow.toml" in status["config_error"]
        assert status["job_count"] == 0  # fell back to the default config

        backups = list(cfg_file.parent.glob("reportflow.toml.invalid-*"))
        assert backups, "the broken config was not backed up"
        assert "broken" in backups[0].read_text(encoding="utf-8")

        # Saving valid settings rewrites the file and clears the error.
        resp = c.put("/settings", json={"smtp": {"host": "smtp.x.com", "username": ""}})
        assert resp.status_code == 200
        assert c.get("/system/status").json()["config_error"] is None


def test_settings_update_persists(client):
    c, _ = client
    resp = c.put(
        "/settings",
        json={
            "smtp": {"host": "smtp.new.example.com", "port": 2525, "use_starttls": False},
            "test": {"recipients": ["new-dev@corp.example.com"]},
        },
    )
    assert resp.status_code == 200
    cfg = c.get("/config").json()
    assert cfg["smtp"]["host"] == "smtp.new.example.com"
    assert cfg["smtp"]["port"] == 2525
    assert cfg["test"]["recipients"] == ["new-dev@corp.example.com"]


def test_settings_rejects_invalid(client):
    c, _ = client
    assert c.put("/settings", json={}).status_code == 400
    assert c.put("/settings", json={"smtp": {"port": -5}}).status_code == 400


def test_smtp_password_lifecycle(client):
    c, _ = client
    assert c.get("/system/smtp-password").json() == {"set": False}
    assert c.post("/system/smtp-password", json={"password": "hunter2"}).status_code == 200
    assert c.get("/system/smtp-password").json() == {"set": True}
    assert c.delete("/system/smtp-password").status_code == 200
    assert c.get("/system/smtp-password").json() == {"set": False}


def test_system_logs_endpoint(client):
    c, _ = client
    resp = c.get("/system/logs", params={"process": "service", "tail": 100})
    assert resp.status_code == 200
    assert "log" in resp.json()
    assert c.get("/system/logs", params={"process": "bogus"}).status_code == 400


def test_email_template_get_put(client):
    c, tmp_path = client
    _make_wb(tmp_path / "t.xlsx")
    c.post("/jobs", json=_job_payload(tmp_path))

    assert c.get("/jobs/daily/email-template").json()["exists"] is False

    html = "<p>Hello {{ job_name }}</p>"
    resp = c.put("/jobs/daily/email-template", json={"content": html})
    assert resp.status_code == 200
    saved_path = Path(resp.json()["path"])
    assert saved_path.exists()
    assert saved_path.read_text(encoding="utf-8") == html

    got = c.get("/jobs/daily/email-template").json()
    assert got == {"content": html, "exists": True}
    # the job now points at the per-job template file
    assert c.get("/jobs/daily").json()["job"]["email_template_path"] == str(saved_path)


def test_multiple_crons_register_multiple_triggers(client):
    c, tmp_path = client
    _make_wb(tmp_path / "t.xlsx")
    payload = dict(_job_payload(tmp_path), schedule_crons=["0 6 * * *", "0 18 * * *"])
    assert c.post("/jobs", json=payload).status_code == 201

    scheduled = c.get("/system/status").json()["scheduled_jobs"]
    assert sorted(scheduled) == ["daily#0", "daily#1"]
