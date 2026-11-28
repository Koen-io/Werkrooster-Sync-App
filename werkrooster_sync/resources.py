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


def open_path(path) -> None:
    """Open a file with the operating system's default application."""
    import os
    import subprocess

    p = str(path)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", p])
        elif os.name == "nt":
            os.startfile(p)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", p])
    except OSError:
        pass
