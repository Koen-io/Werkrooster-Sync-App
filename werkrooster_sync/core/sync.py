"""Synchronisation engine: pushes classified shifts into a calendar backend."""
from __future__ import annotations

from datetime import timedelta

from ..calendars.base import CalendarBackend, CalendarError
from .models import Shift, ShiftType, SyncReport
from .settings import Settings


def prepare_shifts(shifts: list[Shift], settings: Settings) -> tuple[list[Shift], list[Shift]]:
    """Split shifts into (to_sync, skipped_vrij) based on the vrij setting."""
    if settings.include_vrij:
        return list(shifts), []
    to_sync = [s for s in shifts if s.shift_type != ShiftType.VRIJ]
    skipped = [s for s in shifts if s.shift_type == ShiftType.VRIJ]
    return to_sync, skipped


def sync_shifts(
    shifts: list[Shift],
    backend: CalendarBackend,
    settings: Settings,
    progress=None,
) -> SyncReport:
    """Add *shifts* to the backend's target calendar, skipping duplicates.

    ``progress`` is an optional callable ``(done, total, message)`` used by the
    UI to show progress.
    """
    report = SyncReport()
    to_sync, report.skipped_vrij = prepare_shifts(shifts, settings)
    if not to_sync:
        return report

    first = min(s.start for s in to_sync) - timedelta(days=1)
    last = max(s.end for s in to_sync) + timedelta(days=1)

    try:
        backend.begin(settings.calendar_name)
        existing = backend.existing_keys(settings.calendar_name, first, last)
    except CalendarError as exc:
        report.errors.append(str(exc))
        return report

    total = len(to_sync)
    for i, shift in enumerate(to_sync, start=1):
        if progress:
            progress(i, total, shift.display_name)
        if shift.dedupe_key in existing:
            report.skipped_existing.append(shift)
            continue
        try:
            backend.add_shift(settings.calendar_name, shift)
            existing.add(shift.dedupe_key)
            report.added.append(shift)
        except CalendarError as exc:
            report.errors.append(f"{shift.display_name} ({shift.start:%d-%m-%Y}): {exc}")

    try:
        backend.finalize()
    except CalendarError as exc:
        report.errors.append(str(exc))

    return report


def find_duplicates(
    backend: CalendarBackend, settings: Settings, days_back: int = 90, days_forward: int = 180
) -> dict[tuple[str, str], int]:
    """Scan the target calendar for items that occur more than once.

    Returns a mapping of dedupe key -> occurrence count (only counts > 1).
    """
    from datetime import datetime

    start = datetime.now() - timedelta(days=days_back)
    end = datetime.now() + timedelta(days=days_forward)
    counts: dict[tuple[str, str], int] = {}
    for key in backend.existing_keys_list(settings.calendar_name, start, end):
        counts[key] = counts.get(key, 0) + 1
    return {k: c for k, c in counts.items() if c > 1}
