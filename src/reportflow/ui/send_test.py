"""Send a test email from the template editor — one email to one address you type.

The popover sends the template and subject exactly as they are in the editor (nothing has to
be saved first), filled with the preview's sample values, ``[TEST]`` in the subject and no
attachments (``POST /email/send-test``). The address is remembered for next time. Sending
runs on a worker thread, so the editor never freezes while the mail server answers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent, QObject, Qt, QThread, Signal
from PySide6.QtWidgets import QCompleter, QHBoxLayout, QLabel, QLineEdit, QWidget

from reportflow.ui.api_client import ApiError
from reportflow.ui.assets import asset_icon
from reportflow.ui.feedback import recall, remember, toast
from reportflow.ui.kit import Button, Popover, styled_completer
from reportflow.ui.recipient_field import is_address

_ADDRESS_KEY = "template/test_address"
_RUNNING: set[_SendThread] = set()  # sends still in flight (kept alive until finished)


class _SendThread(QThread):
    done = Signal(str)  # "" when sent, else why not

    def __init__(self, send: Callable[[dict], Any], payload: dict) -> None:
        super().__init__()
        self._send = send
        self._payload = payload

    def run(self) -> None:
        try:
            self._send(self._payload)
        except ApiError as e:
            self.done.emit(str(e))
        except Exception as e:  # noqa: BLE001 — shown to the user, never raised into Qt
            self.done.emit(f"Couldn't send: {e}")
        else:
            self.done.emit("")


class SendTestPopover(Popover):
    """ "Send a test email" under its button. ``payload()`` is the email as it is now."""

    sent = Signal(str)  # the address it went to

    def __init__(
        self,
        parent: QWidget,
        *,
        send: Callable[[dict], Any],
        payload: Callable[[], dict],
        addresses: list[str] | None = None,
    ) -> None:
        super().__init__(parent, name="sendTestPopover")
        self._send = send
        self._payload = payload
        self.setFixedWidth(400)
        title = QLabel("Send a test email")
        title.setProperty("popoverTitle", True)
        self.body.addWidget(title)
        about = QLabel(
            "One email to this address: the template as it is now, with sample values, "
            "[TEST] in the subject and no attachments."
        )
        about.setWordWrap(True)
        about.setProperty("muted", True)
        self.body.addWidget(about)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.address = QLineEdit(str(recall(_ADDRESS_KEY) or ""))
        self.address.setPlaceholderText("name@company.com")
        self.address.setAccessibleName("Send the test to")
        self.address.textEdited.connect(lambda *_: self._show_error(""))
        self.address.installEventFilter(self)
        if addresses:
            completer = QCompleter(addresses, self.address)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            styled_completer(completer)
            self.address.setCompleter(completer)
        self.send_button = Button("Send", variant="primary", icon=asset_icon("send.svg"))
        self.send_button.clicked.connect(self.send)
        row.addWidget(self.address, 1)
        row.addWidget(self.send_button)
        self.body.addLayout(row)
        self.error = QLabel("")
        self.error.setObjectName("fieldError")
        self.error.setWordWrap(True)
        self.error.hide()
        self.body.addWidget(self.error)

    def open_for(self, anchor: QWidget) -> None:
        self._show_error("")
        self.open_at(anchor, focus=self.address, align="right")
        self.address.selectAll()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            watched is self.address
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)  # type: ignore[attr-defined]
        ):
            completer = self.address.completer()
            popup = completer.popup() if completer is not None else None
            if popup is None or not popup.isVisible():
                self.send()
                return True
        return super().eventFilter(watched, event)

    def _show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(bool(text))
        self.adjustSize()

    def send(self) -> None:
        to = self.address.text().strip()
        if not is_address(to):
            self._show_error("Type the email address to send the test to.")
            self.address.setFocus()
            return
        self._show_error("")
        self.send_button.setEnabled(False)
        self.send_button.setText("Sending…")
        thread = _SendThread(self._send, {**self._payload(), "to": to})
        _RUNNING.add(thread)
        thread.done.connect(lambda error, address=to: self._finished(address, error))
        thread.finished.connect(lambda t=thread: _RUNNING.discard(t))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _finished(self, address: str, error: str) -> None:
        self.send_button.setEnabled(True)
        self.send_button.setText("Send")
        if error:
            self._show_error(error)
            return
        remember(_ADDRESS_KEY, address)
        owner = self.parentWidget()
        self.close()
        if owner is not None:
            toast(owner, f"Test email sent to {address}.", "success")
        self.sent.emit(address)
