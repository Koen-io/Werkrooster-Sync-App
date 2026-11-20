"""Offscreen-tests voor de schermen: elk scherm wordt minstens één keer gebouwd,
en één test loopt de hele route door tegen een nep-agenda:
rooster inlezen -> plan -> uitvoeren -> klaar -> ongedaan maken.
Er wordt nooit een echte agenda aangeraakt en nooit iets verstuurd."""
from __future__ import annotations

import os
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from tests.nep_agenda import NepAgenda  # noqa: E402

TESTS = Path(__file__).parent
DEFINITIEF = TESTS / "rooster_blokken_definitief.pdf"


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def wacht(app, w):
    """Wacht tot alle achtergronddraden van het venster klaar zijn."""
    from PySide6.QtCore import QThread

    for _ in range(100):
        app.processEvents()
        bezig = [t for t in w.findChildren(QThread) if t.isRunning()]
        if not bezig:
            app.processEvents()
            if not [t for t in w.findChildren(QThread) if t.isRunning()]:
                return
        for t in bezig:
            t.wait()
    raise AssertionError("achtergrondwerk bleef hangen")


@pytest.fixture
def venster(app, monkeypatch):
    """Hoofdvenster met een nep-agenda waarin al een agenda gekozen is."""
    from werkrooster_sync.core.settings import Settings
    from werkrooster_sync.ui import main_window as mw

    agenda = NepAgenda()
    monkeypatch.setattr(mw, "get_backend", lambda _id: agenda)
    monkeypatch.setattr(mw, "all_backends", lambda: [agenda])
    Settings(backend_id="nep", calendar_name="Werk", calendar_key="agenda-1").save()
    w = mw.MainWindow()
    w._bevestig = lambda box, ja: True
    yield w, agenda
    wacht(app, w)
    w.close()


def test_hele_route_inlezen_plan_uitvoeren_klaar_ongedaan(app, venster):
    from werkrooster_sync.core import bijwerken as bw

    w, agenda = venster
    assert w.pagina.currentIndex() == 0
    w.load_files([str(DEFINITIEF)])
    wacht(app, w)
    assert w.pagina.currentIndex() == 1, "na inlezen hoort het controlescherm"
    assert w.plannen and w.zet_btn.isEnabled()
    assert w.lijst.count() > 0
    assert not agenda.items, "plannen mag nog niets in de agenda zetten"

    w.start_bijwerken()
    wacht(app, w)
    assert w.pagina.currentIndex() == 2
    assert agenda.items
    assert w.uitkomst.toegevoegd == len(agenda.items)
    assert "bijgewerkt" in w.klaar_titel.text()
    assert bw.kan_ongedaan()
    assert w.ongedaan_btn.isVisibleTo(w)

    w.maak_ongedaan()
    wacht(app, w)
    assert not agenda.items, "ongedaan maken haalt alles weer weg"
    assert not w.ongedaan_btn.isVisibleTo(w)


def _oud_rooster(agenda, s):
    """Zet een ouder rooster in de agenda, met een cursus die nu wegvalt."""
    from werkrooster_sync.core import bijwerken as bw
    from werkrooster_sync.core.classifier import apply_classification
    from werkrooster_sync.core.models import Shift

    def item(d, soort, info=""):
        st = datetime(d.year, d.month, d.day)
        x = Shift(start=st, end=st + timedelta(days=1), original_summary=soort,
                  all_day=True, info=info)
        x.roster_date = st.date()
        return x

    oud = bw.Roster(per_kolom=True, volledig=True, is_concept=False,
                    gegenereerd=datetime(2026, 11, 10, 9, 0), personeelsnummer="12345678",
                    periode=(date(2027, 4, 30), date(2027, 5, 6)))
    oud.shifts = apply_classification(
        [item(date(2027, 4, 30), "DIENST 07:00-16:30", "Bureaudienst Despatcher"),
         item(date(2027, 5, 4), "DIENST 09:30-20:00", "Teamdag"),
         item(date(2027, 5, 4), "Cursus 13:00-15:00")], s)
    ok = bw.Keuzes(verwijderen_bevestigd=True)
    beheer = bw.Beheer.laad()
    bw.voer_uit(bw.maak_plan(oud, oud.shifts, agenda, s, beheer, ok), agenda, beheer, ok)
    bw.journaal_pad().unlink(missing_ok=True)


def test_ouder_rooster_verwijderen_en_keuzevraag(app, venster):
    from werkrooster_sync.core import bijwerken as bw

    w, agenda = venster
    _oud_rooster(agenda, w.settings)
    # Een item van de app met de hand aangepast: daar hoort een vraag bij.
    for i in list(agenda.items.values()):
        if i.start.day == 30:
            agenda.items[i.native_id] = replace(i, title="Ochtend - ruil met collega")

    w.load_files([str(DEFINITIEF)])
    wacht(app, w)
    dagen = {d.dag: d for p in w.plannen for d in p.dagen}
    twintig = date(2027, 4, 30)
    assert dagen[twintig].keuze_nodig and dagen[twintig].uitkomst == bw.ZELF_AANGEPAST
    assert any(d.netto_weg for d in dagen.values()), "de cursus hoort weg te gaan"
    assert w.verwijder_check.isVisibleTo(w), "verwijderen vraagt een eigen bevestiging"

    w._kies_dag("overschrijf_aangepast", twintig)
    wacht(app, w)
    dagen = {d.dag: d for p in w.plannen for d in p.dagen}
    assert not dagen[twintig].keuze_nodig

    w.verwijder_check.setChecked(True)
    wacht(app, w)
    assert w.keuzes.verwijderen_bevestigd
    w.start_bijwerken()
    wacht(app, w)
    assert w.pagina.currentIndex() == 2
    assert not any("Cursus" in i.title for i in agenda.items.values())
    assert any("ruil" not in i.title and i.start.day == 30 for i in agenda.items.values())


def test_onbekende_code_wordt_een_keer_gevraagd_en_onthouden(app, venster, monkeypatch):
    from werkrooster_sync.core import bijwerken as bw
    from werkrooster_sync.core.models import Shift
    from werkrooster_sync.core.settings import Settings
    from werkrooster_sync.ui import main_window as mw

    w, _ = venster
    st = datetime(2026, 12, 14)
    x = Shift(start=st, end=st + timedelta(days=1), original_summary="TVT", all_day=True)
    x.roster_date = st.date()
    rooster = bw.Roster(per_kolom=True, volledig=True, is_concept=False,
                        gegenereerd=datetime(2026, 11, 20, 9, 0), personeelsnummer="12345678",
                        periode=(st.date(), st.date()))
    rooster.shifts = [x]
    monkeypatch.setattr(mw, "read_roster", lambda pad, s: rooster)

    w.load_files([str(DEFINITIEF)])
    vraag = w._extra
    assert isinstance(vraag, mw.OnbekendeCode)
    vraag.kaarten["vrij"].clicked.emit()
    wacht(app, w)
    assert w.pagina.currentIndex() == 1
    assert "tvt" in Settings.load().rules["keywords"]["vrij"]
    assert all(not s.onbekend for r in w.roosters for s in r.shifts)


def test_instelhulp_drie_stappen_en_opslaan(app, monkeypatch):
    from werkrooster_sync.core.settings import Settings
    from werkrooster_sync.ui.wizard import Instelhulp

    agenda = NepAgenda()
    hulp = Instelhulp(Settings(), [agenda])
    opgeslagen = []
    hulp.klaar.connect(opgeslagen.append)
    hulp._kies_koppeling(agenda)
    wacht(app, hulp)
    assert hulp.agenda_combo.count() == 1
    hulp._volgende()
    assert hulp.pagina.currentIndex() == 1

    # Twee dienstsoorten die overlappen worden tegengehouden.
    laat = next(d for d in hulp.s.dienstsoorten if d["id"] == "laat")
    laat["van"] = "10:00"
    hulp._volgende()
    assert hulp.pagina.currentIndex() == 1 and hulp.editor.fout.isVisibleTo(hulp)
    laat["van"] = "12:00"
    hulp._volgende()
    assert hulp.pagina.currentIndex() == 2

    hulp.vrij_sw.setChecked(False)
    hulp._volgende()
    assert opgeslagen
    s = Settings.load()
    assert s.backend_id == "nep" and s.calendar_name == "Werk" and s.calendar_key == "agenda-1"
    assert s.include_vrij is False


def test_hoofdvenster_opent_instelhulp_zonder_agenda(app, monkeypatch):
    from werkrooster_sync.core.settings import Settings
    from werkrooster_sync.ui import main_window as mw
    from werkrooster_sync.ui.wizard import Instelhulp

    agenda = NepAgenda()
    monkeypatch.setattr(mw, "get_backend", lambda _id: agenda)
    monkeypatch.setattr(mw, "all_backends", lambda: [agenda])
    Settings(backend_id="nep").save()
    w = mw.MainWindow()
    assert isinstance(w._extra, Instelhulp)
    wacht(app, w)
    w.close()


def test_bestand_route_maakt_alleen_een_bestand(app, tmp_path, monkeypatch):
    from werkrooster_sync.calendars.ics_export import IcsExportBackend
    from werkrooster_sync.core.settings import Settings
    from werkrooster_sync.ui import main_window as mw

    ics = IcsExportBackend(output_dir=tmp_path, open_after=False)
    monkeypatch.setattr(mw, "get_backend", lambda _id: ics)
    Settings(backend_id="ics_export").save()
    w = mw.MainWindow()
    w.load_files([str(DEFINITIEF)])
    wacht(app, w)
    assert w.pagina.currentIndex() == 1
    assert "Maak het bestand" in w.zet_btn.text()
    w.start_bijwerken()
    wacht(app, w)
    assert w.pagina.currentIndex() == 2
    assert not w.ongedaan_btn.isVisibleTo(w), "bij een bestand bestaat ongedaan maken niet"
    bestanden = list(tmp_path.glob("*.ics"))
    assert bestanden and "BEGIN:VEVENT" in bestanden[0].read_text(encoding="utf-8")
    w.close()


def test_branding_assets_present_and_loadable(app):
    from werkrooster_sync.app import _app_icon, _make_splash
    from werkrooster_sync.resources import asset_path

    for name in ("splash.png", "logo.png", "icon.ico", "icon.icns",
                 "icons/app-icon-512.png"):
        assert asset_path(name).exists(), f"assets/{name} ontbreekt"

    icon = _app_icon()
    assert not icon.isNull()

    # The handout ships inside the app so it travels with every download.
    assert asset_path("handleiding.pdf").exists()

    # The animated splash renders at any point in its timeline without errors.
    splash = _make_splash(app)
    assert splash is not None
    for t in (0.0, 0.35, 1.0, 3.2):
        splash._time_override = t
        image = splash.grab().toImage()
        assert not image.isNull()
    splash.finish(None)


def test_settings_panel_builds_and_saves(app):
    from werkrooster_sync.core.settings import Settings
    from werkrooster_sync.ui.settings_dialog import SettingsPanel

    s = Settings(backend_id="ics_export")
    panel = SettingsPanel(s)
    fired = []
    panel.saved.connect(lambda *a: fired.append(True))
    assert panel.wizard_btn.text() == "Instelhulp starten"
    # Bij een bestand kan de app niets terugdraaien.
    assert not panel.undo_btn.isEnabled()

    panel.name_edits["vrij"].setText("Vrije dag")
    panel.include_vrij_check.setChecked(False)
    panel.include_afspraken_check.setChecked(False)
    idx = panel.display_combos["nacht"].findData("all_day")
    panel.display_combos["nacht"].setCurrentIndex(idx)
    panel.min_shift_spin.setValue(6)
    panel._save()

    assert fired
    saved = Settings.load()
    assert saved.names["vrij"] == "Vrije dag"
    assert saved.include_vrij is False
    assert saved.include_afspraken is False
    assert saved.display["nacht"] == "all_day"
    assert saved.rules["min_shift_hours"] == 6


def test_feedback_laat_alles_zien_wat_meegaat(app):
    from werkrooster_sync.core import logbook
    from werkrooster_sync.ui.feedback_dialog import FeedbackDialog

    fb = FeedbackDialog(rooster=str(DEFINITIEF))
    getoond = []
    fb._bevestig_voorbeeld = lambda tekst: getoond.append(tekst) or True
    fb._kies_voorbeeld()
    assert getoond and fb._voorbeeld == getoond[0]
    assert "12345678" not in fb._voorbeeld, "geen personeelsnummer in het voorbeeld"

    fb.log_check.setChecked(True)
    assert fb.log_tekst.isVisibleTo(fb)
    assert fb._logboek == logbook.tail()
    assert fb.log_tekst.toPlainText() in (fb._logboek, "(het logboek is leeg)")
    fb.close()


def test_vinkjes_lezen_de_agenda_niet_opnieuw(app, venster):
    from PySide6.QtWidgets import QCheckBox

    w, agenda = venster
    _oud_rooster(agenda, w.settings)
    for i in list(agenda.items.values()):
        if i.start.day in (30, 4) and "Cursus" not in i.title:
            agenda.items[i.native_id] = replace(i, title=i.title + " - ruil met collega")
    gelezen = []
    echt = agenda.read_items
    agenda.read_items = lambda *a: (gelezen.append(a), echt(*a))[1]

    w.load_files([str(DEFINITIEF)])
    wacht(app, w)
    n = len(gelezen)
    assert n and len(w._vraagdagen) == 2
    vinkjes = [v for v in w.findChildren(QCheckBox) if v.text()[:2] in ("vr", "di")]
    assert len(vinkjes) == 2 and not any(v.isChecked() for v in vinkjes)

    vinkjes[0].setChecked(True)  # één dag vervangen
    wacht(app, w)
    w._kies_alles(True)          # alles vervangen
    wacht(app, w)
    assert len(gelezen) == n, "een keuze mag de agenda niet opnieuw inlezen"
    assert len(w._vraagdagen) == 2, "de lijst met vinkjes blijft staan"
    dagen = {d.dag: d for p in w.plannen for d in p.dagen}
    assert not any(dagen[d].keuze_nodig for d in w._vraagdagen)

    w._kies_alles(False)         # alles laten staan
    wacht(app, w)
    dagen = {d.dag: d for p in w.plannen for d in p.dagen}
    assert all(dagen[d].keuze_nodig for d in w._vraagdagen)
    assert w._soort(dagen[date(2027, 4, 30)]) == "laten"
    assert len(gelezen) == n

    w.start_bijwerken()          # bijwerken leest wél vers
    wacht(app, w)
    assert len(gelezen) > n
    assert sum("ruil met collega" in i.title for i in agenda.items.values()) == 2
