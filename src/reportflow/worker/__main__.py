"""Excel Worker entry point.

Usage::

    reportflow-worker --request <path-to-request.json>

Exit codes: 0 = success, 1 = run failed (result.json written), 2 = could not even read the
request (no result.json). The result file — not stdout — is the authoritative channel.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

from reportflow.core.ipc import RunStatus, read_request
from reportflow.core.logging_setup import configure_logging
from reportflow.worker.runner import run_job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reportflow-worker")
    parser.add_argument("--request", required=True, help="Path to the request.json file")
    args = parser.parse_args(argv)

    configure_logging("worker")

    request_path = Path(args.request)
    try:
        request = read_request(request_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not read request {}: {}", request_path, exc)
        return 2

    result = run_job(request)
    return 0 if result.status == RunStatus.SUCCESS else 1


if __name__ == "__main__":
    sys.exit(main())
