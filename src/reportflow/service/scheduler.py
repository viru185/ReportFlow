"""APScheduler wiring: one cron trigger per enabled, scheduled job.

A bad cron expression on one job is logged and skipped; it never prevents the scheduler from
starting or other jobs from being scheduled.
"""

from __future__ import annotations

from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from reportflow.core.config.models import AppConfig
from reportflow.core.state import RunTrigger
from reportflow.service.launcher import Launcher

# Nightly disk housekeeping (delete logs/runs past retention) — quiet hours.
_MAINTENANCE_JOB_ID = "_reportflow_maintenance"
_MAINTENANCE_CRON = "30 3 * * *"


class SchedulerService:
    def __init__(self, launcher: Launcher, maintenance: Callable[[], None] | None = None) -> None:
        self.launcher = launcher
        self.scheduler = BackgroundScheduler()
        self._maintenance = maintenance

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def scheduled_job_names(self) -> list[str]:
        # Internal maintenance is not a user job — keep it out of status counts.
        return [j.id for j in self.scheduler.get_jobs() if j.id != _MAINTENANCE_JOB_ID]

    def next_run_times(self) -> dict[str, str]:
        """Earliest upcoming fire time per job name (ISO), across its cron triggers."""
        result: dict[str, str] = {}
        for aps_job in self.scheduler.get_jobs():
            if aps_job.id == _MAINTENANCE_JOB_ID or aps_job.next_run_time is None:
                continue
            name = aps_job.id.rsplit("#", 1)[0]  # trigger ids are "{job.name}#{index}"
            iso = aps_job.next_run_time.isoformat(timespec="seconds")
            if name not in result or iso < result[name]:
                result[name] = iso
        return result

    def rebuild(self, config: AppConfig) -> None:
        """Replace all scheduled jobs from the current config.

        A job may have several cron entries (e.g. multiple run-times per day); one trigger is
        registered per entry, with the id ``{job.name}#{index}``.
        """
        self.scheduler.remove_all_jobs()
        self._register_maintenance()
        for job in config.jobs:
            if not job.enabled or not job.schedule_crons:
                continue
            for i, cron in enumerate(job.schedule_crons):
                try:
                    trigger = CronTrigger.from_crontab(cron)
                except Exception as e:  # noqa: BLE001 — one bad cron must not break scheduling
                    logger.error("Skipping job {!r} cron {!r}: {}", job.name, cron, e)
                    continue
                self.scheduler.add_job(
                    self._fire,
                    trigger=trigger,
                    args=[job.name],
                    id=f"{job.name}#{i}",
                    name=job.name,
                    coalesce=True,
                    misfire_grace_time=300,
                    max_instances=1,
                    replace_existing=True,
                )
                logger.info("Scheduled job {!r}: {}", job.name, cron)

    def _register_maintenance(self) -> None:
        """(Re-)add the nightly purge — rebuild() wipes all jobs, so it re-registers here."""
        if self._maintenance is None:
            return
        self.scheduler.add_job(
            self._maintenance,
            trigger=CronTrigger.from_crontab(_MAINTENANCE_CRON),
            id=_MAINTENANCE_JOB_ID,
            name="log maintenance",
            coalesce=True,
            misfire_grace_time=3600,
            max_instances=1,
            replace_existing=True,
        )

    def _fire(self, name: str) -> None:
        # Recipients resolve from the job's CURRENT stage at fire time (testing -> test
        # recipients, live -> production), so promoting a job needs no re-scheduling.
        try:
            self.launcher.submit_job_by_name(name, RunTrigger.SCHEDULED)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to launch scheduled job {!r}: {}", name, e)
