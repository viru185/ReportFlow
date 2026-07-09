"""Windows Service entry point: host the local API + scheduler.

Registered as a Windows service via NSSM (a plain console process). Binds to localhost only.
"""

from __future__ import annotations

import sys

import uvicorn
from loguru import logger

from reportflow.core.logging_setup import configure_logging
from reportflow.service.api import ServiceState, create_app


def main(argv: list[str] | None = None) -> int:
    configure_logging("service")
    state = ServiceState()
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
