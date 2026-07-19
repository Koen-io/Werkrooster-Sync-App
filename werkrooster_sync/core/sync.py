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
from .models import CONCEPT_TAG, Shift, ShiftType, SyncReport, marker_for
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
        events = backend.scan_events(settings.calendar_name, first, last)
    except CalendarError as exc:
        report.errors.append(str(exc))
        return report

    existing_ids = {e.sync_id for e in events if e.sync_id}
    existing_key_set = {e.key for e in events}
    concept_by_date: dict[str, list] = {}
    for e in events:
        if e.concept and e.sync_id:
            concept_by_date.setdefault(e.date, []).append(e)

    # ------------------------------------------------------------------
    # Plan: which shifts are new, and which outdated concept items must go.
    # An incoming shift (vrij/ochtend/laat/nacht/dienst — never a loose
    # appointment) replaces the concept items on its day. Only items that
    # carry the app's own concept tag are ever deleted.
    # ------------------------------------------------------------------
    shift_types = {
        ShiftType.VRIJ,
        ShiftType.OCHTEND,
        ShiftType.LAAT,
        ShiftType.NACHT,
        ShiftType.DIENST,
    }
    to_add: list[Shift] = []
    to_delete: set[str] = set()
    for shift in to_sync:
        if shift.sync_id in existing_ids or shift.dedupe_key in existing_key_set:
            report.skipped_existing.append(shift)
            continue
        if settings.replace_concept and shift.shift_type in shift_types:
            day = shift.start.strftime("%Y%m%d")
            outdated = [
                e
                for e in concept_by_date.get(day, [])
                if e.sync_id not in to_delete
            ]
            if outdated:
                to_delete.update(e.sync_id for e in outdated)
                report.replaced.append(shift)
        to_add.append(shift)
        # Register the planned item so an identical copy later in the same
        # file is recognised as a duplicate.
        existing_ids.add(shift.sync_id)
        existing_key_set.add(shift.dedupe_key)

    if to_delete:
        try:
            report.concept_removed = backend.remove_by_sync_ids(
                settings.calendar_name, first, last, to_delete
            )
        except CalendarError as exc:
            report.errors.append(f"Vervangen van conceptdiensten mislukt: {exc}")
            # Do not add the replacements if the old items could not be
            # removed — that would create duplicates.
            replaced_ids = {s.sync_id for s in report.replaced}
            to_add = [s for s in to_add if s.sync_id not in replaced_ids]
            report.replaced = []

    total = len(to_add)
    for i, shift in enumerate(to_add, start=1):
        if progress:
            progress(i, total, shift.display_name)
        marker = marker_for(shift.sync_id)
        if marker not in shift.description:
            shift.description = f"{shift.description}\n\n{marker}".strip()
        if shift.is_concept and CONCEPT_TAG not in shift.description:
            shift.description = f"{shift.description}\n{CONCEPT_TAG}".strip()
        try:
            backend.add_shift(settings.calendar_name, shift)
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
