"""Run Qt tests headless, with per-test UI settings and no blocking prompts."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _isolated_ui(tmp_path, monkeypatch):
    """Remembered window sizes go to a per-test folder (never the developer's own settings),
    and "Discard changes?" answers Discard, so qtbot's teardown can't block on a dialog.
    Tests about the prompt itself patch ``confirm_discard`` again."""
    from PySide6.QtCore import QSettings

    from reportflow.ui import feedback

    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "qsettings")
    )
    monkeypatch.setattr(feedback, "confirm_discard", lambda *_a, **_k: True)
