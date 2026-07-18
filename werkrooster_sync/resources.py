"""Locating bundled assets, both in development and in the packaged app."""
from __future__ import annotations

import sys
from pathlib import Path


def assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller: bundled data lives next to the unpacked runtime files.
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parents[1]
    return base / "assets"


def asset_path(name: str) -> Path:
    return assets_dir() / name
