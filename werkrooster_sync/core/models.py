"""Core data models for Werkrooster Sync."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ShiftType(str, Enum):
    """The five shift categories used by the roster."""

    VRIJ = "vrij"
    OCHTEND = "ochtend"
    LAAT = "laat"
    NACHT = "nacht"
    DIENST = "dienst"

    @classmethod
    def ordered(cls) -> list["ShiftType"]:
        return [cls.VRIJ, cls.OCHTEND, cls.LAAT, cls.NACHT, cls.DIENST]


#: Default display names for calendar items, per shift type.
DEFAULT_NAMES: dict[ShiftType, str] = {
    ShiftType.VRIJ: "Vrij",
    ShiftType.OCHTEND: "Ochtend",
    ShiftType.LAAT: "Laat",
    ShiftType.NACHT: "Nacht",
    ShiftType.DIENST: "Dienst",
}


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

    @property
    def dedupe_key(self) -> tuple[str, str]:
        """Key used to detect duplicates: normalized title + start timestamp."""
        return (self.display_name.strip().casefold(), self.start.strftime("%Y%m%d%H%M"))


@dataclass
class SyncReport:
    """Result of a synchronisation run."""

    added: list[Shift] = field(default_factory=list)
    skipped_existing: list[Shift] = field(default_factory=list)
    skipped_vrij: list[Shift] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors
