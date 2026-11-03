"""Exercise the actual spec filter without executing a PyInstaller build in pytest."""

import ast
from pathlib import Path
from types import SimpleNamespace


def test_ui_bundle_retains_qt_but_excludes_foreign_windows_icu():
    spec = Path(__file__).parents[2] / "packaging/pyinstaller/ui.spec"
    tree = ast.parse(spec.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Attribute) and t.attr == "binaries" for t in node.targets)
    )
    entries = [
        ("icuuc.dll", "foreign/tool/icuuc.dll", "BINARY"),
        ("PySide6\\ICUIN.DLL", "foreign/tool/icuin.dll", "BINARY"),
        ("PySide6\\Qt6Core.dll", "wheel/Qt6Core.dll", "BINARY"),
        ("icudt78.dll", "private/icudt78.dll", "BINARY"),
    ]
    actual = eval(
        compile(ast.Expression(assignment.value), str(spec), "eval"),
        {"a": SimpleNamespace(binaries=entries)},
    )
    assert actual == entries[2:]
