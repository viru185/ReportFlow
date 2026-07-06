# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Excel Worker exe (onedir, console).

Launched by the Service with CREATE_NO_WINDOW so the console never flashes.
"""

import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
ICON = os.path.join(ROOT, "assets", "reportflow.ico")

datas, binaries, hiddenimports = [], [], []
for pkg in ("xlwings",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += [
    "win32com",
    "win32com.client",
    "pythoncom",
    "pywintypes",
    "win32api",
    "win32event",
    "win32process",
    "pypdf",
    "psutil",
]

a = Analysis(
    [os.path.join(ROOT, "src", "reportflow", "worker", "__main__.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["PySide6", "shiboken6", "tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="reportflow-worker",
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="worker")
