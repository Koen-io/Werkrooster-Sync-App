"""Fase 4: dienstsoorten als vrije lijst, onbekende codes."""
from __future__ import annotations

from datetime import datetime

from werkrooster_sync.core.classifier import apply_classification, onbekende_codes
from werkrooster_sync.core.models import Shift, ShiftType
from werkrooster_sync.core.settings import (DEFAULT_DIENSTSOORTEN, Settings,
                                            controleer_dienstsoorten)


def dienst(soort: str, dag=datetime(2026, 11, 23)) -> Shift:
    return Shift(start=dag, end=dag.replace(day=dag.day + 1), original_summary=soort, all_day=True)


def deel_in(*soorten, s=None, dag=datetime(2026, 11, 23)):
    return apply_classification([dienst(x, dag) for x in soorten], s or Settings())


def test_standaard_drie_soorten_op_begintijd():
    uit = deel_in("DIENST 07:00-16:30", "DIENST 13:00-21:30", "DIENST 22:00-07:00")
    assert [x.shift_type for x in uit] == [ShiftType.OCHTEND, ShiftType.LAAT, ShiftType.NACHT]


def test_nachtdienst_over_middernacht():
    (x,) = deel_in("DIENST 23:00-07:00")
    assert x.shift_type == ShiftType.NACHT
    assert (x.start, x.end) == (datetime(2026, 11, 23, 23), datetime(2026, 11, 24, 7))


def test_eindtijd_24_00():
    (x,) = deel_in("DIENST 16:00-24:00")
    assert x.end == datetime(2026, 11, 24, 0) and x.shift_type == ShiftType.LAAT


def test_wisseling_zomer_en_wintertijd():
    # Nacht van 24 op 25 oktober 2026 (klok terug) en 28 op 29 maart 2026 (klok vooruit):
    # de agenda krijgt de tijden zoals ze in het rooster staan.
    for dag in (datetime(2026, 10, 24), datetime(2026, 3, 28)):
        (x,) = deel_in("DIENST 23:00-07:00", dag=dag)
        assert x.shift_type == ShiftType.NACHT
        assert (x.start.hour, x.end.hour, (x.end - x.start).days) == (23, 7, 0)
        assert x.end.date() == dag.date().replace(day=dag.day + 1)


def test_meerdere_soorten_op_een_dag():
    uit = deel_in("DIENST 07:00-12:00", "DIENST 13:00-18:30")
    assert [x.shift_type for x in uit] == [ShiftType.OCHTEND, ShiftType.LAAT]


def test_eigen_dienstsoort_met_eigen_naam():
    s = Settings()
    s.dienstsoorten = [d for d in s.dienstsoorten if d["id"] != "ochtend"]
    sid = s.nieuwe_dienstsoort("Vroeg", "05:00", "08:00")
    s.dienstsoorten.append({"id": "dag", "van": "08:00", "tot": "12:00", "kleur": "#fff"})
    s.names["dag"] = "Dagdienst"
    uit = deel_in("DIENST 06:00-14:00", "DIENST 09:00-17:00", s=s)
    assert [(x.shift_type, x.soort, x.display_name) for x in uit] == [
        (ShiftType.DIENST, sid, "Vroeg"), (ShiftType.DIENST, "dag", "Dagdienst")]
    assert uit[0].reminder_minutes == 60


def test_begintijd_buiten_elk_vak_wordt_dienst():
    s = Settings()
    s.verwijder_dienstsoort("ochtend")
    (x,) = deel_in("DIENST 07:00-16:30", s=s)
    assert x.shift_type == ShiftType.DIENST and x.display_name == "Dienst"


def test_tijdvak_op_de_minuut():
    s = Settings()
    s.dienstsoorten[0]["tot"] = "11:30"   # ochtend 05:00-11:30
    s.dienstsoorten[1]["van"] = "11:30"   # laat 11:30-20:00
    uit = deel_in("DIENST 11:29-20:00", "DIENST 11:30-20:00", s=s)
    assert [x.shift_type for x in uit] == [ShiftType.OCHTEND, ShiftType.LAAT]


def test_overlap_en_fouten_worden_gemeld():
    s = Settings()
    assert controleer_dienstsoorten(s.dienstsoorten, s.names) == []
    s.dienstsoorten[0]["tot"] = "13:00"
    assert any("overlappen" in f for f in controleer_dienstsoorten(s.dienstsoorten, s.names))
    s.dienstsoorten[0]["tot"] = "7 uur"
    assert any("uu:mm" in f for f in controleer_dienstsoorten(s.dienstsoorten, s.names))


def test_instellingen_van_versie_1_worden_omgezet():
    oud = {"calendar_name": "Werk", "rules": {"time_windows": {"nacht": [21, 6], "ochtend": [6, 12],
                                                              "laat": [12, 21]}}}
    s = Settings.from_dict(oud)
    assert [(d["id"], d["van"], d["tot"]) for d in s.dienstsoorten] == [
        ("ochtend", "06:00", "12:00"), ("laat", "12:00", "21:00"), ("nacht", "21:00", "06:00")]
    assert [d["id"] for d in Settings.from_dict({}).dienstsoorten] == [
        d["id"] for d in DEFAULT_DIENSTSOORTEN]
    # En terug: opgeslagen en opnieuw geladen blijft gelijk.
    s.nieuwe_dienstsoort("Vroeg", "04:00", "06:00")
    assert Settings.from_dict(s.to_dict()).dienstsoorten == s.dienstsoorten


def test_onbekende_code_een_keer_vragen_en_onthouden():
    s = Settings()
    uit = deel_in("TVT", "DIENST 07:00-16:30", "[C1] TVT 00:00-24:00", s=s)
    assert onbekende_codes(uit) == ["TVT"]
    s.onthoud_code("TVT", ShiftType.VRIJ.value)
    uit = deel_in("TVT", s=s)
    assert uit[0].shift_type == ShiftType.VRIJ and onbekende_codes(uit) == []


def test_lege_dag_geeft_geen_dienst():
    assert deel_in(s=Settings()) == []
