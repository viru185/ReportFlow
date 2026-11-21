"""Pure schedule <-> cron helpers (no Qt) so the schedule builder is unit-testable.

A job's schedule is a list of 5-field cron expressions. The UI edits it as a list of
``ScheduleRule``s — e.g. "daily at 06:00" AND "weekly on Sunday at 10:00" — each a kind plus
times/weekdays/month-days. Every run-time emits one cron. ``parse_crons`` groups crons back
into rules; anything that doesn't fit a preset is kept verbatim in one ``cron`` rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

RuleKind = Literal["daily", "weekly", "monthly", "cron"]

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


@dataclass
class ScheduleRule:
    kind: RuleKind = "daily"
    times: list[str] = field(default_factory=list)  # "HH:MM", for daily/weekly/monthly
    weekdays: list[str] = field(default_factory=list)  # subset of WEEKDAYS, for weekly
    month_days: list[int] = field(default_factory=list)  # 1-31, for monthly
    crons: list[str] = field(default_factory=list)  # raw expressions, for cron


def _validate_times(times: list[str]) -> list[str]:
    cleaned: list[str] = []
    for t in times:
        t = t.strip()
        if not _TIME_RE.match(t):
            raise ValueError(f"invalid time (expected HH:MM): {t!r}")
        t = f"{int(t.split(':')[0]):02d}:{t.split(':')[1]}"
        if t not in cleaned:
            cleaned.append(t)
    return sorted(cleaned)


def _rule_fields(rule: ScheduleRule) -> tuple[str, str]:
    """The (day-of-month, day-of-week) cron fields of a preset rule (validated)."""
    if rule.kind == "daily":
        return "*", "*"
    if rule.kind == "weekly":
        days = [d for d in WEEKDAYS if d in {w.upper() for w in rule.weekdays}]
        if not days:
            raise ValueError("a weekly schedule needs at least one weekday")
        return "*", ",".join(days)
    if rule.kind == "monthly":
        days_int = sorted({d for d in rule.month_days if 1 <= d <= 31})
        if not days_int:
            raise ValueError("a monthly schedule needs at least one day of the month (1-31)")
        return ",".join(str(d) for d in days_int), "*"
    raise ValueError(f"unknown schedule kind: {rule.kind}")  # pragma: no cover


def compile_rule(rule: ScheduleRule) -> list[str]:
    """One rule -> its cron expressions (one per run-time)."""
    if rule.kind == "cron":
        return [c.strip() for c in rule.crons if c.strip()]
    times = _validate_times(rule.times)
    if not times:
        raise ValueError(f"the {rule.kind} schedule needs at least one run time (HH:MM)")
    dom, dow = _rule_fields(rule)
    crons = []
    for t in times:
        hh, mm = t.split(":")
        crons.append(f"{int(mm)} {int(hh)} {dom} * {dow}")
    return crons


@dataclass(frozen=True)
class Conflict:
    """Schedule ``rule`` (0-based, the later card) clashes with schedule ``other``."""

    rule: int
    other: int
    message: str


def _moments(rule: ScheduleRule) -> set[tuple[str, str]]:
    """When a rule fires, as (day, time) — ``("*", t)`` daily, ``("MON", t)`` weekly,
    ``("d1", t)`` monthly, ``("cron", expr)`` custom. Empty for an incomplete rule."""
    if rule.kind == "cron":
        return {("cron", " ".join(c.split())) for c in rule.crons if c.strip()}
    try:
        times = _validate_times(rule.times)
    except ValueError:
        return set()
    if rule.kind == "daily":
        days = ["*"]
    elif rule.kind == "weekly":
        days = [d for d in WEEKDAYS if d in {w.upper() for w in rule.weekdays}]
    else:
        days = [f"d{d}" for d in sorted({d for d in rule.month_days if 1 <= d <= 31})]
    return {(day, t) for day in days for t in times}


def _clashes(mine: set[tuple[str, str]], theirs: set[tuple[str, str]]) -> list[tuple[str, str]]:
    """The moments of ``mine`` that ``theirs`` also fires at (sorted)."""
    daily = {t for day, t in theirs if day == "*"}
    dated = {t for day, t in theirs if day not in ("*", "cron")}
    hits = []
    for day, t in mine:
        if day == "cron":
            hit = (day, t) in theirs  # the very same expression
        elif day == "*":
            hit = t in daily or t in dated  # every day includes their days
        else:
            hit = (day, t) in theirs or t in daily
        if hit:
            hits.append((day, t))
    return sorted(hits)


def _when(moment: tuple[str, str]) -> str:
    day, t = moment
    if day == "cron":
        return t
    if day == "*":
        return t
    if day.startswith("d"):
        return f"day {day[1:]} at {t}"
    return f"{day.capitalize()} {t}"


def find_conflicts(rules: list[ScheduleRule]) -> list[Conflict]:
    """Schedules that would start the job twice at the same moment — each trigger is its
    own run (two runs, two emails), so the editor refuses them instead of silently merging
    them. One conflict per schedule, reported on the later one. Weekly-vs-monthly dates
    that only sometimes coincide aren't flagged; the service skips such a second start."""
    moments = [_moments(rule) for rule in rules]
    found: list[Conflict] = []
    for j, mine in enumerate(moments):
        for i in range(j):
            theirs = moments[i]
            if not mine or not theirs:
                continue
            name = describe_rule(rules[i])
            if mine == theirs and rules[i].kind == rules[j].kind:
                found.append(Conflict(j, i, f"Same as the schedule above ({name}) — remove one."))
                break
            clash = _clashes(mine, theirs)
            if clash:
                found.append(
                    Conflict(
                        j,
                        i,
                        f"{_when(clash[0])} is already in the schedule above ({name}) — the job "
                        "would run twice at the same moment.",
                    )
                )
                break
    return found


def compile_rules(rules: list[ScheduleRule]) -> list[str]:
    """All rules -> one de-duplicated cron list (empty = manual only).

    Raises ValueError with a user-facing message for an incomplete or overlapping rule.
    """
    crons: list[str] = []
    for rule in rules:
        for cron in compile_rule(rule):
            if cron not in crons:
                crons.append(cron)
    conflicts = find_conflicts(rules)
    if conflicts:
        raise ValueError(conflicts[0].message)
    return crons


def _preset_signature(cron: str) -> tuple[RuleKind, tuple[str, str], str] | None:
    """``(kind, (dom, dow), "HH:MM")`` when a cron is one run-time of a preset rule."""
    fields = cron.split()
    if len(fields) != 5:
        return None
    minute, hour, dom, month, dow = fields
    if month != "*" or not minute.isdigit() or not hour.isdigit():
        return None
    if int(hour) > 23 or int(minute) > 59:
        return None
    time = f"{int(hour):02d}:{int(minute):02d}"
    if dom == "*" and dow == "*":
        return "daily", (dom, dow), time
    if dom == "*":
        days = [d.strip().upper() for d in dow.split(",")]
        if all(d in WEEKDAYS for d in days):
            return "weekly", ("*", ",".join(d for d in WEEKDAYS if d in days)), time
        return None
    if dow == "*":
        parts = dom.split(",")
        if all(p.isdigit() and 1 <= int(p) <= 31 for p in parts):
            return "monthly", (",".join(str(d) for d in sorted(int(p) for p in parts)), "*"), time
    return None


def parse_crons(crons: list[str]) -> list[ScheduleRule]:
    """Best-effort inverse of :func:`compile_rules`: crons sharing a day pattern become one
    rule (with several times); leftovers are kept verbatim in a final ``cron`` rule."""
    rules: dict[tuple[str, str], ScheduleRule] = {}
    leftovers: list[str] = []
    for cron in (c.strip() for c in crons):
        if not cron:
            continue
        sig = _preset_signature(cron)
        if sig is None:
            leftovers.append(cron)
            continue
        kind, (dom, dow), time = sig
        rule = rules.get((dom, dow))
        if rule is None:
            rule = ScheduleRule(kind=kind)
            if kind == "weekly":
                rule.weekdays = dow.split(",")
            elif kind == "monthly":
                rule.month_days = [int(d) for d in dom.split(",")]
            rules[(dom, dow)] = rule
        if time not in rule.times:
            rule.times.append(time)
    result = list(rules.values())
    for rule in result:
        rule.times.sort()
    if leftovers:
        result.append(ScheduleRule(kind="cron", crons=leftovers))
    return result


def describe_rule(rule: ScheduleRule) -> str:
    times = ", ".join(rule.times)
    if rule.kind == "daily":
        return f"Daily at {times}"
    if rule.kind == "weekly":
        days = ", ".join(d.capitalize() for d in rule.weekdays)
        return f"Weekly {days} at {times}"
    if rule.kind == "monthly":
        days = ", ".join(str(d) for d in rule.month_days)
        return f"Monthly day {days} at {times}"
    return "Cron: " + "; ".join(rule.crons)


def describe(crons: list[str]) -> str:
    """Short human-readable schedule summary, e.g. for the dashboard job cards."""
    rules = parse_crons(crons)
    if not rules:
        return "Manual"
    return "; ".join(describe_rule(r) for r in rules)


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


def ago_text(iso: str | None, now: datetime | None = None) -> str | None:
    """Compact relative phrasing of a past ISO timestamp for the job card.

    "just now" / "5m ago" / "3h ago" (within 2 days) / "2d ago" (within a week) /
    "2026-07-01". Returns None for missing/invalid input so callers can skip the segment.
    """
    if not iso:
        return None
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return None
    when = when.replace(tzinfo=None)  # records may carry a timezone
    now = now or datetime.now()
    seconds = (now - when).total_seconds()
    if seconds < 0:
        return None
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 48 * 3600:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 7 * 86400:
        return f"{int(seconds // 86400)}d ago"
    return when.strftime("%Y-%m-%d")
