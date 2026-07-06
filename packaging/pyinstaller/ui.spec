# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the UI exe (onedir, windowed).

collect_all("PySide6") ensures the platforms/qwindows.dll plugin ships (the #1 PySide6
packaging failure). Heavy unused Qt modules are excluded to cut size.
"""

import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

datas, binaries, hiddenimports = [], [], []
for pkg in ("PySide6",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += ["httpx", "win32crypt"]

a = Analysis(
    [os.path.join(ROOT, "src", "reportflow", "ui", "__main__.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "xlwings",
        "tkinter",
        "matplotlib",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQml",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
        "PySide6.QtMultimedia",
        "PySide6.QtQuick",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="reportflow-ui",
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ui")
