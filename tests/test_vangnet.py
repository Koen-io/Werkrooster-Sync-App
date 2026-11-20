"""Vangnet voor versie 2: wat de pdf-lezer doet mag niet ongemerkt veranderen.

Twee lagen:

1. ``test_uitkomst_is_niet_ongemerkt_veranderd`` vergelijkt de volledige
   uitkomst per rooster met de vastgelegde stand in
   ``vangnet_huidige_uitkomst.json``. Verandert de uitkomst met opzet, werk
   het bestand dan bij met ``VANGNET_BIJWERKEN=1 pytest tests/test_vangnet.py``
   en lees het verschil na in ``git diff``.
2. ``test_gewenste_uitkomst_per_dag`` legt vast wat er per dag in de agenda
   hoort te komen voor de roosters met tijdsblokken: precies één item per dag.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from werkrooster_sync.core.classifier import apply_classification
from werkrooster_sync.core.models import ShiftType
from werkrooster_sync.core.pdf_parser import parse_pdf
from werkrooster_sync.core.settings import Settings

HIER = Path(__file__).parent
STAND = HIER / "vangnet_huidige_uitkomst.json"
ROOSTERS = [
    "sample_bvcm_definitief.pdf",
    "sample_bvcm_concept.pdf",
    "rooster_blokken_definitief.pdf",
    "rooster_blokken_concept.pdf",
]


def uitkomst(naam: str):
    s = Settings()  # standaardinstellingen; die van Koen wijken hier niet van af
    return apply_classification(parse_pdf(HIER / naam, s), s)


def als_regels(shifts) -> list[str]:
    return sorted(
        " | ".join([
            f"{x.start:%Y-%m-%d %H:%M}",
            f"{x.end:%Y-%m-%d %H:%M}",
            "hele dag" if x.all_day else "tijden",
            x.shift_type.value,
            x.display_name,
        ])
        for x in shifts
    )


def test_uitkomst_is_niet_ongemerkt_veranderd():
    nu = {naam: als_regels(uitkomst(naam)) for naam in ROOSTERS}
    if os.environ.get("VANGNET_BIJWERKEN"):
        STAND.write_text(
            json.dumps(nu, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    vast = json.loads(STAND.read_text(encoding="utf-8"))
    for naam in ROOSTERS:
        assert nu[naam] == vast[naam], f"Uitkomst van {naam} is veranderd"


# --- Gewenste uitkomst per dag -------------------------------------------
# W = gewone werkdag, V = vrij, anders (begin, eind, memo).
W = ("07:00", "16:30", "Bureaudienst Despatcher")
V = None
GEWENST = {  # testroosters zijn gehusseld: zie hussel() in maak_testrooster.py
    "rooster_blokken_definitief.pdf": (date(2027, 4, 30), False, [
        W, W, V, W, ("09:30", "20:00", "Teamdag"), W, V, W, V, V,
    ]),
    "rooster_blokken_concept.pdf": (date(2027, 5, 10), True, [
        W, V, W, W, V, W, V,                                  # ma 10 - zo 16
        W, V, W, V, W, W, V,                                  # ma 17 - zo 23
        W, W, V, ("09:00", "18:30", "Veiligheidsdag"), W, V, W,  # ma 24 - zo 30
        V, V, W, V, V, W, V,                                  # ma 31 - zo 6
        W, W, W, W,                                           # ma 7 - do 10
    ]),
}


@pytest.mark.parametrize("naam", GEWENST)
def test_gewenste_uitkomst_per_dag(naam):
    eerste_dag, concept, dagen = GEWENST[naam]
    achter = " (concept)" if concept else ""
    verwacht = []
    for i, dag in enumerate(dagen):
        d = eerste_dag + timedelta(days=i)
        if dag is V:
            verwacht.append((f"{d} 00:00", f"{d + timedelta(days=1)} 00:00",
                             "vrij", f"Vrij{achter}"))
        else:
            begin, eind, memo = dag
            verwacht.append((f"{d} {begin}", f"{d} {eind}",
                             "ochtend", f"Ochtend{achter} - {memo}"))

    zichtbaar = sorted(
        (f"{x.start:%Y-%m-%d %H:%M}", f"{x.end:%Y-%m-%d %H:%M}",
         x.shift_type.value, x.display_name)
        for x in uitkomst(naam)
        if x.shift_type != ShiftType.NEGEREN
    )
    assert zichtbaar == verwacht
