"""Output filename tokens — shared by the launcher (real runs) and the job editor's preview.

A job's output name is a stem pattern such as ``{job}_{datetime}``. The default carries the
time of day: with a date-only stem a job run twice on the same day overwrote the first
report. ``{sheet}`` is not expanded here — the worker resolves it per PDF.
"""

from __future__ import annotations

from datetime import datetime

DEFAULT_OUTPUT_STEM = "{job}_{datetime}"

# Tokens that make two runs on the same day produce different file names.
_UNIQUE_PER_RUN = ("{time}", "{datetime}", "{run_id}")


def expand_output_name(
    pattern: str, *, job_name: str, run_id: str, now: datetime, workbook: str = ""
) -> str:
    """Expand {job}/{date}/{time}/{datetime}/{run_id}/{workbook} in an output name."""
    text = pattern.replace("{date}", now.strftime("%Y%m%d"))
    text = text.replace("{time}", now.strftime("%H%M%S"))
    text = text.replace("{datetime}", now.strftime("%Y%m%d_%H%M%S"))
    text = text.replace("{job}", job_name)
    text = text.replace("{run_id}", run_id)
    text = text.replace("{workbook}", workbook)
    return text


def overwrites_same_day(pattern: str) -> bool:
    """True when two runs on one day would get the same name (and the second overwrites)."""
    return not any(token in pattern for token in _UNIQUE_PER_RUN)
