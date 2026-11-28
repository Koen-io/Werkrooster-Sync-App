"""Microsoft Outlook backend for Windows, via COM automation (pywin32).

Works with every account configured in the Outlook desktop app (Exchange,
Microsoft 365, Outlook.com, Gmail via IMAP+calendar, …), because Outlook
does the syncing.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta

from ..core.models import Shift
from .base import AgendaItem, CalendarBackend, CalendarError

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
            end = shift.end if shift.end > shift.start else shift.start
            if shift.all_day:
                # All-day items must run midnight to midnight in Outlook.
                day = shift.start.date()
                end_day = max(end.date(), day + timedelta(days=1))
                appt.Start = day.strftime("%Y-%m-%d") + " 00:00"
                appt.End = end_day.strftime("%Y-%m-%d") + " 00:00"
                appt.AllDayEvent = True
            else:
                appt.Start = shift.start.strftime("%Y-%m-%d %H:%M")
                appt.End = end.strftime("%Y-%m-%d %H:%M")
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
    # Version 2: complete items, addressed by Outlook's own ids
    # ------------------------------------------------------------------
    _KEY_SEP = "|"

    def _all_folders(self, outlook) -> list[tuple[str, str, object]]:
        """Every calendar folder as (name, key, folder). The key is the
        store id plus the folder's entry id: two accounts that both have a
        calendar called "Agenda" get different keys."""
        ns = outlook.GetNamespace("MAPI")
        found: list[tuple[str, str, object]] = []
        seen: set[str] = set()

        def visit(folder, store_name: str) -> None:
            try:
                if folder.DefaultItemType == OL_APPOINTMENT_ITEM:
                    key = f"{folder.StoreID}{self._KEY_SEP}{folder.EntryID}"
                    if key not in seen:
                        seen.add(key)
                        found.append((str(folder.Name), key, folder, store_name))
            except Exception:
                pass
            try:
                for sub in folder.Folders:
                    visit(sub, store_name)
            except Exception:
                pass

        for store_root in ns.Folders:
            try:
                store_name = str(store_root.Name)
                for sub in store_root.Folders:
                    visit(sub, store_name)
            except Exception:
                continue
        try:
            default = ns.GetDefaultFolder(OL_FOLDER_CALENDAR)
            visit(default, "")  # only added when no store listed it
            default_key = f"{default.StoreID}{self._KEY_SEP}{default.EntryID}"
            found.sort(key=lambda f: f[1] != default_key)  # default calendar first
        except Exception:
            pass
        # Same name in more than one account: show the account with it.
        names = [f[0] for f in found]
        return [
            (f"{name} ({store})" if names.count(name) > 1 and store else name, key, folder)
            for name, key, folder, store in found
        ]

    def calendars(self) -> list[tuple[str, str]]:
        return [(name, key) for name, key, _f in self._all_folders(_com())]

    def _folder_v2(self, outlook, name: str, key: str):
        if key:
            store_id, _, entry_id = key.partition(self._KEY_SEP)
            try:
                return outlook.GetNamespace("MAPI").GetFolderFromID(entry_id, store_id)
            except Exception as exc:
                raise CalendarError(
                    f'Agenda "{name}" is niet meer te vinden in Outlook. '
                    "Kies de agenda opnieuw in Instellingen."
                ) from exc
        return self._folder(outlook, name)

    @staticmethod
    def _naive(value) -> datetime:
        return datetime(value.year, value.month, value.day, value.hour, value.minute)

    def read_items(self, name: str, key: str, start: datetime, end: datetime) -> list[AgendaItem]:
        outlook = _com()
        folder = self._folder_v2(outlook, name, key)
        result: list[AgendaItem] = []
        try:
            items = folder.Items
            # No Restrict(): its date texts depend on the Windows regional
            # settings. Newest first, and stop once we are before the range.
            items.Sort("[Start]", True)
            for item in items:
                try:
                    item_start = self._naive(item.Start)
                except Exception:
                    continue  # not an appointment
                if item_start > end:
                    continue
                if item_start < start:
                    break
                try:
                    body = str(item.Body or "")
                except Exception as exc:
                    # Body can be blocked by the Outlook security guard. Without
                    # it we cannot recognise our own items, so stop instead of
                    # adding every shift a second time.
                    raise CalendarError(
                        "Outlook laat de notities van je agenda niet lezen. "
                        "Er is niets veranderd.") from exc
                result.append(AgendaItem(
                    native_id=str(item.EntryID), title=str(item.Subject or ""),
                    start=item_start, end=self._naive(item.End),
                    all_day=bool(item.AllDayEvent), notes=body,
                    location=str(item.Location or ""),
                ))
        except CalendarError:
            raise
        except Exception as exc:
            raise CalendarError(f"Kan agenda-items niet lezen uit Outlook: {exc}") from exc
        return result

    @staticmethod
    def _set_times(appt, item: AgendaItem, existing: bool) -> None:
        end = item.end if item.end > item.start else item.start
        if item.all_day:
            # All-day items must run midnight to midnight in Outlook.
            day = item.start.date()
            end_day = max(end.date(), day + timedelta(days=1))
            new_start = day.strftime("%Y-%m-%d") + " 00:00"
            new_end = end_day.strftime("%Y-%m-%d") + " 00:00"
        else:
            new_start = item.start.strftime("%Y-%m-%d %H:%M")
            new_end = end.strftime("%Y-%m-%d %H:%M")
        appt.AllDayEvent = bool(item.all_day)
        later = False
        if existing:
            try:
                later = item.start > OutlookBackend._naive(appt.End)
            except Exception:
                later = False
        # Never put the start after the end, not even for a moment.
        if later:
            appt.End = new_end
            appt.Start = new_start
        else:
            appt.Start = new_start
            appt.End = new_end
        if item.all_day:
            appt.AllDayEvent = True

    def add_item(self, name: str, key: str, item: AgendaItem) -> str:
        outlook = _com()
        folder = self._folder_v2(outlook, name, key)
        try:
            appt = folder.Items.Add(OL_APPOINTMENT_ITEM)
            appt.Subject = item.title
            self._set_times(appt, item, existing=False)
            if item.location:
                appt.Location = item.location
            if item.reminder_minutes is not None:
                appt.ReminderSet = True
                appt.ReminderMinutesBeforeStart = int(item.reminder_minutes)
            else:
                appt.ReminderSet = False
            appt.Body = item.notes
            appt.Save()
            return str(appt.EntryID)
        except Exception as exc:
            raise CalendarError(f"Outlook weigert het item: {exc}") from exc

    def _item(self, outlook, key: str, native_id: str):
        store_id = key.partition(self._KEY_SEP)[0] if key else ""
        ns = outlook.GetNamespace("MAPI")
        try:
            return ns.GetItemFromID(native_id, store_id) if store_id else ns.GetItemFromID(native_id)
        except Exception as exc:
            raise CalendarError("Het agenda-item bestaat niet meer in Outlook.") from exc

    def update_item(self, name: str, key: str, item: AgendaItem) -> None:
        outlook = _com()
        appt = self._item(outlook, key, item.native_id)
        try:
            self._set_times(appt, item, existing=True)
            appt.Subject = item.title
            appt.Location = item.location or ""
            appt.Body = item.notes  # last: carries the marker
            appt.Save()
        except Exception as exc:
            raise CalendarError(f"Outlook weigert de wijziging: {exc}") from exc

    def delete_item(self, name: str, key: str, native_id: str) -> None:
        outlook = _com()
        appt = self._item(outlook, key, native_id)
        try:
            appt.Delete()
        except Exception as exc:
            raise CalendarError(f"Verwijderen uit Outlook mislukt: {exc}") from exc
