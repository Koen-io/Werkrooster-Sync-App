# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds a self-contained app for the current platform.

macOS  : dist/Werkrooster Sync.app   (copy the .app anywhere, it just works)
Windows: dist/WerkroosterSync.exe    (single portable .exe, no installer)

Build from the repository root:
    pyinstaller WerkroosterSync.spec --noconfirm
"""
import sys

from PyInstaller.utils.hooks import collect_all

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

hiddenimports = ["pypdf", "certifi"]
if IS_WIN:
    hiddenimports += ["win32com", "win32com.client", "pythoncom", "win32timezone"]

# curl_cffi ships a compiled libcurl-impersonate + cert bundle that must be
# collected so the packaged app can present a real Chrome TLS fingerprint
# (needed to pass Cloudflare in front of Web3Forms).
_cffi_datas, _cffi_binaries, _cffi_hidden = collect_all("curl_cffi")
hiddenimports += _cffi_hidden

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
    binaries=_cffi_binaries,
    datas=[("assets", "assets"), ("werkrooster_sync/fonts", "fonts")] + _cffi_datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

import os

ICON_WIN = os.path.join("assets", "icon.ico")
ICON_MAC = os.path.join("assets", "icon.icns")

# Versienummer uit version.py (de bouw zet daar het releasenummer in). Finder
# wil alleen cijfers en punten: "2.0.3-proef" wordt "2.0.3".
import re
_ns = {}
exec(open(os.path.join("werkrooster_sync", "version.py"), encoding="utf-8").read(), _ns)
MAC_VERSION = re.match(r"[0-9.]*", _ns["__version__"]).group().strip(".") or "0.0.0"

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
        icon=ICON_WIN if os.path.exists(ICON_WIN) else None,
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
            icon=ICON_MAC if os.path.exists(ICON_MAC) else None,
            bundle_identifier="nl.werkroostersync.app",
            info_plist={
                "CFBundleName": "Werkrooster Sync",
                "CFBundleDisplayName": "Werkrooster Sync",
                "CFBundleShortVersionString": MAC_VERSION,
                "NSHighResolutionCapable": True,
                # Alleen de Intel-versie zet MAC_MIN_OS (build.yml): een te
                # oude Mac zegt dan netjes welke macOS nodig is.
                **({"LSMinimumSystemVersion": os.environ["MAC_MIN_OS"]}
                   if os.environ.get("MAC_MIN_OS") else {}),
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
