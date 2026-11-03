"""UI entry point: launch the ReportFlow desktop app."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from reportflow import __about__ as about
from reportflow.core.logging_setup import configure_logging, reconfigure
from reportflow.ui.assets import app_icon
from reportflow.ui.style import apply_theme
from reportflow.ui.windows.main_window import MainWindow


def _apply_debug_level_from_config() -> None:
    """Honor app.debug_logging for the UI's own log file (read from the local config)."""
    try:
        from reportflow.core.config.loader import load_config

        if load_config().app.debug_logging:
            reconfigure("ui", level="DEBUG", to_console=False)
    except Exception:  # noqa: BLE001 — config missing/broken: stay at INFO
        pass


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    configure_logging("ui", to_console=False)
    _apply_debug_level_from_config()

    from loguru import logger

    from reportflow.core import paths

    logger.info(
        "UI starting — version {}, data dir {}, exe {}",
        about.VERSION,
        paths.data_root(),
        sys.executable,
    )
    app = QApplication(argv)
    app.setApplicationName(about.NAME)
    app.setWindowIcon(app_icon())
    apply_theme(app)
    # --selftest: construct the QApplication (which loads the Qt platform plugin, e.g.
    # qwindows) and exit 0. Used to validate the frozen build without a visible window.
    if "--selftest" in argv:
        return 0
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
