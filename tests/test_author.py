import io
import random
import re

import pytest

from reportflow import author
from reportflow.service import __main__ as service_main
from reportflow.worker import __main__ as worker_main

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def test_plain_card_when_not_a_console():
    out = io.StringIO()
    assert author.show(out) == 0
    text = out.getvalue()
    assert text.isascii()
    assert "\x1b" not in text
    for line in author.QUOTE:
        assert line in text
    assert author.NAME in text and author.BY in text


@pytest.mark.parametrize("render", [author.big, author.compact])
def test_finished_card_is_a_closed_box_with_the_exact_quote(render):
    card = author.Card(render, random.Random(1))
    lines = [ANSI.sub("", line) for line in card.lines(author.END + 1)]
    assert len(lines) == card.height
    assert {len(line) for line in lines} == {card.width}
    assert lines[0].startswith("╭") and lines[-1].endswith("╯")
    body = "\n".join(lines)
    for line in author.QUOTE:
        assert line in body
    assert f"— {author.BY}" in body
    assert author.NAME in body


def test_every_frame_keeps_the_box_width():
    card = author.Card(author.compact, random.Random(2))
    for step in range(0, 45):
        lines = [ANSI.sub("", line) for line in card.lines(step / 10)]
        assert {len(line) for line in lines} == {card.width}


def _must_not_run(*_args, **_kw):
    raise AssertionError("--author must not read the configuration or start logging")


def test_service_author_needs_no_config_and_writes_no_log(monkeypatch, capsys):
    monkeypatch.setattr(service_main, "configure_logging", _must_not_run)
    monkeypatch.setattr(service_main, "ServiceState", _must_not_run)
    monkeypatch.setattr(service_main.uvicorn, "run", _must_not_run)
    assert service_main.main(["--author"]) == 0
    assert service_main.main(["--port", "1", "--author"]) == 0
    assert author.NAME in capsys.readouterr().out


def test_worker_author_needs_no_request_and_writes_no_log(monkeypatch, capsys):
    monkeypatch.setattr(worker_main, "configure_logging", _must_not_run)
    monkeypatch.setattr(worker_main, "read_request", _must_not_run)
    monkeypatch.setattr(worker_main, "run_job", _must_not_run)
    assert worker_main.main(["--author"]) == 0
    assert worker_main.main(["--request", "missing.json", "--author"]) == 0
    assert author.NAME in capsys.readouterr().out


@pytest.mark.parametrize("parse", [service_main.parse, worker_main.parse])
def test_help_hints_at_author_without_explaining_it(parse, capsys):
    with pytest.raises(SystemExit):
        parse(["--help"])
    text = capsys.readouterr().out
    assert "--author" in text and "who built this" in text
    assert author.NAME not in text  # only a hint: the name shows when you try it


def test_service_still_ignores_arguments_it_does_not_know():
    assert service_main.parse(["--anything", "x"]).author is False
