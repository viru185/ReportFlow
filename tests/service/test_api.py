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
        "workbook_template_path": str(tmp_path / "t.xlsx"),
        "output_xlsx_path": str(tmp_path / "out" / "{run_id}.xlsx"),
        "output_pdf_path": str(tmp_path / "out" / "{run_id}_{sheet}.pdf"),
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
