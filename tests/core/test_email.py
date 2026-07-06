"""Email tests against a local aiosmtpd server (no real SMTP, no Excel)."""

from __future__ import annotations

import email
import socket
from email.message import Message

import pytest
from aiosmtpd.controller import Controller

from reportflow.core.config.models import (
    AppConfig,
    JobConfig,
    Recipients,
    SmtpConfig,
    TestSettings,
)
from reportflow.core.email import render_email, resolve_recipients, send_report
from reportflow.core.email.render import html_to_text


class _Capture:
    def __init__(self):
        self.envelopes = []

    async def handle_DATA(self, server, session, envelope):
        self.envelopes.append((list(envelope.rcpt_tos), envelope.content))
        return "250 OK"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def smtp_server():
    handler = _Capture()
    port = _free_port()
    controller = Controller(handler, hostname="127.0.0.1", port=port)
    controller.start()
    try:
        yield handler, port
    finally:
        controller.stop()


def _config(port: int) -> AppConfig:
    cfg = AppConfig(
        smtp=SmtpConfig(
            host="127.0.0.1",
            port=port,
            use_starttls=False,
            use_ssl=False,
            from_address="reportflow@corp.example.com",
            username="",
        ),
        test=TestSettings(recipients=["fallback@corp.example.com"]),
    )
    return cfg


def _job() -> JobConfig:
    return JobConfig(
        name="daily",
        input_excel_path="C:/t.xlsx",
        output_dir="C:/out",
        sheet_names=["Summary"],
        subject="Daily Report",
        prod=Recipients(to=["boss@corp.example.com"], cc=["ops@corp.example.com"]),
        test=Recipients(
            to=["dev@corp.example.com"],
            cc=["qa@corp.example.com"],
            bcc=["audit@corp.example.com"],
        ),
    )


def _ctx():
    return {
        "job_name": "daily",
        "subject": "Daily Report",
        "status": "success",
        "run_id": "r1",
        "started_at": "s",
        "finished_at": "f",
        "duration_seconds": 1,
        "sheet_names": ["Summary"],
        "hostname": "H",
        "is_test": True,
    }


def test_resolve_recipients_guard():
    cfg = _config(25)
    job = _job()
    assert resolve_recipients(job, cfg, is_test=True).to == ["dev@corp.example.com"]
    assert resolve_recipients(job, cfg, is_test=False).to == ["boss@corp.example.com"]


def test_render_and_text_alternative():
    html = render_email("<p>Hello {{ job_name }}</p>", {"job_name": "daily"})
    assert "Hello daily" in html
    assert html_to_text("<p>Hi</p><br>there") == "Hi\n\nthere"


def test_test_run_goes_only_to_test_recipients(smtp_server, tmp_path):
    handler, port = smtp_server
    xlsx = tmp_path / "out.xlsx"
    xlsx.write_bytes(b"PK\x03\x04fake-xlsx")
    pdf = tmp_path / "Summary.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    envelope = send_report(_config(port), _job(), _ctx(), [xlsx, pdf], is_test=True)

    assert set(envelope) == {
        "dev@corp.example.com",
        "qa@corp.example.com",
        "audit@corp.example.com",
    }
    assert "boss@corp.example.com" not in envelope  # never leak to prod

    rcpts, content = handler.envelopes[0]
    assert set(rcpts) == set(envelope)  # BCC IS in the envelope

    msg: Message = email.message_from_bytes(content)
    assert msg["To"] == "dev@corp.example.com"
    assert msg["Cc"] == "qa@corp.example.com"
    assert msg["Bcc"] is None  # BCC is NOT a header
    assert msg["Subject"] == "[TEST] Daily Report"

    parts = {p.get_content_type() for p in msg.walk()}
    assert "text/plain" in parts and "text/html" in parts
    filenames = {p.get_filename() for p in msg.walk() if p.get_filename()}
    assert filenames == {"out.xlsx", "Summary.pdf"}


def test_prod_run_uses_prod_recipients(smtp_server, tmp_path):
    handler, port = smtp_server
    envelope = send_report(_config(port), _job(), _ctx(), [], is_test=False)
    assert set(envelope) == {"boss@corp.example.com", "ops@corp.example.com"}
    msg = email.message_from_bytes(handler.envelopes[0][1])
    assert msg["Subject"] == "Daily Report"  # no [TEST] prefix
