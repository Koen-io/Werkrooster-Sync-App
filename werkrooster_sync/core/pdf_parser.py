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

Since 2.0 the roster is read **per column** (see :func:`_read_columns`): the
column positions come from the header row of the pdf itself, so time blocks,
breaks and activities no longer leak into the soort. The line-based reader
described above is kept as the fallback ("noodstand") for a pdf whose header
row is not recognised.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
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


def _extract_lines(reader) -> tuple[list[str], bool]:
    try:
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
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


def _parse_lines(lines: list[str], is_concept: bool, settings: Settings) -> list[Shift]:
    """Fallback reader: line based, as in version 1."""

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
            shift.roster_date = start.date()
            shifts.append(shift)

    shifts.sort(key=lambda s: s.start)
    return shifts


# ----------------------------------------------------------------------
# Reading per column (2.0)
# ----------------------------------------------------------------------
_FULL_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_ONLY_TIME_RANGE_RE = re.compile(r"^\d{1,2}[:.]\d{2}\s*[-–—]\s*\d{1,2}[:.]\d{2}$")
#: A soort cell is a name followed by exactly one time range.
_SOORT_RE = re.compile(r"^\S.*?\s\d{1,2}[:.]\d{2}\s*[-–—]\s*\d{1,2}[:.]\d{2}$")
#: Words of the second line of the header row.
_HEADER_LINE_2 = {"dienst", "gebied", "snelcode"}
_PAGE_RE = re.compile(r"Pagina\s+(\d+)\s+van\s+(\d+)", re.IGNORECASE)
_PERIOD_RE = re.compile(r"(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})")

#: Known columns, recognised by how their header text starts.
_COLUMNS = ("dag", "datum", "soort", "tijdstippen", "noodhulp", "project",
            "activiteit", "resultaat", "ibt", "locatie")
#: The header row must at least hold these, each as its own piece of text.
_REQUIRED = {"dag", "datum", "soort", "tijdstippen"}
#: How a block column shows up in the note of the calendar item.
_LABELS = {"noodhulp": "Noodhulpdienst", "resultaat": "Resultaatgebied",
           "ibt": "IBT-snelcode", "locatie": "Locatie"}
_TIJD_IN_MEMO_RE = re.compile(
    r"\(?\s*\d{1,2}[:.]\d{2}\s*[-–—]\s*\d{1,2}[:.]\d{2}\s*(?:uur)?\s*\)?", re.IGNORECASE)
_MEMO_LABEL_RE = re.compile(r"^(dienst|activiteit)\s*:", re.IGNORECASE)
#: "DIENST 22:30-00:00" / "DIENST 00:00-07:30": a night split at midnight.
_TOT_MIDDERNACHT_RE = re.compile(r"^(.*\S)\s+(\d{1,2}[:.]\d{2})\s*[-–—]\s*(?:00|24)[:.]00$")
_VANAF_MIDDERNACHT_RE = re.compile(r"^(.*\S)\s+00[:.]00\s*[-–—]\s*(\d{1,2}[:.]\d{2})$")
_X_TOL = 3.0  # points a cell may start left of its column header
_Y_TOL = 2.0  # points within which pieces of text are on the same line


@dataclass
class Roster:
    """Everything read from one roster pdf."""

    shifts: list[Shift] = field(default_factory=list)
    is_concept: bool = False
    #: True when the pdf was read per column; False = fallback reader, in
    #: which the app may only add items, never change or remove them.
    per_kolom: bool = False
    periode: tuple[date, date] | None = None
    personeelsnummer: str = ""
    gegenereerd: datetime | None = None
    #: All pages read and every day of the period present.
    volledig: bool = False
    #: Lines the reader could not place, per roster day (None = no day).
    onbegrepen: dict[date | None, list[str]] = field(default_factory=dict)
    #: Messages for the user, in plain Dutch.
    meldingen: list[str] = field(default_factory=list)

    def mag_aanpassen(self, dag: date) -> bool:
        """May items on *dag* be changed or removed based on this roster?"""
        return (
            self.per_kolom
            and self.volledig
            and self.periode is not None
            and self.periode[0] <= dag <= self.periode[1]
            and None not in self.onbegrepen
            and dag not in self.onbegrepen
        )


class _GeenKop(Exception):
    """The header row of the table was not recognised."""


@dataclass
class _Dienst:
    soort: str
    blokken: list[dict[str, str]] = field(default_factory=list)
    memos: list[str] = field(default_factory=list)


def _parse_date(text: str) -> date | None:
    m = _FULL_DATE_RE.match(text.strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _page_rows(page) -> list[list[tuple[float, str]]]:
    """The text of a page as rows (top to bottom) of (x, text) pieces."""
    pieces: list[tuple[float, float, str]] = []

    def visit(text, cm, tm, font, size):
        if text.strip():
            pieces.append((float(tm[4]), float(tm[5]), " ".join(text.split())))

    page.extract_text(visitor_text=visit)
    pieces.sort(key=lambda p: (-p[1], p[0]))
    rows: list[list[tuple[float, str]]] = []
    row_y = None
    for x, y, text in pieces:
        if row_y is None or row_y - y > _Y_TOL:
            rows.append([])
            row_y = y
        rows[-1].append((x, text))
    for row in rows:
        row.sort(key=lambda piece: piece[0])  # stable: keeps pdf order
    return rows


def _find_header(rows) -> tuple[int, list[tuple[float, str]]] | None:
    """Index of the header row and its columns as sorted (x, name)."""
    for i, row in enumerate(rows):
        cols = []
        for x, text in row:
            low = text.casefold()
            name = next((c for c in _COLUMNS if low.startswith(c)), None)
            # An unknown header still is a column; its text ends up in the note.
            cols.append((x, name or text))
        if _REQUIRED <= {name for _, name in cols}:
            return i, sorted(cols)
    return None


def _row_text(row) -> str:
    return " ".join(text for _, text in row)


def _cells(row, cols) -> dict[str, str]:
    out: dict[str, str] = {}
    for x, text in row:
        name = cols[0][1]
        for cx, cname in cols:
            if cx <= x + _X_TOL:
                name = cname
        out[name] = f"{out[name]} {text}" if name in out else text
    return out


def _read_columns(reader, settings: Settings) -> Roster:
    roster = Roster(per_kolom=True)
    dagen: dict[date, list[_Dienst]] = {}
    current: date | None = None
    cols = None
    paginas: list[tuple[int, int]] = []

    def onbegrepen(dag: date | None, row) -> None:
        roster.onbegrepen.setdefault(dag, []).append(_row_text(row))

    # A memo can run over several lines; the lines after "Memo:" sit alone in
    # the Dag column. They are collected here and added once the memo ends.
    memo: list = []  # [dienst, [regels]] while a memo is being read

    def memo_klaar() -> None:
        if memo:
            dienst, regels = memo
            for regel in regels:
                if regel and regel not in dienst.memos:
                    dienst.memos.append(regel)
            memo.clear()

    for page_no, page in enumerate(reader.pages, start=1):
        rows = _page_rows(page)
        found = _find_header(rows)
        if found is None:
            if cols is None:
                raise _GeenKop()
            body = rows  # continuation page without a header row
        else:
            head_idx, cols = found
            if page_no == 1:
                _read_report_head(rows[:head_idx], roster)
            elif head_idx:
                for row in rows[:head_idx]:
                    onbegrepen(None, row)
            body = rows[head_idx + 1:]
            # Second line of the header ("dienst", "gebied", "snelcode").
            if body and {t.casefold() for _, t in body[0]} <= _HEADER_LINE_2:
                body = body[1:]

        first_date_row = True
        for row in body:
            text = _row_text(row)
            m = _PAGE_RE.search(text)
            if m or text.casefold().startswith("afgedrukt op"):
                if m:
                    paginas.append((int(m.group(1)), int(m.group(2))))
                continue
            cells = _cells(row, cols)
            dag_cel = cells.pop("dag", "")
            datum_cel = cells.pop("datum", "")
            soort = cells.pop("soort", "")

            if (memo and dag_cel and not (datum_cel or soort or cells)
                    and not dag_cel.casefold().startswith("memo:")
                    # a lone day name means the date was missed: not a memo
                    and dag_cel.split()[0].casefold() not in DAY_NAMES):
                regels = memo[1]
                # A line that starts a new label ("Activiteit: …") is its own
                # memo line; anything else continues the sentence above it.
                if _MEMO_LABEL_RE.match(dag_cel):
                    regels.append(dag_cel)
                else:
                    regels[-1] = f"{regels[-1]} {dag_cel}"
                continue
            memo_klaar()

            if dag_cel.casefold().startswith("memo:"):
                if datum_cel or soort or cells or current is None or not dagen[current]:
                    onbegrepen(current, row)
                else:
                    memo[:] = [dagen[current][-1], [dag_cel[5:].strip()]]
                continue

            if datum_cel:
                dag = _parse_date(datum_cel)
                at_page_top, first_date_row = first_date_row and page_no > 1, False
                if (dag is None
                        or dag_cel.casefold() != DAY_NAMES[dag.weekday()]
                        or (soort and not _SOORT_RE.match(soort))
                        or (current is not None and dag < current)
                        # The same date twice is only normal right after a
                        # page break, where the running day is repeated.
                        or (dag == current and not at_page_top)):
                    onbegrepen(current if dag is None or current and dag <= current
                               else dag, row)
                    if dag is not None and (current is None or dag > current):
                        current = dag
                        dagen.setdefault(dag, [])
                    continue
                current = dag
                diensten = dagen.setdefault(dag, [])
                # A day that runs over a page break repeats its date and soort
                # at the top of the next page: same shift, not a second one.
                if soort and not (at_page_top and diensten
                                  and diensten[-1].soort == soort):
                    diensten.append(_Dienst(soort))
            elif dag_cel or current is None or (soort and not _SOORT_RE.match(soort)):
                onbegrepen(current, row)
                continue
            elif soort:
                dagen[current].append(_Dienst(soort))

            if not cells:
                if not (datum_cel or soort):
                    onbegrepen(current, row)
                continue
            if not dagen[current]:
                onbegrepen(current, row)
                continue
            dienst = dagen[current][-1]
            tijd = cells.get("tijdstippen", "")
            if tijd and _ONLY_TIME_RANGE_RE.match(tijd):
                dienst.blokken.append(cells)
            else:
                onbegrepen(current, row)

    memo_klaar()
    if not dagen:
        raise PdfParseError("Geen roosterdagen gevonden in deze PDF.")

    _check_complete(roster, dagen, paginas, len(reader.pages))
    for dag, regels in roster.onbegrepen.items():
        waar = f"op {dag:%d-%m-%Y}" if dag else "buiten de dagen"
        for regel in regels:
            roster.meldingen.append(f"Regel {waar} niet begrepen: “{regel}”")

    _plak_nachtdiensten(dagen, roster, settings)
    empty_day_is_vrij = bool((settings.rules or {}).get("empty_day_is_vrij", True))
    for dag in sorted(dagen):
        start = datetime(dag.year, dag.month, dag.day)
        diensten = dagen[dag]
        if empty_day_is_vrij and not diensten and dag not in roster.onbegrepen:
            diensten = [_Dienst("Vrij")]
        for dienst in diensten:
            # "Dienst: Maintenance PXF" first, then "Activiteit: SB Rotterdam";
            # times in a memo ("(08:00-17:30 uur)") are left out of the title.
            activiteiten = [_TIJD_IN_MEMO_RE.sub(" ", m.split(":", 1)[1]).strip(" :")
                            for soort in ("dienst:", "activiteit:")
                            for m in dienst.memos if m.casefold().startswith(soort)]
            shift = Shift(
                start=start,
                end=start + timedelta(days=1),
                original_summary=dienst.soort,
                all_day=True,
                description="\n".join(dienst.memos + [_block_line(b) for b in dienst.blokken]),
                info=" / ".join(dict.fromkeys(a for a in activiteiten if a)),
            )
            shift.is_concept = roster.is_concept
            shift.roster_date = dag
            roster.shifts.append(shift)
    roster.shifts.sort(key=lambda s: s.start)
    return roster


def _plak_nachtdiensten(dagen: dict[date, list[_Dienst]], roster: Roster,
                        settings: Settings) -> None:
    """BVCM splits a night shift at midnight: "DIENST 22:30-00:00" on one day
    and "DIENST 00:00-07:30" on the next. Make that one shift on the first day
    ("DIENST 22:30-07:30"), but only when both days were read without doubt."""
    from .classifier import _keyword_category  # here: classifier imports models only
    keywords = (settings.rules or {}).get("keywords", {})
    for dag in sorted(dagen):
        volgende = dag + timedelta(days=1)
        if (not dagen[dag] or not dagen.get(volgende)
                or dag in roster.onbegrepen or volgende in roster.onbegrepen):
            continue
        a, b = dagen[dag][-1], dagen[volgende][0]
        ma, mb = _TOT_MIDDERNACHT_RE.match(a.soort), _VANAF_MIDDERNACHT_RE.match(b.soort)
        if not (ma and mb and ma.group(1) == mb.group(1)):
            continue
        # Only work shifts: no [Rust], verlof or appointment blocks.
        if _keyword_category(a.soort, keywords) in ("negeren", "vrij", "afspraak"):
            continue
        a.soort = f"{ma.group(1)} {ma.group(2)}-{mb.group(2)}"
        a.blokken += b.blokken
        a.memos += [m for m in b.memos if m not in a.memos]
        dagen[volgende].pop(0)


def _block_line(blok: dict[str, str]) -> str:
    """One time block as a line for the note: time, what, and labelled extras."""
    parts = [blok.get("tijdstippen", "")]
    parts += [blok[c] for c in ("activiteit", "project") if blok.get(c)]
    line = " ".join(p for p in parts if p)
    extras = [f"{_LABELS.get(name, name)}: {value}" for name, value in blok.items()
              if name not in ("tijdstippen", "activiteit", "project") and value]
    return " · ".join([line] + extras) if line else " · ".join(extras)


def _read_report_head(rows, roster: Roster) -> None:
    """Period, employee number, generation moment and concept/definitive."""
    for row in rows:
        text = _row_text(row)
        low = text.casefold()
        if "concept" in low:
            roster.is_concept = True
        if low.startswith("periode"):
            m = _PERIOD_RE.search(text)
            first = _parse_date(m.group(1)) if m else None
            last = _parse_date(m.group(2)) if m else None
            if first and last and first <= last:
                roster.periode = (first, last)
        elif low.startswith("medewerker:"):
            # Only a number directly after "Medewerker:" counts; without it
            # the app cannot tell whose items are whose and will only add.
            m = re.match(r"medewerker:\s*(\d{4,12})\b", low)
            roster.personeelsnummer = m.group(1) if m else ""
        elif "generatiedatum" in low:
            m = re.search(r"(\d{2})/(\d{2})/(\d{4})", text)
            tm = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
            if m:
                try:
                    roster.gegenereerd = datetime(
                        int(m.group(3)), int(m.group(2)), int(m.group(1)),
                        int(tm.group(1)) if tm else 0, int(tm.group(2)) if tm else 0)
                except ValueError:
                    pass


def _check_complete(roster: Roster, dagen, paginas, page_count: int) -> None:
    """Were all pages read and is every day of the period present?"""
    problemen = []
    totals = {total for _, total in paginas}
    if (len(paginas) != page_count or totals != {page_count}
            or [n for n, _ in paginas] != list(range(1, page_count + 1))):
        problemen.append("de paginanummering klopt niet (ontbreekt er een pagina?)")
    if roster.periode is None:
        problemen.append("de periode staat niet in de kop")
    else:
        first, last = roster.periode
        if (last - first).days > 400:
            problemen.append("de periode in de kop is onwaarschijnlijk lang")
        else:
            verwacht = {first + timedelta(days=i) for i in range((last - first).days + 1)}
            missend = sorted(verwacht - set(dagen))
            if missend:
                problemen.append(
                    f"{len(missend)} dag(en) van de periode ontbreken, "
                    f"waaronder {missend[0]:%d-%m-%Y}")
            # BVCM lists a rest block that runs past the last day under the
            # day after the period. That day belongs to the next roster.
            for dag in set(dagen) - verwacht:
                del dagen[dag]
                if dag in roster.onbegrepen:
                    roster.onbegrepen.setdefault(None, []).extend(roster.onbegrepen.pop(dag))
    roster.volledig = not problemen
    if problemen:
        roster.meldingen.append(
            "Dit rooster lijkt niet compleet: " + "; ".join(problemen)
            + ". De app voegt alleen toe en past niets aan.")


def read_roster(path: str | Path, settings: Settings | None = None) -> Roster:
    """Read the roster pdf at *path*, per column when the header row is
    recognised and with the line-based fallback reader otherwise."""
    settings = settings or Settings()
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise PdfParseError("PDF-ondersteuning ontbreekt (pypdf niet geïnstalleerd).") from exc
    try:
        reader = PdfReader(str(path))
        lines, is_concept = _extract_lines(reader)
        try:
            return _read_columns(reader, settings)
        except _GeenKop:
            pass
    except PdfParseError:
        raise
    except Exception as exc:
        raise PdfParseError(f"Kan PDF niet lezen: {exc}") from exc
    return Roster(
        shifts=_parse_lines(lines, is_concept, settings),
        is_concept=is_concept,
        meldingen=[
            "De kolommen van dit rooster zijn niet herkend. De app leest het "
            "op de oude manier en voegt alleen toe; er wordt niets aangepast "
            "of verwijderd. Controleer het resultaat extra goed."
        ],
    )


def parse_pdf(path: str | Path, settings: Settings | None = None) -> list[Shift]:
    """Parse *path* and return all roster entries, sorted by start time."""
    return read_roster(path, settings).shifts
