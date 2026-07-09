"""A local fake SMTP server for testing ReportFlow's emails WITHOUT sending real mail.

Run it, point ReportFlow's Settings at host 127.0.0.1 / port 2525 (no TLS, no
username/password), and every "sent" email is printed here and saved as an .eml file you
can open in Outlook.

    uv run python scripts/dev_smtp_server.py            # listens on 127.0.0.1:2525
    uv run python scripts/dev_smtp_server.py --port 25  # pretend to be a real relay

Mails are written to scripts/sample/outbox/.
"""

from __future__ import annotations

import argparse
import email
import email.policy
from datetime import datetime
from pathlib import Path

from aiosmtpd.controller import Controller

OUTBOX = Path(__file__).resolve().parent / "sample" / "outbox"


class _PrintAndSave:
    async def handle_DATA(self, server, session, envelope):
        message = email.message_from_bytes(envelope.content, policy=email.policy.default)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        OUTBOX.mkdir(parents=True, exist_ok=True)
        eml_path = OUTBOX / f"{stamp}.eml"
        eml_path.write_bytes(envelope.content)

        attachments = [part.get_filename() for part in message.walk() if part.get_filename()]
        print("=" * 70)
        print(f"  From:        {envelope.mail_from}")
        print(f"  Envelope-To: {', '.join(envelope.rcpt_tos)}")
        print(f"  To:          {message.get('To', '')}")
        print(f"  Cc:          {message.get('Cc', '')}")
        print(f"  Subject:     {message.get('Subject', '')}")
        print(f"  Attachments: {', '.join(attachments) or '(none)'}")
        print(f"  Saved:       {eml_path}")
        print("=" * 70)
        return "250 OK"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2525)
    args = parser.parse_args()

    controller = Controller(_PrintAndSave(), hostname=args.host, port=args.port)
    controller.start()
    print(f"Fake SMTP server listening on {args.host}:{args.port}")
    print("Point ReportFlow Settings at this host/port (no TLS, empty username/password).")
    print(f"Received emails are saved to {OUTBOX}")
    print("Press Ctrl+C to stop.")
    try:
        import time

        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()


if __name__ == "__main__":
    main()
