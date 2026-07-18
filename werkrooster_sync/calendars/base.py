"""Abstract calendar backend interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from ..core.models import Shift


class CalendarError(Exception):
    """Raised when a calendar operation fails."""


@dataclass
class ExistingEvent:
    """One event found in the target calendar during a scan."""

    title: str  # casefolded
    stamp: str  # yyyymmddhhmm of the start
    sync_id: str = ""  # from the [WerkroosterSync:…] marker, if present
    concept: bool = False  # carries the concept tag (or "(concept)" title)

    @property
    def key(self) -> tuple[str, str]:
        return (self.title, self.stamp)

    @property
    def date(self) -> str:
        return self.stamp[:8]


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

    @abstractmethod
    def existing_keys_list(
        self, calendar_name: str, start: datetime, end: datetime
    ) -> list[tuple[str, str]]:
        """Dedupe keys (title, yyyymmddhhmm) of all events in the range,
        including duplicates."""

    def existing_sync_ids(
        self, calendar_name: str, start: datetime, end: datetime
    ) -> set[str]:
        """Sync-IDs from [WerkroosterSync:…] markers found in event notes.

        Backends that cannot read notes return an empty set; deduplication
        then falls back to title + start time.
        """
        return set()

    def scan_events(
        self, calendar_name: str, start: datetime, end: datetime
    ) -> list[ExistingEvent]:
        """All events in the range as :class:`ExistingEvent` rows.

        The default builds them from the simpler queries; backends override
        this to fetch everything (incl. markers and concept tags) in one go.
        """
        ids = self.existing_sync_ids(calendar_name, start, end)
        events = [
            ExistingEvent(t, s)
            for t, s in self.existing_keys_list(calendar_name, start, end)
        ]
        known = {e.sync_id for e in events if e.sync_id}
        for sync_id in ids - known:
            events.append(ExistingEvent("", "000000000000", sync_id))
        return events

    def scan_existing(
        self, calendar_name: str, start: datetime, end: datetime
    ) -> tuple[list[tuple[str, str]], set[str]]:
        """One combined scan: (dedupe keys, sync-IDs) of events in the range."""
        events = self.scan_events(calendar_name, start, end)
        return (
            [e.key for e in events],
            {e.sync_id for e in events if e.sync_id},
        )

    def remove_by_sync_ids(
        self, calendar_name: str, start: datetime, end: datetime, sync_ids: set[str]
    ) -> int:
        """Delete the app-created events in the range whose marker matches one
        of *sync_ids*. Returns the number removed."""
        raise CalendarError(f"{self.label} kan geen items verwijderen.")

    def remove_duplicates(self, calendar_name: str, start: datetime, end: datetime) -> int:
        """Delete surplus copies of duplicated events. Returns number removed.

        Optional: backends that cannot delete raise CalendarError.
        """
        raise CalendarError(f"{self.label} ondersteunt geen verwijderen van dubbele items.")

    #: Whether this backend can see the target calendar at all. False for
    #: export-style backends: duplicate checking and removal then have to
    #: happen in the receiving calendar app.
    can_inspect_calendar: bool = True

    def count_synced(self, calendar_name: str, start: datetime, end: datetime) -> int:
        """Number of items in the range that were created by this app
        (recognised by their [WerkroosterSync:…] marker)."""
        raise CalendarError(f"{self.label} kan de agenda niet inzien.")

    def remove_synced(self, calendar_name: str, start: datetime, end: datetime) -> int:
        """Delete all items in the range that were created by this app.
        Items the user made themselves are never touched. Returns the
        number removed."""
        raise CalendarError(f"{self.label} kan geen items verwijderen.")
