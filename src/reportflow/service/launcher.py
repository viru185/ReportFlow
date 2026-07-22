"""Launch and supervise one disposable worker process per job run.

Responsibilities:
* Build the ``WorkerRequest`` (resolving output-path tokens and the timeout).
* Launch the worker with no console window and its own process group so the whole tree is
  killable.
* Enforce the timeout; on expiry, tree-kill the worker (which reaps its Excel).
* Read the worker's ``result.json`` (authoritative) + exit code and record the run.
* Send email per lifecycle policy: testing-stage jobs -> test recipients on every run;
  live jobs -> production recipients. Build-only runs never email. NEVER email on failure.
* Bound parallelism: a global concurrency cap plus a per-concurrency-group mutex.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from loguru import logger

from reportflow.core import paths
from reportflow.core.config.models import AppConfig, JobConfig
from reportflow.core.email import send_report
from reportflow.core.ipc import RunStatus, WorkerRequest, read_result, write_request
from reportflow.core.state import RunRecord, RunStore, RunTrigger

_DRY_RUN_NOTE = "not sent — build only"


def _elapsed_seconds(started_at: str | None, finished_at: str | None) -> float | None:
    """Duration from the record's ISO timestamps; None when either is missing/invalid."""
    if not started_at or not finished_at:
        return None
    try:
        delta = datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)
    except ValueError:
        return None
    return max(0.0, delta.total_seconds())


def _format_duration(seconds: float | None) -> str:
    """Whole seconds render bare ("42"), fractional keep one decimal; None -> "?"."""
    if seconds is None:
        return "?"
    return str(int(seconds)) if float(seconds).is_integer() else f"{seconds:.1f}"


_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def _frozen_worker_candidates() -> list[Path]:
    """Possible worker exe locations relative to the frozen service exe.

    The installer lays out ``{app}\\service\\reportflow-service.exe`` and
    ``{app}\\worker\\reportflow-worker.exe`` as SIBLING folders, so the primary candidate
    is one level up from the service's own directory (``install_dir()`` is the exe's own
    folder when frozen — using it directly was the v0.3.0 field bug, WinError 2).
    """
    exe_dir = paths.install_dir()
    return [
        exe_dir.parent / "worker" / "reportflow-worker.exe",  # installer layout
        exe_dir / "worker" / "reportflow-worker.exe",  # flat/alternative layouts
        exe_dir / "reportflow-worker.exe",  # worker beside the service exe
    ]


def default_worker_command() -> list[str]:
    """The command to invoke the worker: the installed exe when frozen, else the module."""
    override = os.environ.get("REPORTFLOW_WORKER_CMD")
    if override:
        import json

        return json.loads(override)
    if getattr(sys, "frozen", False):
        candidates = _frozen_worker_candidates()
        for candidate in candidates:
            if candidate.exists():
                return [str(candidate)]
        tried = "; ".join(str(c) for c in candidates)
        raise FileNotFoundError(
            f"worker executable not found — tried: {tried}. Reinstall ReportFlow."
        )
    return [sys.executable, "-m", "reportflow.worker"]


DEFAULT_OUTPUT_STEM = "{job}_{date}"


def _substitute_tokens(text: str, *, job_name: str, run_id: str, now: datetime) -> str:
    """Expand {date}/{datetime}/{job}/{run_id} in an output name. {sheet} is left for the
    worker (one PDF per sheet)."""
    text = text.replace("{date}", now.strftime("%Y%m%d"))
    text = text.replace("{datetime}", now.strftime("%Y%m%d_%H%M%S"))
    text = text.replace("{job}", job_name)
    text = text.replace("{run_id}", run_id)
    return text


def resolve_output_paths(job: JobConfig, *, run_id: str, now: datetime) -> tuple[Path, Path | None]:
    """Derive the concrete output .xlsx path and the {sheet}-tokenized PDF pattern.

    Folder: ``job.output_dir``, or the input file's folder when unset. Filename stem:
    ``job.output_name`` (tokens expanded), or ``{job}_{date}``. PDFs always get a per-sheet
    suffix; the ``{sheet}`` token is resolved by the worker.
    """
    base = Path(job.output_dir) if job.output_dir else Path(job.input_excel_path).parent
    stem = _substitute_tokens(
        job.output_name or DEFAULT_OUTPUT_STEM, job_name=job.name, run_id=run_id, now=now
    )
    output_xlsx = base / f"{stem}.xlsx"
    output_pdf = base / f"{stem}_{{sheet}}.pdf" if job.generate_pdf else None
    return output_xlsx, output_pdf


class Launcher:
    def __init__(
        self,
        run_store: RunStore,
        get_config: Callable[[], AppConfig],
        *,
        worker_command: list[str] | None = None,
    ) -> None:
        self.run_store = run_store
        self.get_config = get_config
        self._worker_command = worker_command
        self._global_sem = threading.BoundedSemaphore(
            max(1, get_config().app.max_global_concurrency)
        )
        self._group_locks: dict[str, threading.Lock] = {}
        self._group_guard = threading.Lock()
        self._active: dict[str, subprocess.Popen] = {}
        self._active_guard = threading.Lock()

    # -- public ------------------------------------------------------------------

    def run_job_by_name(self, name: str, trigger: RunTrigger) -> RunRecord:
        """Synchronous run (blocks until the worker finishes). Used by tests and internally."""
        config = self.get_config()
        job = config.job(name)
        if job is None:
            raise KeyError(f"unknown job: {name}")
        return self.run(config, job, trigger)

    def submit_job_by_name(self, name: str, trigger: RunTrigger) -> str:
        """Non-blocking run: records the RUNNING row, starts a worker thread, returns run_id."""
        config = self.get_config()
        job = config.job(name)
        if job is None:
            raise KeyError(f"unknown job: {name}")
        request, record = self._prepare(config, job, trigger)
        thread = threading.Thread(
            target=self._run_prepared,
            args=(config, job, request, record),
            name=f"run-{record.run_id}",
            daemon=True,
        )
        thread.start()
        return record.run_id

    def active_run_ids(self) -> list[str]:
        with self._active_guard:
            return list(self._active)

    # -- internals ---------------------------------------------------------------

    def _group_lock(self, group: str | None) -> threading.Lock | None:
        if not group:
            return None
        with self._group_guard:
            return self._group_locks.setdefault(group, threading.Lock())

    def run(self, config: AppConfig, job: JobConfig, trigger: RunTrigger) -> RunRecord:
        request, record = self._prepare(config, job, trigger)
        self._run_prepared(config, job, request, record)
        return record

    @staticmethod
    def _resolve_is_test(job: JobConfig, trigger: RunTrigger) -> bool:
        """The job's lifecycle stage decides who a run emails, resolved at fire time.

        Testing-stage jobs email only the Test recipients on EVERY run (manual or
        scheduled) — promotion to live flips future runs to production without
        re-scheduling. Build-only (dry) runs stay test-flagged; they never email anyway.
        """
        if trigger in (RunTrigger.DRY_RUN, RunTrigger.TEST):
            return True
        return job.stage == "testing"

    def _prepare(
        self, config: AppConfig, job: JobConfig, trigger: RunTrigger
    ) -> tuple[WorkerRequest, RunRecord]:
        is_test = self._resolve_is_test(job, trigger)
        run_id = uuid.uuid4().hex[:12]
        now = datetime.now()
        run_dir = paths.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        request = self._build_request(config, job, run_id, run_dir, now, is_test=is_test)
        record = RunRecord(
            run_id=run_id,
            job_name=job.name,
            trigger=trigger,
            status=RunStatus.RUNNING,
            is_test=is_test,
            started_at=now.isoformat(timespec="seconds"),
            worker_log_path=str(request.log_path),
        )
        self.run_store.upsert(record)
        return request, record

    def _run_prepared(
        self, config: AppConfig, job: JobConfig, request: WorkerRequest, record: RunRecord
    ) -> None:
        group_lock = self._group_lock(job.concurrency_group)
        if group_lock is not None:
            group_lock.acquire()
        try:
            with self._global_sem:
                self._execute(config, job, request, record)
        except Exception as e:  # noqa: BLE001 — background thread must not die silently
            logger.exception("Run {} crashed in launcher: {}", request.run_id, e)
            record.status = RunStatus.CRASHED
            record.error_summary = f"launcher error: {e}"[:500]
            record.finished_at = datetime.now().isoformat(timespec="seconds")
            self.run_store.upsert(record)
        finally:
            if group_lock is not None:
                group_lock.release()

    def _build_request(
        self,
        config: AppConfig,
        job: JobConfig,
        run_id: str,
        run_dir: Path,
        now: datetime,
        *,
        is_test: bool,
    ) -> WorkerRequest:
        timeout = job.timeout_seconds or config.app.default_timeout_seconds
        out_xlsx, out_pdf = resolve_output_paths(job, run_id=run_id, now=now)
        return WorkerRequest(
            run_id=run_id,
            job_name=job.name,
            input_excel_path=job.input_excel_path,
            output_xlsx_path=out_xlsx,
            output_pdf_path=out_pdf,
            sheet_names=job.sheet_names,
            freeze_values=job.freeze_values,
            generate_pdf=job.generate_pdf,
            post_refresh_wait_seconds=job.post_refresh_wait_seconds,
            fail_if_sheet_empty=job.fail_if_sheet_empty,
            fail_if_sheet_has_errors=job.fail_if_sheet_has_errors,
            keep_only_selected_sheets=job.keep_only_selected_sheets,
            unselected_sheets_mode=job.unselected_sheets_mode,
            blank_out_values=job.blank_out_values,
            timeout_seconds=timeout,
            is_test=is_test,
            debug=config.app.debug_logging,
            result_path=run_dir / "result.json",
            log_path=run_dir / "worker.log",
        )

    def _execute(
        self, config: AppConfig, job: JobConfig, request: WorkerRequest, record: RunRecord
    ) -> None:
        req_path = write_request(request, request.result_path.parent / "request.json")
        stdio_path = request.result_path.parent / "worker_stdio.log"

        logger.info("Launching worker for run {} (job {!r})", request.run_id, job.name)
        try:
            command = self._worker_command or default_worker_command()
            with open(stdio_path, "wb") as stdio:
                proc = subprocess.Popen(
                    [*command, "--request", str(req_path)],
                    stdout=stdio,
                    stderr=subprocess.STDOUT,
                    creationflags=_CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP,
                )
        except FileNotFoundError as e:
            # The worker exe is missing/misplaced — record something actionable instead
            # of a bare WinError 2 (the v0.3.0 field failure).
            detail = (
                str(e)
                if "worker executable" in str(e)
                else (f"worker executable not found: {command[0]} — reinstall ReportFlow ({e})")
            )
            logger.error("Run {}: {}", request.run_id, detail)
            record.status = RunStatus.CRASHED
            record.error_summary = detail[:500]
            record.finished_at = datetime.now().isoformat(timespec="seconds")
            self.run_store.upsert(record)
            return
        with self._active_guard:
            self._active[request.run_id] = proc

        timed_out = False
        try:
            exit_code = proc.wait(timeout=request.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            logger.warning("Run {} timed out; killing worker tree", request.run_id)
            self._tree_kill(proc.pid)
            exit_code = proc.wait(timeout=30)
        finally:
            with self._active_guard:
                self._active.pop(request.run_id, None)

        self._finalize(config, job, request, record, exit_code, timed_out=timed_out)

    def _finalize(
        self,
        config: AppConfig,
        job: JobConfig,
        request: WorkerRequest,
        record: RunRecord,
        exit_code: int,
        *,
        timed_out: bool,
    ) -> None:
        record.exit_code = exit_code
        record.finished_at = datetime.now().isoformat(timespec="seconds")
        record.duration_seconds = _elapsed_seconds(record.started_at, record.finished_at)

        result = None
        if request.result_path.exists():
            try:
                result = read_result(request.result_path)
            except Exception as e:  # noqa: BLE001
                logger.error("Could not parse result for run {}: {}", request.run_id, e)

        if timed_out:
            record.status = RunStatus.TIMED_OUT
            record.error_summary = f"timed out after {request.timeout_seconds}s"
        elif result is None:
            record.status = RunStatus.CRASHED
            record.error_summary = "worker produced no result (crashed)"
        else:
            record.status = result.status if exit_code == 0 else RunStatus.FAILED
            record.output_xlsx = str(result.output_xlsx) if result.output_xlsx else None
            record.pdf_paths = [str(p) for p in result.pdf_paths]
            record.warnings = list(result.warnings)
            if result.duration_seconds is not None:
                # Prefer the worker's own measurement over the launcher-bracket fallback.
                record.duration_seconds = result.duration_seconds
            if not result.ok:
                record.error_summary = (result.message or "run failed").strip()[:500]

        self.run_store.upsert(record)
        logger.info("Run {} finished: status={} exit={}", request.run_id, record.status, exit_code)

        self._maybe_email(config, job, record, request)

    def _maybe_email(
        self, config: AppConfig, job: JobConfig, record: RunRecord, request: WorkerRequest
    ) -> None:
        """Send the report email when policy allows, and ALWAYS record why/why not.

        Every path writes ``record.email_note`` so the run history answers "did it
        email?" without digging through logs.
        """
        if record.trigger is RunTrigger.DRY_RUN:
            record.email_note = _DRY_RUN_NOTE
        elif record.status is not RunStatus.SUCCESS:
            record.email_note = "not sent — run did not succeed"
        else:
            attachments: list[Path] = []
            if record.output_xlsx:
                attachments.append(Path(record.output_xlsx))
            attachments.extend(Path(p) for p in record.pdf_paths)
            context = self._email_context(job, record)
            kind = (
                "test recipient(s) — job is in Testing"
                if request.is_test
                else "production recipient(s)"
            )
            try:
                recipients = send_report(config, job, context, attachments, is_test=request.is_test)
                record.email_sent = True
                record.email_note = f"sent to {len(recipients)} {kind}"
            except Exception as e:  # noqa: BLE001 — email failure must not fail the run
                record.email_note = f"failed: {e}"
                logger.error("Emailing report for run {} failed: {}", record.run_id, e)
        logger.info("Run {} email: {}", record.run_id, record.email_note)
        self.run_store.upsert(record)

    @staticmethod
    def _email_context(job: JobConfig, record: RunRecord) -> dict:
        return {
            "job_name": job.name,
            "subject": job.subject or f"{job.name} report",
            "status": str(record.status),
            "run_id": record.run_id,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "duration_seconds": _format_duration(record.duration_seconds),
            "sheet_names": job.sheet_names,
            "hostname": os.environ.get("COMPUTERNAME", "host"),
            "is_test": record.is_test,
            "warnings": list(record.warnings),
        }

    @staticmethod
    def _tree_kill(pid: int) -> None:
        try:
            import psutil

            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except psutil.Error:
                    pass
            parent.kill()
        except Exception as e:  # noqa: BLE001
            logger.error("tree kill of pid {} failed: {}", pid, e)
