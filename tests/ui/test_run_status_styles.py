"""Every run status has a colour, a pill tone and a card edge (0.16 added two)."""

from __future__ import annotations

import pytest

from reportflow.core.ipc.contract import FAILURE_STATUSES, FINAL_STATUSES, RunStatus
from reportflow.ui import style


@pytest.mark.parametrize("status", list(RunStatus))
def test_every_status_is_styled(status):
    assert status.value in style.STATUS_COLORS
    assert status.value in style._STATUS_TONES


def test_card_edges():
    assert style.status_edge("success") == "success"
    assert style.status_edge("running") == "running"
    for status in FAILURE_STATUSES:
        assert style.status_edge(status.value) == "failed"
    assert style.status_edge("stopped") == "muted"  # someone chose to stop it


def test_status_sets():
    assert RunStatus.STOPPED not in FAILURE_STATUSES
    assert RunStatus.INTERRUPTED in FAILURE_STATUSES
    assert RunStatus.RUNNING not in FINAL_STATUSES and RunStatus.STOPPED in FINAL_STATUSES


def test_badge_text(qtbot):
    assert style.status_badge("stopped").text() == "stopped"
    assert style.status_badge("interrupted").property("badge") == "danger"
