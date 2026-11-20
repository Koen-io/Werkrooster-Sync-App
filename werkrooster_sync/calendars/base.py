"""Abstract calendar backend interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from ..core.models import Shift


class CalendarError(Exception):
    """Raised when a calendar operation fails."""


@dataclass
class AgendaItem:
    """A complete calendar item, as read from or written to a calendar."""

    native_id: str = ""  # the calendar's own id for the item ("" = new)
    title: str = ""
    start: datetime = datetime.min
    end: datetime = datetime.min
    all_day: bool = False
    notes: str = ""
    location: str = ""
    #: Only used when an item is added; afterwards the reminder is the user's.
    reminder_minutes: int | None = None


class CalendarBackend(ABC):
    """A destination that shifts can be synced to."""

    #: Stable identifier stored in settings.
    id: str = ""
    #: Human readable name shown in the settings dialog.
    label: str = ""

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this backend can be used on the current machine."""

    def begin(self, calendar_name: str) -> None:
        """Called once before a sync run starts. Optional hook."""

    def finalize(self) -> None:
        """Called once after a sync run completes. Optional hook."""

    @abstractmethod
    def list_calendars(self) -> list[str]:
        """Names of calendars the user can pick as sync target."""

    @abstractmethod
    def add_shift(self, calendar_name: str, shift: Shift) -> None:
        """Create one calendar item for *shift* in *calendar_name*."""

    #: Whether this backend can see the target calendar at all. False for
    #: export-style backends: duplicate checking and removal then have to
    #: happen in the receiving calendar app.
    can_inspect_calendar: bool = True

    # ------------------------------------------------------------------
    # Version 2: complete items, addressed by the calendar's own ids.
    # *key* is the fixed id of the calendar itself; when it is given the
    # calendar is looked up by that id and never by its name alone.
    # ------------------------------------------------------------------
    def calendars(self) -> list[tuple[str, str]]:
        """All calendars as (name, key); key is "" when there is no fixed id."""
        return [(name, "") for name in self.list_calendars()]

    def read_items(self, name: str, key: str, start: datetime, end: datetime) -> list[AgendaItem]:
        raise CalendarError("Deze koppeling kan de agenda niet inzien.")

    def add_item(self, name: str, key: str, item: AgendaItem) -> str:
        """Add *item*; returns the calendar's own id of the new item."""
        raise CalendarError("Deze koppeling kan niet toevoegen.")

    def update_item(self, name: str, key: str, item: AgendaItem) -> None:
        """Set title, times and notes of the item with ``item.native_id``.
        Reminder, colour and location are left as the user has them."""
        raise CalendarError("Deze koppeling kan niet aanpassen.")

    def delete_item(self, name: str, key: str, native_id: str) -> None:
        raise CalendarError("Deze koppeling kan niet verwijderen.")
