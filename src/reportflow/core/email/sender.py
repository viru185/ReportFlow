"""Build and send report / developer-bundle emails over SMTP.

The test-mode recipient guard lives HERE, in exactly one place: a test run resolves to the
job's TEST recipients (or the global test fallback) and can never reach production addresses.
BCC is passed only in the SMTP envelope, never as a header.
"""

from __future__ import annotations

import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from loguru import logger

from reportflow.core import secrets
from reportflow.core.config.models import AppConfig, JobConfig, Recipients, SmtpConfig
from reportflow.core.email.render import html_to_text, render_email, resolve_template
from reportflow.core.secrets import SMTP_PASSWORD_KEY


def resolve_recipients(job: JobConfig, config: AppConfig, *, is_test: bool) -> Recipients:
    """THE guard: test runs use test recipients only; production runs use prod recipients."""
    if is_test:
        if job.test.to:
            return job.test
        # Fall back to the global test recipients if the job has none.
        return Recipients(to=list(config.test.recipients) or ["test@localhost"])
    return job.prod


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

    subject = job.subject or f"{job.name} report"
    if is_test:
        subject = f"[TEST] {subject}"

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
        if smtp.username:
            if not password:
                raise ValueError("username is set but no password is stored or provided")
            try:
                server.login(smtp.username, password)
            except smtplib.SMTPAuthenticationError as e:
                raise PermissionError(f"login rejected for {smtp.username!r} — {e}") from e
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

    msg = EmailMessage()
    msg["From"] = config.smtp.from_address or config.smtp.username or "reportflow@localhost"
    msg["Subject"] = f"[ReportFlow] Diagnostic bundle — {context.get('hostname', 'host')}"
    msg["To"] = ", ".join(to)
    msg.set_content(
        "Attached is the ReportFlow diagnostic bundle (logs + sanitized config). "
        "Secrets have been redacted."
    )
    _attach_file(msg, Path(bundle_path))

    send_message(config.smtp, msg, to)
    logger.info("Developer log bundle sent to {} recipient(s)", len(to))
    return to
