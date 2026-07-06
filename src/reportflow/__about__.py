"""Project metadata — the single source of truth for the About screen and docs."""

from __future__ import annotations

from reportflow import __version__ as VERSION

NAME = "ReportFlow"
SUMMARY = (
    "Windows automation for Excel-based reporting — schedule a workbook, refresh its data, "
    "freeze formulas to values, export per-sheet PDFs using the workbook's own print layout, "
    "and email the results."
)
AUTHOR = "Viren Hirpara"
REPO_URL = "https://github.com/viru185/ReportFlow"
GITHUB_URL = "https://github.com/viru185"
LINKEDIN_URL = "https://www.linkedin.com/in/hirparaviren/"

__all__ = [
    "NAME",
    "SUMMARY",
    "VERSION",
    "AUTHOR",
    "REPO_URL",
    "GITHUB_URL",
    "LINKEDIN_URL",
]
