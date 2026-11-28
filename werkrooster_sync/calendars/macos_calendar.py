"""Apple Calendar backend for macOS, driven through AppleScript (osascript).

Works with every account configured in the Calendar app (iCloud, Google,
Exchange, CalDAV, local), because Calendar itself does the syncing.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta

from ..core.models import Shift
from .base import AgendaItem, CalendarBackend, CalendarError

_SEP = "␟"  # unit separator, will never occur in event titles
_ROW = "␞"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _date_decl(var: str, dt: datetime) -> str:
    """AppleScript that builds a date object without locale-dependent parsing."""
    return (
        f"set {var} to current date\n"
        f"set time of {var} to 0\n"
        f"set day of {var} to 1\n"
        f"set year of {var} to {dt.year}\n"
        f"set month of {var} to {dt.month}\n"
        f"set day of {var} to {dt.day}\n"
        f"set time of {var} to {dt.hour * 3600 + dt.minute * 60}\n"
    )


#: Agenda op macOS 27 weigert ``calendarIdentifier`` (fout -10000). Dan zoekt
#: deze hulp de agenda op naam; een kenmerk uit een oudere macOS werkt zo ook.
_AGENDA_OPZOEKEN = (
    "on wsAgenda(k, n)\n"
    '  tell application "Calendar"\n'
    "    try\n"
    "      return first calendar whose calendarIdentifier is k\n"
    "    end try\n"
    "    return calendar n\n"
    "  end tell\n"
    "end wsAgenda\n"
)


def _eind_voor_agenda(item: AgendaItem) -> datetime:
    """Agenda wil bij een hele-dag-item de laatste dag zelf, niet "de dag erna
    om 0:00" (dat maakt hij soms één, soms twee dagen). De app rekent intern
    met een einde dat net buiten het item valt."""
    if item.end <= item.start:
        return item.start
    if item.all_day:
        return max(item.start, item.end - timedelta(days=1))
    return item.end


def _eind_uit_agenda(start: datetime, eind: datetime, all_day: bool) -> datetime:
    """Omgekeerd: Agenda geeft 23:59:59 op de laatste dag terug."""
    if all_day and eind.time() != datetime.min.time():
        return datetime(eind.year, eind.month, eind.day) + timedelta(days=1)
    if all_day and eind <= start:
        return start + timedelta(days=1)
    return eind


def _run(script: str, timeout: int = 120) -> str:
    if "wsAgenda(" in script:
        script = _AGENDA_OPZOEKEN + script
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise CalendarError("osascript niet gevonden — is dit wel een Mac?") from exc
    except subprocess.TimeoutExpired as exc:
        raise CalendarError("Agenda reageert niet (time-out).") from exc
    if proc.returncode != 0:
        err = proc.stderr.strip() or "onbekende fout"
        if "-1743" in err or "Not authorized" in err:
            raise CalendarError(
                "Geen toegang tot Agenda. Geef toestemming via Systeeminstellingen "
                "→ Privacy en beveiliging → Automatisering."
            )
        raise CalendarError(f"Agenda-fout: {err}")
    return proc.stdout.strip()


class MacCalendarBackend(CalendarBackend):
    id = "apple_calendar"
    label = "Apple Agenda (macOS)"

    def is_available(self) -> bool:
        return sys.platform == "darwin"

    # ------------------------------------------------------------------
    def list_calendars(self) -> list[str]:
        out = _run(
            'set text item delimiters to "' + _SEP + '"\n'
            'tell application "Calendar" to set names to name of every calendar\n'
            "return names as text"
        )
        return [n for n in out.split(_SEP) if n.strip()]

    # ------------------------------------------------------------------
    def add_shift(self, calendar_name: str, shift: Shift) -> None:
        if not calendar_name:
            raise CalendarError("Geen agenda gekozen. Kies eerst een agenda in Instellingen.")
        props = [
            f'summary:"{_esc(shift.display_name)}"',
            "start date:startDate",
            "end date:endDate",
        ]
        if shift.all_day:
            props.append("allday event:true")
        if shift.location:
            props.append(f'location:"{_esc(shift.location)}"')
        if shift.description:
            props.append(f'description:"{_esc(shift.description)}"')

        alarm = ""
        if shift.reminder_minutes is not None:
            alarm = (
                "tell newEvent to make new display alarm at end with properties "
                f"{{trigger interval:-{abs(int(shift.reminder_minutes))}}}\n"
            )

        end = shift.end if shift.end > shift.start else shift.start
        script = (
            _date_decl("startDate", shift.start)
            + _date_decl("endDate", end)
            + f'tell application "Calendar"\n'
            f'  tell calendar "{_esc(calendar_name)}"\n'
            f"    set newEvent to make new event with properties {{{', '.join(props)}}}\n"
            f"    {alarm}"
            f"  end tell\n"
            f"end tell"
        )
        _run(script)

    # ------------------------------------------------------------------
    # Version 2: complete items, addressed by the calendar's own ids
    # ------------------------------------------------------------------
    def calendars(self) -> list[tuple[str, str]]:
        out = _run(
            'set out to ""\n'
            'tell application "Calendar"\n'
            "  repeat with c in calendars\n"
            "    set k to \"\"\n"
            "    try\n"
            "      set k to calendarIdentifier of c\n"
            "    end try\n"
            f'    set out to out & (name of c) & "{_SEP}" & k & "{_ROW}"\n'
            "  end repeat\n"
            "end tell\n"
            "return out"
        )
        result = []
        for row in out.split(_ROW):
            parts = row.split(_SEP)
            if len(parts) == 2 and parts[0].strip():
                naam = parts[0].strip()
                # Geen eigen nummer van Agenda (macOS 27): dan de naam als
                # vast nummer, anders kan de app nooit bijwerken of verwijderen.
                result.append((naam, parts[1].strip() or f"naam:{naam}"))
        return result

    def _cal(self, name: str, key: str) -> str:
        """AppleScript reference to the calendar: by fixed id when known."""
        if key:
            return f'(my wsAgenda("{_esc(key)}", "{_esc(name)}"))'
        if not name:
            raise CalendarError("Geen agenda gekozen. Kies eerst een agenda in Instellingen.")
        return f'calendar "{_esc(name)}"'

    def read_items(self, name: str, key: str, start: datetime, end: datetime) -> list[AgendaItem]:
        def stamp(var: str) -> str:
            return (f"((year of {var}) as text) & \"-\" & ((month of {var}) as integer) & \"-\" & "
                    f"(day of {var}) & \"-\" & (time of {var})")

        out = _run(
            _date_decl("d1", start) + _date_decl("d2", end)
            + 'set out to ""\n'
            'tell application "Calendar"\n'
            f"  tell {self._cal(name, key)}\n"
            "    set evs to every event whose start date ≥ d1 and start date ≤ d2\n"
            "    repeat with e in evs\n"
            "      set sd to start date of e\n"
            "      set ed to end date of e\n"
            '      set desc to ""\n'
            '      set loc to ""\n'
            "      try\n"
            "        set desc to (description of e) as text\n"
            "      end try\n"
            "      try\n"
            "        set loc to (location of e) as text\n"
            "      end try\n"
            '      if desc is "missing value" then set desc to ""\n'
            '      if loc is "missing value" then set loc to ""\n'
            '      set ad to "0"\n'
            '      if allday event of e then set ad to "1"\n'
            f'      set out to out & (uid of e) & "{_SEP}" & (summary of e) & "{_SEP}" & {stamp("sd")} '
            f'& "{_SEP}" & {stamp("ed")} & "{_SEP}" & ad & "{_SEP}" & loc & "{_SEP}" & desc & "{_ROW}"\n'
            "    end repeat\n"
            "  end tell\n"
            "end tell\n"
            "return out",
            timeout=300,
        )

        def moment(text: str) -> datetime:
            y, m, d, secs = (int(float(x)) for x in text.strip().split("-"))
            return datetime(y, m, d) + timedelta(seconds=secs)

        items = []
        for row in out.split(_ROW):
            parts = row.split(_SEP)
            if len(parts) != 7:
                if row.strip():
                    # A title or note containing our separator: never guess.
                    raise CalendarError("Een agenda-item kon niet gelezen worden.")
                continue
            try:
                hele_dag = parts[4].strip() == "1"
                begin = moment(parts[2])
                items.append(AgendaItem(
                    native_id=parts[0].strip(), title=parts[1],
                    start=begin, end=_eind_uit_agenda(begin, moment(parts[3]), hele_dag),
                    all_day=hele_dag, location=parts[5], notes=parts[6],
                ))
            except ValueError as exc:
                raise CalendarError(f"Een agenda-item kon niet gelezen worden: {exc}") from exc
        return items

    def add_item(self, name: str, key: str, item: AgendaItem) -> str:
        props = [f'summary:"{_esc(item.title)}"', "start date:d1", "end date:d2"]
        if item.all_day:
            props.append("allday event:true")
        if item.location:
            props.append(f'location:"{_esc(item.location)}"')
        if item.notes:
            props.append(f'description:"{_esc(item.notes)}"')
        alarm = ""
        if item.reminder_minutes is not None:
            alarm = ("    tell e to make new display alarm at end with properties "
                     f"{{trigger interval:-{abs(int(item.reminder_minutes))}}}\n")
        end = _eind_voor_agenda(item)
        uid = _run(
            _date_decl("d1", item.start) + _date_decl("d2", end)
            + 'tell application "Calendar"\n'
            f"  tell {self._cal(name, key)}\n"
            f"    set e to make new event with properties {{{', '.join(props)}}}\n"
            + alarm
            + "    return uid of e\n"
            "  end tell\n"
            "end tell"
        )
        if not uid:
            raise CalendarError("Agenda gaf geen nummer terug voor het nieuwe item.")
        return uid

    def update_item(self, name: str, key: str, item: AgendaItem) -> None:
        end = _eind_voor_agenda(item)
        # Times first and in an order that never puts the start after the
        # end; the note with the marker goes last, so an interrupted update
        # is recognisable as unfinished.
        _run(
            _date_decl("d1", item.start) + _date_decl("d2", end)
            + 'tell application "Calendar"\n'
            f"  tell {self._cal(name, key)}\n"
            f'    set e to first event whose uid is "{_esc(item.native_id)}"\n'
            f"    set allday event of e to {'true' if item.all_day else 'false'}\n"
            "    if d1 > (end date of e) then\n"
            "      set end date of e to d2\n"
            "      set start date of e to d1\n"
            "    else\n"
            "      set start date of e to d1\n"
            "      set end date of e to d2\n"
            "    end if\n"
            f'    set summary of e to "{_esc(item.title)}"\n'
            f'    set location of e to "{_esc(item.location or "")}"\n'
            f'    set description of e to "{_esc(item.notes)}"\n'
            "  end tell\n"
            "end tell"
        )

    def delete_item(self, name: str, key: str, native_id: str) -> None:
        _run(
            'tell application "Calendar"\n'
            f"  tell {self._cal(name, key)}\n"
            f'    delete (first event whose uid is "{_esc(native_id)}")\n'
            "  end tell\n"
            "end tell"
        )
