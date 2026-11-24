"""Launch and supervise one disposable worker process per job run.

Responsibilities:
* Build the ``WorkerRequest`` (resolving output-path tokens and the timeout).
* Admit runs through ONE queue (0.16): a run starts when everything it needs is free at
  once — its input workbooks (two runs never open the same file together), its concurrency
  group, a global slot (``max_global_concurrency``, read live). First come, first served; a
  later run may start when nothing it needs is taken or reserved by an earlier one. Each
  waiting run knows why it waits. One run per job at a time (``JobBusyError``).
* Launch the worker with no console window and its own process group.
* Supervise it: Stop (``stop()``), the time limit and service shutdown kill the worker FIRST
  (killing Excel first makes the worker retry with a new Excel), then close the Excel
  processes the run recorded in ``progress.json`` — Excel is started by COM, so it is NOT a
  child of the worker, and the old tree-kill left it running with the file open.
* Read the worker's ``result.json`` (authoritative) + exit code and record the run.
* Send email per lifecycle policy: testing-stage jobs -> test recipients on every run;
  live jobs -> production recipients. Build-only runs never email. NEVER email on failure,
  a stop or an interruption. The run's queue resources are released before emailing.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from reportflow.core import paths
from reportflow.core.config.models import AppConfig, JobConfig, stage_label
from reportflow.core.email import send_report
from reportflow.core.email.render import date_context, render_subject
from reportflow.core.ipc import (
    RunStatus,
    SheetTask,
    WorkbookTask,
    WorkerProgress,
    WorkerRequest,
    progress_path,
    read_progress,
    read_result,
    write_request,
)
from reportflow.core.output_names import DEFAULT_OUTPUT_STEM, expand_output_name
from reportflow.core.procs import kill_verified
from reportflow.core.state import RunRecord, RunStore, RunTrigger
from reportflow.worker.private_copy import remove_run_copies

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


def _format_limit(seconds: int) -> str:
    """900 -> "15 min", 90 -> "90s" — time limits are set in minutes in the UI."""
    return f"{seconds // 60} min" if seconds % 60 == 0 else f"{seconds}s"


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


def resolve_output_paths(
    job: JobConfig, *, run_id: str, now: datetime
) -> list[tuple[Path, Path | None]]:
    """Per workbook: the concrete output .xlsx path and the {sheet}-tokenized PDF pattern.

    Folder: ``job.output_dir``, or each input file's own folder when unset. Filename stem:
    ``job.output_name`` (tokens expanded), or the default. With several workbooks the stem
    must tell them apart, so ``_{workbook}`` (the input file's name) is appended when the
    pattern lacks it. PDFs always get a per-sheet suffix, resolved by the worker; the PDF
    pattern is None when no sheet of that workbook wants a PDF.
    """
    pattern = job.output_name or DEFAULT_OUTPUT_STEM
    if len(job.workbooks) > 1 and "{workbook}" not in pattern:
        pattern += "_{workbook}"
    taken: set[str] = set()
    resolved: list[tuple[Path, Path | None]] = []
    for wb in job.workbooks:
        source = Path(wb.input_excel_path)
        base = Path(job.output_dir) if job.output_dir else source.parent
        stem = expand_output_name(
            pattern, job_name=job.name, run_id=run_id, now=now, workbook=source.stem
        )
        # Two inputs with the same file name (from different folders) must not overwrite
        # each other's output.
        unique, n = stem, 2
        while any(str(base / name).casefold() in taken for name in (unique, unique + "_email")):
            unique, n = f"{stem}_{n}", n + 1
        taken.update(str(base / name).casefold() for name in (unique, unique + "_email"))
        output_pdf = base / f"{unique}_{{sheet}}.pdf" if any(s.pdf for s in wb.sheets) else None
        resolved.append((base / f"{unique}.xlsx", output_pdf))
    return resolved


class JobBusyError(RuntimeError):
    """The job already has a run waiting or running — one run per job at a time."""

    def __init__(self, job: str, run_id: str, phase: str) -> None:
        state = "waiting to start" if phase == "queued" else "running"
        super().__init__(f"'{job}' is already {state} (run {run_id}) — stop it or wait for it")
        self.job, self.run_id, self.phase = job, run_id, phase


class StopRefusedError(RuntimeError):
    """The run is past the point where Stop means anything (finishing, or timing out)."""


class ServiceClosingError(RuntimeError):
    """The service is shutting down: no new runs."""


_POLL_SECONDS = 0.5
_WAIT_SECONDS = 5.0  # a waiting run re-checks the queue at least this often


def _file_key(path: str | Path) -> str:
    """One workbook, however its path is spelled (case, ``..``, forward slashes)."""
    return os.path.normcase(os.path.abspath(str(path)))


def _clock(moment: datetime | None) -> str:
    return (moment or datetime.now()).strftime("%H:%M:%S")


@dataclass(eq=False)
class _Slot:
    """One run from submit until it is recorded. Guarded by ``Launcher._cv``."""

    run_id: str
    job_key: str
    job_name: str
    trigger: RunTrigger
    files: frozenset[str] = frozenset()
    file_names: dict[str, str] = field(default_factory=dict)  # key -> file name for messages
    group: str | None = None
    phase: str = "queued"  # queued | starting | running | stopping | finishing
    admitted: bool = False
    waiting_for: str | None = None
    stop_by: str | None = None
    stop_at: datetime | None = None
    kill_reason: str | None = None  # stop | timeout | shutdown — the first one wins
    proc: subprocess.Popen | None = None
    progress: WorkerProgress | None = None
    worker_started_at: datetime | None = None


class Launcher:
    # Executables a run's recorded processes may be — nothing else is ever killed.
    _EXCEL_IMAGES: frozenset[str] = frozenset({"excel.exe"})
    _WORKER_IMAGES: frozenset[str] = frozenset(
        {"reportflow-worker.exe", "python.exe", "pythonw.exe"}
    )

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
        self._cv = threading.Condition()
        self._slots: dict[str, _Slot] = {}
        self._by_job: dict[str, str] = {}  # job name (casefolded) -> run_id
        self._queue: list[_Slot] = []  # waiting runs, first come first served
        self._admitted: list[_Slot] = []
        self._closing = False
        self._threads: dict[str, threading.Thread] = {}

    # -- public ------------------------------------------------------------------
    def run_job_by_name(self, name: str, trigger: RunTrigger) -> RunRecord:
        """Synchronous run (blocks until the worker finishes). Used by tests and internally."""
        config = self.get_config()
        job = config.job(name)
        if job is None:
            raise KeyError(f"unknown job: {name}")
        return self.run(config, job, trigger)

    def submit_job_by_name(self, name: str, trigger: RunTrigger) -> str:
        """Non-blocking run: records the RUNNING row, starts a run thread, returns run_id.
        Raises ``JobBusyError`` when the job already has a run waiting or running."""
        config = self.get_config()
        job = config.job(name)
        if job is None:
            raise KeyError(f"unknown job: {name}")
        slot, request, record = self._prepare(config, job, trigger)
        thread = threading.Thread(
            target=self._run_slot,
            args=(slot, config, job, request, record),
            name=f"run-{record.run_id}",
            daemon=True,
        )
        with self._cv:
            self._threads[record.run_id] = thread
        thread.start()
        return record.run_id

    def run(self, config: AppConfig, job: JobConfig, trigger: RunTrigger) -> RunRecord:
        slot, request, record = self._prepare(config, job, trigger)
        self._run_slot(slot, config, job, request, record)
        return record

    def active_run_ids(self) -> list[str]:
        """Runs whose worker is running (or being stopped)."""
        with self._cv:
            return [s.run_id for s in self._slots.values() if s.proc is not None]

    def inflight_run_ids(self) -> list[str]:
        """Every run from submit until it is recorded — waiting ones included."""
        with self._cv:
            return list(self._slots)

    def queued_run_ids(self) -> list[str]:
        with self._cv:
            return [s.run_id for s in self._queue]

    def inflight_job_names(self) -> set[str]:
        """Jobs with a run queued or running (e.g. a rename must wait for them)."""
        with self._cv:
            return {s.job_name for s in self._slots.values()}

    def live(self, run_id: str) -> dict[str, Any] | None:
        """What an in-flight run is doing — for the dashboard and the run history."""
        with self._cv:
            slot = self._slots.get(run_id)
            return self._live_locked(slot) if slot is not None else None

    def live_for_job(self, name: str) -> dict[str, Any] | None:
        with self._cv:
            run_id = self._by_job.get(name.casefold())
            slot = self._slots.get(run_id) if run_id else None
            return self._live_locked(slot) if slot is not None else None

    def stop(self, run_id: str, by: str) -> str:
        """Ask an in-flight run to stop; returns its phase. ``KeyError``: not in flight;
        ``StopRefusedError``: it is finishing, or already timing out / shutting down."""
        with self._cv:
            slot = self._slots.get(run_id)
            if slot is None:
                raise KeyError(run_id)
            if slot.phase == "finishing":
                raise StopRefusedError("it is already finishing — it can no longer be stopped")
            if slot.kill_reason in ("timeout", "shutdown"):
                raise StopRefusedError(f"it is already being ended ({slot.kill_reason})")
            if slot.stop_by is None:
                slot.stop_by = by or "someone"
                slot.stop_at = datetime.now()
                logger.info("Run {} ({!r}): stop requested by {}", run_id, slot.job_name, by)
            self._cv.notify_all()
            return slot.phase

    def shutdown(self, grace: float = 8.0) -> None:
        """The service is stopping: no new runs; waiting runs leave the queue and running
        ones are killed (and recorded as interrupted) within one poll."""
        with self._cv:
            self._closing = True
            self._cv.notify_all()
            threads = list(self._threads.values())
        deadline = time.monotonic() + grace
        for thread in threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))

    def recover_interrupted(self) -> int:
        """At start-up: a "running" row that no run of this service owns was cut off by a
        stop, a restart or a crash. Close what it left behind (its worker, its Excel —
        verified, see ``core/procs.py``) and record it as interrupted, with its last step.
        Returns how many runs were recovered."""
        with self._cv:
            owned = set(self._slots)
        recovered = 0
        for record in self.run_store.list_by_status(RunStatus.RUNNING):
            if record.run_id in owned:
                continue
            run_dir = (
                Path(record.worker_log_path).parent
                if record.worker_log_path
                else paths.run_dir(record.run_id)
            )
            progress = read_progress(run_dir / "progress.json")
            if progress is not None:
                if progress.worker is not None:
                    kill_verified(progress.worker, images=self._WORKER_IMAGES)
                for ref in progress.excels:
                    kill_verified(ref, images=self._EXCEL_IMAGES)
            remove_run_copies(run_dir)
            result = None
            if (run_dir / "result.json").exists():
                try:
                    result = read_result(run_dir / "result.json")
                except Exception:  # noqa: BLE001 — a half-written file: treat as none
                    result = None
            step = progress.step if progress else None
            record.status = RunStatus.INTERRUPTED
            record.finished_at = record.finished_at or datetime.now().isoformat(timespec="seconds")
            record.email_note = "not sent — interrupted"
            if result is not None and result.ok:
                record.output_xlsx_paths = [str(p) for p in result.output_xlsx_paths]
                record.output_xlsx = (
                    record.output_xlsx_paths[0] if record.output_xlsx_paths else None
                )
                record.pdf_paths = [str(p) for p in result.pdf_paths]
                record.error_summary = (
                    "Interrupted — the ReportFlow service stopped or restarted after this "
                    "report was built but before it was emailed. Run it again to send it."
                )
            else:
                at = f" while this run was at: {step}" if step else " while this run was waiting"
                record.error_summary = (
                    f"Interrupted — the ReportFlow service stopped or restarted{at}. Nothing "
                    "was emailed; run it again."
                )
            self.run_store.upsert(record)
            recovered += 1
            logger.warning(
                "Run {} ({!r}) was cut off by a service stop/restart — recorded as interrupted",
                record.run_id,
                record.job_name,
            )
        return recovered

    # -- the queue ------------------------------------------------------------------
    @staticmethod
    def _live_locked(slot: _Slot) -> dict[str, Any]:
        progress = slot.progress
        started = slot.worker_started_at
        return {
            "run_id": slot.run_id,
            "phase": slot.phase,
            "waiting_for": slot.waiting_for,
            "step": progress.step if progress else None,
            "step_since": progress.since if progress else None,
            "workbook": progress.workbook if progress else None,
            "worker_started_at": started.isoformat(timespec="seconds") if started else None,
            "stop_requested_by": slot.stop_by,
            "trigger": str(slot.trigger),
        }

    def _dispatch_locked(self) -> None:
        """Admit every waiting run whose resources are all free (see the module docstring)."""
        cap = max(1, self.get_config().app.max_global_concurrency)
        held_files: dict[str, _Slot] = {}
        held_groups: dict[str, _Slot] = {}
        for slot in self._admitted:
            held_files.update(dict.fromkeys(slot.files, slot))
            if slot.group:
                held_groups[slot.group] = slot
        reserved_files: dict[str, _Slot] = {}
        reserved_groups: dict[str, _Slot] = {}
        for slot in list(self._queue):
            reason = None
            for key in sorted(slot.files):
                other = held_files.get(key) or reserved_files.get(key)
                if other is not None:
                    name = slot.file_names.get(key, "")
                    reason = f"same workbook as '{other.job_name}' ({name})"
                    break
            if reason is None and slot.group:
                other = held_groups.get(slot.group) or reserved_groups.get(slot.group)
                if other is not None:
                    reason = f"concurrency group '{slot.group}' is used by '{other.job_name}'"
            if reason is None and len(self._admitted) >= cap:
                reason = f"all {cap} run slot(s) are busy"
            if reason is not None:
                slot.waiting_for = reason
                reserved_files.update(dict.fromkeys(slot.files, slot))
                if slot.group:
                    reserved_groups.setdefault(slot.group, slot)
                continue
            slot.admitted, slot.waiting_for = True, None
            self._queue.remove(slot)
            self._admitted.append(slot)
            held_files.update(dict.fromkeys(slot.files, slot))
            if slot.group:
                held_groups[slot.group] = slot
        self._cv.notify_all()

    def _wait_admitted(self, slot: _Slot) -> bool:
        """Block until the run is admitted (True), or it is stopped / the service closes
        while it waits (False — it never started)."""
        with self._cv:
            self._queue.append(slot)
            self._dispatch_locked()
            while not slot.admitted:
                if slot.stop_by is not None or self._closing:
                    if slot in self._queue:
                        self._queue.remove(slot)
                    self._dispatch_locked()
                    return False
                self._cv.wait(timeout=_WAIT_SECONDS)
                if not slot.admitted:
                    self._dispatch_locked()  # the cap is read live
            slot.phase = "starting"
            return True

    def _release_admission(self, slot: _Slot) -> None:
        with self._cv:
            if slot in self._admitted:
                self._admitted.remove(slot)
            if slot in self._queue:
                self._queue.remove(slot)
            self._dispatch_locked()

    def _forget(self, slot: _Slot) -> None:
        with self._cv:
            self._slots.pop(slot.run_id, None)
            if self._by_job.get(slot.job_key) == slot.run_id:
                self._by_job.pop(slot.job_key, None)
            self._threads.pop(slot.run_id, None)
            if slot in self._admitted:
                self._admitted.remove(slot)
            if slot in self._queue:
                self._queue.remove(slot)
            self._dispatch_locked()

    # -- internals ---------------------------------------------------------------
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
    ) -> tuple[_Slot, WorkerRequest, RunRecord]:
        run_id = uuid.uuid4().hex[:12]
        slot = _Slot(run_id=run_id, job_key=job.name.casefold(), job_name=job.name, trigger=trigger)
        with self._cv:
            if self._closing:
                raise ServiceClosingError("the ReportFlow service is stopping")
            busy = self._by_job.get(slot.job_key)
            if busy is not None:
                raise JobBusyError(job.name, busy, self._slots[busy].phase)
            self._slots[run_id] = slot
            self._by_job[slot.job_key] = run_id
        try:
            is_test = self._resolve_is_test(job, trigger)
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
        except BaseException:
            self._forget(slot)
            raise
        return slot, request, record

    def _run_slot(
        self,
        slot: _Slot,
        config: AppConfig,
        job: JobConfig,
        request: WorkerRequest,
        record: RunRecord,
    ) -> None:
        try:
            # Computed here, not in _prepare (the API thread): a path on an unreachable
            # share can take a long time to resolve.
            names = {
                _file_key(wb.input_excel_path): Path(wb.input_excel_path).name
                for wb in job.workbooks
            }
            with self._cv:
                slot.files = frozenset(names)
                slot.file_names = names
                slot.group = (job.concurrency_group or "").strip().casefold() or None
            if not self._wait_admitted(slot):
                self._record_not_started(slot, record)
                return
            self._execute(config, job, request, record, slot)
        except Exception as e:  # noqa: BLE001 — background thread must not die silently
            logger.exception("Run {} crashed in launcher: {}", request.run_id, e)
            record.status = RunStatus.CRASHED
            record.error_summary = f"launcher error: {e}"[:500]
            record.finished_at = datetime.now().isoformat(timespec="seconds")
            self.run_store.upsert(record)
        finally:
            self._forget(slot)

    def _record_not_started(self, slot: _Slot, record: RunRecord) -> None:
        """A run stopped (or interrupted by a shutdown) while it was still waiting."""
        record.finished_at = datetime.now().isoformat(timespec="seconds")
        record.duration_seconds = _elapsed_seconds(record.started_at, record.finished_at)
        if slot.stop_by is not None:
            record.status = RunStatus.STOPPED
            record.error_summary = (
                f"Stopped by {slot.stop_by} at {_clock(slot.stop_at)} before it started"
            )
            record.email_note = "not sent — stopped"
        else:
            record.status = RunStatus.INTERRUPTED
            record.error_summary = (
                "Interrupted — the ReportFlow service was stopping before this run started. "
                "Nothing was emailed; run it again."
            )
            record.email_note = "not sent — interrupted"
        self.run_store.upsert(record)
        logger.info("Run {} {} before it started", record.run_id, record.status)

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
        outputs = resolve_output_paths(job, run_id=run_id, now=now)
        workbooks = [
            WorkbookTask(
                input_excel_path=wb.input_excel_path,
                output_xlsx_path=out_xlsx,
                output_pdf_path=out_pdf,
                sheets=[
                    SheetTask(name=s.name, excel=s.excel, pdf=s.pdf, hidden=s.hidden)
                    for s in wb.sheets
                ],
                pdf_mode=wb.pdf_mode,
                unselected_sheets=wb.unselected_sheets,
            )
            for wb, (out_xlsx, out_pdf) in zip(job.workbooks, outputs, strict=True)
        ]
        return WorkerRequest(
            run_id=run_id,
            job_name=job.name,
            workbooks=workbooks,
            continue_on_workbook_failure=job.on_workbook_failure == "send_partial",
            freeze_values=job.freeze_values,
            post_refresh_wait_seconds=job.post_refresh_wait_seconds,
            fail_if_sheet_empty=job.fail_if_sheet_empty,
            fail_if_sheet_has_errors=job.fail_if_sheet_has_errors,
            require_pi_datalink=job.require_pi_datalink,
            blank_out_values=job.blank_out_values,
            private_copy=job.private_copy,
            timeout_seconds=timeout,
            is_test=is_test,
            debug=config.app.debug_logging,
            result_path=run_dir / "result.json",
            log_path=run_dir / "worker.log",
        )

    def _execute(
        self,
        config: AppConfig,
        job: JobConfig,
        request: WorkerRequest,
        record: RunRecord,
        slot: _Slot,
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
        with self._cv:
            slot.proc = proc
            slot.phase = "running"
            slot.worker_started_at = datetime.now()
        exit_code, reason = self._supervise(slot, proc, request)
        if reason is not None:
            logger.warning("Run {}: {} — ending the worker, then its Excel", request.run_id, reason)
            exit_code = self._kill_worker(proc)
        # Close every Excel the run recorded (after the worker is gone, so it can't start a
        # new one) — also after a normal exit: a hung Excel would keep the file open.
        slot.progress = read_progress(progress_path(request.result_path)) or slot.progress
        self._close_excels(slot)
        remove_run_copies(request.result_path.parent)
        with self._cv:
            if reason is None and slot.stop_by is not None:
                reason = "stop"  # Stop raced the worker's normal exit: still not emailed
            slot.phase = "finishing"
        self._release_admission(slot)  # free the queue before emailing (SMTP can be slow)
        self._finalize(config, job, request, record, exit_code, reason=reason, slot=slot)

    def _supervise(
        self, slot: _Slot, proc: subprocess.Popen, request: WorkerRequest
    ) -> tuple[int | None, str | None]:
        """Wait for the worker. Returns (exit code, reason it must be killed or None)."""
        deadline = time.monotonic() + request.timeout_seconds
        progress_file = progress_path(request.result_path)
        while True:
            try:
                return proc.wait(timeout=_POLL_SECONDS), None
            except subprocess.TimeoutExpired:
                pass
            progress = read_progress(progress_file)
            with self._cv:
                if progress is not None:
                    slot.progress = progress
                reason = None
                if slot.stop_by is not None:
                    reason = "stop"
                elif self._closing:
                    reason = "shutdown"
                elif time.monotonic() >= deadline:
                    reason = "timeout"
                if reason is not None:
                    slot.kill_reason = reason
                    slot.phase = "stopping"
                    return None, reason

    @staticmethod
    def _kill_worker(proc: subprocess.Popen) -> int | None:
        """Kill the worker through its own handle (never a reused PID), then any children."""
        try:
            import psutil

            children = psutil.Process(proc.pid).children(recursive=True)
        except Exception:  # noqa: BLE001 — already gone
            children = []
        try:
            proc.kill()
        except OSError as e:
            logger.debug("worker kill failed: {}", e)
        for child in children:
            try:
                child.kill()
            except Exception:  # noqa: BLE001
                pass
        try:
            return proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            logger.error("worker pid {} did not exit after kill", proc.pid)
            return None

    def _close_excels(self, slot: _Slot) -> None:
        progress = slot.progress
        for ref in progress.excels if progress else []:
            kill_verified(ref, images=self._EXCEL_IMAGES)

    def _finalize(
        self,
        config: AppConfig,
        job: JobConfig,
        request: WorkerRequest,
        record: RunRecord,
        exit_code: int | None,
        *,
        reason: str | None,
        slot: _Slot,
    ) -> None:
        record.exit_code = exit_code
        record.finished_at = datetime.now().isoformat(timespec="seconds")
        record.duration_seconds = _elapsed_seconds(record.started_at, record.finished_at)
        step = slot.progress.step if slot.progress else None
        while_doing = f" while: {step}" if step else ""
        result = None
        if request.result_path.exists():
            try:
                result = read_result(request.result_path)
            except Exception as e:  # noqa: BLE001
                logger.error("Could not parse result for run {}: {}", request.run_id, e)
        if reason == "stop":
            record.status = RunStatus.STOPPED
            built = " — the report was built but not emailed" if result and result.ok else ""
            record.error_summary = (
                f"Stopped by {slot.stop_by} at {_clock(slot.stop_at)}{while_doing}{built}"
            )
            record.email_note = "not sent — stopped"
        elif reason == "shutdown":
            record.status = RunStatus.INTERRUPTED
            record.error_summary = (
                f"Interrupted — the ReportFlow service was stopping{while_doing}. Nothing "
                "was emailed; run it again."
            )
            record.email_note = "not sent — interrupted"
        elif reason == "timeout":
            record.status = RunStatus.TIMED_OUT
            # Say what to do: the usual cause is simply a big report (lots of PI data).
            last = f" Last step: {step}." if step else ""
            record.error_summary = (
                f"timed out after {_format_limit(request.timeout_seconds)} (the job's time "
                f"limit).{last} If the report is just large, raise Time limit in Edit → "
                "Advanced."
            )
        elif result is None:
            record.status = RunStatus.CRASHED
            record.error_summary = "worker produced no result (crashed)"
        else:
            record.status = result.status if exit_code == 0 else RunStatus.FAILED
            record.output_xlsx_paths = [str(p) for p in result.output_xlsx_paths]
            record.output_xlsx = record.output_xlsx_paths[0] if record.output_xlsx_paths else None
            record.pdf_paths = [str(p) for p in result.pdf_paths]
            record.attachment_paths = [str(p) for p in result.attachment_paths]
            record.warnings = list(result.warnings)
            if result.duration_seconds is not None:
                # Prefer the worker's own measurement over the launcher-bracket fallback.
                record.duration_seconds = result.duration_seconds
            if not result.ok:
                record.error_summary = (result.message or "run failed").strip()[:500]
        self.run_store.upsert(record)
        logger.info("Run {} finished: status={} exit={}", request.run_id, record.status, exit_code)
        if record.status in (RunStatus.STOPPED, RunStatus.INTERRUPTED):
            logger.info("Run {} email: {}", record.run_id, record.email_note)
            return
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
        elif not record.attachment_paths:
            record.email_note = "not sent — no attachments selected"
        else:
            template = job.email_template_path
            if template is not None and not Path(template).exists():
                # A linked template file that moved/vanished: send with the default rather
                # than not at all — but say so on the run instead of failing silently.
                note = f"email template not found: {template} — sent with the default template"
                logger.warning("Run {}: {}", record.run_id, note)
                record.warnings.append(note)
            attachments = [Path(p) for p in record.attachment_paths or []]
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
        """Every documented placeholder (see ``core.email.render.PLACEHOLDERS``)."""
        try:
            started = datetime.fromisoformat(record.started_at or "")
        except ValueError:
            started = datetime.now()
        attachments = [Path(p).name for p in record.attachment_paths or []]
        context = {
            "job_name": job.name,
            "status": str(record.status),
            "stage": stage_label(job.stage),
            "run_id": record.run_id,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
            "duration_seconds": _format_duration(record.duration_seconds),
            "sheet_names": job.sheet_names,
            "sheet_count": len(job.sheet_names),
            "workbooks": [Path(wb.input_excel_path).name for wb in job.workbooks],
            "attachments": attachments,
            "attachment_count": len(attachments),
            "hostname": os.environ.get("COMPUTERNAME", "host"),
            "is_test": record.is_test,
            "warnings": list(record.warnings),
            "warning_count": len(record.warnings),
            **date_context(started),
        }
        context["subject"] = render_subject(job.subject or f"{job.name} report", context)
        return context
