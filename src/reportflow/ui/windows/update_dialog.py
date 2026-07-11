"""Update-available dialog: shows release notes; downloads with progress and launches
the installer silently on the user's explicit click (the upgrade itself is automatic).
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import httpx
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from reportflow import __about__ as about
from reportflow.ui.updater import UpdateInfo


class _DownloadThread(QThread):
    progress = Signal(int, int)  # received, total
    done = Signal(str)  # file path
    failed = Signal(str)

    def __init__(self, url: str, dest: Path, parent=None) -> None:
        super().__init__(parent)
        self._url = url
        self._dest = dest
        self.cancelled = False

    def run(self) -> None:
        try:
            with httpx.stream("GET", self._url, follow_redirects=True, timeout=60) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length", 0))
                received = 0
                with open(self._dest, "wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=256 * 1024):
                        if self.cancelled:
                            return
                        fh.write(chunk)
                        received += len(chunk)
                        self.progress.emit(received, total)
            self.done.emit(str(self._dest))
        except Exception as e:  # noqa: BLE001 — surfaced in the dialog
            self.failed.emit(str(e))


class UpdateDialog(QDialog):
    def __init__(self, info: UpdateInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._info = info
        self._thread: _DownloadThread | None = None
        self.setWindowTitle(f"Update available — v{about.VERSION} → v{info.version}")
        self.resize(520, 420)

        layout = QVBoxLayout(self)
        headline = QLabel(
            f"<b>{about.NAME} update: v{about.VERSION} &nbsp;→&nbsp; v{info.version}</b><br>"
            f"You are currently on version {about.VERSION}."
        )
        headline.setWordWrap(True)
        layout.addWidget(headline)

        notes = QTextBrowser()
        notes.setMarkdown(info.notes or "_No release notes._")
        layout.addWidget(notes, 1)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setProperty("muted", True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.update_btn = QPushButton("Update now")
        self.update_btn.setProperty("accent", True)
        self.update_btn.setToolTip(
            "Download the installer and upgrade automatically. The app closes and reopens "
            "when the update finishes; your jobs, settings, and logs are preserved."
        )
        self.update_btn.clicked.connect(self._start)
        later = QPushButton("Later")
        later.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(later)
        buttons.addWidget(self.update_btn)
        layout.addLayout(buttons)

        if info.installer_url is None:
            self.update_btn.setEnabled(False)
            self.status.setText("The release has no installer asset yet — try again shortly.")

    def _start(self) -> None:
        assert self._info.installer_url is not None
        self.update_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.status.setText("Downloading update…")

        self.status.setText(
            f"Updating from v{about.VERSION} to v{self._info.version} — downloading…"
        )
        dest = Path(tempfile.gettempdir()) / f"ReportFlow-Setup-{self._info.version}.exe"
        thread = _DownloadThread(self._info.installer_url, dest, self)
        thread.progress.connect(self._on_progress)
        thread.done.connect(self._on_done)
        thread.failed.connect(self._on_failed)
        self._thread = thread
        thread.start()

    def _on_progress(self, received: int, total: int) -> None:
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(received)
            self.status.setText(f"Downloading update… {received / 1e6:.1f} / {total / 1e6:.1f} MB")
        else:
            self.progress.setMaximum(0)  # busy indicator

    def _on_done(self, path: str) -> None:
        self.status.setText("Download complete — updating and reopening ReportFlow…")
        # /SILENT: automatic upgrade with a progress window only (no wizard). The
        # installer stops the service, replaces files, preserves ProgramData, restarts.
        try:
            subprocess.Popen([path, "/SILENT"], close_fds=True)  # noqa: S603
        except OSError as e:
            QMessageBox.warning(self, "Update", f"Could not start the installer: {e}")
            self.update_btn.setEnabled(True)
            return
        os_quit = QApplication.instance()
        if os_quit is not None:
            os_quit.quit()  # release our files so the installer can replace them

    def _on_failed(self, error: str) -> None:
        QMessageBox.warning(self, "Update failed", f"Download failed: {error}")
        self.progress.setVisible(False)
        self.update_btn.setEnabled(True)
        self.status.setText("")

    def reject(self) -> None:  # cancel an in-flight download on Later/close
        if self._thread is not None and self._thread.isRunning():
            self._thread.cancelled = True
        super().reject()
