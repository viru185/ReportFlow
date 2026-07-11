"""Shared log colouring + filtering for the log viewers.

* :func:`filter_log_text` — pure line filter by level threshold and search term (grep-like),
  unit-testable without Qt.
* :class:`LogHighlighter` — a ``QSyntaxHighlighter`` that tints each line by its loguru level
  and highlights the current search term. Used by both the application-log viewer and the
  per-run log popup so colouring is consistent.
"""

from __future__ import annotations

import re

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat

from reportflow.ui.style import ACCENT, LOG_LEVEL_COLORS

# loguru's default line: "2026-07-11 11:51:08.123 | INFO     | module:func:42 - message".
_LEVEL_RE = re.compile(r"\|\s*(TRACE|DEBUG|INFO|SUCCESS|WARNING|ERROR|CRITICAL)\s*\|")

# Severity order for the level filter (matches loguru's numeric levels).
_SEVERITY: dict[str, int] = {
    "TRACE": 5,
    "DEBUG": 10,
    "INFO": 20,
    "SUCCESS": 25,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


def line_level(line: str) -> str | None:
    """The loguru level named in a log line, or None (e.g. a traceback continuation)."""
    m = _LEVEL_RE.search(line)
    return m.group(1) if m else None


def filter_log_text(text: str, *, min_level: str = "", search: str = "") -> str:
    """Keep lines at/above ``min_level`` that contain ``search`` (case-insensitive).

    Lines with no detectable level (continuations) are kept — they belong to the line above.
    An empty ``min_level`` means no level filtering; an empty ``search`` means no text filter.
    """
    min_sev = _SEVERITY.get(min_level.upper(), 0)
    term = search.lower()
    kept: list[str] = []
    for line in text.splitlines():
        level = line_level(line)
        if level and _SEVERITY[level] < min_sev:
            continue
        if term and term not in line.lower():
            continue
        kept.append(line)
    return "\n".join(kept)


class LogHighlighter(QSyntaxHighlighter):
    """Colour each log line by its level and highlight the active search term."""

    def __init__(self, document) -> None:  # noqa: ANN001 — QTextDocument
        super().__init__(document)
        self._search = ""

    def set_search(self, term: str) -> None:
        self._search = term or ""
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802 — Qt override
        level = line_level(text)
        if level:
            color = LOG_LEVEL_COLORS.get(level)
            if color:
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(color))
                self.setFormat(0, len(text), fmt)
        if self._search:
            low = text.lower()
            term = self._search.lower()
            start = 0
            while True:
                idx = low.find(term, start)
                if idx < 0:
                    break
                fmt = QTextCharFormat()
                fmt.setBackground(QColor(ACCENT))
                fmt.setForeground(QColor("#ffffff"))
                self.setFormat(idx, len(term), fmt)
                start = idx + len(term)
