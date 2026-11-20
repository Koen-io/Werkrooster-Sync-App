"""Voorbeeldrooster versturen: alleen opbouw, geen persoonsgegevens."""
from pathlib import Path

from werkrooster_sync.core.voorbeeld import voorbeeld_uit_pdf

HIER = Path(__file__).parent


def test_alleen_opbouw_blijft_staan():
    t = voorbeeld_uit_pdf(HIER / "rooster_blokken_definitief.pdf")
    # Persoonsgegevens en vrije tekst weg (ook niet in stukjes).
    for weg in ("12345678", "Voorbeeld", "Bureaudienst", "Despatcher", "Teamdag"):
        assert weg not in t, weg
    # Opbouw blijft: kolomkoppen, datums, tijden, soortcodes, labels.
    for blijft in ("Soort", "Tijdstippen", "30/04/2027", "DIENST 07:00-16:30",
                   "11:30-12:00", "Vrijdag", "Activiteit:"):
        assert blijft in t, blijft


def test_gevoelige_code_en_vrije_tekst_in_soort_gaan_eruit(tmp_path):
    from tests.maak_testrooster import lees_paginas, schrijf_pdf
    paginas = lees_paginas(HIER / "rooster_blokken_definitief.pdf")
    b, h, stukjes = paginas[0]
    regel = next(s for s in stukjes if s[4].strip().startswith("DIENST"))
    dag = next(s for s in stukjes if s[4].strip().startswith("Zaterdag"))
    paginas[0] = (b, h, stukjes + [(regel[0], dag[1], regel[2], False, "ZIEK door werk 00:00-24:00")])
    schrijf_pdf(paginas, tmp_path / "r.pdf")
    t = voorbeeld_uit_pdf(tmp_path / "r.pdf")
    rooster = t.split("--- pagina 1", 1)[1]
    assert "ZIEK" not in rooster and "door" not in rooster
    assert "AFWEZIG xxxx xxxx 00:00-24:00" in rooster


def test_namen_codes_en_datums_op_de_verkeerde_plek_gaan_eruit(tmp_path):
    from tests.maak_testrooster import lees_paginas, schrijf_pdf
    paginas = lees_paginas(HIER / "rooster_blokken_definitief.pdf")
    b, h, stukjes = paginas[0]
    regel = next(s for s in stukjes if s[4].strip().startswith("DIENST"))
    kop = next(s for s in stukjes if s[4].strip() == "Dag")
    memo = next(s for s in stukjes if s[4].startswith("Memo:"))
    dagen = [s for s in stukjes if s[4].strip() in ("Zaterdag", "Zondag")]
    extra = [(400, kop[1], kop[2], False, "Piet Jansen"),
             (regel[0], dagen[0][1], regel[2], False, "Jansen 00:00-24:00"),
             (regel[0], dagen[1][1], regel[2], False, "ZWAV 00:00-24:00"),
             (memo[0], memo[1] - 4, memo[2], False, "geboren 12-03-1985 om 12.50")]
    paginas[0] = (b, h, stukjes + extra)
    schrijf_pdf(paginas, tmp_path / "r.pdf")
    t = voorbeeld_uit_pdf(tmp_path / "r.pdf")
    for weg in ("Piet", "Jansen", "ZWAV", "1985", "12.50"):
        assert weg not in t, weg
    assert "AFWEZIG 00:00-24:00" in t and "Tijdstippen" in t and "DIENST 07:00-16:30" in t
