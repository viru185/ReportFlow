"""Unit tests for the pure log filter/level helpers (no Qt)."""

from __future__ import annotations

from reportflow.ui.log_format import filter_log_text, line_level, segment_spans
from reportflow.ui.style import LOG_LEVEL_COLORS, LOG_LOCATION, LOG_TIME

_SAMPLE = "\n".join(
    [
        "2026-07-11 10:00:00.000 | DEBUG    | m:f:1 - low detail",
        "2026-07-11 10:00:01.000 | INFO     | m:f:2 - hello world",
        "2026-07-11 10:00:02.000 | WARNING  | m:f:3 - be careful",
        "    a traceback continuation line",
        "2026-07-11 10:00:03.000 | ERROR    | m:f:4 - boom",
    ]
)


def test_line_level_detects_and_ignores():
    assert line_level("2026 | ERROR    | m:f:1 - x") == "ERROR"
    assert line_level("    continuation") is None


def test_level_filter_keeps_threshold_and_continuations():
    out = filter_log_text(_SAMPLE, min_level="Warning").splitlines()
    assert "be careful" in out[0]
    assert any("continuation" in line for line in out)  # no-level lines are kept
    assert any("boom" in line for line in out)
    assert not any("low detail" in line for line in out)  # DEBUG dropped
    assert not any("hello world" in line for line in out)  # INFO dropped


def test_search_filters_to_matching_lines():
    out = filter_log_text(_SAMPLE, search="hello")
    assert out.strip().endswith("hello world")
    assert "boom" not in out


def test_empty_filters_return_everything():
    assert filter_log_text(_SAMPLE) == _SAMPLE


def test_segment_spans_colours_time_level_location_distinctly():
    line = "2026-07-11 10:00:01.000 | INFO     | mod:func:42 - hello world"
    spans = segment_spans(line)
    # time, level, location (INFO message is NOT tinted -> only 3 spans)
    assert len(spans) == 3
    by_color = {color: line[start:end] for start, end, color, _bold in spans}
    assert by_color[LOG_TIME] == "2026-07-11 10:00:01.000"
    assert by_color[LOG_LEVEL_COLORS["INFO"]] == "INFO"
    assert by_color[LOG_LOCATION] == "mod:func:42"
    # the level token is bold
    assert any(bold for *_x, bold in spans)


def test_segment_spans_tints_message_for_loud_levels():
    line = "2026-07-11 10:00:03.000 | ERROR    | m:f:4 - boom"
    spans = segment_spans(line)
    # time, level, location, AND message (loud) -> 4 spans, message in the error colour
    assert len(spans) == 4
    err = LOG_LEVEL_COLORS["ERROR"]
    msg_span = [(s, e) for s, e, c, _b in spans if c == err and line[s:e] == "boom"]
    assert msg_span


def test_segment_spans_empty_for_unparseable_lines():
    assert segment_spans("    a traceback continuation line") == []
    assert segment_spans("") == []
