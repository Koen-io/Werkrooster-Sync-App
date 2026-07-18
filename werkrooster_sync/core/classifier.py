"""Classify roster items into vrij / ochtend / laat / nacht / dienst /
afspraak, or mark them as roster noise to ignore.

The pipeline per item:

0. **Time extraction** — roster exports (BVCM/Outlook) deliver shifts as
   all-day events with the real times only in the title, e.g.
   ``[C1] 12785201 DIENST 07:00 - 16:00``. Those times are pulled out of the
   title and the item becomes a real timed shift ("00:00 - 24:00" keeps
   meaning the whole day). An end time before the start time wraps to the
   next day (night shifts).
1. **Keywords** — a configured keyword in the title decides the category;
   the longest matching keyword wins across all categories (so the specific
   dienst-code "bver_quara" beats the shorter verlof-keyword "bver").
   Negeren keywords ([Rust], pauze, verjaardag) drop roster noise; vrij
   keywords cover all BVCM verlof registrations (vakantie, verlof, lfu,
   zorg, rver, geb_verl, …); afspraak keywords (ziek, consig, cursus, …)
   keep their own title.
2. **All-day** items without any keyword are treated as regular all-day
   appointments (afspraak) that keep their own title.
3. **Duration** — a timed item without a keyword shorter than
   ``min_shift_hours`` (default 5) is not a whole shift: it becomes an
   *afspraak* at its exact times.
4. **Start-hour windows** — otherwise the start hour decides: nacht
   (20:00–04:59), ochtend (05:00–11:59), laat (12:00–19:59) by default.
   Dienst-codes (A5.x, A6.x, …) deliberately have no keywords: their name
   should come from the start time.
5. Anything left becomes *dienst*.

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


#: Category order used to break ties between equally long keywords.
_KEYWORD_PRIORITY = (
    ShiftType.NEGEREN,
    ShiftType.VRIJ,
    ShiftType.OCHTEND,
    ShiftType.LAAT,
    ShiftType.NACHT,
    ShiftType.DIENST,
    ShiftType.AFSPRAAK,  # e.g. "ziek": keeps its own title
)


def _keyword_category(summary: str, keywords: dict) -> ShiftType | None:
    """The category whose keyword matches the summary.

    The *longest* matching keyword wins across all categories, so a specific
    code like "bver_quara" (dienst) beats the shorter verlof-keyword "bver".
    Ties fall back to the category order above.
    """
    s = summary.casefold()
    best_len, best_type = 0, None
    for t in _KEYWORD_PRIORITY:
        for k in keywords.get(t.value, []):
            k = k.strip().casefold()
            if k and k in s and len(k) > best_len:
                best_len, best_type = len(k), t
    return best_type


def classify(shift: Shift, settings: Settings) -> ShiftType:
    """Determine the shift type for a single roster item."""
    keywords = settings.rules.get("keywords", {})

    matched = _keyword_category(shift.original_summary, keywords)
    if matched is not None:
        return matched

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
        # Keep a concept flag set by the parser (PDF rosters carry it in the
        # document title instead of per-item [C1]/[C2] prefixes).
        shift.is_concept = shift.is_concept or bool(
            _CONCEPT_RE.match(shift.original_summary)
        )

        if shift.shift_type in (ShiftType.AFSPRAAK, ShiftType.NEGEREN):
            # These keep their own title from the roster; for appointments the
            # time range is stripped ("ZIEK 10:00-17:36" -> "ZIEK") since the
            # calendar item itself carries the times.
            title = shift.original_summary
            if shift.shift_type == ShiftType.AFSPRAAK:
                title = _TIME_RANGE_RE.sub("", title)
                title = re.sub(r"\s+", " ", title).strip(" -–—")
            shift.display_name = title or settings.name_for(shift.shift_type)
        else:
            shift.display_name = settings.name_for(shift.shift_type)
            if settings.rules.get("mark_concept", True) and shift.is_concept:
                shift.display_name += " (concept)"

        if shift.shift_type == ShiftType.NEGEREN:
            shift.reminder_minutes = None
        else:
            shift.reminder_minutes = settings.reminder_for(shift.shift_type)
            if settings.display_for(shift.shift_type) == "all_day":
                if not shift.all_day:
                    # Keep the real shift times visible in the item's notes.
                    times = f"Diensttijden: {shift.start:%H:%M}–{shift.end:%H:%M}"
                    if times not in shift.description:
                        shift.description = f"{times}\n{shift.description}".strip()
                shift.all_day = True

        # The sync-ID is derived from the roster event itself (not from the
        # display name), so a re-import recognises the item even after the
        # user renamed it in their calendar.
        shift.sync_id = make_sync_id(
            shift.uid, shift.original_summary, shift.start, shift.end
        )
    return shifts
