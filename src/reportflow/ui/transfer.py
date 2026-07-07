"""Pure import/export helpers for jobs and settings (no Qt — unit-testable).

File formats:
    {"reportflow_export": "jobs", "version": 1, "jobs": [<JobConfig dump>, ...]}
    {"reportflow_export": "settings", "version": 1, "settings": {app|smtp|ui|email|test}}
"""

from __future__ import annotations

from typing import Any

from reportflow.core.config.models import JobConfig

JOBS_KIND = "jobs"
SETTINGS_KIND = "settings"
FORMAT_VERSION = 1

SETTINGS_SECTIONS = ("app", "smtp", "ui", "email", "test")


class TransferError(ValueError):
    """The file is not a valid ReportFlow export of the expected kind."""


def export_jobs(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    return {"reportflow_export": JOBS_KIND, "version": FORMAT_VERSION, "jobs": jobs}


def parse_jobs_file(data: Any) -> list[JobConfig]:
    """Validate an export payload and return the contained jobs (raises TransferError)."""
    if not isinstance(data, dict) or data.get("reportflow_export") != JOBS_KIND:
        raise TransferError("this file is not a ReportFlow jobs export")
    raw_jobs = data.get("jobs")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        raise TransferError("the export contains no jobs")
    jobs: list[JobConfig] = []
    for i, raw in enumerate(raw_jobs):
        try:
            jobs.append(JobConfig.model_validate(raw))
        except Exception as e:  # noqa: BLE001 — reported with the entry index
            raise TransferError(f"job #{i + 1} is invalid: {e}") from e
    return jobs


def copy_name(name: str, existing: set[str]) -> str:
    """'daily' -> 'daily-2' (or -3, ...) avoiding every name in ``existing``."""
    lowered = {e.casefold() for e in existing}
    n = 2
    while f"{name}-{n}".casefold() in lowered:
        n += 1
    return f"{name}-{n}"


def export_settings(config: dict[str, Any]) -> dict[str, Any]:
    sections = {k: config[k] for k in SETTINGS_SECTIONS if k in config}
    return {
        "reportflow_export": SETTINGS_KIND,
        "version": FORMAT_VERSION,
        "settings": sections,
    }


def parse_settings_file(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("reportflow_export") != SETTINGS_KIND:
        raise TransferError("this file is not a ReportFlow settings export")
    sections = data.get("settings")
    if not isinstance(sections, dict):
        raise TransferError("the export contains no settings")
    unknown = set(sections) - set(SETTINGS_SECTIONS)
    if unknown:
        raise TransferError(f"unknown settings section(s): {sorted(unknown)}")
    if not sections:
        raise TransferError("the export contains no settings sections")
    return sections
