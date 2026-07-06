"""UI entry point: launch the ReportFlow desktop app."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from reportflow.core.logging_setup import configure_logging
from reportflow.ui.windows.main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    configure_logging("ui", to_console=False)
    app = QApplication(argv)
    app.setApplicationName("ReportFlow")
    # --selftest: construct the QApplication (which loads the Qt platform plugin, e.g.
    # qwindows) and exit 0. Used to validate the frozen build without a visible window.
    if "--selftest" in argv:
        return 0
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
