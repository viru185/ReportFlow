"""Windows Service entry point: host the local API + scheduler.

Registered as a Windows service via NSSM (a plain console process). Binds to localhost only.
"""

from __future__ import annotations

import argparse
import sys
from typing import IO

import uvicorn
from loguru import logger

from reportflow.core import paths
from reportflow.core.logging_setup import configure_logging
from reportflow.service.api import ServiceState, create_app

_instance_lock: IO[str] | None = None  # held for the life of the process


def take_instance_lock() -> bool:
    """Only one service may own the data folder: a second copy would also recover (and
    kill) the first one's runs. Windows drops the lock when the process ends."""
    global _instance_lock
    import msvcrt

    lock_path = paths.state_dir() / "service.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+")  # noqa: SIM115 — kept open on purpose
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return False
    _instance_lock = handle
    return True


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="reportflow-service",
        description="ReportFlow service: the local API and scheduler (run by NSSM).",
    )
    parser.add_argument("--author", action="store_true", help="who built this")
    # Unknown arguments are ignored, as before, so nothing passed in can stop the service.
    return parser.parse_known_args(argv)[0]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--author" in argv:
        from reportflow import author

        return author.show()
    parse(argv)
    configure_logging("service")
    if not take_instance_lock():
        logger.error(
            "Another ReportFlow service is already running on this computer (it holds {}). "
            "This copy stops.",
            paths.state_dir() / "service.lock",
        )
        return 1
    state = ServiceState()
    recovered = state.launcher.recover_interrupted()
    if recovered:
        logger.warning("{} run(s) were cut off by the last stop/restart", recovered)
    if state.config.app.debug_logging:
        from reportflow.core.logging_setup import reconfigure

        reconfigure("service", level="DEBUG")
    host = state.config.app.api_host
    port = state.config.app.api_port

    app = create_app(state)
    logger.info("Starting ReportFlow service API on http://{}:{}", host, port)
    try:
        uvicorn.run(app, host=host, port=port, log_config=None)
    except SystemExit:
        # uvicorn exits via SystemExit when it cannot start (e.g. the port is taken).
        logger.error(
            "Service failed to start — port {} may already be in use. Is another "
            "ReportFlow service (or a stray reportflow-service.exe) running?",
            port,
        )
        return 1
    except OSError as e:
        if getattr(e, "winerror", None) == 10048 or "address already in use" in str(e).lower():
            logger.error(
                "Port {} is already in use — another ReportFlow service (or a stray "
                "reportflow-service.exe) is running. Stop it and restart this service.",
                port,
            )
            return 1
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
