"""Autocomplete sources, built from the service's ``GET /config`` snapshot.

Everything the app already knows becomes a suggestion: every address on any job (Production
and Test, To/Cc/Bcc), every email-group member, the Settings test/support addresses, and
every concurrency group in use. Pure functions over the config dict, so they are testable
without Qt or a service.
"""

from __future__ import annotations

from typing import Any

_RECIPIENT_FIELDS = ("to", "cc", "bcc")


def _unique(values: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for value in values:
        value = str(value).strip()
        if value:
            seen.setdefault(value.casefold(), value)
    return sorted(seen.values(), key=str.casefold)


def _jobs(config: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = config.get("job", config.get("jobs")) or []
    return [j for j in jobs if isinstance(j, dict)]


def email_groups(config: dict[str, Any]) -> dict[str, list[str]]:
    """``{group name: members}`` from Settings → Email groups."""
    groups = (config.get("email") or {}).get("groups") or []
    return {str(g["name"]): [str(m) for m in g.get("members") or []] for g in groups}


def known_addresses(config: dict[str, Any]) -> list[str]:
    """Every address the app has seen, de-duplicated case-insensitively, sorted."""
    found: list[str] = []
    for job in _jobs(config):
        for side in ("prod", "test"):
            recipients = job.get(side) or {}
            for key in _RECIPIENT_FIELDS:
                found.extend(recipients.get(key) or [])
    for members in email_groups(config).values():
        found.extend(members)
    test = config.get("test") or {}
    found.extend(test.get("recipients") or [])
    found.extend(test.get("developer_bundle_recipients") or [])
    return _unique(found)


def concurrency_groups(config: dict[str, Any]) -> list[str]:
    """Every concurrency group a job already uses."""
    return _unique([j.get("concurrency_group") or "" for j in _jobs(config)])


def jobs_using_group(config: dict[str, Any], name: str) -> list[str]:
    """Jobs whose recipients refer to email group ``name`` (case-insensitive)."""
    key = name.strip().casefold()
    using: list[str] = []
    for job in _jobs(config):
        for side in ("prod", "test"):
            recipients = job.get(side) or {}
            names = [n for f in _RECIPIENT_FIELDS for n in recipients.get(f"{f}_groups") or []]
            if any(str(n).casefold() == key for n in names):
                using.append(str(job.get("name")))
                break
    return using
