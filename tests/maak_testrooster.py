"""Maak van een echt BVCM-rooster een geanonimiseerd testbestand.

    python tests/maak_testrooster.py <echt.pdf> <tests/uit.pdf> <nummer> "<Naam, X>"

Het echte bestand wordt niet gekopieerd: er wordt een nieuwe pdf opgebouwd met
alleen de zichtbare tekst op dezelfde plek. Zo gaat er geen verborgen tekst of
bestandsinformatie mee. Personeelsnummer en naam worden vervangen door
"12345678" en "Voorbeeld, P". Lees het resultaat altijd zelf na voordat het de
(openbare) repo in gaat: memo's en locaties kunnen ook herkenbaar zijn.
"""
from __future__ import annotations

import random
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from pypdf import PdfReader

NEP_NUMMER = "12345678"
NEP_NAAM = "Voorbeeld, P"
HUSSEL_WEKEN = 23  # hele weken, zodat de weekdagen kloppen
HUSSEL_ZAAD = 2026
_DATUM = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def _fragments(page) -> list[tuple[float, float, float, bool, str]]:
    out = []

    def visit(text, cm, tm, font, size):
        if text.strip():
            bold = "bold" in str((font or {}).get("/BaseFont", "")).lower()
            out.append((tm[4], tm[5], size, bold, text.replace("\n", "")))

    page.extract_text(visitor_text=visit)
    return out


def _pdf_string(text: str) -> bytes:
    raw = text.encode("cp1252")  # faalt hard op tekens die we niet kunnen schrijven
    for ch in (b"\\", b"(", b")"):
        raw = raw.replace(ch, b"\\" + ch)
    return b"(" + raw + b")"


def lees_paginas(src: Path) -> list[tuple[float, float, list]]:
    """Per pagina: breedte, hoogte en de stukjes tekst (x, y, grootte, vet, tekst)."""
    return [(float(p.mediabox.width), float(p.mediabox.height), _fragments(p))
            for p in PdfReader(str(src)).pages]


def schrijf_pdf(paginas: list[tuple[float, float, list]], dst: Path) -> None:
    """Schrijf een kale pdf met alleen deze stukjes tekst."""
    objects: list[bytes] = [
        b"",  # 1: catalog, hieronder ingevuld
        b"",  # 2: pages
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    kids = []
    for breedte, hoogte, stukjes in paginas:
        ops = [b"BT"]
        for x, y, size, bold, text in stukjes:
            font = b"/F2" if bold else b"/F1"
            ops.append(b"%s %.3f Tf 1 0 0 1 %.2f %.2f Tm %s Tj"
                       % (font, size, x, y, _pdf_string(text)))
        ops.append(b"ET")
        stream = b"\n".join(ops)
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        content_no = len(objects)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] "
            b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents %d 0 R >>"
            % (breedte, hoogte, content_no)
        )
        kids.append(len(objects))
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids), len(kids))

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref)
    dst.write_bytes(bytes(out))


def _schuif(text: str) -> str:
    def nieuw(m):
        d = date(int(m[3]), int(m[2]), int(m[1])) + timedelta(weeks=HUSSEL_WEKEN)
        return d.strftime("%d/%m/%Y")
    text = _DATUM.sub(nieuw, text)
    # "Periode:  12 / 2026": jaar meeschuiven met de eerste datum erachter.
    m = re.search(r"(\d+) / (\d{4})(\s+)(\d{2}/\d{2}/(\d{4}))", text)
    if m:
        text = text.replace(m[0], f"{m[1]} / {m[5]}{m[3]}{m[4]}")
    return text


def hussel(paginas: list[tuple[float, float, list]]) -> list[tuple[float, float, list]]:
    """Verberg het echte werkpatroon: schuif alle datums HUSSEL_WEKEN weken op
    en schud per pagina welke dag welke inhoud krijgt (dienst, vrij of leeg).
    Datum en weekdag blijven in volgorde; de rijen worden opnieuw gestapeld.
    De eerste en laatste dag van een pagina blijven staan: een dag die over
    de paginawissel loopt, staat op beide pagina's."""
    rnd = random.Random(HUSSEL_ZAAD)
    uit = []
    for breedte, hoogte, stukjes in paginas:
        ankers = sorted((y for x, y, _, vet, t in stukjes
                         if vet and abs(x - 87.0) < 1 and _DATUM.fullmatch(t.strip())),
                        reverse=True)
        if len(ankers) < 4:
            uit.append((breedte, hoogte, [s[:4] + (_schuif(s[4]),) for s in stukjes]))
            continue
        bovenkant, laatste = ankers[0], ankers[-1]
        vast = [s for s in stukjes if s[1] > bovenkant or s[1] <= laatste]
        koppen, blokken = [], []  # koppen: datum + weekdag; blokken: (hoogte, inhoud)
        for top, onder in zip(ankers, ankers[1:]):
            rij = [s for s in stukjes if onder < s[1] <= top]
            koppen.append([(x, y - top, g, v, t) for x, y, g, v, t in rij
                           if y == top and x < 140])
            blokken.append((top - onder, [(x, y - top, g, v, t) for x, y, g, v, t in rij
                                          if not (y == top and x < 140)]))
        midden = blokken[1:]
        rnd.shuffle(midden)
        blokken[1:] = midden
        top, nieuw = bovenkant, []
        for kop, (hoog, inhoud) in zip(koppen, blokken):
            nieuw += [(x, round(top + dy, 2), g, v, t) for x, dy, g, v, t in kop + inhoud]
            top -= hoog
        assert abs(top - laatste) < 0.01  # de laatste dag staat nog op zijn plek
        uit.append((breedte, hoogte, [s[:4] + (_schuif(s[4]),) for s in vast + nieuw]))
    return uit


def anonimiseer(src: Path, dst: Path, nummer: str, naam: str) -> None:
    schrijf_pdf(
        [(b, h, [(x, y, size, bold,
                  text.replace(nummer, NEP_NUMMER).replace(naam, NEP_NAAM))
                 for x, y, size, bold, text in stukjes])
         for b, h, stukjes in lees_paginas(src)],
        dst,
    )

    # Zelfcontrole: zelfde tekst als het origineel (op de vervanging na), en
    # het echte nummer en de echte naam komen nergens meer voor.
    def tekst(path):
        return "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)

    verwacht = tekst(src).replace(nummer, NEP_NUMMER).replace(naam, NEP_NAAM)
    nieuw = tekst(dst)
    achternaam = naam.split(",")[0].strip()
    assert nummer.encode() not in dst.read_bytes() and nummer not in nieuw
    assert achternaam.casefold() not in nieuw.casefold(), "naam staat er nog in"
    assert achternaam.casefold().encode() not in dst.read_bytes().lower()
    if [r.split() for r in nieuw.splitlines()] != [r.split() for r in verwacht.splitlines()]:
        raise SystemExit("Tekst van de kopie wijkt af van het origineel")
    schrijf_pdf(hussel(lees_paginas(dst)), dst)


if __name__ == "__main__":
    if sys.argv[1] == "--hussel":  # alleen husselen, voor een al anoniem rooster
        schrijf_pdf(hussel(lees_paginas(Path(sys.argv[2]))), Path(sys.argv[3]))
        raise SystemExit(0)
    src, dst, nummer, naam = sys.argv[1:5]
    anonimiseer(Path(src), Path(dst), nummer, naam)
    print("geschreven:", dst)
