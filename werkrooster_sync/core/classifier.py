"""Classify roster items into vrij / ochtend / laat / nacht / dienst / afspraak.

Classification is rule based and fully configurable via Settings:

1. **Keywords** — if the original event summary contains a configured keyword
   for a shift type, that type wins. Vrij keywords are checked first so a free
   day is never mistaken for a work shift.
2. **All-day events** without a matching work keyword are treated as *vrij*.
3. **Duration** — a timed item without a keyword that is shorter than
   ``min_shift_hours`` (default 5) is not a whole shift: it becomes an
   *afspraak* that keeps its original title and exact times.
4. **Start-hour windows** — otherwise the hour the shift starts decides:
   nacht (20:00–04:59), ochtend (05:00–11:59), laat (12:00–19:59) by default.
5. Anything that still has no match becomes *dienst*.
"""
from __future__ import annotations

from .models import Shift, ShiftType, make_sync_id
from .settings import Settings


def _keyword_match(summary: str, keywords: list[str]) -> bool:
    s = summary.casefold()
    return any(k.casefold() in s for k in keywords if k.strip())


def classify(shift: Shift, settings: Settings) -> ShiftType:
    """Determine the shift type for a single roster item."""
    keywords = settings.rules.get("keywords", {})

    if _keyword_match(shift.original_summary, keywords.get(ShiftType.VRIJ.value, [])):
        return ShiftType.VRIJ

    for t in (ShiftType.OCHTEND, ShiftType.LAAT, ShiftType.NACHT, ShiftType.DIENST):
        if _keyword_match(shift.original_summary, keywords.get(t.value, [])):
            return t

    if shift.all_day:
        return ShiftType.VRIJ

    duration_hours = (shift.end - shift.start).total_seconds() / 3600
    min_hours = float(settings.rules.get("min_shift_hours", 5))
    if duration_hours < min_hours:
        return ShiftType.AFSPRAAK

    hour = shift.start.hour
    windows = settings.rules.get("time_windows", {})
    for type_name, window in windows.items():
        try:
            lo, hi = int(window[0]), int(window[1])
            t = ShiftType(type_name)
        except (ValueError, IndexError, TypeError):
            continue
        if lo <= hi:
            if lo <= hour < hi:
                return t
        else:  # window wraps midnight, e.g. [20, 5]
            if hour >= lo or hour < hi:
                return t

    return ShiftType.DIENST


def apply_classification(shifts: list[Shift], settings: Settings) -> list[Shift]:
    """Classify every item and apply name, reminder, display mode and sync-ID."""
    for shift in shifts:
        shift.shift_type = classify(shift, settings)
        if shift.shift_type == ShiftType.AFSPRAAK:
            # Appointments keep their own title from the roster.
            shift.display_name = shift.original_summary or settings.name_for(
                ShiftType.AFSPRAAK
            )
        else:
            shift.display_name = settings.name_for(shift.shift_type)
        shift.reminder_minutes = settings.reminder_for(shift.shift_type)
        if settings.display_for(shift.shift_type) == "all_day":
            shift.all_day = True
        # The sync-ID is derived from the roster event itself (not from the
        # display name), so a re-import recognises the item even after the
        # user renamed it in their calendar.
        shift.sync_id = make_sync_id(
            shift.uid, shift.original_summary, shift.start, shift.end
        )
    return shifts
