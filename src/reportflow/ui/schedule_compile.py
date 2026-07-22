"""Pure schedule <-> cron helpers (no Qt) so the schedule builder is unit-testable.

A job's schedule is a list of 5-field cron expressions. The UI edits it through a
``ScheduleSpec``: a mode plus times/weekdays/month-days. Multiple run-times per day emit one
cron per time. ``parse_crons`` is best-effort — anything that doesn't fit a preset comes back
as ``advanced`` with the raw expressions preserved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Mode = Literal["manual", "daily", "weekly", "monthly", "advanced"]

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


@dataclass
class ScheduleSpec:
    mode: Mode = "manual"
    times: list[str] = field(default_factory=list)  # "HH:MM", used by daily/weekly/monthly
    weekdays: list[str] = field(default_factory=list)  # subset of WEEKDAYS, for weekly
    month_days: list[int] = field(default_factory=list)  # 1-31, for monthly
    crons: list[str] = field(default_factory=list)  # raw expressions, for advanced


def _validate_times(times: list[str]) -> list[str]:
    cleaned: list[str] = []
    for t in times:
        t = t.strip()
        if not _TIME_RE.match(t):
            raise ValueError(f"invalid time (expected HH:MM): {t!r}")
        if t not in cleaned:
            cleaned.append(t)
    return sorted(cleaned)


def compile_spec(spec: ScheduleSpec) -> list[str]:
    """Compile a ScheduleSpec into a list of 5-field cron expressions."""
    if spec.mode == "manual":
        return []
    if spec.mode == "advanced":
        return [c.strip() for c in spec.crons if c.strip()]

    times = _validate_times(spec.times)
    if not times:
        raise ValueError("at least one run time (HH:MM) is required")

    if spec.mode == "daily":
        dom, dow = "*", "*"
    elif spec.mode == "weekly":
        days = [d for d in WEEKDAYS if d in {w.upper() for w in spec.weekdays}]
        if not days:
            raise ValueError("select at least one weekday")
        dom, dow = "*", ",".join(days)
    elif spec.mode == "monthly":
        days_int = sorted({d for d in spec.month_days if 1 <= d <= 31})
        if not days_int:
            raise ValueError("select at least one day of month (1-31)")
        dom, dow = ",".join(str(d) for d in days_int), "*"
    else:  # pragma: no cover — Literal exhausts the modes
        raise ValueError(f"unknown mode: {spec.mode}")

    crons = []
    for t in times:
        hh, mm = t.split(":")
        crons.append(f"{int(mm)} {int(hh)} {dom} * {dow}")
    return crons


def parse_crons(crons: list[str]) -> ScheduleSpec:
    """Best-effort inverse of :func:`compile_spec`; falls back to ``advanced``."""
    crons = [c.strip() for c in crons if c.strip()]
    if not crons:
        return ScheduleSpec(mode="manual")

    times: list[str] = []
    signature: tuple[str, str] | None = None  # (dom, dow) shared by every entry
    for cron in crons:
        fields = cron.split()
        if len(fields) != 5:
            return ScheduleSpec(mode="advanced", crons=crons)
        minute, hour, dom, month, dow = fields
        if month != "*" or not minute.isdigit() or not hour.isdigit():
            return ScheduleSpec(mode="advanced", crons=crons)
        if signature is None:
            signature = (dom, dow)
        elif signature != (dom, dow):
            return ScheduleSpec(mode="advanced", crons=crons)
        times.append(f"{int(hour):02d}:{int(minute):02d}")

    assert signature is not None
    dom, dow = signature
    times = sorted(set(times))

    if dom == "*" and dow == "*":
        return ScheduleSpec(mode="daily", times=times)
    if dom == "*":
        days = [d.strip().upper() for d in dow.split(",")]
        if all(d in WEEKDAYS for d in days):
            ordered = [d for d in WEEKDAYS if d in days]
            return ScheduleSpec(mode="weekly", times=times, weekdays=ordered)
        return ScheduleSpec(mode="advanced", crons=crons)
    if dow == "*":
        parts = dom.split(",")
        if all(p.isdigit() and 1 <= int(p) <= 31 for p in parts):
            month_days = sorted(int(p) for p in parts)
            return ScheduleSpec(mode="monthly", times=times, month_days=month_days)
    return ScheduleSpec(mode="advanced", crons=crons)


def describe(crons: list[str]) -> str:
    """Short human-readable schedule summary, e.g. for the dashboard job cards."""
    spec = parse_crons(crons)
    if spec.mode == "manual":
        return "Manual"
    times = ", ".join(spec.times)
    if spec.mode == "daily":
        return f"Daily at {times}"
    if spec.mode == "weekly":
        days = ", ".join(d.capitalize() for d in spec.weekdays)
        return f"Weekly {days} at {times}"
    if spec.mode == "monthly":
        days = ", ".join(str(d) for d in spec.month_days)
        return f"Monthly day {days} at {times}"
    return "Cron: " + "; ".join(spec.crons)


def friendly_time(iso: str | None, now: datetime | None = None) -> str | None:
    """Compact human phrasing of an upcoming ISO timestamp for the job card.

    "today 18:00" / "tomorrow 06:00" / "Mon 06:00" (within a week) / "2026-08-01 06:00".
    Returns None for missing/invalid input so callers can simply skip the segment.
    """
    if not iso:
        return None
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return None
    when = when.replace(tzinfo=None)  # scheduler may hand back an aware datetime
    now = now or datetime.now()
    clock = when.strftime("%H:%M")
    days_ahead = (when.date() - now.date()).days
    if days_ahead <= 0:
        return f"today {clock}"
    if days_ahead == 1:
        return f"tomorrow {clock}"
    if days_ahead < 7:
        return f"{when.strftime('%a')} {clock}"
    return f"{when.strftime('%Y-%m-%d')} {clock}"
