"""Een agenda in het geheugen, om het bijwerken te testen zonder echte agenda.

Kan op commando afbreken of weigeren: ``breek_bij=n`` laat de n-de
schrijfactie de app "uitvallen" (vóór of ná het uitvoeren), ``weiger_bij=n``
laat hem mislukken met een gewone agendafout.
"""
from __future__ import annotations

from dataclasses import replace

from werkrooster_sync.calendars.base import AgendaItem, CalendarBackend, CalendarError


class Uitgevallen(BaseException):
    """De app valt uit (stroom weg, afgesloten): geen nette foutafhandeling."""


class NepAgenda(CalendarBackend):
    id = "nep"
    label = "Nep-agenda"

    def __init__(self):
        self.items: dict[str, AgendaItem] = {}
        self._volgnummer = 0
        self.schrijfacties = 0
        self.breek_bij = None
        self.breek_na_uitvoeren = False
        self.weiger_bij = None

    def is_available(self):
        return True

    def list_calendars(self):
        return ["Werk"]

    def calendars(self):
        return [("Werk", "agenda-1")]

    def add_shift(self, calendar_name, shift):  # oude route, niet gebruikt
        raise AssertionError("oude route")

    def existing_keys_list(self, calendar_name, start, end):
        return []

    # ------------------------------------------------------------------
    def _schrijf(self, doe):
        self.schrijfacties += 1
        n = self.schrijfacties
        if n == self.weiger_bij:
            raise CalendarError("agenda weigert")
        if n == self.breek_bij and not self.breek_na_uitvoeren:
            raise Uitgevallen()
        uit = doe()
        if n == self.breek_bij:
            raise Uitgevallen()
        return uit

    def read_items(self, name, key, start, end):
        # Teruggeven zoals een echte agenda dat doet: net iets anders dan
        # geschreven (Windows-regeleinden en een lege regel erachter).
        return [replace(i, notes=i.notes.replace("\n", "\r\n") + "\r\n")
                for i in self.items.values() if start <= i.start <= end]

    def add_item(self, name, key, item):
        def doe():
            self._volgnummer += 1
            nummer = f"n{self._volgnummer}"
            self.items[nummer] = replace(item, native_id=nummer)
            return nummer
        return self._schrijf(doe)

    def update_item(self, name, key, item):
        def doe():
            if item.native_id not in self.items:
                raise CalendarError("item bestaat niet meer")
            oud = self.items[item.native_id]
            self.items[item.native_id] = replace(
                oud, title=item.title, start=item.start, end=item.end,
                all_day=item.all_day, notes=item.notes)
        return self._schrijf(doe)

    def delete_item(self, name, key, native_id):
        def doe():
            if native_id not in self.items:
                raise CalendarError("item bestaat niet meer")
            del self.items[native_id]
        return self._schrijf(doe)
