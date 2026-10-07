"""Round-trip tests for the pure schedule <-> cron helpers (no Qt)."""

from __future__ import annotations

import pytest

from reportflow.ui.schedule_compile import ScheduleRule, compile_rules, describe, parse_crons


def test_manual_round_trip():
    assert compile_rules([]) == []
    assert parse_crons([]) == []
    assert describe([]) == "Manual"


def test_daily_multiple_times():
    crons = compile_rules([ScheduleRule(kind="daily", times=["18:45", "06:15"])])
    assert crons == ["15 6 * * *", "45 18 * * *"]  # sorted by time

    [back] = parse_crons(crons)
    assert back.kind == "daily"
    assert back.times == ["06:15", "18:45"]
    assert describe(crons) == "Daily at 06:15, 18:45"


def test_weekly_round_trip():
    rule = ScheduleRule(kind="weekly", times=["06:00", "18:00"], weekdays=["WED", "MON"])
    crons = compile_rules([rule])
    assert crons == ["0 6 * * MON,WED", "0 18 * * MON,WED"]  # weekday order normalized

    [back] = parse_crons(crons)
    assert back.kind == "weekly"
    assert back.weekdays == ["MON", "WED"]
    assert back.times == ["06:00", "18:00"]
    assert describe(crons) == "Weekly Mon, Wed at 06:00, 18:00"


def test_monthly_round_trip():
    crons = compile_rules([ScheduleRule(kind="monthly", times=["07:30"], month_days=[15, 1])])
    assert crons == ["30 7 1,15 * *"]

    [back] = parse_crons(crons)
    assert back.kind == "monthly"
    assert back.month_days == [1, 15]
    assert describe(crons) == "Monthly day 1, 15 at 07:30"


def test_daily_plus_sunday_at_another_time():
    """The owner's case: one report daily AND on Sunday at a different time."""
    rules = [
        ScheduleRule(kind="daily", times=["06:00"]),
        ScheduleRule(kind="weekly", times=["10:00"], weekdays=["SUN"]),
    ]
    crons = compile_rules(rules)
    assert crons == ["0 6 * * *", "0 10 * * SUN"]
    assert [(r.kind, r.times) for r in parse_crons(crons)] == [
        ("daily", ["06:00"]),
        ("weekly", ["10:00"]),
    ]
    assert describe(crons) == "Daily at 06:00; Weekly Sun at 10:00"


def test_overlapping_rules_rejected():
    """Each cron is its own trigger — the same moment twice would run (and email) twice."""
    with pytest.raises(ValueError, match="already in the daily schedule"):
        compile_rules(
            [
                ScheduleRule(kind="daily", times=["06:00"]),
                ScheduleRule(kind="weekly", times=["06:00"], weekdays=["SUN"]),
            ]
        )
    with pytest.raises(ValueError, match="in two schedules"):
        compile_rules(
            [
                ScheduleRule(kind="weekly", times=["06:00"], weekdays=["MON", "SUN"]),
                ScheduleRule(kind="weekly", times=["06:00"], weekdays=["SUN"]),
            ]
        )


def test_custom_cron_preserved_alongside_presets():
    raw = ["0 6 * * *", "*/5 9-17 * * MON-FRI"]
    rules = parse_crons(raw)
    assert [r.kind for r in rules] == ["daily", "cron"]
    assert rules[1].crons == ["*/5 9-17 * * MON-FRI"]
    assert compile_rules(rules) == raw
    assert describe(raw) == "Daily at 06:00; Cron: */5 9-17 * * MON-FRI"


def test_mixed_signatures_become_separate_rules():
    crons = ["0 6 * * *", "0 7 * * MON", "30 7 * * MON"]
    rules = parse_crons(crons)
    assert [(r.kind, r.times) for r in rules] == [
        ("daily", ["06:00"]),
        ("weekly", ["07:00", "07:30"]),
    ]


def test_invalid_time_rejected():
    with pytest.raises(ValueError):
        compile_rules([ScheduleRule(kind="daily", times=["25:00"])])


def test_rule_needs_a_time_and_weekly_a_weekday():
    with pytest.raises(ValueError, match="at least one run time"):
        compile_rules([ScheduleRule(kind="daily")])
    with pytest.raises(ValueError, match="weekday"):
        compile_rules([ScheduleRule(kind="weekly", times=["06:00"], weekdays=[])])


def test_times_deduped():
    crons = compile_rules([ScheduleRule(kind="daily", times=["06:00", "06:00"])])
    assert crons == ["0 6 * * *"]


def test_friendly_time_phrases():
    from datetime import datetime

    from reportflow.ui.schedule_compile import friendly_time

    now = datetime(2026, 7, 15, 12, 0, 0)  # a Wednesday
    assert friendly_time("2026-07-15T18:00:00", now) == "today 18:00"
    assert friendly_time("2026-07-16T06:00:00", now) == "tomorrow 06:00"
    assert friendly_time("2026-07-20T06:00:00", now) == "Mon 06:00"  # within a week
    assert friendly_time("2026-08-01T06:00:00", now) == "2026-08-01 06:00"
    assert friendly_time(None, now) is None
    assert friendly_time("not-a-date", now) is None
    # Aware timestamps (APScheduler hands those back) don't blow up.
    assert friendly_time("2026-07-15T18:00:00+05:30", now) == "today 18:00"


def test_ago_text_phrases():
    from datetime import datetime

    from reportflow.ui.schedule_compile import ago_text

    now = datetime(2026, 7, 15, 12, 0, 0)
    assert ago_text("2026-07-15T11:59:30", now) == "just now"
    assert ago_text("2026-07-15T11:55:00", now) == "5m ago"
    assert ago_text("2026-07-15T09:00:00", now) == "3h ago"
    assert ago_text("2026-07-14T09:00:00", now) == "27h ago"  # under 2 days stays in hours
    assert ago_text("2026-07-13T09:00:00", now) == "2d ago"
    assert ago_text("2026-07-01T09:00:00", now) == "2026-07-01"
    assert ago_text(None, now) is None
    assert ago_text("not-a-date", now) is None
    assert ago_text("2026-07-16T09:00:00", now) is None  # future -> skip the segment
    # Aware timestamps don't blow up.
    assert ago_text("2026-07-15T11:00:00+05:30", now) == "1h ago"
