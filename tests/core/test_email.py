"""Email tests against a local aiosmtpd server (no real SMTP, no Excel)."""

from __future__ import annotations

import email
import email.header
import email.policy
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


def test_dev_log_bundle_includes_operator_note(smtp_server, tmp_path):
    from reportflow.core.config.models import TestSettings
    from reportflow.core.email import send_dev_log_bundle

    handler, port = smtp_server
    cfg = _config(port).model_copy(
        update={"test": TestSettings(developer_bundle_recipients=["dev@corp.example.com"])}
    )
    bundle = tmp_path / "logs.zip"
    bundle.write_bytes(b"PK\x03\x04")
    context = {"hostname": "SERVER1", "note": "MURI sheet came out empty"}

    to = send_dev_log_bundle(cfg, bundle, context)

    assert to == ["dev@corp.example.com"]
    msg = email.message_from_bytes(handler.envelopes[0][1], policy=email.policy.default)
    subject = str(email.header.make_header(email.header.decode_header(msg["Subject"])))
    assert "MURI sheet came out empty" in subject
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "MURI sheet came out empty" in body


def test_subject_placeholders_are_expanded(smtp_server, tmp_path):
    from datetime import datetime

    from reportflow.core.email.render import date_context

    handler, port = smtp_server
    job = _job().model_copy(update={"subject": "R&D report — {{ today }}"})
    ctx = {**_ctx(), **date_context(datetime(2026, 10, 7, 6, 15))}

    send_report(_config(port), job, ctx, [], is_test=True)

    from email import policy

    msg = email.message_from_bytes(handler.envelopes[0][1], policy=policy.default)
    assert msg["Subject"] == "[TEST] R&D report — 07-Oct-2026"  # not HTML-escaped


def test_broken_subject_template_still_sends_as_written():
    from reportflow.core.email.render import render_subject, template_error

    assert render_subject("Report {{ today", {"today": "x"}) == "Report {{ today"
    assert template_error("Report {{ today") is not None
    assert template_error("Report {{ today }}") is None


def test_date_placeholders():
    from datetime import datetime

    from reportflow.core.email.render import date_context

    ctx = date_context(datetime(2026, 3, 1, 6, 15))  # the 1st: previous month is February
    assert ctx["today"] == "01-Mar-2026"
    assert ctx["yesterday"] == "28-Feb-2026"
    assert ctx["now"] == "01-Mar-2026 06:15"
    assert ctx["weekday"] == "Sunday"
    assert ctx["month"] == "March 2026"
    assert ctx["previous_month"] == "February 2026"
    assert ctx["week_number"] == "9"
    assert ctx["run_date"].strftime("%d/%m/%Y") == "01/03/2026"
    jan = date_context(datetime(2026, 1, 1))
    assert jan["previous_month"] == "December 2025" and jan["yesterday"] == "31-Dec-2025"


def test_every_documented_placeholder_has_a_sample_value():
    """The preview (and the Help examples) must never show a blank for a listed placeholder."""
    from reportflow.core.email.render import PLACEHOLDERS, render_email, sample_context

    ctx = sample_context()
    for group, label, token, _ in PLACEHOLDERS:
        if group == "Blocks":
            render_email(token, ctx)  # must at least render
            continue
        assert render_email(token, ctx).strip(), f"{label} ({token}) renders empty"
