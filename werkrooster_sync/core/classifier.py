"""Classify roster items into vrij / ochtend / laat / nacht / dienst /
afspraak, or mark them as roster noise to ignore.

The pipeline per item:

0. **Time extraction** — roster exports (BVCM/Outlook) deliver shifts as
   all-day events with the real times only in the title, e.g.
   ``[C1] 12785201 DIENST 07:00 - 16:00``. Those times are pulled out of the
   title and the item becomes a real timed shift ("00:00 - 24:00" keeps
   meaning the whole day). An end time before the start time wraps to the
   next day (night shifts).
1. **Negeren keywords** — items like ``[Rust]`` blocks (the rest periods the
   roster exports around every shift) and birthday events are flagged and
   never synced.
2. **Keywords** — a configured keyword in the title decides the shift type.
   Vrij keywords (vrij, vakantie, verlof, lfu, …) are checked first.
3. **All-day** items without any keyword are treated as regular all-day
   appointments (afspraak) that keep their own title.
4. **Duration** — a timed item without a keyword shorter than
   ``min_shift_hours`` (default 5) is not a whole shift: it becomes an
   *afspraak* at its exact times.
5. **Start-hour windows** — otherwise the start hour decides: nacht
   (20:00–04:59), ochtend (05:00–11:59), laat (12:00–19:59) by default.
6. Anything left becomes *dienst*.

Shifts from a concept roster (``[C1]``/``[C2]`` title prefix) optionally get
a " (concept)" suffix on their calendar name.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta

from .models import Shift, ShiftType, make_sync_id
from .settings import Settings

#: "07:00 - 16:00", "7.30-16.00", "23:00 – 07:30" …
_TIME_RANGE_RE = re.compile(
    r"(\d{1,2})[:.](\d{2})\s*[-–—]\s*(\d{1,2})[:.](\d{2})"
)
_CONCEPT_RE = re.compile(r"^\s*\[c\d+\]", re.IGNORECASE)


def _keyword_match(summary: str, keywords: list[str]) -> bool:
    s = summary.casefold()
    return any(k.casefold() in s for k in keywords if k.strip())


def extract_summary_times(shift: Shift, settings: Settings) -> None:
    """Turn an all-day roster item into a timed one using the times in its
    title. Mutates the shift in place."""
    if not settings.rules.get("parse_times_from_title", True):
        return
    if not shift.all_day:
        return
    m = _TIME_RANGE_RE.search(shift.original_summary)
    if not m:
        return
    h1, m1, h2, m2 = (int(g) for g in m.groups())
    if h1 > 23 or m1 > 59 or h2 > 24 or m2 > 59:
        return
    if (h1, m1) == (0, 0) and (h2 in (0, 24)) and m2 == 0:
        return  # "00:00 - 24:00" really is the whole day
    day = shift.start.date()
    start = datetime.combine(day, time(h1, m1))
    end = datetime.combine(day, time(0 if h2 == 24 else h2, m2))
    if end <= start:
        end += timedelta(days=1)
    shift.start, shift.end, shift.all_day = start, end, False


def classify(shift: Shift, settings: Settings) -> ShiftType:
    """Determine the shift type for a single roster item."""
    keywords = settings.rules.get("keywords", {})

    if _keyword_match(shift.original_summary, keywords.get(ShiftType.NEGEREN.value, [])):
        return ShiftType.NEGEREN

    if _keyword_match(shift.original_summary, keywords.get(ShiftType.VRIJ.value, [])):
        return ShiftType.VRIJ

    for t in (ShiftType.OCHTEND, ShiftType.LAAT, ShiftType.NACHT, ShiftType.DIENST):
        if _keyword_match(shift.original_summary, keywords.get(t.value, [])):
            return t

    if shift.all_day:
        # No keyword and genuinely a whole day: an ordinary all-day
        # appointment (keeps its own title), not a work shift.
        return ShiftType.AFSPRAAK

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
        extract_summary_times(shift, settings)
        shift.shift_type = classify(shift, settings)
        shift.is_concept = bool(_CONCEPT_RE.match(shift.original_summary))

        if shift.shift_type in (ShiftType.AFSPRAAK, ShiftType.NEGEREN):
            # These keep their own title from the roster.
            shift.display_name = shift.original_summary or settings.name_for(
                shift.shift_type
            )
        else:
            shift.display_name = settings.name_for(shift.shift_type)
            if settings.rules.get("mark_concept", True) and _CONCEPT_RE.match(
                shift.original_summary
            ):
                shift.display_name += " (concept)"

        if shift.shift_type == ShiftType.NEGEREN:
            shift.reminder_minutes = None
        else:
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
