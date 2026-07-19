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
    def _scan(
        self, calendar_name: str, start: datetime, end: datetime, with_uid: bool = False
    ) -> list[tuple[str, str, str, bool, str]]:
        """Rows of (title_casefold, stamp, sync_id, concept, uid) in range."""
        if not calendar_name:
            return []
        out = _run(
            self._range_script(calendar_name, start, end, with_uid=with_uid),
            timeout=300,
        )
        rows: list[tuple[str, str, str, bool, str]] = []
        for row in out.split(_ROW):
            parts = row.split(_SEP)
            if len(parts) >= 4:
                title = parts[0].strip().casefold()
                concept = parts[3].strip() == "1" or title.endswith("(concept)")
                uid = parts[4].strip() if len(parts) >= 5 else ""
                rows.append((title, parts[1].strip(), parts[2].strip(), concept, uid))
        return rows

    def existing_keys_list(
        self, calendar_name: str, start: datetime, end: datetime
    ) -> list[tuple[str, str]]:
        return [(t, s) for t, s, _m, _c, _u in self._scan(calendar_name, start, end)]

    def scan_events(self, calendar_name: str, start: datetime, end: datetime):
        from .base import ExistingEvent

        return [
            ExistingEvent(t, s, m, c)
            for t, s, m, c, _u in self._scan(calendar_name, start, end)
        ]

    def _range_script(
        self, calendar_name: str, start: datetime, end: datetime, with_uid: bool
    ) -> str:
        uid_part = ' & "' + _SEP + '" & (uid of e)' if with_uid else ""
        return (
            _date_decl("d1", start)
            + _date_decl("d2", end)
            + f'set out to ""\n'
            f'set tag to "[WerkroosterSync:"\n'
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
            f'      set syncId to ""\n'
            f'      set conceptFlag to "0"\n'
            f"      try\n"
            f"        set desc to (description of e) as text\n"
            f"        if desc contains tag then\n"
            f"          set AppleScript's text item delimiters to tag\n"
            f"          set part to text item 2 of desc\n"
            f'          set AppleScript\'s text item delimiters to ""\n'
            f"          set syncId to text 1 thru 12 of part\n"
            f"        end if\n"
            f'        if desc contains "[WerkroosterSync-concept]" then set conceptFlag to "1"\n'
            f"      end try\n"
            f'      set AppleScript\'s text item delimiters to ""\n'
            f'      set out to out & (summary of e) & "{_SEP}" & stamp & "{_SEP}" & syncId & "{_SEP}" & conceptFlag{uid_part} & "{_ROW}"\n'
            f"    end repeat\n"
            f"  end tell\n"
            f"end tell\n"
            f"return out"
        )

    # ------------------------------------------------------------------
    def remove_duplicates(self, calendar_name: str, start: datetime, end: datetime) -> int:
        rows = self._scan(calendar_name, start, end, with_uid=True)
        seen: set[tuple[str, str]] = set()
        surplus_uids: list[str] = []
        for title, stamp, _marker, _concept, uid in rows:
            key = (title, stamp)
            if key in seen:
                surplus_uids.append(uid)
            else:
                seen.add(key)

        self._delete_by_uids(calendar_name, surplus_uids)
        return len(surplus_uids)

    def _delete_by_uids(self, calendar_name: str, uids: list[str]) -> None:
        for uid in uids:
            _run(
                f'tell application "Calendar"\n'
                f'  tell calendar "{_esc(calendar_name)}"\n'
                f'    delete (every event whose uid is "{_esc(uid)}")\n'
                f"  end tell\n"
                f"end tell"
            )

    # ------------------------------------------------------------------
    def count_synced(self, calendar_name: str, start: datetime, end: datetime) -> int:
        rows = self._scan(calendar_name, start, end)
        return sum(1 for _t, _s, marker, _c, _u in rows if marker)

    def remove_synced(self, calendar_name: str, start: datetime, end: datetime) -> int:
        rows = self._scan(calendar_name, start, end, with_uid=True)
        uids = [uid for _t, _s, marker, _c, uid in rows if marker and uid]
        self._delete_by_uids(calendar_name, uids)
        return len(uids)

    def remove_by_sync_ids(
        self, calendar_name: str, start: datetime, end: datetime, sync_ids: set[str]
    ) -> int:
        rows = self._scan(calendar_name, start, end, with_uid=True)
        uids = [uid for _t, _s, marker, _c, uid in rows if marker in sync_ids and uid]
        self._delete_by_uids(calendar_name, uids)
        return len(uids)
