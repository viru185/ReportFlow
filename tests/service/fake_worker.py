"""A fake worker for launcher tests — no Excel. Behavior via REPORTFLOW_FAKE_MODE, or
REPORTFLOW_FAKE_MODE_<JOB NAME> for one job (several jobs in one test).

Modes: success | warn | fail | crash | hang | slow | hang_excel. Writes a real result.json
using the shared IPC contract so the launcher exercises its true parsing path.

- ``slow``: writes "start/end <job> <monotonic>" to ``<REPORTFLOW_FAKE_LOG>/<job>.log``
  around a REPORTFLOW_FAKE_SLEEP-second sleep, then succeeds (who ran at the same time as
  whom). One file per job: two processes appending to one file on Windows can overwrite
  each other's line.
- ``hang_excel``: starts a stand-in "Excel" that is NOT its child (a helper starts it and
  exits — like COM's), records it in progress.json with the step "Freezing values on
  'Problem Points'", then hangs. The launcher must close that process on Stop / a timeout.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from reportflow.core.ipc import (
    ProcessRef,
    RunStatus,
    WorkerProgress,
    WorkerResult,
    progress_path,
    read_request,
    write_progress,
    write_result,
)
from reportflow.core.procs import process_ref

_SLEEPER = "import time; time.sleep(60)"


def _detached_sleeper(pid_file: Path) -> ProcessRef:
    """Start a sleeper whose parent exits at once, so it is not our child (like Excel).

    The REAL interpreter (not the venv's launcher, which would start a second process) and
    CREATE_NO_WINDOW: a sleeper with no console of its own made Windows pop up an empty
    terminal window for it (seen on the owner's desktop, 2026-11-24)."""
    real = getattr(sys, "_base_executable", sys.executable)
    launcher = (
        "import subprocess; "
        f"p = subprocess.Popen([{real!r}, '-c', {_SLEEPER!r}], "
        "creationflags=0x08000000 | 0x00000200); "  # CREATE_NO_WINDOW | NEW_PROCESS_GROUP
        f"open({str(pid_file)!r}, 'w').write(str(p.pid))"
    )
    subprocess.run([sys.executable, "-c", launcher], check=True, creationflags=0x08000000)
    ref = process_ref(int(pid_file.read_text()))
    assert ref is not None
    return ref


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    request = read_request(Path(args.request))
    key = "REPORTFLOW_FAKE_MODE_" + request.job_name.upper().replace(" ", "_")
    mode = os.environ.get(key) or os.environ.get("REPORTFLOW_FAKE_MODE", "success")

    if mode == "hang_excel":
        run_dir = request.result_path.parent
        excel = _detached_sleeper(run_dir / "fake_excel.pid")
        write_progress(
            WorkerProgress(
                run_id=request.run_id,
                step="Freezing values on 'Problem Points'",
                since=datetime.now().isoformat(timespec="seconds"),
                workbook="PI_Point_Health.xlsm",
                worker=process_ref(),
                excels=[excel],
            ),
            progress_path(request.result_path),
        )
        time.sleep(120)
        return 0
    if mode == "slow":
        log = Path(os.environ["REPORTFLOW_FAKE_LOG"]) / f"{request.job_name}.log"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"start {request.job_name} {time.monotonic()}\n")
        time.sleep(float(os.environ.get("REPORTFLOW_FAKE_SLEEP", "1.5")))
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"end {request.job_name} {time.monotonic()}\n")

    if mode == "crash":
        return 3  # exit nonzero WITHOUT writing a result
    if mode == "hang":
        time.sleep(60)  # exceed the test timeout; launcher should kill us
        return 0

    if mode == "fail":
        write_result(
            WorkerResult(run_id=request.run_id, status=RunStatus.FAILED, message="boom"),
            request.result_path,
        )
        return 1

    # success: create the output artifacts (one per workbook) and report them
    outputs = []
    pdfs = []
    attachments = []
    for task in request.workbooks:
        task.output_xlsx_path.parent.mkdir(parents=True, exist_ok=True)
        task.output_xlsx_path.write_bytes(b"PK\x03\x04fake-xlsx")
        outputs.append(task.output_xlsx_path)
        if any(s.excel for s in task.sheets):
            email_xlsx = task.output_xlsx_path.with_name(f"{task.output_xlsx_path.stem}_email.xlsx")
            email_xlsx.write_bytes(b"PK\x03\x04fake-xlsx")
            attachments.append(email_xlsx)
        if task.output_pdf_path is None:
            continue
        if task.pdf_mode == "combined" and any(s.pdf for s in task.sheets):
            p = task.output_xlsx_path.with_suffix(".pdf")
            p.write_bytes(b"%PDF-1.4 fake")
            pdfs.append(p)
            continue
        for sheet in task.sheets:
            if not sheet.pdf:
                continue
            p = Path(str(task.output_pdf_path).replace("{sheet}", sheet.name))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"%PDF-1.4 fake")
            pdfs.append(p)
    warnings = ["sheet 'Detailed report': 12 error cell(s) (#REF!) — delivered anyway"]
    write_result(
        WorkerResult(
            run_id=request.run_id,
            status=RunStatus.SUCCESS,
            message="completed with 1 warning(s)" if mode == "warn" else "completed",
            output_xlsx_paths=outputs,
            pdf_paths=pdfs,
            attachment_paths=[*attachments, *pdfs],
            warnings=warnings if mode == "warn" else [],
            excel_pid_reaped=True,
        ),
        request.result_path,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
