"""Render the HTML email body (and subject) from Jinja2 templates, with a plain-text fallback.

``PLACEHOLDERS`` is the one list of documented placeholders: the template editor's insert
list and the Help guide's table are both built from it, and ``sample_context`` provides a
value for every one of them so the preview never shows a blank.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from jinja2 import Environment, TemplateError, select_autoescape

from reportflow.core import paths
from reportflow.core.config.defaults import DEFAULT_EMAIL_TEMPLATE
from reportflow.core.config.models import AppConfig, JobConfig

_env = Environment(autoescape=select_autoescape(["html", "xml"]), enable_async=False)
# Subjects are plain text — escaping would turn "R&D" into "R&amp;D".
_text_env = Environment(autoescape=False, enable_async=False)

# 07-Oct-2026: unambiguous whichever way round the reader writes dates.
DATE_FORMAT = "%d-%b-%Y"

# (group, label, placeholder to insert, what it is for). Examples come from sample_context.
PLACEHOLDERS: list[tuple[str, str, str, str]] = [
    ("Dates", "Today", "{{ today }}", "the run's date"),
    ("Dates", "Yesterday", "{{ yesterday }}", "the day before — for reports on yesterday's data"),
    ("Dates", "Date and time", "{{ now }}", "the run's date and time"),
    ("Dates", "Weekday", "{{ weekday }}", "the run's day of the week"),
    ("Dates", "Month", "{{ month }}", "the run's month"),
    ("Dates", "Previous month", "{{ previous_month }}", "last month — for monthly reports"),
    ("Dates", "Week number", "{{ week_number }}", "the ISO week number"),
    (
        "Dates",
        "Your own date format",
        "{{ run_date.strftime('%d/%m/%Y') }}",
        "the run's date in any format (%d day, %m month, %Y year, %b Jan, %A Monday)",
    ),
    ("Run", "Job name", "{{ job_name }}", "the job's name"),
    ("Run", "Status", "{{ status }}", "the run's outcome"),
    ("Run", "Stage", "{{ stage }}", "Testing or Live"),
    ("Run", "Started", "{{ started_at }}", "when the run started"),
    ("Run", "Finished", "{{ finished_at }}", "when the run finished"),
    ("Run", "Duration (s)", "{{ duration_seconds }}", "how long the run took, in seconds"),
    ("Run", "Run ID", "{{ run_id }}", "the run's id — handy when reporting a problem"),
    ("Run", "Host", "{{ hostname }}", "the machine that built the report"),
    ("Run", "Warning count", "{{ warning_count }}", "how many warnings the run has"),
    ("Files", "Attachments", '{{ attachments | join(", ") }}', "the attached file names"),
    ("Files", "Attachment count", "{{ attachment_count }}", "how many files are attached"),
    ("Files", "Workbooks", '{{ workbooks | join(", ") }}', "the input workbooks"),
    ("Files", "Sheets", '{{ sheet_names | join(", ") }}', "the included sheets"),
    ("Files", "Sheet count", "{{ sheet_count }}", "how many sheets are included"),
    (
        "Blocks",
        "Warnings list",
        "{% if warnings %}<ul>{% for w in warnings %}<li>{{ w }}</li>{% endfor %}</ul>{% endif %}",
        "lists the run's warnings — only when there are any",
    ),
    (
        "Blocks",
        "Testing-only text",
        "{% if is_test %}TEST RUN{% endif %}",
        "text that only appears on Testing-stage runs",
    ),
]


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


def render_subject(subject: str, context: dict[str, Any]) -> str:
    """Expand placeholders in a subject line ("Daily report — {{ today }}").

    A broken subject template must not cost the email: fall back to the text as written.
    """
    try:
        return " ".join(_text_env.from_string(subject).render(**context).split())
    except TemplateError:
        return subject


def template_error(source: str) -> str | None:
    """A user-facing syntax error for a template/subject, or None when it parses."""
    try:
        _env.parse(source)
    except TemplateError as e:
        return str(e)
    return None


def date_context(at: datetime) -> dict[str, Any]:
    """Date placeholders for a run that started at ``at``."""
    day = at.date()
    last_month = day.replace(day=1) - timedelta(days=1)
    return {
        "today": day.strftime(DATE_FORMAT),
        "yesterday": (day - timedelta(days=1)).strftime(DATE_FORMAT),
        "now": at.strftime(f"{DATE_FORMAT} %H:%M"),
        "weekday": at.strftime("%A"),
        "month": at.strftime("%B %Y"),
        "previous_month": last_month.strftime("%B %Y"),
        "week_number": str(day.isocalendar().week),
        # Objects for custom formats: {{ run_date.strftime('%d/%m/%Y') }}.
        "run_date": day,
        "run_at": at,
    }


def html_to_text(html: str) -> str:
    """A minimal plain-text alternative derived from the HTML body."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def sample_context(job: JobConfig | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Placeholder context for the UI's email preview — a value for every placeholder."""
    now = now or datetime.now()
    name = job.name if job else "Sample Job"
    workbooks = [Path(wb.input_excel_path) for wb in job.workbooks] if job else [Path("Sales.xlsx")]
    sheets = job.sheet_names if job else ["Summary", "Detail"]
    stem = f"{name}_{now.strftime('%Y%m%d_%H%M%S')}"
    attachments = [f"{stem}.xlsx", *(f"{stem}_{s}.pdf" for s in sheets[:2])]
    context: dict[str, Any] = {
        "job_name": name,
        "status": "success",
        "stage": "Testing",
        "run_id": "preview-0001",
        "started_at": now.isoformat(timespec="seconds"),
        "finished_at": (now + timedelta(seconds=12)).isoformat(timespec="seconds"),
        "duration_seconds": 12,
        "sheet_names": sheets,
        "sheet_count": len(sheets),
        "workbooks": [p.name for p in workbooks],
        "attachments": attachments,
        "attachment_count": len(attachments),
        "hostname": "REPORTFLOW-HOST",
        "is_test": True,
        "warnings": [],
        "warning_count": 0,
        **date_context(now),
    }
    raw_subject = job.subject if job and job.subject else f"{name} report"
    context["subject"] = render_subject(raw_subject, context)
    return context
