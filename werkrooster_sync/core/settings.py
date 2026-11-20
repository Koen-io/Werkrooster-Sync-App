"""Persistent app settings.

Settings are stored as JSON in the per-user config directory. Version 1 kept
them next to the app; :func:`settings_path` moves such a file over once.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import DEFAULT_NAMES, ShiftType

APP_NAME = "WerkroosterSync"
log = logging.getLogger(__name__)


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
    d = _user_config_dir()
    d.mkdir(parents=True, exist_ok=True)
    target = d / "settings.json"
    marker = d / "verhuisd.txt"
    if not marker.exists():
        # One-time move from version 1. The file next to the app was the one
        # in use, so it wins; a (stale) file already in the user directory is
        # kept as a backup and not used.
        try:
            portable = _portable_dir() / "settings.json"
            if portable.is_file():
                data = portable.read_bytes()
                if target.exists():
                    os.replace(target, d / "settings.verouderd.json")
                _write_safely(target, data)
            marker.write_text("Instellingen staan sinds versie 2 in deze map.\n",
                              encoding="utf-8")
        except OSError:
            log.exception("Verhuizen van de instellingen mislukt")
    return target


def _write_safely(path: Path, data: bytes) -> None:
    """Write via a temporary file and keep the previous version as backup,
    so a crash halfway never leaves a broken settings file."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    if path.exists():
        os.replace(path, path.with_name(path.name + ".bak"))
    os.replace(tmp, path)


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

def _keyword_keys(keywords: dict[str, list[str]]) -> list[str]:
    return sorted(f"{soort}:{kw}" for soort, kws in keywords.items() for kw in kws)


#: The standard keywords as shipped with version 1. A settings file without
#: ``known_keywords`` was written by version 1 and has seen exactly these.
#: Never change this list; add new keywords to DEFAULT_RULES only.
_V1_KEYWORDS: frozenset[str] = frozenset(_keyword_keys(DEFAULT_RULES["keywords"]))


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


#: De standaard dienstsoorten. Een soort is een tijdvak voor de begintijd van
#: een dienst, met een vast intern id: hernoemen breekt dan niets. De drie
#: standaardsoorten houden de ids "ochtend", "laat" en "nacht"; een eigen
#: soort krijgt een nieuw id. Naam, herinnering en weergave staan, net als
#: bij de andere soorten, in ``names``, ``reminders`` en ``display``.
DEFAULT_DIENSTSOORTEN: list[dict[str, str]] = [
    {"id": ShiftType.OCHTEND.value, "van": "05:00", "tot": "12:00", "kleur": "#FFB340"},
    {"id": ShiftType.LAAT.value, "van": "12:00", "tot": "20:00", "kleur": "#FF8A5C"},
    {"id": ShiftType.NACHT.value, "van": "20:00", "tot": "05:00", "kleur": "#A99CFF"},
]
_TIJD_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def minuten(tijd: str) -> int | None:
    """"07:30" -> 450; None bij een ongeldige tijd."""
    m = _TIJD_RE.match(tijd or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def in_tijdvak(minuut: int, van: str, tot: str) -> bool:
    lo, hi = minuten(van), minuten(tot)
    if lo is None or hi is None or lo == hi:
        return False
    return lo <= minuut < hi if lo < hi else (minuut >= lo or minuut < hi)


def controleer_dienstsoorten(soorten: list[dict], namen: dict[str, str]) -> list[str]:
    """Wat er mis is met een lijst dienstsoorten, in gewone woorden. Leeg = goed."""
    fouten = []
    bezet: dict[int, str] = {}
    for d in soorten:
        naam = (namen.get(d.get("id", "")) or "").strip() or "Een dienstsoort"
        if not (namen.get(d.get("id", "")) or "").strip():
            fouten.append("Elke dienstsoort heeft een naam nodig.")
        lo, hi = minuten(d.get("van", "")), minuten(d.get("tot", ""))
        if lo is None or hi is None:
            fouten.append(f"{naam}: vul de tijden in als uu:mm, bijvoorbeeld 07:00.")
            continue
        if lo == hi:
            fouten.append(f"{naam}: begin en eind van het tijdvak zijn gelijk.")
            continue
        for m in range(1440):
            if in_tijdvak(m, d["van"], d["tot"]):
                if m in bezet and bezet[m] != naam:
                    fouten.append(f"{naam} en {bezet[m]} overlappen.")
                    break
                bezet[m] = naam
    return list(dict.fromkeys(fouten))


def _soorten_uit_v1(rules: dict) -> list[dict[str, str]]:
    """Versie 1 had vaste tijdvakken in hele uren (rules.time_windows)."""
    vakken = rules.get("time_windows") or {}
    uit = []
    for d in DEFAULT_DIENSTSOORTEN:
        vak = vakken.get(d["id"])
        try:
            van, tot = f"{int(vak[0]) % 24:02d}:00", f"{int(vak[1]) % 24:02d}:00"
        except (TypeError, ValueError, IndexError):
            van, tot = d["van"], d["tot"]
        uit.append({**d, "van": van, "tot": tot})
    return uit


def _schoon(key: str, waarde: Any, standaard: Any) -> Any:
    """Een waarde uit settings.json, teruggebracht tot het juiste soort. Een
    kapot of vreemd bestand mag de app niet laten vastlopen: wat niet past,
    valt terug op de standaard (None)."""
    if isinstance(standaard, bool):
        return waarde if isinstance(waarde, bool) else None
    if isinstance(standaard, str):
        return waarde if isinstance(waarde, str) else None
    if key == "names" and isinstance(waarde, dict):
        return {str(k): v for k, v in waarde.items() if isinstance(v, str)}
    if key == "display" and isinstance(waarde, dict):
        return {str(k): v for k, v in waarde.items() if v in ("timed", "all_day")}
    if key == "reminders" and isinstance(waarde, dict):
        uit = {}
        for k, v in waarde.items():
            if isinstance(v, dict) and isinstance(v.get("minutes", 0), int) \
                    and not isinstance(v.get("minutes", 0), bool):
                uit[str(k)] = {"enabled": bool(v.get("enabled")),
                               "minutes": max(0, v.get("minutes", 0))}
        return uit
    if key == "dienstsoorten" and isinstance(waarde, list):
        velden = ("id", "van", "tot", "kleur")
        goed = [{f: d.get(f, "") for f in velden} for d in waarde
                if isinstance(d, dict) and all(isinstance(d.get(f, ""), str) for f in velden)
                and d.get("id")]
        return goed if goed or not waarde else None  # alles kapot: standaard
    if key == "known_keywords" and isinstance(waarde, list):
        return [k for k in waarde if isinstance(k, str)]
    if key == "rules" and isinstance(waarde, dict):
        rules = json.loads(json.dumps(DEFAULT_RULES))
        kw = waarde.get("keywords")
        if isinstance(kw, dict):
            rules["keywords"] = {str(k): [x for x in v if isinstance(x, str)]
                                 for k, v in kw.items() if isinstance(v, list)}
        for k, v in waarde.items():
            if k != "keywords" and k in rules and type(v) is type(rules[k]):
                rules[k] = v
            elif k == "time_windows" and isinstance(v, dict):
                rules[k] = v
        return rules
    return None


@dataclass
class Settings:
    """All user-adjustable settings."""

    backend_id: str = ""  # empty = auto-select best backend for this platform
    calendar_name: str = ""
    #: The calendar's own fixed id; without it the app only ever adds.
    calendar_key: str = ""
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
    #: Standard keywords this settings file has already been offered. A
    #: keyword that is new in an update is added once; one the user removed
    #: is in this list and therefore stays removed.
    known_keywords: list[str] = field(
        default_factory=lambda: _keyword_keys(DEFAULT_RULES["keywords"])
    )
    dienstsoorten: list[dict[str, str]] = field(
        default_factory=lambda: [dict(d) for d in DEFAULT_DIENSTSOORTEN]
    )

    # ------------------------------------------------------------------
    # "sleutel" is de waarde van een ShiftType of het id van een eigen dienstsoort.
    def name_for(self, shift_type: ShiftType | str) -> str:
        k = getattr(shift_type, "value", shift_type)
        try:
            standaard = DEFAULT_NAMES[ShiftType(k)]
        except ValueError:
            standaard = DEFAULT_NAMES[ShiftType.DIENST]
        return self.names.get(k) or standaard

    def reminder_for(self, shift_type: ShiftType | str) -> int | None:
        k = getattr(shift_type, "value", shift_type)
        cfg = self.reminders.get(k) or DEFAULT_REMINDERS.get(k) \
            or DEFAULT_REMINDERS[ShiftType.DIENST.value]
        if cfg.get("enabled"):
            return int(cfg.get("minutes", 0))
        return None

    def display_for(self, shift_type: ShiftType | str) -> str:
        k = getattr(shift_type, "value", shift_type)
        return self.display.get(k) or DEFAULT_DISPLAY.get(k, "timed")

    def dienstsoort_voor(self, minuut: int) -> str | None:
        """Id van de dienstsoort waarin een begintijd (minuten na middernacht) valt."""
        for d in self.dienstsoorten:
            if in_tijdvak(minuut, d.get("van", ""), d.get("tot", "")):
                return d.get("id")
        return None

    def nieuwe_dienstsoort(self, naam: str, van: str, tot: str, kleur: str = "#8E9BFF") -> str:
        """Voeg een eigen dienstsoort toe; geeft het nieuwe (vaste) id terug."""
        sid = f"soort-{secrets.token_hex(4)}"
        self.dienstsoorten.append({"id": sid, "van": van, "tot": tot, "kleur": kleur})
        self.names[sid] = naam
        self.reminders[sid] = dict(DEFAULT_REMINDERS[ShiftType.DIENST.value])
        self.display[sid] = "timed"
        return sid

    def verwijder_dienstsoort(self, sid: str) -> None:
        self.dienstsoorten = [d for d in self.dienstsoorten if d.get("id") != sid]
        if sid not in {t.value for t in ShiftType}:
            for m in (self.names, self.reminders, self.display, self.rules.get("keywords", {})):
                m.pop(sid, None)

    def onthoud_code(self, code: str, sleutel: str) -> None:
        """Een onbekende code uit het rooster hoort voortaan bij deze soort."""
        kw = code.strip().casefold()
        if kw:
            lijst = self.rules.setdefault("keywords", {}).setdefault(sleutel, [])
            if kw not in lijst:
                lijst.append(kw)

    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_id": self.backend_id,
            "calendar_name": self.calendar_name,
            "calendar_key": self.calendar_key,
            "names": self.names,
            "reminders": self.reminders,
            "include_vrij": self.include_vrij,
            "include_afspraken": self.include_afspraken,
            "replace_concept": self.replace_concept,
            "info_in_title": self.info_in_title,
            "display": self.display,
            "rules": self.rules,
            "theme": self.theme,
            "known_keywords": self.known_keywords,
            "dienstsoorten": self.dienstsoorten,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        s = cls()
        if not isinstance(data, dict):
            data = {}
        for key, standaard in s.to_dict().items():
            if key in data and data[key] is not None:
                waarde = _schoon(key, data[key], standaard)
                if waarde is not None:
                    setattr(s, key, waarde)
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
        # Keywords that are new since this file was written (see known_keywords).
        known = set(data.get("known_keywords") or _V1_KEYWORDS)
        in_use = {kw for kws in s.rules["keywords"].values() for kw in kws}
        for soort, kws in DEFAULT_RULES["keywords"].items():
            for kw in kws:
                if f"{soort}:{kw}" not in known and kw not in in_use:
                    s.rules["keywords"][soort].append(kw)
        s.known_keywords = _keyword_keys(DEFAULT_RULES["keywords"])
        if not isinstance(data.get("dienstsoorten"), list):
            s.dienstsoorten = _soorten_uit_v1(s.rules)
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
        _write_safely(
            p, json.dumps(self.to_dict(), indent=2, ensure_ascii=False).encode("utf-8")
        )
        return p

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        p = path or settings_path()
        # A damaged file falls back on the backup of the previous save.
        for candidate in (p, p.with_name(p.name + ".bak")):
            if not candidate.exists():
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return cls.from_dict(data)
            except (ValueError, OSError, TypeError, AttributeError, KeyError, RecursionError):
                log.exception("Instellingen onleesbaar: %s", candidate.name)
        return cls()
