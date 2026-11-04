"""Exercise the developer capture tool through ReportFlow's real SMTP sender."""

from __future__ import annotations

import email.policy
import runpy
import smtplib
import subprocess
import sys
from email.parser import BytesParser
from pathlib import Path

import pytest
from aiosmtpd.controller import Controller
from tests.core.test_email import _config, _ctx, _free_port, _job

from reportflow.core.email import send_report

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev_smtp_server.py"
Capture = runpy.run_path(str(SCRIPT))["_PrintAndSave"]


@pytest.fixture
def capture_server(tmp_path):
    port = _free_port()
    outbox = tmp_path / "outbox"
    controller = Controller(Capture(outbox), hostname="127.0.0.1", port=port)
    controller.start()
    try:
        yield port, outbox
    finally:
        controller.stop()


def test_capture_preserves_report_body_attachments_and_multiple_messages(
    capture_server, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr("reportflow.core.email.sender.secrets.get_secret", lambda _: None)
    port, outbox = capture_server
    attachment = tmp_path / "report.pdf"
    attachment.write_bytes(b"%PDF-1.4\nexample attachment\n")
    for _ in range(2):
        send_report(_config(port), _job(), _ctx(), [attachment], is_test=True)
    files = list(outbox.glob("*.eml"))
    assert len(files) == 2
    for path in files:
        message = BytesParser(policy=email.policy.default).parsebytes(path.read_bytes())
        assert str(message["Subject"]).startswith("[TEST]")
        assert message.get_body(preferencelist=("html",)) is not None
        assert "dev@corp.example.com" in str(message["To"])
        assert message["Bcc"] is None
        parts = list(message.iter_attachments())
        assert [p.get_filename() for p in parts] == ["report.pdf"]
        assert parts[0].get_payload(decode=True) == attachment.read_bytes()
    assert "audit@corp.example.com" in capsys.readouterr().out


def test_capture_reports_storage_failure_to_sender(capture_server, tmp_path, monkeypatch):
    monkeypatch.setattr("reportflow.core.email.sender.secrets.get_secret", lambda _: None)
    port, outbox = capture_server
    outbox.write_text("Blocks directory creation", encoding="utf-8")
    with pytest.raises(smtplib.SMTPDataError) as exc:
        send_report(_config(port), _job(), _ctx(), [], is_test=True)
    assert exc.value.smtp_code == 452


@pytest.mark.parametrize("args", [["--host", "0.0.0.0"], ["--port", "0"]])
def test_capture_rejects_invalid_listener_arguments(args):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 2
    assert "error:" in result.stderr
