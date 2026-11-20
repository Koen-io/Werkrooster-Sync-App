"""Breekpunten van het bijwerken (zie docs/ontwerp-bijwerken.md)."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from tests.nep_agenda import NepAgenda, Uitgevallen
from werkrooster_sync.calendars.base import AgendaItem
from werkrooster_sync.core import bijwerken as b
from werkrooster_sync.core.classifier import apply_classification
from werkrooster_sync.core.models import Shift
from werkrooster_sync.core.pdf_parser import Roster
from werkrooster_sync.core.settings import Settings

D1 = date(2026, 11, 23)  # maandag
GEN = datetime(2026, 11, 20, 17, 38)


def dag(n: int) -> date:
    return D1 + timedelta(days=n)


def instellingen(**anders) -> Settings:
    return Settings(**{"calendar_name": "Werk", "calendar_key": "agenda-1", **anders})


def rooster(dagen: list[list[str]], *, concept=False, gen=GEN, nummer="12345678",
            eerste=D1, s: Settings | None = None, **anders):
    """Een rooster met per dag de soortregels uit de pdf; [] is een lege dag."""
    r = Roster(per_kolom=True, volledig=True, is_concept=concept, gegenereerd=gen,
               personeelsnummer=nummer,
               periode=(eerste, eerste + timedelta(days=len(dagen) - 1)))
    for k, v in anders.items():
        setattr(r, k, v)
    shifts = []
    for i, soorten in enumerate(dagen):
        d = eerste + timedelta(days=i)
        start = datetime(d.year, d.month, d.day)
        for soort in soorten or ["Vrij"]:
            x = Shift(start=start, end=start + timedelta(days=1), original_summary=soort,
                      all_day=True, description="07:00-11:30 Werk" if "DIENST" in soort else "")
            x.is_concept, x.roster_date = concept, d
            shifts.append(x)
    r.shifts = apply_classification(shifts, s or instellingen())
    return r


def werk_bij(agenda, r, s=None, keuzes=None, beheer=None):
    s = s or instellingen()
    beheer = beheer if beheer is not None else b.Beheer.laad()
    plan = b.maak_plan(r, r.shifts, agenda, s, beheer, keuzes)
    return plan, b.voer_uit(plan, agenda, beheer, keuzes)


def stand(agenda) -> list[str]:
    return sorted(f"{i.start:%d %H:%M}-{i.end:%d %H:%M} {i.title}" for i in agenda.items.values())


WEEK = [["DIENST 07:00-16:30"], ["DIENST 07:00-16:30"], [], ["DIENST 23:00-07:00"]]
WEEK_STAND = ["23 07:00-23 16:30 Ochtend", "24 07:00-24 16:30 Ochtend",
              "25 00:00-26 00:00 Vrij", "26 23:00-27 07:00 Nacht"]


# ----------------------------------------------------------------------
def test_eerste_keer_alles_nieuw_en_daarna_staat_het_er_al():
    agenda = NepAgenda()
    plan, uit = werk_bij(agenda, rooster(WEEK))
    assert [d.uitkomst for d in plan.dagen] == [b.NIEUW] * 4
    assert uit.ok and uit.toegevoegd == 4 and stand(agenda) == WEEK_STAND

    geschreven = agenda.schrijfacties
    plan, uit = werk_bij(agenda, rooster(WEEK))
    assert [d.uitkomst for d in plan.dagen] == [b.STAAT_ER_AL] * 4
    assert agenda.schrijfacties == geschreven and uit.ok


def test_notitie_heeft_eigen_blok_met_kenmerk_zonder_leesbaar_nummer():
    agenda = NepAgenda()
    werk_bij(agenda, rooster(WEEK))
    notitie = agenda.items["n1"].notes
    assert notitie.splitlines()[:2] == ["Uit je werkrooster:", "07:00-11:30 Werk"]
    assert b.KENMERK_RE.search(notitie.splitlines()[-1])
    assert "12345678" not in notitie


def test_gewijzigde_tijd_past_het_bestaande_item_aan_en_laat_jouw_tekst_staan():
    agenda = NepAgenda()
    werk_bij(agenda, rooster(WEEK))
    oud = agenda.items["n1"]
    agenda.items["n1"] = replace(oud, notes="Neem taart mee\n\n" + oud.notes,
                                 location="Bureau", reminder_minutes=15)

    nieuw = [["DIENST 08:00-17:00"]] + WEEK[1:]
    plan, uit = werk_bij(agenda, rooster(nieuw, gen=GEN + timedelta(days=1)))
    assert plan.dagen[0].uitkomst == b.GEWIJZIGD
    assert [s.actie for s in plan.dagen[0].stappen] == ["werk_bij"]
    item = agenda.items["n1"]  # zelfde item, niet verwijderd en opnieuw gemaakt
    assert (item.start.hour, item.end.hour) == (8, 17)
    assert item.notes.startswith("Neem taart mee")
    assert (item.location, item.reminder_minutes) == ("Bureau", 15)
    assert uit.ok and uit.bijgewerkt == 1 and len(agenda.items) == 4


def test_vervallen_dienst_wordt_pas_verwijderd_na_eigen_bevestiging():
    agenda = NepAgenda()
    werk_bij(agenda, rooster(WEEK), instellingen(include_vrij=False))
    assert len(agenda.items) == 3
    korter = [WEEK[0], [], [], WEEK[3]]
    s = instellingen(include_vrij=False)

    plan, uit = werk_bij(agenda, rooster(korter, gen=GEN + timedelta(days=1), s=s), s)
    assert plan.dagen[1].uitkomst == b.VERWIJDEREN and plan.aantal_verwijderingen == 1
    assert len(agenda.items) == 3 and dag(1) in uit.niet_bijgewerkt

    plan, uit = werk_bij(agenda, rooster(korter, gen=GEN + timedelta(days=1), s=s), s,
                         b.Keuzes(verwijderen_bevestigd=True))
    assert uit.ok and uit.verwijderd == 1 and len(agenda.items) == 2


def test_splitsen_en_samenvoegen_zonder_gokwerk():
    agenda = NepAgenda()
    werk_bij(agenda, rooster(WEEK))
    gesplitst = [["DIENST 07:00-12:00", "DIENST 13:00-18:30"]] + WEEK[1:]
    plan, uit = werk_bij(agenda, rooster(gesplitst, gen=GEN + timedelta(days=1)))
    assert sorted(s.actie for s in plan.dagen[0].stappen) == ["verwijder", "voeg_toe", "voeg_toe"]
    assert uit.ok and stand(agenda)[:2] == ["23 07:00-23 12:00 Ochtend", "23 13:00-23 18:30 Laat"]

    # Samenvoegen: er verdwijnt netto een item, dus eerst bevestigen.
    plan, uit = werk_bij(agenda, rooster(WEEK, gen=GEN + timedelta(days=2)))
    assert plan.aantal_verwijderingen == 1
    assert uit.niet_bijgewerkt == {D1: "verwijderen is niet bevestigd"}
    plan, uit = werk_bij(agenda, rooster(WEEK, gen=GEN + timedelta(days=2)), keuzes=JA)
    assert uit.ok and stand(agenda) == WEEK_STAND


def test_tweede_dienst_erbij_laat_de_eerste_met_rust():
    agenda = NepAgenda()
    werk_bij(agenda, rooster(WEEK))
    erbij = [["DIENST 07:00-16:30", "DIENST 18:00-23:30"]] + WEEK[1:]
    plan, uit = werk_bij(agenda, rooster(erbij, gen=GEN + timedelta(days=1)))
    assert [s.actie for s in plan.dagen[0].stappen] == ["voeg_toe"]
    assert uit.ok and "n1" in agenda.items


def test_definitief_vervangt_concept():
    agenda = NepAgenda()
    werk_bij(agenda, rooster(WEEK, concept=True))
    assert "23 07:00-23 16:30 Ochtend (concept)" in stand(agenda)
    plan, uit = werk_bij(agenda, rooster(WEEK, gen=GEN - timedelta(days=3)))  # ouder, maar definitief
    assert {d.uitkomst for d in plan.dagen} == {b.VERVANGT_CONCEPT}
    assert uit.ok and stand(agenda) == WEEK_STAND and len(agenda.items) == 4


# --- afbreken ---------------------------------------------------------
VOOR = [["DIENST 07:00-16:30"], ["DIENST 07:00-16:30"], ["DIENST 07:00-16:30"], []]
NA = [["DIENST 08:00-17:00"],                               # aanpassen
      ["DIENST 07:00-12:00", "DIENST 13:00-18:30"],          # vervangen
      [],                                                    # vervalt
      ["DIENST 23:00-07:00"]]                                # nieuw
NA_STAND = ["23 08:00-23 17:00 Ochtend", "24 07:00-24 12:00 Ochtend",
            "24 13:00-24 18:30 Laat", "26 23:00-27 07:00 Nacht"]
JA = b.Keuzes(verwijderen_bevestigd=True)
ZONDER_VRIJ = dict(include_vrij=False)


def _begin():
    agenda = NepAgenda()
    s = instellingen(**ZONDER_VRIJ)
    werk_bij(agenda, rooster(VOOR, s=s), s)
    return agenda, s


def test_volledige_bijwerking_geeft_het_gewenste_eindbeeld():
    agenda, s = _begin()
    plan, uit = werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    assert uit.ok and stand(agenda) == NA_STAND
    assert (uit.toegevoegd, uit.bijgewerkt, uit.verwijderd) == (3, 1, 2)


@pytest.mark.parametrize("na_uitvoeren", [False, True])
@pytest.mark.parametrize("n", range(1, 7))
def test_afbreken_op_elk_moment_en_opnieuw_draaien_geeft_geen_dubbelen(n, na_uitvoeren):
    agenda, s = _begin()
    nieuw = rooster(NA, gen=GEN + timedelta(days=1), s=s)
    agenda.breek_bij = agenda.schrijfacties + n
    agenda.breek_na_uitvoeren = na_uitvoeren
    with pytest.raises(Uitgevallen):
        werk_bij(agenda, nieuw, s, JA)

    agenda.breek_bij = None
    plan, uit = werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    assert uit.ok, uit
    assert stand(agenda) == NA_STAND
    # En nog een keer: nu is er niets meer te doen.
    geschreven = agenda.schrijfacties
    plan, uit = werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    assert agenda.schrijfacties == geschreven and stand(agenda) == NA_STAND


def test_half_aangepast_item_na_uitval_telt_niet_als_zelf_aangepast():
    agenda, s = _begin()
    nieuw = rooster(NA, gen=GEN + timedelta(days=1), s=s)
    plan = b.maak_plan(nieuw, nieuw.shifts, agenda, s, b.Beheer.laad(), JA)
    # De agenda zette de nieuwe tijd al, de notitie met het kenmerk nog niet.
    j = b._Journaal({"agenda": "Werk", "agenda_nummer": "agenda-1", "sleutel": "x",
                     "bereik": ["2026-01-01T00:00:00", "2027-01-01T00:00:00"], "beheer_voor": None})
    stap = plan.dagen[0].stappen[0]
    j.schrijf({"fase": "ga", "n": 1, "dag": D1.isoformat(), "actie": "werk_bij",
               "voor": b._item_dict(stap.voor), "na": b._item_dict(stap.na)})
    j.sluit()
    agenda.items["n1"] = replace(agenda.items["n1"], start=stap.na.start, end=stap.na.end)

    plan, uit = werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    assert plan.dagen[0].uitkomst == b.GEWIJZIGD and not plan.dagen[0].keuze_nodig
    assert uit.ok and stand(agenda) == NA_STAND


@pytest.mark.parametrize("n", [2, 3, 4])  # 1 = de enige stap van dag 1
def test_stap_die_mislukt_zet_de_hele_dag_terug(n):
    agenda, s = _begin()
    voor = dict(agenda.items)
    agenda.weiger_bij = agenda.schrijfacties + n  # binnen dag 2: weg, erbij, erbij
    plan, uit = werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    assert dag(1) in uit.niet_bijgewerkt and "teruggezet" in uit.niet_bijgewerkt[dag(1)]
    op_dag_2 = [f"{i.start:%H:%M} {i.title}" for i in agenda.items.values() if i.start.date() == dag(1)]
    assert op_dag_2 == ["07:00 Ochtend"]            # zoals hij was
    assert "23 08:00-23 17:00 Ochtend" in stand(agenda)  # de andere dagen wel
    assert "26 23:00-27 07:00 Nacht" in stand(agenda)
    # Het teruggezette item heeft dezelfde titel, tijden en notitie als ervoor.
    oud_item = next(i for i in voor.values() if i.start.date() == dag(1))
    nu_item = next(i for i in agenda.items.values() if i.start.date() == dag(1))
    assert (nu_item.title, nu_item.start, nu_item.end) == (oud_item.title, oud_item.start, oud_item.end)
    assert b._regels(nu_item.notes) == b._regels(oud_item.notes)

    agenda.weiger_bij = None  # daarna lukt het gewoon alsnog
    plan, uit = werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    assert uit.ok and stand(agenda) == NA_STAND


def test_item_met_de_hand_aangepast_tussen_controle_en_schrijven_slaat_de_dag_over():
    agenda, s = _begin()
    nieuw = rooster(NA, gen=GEN + timedelta(days=1), s=s)
    beheer = b.Beheer.laad()
    plan = b.maak_plan(nieuw, nieuw.shifts, agenda, s, beheer, JA)
    agenda.items["n1"] = replace(agenda.items["n1"], title="Ochtend ruilen met Piet")
    uit = b.voer_uit(plan, agenda, beheer, JA)
    assert "intussen veranderd" in uit.niet_bijgewerkt[dag(0)]
    assert agenda.items["n1"].title == "Ochtend ruilen met Piet"
    assert "26 23:00-27 07:00 Nacht" in stand(agenda)


def test_zelf_aangepast_item_wordt_niet_stil_overschreven():
    agenda, s = _begin()
    agenda.items["n1"] = replace(agenda.items["n1"], title="Ochtend (geruild)")
    nieuw = lambda: rooster(NA, gen=GEN + timedelta(days=1), s=s)  # noqa: E731
    plan, uit = werk_bij(agenda, nieuw(), s, JA)
    assert plan.dagen[0].uitkomst == b.ZELF_AANGEPAST and plan.dagen[0].keuze_nodig
    assert agenda.items["n1"].title == "Ochtend (geruild)"

    keuzes = b.Keuzes(verwijderen_bevestigd=True, overschrijf_aangepast={dag(0)})
    plan, uit = werk_bij(agenda, nieuw(), s, keuzes)
    assert uit.ok and stand(agenda) == NA_STAND


def test_vervangen_van_item_met_eigen_notitie_vraagt_eerst():
    agenda, s = _begin()
    agenda.items["n2"] = replace(agenda.items["n2"], notes="Sleutel ophalen\n\n" + agenda.items["n2"].notes)
    plan, uit = werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    assert plan.dagen[1].uitkomst == b.ZELF_AANGEPAST and "n2" in agenda.items


def test_verplaatst_item_blijft_van_de_gebruiker():
    agenda, s = _begin()
    oud = agenda.items["n1"]
    agenda.items["n1"] = replace(oud, start=oud.start + timedelta(days=30), end=oud.end + timedelta(days=30))
    plan, uit = werk_bij(agenda, rooster(VOOR, s=s), s)
    assert plan.dagen[0].uitkomst == b.NIEUW and "n1" in agenda.items


# --- van wie is wat ---------------------------------------------------
def test_twee_medewerkers_in_dezelfde_agenda_blijven_van_elkaar_af():
    agenda = NepAgenda()
    s = instellingen(**ZONDER_VRIJ)
    werk_bij(agenda, rooster(WEEK, nummer="11111111", s=s), s)
    werk_bij(agenda, rooster([[], ["DIENST 14:00-23:00"], [], []], nummer="22222222", s=s), s, JA)
    assert len(agenda.items) == 4  # 3 van de een, 1 van de ander

    werk_bij(agenda, rooster([[], [], [], []], nummer="22222222", gen=GEN + timedelta(days=1), s=s), s, JA)
    assert stand(agenda) == ["23 07:00-23 16:30 Ochtend", "24 07:00-24 16:30 Ochtend",
                             "26 23:00-27 07:00 Nacht"]


def test_eigen_afspraken_zonder_kenmerk_blijven_altijd_staan():
    agenda = NepAgenda()
    agenda.items["eigen"] = AgendaItem("eigen", "Tandarts", datetime(2026, 11, 23, 9),
                                       datetime(2026, 11, 23, 10), notes="niet vergeten")
    werk_bij(agenda, rooster(WEEK))
    werk_bij(agenda, rooster([[], [], [], []], gen=GEN + timedelta(days=1)), keuzes=JA)
    assert agenda.items["eigen"].title == "Tandarts"


@pytest.mark.parametrize("anders,instelling", [
    ({"per_kolom": False}, {}),            # noodstand: kolommen niet herkend
    ({"volledig": False}, {}),             # pagina of dag ontbreekt
    ({"personeelsnummer": ""}, {}),        # niet te zien van wie het is
    ({}, {"calendar_key": ""}),            # agenda zonder vast nummer
])
def test_bij_twijfel_alleen_toevoegen_en_nooit_aanpassen(anders, instelling):
    agenda = NepAgenda()
    s = instellingen(**ZONDER_VRIJ)
    werk_bij(agenda, rooster(VOOR, s=s), s)
    voor = dict(agenda.items)

    s2 = instellingen(**{**ZONDER_VRIJ, **instelling})
    plan, uit = werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s2, **anders), s2, JA)
    assert plan.alleen_toevoegen
    assert all(s_.actie == "voeg_toe" for d in plan.dagen for s_ in d.stappen)
    for nummer, item in voor.items():  # niets aangepast, niets weg
        assert agenda.items[nummer] == item
    # Geen dienst naast een afwijkend eigen item (dat zou een dubbele geven).
    assert [d.uitkomst for d in plan.dagen][:2] == [b.OVERGESLAGEN, b.OVERGESLAGEN]
    assert "26 23:00-27 07:00 Nacht" in stand(agenda)


def test_dag_met_onbegrepen_regel_wordt_helemaal_overgeslagen():
    agenda, s = _begin()
    plan, uit = werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s,
                                         onbegrepen={dag(3): ["???"]}), s, JA)
    assert plan.dagen[3].uitkomst == b.OVERGESLAGEN
    assert "26 23:00-27 07:00 Nacht" not in stand(agenda)
    assert "23 08:00-23 17:00 Ochtend" in stand(agenda)


def test_onbegrepen_regel_buiten_de_dagen_verandert_niets_tot_bevestiging():
    agenda, s = _begin()
    maak = lambda: rooster(NA, gen=GEN + timedelta(days=1), s=s, onbegrepen={None: ["???"]})  # noqa: E731
    geschreven = agenda.schrijfacties
    plan, uit = werk_bij(agenda, maak(), s, JA)
    assert agenda.schrijfacties == geschreven and all(d.keuze_nodig for d in plan.dagen)

    plan, uit = werk_bij(agenda, maak(), s, b.Keuzes(verwijderen_bevestigd=True, onbegrepen_bevestigd=True))
    assert all(s_.actie == "voeg_toe" for d in plan.dagen for s_ in d.stappen)
    assert "26 23:00-27 07:00 Nacht" in stand(agenda) and len(agenda.items) == 4


# --- welk rooster wint ------------------------------------------------
def test_ouder_rooster_verandert_niets_tot_bevestiging_en_de_grens_schuift_niet_terug():
    agenda, s = _begin()
    werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=5), s=s), s, JA)
    assert stand(agenda) == NA_STAND

    oud = lambda dagen=1: rooster(VOOR, gen=GEN + timedelta(days=dagen), s=s)  # noqa: E731
    plan, uit = werk_bij(agenda, oud(), s, JA)
    assert {d.uitkomst for d in plan.dagen} == {b.OUDER_ROOSTER}
    assert stand(agenda) == NA_STAND

    keuzes = b.Keuzes(verwijderen_bevestigd=True, ouder_toestaan=True)
    plan, uit = werk_bij(agenda, oud(), s, keuzes)
    assert uit.ok and len(agenda.items) == 3 and "25 07:00-25 16:30 Ochtend" in stand(agenda)

    # Een volgend ouder rooster krijgt opnieuw de waarschuwing.
    plan, uit = werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=2), s=s), s, JA)
    assert b.OUDER_ROOSTER in {d.uitkomst for d in plan.dagen}
    assert len(agenda.items) == 3


def test_concept_na_definitief_geldt_als_ouder():
    agenda, s = _begin()
    plan, uit = werk_bij(agenda, rooster(NA, concept=True, gen=GEN + timedelta(days=9), s=s), s, JA)
    assert {d.uitkomst for d in plan.dagen} == {b.OUDER_ROOSTER}


def test_zelfde_datum_andere_inhoud_laat_de_gebruiker_beslissen():
    agenda, s = _begin()
    plan, uit = werk_bij(agenda, rooster(NA, s=s), s, JA)  # zelfde generatiedatum
    assert {d.uitkomst for d in plan.dagen} == {b.ANDERE_INHOUD}
    assert len(agenda.items) == 3


def test_vervallen_dienst_komt_niet_terug_door_een_ouder_rooster():
    agenda, s = _begin()
    werk_bij(agenda, rooster([[], [], [], []], gen=GEN + timedelta(days=5), s=s), s, JA)
    assert not agenda.items
    plan, uit = werk_bij(agenda, rooster(VOOR, gen=GEN + timedelta(days=1), s=s), s, JA)
    assert not agenda.items and b.OUDER_ROOSTER in {d.uitkomst for d in plan.dagen}


def test_tweede_apparaat_zonder_geheugen_ziet_de_rang_in_de_agenda():
    agenda, s = _begin()
    b.beheer_pad().unlink()  # ander apparaat: zelfde agenda, geen beheer.json
    plan, uit = werk_bij(agenda, rooster(NA, concept=True, gen=GEN - timedelta(days=1), s=s), s, JA)
    assert b.OUDER_ROOSTER in {d.uitkomst for d in plan.dagen}
    assert stand(agenda)[0] == "23 07:00-23 16:30 Ochtend"


def test_andere_instelling_is_geen_ander_rooster():
    agenda, s = _begin()
    s2 = instellingen(**ZONDER_VRIJ)
    s2.names["ochtend"] = "Vroeg"
    plan, uit = werk_bij(agenda, rooster(VOOR, s=s2), s2, JA)
    assert {d.uitkomst for d in plan.dagen} == {b.GEWIJZIGD, b.STAAT_ER_AL}
    assert uit.ok and "23 07:00-23 16:30 Vroeg" in stand(agenda)


# --- nachtdienst en periodegrens --------------------------------------
def test_nachtdienst_van_vorige_periode_blijft_staan():
    agenda = NepAgenda()
    s = instellingen(**ZONDER_VRIJ)
    vorige = rooster([["DIENST 23:00-07:00"]], eerste=D1 - timedelta(days=1), s=s)
    werk_bij(agenda, vorige, s)
    assert stand(agenda) == ["22 23:00-23 07:00 Nacht"]
    werk_bij(agenda, rooster([[], []], gen=GEN + timedelta(days=1), s=s), s, JA)
    assert stand(agenda) == ["22 23:00-23 07:00 Nacht"]


def test_nachtdienst_op_laatste_dag_hoort_bij_zijn_roosterdag():
    agenda = NepAgenda()
    s = instellingen(**ZONDER_VRIJ)
    werk_bij(agenda, rooster([["DIENST 23:00-07:00"]], s=s), s)
    plan, uit = werk_bij(agenda, rooster([["DIENST 22:00-06:00"]], gen=GEN + timedelta(days=1), s=s), s)
    assert uit.ok and stand(agenda) == ["23 22:00-24 06:00 Nacht"]


# --- ongedaan maken ---------------------------------------------------
def test_ongedaan_maken_zet_agenda_en_geheugen_terug():
    agenda, s = _begin()
    voor = stand(agenda)
    beheer_voor = b.beheer_pad().read_text(encoding="utf-8")
    werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    assert b.kan_ongedaan()

    terug = b.maak_ongedaan(agenda, b.Beheer.laad())
    assert not terug.fouten and not terug.blijft_staan
    assert stand(agenda) == voor
    assert b.beheer_pad().read_text(encoding="utf-8") == beheer_voor
    assert not b.kan_ongedaan()
    # Het nieuwere rooster kan daarna gewoon opnieuw verwerkt worden.
    plan, uit = werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    assert uit.ok and stand(agenda) == NA_STAND


def test_ongedaan_maken_laat_met_de_hand_aangepaste_items_staan():
    agenda, s = _begin()
    werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    nacht = next(k for k, i in agenda.items.items() if i.title == "Nacht")
    agenda.items[nacht] = replace(agenda.items[nacht], title="Nacht (ruilen?)")
    terug = b.maak_ongedaan(agenda, b.Beheer.laad())
    assert terug.blijft_staan == ["26-11-2026 Nacht (ruilen?)"]
    assert nacht in agenda.items
    assert "23 07:00-23 16:30 Ochtend" in stand(agenda)


@pytest.mark.parametrize("na_uitvoeren", [False, True])
@pytest.mark.parametrize("n", range(1, 7))
def test_ongedaan_maken_na_afgebroken_bijwerking_geeft_geen_dubbelen(n, na_uitvoeren):
    agenda, s = _begin()
    voor = stand(agenda)
    agenda.breek_bij, agenda.breek_na_uitvoeren = agenda.schrijfacties + n, na_uitvoeren
    with pytest.raises(Uitgevallen):
        werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    agenda.breek_bij = None
    terug = b.maak_ongedaan(agenda, b.Beheer.laad())
    assert not terug.fouten
    assert stand(agenda) == voor


# --- overstap van versie 1 --------------------------------------------
def _v1(agenda, nummer, titel, start, end, notes="[WerkroosterSync:0123456789ab]"):
    agenda.items[nummer] = AgendaItem(nummer, titel, start, end, notes=notes)


def _oude_agenda():
    agenda = NepAgenda()
    _v1(agenda, "o1", "Ochtend", datetime(2026, 11, 23, 7), datetime(2026, 11, 23, 16, 30))
    _v1(agenda, "o2", "Administratief afhandelen", datetime(2026, 11, 23, 12), datetime(2026, 11, 23, 16, 30))
    return agenda


def test_oude_items_zonder_bevestiging_met_rust_laten_en_niet_verdubbelen():
    agenda = _oude_agenda()
    s = instellingen(**ZONDER_VRIJ)
    plan, uit = werk_bij(agenda, rooster([["DIENST 07:00-16:30"]], s=s), s, JA)
    assert plan.oude_items == 2
    assert sorted(agenda.items) == ["o1", "o2"] and agenda.schrijfacties == 0


def test_oude_items_na_bevestiging_overnemen_en_de_rest_laten_kiezen():
    agenda = _oude_agenda()
    s = instellingen(**ZONDER_VRIJ)
    ja = b.Keuzes(verwijderen_bevestigd=True, oude_items_zijn_van_mij=True)
    plan, uit = werk_bij(agenda, rooster([["DIENST 07:00-16:30"]], s=s), s, ja)
    assert plan.dagen[0].uitkomst == b.MOGELIJK_DUBBEL and plan.dagen[0].keuze_nodig
    assert agenda.schrijfacties == 0

    ja.vervang_oude_items = {D1}
    plan, uit = werk_bij(agenda, rooster([["DIENST 07:00-16:30"]], s=s), s, ja)
    assert uit.ok and sorted(agenda.items) == ["o1"]
    overgenomen = b.Gelezen.van(agenda.items["o1"])
    assert overgenomen.versie == 2 and not overgenomen.aangepast
    assert "0123456789ab" not in agenda.items["o1"].notes
    # De bevestiging is onthouden; een volgende keer hoeft de vraag niet opnieuw.
    assert b.Beheer.laad().agenda(plan.beheer_sleutel)["oude_items_van_mij"] is True


def test_stoppen_als_de_agenda_iets_anders_teruggeeft_dan_geschreven():
    class Eigenwijs(NepAgenda):
        def read_items(self, name, key, start, end):
            return [replace(i, start=i.start + timedelta(hours=1), end=i.end + timedelta(hours=1))
                    for i in super().read_items(name, key, start, end)]

    agenda = Eigenwijs()
    plan, uit = werk_bij(agenda, rooster(WEEK))
    assert any("anders terug" in f for f in uit.fouten)
    assert len(agenda.items) == 1  # na de eerste dag gestopt


# --- uit de nalezing van 20-11-2026 -----------------------------------
def test_ongedaan_maken_opnieuw_proberen_na_een_fout_geeft_geen_dubbelen():
    agenda, s = _begin()
    voor = stand(agenda)
    werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    agenda.weiger_bij = agenda.schrijfacties + 2
    assert b.maak_ongedaan(agenda, b.Beheer.laad()).fouten
    agenda.weiger_bij = None
    terug = b.maak_ongedaan(agenda, b.Beheer.laad())
    assert not terug.fouten and not terug.blijft_staan
    assert stand(agenda) == voor


@pytest.mark.parametrize("n", range(1, 7))
def test_uitval_hervatten_en_dan_ongedaan_maken(n):
    agenda, s = _begin()
    voor = stand(agenda)
    agenda.breek_bij = agenda.schrijfacties + n
    with pytest.raises(Uitgevallen):
        werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    agenda.breek_bij = None
    plan, uit = werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    assert uit.ok and stand(agenda) == NA_STAND
    terug = b.maak_ongedaan(agenda, b.Beheer.laad())
    assert not terug.fouten and stand(agenda) == voor


def test_ronde_zonder_werk_laat_de_vorige_bijwerking_ongedaan_te_maken():
    agenda, s = _begin()
    voor = stand(agenda)
    werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)  # niets te doen
    assert b.kan_ongedaan()
    assert not b.maak_ongedaan(agenda, b.Beheer.laad()).fouten
    assert stand(agenda) == voor


def test_ongedaan_maken_weigert_een_andere_agenda_app():
    agenda, s = _begin()
    werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    ander = NepAgenda()
    ander.id = "ander"
    assert b.maak_ongedaan(ander, b.Beheer.laad()).fouten
    assert ander.schrijfacties == 0 and b.kan_ongedaan()


def test_half_gelukte_aanpassing_wordt_ook_teruggezet():
    class Half(NepAgenda):
        half = False

        def update_item(self, name, key, item):
            if self.half:  # titel en tijd gaan erin, dan een fout
                oud = self.items[item.native_id]
                self.items[item.native_id] = replace(oud, title=item.title,
                                                     start=item.start, end=item.end)
                self.half = False
                raise b.CalendarError("notitie mislukt")
            return super().update_item(name, key, item)

    agenda = Half()
    s = instellingen(**ZONDER_VRIJ)
    werk_bij(agenda, rooster(VOOR, s=s), s)
    voor = dict(agenda.items)
    agenda.half = True
    plan, uit = werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    assert "teruggezet" in uit.niet_bijgewerkt[D1]
    a, v = agenda.items["n1"], voor["n1"]
    assert (a.title, a.start, a.end) == (v.title, v.start, v.end)
    assert b._regels(a.notes) == b._regels(v.notes)
    # Volgende ronde: geen "zelf aangepast", gewoon bijwerken.
    plan, uit = werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    assert uit.ok and stand(agenda) == NA_STAND


def test_oud_item_met_eigen_notitie_wordt_niet_stil_overschreven():
    agenda = NepAgenda()
    _v1(agenda, "o1", "Ochtend", datetime(2026, 11, 23, 7), datetime(2026, 11, 23, 16, 30),
        notes="sleutel bij buurman\n\n[WerkroosterSync:0123456789ab]")
    s = instellingen(**ZONDER_VRIJ)
    ja = b.Keuzes(verwijderen_bevestigd=True, oude_items_zijn_van_mij=True)
    plan, uit = werk_bij(agenda, rooster([["DIENST 07:00-16:30"]], s=s), s, ja)
    assert plan.dagen[0].uitkomst == b.ZELF_AANGEPAST and plan.dagen[0].keuze_nodig
    assert agenda.schrijfacties == 0


def test_oud_item_dat_net_niet_past_geeft_geen_stille_dubbele():
    agenda = NepAgenda()
    _v1(agenda, "o1", "Ochtend", datetime(2026, 11, 23, 7), datetime(2026, 11, 23, 16, 30))
    s = instellingen(**ZONDER_VRIJ)
    plan, uit = werk_bij(agenda, rooster([["DIENST 08:00-17:00"]], s=s), s, JA)
    assert plan.dagen[0].uitkomst == b.MOGELIJK_DUBBEL and plan.dagen[0].keuze_nodig
    assert agenda.schrijfacties == 0


def test_eigen_locatie_gaat_niet_stil_verloren():
    agenda = NepAgenda()
    werk_bij(agenda, rooster(WEEK))
    agenda.items["n1"] = replace(agenda.items["n1"], location="Zaal 4")
    gesplitst = [["DIENST 07:00-12:00", "DIENST 13:00-18:30"]] + WEEK[1:]
    plan, uit = werk_bij(agenda, rooster(gesplitst, gen=GEN + timedelta(days=1)), keuzes=JA)
    assert plan.dagen[0].uitkomst == b.ZELF_AANGEPAST and plan.dagen[0].keuze_nodig
    assert agenda.items["n1"].location == "Zaal 4"


def test_ongedaan_maken_laat_item_met_eigen_locatie_staan():
    agenda, s = _begin()
    werk_bij(agenda, rooster(NA, gen=GEN + timedelta(days=1), s=s), s, JA)
    nacht = next(k for k, i in agenda.items.items() if i.title == "Nacht")
    agenda.items[nacht] = replace(agenda.items[nacht], location="Post Noord")
    terug = b.maak_ongedaan(agenda, b.Beheer.laad())
    assert nacht in agenda.items and terug.blijft_staan


def test_na_bevestigd_ouder_rooster_wint_het_nieuwste_weer_zonder_vraag():
    agenda = NepAgenda()
    nieuw = [["DIENST 08:00-17:00"]] + WEEK[1:]
    werk_bij(agenda, rooster(nieuw, gen=GEN + timedelta(days=5)))
    werk_bij(agenda, rooster(WEEK), keuzes=b.Keuzes(ouder_toestaan=True))
    assert stand(agenda) == WEEK_STAND
    plan, uit = werk_bij(agenda, rooster(nieuw, gen=GEN + timedelta(days=5)))
    assert not any(d.keuze_nodig for d in plan.dagen) and uit.ok
    # En het oudere rooster vraagt weer om bevestiging.
    plan, _ = werk_bij(agenda, rooster(WEEK))
    assert plan.dagen[0].uitkomst == b.OUDER_ROOSTER


def test_zonder_geheugen_en_zonder_datum_niet_stil_overschrijven():
    agenda = NepAgenda()
    werk_bij(agenda, rooster(WEEK))
    b.beheer_pad().unlink()  # bv. een tweede computer
    ander = [["DIENST 08:00-17:00"]] + WEEK[1:]
    plan, _ = werk_bij(agenda, rooster(ander, gen=None))
    assert plan.dagen[0].uitkomst == b.ANDERE_INHOUD and plan.dagen[0].keuze_nodig
    plan, _ = werk_bij(agenda, rooster(ander, gen=None, concept=True))
    assert plan.dagen[0].uitkomst == b.OUDER_ROOSTER
    assert stand(agenda) == WEEK_STAND


def test_dubbel_kenmerk_wordt_bij_overschrijven_opgeruimd():
    agenda = NepAgenda()
    werk_bij(agenda, rooster(WEEK))
    i = agenda.items["n1"]
    kenmerk = b.KENMERK_RE.search(i.notes).group(0)
    agenda.items["n1"] = replace(i, notes=i.notes + "\n\nmijn tekst " + kenmerk)
    nieuw = [["DIENST 08:00-17:00"]] + WEEK[1:]
    keuzes = b.Keuzes(overschrijf_aangepast={D1})
    plan, uit = werk_bij(agenda, rooster(nieuw, gen=GEN + timedelta(days=1)), keuzes=keuzes)
    assert uit.ok, uit
    g = b.Gelezen.van(agenda.items["n1"])
    assert not g.aangepast and len(b.KENMERK_RE.findall(agenda.items["n1"].notes)) == 1
    assert "mijn tekst" in agenda.items["n1"].notes


def test_gelezen_scheidt_eigen_tekst_van_het_blok():
    g = b.gewenst_uit(rooster(WEEK).shifts[0], GEN)
    item = g.als_item("abcdef0123")
    item.notes = "boven\n\n" + item.notes + "\n\nonder"
    gelezen = b.Gelezen.van(item)
    assert gelezen.versie == 2 and not gelezen.aangepast
    assert gelezen.eigen_tekst == (["boven"], ["onder"])
    assert b.Gelezen.van(replace(item, title="Anders")).aangepast


def test_alleen_toevoegen_ziet_de_dienst_van_een_collega_niet_als_de_jouwe():
    agenda = NepAgenda()
    werk_bij(agenda, rooster(WEEK, nummer="11111111"))
    plan, uit = werk_bij(agenda, rooster(WEEK, nummer="22222222", volledig=False))
    assert plan.alleen_toevoegen and uit.ok
    assert len(agenda.items) == 8


def test_dienst_die_niet_op_zijn_roosterdag_begint_wordt_overgeslagen():
    agenda = NepAgenda()
    r = rooster(WEEK)
    r.shifts[0].roster_date = dag(1)
    plan, uit = werk_bij(agenda, r)
    assert plan.dagen[1].uitkomst == b.OVERGESLAGEN


def test_vaste_uids_zijn_gelijk_voor_een_nieuwere_versie_van_het_rooster():
    a, c = rooster(WEEK), rooster(WEEK, gen=GEN + timedelta(days=3), concept=True)
    b.vaste_uids(a.shifts, "12345678")
    b.vaste_uids(c.shifts, "12345678")
    assert [x.uid for x in a.shifts] == [x.uid for x in c.shifts]
    assert len({x.uid for x in a.shifts}) == len(a.shifts)
    assert "12345678" not in a.shifts[0].uid
    ander = rooster(WEEK)
    b.vaste_uids(ander.shifts, "87654321")
    assert ander.shifts[0].uid != a.shifts[0].uid


def test_agenda_kiezen_op_vast_nummer_en_naam():
    class Lijst(NepAgenda):
        def calendars(self):
            return [("Werk", "k1"), ("Thuis", "k2"), ("Dubbel", "k3"), ("Dubbel", "k4")]
    a = Lijst()
    assert b.agenda_kiezen(a, "Oude naam", "k1") == ("Werk", "k1")   # hernoemd
    assert b.agenda_kiezen(a, "Thuis", "") == ("Thuis", "k2")
    assert b.agenda_kiezen(a, "Dubbel", "") == ("Dubbel", "")        # niet eenduidig
    assert b.agenda_kiezen(a, "Werk", "weg") == ("Werk", "")          # verwijderd


def test_meerdere_roosters_nieuwste_definitieve_als_laatste():
    oud_def = rooster(WEEK, gen=GEN)
    concept = rooster(WEEK, gen=GEN + timedelta(days=9), concept=True)
    nieuw_def = rooster(WEEK, gen=GEN + timedelta(days=5))
    assert b.op_rangvolgorde([nieuw_def, concept, oud_def]) == [concept, oud_def, nieuw_def]


def test_mac_hele_dag_einde_heen_en_terug():
    """Agenda wil bij een hele dag de laatste dag zelf en geeft 23:59:59 terug."""
    from werkrooster_sync.calendars.base import AgendaItem
    from werkrooster_sync.calendars.macos_calendar import _eind_uit_agenda, _eind_voor_agenda

    d = datetime(2026, 11, 21)
    een = AgendaItem(start=d, end=d + timedelta(days=1), all_day=True)
    assert _eind_voor_agenda(een) == d
    drie = AgendaItem(start=d, end=d + timedelta(days=3), all_day=True)
    assert _eind_voor_agenda(drie) == d + timedelta(days=2)
    tijd = AgendaItem(start=d.replace(hour=7), end=d.replace(hour=16), all_day=False)
    assert _eind_voor_agenda(tijd) == d.replace(hour=16)
    assert _eind_uit_agenda(d, d.replace(hour=23, minute=59, second=59), True) == d + timedelta(days=1)
    assert _eind_uit_agenda(d, d + timedelta(days=1, hours=23, minutes=59, seconds=59), True) \
        == d + timedelta(days=2)
    assert _eind_uit_agenda(d, d + timedelta(days=1), True) == d + timedelta(days=1)
    assert _eind_uit_agenda(d.replace(hour=7), d.replace(hour=16), False) == d.replace(hour=16)


def test_mac_agenda_zonder_eigen_nummer_krijgt_naam(monkeypatch):
    """Agenda op macOS 27 geeft geen calendarIdentifier; zonder vast nummer
    zou de app alleen nog toevoegen."""
    from werkrooster_sync.calendars import macos_calendar as mc

    monkeypatch.setattr(mc, "_run", lambda *a, **k: f"Werk{mc._SEP}{mc._ROW}Thuis{mc._SEP}ABC{mc._ROW}")
    assert mc.MacCalendarBackend().calendars() == [("Werk", "naam:Werk"), ("Thuis", "ABC")]
    ref = mc.MacCalendarBackend()._cal("Werk", "naam:Werk")
    assert "wsAgenda" in ref and '"Werk"' in ref


def test_journaal_overleeft_vreemd_teken_en_halve_laatste_regel():
    import json
    pad = b.journaal_pad()
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_text(json.dumps({"fase": "begin"}) + "\n"
                   + json.dumps({"n": 1, "notitie": "regel twee"}, ensure_ascii=False)
                   + "\n" + '{"n": 2, "fa', encoding="utf-8")
    assert [r.get("n") for r in b._lees_journaal()] == [None, 1]
    pad.write_text('{"fase": "begin"}\n{kapot\n{"n": 3}\n', encoding="utf-8")
    assert b._lees_journaal() == []
