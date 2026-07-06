"""Shared test fixtures.

Redirect the ReportFlow data root to a temp directory so tests never read or write the
real ``%ProgramData%\\ReportFlow`` tree.
"""

from __future__ import annotations

import pytest

from reportflow.core import paths


@pytest.fixture(autouse=True)
def temp_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORTFLOW_DATA_DIR", str(tmp_path))
    paths.data_root.cache_clear()
    paths.ensure_dirs()
    yield tmp_path
    paths.data_root.cache_clear()
