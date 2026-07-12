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

from reportflow.ui.style import ACCENT, LOG_LEVEL_COLORS, LOG_LOCATION, LOG_TIME

# loguru's default line: "2026-07-11 11:51:08.123 | INFO     | module:func:42 - message".
_LEVEL_RE = re.compile(r"\|\s*(TRACE|DEBUG|INFO|SUCCESS|WARNING|ERROR|CRITICAL)\s*\|")

# Full-line parse for per-segment (date | level | location | message) colouring.
_LINE_RE = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\s*\|\s*"
    r"(?P<level>TRACE|DEBUG|INFO|SUCCESS|WARNING|ERROR|CRITICAL)\s*\|\s*"
    r"(?P<loc>.*?) - (?P<msg>.*)$"
)

# Levels whose message text is worth tinting so problems pop even mid-line.
_LOUD_LEVELS = frozenset({"WARNING", "ERROR", "CRITICAL"})

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


def segment_spans(line: str) -> list[tuple[int, int, str, bool]]:
    """Return ``(start, end, colour, bold)`` spans colouring a loguru line by segment.

    Splits ``<time> | <LEVEL> | <location> - <message>`` into distinctly-coloured parts:
    timestamp, level (bold, in its level colour), location, and message (tinted only for
    loud levels). Returns an empty list when the line doesn't match the loguru format
    (tracebacks, stdio) — callers fall back to whole-line colouring. Pure; Qt-free.
    """
    m = _LINE_RE.match(line)
    if not m:
        return []
    level = m.group("level")
    level_color = LOG_LEVEL_COLORS.get(level, "")
    spans: list[tuple[int, int, str, bool]] = [
        (m.start("time"), m.end("time"), LOG_TIME, False),
        (m.start("level"), m.end("level"), level_color, True),
        (m.start("loc"), m.end("loc"), LOG_LOCATION, False),
    ]
    if level in _LOUD_LEVELS and level_color:
        spans.append((m.start("msg"), m.end("msg"), level_color, False))
    return spans


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
        spans = segment_spans(text)
        if spans:
            for start, end, color, bold in spans:
                if not color:
                    continue
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(color))
                if bold:
                    fmt.setFontWeight(700)
                self.setFormat(start, end - start, fmt)
        else:
            # Unparseable line (traceback / stdio): fall back to whole-line level tint.
            level = line_level(text)
            line_color = LOG_LEVEL_COLORS.get(level) if level else None
            if line_color:
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(line_color))
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
