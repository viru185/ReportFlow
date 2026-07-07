# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the UI exe (onedir, windowed).

The UI uses only QtCore/QtGui/QtWidgets. Rather than collect_all("PySide6") (which pulls
~680 MB of Qt), we let PyInstaller's bundled PySide6 hook collect exactly the imported
modules plus the required plugins (crucially platforms/qwindows.dll), and exclude the heavy
unused Qt modules so nothing drags them in. Validate the frozen build with:

    reportflow-ui.exe --selftest    # exit 0 == the qwindows platform plugin loaded
"""

import os

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
ICON = os.path.join(ROOT, "assets", "reportflow.ico")

# Heavy Qt modules this app never imports. Excluding them keeps the analysis from pulling
# their (large) DLLs and data.
_QT_EXCLUDES = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuick3D",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtWebSockets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtUiTools",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtTextToSpeech",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtRemoteObjects",
    "PySide6.QtHttpServer",
    "PySide6.QtSvgWidgets",
]

a = Analysis(
    [os.path.join(ROOT, "src", "reportflow", "ui", "__main__.py")],
    pathex=[os.path.join(ROOT, "src")],
    datas=[
        (os.path.join(ROOT, "assets", "reportflow.png"), "assets"),
        (os.path.join(ROOT, "assets", "check.svg"), "assets"),
        (os.path.join(ROOT, "src", "reportflow"), "reportflow"),
    ],
    hiddenimports=["httpx", "win32crypt", "importlib.metadata"],
    excludes=["xlwings", "tkinter", "matplotlib", *_QT_EXCLUDES],
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
    icon=ICON,
)
coll = COLLECT(exe, a.binaries, a.datas, name="ui")
