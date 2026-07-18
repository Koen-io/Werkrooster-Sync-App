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

    def existing_keys(
        self, calendar_name: str, start: datetime, end: datetime
    ) -> set[tuple[str, str]]:
        return set(self.existing_keys_list(calendar_name, start, end))

    def remove_duplicates(self, calendar_name: str, start: datetime, end: datetime) -> int:
        """Delete surplus copies of duplicated events. Returns number removed.

        Optional: backends that cannot delete raise CalendarError.
        """
        raise CalendarError(f"{self.label} ondersteunt geen verwijderen van dubbele items.")
