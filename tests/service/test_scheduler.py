"""The scheduler starts a job at most once per minute, whichever of its triggers fire."""

from __future__ import annotations

from types import SimpleNamespace

from reportflow.service.scheduler import SchedulerService


def test_two_triggers_meeting_start_the_job_once(monkeypatch):
    started: list[str] = []
    launcher = SimpleNamespace(submit_job_by_name=lambda name, trigger: started.append(name))
    service = SchedulerService(launcher)  # type: ignore[arg-type]
    service._fire("daily")
    service._fire("daily")  # e.g. weekly Monday 06:00 and monthly day 1 at 06:00
    service._fire("weekly")  # another job at the same minute is its own run
    assert started == ["daily", "weekly"]
    service._last_fired["daily"] = "2000-01-01 00:00"  # a later minute starts it again
    service._fire("daily")
    assert started == ["daily", "weekly", "daily"]
