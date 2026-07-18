"""Microsoft Outlook backend for Windows, via COM automation (pywin32).

Works with every account configured in the Outlook desktop app (Exchange,
Microsoft 365, Outlook.com, Gmail via IMAP+calendar, …), because Outlook
does the syncing.
"""
from __future__ import annotations

import sys
from datetime import datetime

from ..core.models import Shift
from .base import CalendarBackend, CalendarError

OL_APPOINTMENT_ITEM = 1
OL_FOLDER_CALENDAR = 9


def _com():
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:  # pragma: no cover - windows only
        raise CalendarError(
            "Outlook-koppeling niet beschikbaar (pywin32 ontbreekt)."
        ) from exc
    pythoncom.CoInitialize()
    try:
        return win32com.client.Dispatch("Outlook.Application")
    except Exception as exc:  # pragma: no cover - windows only
        raise CalendarError(
            "Kan Outlook niet openen. Is Microsoft Outlook geïnstalleerd?"
        ) from exc


class OutlookBackend(CalendarBackend):
    id = "outlook"
    label = "Microsoft Outlook (Windows)"

    def is_available(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import win32com.client  # noqa: F401
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    def _calendar_folders(self, outlook) -> dict[str, object]:
        """All calendar folders across all stores, keyed by display name."""
        ns = outlook.GetNamespace("MAPI")
        folders: dict[str, object] = {}

        def visit(folder, prefix: str) -> None:
            try:
                if folder.DefaultItemType == OL_APPOINTMENT_ITEM:
                    folders[prefix + folder.Name] = folder
            except Exception:
                pass
            try:
                for sub in folder.Folders:
                    visit(sub, prefix)
            except Exception:
                pass

        default = ns.GetDefaultFolder(OL_FOLDER_CALENDAR)
        visit(default, "")
        for store_root in ns.Folders:
            try:
                for sub in store_root.Folders:
                    visit(sub, "")
            except Exception:
                continue
        return folders

    def _folder(self, outlook, calendar_name: str):
        folders = self._calendar_folders(outlook)
        if not calendar_name:
            return outlook.GetNamespace("MAPI").GetDefaultFolder(OL_FOLDER_CALENDAR)
        if calendar_name in folders:
            return folders[calendar_name]
        raise CalendarError(f'Agenda "{calendar_name}" niet gevonden in Outlook.')

    # ------------------------------------------------------------------
    def list_calendars(self) -> list[str]:
        outlook = _com()
        return sorted(self._calendar_folders(outlook).keys())

    # ------------------------------------------------------------------
    def add_shift(self, calendar_name: str, shift: Shift) -> None:
        outlook = _com()
        folder = self._folder(outlook, calendar_name)
        try:
            appt = folder.Items.Add(OL_APPOINTMENT_ITEM)
            appt.Subject = shift.display_name
            appt.Start = shift.start.strftime("%Y-%m-%d %H:%M")
            end = shift.end if shift.end > shift.start else shift.start
            appt.End = end.strftime("%Y-%m-%d %H:%M")
            if shift.all_day:
                appt.AllDayEvent = True
            if shift.location:
                appt.Location = shift.location
            if shift.description:
                appt.Body = shift.description
            if shift.reminder_minutes is not None:
                appt.ReminderSet = True
                appt.ReminderMinutesBeforeStart = int(shift.reminder_minutes)
            else:
                appt.ReminderSet = False
            appt.Save()
        except CalendarError:
            raise
        except Exception as exc:
            raise CalendarError(f"Outlook weigert het item: {exc}") from exc

    # ------------------------------------------------------------------
    def _items_in_range(self, folder, start: datetime, end: datetime):
        items = folder.Items
        items.IncludeRecurrences = True
        items.Sort("[Start]")
        restriction = (
            f"[Start] >= '{start.strftime('%m/%d/%Y %I:%M %p')}'"
            f" AND [Start] <= '{end.strftime('%m/%d/%Y %I:%M %p')}'"
        )
        return items.Restrict(restriction)

    def existing_keys_list(
        self, calendar_name: str, start: datetime, end: datetime
    ) -> list[tuple[str, str]]:
        outlook = _com()
        folder = self._folder(outlook, calendar_name)
        keys: list[tuple[str, str]] = []
        try:
            for item in self._items_in_range(folder, start, end):
                subject = str(item.Subject or "")
                item_start = item.Start  # pywintypes datetime
                stamp = f"{item_start.year:04d}{item_start.month:02d}{item_start.day:02d}" \
                        f"{item_start.hour:02d}{item_start.minute:02d}"
                keys.append((subject.strip().casefold(), stamp))
        except Exception as exc:
            raise CalendarError(f"Kan agenda-items niet lezen uit Outlook: {exc}") from exc
        return keys

    # ------------------------------------------------------------------
    def remove_duplicates(self, calendar_name: str, start: datetime, end: datetime) -> int:
        outlook = _com()
        folder = self._folder(outlook, calendar_name)
        seen: set[tuple[str, str]] = set()
        surplus = []
        try:
            for item in self._items_in_range(folder, start, end):
                subject = str(item.Subject or "")
                item_start = item.Start
                stamp = f"{item_start.year:04d}{item_start.month:02d}{item_start.day:02d}" \
                        f"{item_start.hour:02d}{item_start.minute:02d}"
                key = (subject.strip().casefold(), stamp)
                if key in seen:
                    surplus.append(item)
                else:
                    seen.add(key)
            for item in surplus:
                item.Delete()
        except Exception as exc:
            raise CalendarError(f"Verwijderen van dubbele items mislukt: {exc}") from exc
        return len(surplus)
