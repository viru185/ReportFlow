"""Email rendering and sending, plus diagnostic-bundle redaction."""

from reportflow.core.email.redaction import build_log_bundle, redact_config
from reportflow.core.email.render import render_email, resolve_template, sample_context
from reportflow.core.email.sender import (
    resolve_recipients,
    send_dev_log_bundle,
    send_report,
)

__all__ = [
    "render_email",
    "resolve_template",
    "sample_context",
    "resolve_recipients",
    "send_report",
    "send_dev_log_bundle",
    "redact_config",
    "build_log_bundle",
]
