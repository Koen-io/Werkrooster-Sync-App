"""Apple Calendar backend for macOS, driven through AppleScript (osascript).

Works with every account configured in the Calendar app (iCloud, Google,
Exchange, CalDAV, local), because Calendar itself does the syncing.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime

from ..core.models import Shift
from .base import CalendarBackend, CalendarError

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


def _run(script: str, timeout: int = 120) -> str:
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
                f"{{trigger interval:-{int(shift.reminder_minutes)}}}\n"
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
    def existing_keys_list(
        self, calendar_name: str, start: datetime, end: datetime
    ) -> list[tuple[str, str]]:
        if not calendar_name:
            return []
        out = _run(self._range_script(calendar_name, start, end, with_id=False), timeout=300)
        keys: list[tuple[str, str]] = []
        for row in out.split(_ROW):
            parts = row.split(_SEP)
            if len(parts) == 2:
                keys.append((parts[0].strip().casefold(), parts[1].strip()))
        return keys

    def _range_script(
        self, calendar_name: str, start: datetime, end: datetime, with_id: bool
    ) -> str:
        id_part = ' & "' + _SEP + '" & (uid of e)' if with_id else ""
        return (
            _date_decl("d1", start)
            + _date_decl("d2", end)
            + f'set out to ""\n'
            f'tell application "Calendar"\n'
            f'  tell calendar "{_esc(calendar_name)}"\n'
            f"    set evs to every event whose start date ≥ d1 and start date ≤ d2\n"
            f"    repeat with e in evs\n"
            f"      set sd to start date of e\n"
            f"      set mm to (month of sd as integer)\n"
            f'      set mmT to text -2 thru -1 of ("0" & mm)\n'
            f'      set ddT to text -2 thru -1 of ("0" & (day of sd))\n'
            f'      set hhT to text -2 thru -1 of ("0" & (hours of sd))\n'
            f'      set miT to text -2 thru -1 of ("0" & (minutes of sd))\n'
            f"      set stamp to ((year of sd) as text) & mmT & ddT & hhT & miT\n"
            f'      set out to out & (summary of e) & "{_SEP}" & stamp{id_part} & "{_ROW}"\n'
            f"    end repeat\n"
            f"  end tell\n"
            f"end tell\n"
            f"return out"
        )

    # ------------------------------------------------------------------
    def remove_duplicates(self, calendar_name: str, start: datetime, end: datetime) -> int:
        out = _run(self._range_script(calendar_name, start, end, with_id=True), timeout=300)
        seen: set[tuple[str, str]] = set()
        surplus_uids: list[str] = []
        for row in out.split(_ROW):
            parts = row.split(_SEP)
            if len(parts) != 3:
                continue
            key = (parts[0].strip().casefold(), parts[1].strip())
            if key in seen:
                surplus_uids.append(parts[2].strip())
            else:
                seen.add(key)

        for uid in surplus_uids:
            _run(
                f'tell application "Calendar"\n'
                f'  tell calendar "{_esc(calendar_name)}"\n'
                f'    delete (every event whose uid is "{_esc(uid)}")\n'
                f"  end tell\n"
                f"end tell"
            )
        return len(surplus_uids)
