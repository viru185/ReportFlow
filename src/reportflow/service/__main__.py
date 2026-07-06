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
    host = state.config.app.api_host
    port = state.config.app.api_port

    app = create_app(state)
    logger.info("Starting ReportFlow service API on http://{}:{}", host, port)
    uvicorn.run(app, host=host, port=port, log_config=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
