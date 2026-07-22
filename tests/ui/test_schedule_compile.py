"""Round-trip tests for the pure schedule <-> cron helpers (no Qt)."""

from __future__ import annotations

import pytest

from reportflow.ui.schedule_compile import ScheduleSpec, compile_spec, describe, parse_crons


def test_manual_round_trip():
    assert compile_spec(ScheduleSpec(mode="manual")) == []
    assert parse_crons([]).mode == "manual"
    assert describe([]) == "Manual"


def test_daily_multiple_times():
    spec = ScheduleSpec(mode="daily", times=["18:45", "06:15"])
    crons = compile_spec(spec)
    assert crons == ["15 6 * * *", "45 18 * * *"]  # sorted by time

    back = parse_crons(crons)
    assert back.mode == "daily"
    assert back.times == ["06:15", "18:45"]
    assert describe(crons) == "Daily at 06:15, 18:45"


def test_weekly_round_trip():
    spec = ScheduleSpec(mode="weekly", times=["06:00", "18:00"], weekdays=["WED", "MON"])
    crons = compile_spec(spec)
    assert crons == ["0 6 * * MON,WED", "0 18 * * MON,WED"]  # weekday order normalized

    back = parse_crons(crons)
    assert back.mode == "weekly"
    assert back.weekdays == ["MON", "WED"]
    assert back.times == ["06:00", "18:00"]
    assert describe(crons) == "Weekly Mon, Wed at 06:00, 18:00"


def test_monthly_round_trip():
    spec = ScheduleSpec(mode="monthly", times=["07:30"], month_days=[15, 1])
    crons = compile_spec(spec)
    assert crons == ["30 7 1,15 * *"]

    back = parse_crons(crons)
    assert back.mode == "monthly"
    assert back.month_days == [1, 15]
    assert describe(crons) == "Monthly day 1, 15 at 07:30"


def test_advanced_preserved():
    raw = ["*/5 9-17 * * MON-FRI"]
    spec = parse_crons(raw)
    assert spec.mode == "advanced"
    assert spec.crons == raw
    assert compile_spec(spec) == raw
    assert describe(raw).startswith("Cron:")


def test_mixed_signatures_fall_back_to_advanced():
    crons = ["0 6 * * *", "0 7 * * MON"]  # different dom/dow signatures
    assert parse_crons(crons).mode == "advanced"


def test_invalid_time_rejected():
    with pytest.raises(ValueError):
        compile_spec(ScheduleSpec(mode="daily", times=["25:00"]))


def test_weekly_requires_weekday():
    with pytest.raises(ValueError):
        compile_spec(ScheduleSpec(mode="weekly", times=["06:00"], weekdays=[]))


def test_times_deduped():
    crons = compile_spec(ScheduleSpec(mode="daily", times=["06:00", "06:00"]))
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
