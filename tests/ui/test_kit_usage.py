"""The UI is built from ``reportflow.ui.kit`` — never raw Qt widgets or inline stylesheets.

One class per kind of widget is what keeps every button, dropdown, list and menu looking
and behaving the same. A raw ``QPushButton(...)`` or a ``setStyleSheet(...)`` in a window is
how the look drifted before (a square amber tooltip, an emoji menu, 12 px scrollbars).
"""

from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "src" / "reportflow" / "ui"
RAW = re.compile(
    r"\b(QPushButton|QToolButton|QComboBox|QMenu|QScrollArea|QListWidget|QTableWidget"
    r"|QSpinBox|QTimeEdit)\("
)
INLINE_STYLE = re.compile(r"\.setStyleSheet\(")


def _ui_sources() -> list[Path]:
    return [
        path
        for path in UI.rglob("*.py")
        if "kit" not in path.relative_to(UI).parts and path.name != "style.py"
    ]


def test_windows_build_widgets_from_the_kit():
    offenders = [
        f"{path.relative_to(UI)}:{number}: {line.strip()}"
        for path in _ui_sources()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if RAW.search(line)
    ]
    assert not offenders, "use reportflow.ui.kit instead:\n" + "\n".join(offenders)


def test_no_inline_stylesheets_outside_the_theme():
    offenders = [
        f"{path.relative_to(UI)}:{number}: {line.strip()}"
        for path in _ui_sources()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if INLINE_STYLE.search(line)
    ]
    assert not offenders, "style with a property + style.py instead:\n" + "\n".join(offenders)
