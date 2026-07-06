"""Render the HTML email body from a Jinja2 template, with a plain-text fallback."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, select_autoescape

from reportflow.core import paths
from reportflow.core.config.defaults import DEFAULT_EMAIL_TEMPLATE
from reportflow.core.config.models import AppConfig, JobConfig

_env = Environment(autoescape=select_autoescape(["html", "xml"]), enable_async=False)


def resolve_template(job: JobConfig | None, config: AppConfig) -> str:
    """Return the HTML template text: per-job override, else global default, else built-in."""
    if job is not None and job.email_template_path is not None:
        p = Path(job.email_template_path)
        if p.exists():
            return p.read_text(encoding="utf-8")

    default = config.email.default_template_path
    default_path = Path(default)
    if not default_path.is_absolute():
        default_path = paths.templates_dir() / default
    if default_path.exists():
        return default_path.read_text(encoding="utf-8")

    return DEFAULT_EMAIL_TEMPLATE


def render_email(template_source: str, context: dict[str, Any]) -> str:
    return _env.from_string(template_source).render(**context)


def html_to_text(html: str) -> str:
    """A minimal plain-text alternative derived from the HTML body."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def sample_context(job: JobConfig | None = None) -> dict[str, Any]:
    """Placeholder context for the UI's email preview."""
    return {
        "job_name": job.name if job else "Sample Job",
        "subject": (job.subject if job and job.subject else "Sample Report"),
        "status": "success",
        "run_id": "preview-0001",
        "started_at": "2026-07-07T06:00:00",
        "finished_at": "2026-07-07T06:00:12",
        "duration_seconds": 12.0,
        "sheet_names": (job.sheet_names if job else ["Summary", "Detail"]),
        "hostname": "REPORTFLOW-HOST",
        "is_test": True,
    }
