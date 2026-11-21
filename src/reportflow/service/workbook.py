"""Workbook sheet discovery for the UI — via openpyxl, never COM.

Keeping Excel out of the Service is a hard rule; sheet names are read statically.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook


class WorkbookError(Exception):
    pass


class WorkbookNotFound(WorkbookError):
    """The file isn't there — as seen by the SERVICE's Windows account."""


def discover_sheets(path: Path) -> list[str]:
    p = Path(path)
    if not p.exists():
        # The service runs as its own account: a mapped drive letter (Z:\) of the
        # user's is invisible to it, while the same share's \\server\path works.
        raise WorkbookNotFound(
            f"The ReportFlow service can't find {p}. If the file is on a mapped drive, "
            "use its full network path (\\\\server\\share\\…) instead."
        )
    try:
        wb = load_workbook(p, read_only=True, keep_links=False)
    except Exception as e:  # noqa: BLE001 — surface a clean message to the UI
        raise WorkbookError(f"could not open workbook: {e}") from e
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()
