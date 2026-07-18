"""Abstract calendar backend interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from ..core.models import Shift


class CalendarError(Exception):
    """Raised when a calendar operation fails."""


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

    def scan_existing(
        self, calendar_name: str, start: datetime, end: datetime
    ) -> tuple[list[tuple[str, str]], set[str]]:
        """One combined scan: (dedupe keys, sync-IDs) of events in the range.

        Backends override this when both can be fetched in a single query.
        """
        return (
            self.existing_keys_list(calendar_name, start, end),
            self.existing_sync_ids(calendar_name, start, end),
        )

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
