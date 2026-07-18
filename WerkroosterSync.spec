# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds a self-contained app for the current platform.

macOS  : dist/Werkrooster Sync.app   (copy the .app anywhere, it just works)
Windows: dist/WerkroosterSync.exe    (single portable .exe, no installer)

Build from the repository root:
    pyinstaller WerkroosterSync.spec --noconfirm
"""
import sys

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

hiddenimports = []
if IS_WIN:
    hiddenimports += ["win32com", "win32com.client", "pythoncom", "win32timezone"]

excludes = [
    "tkinter",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtMultimedia",
    "PySide6.QtCharts",
    "PySide6.QtPdf",
    "PySide6.QtDesigner",
]

a = Analysis(
    ["run_app.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

if IS_WIN:
    # Single-file portable .exe
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        name="WerkroosterSync",
        console=False,
        upx=False,
        icon=None,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        exclude_binaries=True,
        name="WerkroosterSync",
        console=False,
        upx=False,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        name="WerkroosterSync",
        upx=False,
    )
    if IS_MAC:
        app = BUNDLE(
            coll,
            name="Werkrooster Sync.app",
            icon=None,
            bundle_identifier="nl.werkroostersync.app",
            info_plist={
                "CFBundleName": "Werkrooster Sync",
                "CFBundleDisplayName": "Werkrooster Sync",
                "CFBundleShortVersionString": "1.0.0",
                "NSHighResolutionCapable": True,
                "NSAppleEventsUsageDescription": (
                    "Werkrooster Sync gebruikt de Agenda-app om je rooster "
                    "in je agenda te zetten."
                ),
                "CFBundleDocumentTypes": [
                    {
                        "CFBundleTypeName": "iCalendar bestand",
                        "CFBundleTypeExtensions": ["ics"],
                        "CFBundleTypeRole": "Viewer",
                    }
                ],
            },
        )
