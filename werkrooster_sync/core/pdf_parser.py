"""Parse a BVCM "Medewerker Rooster" PDF into :class:`Shift` objects.

The PDF is a day-per-row table. After text extraction the relevant lines look
like (order of date/day name can vary per extractor)::

    18/07/2026Zaterdag [Rust] 00:00-24:00
    20/07/2026Maandag ZIEK 10:00-17:36
    ZIEK 10:00-17:36              <- extra item on the previous day
    Memo: Dienst: uren correctie  <- note for the previous item
    18/07/2026Zaterdag            <- empty day (definitive roster)

Each entry becomes an all-day Shift whose *summary* holds the soort + times
(exactly the format the ICS export uses in its titles), so the normal
classification pipeline — time extraction, keywords, negeren, naming —
applies unchanged.

A "Concept Medewerker Rooster" is recognised by its title; every shift from
it is flagged as concept so the automatic concept replacement works.

Free days: the definitive PDF leaves them empty and the concept PDF fills
them with ``[Rust] 00:00-24:00``. With the ``empty_day_is_vrij`` rule
(default on) such days become a *Vrij* item, matching the ICS export which
lists free days explicitly.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

from .ics_parser import IcsParseError
from .models import Shift
from .settings import Settings

DAY_NAMES = (
    "maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"
)

_DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_TIME_RANGE_RE = re.compile(r"\d{1,2}[:.]\d{2}\s*[-–—]\s*\d{1,2}[:.]\d{2}")

#: Lines that belong to the report chrome, not to the roster itself.
_SKIP_MARKERS = (
    "medewerker rooster",
    "generatiedatum",
    "medewerker:",
    "periode:",
    "aan dit rooster kunnen geen rechten",
    "soort",
    "start-eind",
    "tijdstippen",
    "noodhulp",
    "dienst",
    "project",
    "activiteit",
    "resultaat",
    "gebied",
    "ibt",
    "snelcode",
    "locatie",
    "afgedrukt op",
    "pagina",
)


class PdfParseError(IcsParseError):
    """Raised when the PDF cannot be read as a roster."""


def _extract_lines(path: Path) -> tuple[list[str], bool]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise PdfParseError("PDF-ondersteuning ontbreekt (pypdf niet geïnstalleerd).") from exc

    try:
        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfParseError:
        raise
    except Exception as exc:
        raise PdfParseError(f"Kan PDF niet lezen: {exc}") from exc

    if not text.strip():
        raise PdfParseError(
            "Deze PDF bevat geen leesbare tekst (mogelijk een scan)."
        )
    lowered = text.casefold()
    if "rooster" not in lowered:
        raise PdfParseError("Dit lijkt geen roosterbestand te zijn.")
    # The title ("Concept Medewerker Rooster") and the disclaimer line both
    # sit in the first few lines of page 1.
    head = "\n".join(text.splitlines()[:12]).casefold()
    is_concept = "concept" in head
    return text.splitlines(), is_concept


def _is_chrome(line: str) -> bool:
    low = line.strip().casefold()
    if not low:
        return True
    # A roster row always carries a date, a time range or a day entry; the
    # chrome lines match one of the known header/footer fragments and carry
    # no soort+time information.
    if _TIME_RANGE_RE.search(low):
        return False
    if _DATE_RE.search(low):
        # Dates also occur in chrome ("Periode:", "Afgedrukt op", …).
        return any(m in low for m in _SKIP_MARKERS)
    return True if any(m in low for m in _SKIP_MARKERS) else False


def _clean_entry(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" -–")


def parse_pdf(path: str | Path, settings: Settings | None = None) -> list[Shift]:
    """Parse *path* and return all roster entries, sorted by start time."""
    p = Path(path)
    settings = settings or Settings()
    lines, is_concept = _extract_lines(p)

    days: dict[str, list[str]] = {}  # yyyy-mm-dd -> entry texts
    order: list[str] = []
    memos: dict[int, str] = {}
    entries: list[tuple[str, str]] = []  # (date_iso, entry_text)
    current_date: str | None = None

    for raw in lines:
        line = raw.strip()
        low = line.casefold()
        if low.startswith("memo:"):
            memo = line[5:].strip()
            if memo and entries:
                idx = len(entries) - 1
                memos[idx] = f"{memos.get(idx, '')}\n{memo}".strip()
            continue
        if _is_chrome(line):
            continue

        m = _DATE_RE.search(line)
        if m:
            day, month, year = (int(g) for g in m.groups())
            try:
                date_iso = f"{year:04d}-{month:02d}-{day:02d}"
                datetime(year, month, day)
            except ValueError:
                continue
            current_date = date_iso
            if date_iso not in days:
                days[date_iso] = []
                order.append(date_iso)
            rest = line[: m.start()] + line[m.end():]
            # Strip the day name next to the date — but only as a standalone
            # word, so soorten like "[Vr.zondag]" keep their name intact.
            for name in DAY_NAMES:
                rest = re.sub(
                    rf"(?<![.\w]){name}\b", "", rest, flags=re.IGNORECASE
                )
            entry = _clean_entry(rest)
            if entry:
                days[date_iso].append(entry)
                entries.append((date_iso, entry))
        elif current_date and (_TIME_RANGE_RE.search(line) or line.startswith("[")):
            entry = _clean_entry(line)
            if entry:
                days[current_date].append(entry)
                entries.append((current_date, entry))

    if not order:
        raise PdfParseError("Geen roosterdagen gevonden in deze PDF.")

    empty_day_is_vrij = bool(
        (settings.rules or {}).get("empty_day_is_vrij", True)
    )

    shifts: list[Shift] = []
    memo_by_key: dict[tuple[str, str], str] = {}
    for idx, (date_iso, entry) in enumerate(entries):
        if idx in memos:
            memo_by_key[(date_iso, entry)] = memos[idx]

    for date_iso in order:
        year, month, day = (int(x) for x in date_iso.split("-"))
        start = datetime(year, month, day)
        day_entries = days[date_iso]

        if empty_day_is_vrij and not day_entries:
            # An empty day in the definitive roster is a free day, like the
            # ICS export lists explicitly. Days holding only [Rust] blocks
            # are handled generically after classification.
            day_entries = ["Vrij"]

        for entry in day_entries:
            shift = Shift(
                start=start,
                end=start + timedelta(days=1),
                original_summary=entry,
                all_day=True,
                description=memo_by_key.get((date_iso, entry), ""),
            )
            shift.is_concept = is_concept
            shifts.append(shift)

    shifts.sort(key=lambda s: s.start)
    return shifts
