"""FastAPI application wiring: state, lifespan, and all local-only endpoints."""

from __future__ import annotations

import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel

from reportflow import __version__
from reportflow.core import paths, secrets
from reportflow.core.config.loader import ConfigError, load_config, save_config
from reportflow.core.config.models import AppConfig, JobConfig
from reportflow.core.email import (
    build_log_bundle,
    redact_config,
    render_email,
    resolve_template,
    sample_context,
    send_dev_log_bundle,
)
from reportflow.core.secrets import SMTP_PASSWORD_KEY
from reportflow.core.state import RunStore, RunTrigger
from reportflow.service.bootstrap import seed_data_files
from reportflow.service.launcher import Launcher
from reportflow.service.scheduler import SchedulerService
from reportflow.service.workbook import WorkbookError, discover_sheets


class ServiceState:
    """Holds the reloadable config plus the run store, launcher, and scheduler."""

    def __init__(self, worker_command: list[str] | None = None) -> None:
        seed_data_files()
        self.config_error: str | None = None
        self.config: AppConfig = self._load_or_default()
        self.run_store = RunStore()
        self.launcher = Launcher(self.run_store, lambda: self.config, worker_command=worker_command)
        self.scheduler = SchedulerService(self.launcher)
        self._lock = threading.Lock()

    def _load_or_default(self) -> AppConfig:
        try:
            config = load_config()
            self.config_error = None
            return config
        except ConfigError as e:
            logger.error("Config invalid at startup; API stays up, scheduling disabled: {}", e)
            self.config_error = str(e)
            self._backup_invalid_config()
            from reportflow.core.config.defaults import default_config

            return default_config()

    @staticmethod
    def _backup_invalid_config() -> None:
        """Preserve the broken file — a later Settings save would silently overwrite it."""
        src = paths.config_file()
        if not src.exists():
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = src.with_name(f"{src.name}.invalid-{stamp}")
        try:
            backup.write_bytes(src.read_bytes())
            logger.warning("Backed up the invalid config to {}", backup)
        except OSError as e:
            logger.error("Could not back up the invalid config: {}", e)

    def reload(self) -> None:
        with self._lock:
            self.config = load_config()
            self.config_error = None
            self.scheduler.rebuild(self.config)

    def save_jobs(self, jobs: list[JobConfig]) -> None:
        """Validate (uniqueness), persist, and re-schedule with the new job list."""
        with self._lock:
            data = self.config.model_dump(mode="python", by_alias=True)
            data["job"] = [j.model_dump(mode="python", by_alias=True) for j in jobs]
            new_config = AppConfig.model_validate(data)
            save_config(new_config)
            self.config = new_config
            self.config_error = None
            self.scheduler.rebuild(new_config)

    def save_settings(self, sections: dict[str, Any]) -> None:
        """Merge the given non-job sections (app/smtp/ui/email/test) into the config,
        validate, persist, and re-schedule. Jobs are never touched here."""
        allowed = {"app", "smtp", "ui", "email", "test"}
        unknown = set(sections) - allowed
        if unknown:
            raise ValueError(f"unknown settings section(s): {sorted(unknown)}")
        with self._lock:
            data = self.config.model_dump(mode="python", by_alias=True)
            for key, value in sections.items():
                data[key] = value
            new_config = AppConfig.model_validate(data)
            save_config(new_config)
            self.config = new_config
            self.config_error = None
            self.scheduler.rebuild(new_config)
        self._apply_log_level()

    def _apply_log_level(self) -> None:
        from reportflow.core.logging_setup import reconfigure

        reconfigure("service", level="DEBUG" if self.config.app.debug_logging else "INFO")


# --- request/response models ---------------------------------------------------


class SheetsRequest(BaseModel):
    path: str


class EmailPreviewRequest(BaseModel):
    job_name: str | None = None


class SettingsUpdate(BaseModel):
    app: dict[str, Any] | None = None
    smtp: dict[str, Any] | None = None
    ui: dict[str, Any] | None = None
    email: dict[str, Any] | None = None
    test: dict[str, Any] | None = None


class SmtpPasswordUpdate(BaseModel):
    password: str


class SmtpTestRequest(BaseModel):
    host: str = ""
    port: int = 587
    use_starttls: bool = True
    use_ssl: bool = False
    from_address: str = ""
    username: str | None = None
    password: str | None = None  # None/empty -> fall back to the stored secret


class EmailTemplateUpdate(BaseModel):
    content: str


class RunResponse(BaseModel):
    run_id: str
    status: str = "running"


# --- app factory ---------------------------------------------------------------


def create_app(state: ServiceState | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        st: ServiceState = app.state.svc
        st.scheduler.start()
        st.scheduler.rebuild(st.config)
        logger.info("Service started (version {})", __version__)
        try:
            yield
        finally:
            st.scheduler.shutdown()
            logger.info("Service stopped")

    app = FastAPI(title="ReportFlow Service", version=__version__, lifespan=lifespan)
    app.state.svc = state or ServiceState()

    def svc() -> ServiceState:
        return app.state.svc

    def _require_job(name: str) -> JobConfig:
        job = svc().config.job(name)
        if job is None:
            raise HTTPException(status_code=404, detail=f"unknown job: {name}")
        return job

    def _job_summary(job: JobConfig) -> dict[str, Any]:
        latest = svc().run_store.latest_for_job(job.name)
        last_failure = svc().run_store.latest_failure_for_job(job.name)
        return {
            "name": job.name,
            "enabled": job.enabled,
            "schedule_crons": job.schedule_crons,
            "sheet_names": job.sheet_names,
            "last_status": str(latest.status) if latest else None,
            "last_run_at": latest.started_at if latest else None,
            "last_failure_at": last_failure.started_at if last_failure else None,
            "last_email_note": latest.email_note if latest else None,
            "last_email_failed": bool(latest and (latest.email_note or "").startswith("failed:")),
        }

    # -- system ----------------------------------------------------------------

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__}

    @app.get("/system/status")
    def system_status() -> dict[str, Any]:
        username = os.environ.get("USERNAME", "")
        return {
            "version": __version__,
            "active_runs": svc().launcher.active_run_ids(),
            "scheduled_jobs": svc().scheduler.scheduled_job_names(),
            "job_count": len(svc().config.jobs),
            "config_error": svc().config_error,
            # The Windows identity the service (and thus its Excel workers) runs as. A name
            # ending in "$" is the machine account (LocalSystem), under which VSTO add-ins
            # like PI DataLink cannot load — the UI warns about this.
            "service_account": f"{os.environ.get('USERDOMAIN', '')}\\{username}".strip("\\"),
            "service_account_is_system": username.endswith("$"),
        }

    @app.get("/config")
    def get_config() -> dict[str, Any]:
        return redact_config(svc().config)

    @app.post("/config/reload")
    def reload_config() -> dict[str, Any]:
        try:
            svc().reload()
        except ConfigError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True, "job_count": len(svc().config.jobs)}

    @app.put("/settings")
    def update_settings(update: SettingsUpdate) -> dict[str, Any]:
        sections = {k: v for k, v in update.model_dump().items() if v is not None}
        logger.info("API: settings update for section(s) {}", sorted(sections))
        if not sections:
            raise HTTPException(status_code=400, detail="no settings sections provided")
        try:
            svc().save_settings(sections)
        except Exception as e:  # noqa: BLE001 — validation / write error -> 400
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True, "sections": sorted(sections)}

    @app.get("/system/smtp-password")
    def smtp_password_status() -> dict[str, Any]:
        return {"set": secrets.has_secret(SMTP_PASSWORD_KEY)}

    @app.post("/system/smtp-password")
    def set_smtp_password(update: SmtpPasswordUpdate) -> dict[str, Any]:
        if not update.password:
            raise HTTPException(status_code=400, detail="password must not be empty")
        secrets.set_secret(SMTP_PASSWORD_KEY, update.password)
        return {"ok": True, "set": True}

    @app.delete("/system/smtp-password")
    def clear_smtp_password() -> dict[str, Any]:
        secrets.delete_secret(SMTP_PASSWORD_KEY)
        return {"ok": True, "set": False}

    @app.post("/system/smtp-test")
    def smtp_test(req: SmtpTestRequest) -> dict[str, Any]:
        from reportflow.core.config.models import SmtpConfig
        from reportflow.core.email.sender import test_smtp_connection

        try:
            smtp = SmtpConfig.model_validate(req.model_dump(exclude={"password"}))
            test_smtp_connection(smtp, req.password or None)
        except Exception as e:  # noqa: BLE001 — surface the reason to the UI
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"ok": True}

    @app.get("/system/logs")
    def system_logs(process: str = "service", tail: int = 500) -> dict[str, Any]:
        if process not in ("service", "worker", "ui"):
            raise HTTPException(status_code=400, detail=f"unknown process: {process}")
        log_path = paths.logs_dir() / process / f"{process}.log"
        if not log_path.exists():
            return {"process": process, "log": ""}
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"process": process, "log": "\n".join(lines[-min(tail, 5000) :])}

    # -- jobs ------------------------------------------------------------------

    @app.get("/jobs")
    def list_jobs() -> list[dict[str, Any]]:
        return [_job_summary(j) for j in svc().config.jobs]

    @app.get("/jobs/{name}")
    def get_job(name: str) -> dict[str, Any]:
        job = _require_job(name)
        return {"job": job.model_dump(mode="json"), "summary": _job_summary(job)}

    @app.post("/jobs", status_code=201)
    def create_job(job: JobConfig) -> dict[str, Any]:
        logger.info("API: create job {!r}", job.name)
        if svc().config.job(job.name) is not None:
            raise HTTPException(status_code=409, detail=f"job already exists: {job.name}")
        jobs = [*svc().config.jobs, job]
        _save_jobs_or_400(svc(), jobs)
        return {"ok": True, "name": job.name}

    @app.put("/jobs/{name}")
    def update_job(name: str, job: JobConfig) -> dict[str, Any]:
        logger.info("API: update job {!r}", name)
        _require_job(name)
        jobs = [job if j.name.casefold() == name.casefold() else j for j in svc().config.jobs]
        _save_jobs_or_400(svc(), jobs)
        return {"ok": True, "name": job.name}

    @app.delete("/jobs/{name}")
    def delete_job(name: str) -> dict[str, Any]:
        logger.info("API: delete job {!r}", name)
        _require_job(name)
        jobs = [j for j in svc().config.jobs if j.name.casefold() != name.casefold()]
        _save_jobs_or_400(svc(), jobs)
        return {"ok": True}

    @app.post("/jobs/{name}/run", response_model=RunResponse)
    def run_job(name: str) -> RunResponse:
        logger.info("API: manual run requested for {!r}", name)
        _require_job(name)
        run_id = svc().launcher.submit_job_by_name(name, RunTrigger.MANUAL, is_test=False)
        return RunResponse(run_id=run_id)

    @app.post("/jobs/{name}/test", response_model=RunResponse)
    def test_job(name: str) -> RunResponse:
        logger.info("API: test run requested for {!r}", name)
        _require_job(name)
        run_id = svc().launcher.submit_job_by_name(name, RunTrigger.TEST, is_test=True)
        return RunResponse(run_id=run_id)

    @app.post("/jobs/{name}/dry-run", response_model=RunResponse)
    def dry_run_job(name: str) -> RunResponse:
        # Build + validate the report (so the #NAME?/error-cell scan runs) but never email.
        logger.info("API: dry run requested for {!r}", name)
        _require_job(name)
        run_id = svc().launcher.submit_job_by_name(name, RunTrigger.DRY_RUN, is_test=True)
        return RunResponse(run_id=run_id)

    def _job_template_path(job: JobConfig) -> Path:
        return paths.templates_dir() / "jobs" / f"{job.name}.html"

    @app.get("/jobs/{name}/email-template")
    def get_email_template(name: str) -> dict[str, Any]:
        job = _require_job(name)
        # Prefer the job's configured template; fall back to the conventional per-job file.
        path = Path(job.email_template_path) if job.email_template_path else _job_template_path(job)
        if path.exists():
            return {"content": path.read_text(encoding="utf-8"), "exists": True}
        return {"content": "", "exists": False}

    @app.put("/jobs/{name}/email-template")
    def put_email_template(name: str, update: EmailTemplateUpdate) -> dict[str, Any]:
        job = _require_job(name)
        path = _job_template_path(job)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(update.content, encoding="utf-8")
        if job.email_template_path != path:
            updated = job.model_copy(update={"email_template_path": path})
            jobs = [
                updated if j.name.casefold() == name.casefold() else j for j in svc().config.jobs
            ]
            _save_jobs_or_400(svc(), jobs)
        return {"ok": True, "path": str(path)}

    # -- runs ------------------------------------------------------------------

    @app.get("/runs")
    def list_runs(job: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return [r.model_dump(mode="json") for r in svc().run_store.list(job, min(limit, 500))]

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        rec = svc().run_store.get(run_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="unknown run")
        return rec.model_dump(mode="json")

    @app.get("/runs/{run_id}/log")
    def get_run_log(run_id: str, tail: int = 400) -> dict[str, Any]:
        rec = svc().run_store.get(run_id)
        if rec is None or not rec.worker_log_path:
            raise HTTPException(status_code=404, detail="no log for run")
        path = Path(rec.worker_log_path)
        if not path.exists():
            return {"run_id": run_id, "log": ""}
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"run_id": run_id, "log": "\n".join(lines[-tail:])}

    # -- workbook / email ------------------------------------------------------

    @app.post("/workbook/sheets")
    def workbook_sheets(req: SheetsRequest) -> dict[str, Any]:
        try:
            return {"sheets": discover_sheets(Path(req.path))}
        except WorkbookError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/email/preview")
    def email_preview(req: EmailPreviewRequest) -> dict[str, Any]:
        job = svc().config.job(req.job_name) if req.job_name else None
        html = render_email(resolve_template(job, svc().config), sample_context(job))
        return {"html": html}

    @app.post("/system/send-dev-logs")
    def send_dev_logs() -> dict[str, Any]:
        st = svc()
        if not st.config.test.developer_bundle_recipients:
            raise HTTPException(status_code=400, detail="no developer_bundle_recipients configured")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bundle = paths.state_dir() / "bundles" / f"reportflow_logs_{stamp}.zip"
        metadata = {
            "hostname": os.environ.get("COMPUTERNAME", "host"),
            "windows_user": os.environ.get("USERNAME", "unknown"),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
        build_log_bundle(bundle, st.config, metadata=metadata)
        try:
            recipients = send_dev_log_bundle(st.config, bundle, metadata)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"failed to send: {e}") from e
        return {"ok": True, "recipients": recipients, "bundle": str(bundle)}

    @app.post("/system/export-logs")
    def export_logs() -> dict[str, Any]:
        """Build the diagnostic zip on disk WITHOUT emailing it — for when SMTP is down and
        the logs must be sent to the developer by hand."""
        st = svc()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bundle = paths.state_dir() / "bundles" / f"reportflow_logs_{stamp}.zip"
        metadata = {
            "hostname": os.environ.get("COMPUTERNAME", "host"),
            "windows_user": os.environ.get("USERNAME", "unknown"),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
        build_log_bundle(bundle, st.config, metadata=metadata)
        logger.info("API: exported diagnostic bundle to {}", bundle)
        return {"ok": True, "bundle": str(bundle)}

    return app


def _save_jobs_or_400(state: ServiceState, jobs: list[JobConfig]) -> None:
    try:
        state.save_jobs(jobs)
    except Exception as e:  # noqa: BLE001 — validation / write error -> 400
        raise HTTPException(status_code=400, detail=str(e)) from e
