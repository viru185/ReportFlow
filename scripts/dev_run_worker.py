"""Drive the Excel worker against a workbook for local end-to-end verification.

Examples::

    uv run python scripts/make_sample.py
    uv run python scripts/dev_run_worker.py
    uv run python scripts/dev_run_worker.py --subprocess
    uv run python scripts/dev_run_worker.py --sheets Summary Detail --runs 3

Prints the structured result and asserts the output artifacts exist. Also reports any
net-new EXCEL.EXE processes so ghosts are caught immediately.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = REPO / "scripts" / "sample" / "template.xlsx"
WORK = REPO / "scripts" / "sample" / "output"


def _excel_pids() -> set[int]:
    import psutil

    pids = set()
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() == "excel.exe":
                pids.add(p.pid)
        except psutil.Error:
            pass
    return pids


def _build_request(template: Path, sheets: list[str], run_id: str, *, freeze: bool, pdf: bool):
    from reportflow.core import paths
    from reportflow.core.ipc import WorkerRequest

    run_dir = paths.run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    return WorkerRequest(
        run_id=run_id,
        job_name="dev_sample",
        input_excel_path=template,
        output_xlsx_path=WORK / f"{run_id}.xlsx",
        output_pdf_path=WORK / f"{run_id}_{{sheet}}.pdf",
        sheet_names=sheets,
        freeze_values=freeze,
        generate_pdf=pdf,
        timeout_seconds=300,
        is_test=True,
        result_path=run_dir / "result.json",
        log_path=run_dir / "worker.log",
    )


def _run_inprocess(request) -> int:
    from reportflow.core.ipc import RunStatus
    from reportflow.core.logging_setup import configure_logging
    from reportflow.worker.runner import run_job

    configure_logging("worker")
    result = run_job(request)
    return 0 if result.status == RunStatus.SUCCESS else 1


def _run_subprocess(request) -> int:
    from reportflow.core.ipc import write_request

    req_path = write_request(request, request.result_path.parent / "request.json")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [sys.executable, "-m", "reportflow.worker", "--request", str(req_path)],
        creationflags=creationflags,
    )
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--sheets", nargs="+", default=["Summary", "Detail"])
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--subprocess", action="store_true", help="Run via the worker exe/module")
    parser.add_argument("--no-freeze", action="store_true")
    parser.add_argument("--no-pdf", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=REPO / "scripts" / "sample" / "_data")
    args = parser.parse_args(argv)

    os.environ["REPORTFLOW_DATA_DIR"] = str(args.data_dir)
    from reportflow.core import paths
    from reportflow.core.ipc import read_result

    paths.data_root.cache_clear()
    paths.ensure_dirs()
    WORK.mkdir(parents=True, exist_ok=True)

    before = _excel_pids()
    overall = 0
    for _ in range(args.runs):
        run_id = uuid.uuid4().hex[:12]
        request = _build_request(
            args.template, args.sheets, run_id, freeze=not args.no_freeze, pdf=not args.no_pdf
        )
        code = _run_subprocess(request) if args.subprocess else _run_inprocess(request)
        result = read_result(request.result_path)
        print(f"\n=== run {run_id} (exit {code}) ===")
        print(result.model_dump_json(indent=2))
        if result.ok:
            assert Path(result.output_xlsx).exists(), "output xlsx missing"
            for pdf in result.pdf_paths:
                assert Path(pdf).exists() and Path(pdf).stat().st_size > 0, f"bad pdf {pdf}"
        overall |= code

    after = _excel_pids()
    leaked = after - before
    print(f"\nEXCEL.EXE before={len(before)} after={len(after)} leaked={sorted(leaked)}")
    if leaked:
        print("!! GHOST EXCEL DETECTED")
        overall |= 1
    return overall


if __name__ == "__main__":
    sys.exit(main())
