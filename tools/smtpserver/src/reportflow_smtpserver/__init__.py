"""Capture ReportFlow's SMTP messages locally as files that can be opened in a mail client.

Run it, point ReportFlow's Settings at host 127.0.0.1 / port 2525 (no TLS, no
username/password), and every "sent" email is printed here and saved as an .eml file you
can open in Outlook.

    uv run smtpserver            # listens on 127.0.0.1:2525
    uv run smtpserver --outbox build/local-test/outbox

Mails are written to build/local-test/outbox/ relative to the working directory.
"""

from __future__ import annotations

import argparse
import email
import email.policy
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from aiosmtpd.controller import Controller

OUTBOX = Path("build/local-test/outbox")


class _PrintAndSave:
    def __init__(self, outbox: Path = OUTBOX) -> None:
        self.outbox = outbox

    async def handle_DATA(self, server, session, envelope):
        message = email.message_from_bytes(envelope.content, policy=email.policy.default)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        eml_path = self.outbox / f"{stamp}_{uuid4().hex}.eml"
        try:
            self.outbox.mkdir(parents=True, exist_ok=True)
            eml_path.write_bytes(envelope.content)
        except OSError as exc:
            print(f"Could not save captured email: {exc}", file=sys.stderr, flush=True)
            return "452 Could not save captured email"

        attachments = [part.get_filename() for part in message.walk() if part.get_filename()]
        print("=" * 70)
        print(f"  From:        {envelope.mail_from}")
        print(f"  Envelope-To: {', '.join(envelope.rcpt_tos)}")
        print(f"  To:          {message.get('To', '')}")
        print(f"  Cc:          {message.get('Cc', '')}")
        print(f"  Subject:     {message.get('Subject', '')}")
        print(f"  Attachments: {', '.join(attachments) or '(none)'}")
        print(f"  Saved:       {eml_path}")
        print("=" * 70, flush=True)
        return "250 OK"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=["127.0.0.1"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2525)
    parser.add_argument("--outbox", type=Path, default=OUTBOX)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    outbox = args.outbox.resolve()
    controller = Controller(_PrintAndSave(outbox), hostname=args.host, port=args.port)
    try:
        outbox.mkdir(parents=True, exist_ok=True)
        controller.start()
    except (OSError, TimeoutError) as exc:
        print(f"Could not start SMTP capture on {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1
    print(f"Fake SMTP server listening on {args.host}:{args.port}")
    print("Point ReportFlow Settings at this host/port (no TLS, empty username/password).")
    print(f"Received emails are saved to {outbox}")
    print("Messages are stored locally. Press Ctrl+C to stop.", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
