"""Een voorbeeldrooster zonder persoonsgegevens, om te versturen.

Roosters van andere eenheden kunnen er anders uitzien. Om de app daarop aan
te passen is de *opbouw* nodig, niet de inhoud. Deze module maakt daarom een
nieuw tekstbestand en stuurt nooit de pdf zelf: zo gaat er geen verborgen
tekst of bestandsinformatie mee.

Wat blijft staan: per pagina de regels met de x-positie van elk stukje
tekst, de kolomkoppen, datums, tijden, weekdagen en de codes in de kolom
Soort (DIENST, VERLOF, ...). Al het andere (namen, nummers, memo's,
projecten, activiteiten, locaties) wordt vervangen door opvulling van
dezelfde lengte: letters worden x, cijfers 0.

De gebruiker ziet de tekst voordat hij verstuurd wordt.
"""
from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from .models import ShiftType
from .pdf_parser import _COLUMNS, _HEADER_LINE_2, _X_TOL, _find_header, _page_rows
from .settings import DEFAULT_RULES

_DATUM = re.compile(r"^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$")
_TIJD = re.compile(r"^\d{1,2}:\d{2}([-–]\d{1,2}:\d{2})?$")
_WOORDEN = {
    "ma", "di", "wo", "do", "vr", "za", "zo", "maandag", "dinsdag", "woensdag",
    "donderdag", "vrijdag", "zaterdag", "zondag", "pagina", "van", "tot", "t/m",
    "periode", "concept", "rooster", "medewerker", "medewerker:", "gegenereerd",
    "gegenereerd:", "generatiedatum:", "op", "-", "–", ":", "/",
    # Labels van memo's en kolommen: opbouw, de waarde erachter niet.
    "memo:", "activiteit:", "project:", "locatie:", "periode:", "noodhulp:",
    "resultaat:", "ibt:", "informatie:", "notitie:",
}
#: Codes in de kolom Soort die gewoon mee mogen: ze zeggen niets over iemand.
_VEILIGE_CODES = {"dienst", "vrij", "verlof", "vakantie", "rust", "consig",
                  "consignatie", "cursus", "opleiding", "training", "piket"}
#: Verlof- en afwezigheidscodes kunnen iets over gezondheid of privé zeggen
#: (ziek, zwangerschap, rouw, ...): die worden "AFWEZIG". Elke andere code
#: wordt gemaskeerd, want ook een naam kan in die kolom staan.
_AFWEZIG = {k.strip("[]() ").casefold()
            for soort in (ShiftType.VRIJ.value, ShiftType.AFSPRAAK.value)
            for k in DEFAULT_RULES["keywords"].get(soort, [])} - _VEILIGE_CODES
#: Kolommen waarin datums en tijden opbouw zijn (elders kan het een verjaardag zijn).
_TIJD_KOLOMMEN = {"datum", "tijdstippen", "soort", None}


def _maskeer(woord: str) -> str:
    return re.sub(r"\d", "0", re.sub(r"[^\W\d_]", "x", woord))


def _woord(woord: str, kolom: str | None, eerste: bool) -> str:
    if woord.casefold() in _WOORDEN:
        return woord
    if kolom in _TIJD_KOLOMMEN and (_DATUM.match(woord) or _TIJD.match(woord)):
        return woord
    if kolom == "soort" and eerste:
        code = woord.strip("[]() ").casefold()
        if code in _VEILIGE_CODES:
            return woord
        if code in _AFWEZIG:
            return "AFWEZIG"
    return _maskeer(woord)


def voorbeeld_uit_pdf(path: str | Path) -> str:
    regels = ["Werkrooster Sync - voorbeeldrooster (alleen de opbouw, geen inhoud)",
              "Per regel: x-positie:tekst. Vrije tekst is vervangen door x en 0."]
    for nr, page in enumerate(PdfReader(str(path)).pages, 1):
        regels.append(f"--- pagina {nr}")
        rows = _page_rows(page)
        kop = _find_header(rows)
        kop_i, kolommen = kop if kop else (-1, [])
        for i, row in enumerate(rows):
            delen = []
            for x, tekst in row:
                kolom = None  # boven de kopregel: kop van het rapport (periode, datum)
                if i == kop_i:
                    # Kolomkoppen zijn opbouw, maar alleen de bekende.
                    bekend = tekst.casefold().startswith(_COLUMNS) or \
                        tekst.casefold() in _HEADER_LINE_2
                    delen.append(f"{x:.0f}:" + (tekst if bekend else _maskeer(tekst)))
                    continue
                if i > kop_i >= 0:
                    kolom = "?"
                    for cx, naam in kolommen:
                        if cx <= x + _X_TOL:
                            kolom = naam
                woorden = tekst.split()
                delen.append(f"{x:.0f}:" + " ".join(
                    _woord(w, kolom, j == 0) for j, w in enumerate(woorden)))
            regels.append("  ".join(delen))
    return "\n".join(regels) + "\n"
