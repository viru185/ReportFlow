"""UI entry point: launch the ReportFlow desktop app."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from reportflow import __about__ as about
from reportflow.core.logging_setup import configure_logging
from reportflow.ui.assets import app_icon
from reportflow.ui.style import APP_QSS
from reportflow.ui.windows.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    configure_logging("ui", to_console=False)
    app = QApplication(argv)
    app.setApplicationName(about.NAME)
    app.setWindowIcon(app_icon())
    app.setStyleSheet(APP_QSS)
    # --selftest: construct the QApplication (which loads the Qt platform plugin, e.g.
    # qwindows) and exit 0. Used to validate the frozen build without a visible window.
    if "--selftest" in argv:
        return 0
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
