"""Service-account validation + apply, and the endpoints that drive them.

The Windows calls (LogonUser, nssm) are mocked — these tests never touch real credentials
or reconfigure a real service. A guard also asserts the password never lands in a log.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reportflow.core.config.loader import save_config
from reportflow.core.config.models import AppConfig, SmtpConfig, TestSettings
from reportflow.service import service_account as sa
from reportflow.service.api import ServiceState, create_app

FAKE = str(Path(__file__).parent / "fake_worker.py")


# -- pure helpers ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("CORP\\pi_user", ("CORP", "pi_user")),
        (".\\local", (".", "local")),
        ("bare", (".", "bare")),
        ("  CORP\\pi_user  ", ("CORP", "pi_user")),
    ],
)
def test_split_account(raw, expected):
    assert sa.split_account(raw) == expected


def test_validate_rejects_blank_fields():
    with pytest.raises(sa.ServiceAccountError):
        sa.validate_credentials("", "pw")
    with pytest.raises(sa.ServiceAccountError):
        sa.validate_credentials("CORP\\u", "")


def test_validate_rejects_bad_credentials(monkeypatch):
    def _boom(name, domain, password):
        raise OSError("logon failure")

    monkeypatch.setattr(sa, "_logon", _boom)
    with pytest.raises(sa.ServiceAccountError):
        sa.validate_credentials("CORP\\pi_user", "wrong")


def test_validate_accepts_good_credentials(monkeypatch):
    seen = {}

    def _ok(name, domain, password):
        seen["args"] = (name, domain, password)

    monkeypatch.setattr(sa, "_logon", _ok)
    sa.validate_credentials("CORP\\pi_user", "right")  # no raise
    assert seen["args"] == ("pi_user", "CORP", "right")


def test_apply_builds_nssm_objectname_and_restarts(monkeypatch, tmp_path):
    nssm = tmp_path / "nssm.exe"
    nssm.write_bytes(b"x")
    monkeypatch.setattr(sa, "nssm_path", lambda: nssm)

    calls = {}

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def _run(args, **kw):
        calls["run"] = args
        return _Result()

    monkeypatch.setattr(sa.subprocess, "run", _run)
    monkeypatch.setattr(sa, "_schedule_restart", lambda n, s: calls.setdefault("restart", True))

    account = sa.apply_service_account("corp\\pi_user", "secret")
    assert account == "corp\\pi_user"
    # nssm set <svc> ObjectName <account> <password>
    assert calls["run"][1:5] == ["set", "ReportFlow", "ObjectName", "corp\\pi_user"]
    assert calls["run"][5] == "secret"
    assert calls["restart"] is True


def test_apply_raises_on_nssm_failure(monkeypatch, tmp_path):
    nssm = tmp_path / "nssm.exe"
    nssm.write_bytes(b"x")
    monkeypatch.setattr(sa, "nssm_path", lambda: nssm)

    class _Result:
        returncode = 1
        stdout = ""
        stderr = "the account does not have logon-as-a-service right"

    monkeypatch.setattr(sa.subprocess, "run", lambda *a, **k: _Result())
    with pytest.raises(sa.ServiceAccountError):
        sa.apply_service_account("corp\\pi_user", "secret")


# -- endpoints ------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTFLOW_FAKE_MODE", "success")
    save_config(
        AppConfig(
            smtp=SmtpConfig(host="127.0.0.1", port=1, use_starttls=False, username=""),
            test=TestSettings(recipients=["dev@corp.example.com"]),
        )
    )
    state = ServiceState(worker_command=[sys.executable, FAKE])
    app = create_app(state)
    with TestClient(app) as c:
        yield c


def test_get_service_account(client):
    body = client.get("/system/service-account").json()
    assert "account" in body and "is_system" in body


def test_set_service_account_rejects_invalid(client, monkeypatch):
    def _bad(user, password):
        raise sa.ServiceAccountError("rejected by Windows")

    monkeypatch.setattr(sa, "validate_credentials", _bad)
    resp = client.post("/system/service-account", json={"user": "CORP\\u", "password": "no"})
    assert resp.status_code == 400
    assert "rejected" in resp.json()["detail"]


def test_set_service_account_applies_when_valid(client, monkeypatch):
    monkeypatch.setattr(sa, "validate_credentials", lambda u, p: None)
    monkeypatch.setattr(sa, "apply_service_account", lambda u, p: "CORP\\pi_user")
    resp = client.post(
        "/system/service-account", json={"user": "CORP\\pi_user", "password": "right"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["account"] == "CORP\\pi_user"


def test_set_service_account_never_logs_password(client, monkeypatch):
    logged: list[str] = []
    from reportflow.service.api import app as app_module

    monkeypatch.setattr(sa, "validate_credentials", lambda u, p: None)
    monkeypatch.setattr(sa, "apply_service_account", lambda u, p: "CORP\\pi_user")
    monkeypatch.setattr(
        app_module.logger, "info", lambda *a, **k: logged.append(" ".join(map(str, a)))
    )
    client.post("/system/service-account", json={"user": "CORP\\u", "password": "sup3rsecret"})
    assert not any("sup3rsecret" in line for line in logged)
