"""Persistent app settings.

Settings are stored as JSON. The app is fully portable: when a ``settings.json``
exists (or can be created) next to the executable/bundle, it is used, so the app
can be copied to another machine together with its configuration. Otherwise the
per-user config directory is used.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import DEFAULT_NAMES, ShiftType

APP_NAME = "WerkroosterSync"


def _portable_dir() -> Path:
    """Directory next to the running executable / script."""
    if getattr(sys, "frozen", False):  # PyInstaller bundle
        exe = Path(sys.executable).resolve()
        if sys.platform == "darwin" and ".app/Contents/MacOS" in str(exe):
            # Place settings next to the .app bundle, not inside it.
            return exe.parents[3]
        return exe.parent
    return Path(__file__).resolve().parents[2]


def _user_config_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def settings_path() -> Path:
    portable = _portable_dir() / "settings.json"
    if portable.exists():
        return portable
    # Try to use the portable location if it is writable.
    try:
        portable.parent.mkdir(parents=True, exist_ok=True)
        test = portable.parent / ".write_test"
        test.write_text("", encoding="utf-8")
        test.unlink()
        return portable
    except OSError:
        d = _user_config_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d / "settings.json"


#: Default classification rules. An event is classified by keyword first;
#: if no keyword matches, by the hour its shift starts.
DEFAULT_RULES: dict[str, Any] = {
    "keywords": {
        ShiftType.VRIJ.value: ["vrij", "vry", "off", "rooster vrij", "roostervrij"],
        ShiftType.OCHTEND.value: ["ochtend", "vroeg", "morning", "early"],
        ShiftType.LAAT.value: ["laat", "avond", "late", "evening"],
        ShiftType.NACHT.value: ["nacht", "night"],
        # "dienst" is the fallback category; generic words like "dienst" must
        # not override the start-time rules, so no default keywords here.
        ShiftType.DIENST.value: [],
    },
    # Start-hour windows [from, to) in local time, checked in this order.
    "time_windows": {
        ShiftType.NACHT.value: [20, 5],
        ShiftType.OCHTEND.value: [5, 12],
        ShiftType.LAAT.value: [12, 20],
    },
    # A timed roster item without a matching keyword only counts as a shift
    # when it lasts at least this many hours; shorter items (meetings,
    # courses, …) become 'afspraak' and keep their original title.
    "min_shift_hours": 5,
}

DEFAULT_REMINDERS: dict[str, dict[str, Any]] = {
    ShiftType.VRIJ.value: {"enabled": False, "minutes": 0},
    ShiftType.OCHTEND.value: {"enabled": True, "minutes": 720},
    ShiftType.LAAT.value: {"enabled": True, "minutes": 120},
    ShiftType.NACHT.value: {"enabled": True, "minutes": 240},
    ShiftType.DIENST.value: {"enabled": True, "minutes": 120},
    ShiftType.AFSPRAAK.value: {"enabled": True, "minutes": 30},
}

#: How each shift type appears in the calendar: "all_day" (an item at the top
#: of the day) or "timed" (a block at the exact shift times).
DEFAULT_DISPLAY: dict[str, str] = {
    ShiftType.VRIJ.value: "all_day",
    ShiftType.OCHTEND.value: "timed",
    ShiftType.LAAT.value: "timed",
    ShiftType.NACHT.value: "timed",
    ShiftType.DIENST.value: "timed",
    ShiftType.AFSPRAAK.value: "timed",
}


@dataclass
class Settings:
    """All user-adjustable settings."""

    backend_id: str = ""  # empty = auto-select best backend for this platform
    calendar_name: str = ""
    names: dict[str, str] = field(
        default_factory=lambda: {t.value: n for t, n in DEFAULT_NAMES.items()}
    )
    reminders: dict[str, dict[str, Any]] = field(
        default_factory=lambda: json.loads(json.dumps(DEFAULT_REMINDERS))
    )
    include_vrij: bool = True
    include_afspraken: bool = True
    display: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_DISPLAY))
    rules: dict[str, Any] = field(
        default_factory=lambda: json.loads(json.dumps(DEFAULT_RULES))
    )
    theme: str = "dark"

    # ------------------------------------------------------------------
    def name_for(self, shift_type: ShiftType) -> str:
        return self.names.get(shift_type.value) or DEFAULT_NAMES[shift_type]

    def reminder_for(self, shift_type: ShiftType) -> int | None:
        cfg = self.reminders.get(shift_type.value) or {}
        if cfg.get("enabled"):
            return int(cfg.get("minutes", 0))
        return None

    def display_for(self, shift_type: ShiftType) -> str:
        return self.display.get(shift_type.value, DEFAULT_DISPLAY[shift_type.value])

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_id": self.backend_id,
            "calendar_name": self.calendar_name,
            "names": self.names,
            "reminders": self.reminders,
            "include_vrij": self.include_vrij,
            "include_afspraken": self.include_afspraken,
            "display": self.display,
            "rules": self.rules,
            "theme": self.theme,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        s = cls()
        for key in s.to_dict():
            if key in data and data[key] is not None:
                setattr(s, key, data[key])
        # Migrate the old vrij_as_all_day flag into the display map.
        if "vrij_as_all_day" in data and "display" not in data:
            s.display[ShiftType.VRIJ.value] = (
                "all_day" if data["vrij_as_all_day"] else "timed"
            )
        # Merge in any missing defaults (forward compatibility).
        for t, n in DEFAULT_NAMES.items():
            s.names.setdefault(t.value, n)
        for t in ShiftType:
            s.reminders.setdefault(t.value, dict(DEFAULT_REMINDERS[t.value]))
            s.display.setdefault(t.value, DEFAULT_DISPLAY[t.value])
        s.rules.setdefault("min_shift_hours", DEFAULT_RULES["min_shift_hours"])
        return s

    # ------------------------------------------------------------------
    def save(self, path: Path | None = None) -> Path:
        p = path or settings_path()
        p.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return p

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        p = path or settings_path()
        if p.exists():
            try:
                return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
        return cls()
