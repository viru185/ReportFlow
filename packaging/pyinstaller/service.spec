# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Service exe (onedir, console — NSSM captures its output)."""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
ICON = os.path.join(ROOT, "assets", "reportflow.ico")

datas, binaries, hiddenimports = [], [], []
for pkg in ("uvicorn",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# The version lives only in pyproject.toml; frozen exes read it from package metadata.
datas += copy_metadata("reportflow")

hiddenimports += collect_submodules("apscheduler")
hiddenimports += [
    "fastapi",
    "openpyxl",
    "httpx",
    "anyio",
    "h11",
    "email_validator",
    "win32crypt",
    "win32ctypes",
]

a = Analysis(
    [os.path.join(ROOT, "src", "reportflow", "service", "__main__.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["PySide6", "shiboken6", "xlwings", "tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="reportflow-service",
    console=True,
    icon=ICON,
)
coll = COLLECT(exe, a.binaries, a.datas, name="service")
