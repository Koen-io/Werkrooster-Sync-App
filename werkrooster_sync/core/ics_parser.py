"""Parse the roster .ics file into :class:`Shift` objects."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

from icalendar import Calendar

from .models import Shift


class IcsParseError(Exception):
    """Raised when the .ics file cannot be read or contains no events."""


def _as_datetime(value: date | datetime) -> tuple[datetime, bool]:
    """Return (naive local datetime, is_date_only)."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone().replace(tzinfo=None)
        return value, False
    return datetime.combine(value, time.min), True


def parse_ics(path: str | Path) -> list[Shift]:
    """Parse *path* and return all events as shifts, sorted by start time."""
    p = Path(path)
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise IcsParseError(f"Kan bestand niet lezen: {exc}") from exc

    try:
        cal = Calendar.from_ical(raw)
    except Exception as exc:  # icalendar raises various ValueError subclasses
        raise IcsParseError(f"Ongeldig .ics bestand: {exc}") from exc

    shifts: list[Shift] = []
    for component in cal.walk("VEVENT"):
        dtstart = component.get("DTSTART")
        if dtstart is None:
            continue
        start, date_only = _as_datetime(dtstart.dt)

        dtend = component.get("DTEND")
        if dtend is not None:
            end, _ = _as_datetime(dtend.dt)
        else:
            duration = component.get("DURATION")
            if duration is not None:
                end = start + duration.dt
            elif date_only:
                end = start + timedelta(days=1)
            else:
                end = start

        shifts.append(
            Shift(
                start=start,
                end=end,
                original_summary=str(component.get("SUMMARY", "")).strip(),
                all_day=date_only,
                location=str(component.get("LOCATION", "")).strip(),
                description=str(component.get("DESCRIPTION", "")).strip(),
                uid=str(component.get("UID", "")).strip(),
            )
        )

    if not shifts:
        raise IcsParseError("Geen agenda-items gevonden in dit bestand.")

    shifts.sort(key=lambda s: s.start)
    return shifts
