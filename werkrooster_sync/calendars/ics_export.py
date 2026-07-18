"""Universal fallback backend: writes a cleaned-up .ics file.

The generated file contains the renamed shifts including reminders (VALARM),
and is opened with the system's default calendar application afterwards. This
makes the app work with *any* calendar program on macOS, Windows or Linux
(Google Agenda via import, Thunderbird, Windows Agenda, enz.).

Duplicate detection is not possible in this mode, because the app never sees
the target calendar — the calendar app's own import dialog handles that.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

from ..core.models import Shift
from .base import CalendarBackend, CalendarError

CALENDAR_LABEL = "Standaard agenda-app (.ics import)"


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def _fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


class IcsExportBackend(CalendarBackend):
    id = "ics_export"
    label = "Andere agenda-app (.ics export)"

    def __init__(self, output_dir: Path | None = None, open_after: bool = True):
        self.output_dir = output_dir
        self.open_after = open_after
        self._buffer: list[Shift] = []
        self.last_output: Path | None = None

    def is_available(self) -> bool:
        return True

    def list_calendars(self) -> list[str]:
        return [CALENDAR_LABEL]

    def begin(self, calendar_name: str) -> None:
        self._buffer = []

    def add_shift(self, calendar_name: str, shift: Shift) -> None:
        self._buffer.append(shift)

    def existing_keys_list(self, calendar_name, start, end):
        return []

    def finalize(self) -> None:
        if not self._buffer:
            return
        out_dir = self.output_dir or Path.home() / "Downloads"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            out_dir = Path.home()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"Werkrooster_{stamp}.ics"

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//WerkroosterSync//NL",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
        ]
        now = datetime.utcnow()
        for shift in self._buffer:
            lines.append("BEGIN:VEVENT")
            lines.append(f"UID:{uuid.uuid4()}@werkroostersync")
            lines.append(f"DTSTAMP:{_fmt(now)}Z")
            if shift.all_day:
                lines.append(f"DTSTART;VALUE=DATE:{_fmt_date(shift.start)}")
                end = shift.end if shift.end > shift.start else shift.start
                lines.append(f"DTEND;VALUE=DATE:{_fmt_date(end)}")
            else:
                lines.append(f"DTSTART:{_fmt(shift.start)}")
                end = shift.end if shift.end > shift.start else shift.start
                lines.append(f"DTEND:{_fmt(end)}")
            lines.append(f"SUMMARY:{_escape(shift.display_name)}")
            if shift.location:
                lines.append(f"LOCATION:{_escape(shift.location)}")
            if shift.description:
                lines.append(f"DESCRIPTION:{_escape(shift.description)}")
            if shift.reminder_minutes is not None:
                lines.append("BEGIN:VALARM")
                lines.append("ACTION:DISPLAY")
                lines.append(f"DESCRIPTION:{_escape(shift.display_name)}")
                lines.append(f"TRIGGER:-PT{int(shift.reminder_minutes)}M")
                lines.append("END:VALARM")
            lines.append("END:VEVENT")
        lines.append("END:VCALENDAR")

        try:
            path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
        except OSError as exc:
            raise CalendarError(f"Kan exportbestand niet schrijven: {exc}") from exc
        self.last_output = path
        self._buffer = []

        if self.open_after:
            self._open(path)

    @staticmethod
    def _open(path: Path) -> None:
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            elif os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError:
            pass  # file is saved; opening it is best-effort
