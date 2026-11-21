"""Build and send report / developer-bundle emails over SMTP.

The test-mode recipient guard lives HERE, in exactly one place: a test run resolves to the
job's TEST recipients and can never reach production addresses.
BCC is passed only in the SMTP envelope, never as a header.
"""

from __future__ import annotations

import mimetypes
import re
import smtplib
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import Any

from jinja2 import TemplateError
from loguru import logger

from reportflow.core import secrets
from reportflow.core.config.models import AppConfig, JobConfig, SmtpConfig
from reportflow.core.email.recipients import ResolvedRecipients, resolve
from reportflow.core.email.render import (
    explain_template_error,
    final_subject,
    html_to_text,
    render_email,
    resolve_template,
    sample_context,
)
from reportflow.core.secrets import SMTP_PASSWORD_KEY


def resolve_recipients(job: JobConfig, config: AppConfig, *, is_test: bool) -> ResolvedRecipients:
    """THE guard: test runs use test recipients only; production runs use prod recipients.

    Email groups are expanded here, and every address appears once (To > Cc > Bcc).
    """
    # Every job has its own Test To (``Recipients`` requires one), so there is no fallback:
    # a test run can only ever reach the people the job names for testing.
    return resolve(job.test if is_test else job.prod, config.email.groups)


def _attach_file(msg: EmailMessage, path: Path) -> None:
    ctype, _ = mimetypes.guess_type(str(path))
    maintype, subtype = ctype.split("/", 1) if ctype else ("application", "octet-stream")
    msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)


def build_report_message(
    config: AppConfig,
    job: JobConfig,
    context: dict[str, Any],
    attachments: list[Path],
    *,
    is_test: bool,
) -> tuple[EmailMessage, list[str]]:
    recipients = resolve_recipients(job, config, is_test=is_test)

    # Placeholders work in the subject too ("Daily report — {{ today }}").
    subject = final_subject(job.subject, job.name, context, is_test=is_test)

    html = render_email(resolve_template(job, config), context)
    text = html_to_text(html)

    msg = EmailMessage()
    msg["From"] = config.smtp.from_address or config.smtp.username or "reportflow@localhost"
    msg["Subject"] = subject
    msg["To"] = ", ".join(str(a) for a in recipients.to)
    if recipients.cc:
        msg["Cc"] = ", ".join(str(a) for a in recipients.cc)
    # NB: BCC is intentionally NOT added as a header.

    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    for path in attachments:
        p = Path(path)
        if p.exists():
            _attach_file(msg, p)
        else:
            logger.warning("Attachment missing, skipping: {}", p)

    return msg, recipients.all_addresses()


def test_smtp_connection(smtp: SmtpConfig, password: str | None = None) -> None:
    """Verify the SMTP settings: connect, EHLO, STARTTLS (if configured), and log in
    when credentials are present. Raises with a readable message on any failure.

    ``password=None`` falls back to the stored secret; an empty username skips login.
    """
    if not smtp.host:
        raise ValueError("SMTP host is not set")
    if password is None:
        password = secrets.get_secret(SMTP_PASSWORD_KEY)

    try:
        if smtp.use_ssl:
            server: smtplib.SMTP = smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=10)
        else:
            server = smtplib.SMTP(smtp.host, smtp.port, timeout=10)
    except (OSError, smtplib.SMTPException) as e:
        raise ConnectionError(f"could not connect to {smtp.host}:{smtp.port} — {e}") from e
    try:
        server.ehlo()
        if smtp.use_starttls and not smtp.use_ssl:
            server.starttls()
            server.ehlo()
        # Login only when BOTH a username and a password exist — anonymous relays
        # (e.g. internal servers on port 25) need no credentials at all, and sending
        # behaves the same way (see send_message).
        if smtp.username and password:
            try:
                server.login(smtp.username, password)
            except smtplib.SMTPAuthenticationError as e:
                raise PermissionError(f"login rejected for {smtp.username!r} — {e}") from e
        elif smtp.username:
            logger.info("SMTP test: no password stored/provided — skipping login check")
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            server.close()


def send_message(smtp: SmtpConfig, message: EmailMessage, envelope_to: list[str]) -> None:
    password = secrets.get_secret(SMTP_PASSWORD_KEY)
    sender = message["From"]

    if smtp.use_ssl:
        server: smtplib.SMTP = smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=30)
    else:
        server = smtplib.SMTP(smtp.host, smtp.port, timeout=30)
    try:
        server.ehlo()
        if smtp.use_starttls and not smtp.use_ssl:
            server.starttls()
            server.ehlo()
        if smtp.username and password:
            server.login(smtp.username, password)
        server.sendmail(sender, envelope_to, message.as_string())
    finally:
        try:
            server.quit()
        except Exception:  # noqa: BLE001
            server.close()


_TEST_NOTE = (
    '<p style="font-family:Segoe UI,Arial,sans-serif;font-size:12px;color:#555;background:#f3f4f6;'
    'border:1px solid #d1d5db;border-radius:6px;padding:8px 10px;margin:0 0 12px 0;">'
    "This is a test of the email template for <b>{job}</b>, sent from ReportFlow with sample "
    "values. The report files are not attached.</p>"
)


def send_template_test(
    config: AppConfig,
    *,
    to: str,
    template: str,
    job_name: str,
    subject: str | None = None,
    is_test: bool = True,
    sheet_names: list[str] | None = None,
    workbooks: list[str] | None = None,
) -> None:
    """Email one sample of a job's message to ``to``: the template and subject as they are
    in the editor, filled with the same sample values as its preview, ``[TEST]`` in the
    subject and a note on top. Raises ValueError for anything the user can fix (no email
    server set up, a broken template); other errors come from the mail server."""
    if not config.smtp.host:
        raise ValueError("The email server isn't set up yet — File → Settings → Email.")
    context = sample_context(
        is_test=is_test,
        job_name=job_name,
        subject=subject,
        sheet_names=sheet_names,
        workbooks=workbooks,
    )
    try:
        html = render_email(template, context)
    except TemplateError as e:
        raise ValueError(f"The template has an error: {explain_template_error(str(e))}") from e
    note = _TEST_NOTE.format(job=escape(job_name or "this job"))
    body = re.search(r"<body[^>]*>", html, flags=re.IGNORECASE)
    html = html[: body.end()] + note + html[body.end() :] if body else note + html
    title = final_subject(subject, job_name or "Job", context, is_test=False)
    msg = EmailMessage()
    msg["From"] = config.smtp.from_address or config.smtp.username or "reportflow@localhost"
    msg["To"] = to
    msg["Subject"] = f"[TEST] {title}"
    msg.set_content(html_to_text(html))
    msg.add_alternative(html, subtype="html")
    send_message(config.smtp, msg, [to])
    logger.info("Sent a template test email for {!r} to {}", job_name, to)


def send_report(
    config: AppConfig,
    job: JobConfig,
    context: dict[str, Any],
    attachments: list[Path],
    *,
    is_test: bool,
) -> list[str]:
    """Build and send a report email. Returns the envelope recipients it was sent to."""
    message, envelope = build_report_message(config, job, context, attachments, is_test=is_test)
    send_message(config.smtp, message, envelope)
    logger.info(
        "Report email sent for job {!r} (test={}) to {} recipient(s)",
        job.name,
        is_test,
        len(envelope),
    )
    return envelope


def send_dev_log_bundle(config: AppConfig, bundle_path: Path, context: dict[str, Any]) -> list[str]:
    """Send the redacted diagnostic bundle to the developer recipients."""
    to = [str(a) for a in config.test.developer_bundle_recipients]
    if not to:
        raise ValueError("no developer_bundle_recipients configured")

    note = str(context.get("note", "")).strip()
    msg = EmailMessage()
    msg["From"] = config.smtp.from_address or config.smtp.username or "reportflow@localhost"
    subject = f"[ReportFlow] Diagnostic bundle — {context.get('hostname', 'host')}"
    if note:
        # Show the first line of the operator's note in the subject for a quick scan.
        subject += f" — {note.splitlines()[0][:80]}"
    msg["Subject"] = subject
    msg["To"] = ", ".join(to)
    body = (
        "Attached is the ReportFlow diagnostic bundle (logs + sanitized config). "
        "Secrets have been redacted."
    )
    if note:
        body += f"\n\nProblem description from the operator:\n{note}"
    msg.set_content(body)
    _attach_file(msg, Path(bundle_path))

    send_message(config.smtp, msg, to)
    logger.info("Developer log bundle sent to {} recipient(s)", len(to))
    return to
