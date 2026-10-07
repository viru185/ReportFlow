"""A fake worker for launcher tests — no Excel. Behavior via REPORTFLOW_FAKE_MODE.

Modes: success | fail | crash | hang. Writes a real result.json using the shared IPC contract
so the launcher exercises its true parsing path.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from reportflow.core.ipc import RunStatus, WorkerResult, read_request, write_result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    mode = os.environ.get("REPORTFLOW_FAKE_MODE", "success")

    request = read_request(Path(args.request))

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
    for task in request.workbooks:
        task.output_xlsx_path.parent.mkdir(parents=True, exist_ok=True)
        task.output_xlsx_path.write_bytes(b"PK\x03\x04fake-xlsx")
        outputs.append(task.output_xlsx_path)
        if task.output_pdf_path is None:
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
            warnings=warnings if mode == "warn" else [],
            excel_pid_reaped=True,
        ),
        request.result_path,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
