"""Compatibility launcher for the local SMTP capture command."""

import sys

from reportflow.dev_smtp import _PrintAndSave as _PrintAndSave
from reportflow.dev_smtp import main

if __name__ == "__main__":
    sys.exit(main())
