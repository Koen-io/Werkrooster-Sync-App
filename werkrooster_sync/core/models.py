"""Core data models for Werkrooster Sync."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ShiftType(str, Enum):
    """The five shift categories used by the roster, plus 'afspraak' for
    roster items that are not a whole shift (meetings, courses, …)."""

    VRIJ = "vrij"
    OCHTEND = "ochtend"
    LAAT = "laat"
    NACHT = "nacht"
    DIENST = "dienst"
    AFSPRAAK = "afspraak"
    #: Roster noise that should never reach the calendar (e.g. [Rust] blocks).
    NEGEREN = "negeren"

    @classmethod
    def ordered(cls) -> list["ShiftType"]:
        return [
            cls.VRIJ,
            cls.OCHTEND,
            cls.LAAT,
            cls.NACHT,
            cls.DIENST,
            cls.AFSPRAAK,
            cls.NEGEREN,
        ]


#: Default display names for calendar items, per shift type.
#: For AFSPRAAK the original title from the roster is kept; this value is
#: only the fallback when that title is empty.
DEFAULT_NAMES: dict[ShiftType, str] = {
    ShiftType.VRIJ: "Vrij",
    ShiftType.OCHTEND: "Ochtend",
    ShiftType.LAAT: "Laat",
    ShiftType.NACHT: "Nacht",
    ShiftType.DIENST: "Dienst",
    ShiftType.AFSPRAAK: "Afspraak",
    ShiftType.NEGEREN: "Genegeerd",
}


# ----------------------------------------------------------------------
# Sync-ID marker
#
# Every calendar item the app creates gets an invisible tag in its
# notes/description: "[WerkroosterSync:abc123def456]". The ID is derived from
# the roster event itself (its UID, or title+times as fallback), so importing
# the same roster again yields the same ID. That lets the app recognise items
# it created earlier even when the user has renamed them or a different
# colleague's copy of the app does the import.
# ----------------------------------------------------------------------
MARKER_RE = re.compile(r"\[WerkroosterSync:([0-9a-f]{12})\]")


def make_sync_id(uid: str, summary: str, start: datetime, end: datetime) -> str:
    # Deliberately date-based (not time-based): roster exports hide the real
    # times in the title, and extracting those is a setting — the ID must not
    # change when that setting changes.
    basis = uid.strip() or summary.strip().casefold()
    raw = f"{basis}|{start:%Y%m%d}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def marker_for(sync_id: str) -> str:
    return f"[WerkroosterSync:{sync_id}]"


def extract_sync_ids(text: str) -> list[str]:
    return MARKER_RE.findall(text or "")


@dataclass
class Shift:
    """A single roster entry parsed from the .ics file."""

    start: datetime
    end: datetime
    original_summary: str
    shift_type: ShiftType = ShiftType.DIENST
    display_name: str = ""
    all_day: bool = False
    location: str = ""
    description: str = ""
    uid: str = ""
    reminder_minutes: Optional[int] = None  # None = no reminder
    sync_id: str = ""
    already_imported: bool = False  # set by the automatic duplicate check

    @property
    def dedupe_key(self) -> tuple[str, str]:
        """Legacy duplicate key: normalized title + start timestamp. Used as
        fallback for calendar items that predate the sync-ID marker."""
        return (self.display_name.strip().casefold(), self.start.strftime("%Y%m%d%H%M"))


@dataclass
class SyncReport:
    """Result of a synchronisation run."""

    added: list[Shift] = field(default_factory=list)
    skipped_existing: list[Shift] = field(default_factory=list)
    skipped_by_settings: list[Shift] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors
