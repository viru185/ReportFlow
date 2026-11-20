"""Shared test fixtures.

Redirect the ReportFlow data root to a temp directory so tests never read or write the
real ``%ProgramData%\\ReportFlow`` tree, and hide this machine's PI add-in registrations so
results never depend on whether PI DataLink happens to be installed (or trusted) here.
"""

from __future__ import annotations

import pytest

from reportflow.core import paths, vsto_trust


@pytest.fixture(autouse=True)
def temp_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTFLOW_DATA_DIR", str(tmp_path))
    paths.data_root.cache_clear()
    paths.ensure_dirs()
    yield tmp_path
    paths.data_root.cache_clear()


@pytest.fixture(autouse=True)
def no_local_pi_addins(monkeypatch):
    monkeypatch.setattr(vsto_trust, "pi_registrations", lambda: [])
