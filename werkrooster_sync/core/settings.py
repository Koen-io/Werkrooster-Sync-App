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
        # Vrij + all BVCM leave registrations (verlof-soorten).
        ShiftType.VRIJ.value: [
            "vrij",
            "vry",
            "roostervrij",
            "vakantie",
            "verlof",
            "lfu",
            "vr.zondag",
            "vr.zaterdag",
            "feestdag",
            "bver",       # Buitengewoon verlof (BVER_QUARA telt als dienst)
            "bv_sportd",  # Bijzonder verlof sportdag
            "blok_opnll", # Geblokkeerde levensloopgelden
            "cala",       # Calamiteitenverlof
            "caocomp",    # Compensatie niet gewerkte uren
            "geb_verl",   # Aanvullend geboorteverlof
            "onb_verl",   # Onbetaald verlof
            "rver",       # Rouwverlof
            "studie",     # Studieverlof
            "uitdeta",    # Uitdetacheren
            "zorg",       # Zorgverlof
            "zwav",       # Zwangerschapsverlof
        ],
        ShiftType.OCHTEND.value: ["ochtend", "vroeg", "morning", "early"],
        ShiftType.LAAT.value: ["laat", "avond", "late", "evening"],
        ShiftType.NACHT.value: ["nacht", "night"],
        # "dienst" is the fallback category; generic words like "dienst" must
        # not override the start-time rules — shifts get their name from the
        # start time. Only codes that would otherwise be caught by a
        # verlof-keyword belong here (longest matching keyword wins, so
        # "bver_quara" beats the vrij-keyword "bver").
        ShiftType.DIENST.value: ["bver_quara"],
        # Items that keep their own title (with times stripped), like sick
        # leave from the PDF roster ("ZIEK 10:00-17:36" -> "ZIEK") and
        # consignatie (on-call is not a worked shift).
        ShiftType.AFSPRAAK.value: [
            "ziek",
            "cursus",
            "opleiding",
            "training",
            "consig",
            "schors",
            "werkonderb",
        ],
        # Roster noise that should never reach the calendar. [Rust] blocks are
        # the rest periods BVCM exports around every shift; pauzes are breaks
        # inside a shift; birthdays come from Outlook's contacts calendar
        # riding along in the export.
        ShiftType.NEGEREN.value: ["[rust]", "pauze", "verjaardag"],
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
    # Roster exports (BVCM/Outlook) deliver every shift as an all-day event
    # with the real times only in the title ("DIENST 07:00 - 16:00"). When
    # enabled, those times are extracted and the item becomes a real timed
    # shift; "00:00 - 24:00" keeps meaning the whole day.
    "parse_times_from_title": True,
    # Shifts from a concept roster ([C1]/[C2] prefix) get a " (concept)"
    # suffix in the calendar so they are recognisable as not-yet-definitive.
    "mark_concept": True,
    # PDF rosters leave free days empty (definitive) or fill them with a
    # full-day [Rust] block (concept); treat such days as Vrij, matching the
    # ICS export which lists free days explicitly.
    "empty_day_is_vrij": True,
}

DEFAULT_REMINDERS: dict[str, dict[str, Any]] = {
    ShiftType.VRIJ.value: {"enabled": False, "minutes": 0},
    ShiftType.OCHTEND.value: {"enabled": True, "minutes": 60},
    ShiftType.LAAT.value: {"enabled": True, "minutes": 60},
    ShiftType.NACHT.value: {"enabled": True, "minutes": 60},
    ShiftType.DIENST.value: {"enabled": True, "minutes": 60},
    ShiftType.AFSPRAAK.value: {"enabled": True, "minutes": 30},
    ShiftType.NEGEREN.value: {"enabled": False, "minutes": 0},
}

#: How each shift type appears in the calendar: "all_day" (an item at the top
#: of the day) or "timed" (a block at the exact shift times). Only Vrij is a
#: whole-day item; every dienst shows as a block at its exact times.
DEFAULT_DISPLAY: dict[str, str] = {
    ShiftType.VRIJ.value: "all_day",
    ShiftType.OCHTEND.value: "timed",
    ShiftType.LAAT.value: "timed",
    ShiftType.NACHT.value: "timed",
    ShiftType.DIENST.value: "timed",
    ShiftType.AFSPRAAK.value: "timed",
    ShiftType.NEGEREN.value: "timed",
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
    #: During sync: automatically delete an outdated concept item when a new
    #: (definitive or updated concept) shift arrives for the same day.
    replace_concept: bool = True
    #: Append the roster's Informatie/Notitie text to the calendar title,
    #: e.g. "Ochtend - QRA".
    info_in_title: bool = True
    display: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_DISPLAY))
    rules: dict[str, Any] = field(
        default_factory=lambda: json.loads(json.dumps(DEFAULT_RULES))
    )
    theme: str = "glas-donker"

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
            "replace_concept": self.replace_concept,
            "info_in_title": self.info_in_title,
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
        s.rules.setdefault("keywords", {})
        for t in ShiftType:
            s.rules["keywords"].setdefault(
                t.value, list(DEFAULT_RULES["keywords"].get(t.value, []))
            )
        for key in (
            "min_shift_hours",
            "parse_times_from_title",
            "mark_concept",
            "empty_day_is_vrij",
        ):
            s.rules.setdefault(key, DEFAULT_RULES[key])
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
