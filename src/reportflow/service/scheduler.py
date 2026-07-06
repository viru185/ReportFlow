"""APScheduler wiring: one cron trigger per enabled, scheduled job.

A bad cron expression on one job is logged and skipped; it never prevents the scheduler from
starting or other jobs from being scheduled.
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from reportflow.core.config.models import AppConfig
from reportflow.core.state import RunTrigger
from reportflow.service.launcher import Launcher


class SchedulerService:
    def __init__(self, launcher: Launcher) -> None:
        self.launcher = launcher
        self.scheduler = BackgroundScheduler()

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def scheduled_job_names(self) -> list[str]:
        return [j.id for j in self.scheduler.get_jobs()]

    def rebuild(self, config: AppConfig) -> None:
        """Replace all scheduled jobs from the current config."""
        self.scheduler.remove_all_jobs()
        for job in config.jobs:
            if not job.enabled or not job.schedule_cron:
                continue
            try:
                trigger = CronTrigger.from_crontab(job.schedule_cron)
            except Exception as e:  # noqa: BLE001 — one bad cron must not break scheduling
                logger.error(
                    "Skipping job {!r}: invalid cron {!r}: {}", job.name, job.schedule_cron, e
                )
                continue
            self.scheduler.add_job(
                self._fire,
                trigger=trigger,
                args=[job.name],
                id=job.name,
                name=job.name,
                coalesce=True,
                misfire_grace_time=300,
                max_instances=1,
                replace_existing=True,
            )
            logger.info("Scheduled job {!r}: {}", job.name, job.schedule_cron)

    def _fire(self, name: str) -> None:
        try:
            self.launcher.submit_job_by_name(name, RunTrigger.SCHEDULED, is_test=False)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to launch scheduled job {!r}: {}", name, e)
