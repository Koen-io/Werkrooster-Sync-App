"""Parse the roster .ics file into :class:`Shift` objects."""
from __future__ import annotations

import html
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

from icalendar import Calendar

from .models import Shift


class IcsParseError(Exception):
    """Raised when the .ics file cannot be read or contains no events."""


#: "Informatie: QRA" / "Info: Kustwacht" / "Notitie: …" in the description.
_INFO_RE = re.compile(
    r"(?:informatie|notitie|info)\s*:\s*([^\r\n<]+)", re.IGNORECASE
)


def _extract_info(component) -> str:
    """Pull the Informatie/Notitie value from DESCRIPTION or the HTML
    X-ALT-DESC that BVCM/Outlook exports carry."""
    sources = []
    desc = component.get("DESCRIPTION")
    if desc:
        sources.append(str(desc))
    alt = component.get("X-ALT-DESC")
    if alt:
        text = re.sub(r"<[^>]+>", "\n", str(alt))
        sources.append(html.unescape(text))
    for source in sources:
        for match in _INFO_RE.finditer(source):
            value = match.group(1).strip().strip("\\").strip()
            if value:
                return value
    return ""


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
                info=_extract_info(component),
            )
        )

    if not shifts:
        raise IcsParseError("Geen agenda-items gevonden in dit bestand.")

    shifts.sort(key=lambda s: s.start)
    return shifts
