"""Tests for the BVCM PDF roster reader."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from werkrooster_sync.core.classifier import apply_classification
from werkrooster_sync.core.ics_parser import IcsParseError
from werkrooster_sync.core.pdf_parser import PdfParseError, parse_pdf
from werkrooster_sync.core.models import ShiftType
from werkrooster_sync.core.settings import Settings

CONCEPT = Path(__file__).parent / "sample_bvcm_concept.pdf"
DEFINITIEF = Path(__file__).parent / "sample_bvcm_definitief.pdf"


def classified(path, settings=None):
    s = settings or Settings()
    return apply_classification(parse_pdf(path, s), s), s


def by_date(shifts, y, m, d):
    return [x for x in shifts if x.start.date() == datetime(y, m, d).date()]


def test_definitief_pdf_parses_and_classifies():
    shifts, _ = classified(DEFINITIEF)

    # Empty day becomes Vrij
    vrij = by_date(shifts, 2026, 7, 18)
    assert len(vrij) == 1
    assert vrij[0].shift_type == ShiftType.VRIJ
    assert vrij[0].is_concept is False

    # DIENST with times from the entry text -> real timed shift
    dienst = by_date(shifts, 2026, 7, 20)[0]
    assert dienst.shift_type == ShiftType.OCHTEND
    assert not dienst.all_day
    assert dienst.start == datetime(2026, 7, 20, 7, 0)
    assert dienst.end == datetime(2026, 7, 20, 16, 0)
    assert dienst.display_name == "Ochtend"  # no concept suffix

    # ZIEK keeps its own (time-stripped) title
    ziek = by_date(shifts, 2026, 7, 21)[0]
    assert ziek.shift_type == ShiftType.AFSPRAAK
    assert ziek.display_name == "ZIEK"
    assert ziek.start == datetime(2026, 7, 21, 10, 0)

    # Continuation line [Rust] belongs to the same day and is ignored noise
    wo = by_date(shifts, 2026, 7, 22)
    assert {x.shift_type for x in wo} == {ShiftType.LAAT, ShiftType.NEGEREN}

    # Vr.zondag day: vrij + the full-day rust row as noise
    zo = by_date(shifts, 2026, 7, 26)
    assert ShiftType.VRIJ in {x.shift_type for x in zo}

    # Night shift wraps past midnight
    nacht = by_date(shifts, 2026, 7, 27)[0]
    assert nacht.shift_type == ShiftType.NACHT
    assert nacht.end == datetime(2026, 7, 28, 7, 30)
    # Memo is attached as note
    assert "extra briefing" in nacht.description


def test_concept_pdf_flags_everything_as_concept():
    shifts, _ = classified(CONCEPT)
    assert all(x.is_concept for x in shifts)
    dienst = by_date(shifts, 2026, 7, 20)[0]
    assert dienst.display_name == "Ochtend (concept)"

    # Full-day [Rust] on an otherwise empty day counts as Vrij; the rust row
    # itself stays visible as (grey) noise.
    day = by_date(shifts, 2026, 7, 18)
    vrij = [x for x in day if x.shift_type == ShiftType.VRIJ]
    assert len(vrij) == 1
    assert vrij[0].display_name == "Vrij (concept)"


def test_empty_day_option_can_be_disabled():
    s = Settings()
    s.rules["empty_day_is_vrij"] = False
    shifts, _ = classified(DEFINITIEF, s)
    assert by_date(shifts, 2026, 7, 18) == []


def test_pdf_sync_ids_are_deterministic():
    ids1 = [x.sync_id for x in classified(DEFINITIEF)[0]]
    ids2 = [x.sync_id for x in classified(DEFINITIEF)[0]]
    assert ids1 == ids2
    assert all(ids1)


def test_pdf_parse_error_is_catchable_as_ics_error(tmp_path):
    bad = tmp_path / "geen_rooster.pdf"
    bad.write_bytes(b"%PDF-1.4 not really a pdf")
    with pytest.raises(IcsParseError):
        parse_pdf(bad, Settings())
    assert issubclass(PdfParseError, IcsParseError)


# ----------------------------------------------------------------------
# Lezen per kolom (2.0)
# ----------------------------------------------------------------------
from datetime import date

from tests.maak_testrooster import lees_paginas, schrijf_pdf
from werkrooster_sync.core.pdf_parser import read_roster

BLOKKEN = Path(__file__).parent / "rooster_blokken_definitief.pdf"
BLOKKEN_CONCEPT = Path(__file__).parent / "rooster_blokken_concept.pdf"


def aangepast(tmp_path, bewerk, bron=BLOKKEN):
    """Een kopie van het testrooster waarin *bewerk* de pagina's aanpast."""
    paginas = [(b, h, list(stukjes)) for b, h, stukjes in lees_paginas(bron)]
    paginas = bewerk(paginas) or paginas
    doel = tmp_path / "rooster.pdf"
    schrijf_pdf(paginas, doel)
    return read_roster(doel)


def test_kop_van_het_rooster_wordt_gelezen():
    r = read_roster(BLOKKEN)
    assert r.per_kolom and r.volledig and not r.is_concept
    assert r.periode == (date(2027, 4, 30), date(2027, 5, 9))
    assert r.personeelsnummer == "12345678"
    assert r.gegenereerd == datetime(2027, 4, 30, 17, 38)
    assert not r.meldingen and not r.onbegrepen
    assert all(r.mag_aanpassen(s.roster_date) for s in r.shifts)

    c = read_roster(BLOKKEN_CONCEPT)
    assert c.is_concept and c.volledig
    assert c.periode == (date(2027, 5, 10), date(2027, 6, 10))


def test_tijdsblokken_en_memo_komen_in_notitie_en_titel():
    r = read_roster(BLOKKEN)
    teamdag = [s for s in r.shifts if s.roster_date == date(2027, 5, 4)]
    assert len(teamdag) == 1
    assert teamdag[0].original_summary == "DIENST 09:30-20:00"
    assert teamdag[0].info == "Teamdag"
    assert teamdag[0].description.splitlines() == [
        "Activiteit: Teamdag",
        "09:30-14:30 Teamdag",
        "14:30-15:00 Pauze (onbetaald)",
        "15:00-20:00 Teamdag",
    ]


def test_dag_over_paginawissel_is_een_dienst():
    r = read_roster(BLOKKEN)
    vr = [s for s in r.shifts if s.roster_date == date(2027, 5, 7)]
    assert len(vr) == 1
    assert [x.split()[0] for x in vr[0].description.splitlines()[1:]] == [
        "07:00-11:30", "11:30-12:00", "12:00-16:30"]


def test_woord_in_activiteit_gooit_de_soort_niet_om(tmp_path):
    def bewerk(paginas):
        b, h, stukjes = paginas[0]
        paginas[0] = (b, h, [
            (x, y, g, v, " Nachtelijke oefening vrij" if "Administratief" in t else t)
            for x, y, g, v, t in stukjes])
    r = aangepast(tmp_path, bewerk)
    s = Settings()
    soorten = {x.roster_date: x.shift_type
               for x in apply_classification(r.shifts, s)}
    assert soorten[date(2027, 4, 30)] == ShiftType.OCHTEND


def test_onbegrepen_regel_blokkeert_alleen_die_dag(tmp_path):
    def bewerk(paginas):
        b, h, stukjes = paginas[0]
        # Een losse regel in de kolom Dag, tussen 03/05 en 04/05.
        stukjes.append((30.0, 258.0, 9.0, False, "Iets wat de app niet kent"))
    r = aangepast(tmp_path, bewerk)
    assert r.onbegrepen == {date(2027, 5, 3): ["Iets wat de app niet kent"]}
    assert not r.mag_aanpassen(date(2027, 5, 3))
    assert r.mag_aanpassen(date(2027, 5, 4))
    assert any("03-05-2027" in m and "Iets wat" in m for m in r.meldingen)


def test_ontbrekende_pagina_maakt_het_rooster_onvolledig(tmp_path):
    r = aangepast(tmp_path, lambda paginas: paginas[:1])
    assert r.per_kolom and not r.volledig
    assert not r.mag_aanpassen(date(2027, 4, 30))
    assert any("niet compleet" in m for m in r.meldingen)
    # Wat wel gelezen is komt er gewoon uit.
    assert any(s.roster_date == date(2027, 4, 30) for s in r.shifts)


def test_dag_buiten_de_periode_telt_niet_mee(tmp_path):
    def bewerk(paginas):
        b, h, stukjes = paginas[1]
        stukjes += [(87.0, 460.0, 9.0, False, "10/05/2027"),
                    (30.0, 460.0, 9.0, False, "Maandag"),
                    (144.0, 460.0, 9.0, False, " [Rust] 00:00-07:00")]
    r = aangepast(tmp_path, bewerk)
    assert r.volledig
    assert max(s.roster_date for s in r.shifts) == date(2027, 5, 9)


def test_andere_kolomposities_worden_uit_de_kop_gelezen(tmp_path):
    def bewerk(paginas):
        # Alles vanaf de kolom Tijdstippen schuift 40 punten naar rechts.
        return [(b, h, [(x + 40 if x > 250 and y > 40 else x, y, g, v, t)
                        for x, y, g, v, t in stukjes])
                for b, h, stukjes in paginas]
    r = aangepast(tmp_path, bewerk)
    assert r.per_kolom and r.volledig and not r.onbegrepen
    assert [s.original_summary for s in r.shifts
            if s.roster_date == date(2027, 5, 4)] == ["DIENST 09:30-20:00"]


def test_zonder_herkenbare_kop_valt_de_app_terug_op_de_oude_manier():
    r = read_roster(DEFINITIEF)  # nagemaakt voorbeeld zonder losse kolommen
    assert not r.per_kolom and not r.volledig
    assert not r.mag_aanpassen(date(2026, 7, 20))
    assert any("niet herkend" in m for m in r.meldingen)
    assert r.shifts and all(s.roster_date for s in r.shifts)


# --- Aanscherpingen na tegenlezing: liever melden dan stil verkeerd lezen ---
def _erbij(pagina, *stukjes):
    def bewerk(paginas):
        paginas[pagina][2].extend((x, y, 9.0, False, t) for x, y, t in stukjes)
    return bewerk


def test_mag_aanpassen_alleen_binnen_de_periode():
    r = read_roster(BLOKKEN)
    assert r.mag_aanpassen(date(2027, 5, 9))
    assert not r.mag_aanpassen(date(2027, 5, 10))
    assert not r.mag_aanpassen(date(2020, 1, 1))


def test_onbegrepen_regel_op_dag_buiten_periode_blokkeert_alles(tmp_path):
    r = aangepast(tmp_path, _erbij(1, (87.0, 460.0, "10/05/2027"), (30.0, 460.0, "Maandag"),
                                   (30.0, 448.0, "Onbekend ding")))
    assert r.onbegrepen == {None: ["Onbekend ding"]}
    assert not r.mag_aanpassen(date(2027, 5, 3))


def test_losse_tekst_in_kolom_soort_wordt_geen_dienst(tmp_path):
    r = aangepast(tmp_path, _erbij(0, (150.0, 396.0, "Rommel")))
    assert r.onbegrepen == {date(2027, 4, 30): ["Rommel"]}
    assert [s.original_summary for s in r.shifts
            if s.roster_date == date(2027, 4, 30)] == ["DIENST 07:00-16:30"]


def test_regel_direct_onder_de_kop_wordt_niet_stil_weggegooid(tmp_path):
    def bewerk(paginas):
        b, h, stukjes = paginas[1]
        stukjes[:] = [s for s in stukjes if s[4].strip() not in ("dienst", "gebied", "snelcode")]
        stukjes.append((507.0, 540.0, 9.0, False, "afhandelen"))
    r = aangepast(tmp_path, bewerk)
    assert r.onbegrepen == {date(2027, 5, 7): ["afhandelen"]}


def test_tekst_zonder_tijd_wordt_niet_aan_een_ander_blok_geplakt(tmp_path):
    r = aangepast(tmp_path, _erbij(0, (507.0, 384.0, "Losse tekst")))
    assert r.onbegrepen == {date(2027, 4, 30): ["Losse tekst"]}


def test_herhaalde_datum_midden_op_de_pagina_is_onbegrepen(tmp_path):
    r = aangepast(tmp_path, _erbij(0, (87.0, 346.0, "30/04/2027"), (30.0, 346.0, "Vrijdag"),
                                   (144.0, 346.0, "DIENST 07:00-16:30")))
    assert date(2027, 4, 30) in r.onbegrepen
    assert len([s for s in r.shifts if s.roster_date == date(2027, 4, 30)]) == 1


def test_verkeerde_weekdag_bij_datum_is_onbegrepen(tmp_path):
    def bewerk(paginas):
        b, h, stukjes = paginas[0]
        paginas[0] = (b, h, [(x, y, g, v, "Maandag" if t == "Zondag" else t)
                             for x, y, g, v, t in stukjes])
    r = aangepast(tmp_path, bewerk)
    assert not r.mag_aanpassen(date(2027, 5, 2))
    assert r.onbegrepen
    # Een onbegrepen dag krijgt geen verzonnen "Vrij".
    assert not [s for s in r.shifts if s.roster_date == date(2027, 5, 2)]


def test_dubbel_paginanummer_maakt_onvolledig(tmp_path):
    def bewerk(paginas):
        b, h, stukjes = paginas[1]
        paginas[1] = (b, h, [(x, y, g, v, t.replace("Pagina 2 van 2", "Pagina 1 van 2"))
                             for x, y, g, v, t in stukjes])
    assert not aangepast(tmp_path, bewerk).volledig
