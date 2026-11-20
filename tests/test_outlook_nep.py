"""De Outlook-koppeling tegen een nagebootst Outlook.

Echte Outlook kan alleen op Windows getest worden (met de proefversie). Deze
tests vangen wel fouten in de eigen code van de koppeling: de juiste agenda
kiezen bij twee accounts, lezen, toevoegen, aanpassen en verwijderen.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from tests import test_bijwerken as tb
from werkrooster_sync.calendars import outlook_windows
from werkrooster_sync.calendars.base import CalendarError
from werkrooster_sync.core import bijwerken as b


class NepItem:
    def __init__(self, map_):
        self._map, self._start, self._end, self._body = map_, None, None, ""
        self.Subject, self.AllDayEvent, self.Location = "", False, ""
        self.ReminderSet, self.ReminderMinutesBeforeStart = False, 0
        self.EntryID = ""

    @staticmethod
    def _tijd(waarde):
        return datetime.strptime(waarde, "%Y-%m-%d %H:%M") if isinstance(waarde, str) else waarde

    Start = property(lambda self: self._start,
                     lambda self, w: setattr(self, "_start", self._tijd(w)))
    End = property(lambda self: self._end,
                   lambda self, w: setattr(self, "_end", self._tijd(w)))
    # Outlook geeft de tekst terug met Windows-regeleinden en een spatie erachter.
    Body = property(lambda self: self._body.replace("\n", "\r\n") + " \r\n",
                    lambda self, w: setattr(self, "_body", w.replace("\r\n", "\n")))

    def Save(self):
        if self._start > self._end:
            raise RuntimeError("begin na einde")
        if not self.EntryID:
            self._map.teller[0] += 1
            self.EntryID = f"item-{self._map.teller[0]}"
            self._map.opgeslagen[self.EntryID] = self

    def Delete(self):
        del self._map.opgeslagen[self.EntryID]


class NepItems(list):
    def __init__(self, map_):
        super().__init__(map_.opgeslagen.values())
        self._map = map_

    def Sort(self, veld, aflopend=False):
        self.sort(key=lambda i: i.Start, reverse=aflopend)

    def Add(self, soort):
        return NepItem(self._map)


class NepMap:
    DefaultItemType = 1
    Folders = ()

    def __init__(self, naam, store, entry, teller):
        self.Name, self.StoreID, self.EntryID = naam, store, entry
        self.opgeslagen, self.teller = {}, teller

    Items = property(lambda self: NepItems(self))


class NepStore:
    def __init__(self, naam, mappen):
        self.Name, self.Folders = naam, mappen


class NepOutlook:
    def __init__(self):
        teller = [0]
        self.prive = NepMap("Agenda", "store-prive", "map-1", teller)
        self.werk = NepMap("Agenda", "store-werk", "map-2", teller)
        self.Folders = [NepStore("prive@voorbeeld.nl", [self.prive]),
                        NepStore("werk@voorbeeld.nl", [self.werk])]

    def GetNamespace(self, naam):
        return self

    def GetDefaultFolder(self, soort):
        return self.prive

    def GetFolderFromID(self, entry, store):
        return next(m for m in (self.prive, self.werk) if (m.StoreID, m.EntryID) == (store, entry))

    def GetItemFromID(self, entry, store=None):
        for m in (self.prive, self.werk):
            if entry in m.opgeslagen and store in (None, m.StoreID):
                return m.opgeslagen[entry]
        raise RuntimeError("niet gevonden")


@pytest.fixture
def outlook(monkeypatch):
    nep = NepOutlook()
    monkeypatch.setattr(outlook_windows, "_com", lambda: nep)
    return nep


def _stand(map_):
    return sorted(f"{i.Start:%d %H:%M}-{i.End:%d %H:%M} {i.Subject}" for i in map_.opgeslagen.values())


def test_twee_accounts_met_dezelfde_agendanaam_blijven_uit_elkaar(outlook):
    agendas = outlook_windows.OutlookBackend().calendars()
    assert agendas == [("Agenda (prive@voorbeeld.nl)", "store-prive|map-1"),
                       ("Agenda (werk@voorbeeld.nl)", "store-werk|map-2")]


def test_hele_ronde_in_de_gekozen_agenda_en_de_andere_blijft_leeg(outlook):
    koppeling = outlook_windows.OutlookBackend()
    s = tb.instellingen(calendar_name="Agenda (werk@voorbeeld.nl)", calendar_key="store-werk|map-2")
    eigen = outlook.prive.Items.Add(1)
    eigen.Subject, eigen.Start, eigen.End = "Tandarts", "2026-11-23 09:00", "2026-11-23 10:00"
    eigen.Save()

    plan, uit = tb.werk_bij(koppeling, tb.rooster(tb.VOOR + [[]], s=s), s)
    assert uit.ok, uit
    assert _stand(outlook.werk) == ["23 07:00-23 16:30 Ochtend", "24 07:00-24 16:30 Ochtend",
                                    "25 07:00-25 16:30 Ochtend", "26 00:00-27 00:00 Vrij",
                                    "27 00:00-28 00:00 Vrij"]
    herinnering = {i.Subject: (i.ReminderSet, i.ReminderMinutesBeforeStart)
                   for i in outlook.werk.opgeslagen.values()}
    assert herinnering == {"Ochtend": (True, 60), "Vrij": (False, 0)}

    # Niets te doen bij opnieuw inlezen: Outlook geeft tekst en hele dagen
    # anders terug dan geschreven, maar dat telt niet als verschil.
    plan, uit = tb.werk_bij(koppeling, tb.rooster(tb.VOOR + [[]], s=s), s)
    assert {d.uitkomst for d in plan.dagen} == {b.STAAT_ER_AL}

    nieuw = tb.rooster(tb.NA + [["DIENST 23:30-07:00"]], gen=tb.GEN + timedelta(days=1), s=s)
    plan, uit = tb.werk_bij(koppeling, nieuw, s, tb.JA)
    assert uit.ok, uit
    assert _stand(outlook.werk) == [
        "23 08:00-23 17:00 Ochtend", "24 07:00-24 12:00 Ochtend", "24 13:00-24 18:30 Laat",
        "25 00:00-26 00:00 Vrij", "26 23:00-27 07:00 Nacht", "27 23:30-28 07:00 Nacht"]

    terug = b.maak_ongedaan(koppeling, b.Beheer.laad())
    assert not terug.fouten and not terug.blijft_staan
    assert len(outlook.werk.opgeslagen) == 5
    assert _stand(outlook.prive) == ["23 09:00-23 10:00 Tandarts"]


def test_aanpassen_naar_later_tijdstip_zet_begin_nooit_na_einde(outlook):
    koppeling = outlook_windows.OutlookBackend()
    s = tb.instellingen(calendar_key="store-werk|map-2", include_vrij=False)
    tb.werk_bij(koppeling, tb.rooster([["DIENST 07:00-12:30"]], s=s), s)
    plan, uit = tb.werk_bij(koppeling, tb.rooster([["DIENST 14:00-23:00"]],
                                                  gen=tb.GEN + timedelta(days=1), s=s), s)
    assert uit.ok and _stand(outlook.werk) == ["23 14:00-23 23:00 Laat"]


def test_verdwenen_agenda_geeft_een_duidelijke_melding(outlook):
    with pytest.raises(CalendarError, match="niet meer te vinden"):
        outlook_windows.OutlookBackend().read_items(
            "Agenda", "store-weg|map-9", datetime(2026, 1, 1), datetime(2027, 1, 1))
