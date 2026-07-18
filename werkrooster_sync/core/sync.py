"""Synchronisation engine: pushes classified shifts into a calendar backend.

Duplicate protection works in two layers:

1. **Sync-ID marker** — every item the app creates carries an invisible
   ``[WerkroosterSync:<id>]`` tag in its notes. The ID is derived from the
   roster event, so a re-import of (an updated copy of) the same roster
   produces the same ID. Items whose ID is already in the calendar are
   skipped — even if the user has renamed them or added a note to the title,
   so those edits are never lost.
2. **Title + start time** — fallback for items created before the marker
   existed (or by the old script).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ..calendars.base import CalendarBackend, CalendarError
from .models import Shift, ShiftType, SyncReport, marker_for
from .settings import Settings


def prepare_shifts(shifts: list[Shift], settings: Settings) -> tuple[list[Shift], list[Shift]]:
    """Split shifts into (to_sync, skipped_by_settings)."""
    to_sync, skipped = [], []
    for s in shifts:
        if s.shift_type == ShiftType.NEGEREN:
            skipped.append(s)
        elif s.shift_type == ShiftType.VRIJ and not settings.include_vrij:
            skipped.append(s)
        elif s.shift_type == ShiftType.AFSPRAAK and not settings.include_afspraken:
            skipped.append(s)
        else:
            to_sync.append(s)
    return to_sync, skipped


def _range(shifts: list[Shift]) -> tuple[datetime, datetime]:
    first = min(s.start for s in shifts) - timedelta(days=1)
    last = max(s.end for s in shifts) + timedelta(days=1)
    return first, last


def mark_already_imported(
    shifts: list[Shift], backend: CalendarBackend, settings: Settings
) -> int:
    """Automatic duplicate check: flag shifts that already exist in the
    target calendar. Returns the number of flagged items."""
    to_check, _ = prepare_shifts(shifts, settings)
    if not to_check:
        return 0
    first, last = _range(to_check)
    keys, ids = backend.scan_existing(settings.calendar_name, first, last)
    key_set = set(keys)
    count = 0
    for s in shifts:
        if s.shift_type == ShiftType.NEGEREN:
            s.already_imported = False
            continue
        s.already_imported = s.sync_id in ids or s.dedupe_key in key_set
        if s.already_imported:
            count += 1
    return count


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
    to_sync, report.skipped_by_settings = prepare_shifts(shifts, settings)
    if not to_sync:
        return report

    first, last = _range(to_sync)

    try:
        backend.begin(settings.calendar_name)
        existing_keys, existing_ids = backend.scan_existing(
            settings.calendar_name, first, last
        )
        existing_key_set = set(existing_keys)
    except CalendarError as exc:
        report.errors.append(str(exc))
        return report

    total = len(to_sync)
    for i, shift in enumerate(to_sync, start=1):
        if progress:
            progress(i, total, shift.display_name)
        if shift.sync_id in existing_ids or shift.dedupe_key in existing_key_set:
            report.skipped_existing.append(shift)
            continue
        marker = marker_for(shift.sync_id)
        if marker not in shift.description:
            shift.description = f"{shift.description}\n\n{marker}".strip()
        try:
            backend.add_shift(settings.calendar_name, shift)
            existing_ids.add(shift.sync_id)
            existing_key_set.add(shift.dedupe_key)
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
    start = datetime.now() - timedelta(days=days_back)
    end = datetime.now() + timedelta(days=days_forward)
    counts: dict[tuple[str, str], int] = {}
    for key in backend.existing_keys_list(settings.calendar_name, start, end):
        counts[key] = counts.get(key, 0) + 1
    return {k: c for k, c in counts.items() if c > 1}
