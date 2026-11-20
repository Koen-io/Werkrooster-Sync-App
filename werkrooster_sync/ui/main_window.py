"""Het hoofdvenster: rooster kiezen, controleren, klaar.

Alles wat de agenda leest of schrijft gebeurt in een achtergronddraad. Tijdens
het bijwerken kan er geen tweede actie starten: knoppen en slepen staan uit en
de instellingen gaan niet open.
"""
from __future__ import annotations

import copy
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..calendars.ics_export import IcsExportBackend
from ..calendars.registry import all_backends, get_backend
from ..core import bijwerken as bw
from ..core.classifier import apply_classification, code_van, onbekende_codes
from ..core.models import Shift, ShiftType
from ..core.pdf_parser import Roster, read_roster
from ..core.settings import Settings
from . import theme
from .settings_dialog import SettingsPanel, _Worker
from .widgets import (
    DropZone,
    Icoon,
    KeuzeKaart,
    Pil,
    StepBar,
    Stip,
    Tegel,
    Vinkrondje,
    dag_kort,
    dag_lang,
    herpolish,
    kaart,
    knop,
    label,
    leeg_layout,
    periode_tekst,
    tijden,
)

KOPPELING_NAAM = {"apple_calendar": "Apple Agenda", "outlook": "Outlook",
                  "ics_export": "Een andere agenda"}

#: Woord op de tegel en label in de lijst, per uitkomst.
TEGEL = {bw.NIEUW: "nieuw", bw.GEWIJZIGD: "gewijzigd", bw.VERVANGT_CONCEPT: "vervangt concept",
         bw.STAAT_ER_AL: "staat er al", bw.VERWIJDEREN: "wordt verwijderd",
         bw.OVERGESLAGEN: "overgeslagen"}

#: Volgorde van de tegels.
TEGEL_VOLGORDE = [bw.NIEUW, bw.GEWIJZIGD, bw.VERVANGT_CONCEPT, bw.STAAT_ER_AL,
                  bw.VERWIJDEREN, "kiezen", "laten", bw.OVERGESLAGEN]


def _pil(uitkomst: str) -> Pil:
    if uitkomst == bw.NIEUW:
        return Pil("+ Nieuw", theme.ACCENT, theme.ACCENT_TEXT)
    if uitkomst == bw.GEWIJZIGD:
        return Pil("Gewijzigd", theme.OCHTEND, theme.ACCENT_TEXT)
    if uitkomst == bw.VERVANGT_CONCEPT:
        return Pil("Vervangt concept", theme.BORDER, theme.TEXT)
    if uitkomst == bw.STAAT_ER_AL:
        return Pil("Staat er al", "", theme.TEXT_DIM)
    if uitkomst == bw.VERWIJDEREN:
        return Pil("Wordt verwijderd", "", theme.DANGER, theme.DANGER)
    if uitkomst == "laten":
        return Pil("Blijft staan", "", theme.TEXT_DIM, theme.BORDER)
    if uitkomst == "bestand":
        return Pil("Komt in bestand", "", theme.TEXT_DIM)
    if uitkomst in (bw.ZELF_AANGEPAST, bw.MOGELIJK_DUBBEL, bw.OUDER_ROOSTER, bw.ANDERE_INHOUD):
        return Pil(uitkomst[0].upper() + uitkomst[1:], "", theme.WARN, theme.WARN)
    return Pil("Overgeslagen", "", theme.TEXT_DIM, theme.BORDER)


def _overlapt(a: Roster, b: Roster) -> bool:
    if not a.periode or not b.periode:
        return True
    return a.periode[0] <= b.periode[1] and b.periode[0] <= a.periode[1]


def _dag_van(x: Shift) -> date:
    return x.roster_date or x.start.date()


# ----------------------------------------------------------------------
class OnbekendeCode(QWidget):
    """Eén keer vragen wat een onbekende code uit het rooster is."""

    def __init__(self, code: str, voorbeelden: list[Shift], settings: Settings, klaar,
                 parent=None):
        super().__init__(parent)
        self.code = code
        root = QVBoxLayout(self)
        root.setContentsMargins(56, 40, 56, 32)
        root.setSpacing(14)
        boven = QLabel("Eén ding weten we nog niet")
        boven.setStyleSheet(f"color: {theme.WARN}; font-size: 16px; font-weight: 700;")
        root.addWidget(boven)
        root.addWidget(label(f"Wat is “{code}”?", "pageTitle"))
        x = voorbeelden[0]
        waar = (f"op {dag_lang(_dag_van(x))}" +
                (f" (en nog {len(voorbeelden) - 1} andere dag{'en' if len(voorbeelden) > 2 else ''})"
                 if len(voorbeelden) > 1 else ""))
        wanneer = "de hele dag" if x.all_day else f"van {x.start:%H:%M} tot {x.end:%H:%M}"
        uitleg = label(f"Deze soort staat {waar} in je rooster, {wanneer}. De app kent hem "
                       "nog niet. Kies één keer wat het is; daarna weet de app het voortaan.",
                       "lead", wrap=True)
        uitleg.setMaximumWidth(960)
        root.addWidget(uitleg)
        root.addSpacing(10)

        dienst = settings.name_for(ShiftType.DIENST.value)
        keuzes = [
            ("Een gewone dienst", f"Komt als “{dienst}” in je agenda.",
             theme.ACCENT, ShiftType.DIENST.value),
            ("Vrij of verlof", "Komt als “Vrij” bovenaan de dag te staan.",
             theme.VRIJ, ShiftType.VRIJ.value),
            ("Iets anders", "Zoals een cursus of piket. Houdt zijn eigen naam uit het rooster.",
             theme.AFSPRAAK, ShiftType.AFSPRAAK.value),
            ("Niet in mijn agenda", "De app slaat deze soort voortaan over.",
             "", ShiftType.NEGEREN.value),
        ]
        rooster = QGridLayout()
        rooster.setSpacing(20)
        self.kaarten: dict[str, KeuzeKaart] = {}
        for i, (titel, tekst, kleur, sleutel) in enumerate(keuzes):
            k = KeuzeKaart(titel, tekst, stip=kleur)
            k.setMinimumHeight(150)
            k.clicked.connect(lambda sleutel=sleutel: klaar(code, sleutel, self.onthoud.isChecked()))
            self.kaarten[sleutel] = k
            rooster.addWidget(k, i // 2, i % 2)
        root.addLayout(rooster, stretch=1)
        onder = QHBoxLayout()
        self.onthoud = QCheckBox("Onthoud mijn keuze voor volgende roosters")
        self.onthoud.setChecked(True)
        self.onthoud.setStyleSheet("font-size: 16px;")
        onder.addWidget(self.onthoud)
        onder.addStretch()
        onder.addWidget(knop("Nu overslaan", "big", lambda: klaar(code, "", False)))
        root.addLayout(onder)


# ----------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.roosters: list[Roster] = []
        self._ruw: dict[int, list[Shift]] = {}
        self.paden: list[str] = []
        self.plannen: list[bw.Plan] = []
        self.keuzes = bw.Keuzes()
        self._laten: set[date] = set()
        self._nee: set[str] = set()
        #: Agenda één keer gelezen per controlescherm; keuzes rekenen hieruit.
        self._momentopname: bw.Momentopname | None = None
        #: Dagen waar de gebruiker per vinkje kiest: dag -> (keuzeveld, reden).
        self._vraagdagen: dict[date, tuple[str, str]] = {}
        self._gevraagd: set[str] = set()
        self._eenmalig: dict[str, str] = {}
        self._worker: _Worker | None = None
        self._bezig = False
        self.uitkomst: bw.Uitkomst | None = None

        self.setWindowTitle("Werkrooster Sync")
        self.setMinimumSize(1000, 720)
        self.setStyleSheet(theme.QSS)

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)
        hoofd = QWidget()
        self._stack.addWidget(hoofd)
        root = QVBoxLayout(hoofd)
        root.setContentsMargins(56, 30, 56, 30)
        root.setSpacing(22)

        kop = QHBoxLayout()
        kop.setSpacing(12)
        kop.addWidget(label("Werkrooster Sync", "appTitle"))
        kop.addStretch()
        self.handleiding_btn = knop("Handleiding", "secondary", self.open_handleiding)
        self.feedback_btn = knop("Feedback", "secondary", self.open_feedback)
        self.settings_btn = knop("Instellingen", "secondary", self.open_settings)
        for b in (self.handleiding_btn, self.feedback_btn, self.settings_btn):
            kop.addWidget(b)
        root.addLayout(kop)
        self.stappen = StepBar()
        root.addWidget(self.stappen)

        self.pagina = QStackedWidget()
        self.pagina.addWidget(self._bouw_kiezen())
        self.pagina.addWidget(self._bouw_controle())
        self.pagina.addWidget(self._bouw_klaar())
        root.addWidget(self.pagina, stretch=1)
        self._ververs_agendabalk()

        if not self.settings.calendar_name and self.settings.backend_id != IcsExportBackend.id:
            self.open_instelhulp()

    # ------------------------------------------------------------------
    def _koppeling(self):
        return get_backend(self.settings.backend_id)

    def _indeel_instellingen(self) -> Settings:
        """De instellingen plus codes die alleen voor deze keer zijn gekozen."""
        if not self._eenmalig:
            return self.settings
        s = Settings.from_dict(self.settings.to_dict())
        for code, sleutel in self._eenmalig.items():
            s.onthoud_code(code, sleutel)
        return s

    def _zet_bezig(self, aan: bool) -> None:
        """Tijdens agenda-werk: geen tweede actie."""
        self._bezig = aan
        self.settings_btn.setEnabled(not aan)
        self.drop_zone.set_actief(not aan)
        self.andere_btn.setEnabled(not aan)
        self.ander_bestand_btn.setEnabled(not aan)
        self.nog_een_btn.setEnabled(not aan)
        self.ongedaan_btn.setEnabled(not aan)
        self.veranderd_btn.setEnabled(not aan)
        self.voortgang.setVisible(aan)
        self.voortgang_lbl.setVisible(aan)
        if aan:
            self.zet_btn.setEnabled(False)

    def closeEvent(self, event):  # noqa: N802 (Qt API)
        if self._bezig:
            QMessageBox.information(self, "Even wachten",
                                    "De app is bezig met je agenda. Wacht tot hij klaar is, "
                                    "dan kun je de app sluiten.")
            event.ignore()
            return
        super().closeEvent(event)

    def _start(self, fn, klaar, met_voortgang: bool = False) -> None:
        self._zet_bezig(True)
        self._worker = _Worker(fn, self, met_voortgang=met_voortgang)

        def done(uit) -> None:
            self._zet_bezig(False)
            klaar(uit)

        def failed(melding: str) -> None:
            self._zet_bezig(False)
            self._fout(melding)

        self._worker.done.connect(done)
        self._worker.failed.connect(failed)
        self._worker.voortgang.connect(self._op_voortgang)
        self._worker.start()

    def _op_voortgang(self, gedaan: int, totaal: int, _tekst: str) -> None:
        self.voortgang.setRange(0, max(1, totaal))
        self.voortgang.setValue(gedaan)
        self.voortgang_lbl.setText(f"Bezig met je agenda: {gedaan} van {totaal}")

    def _fout(self, melding: str) -> None:
        """Een fout bij agenda-werk: op het scherm waar je bent."""
        if self.pagina.currentIndex() == 1:
            self.status.setText(melding)
            self.status.setVisible(True)
            herpolish(self.status, "statusError")
            self._ververs_knop()
        else:
            self.pagina.setCurrentIndex(0)
            self.stappen.zet(0)
            self.drop_zone.toon_fout(melding)

    # ------------------------------------------------------------------
    # Stap 1: rooster kiezen
    # ------------------------------------------------------------------
    def _bouw_kiezen(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(24)
        self.drop_zone = DropZone()
        self.drop_zone.files_selected.connect(self.load_files)
        self.drop_zone.hulp_btn.clicked.connect(self.open_handleiding)
        lay.addWidget(self.drop_zone, stretch=1)

        balk = QFrame()
        balk.setObjectName("card")
        b = QHBoxLayout(balk)
        b.setContentsMargins(22, 14, 16, 14)
        b.setSpacing(14)
        b.addWidget(Icoon("agenda", 26, theme.TEXT_DIM))
        self.agenda_lbl = QLabel()
        self.agenda_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.agenda_lbl.setStyleSheet(f"font-size: 16px; color: {theme.TEXT_DIM};")
        b.addWidget(self.agenda_lbl, stretch=1)
        self.andere_btn = knop("Andere agenda", "secondary", self.open_agenda_kiezen)
        b.addWidget(self.andere_btn)
        lay.addWidget(balk)
        return w

    def _ververs_agendabalk(self) -> None:
        import html

        s = self.settings
        b = self._koppeling()
        if not b.can_inspect_calendar:
            tekst = "Je krijgt een bestand om zelf in je agenda in te lezen"
        elif s.calendar_name:
            tekst = (f"Komt in je agenda <b style='color:{theme.TEXT}'>"
                     f"{html.escape(s.calendar_name)}</b>")
        else:
            tekst = "Er is nog geen agenda gekozen"
        naam = KOPPELING_NAAM.get(b.id, b.label)
        self.agenda_lbl.setText(f"{tekst} · {html.escape(naam)}")

    def load_file(self, path: str) -> None:
        self.load_files([path])

    def load_files(self, paden: list[str]) -> None:
        """Lees een of meer roosters in en ga door naar controleren."""
        if self._bezig:
            return
        self.drop_zone.toon_fout("")
        roosters = []
        for pad in paden:
            if not pad.lower().endswith(".pdf"):
                self.drop_zone.toon_fout(f"“{Path(pad).name}” is geen pdf. Kies het "
                                         "pdf-bestand “Medewerker Rooster” uit BVCM.")
                return
            try:
                roosters.append(read_roster(pad, self.settings))
            except Exception as exc:  # PdfParseError en kapotte bestanden
                self.drop_zone.toon_fout(f"“{Path(pad).name}” kon niet worden gelezen. {exc}")
                return
        self.paden = list(paden)
        self.roosters = bw.op_rangvolgorde(roosters)
        self._ruw = {id(r): copy.deepcopy(r.shifts) for r in self.roosters}
        self.keuzes = bw.Keuzes()
        self._laten = set()
        self._nee = set()
        self._deel_in()
        self._vraag_of_ga_door()

    def _deel_in(self) -> None:
        s = self._indeel_instellingen()
        for r in self.roosters:
            r.shifts = apply_classification(copy.deepcopy(self._ruw[id(r)]), s)

    def _alle_shifts(self) -> list[Shift]:
        return [x for r in self.roosters for x in r.shifts]

    def _vraag_of_ga_door(self) -> None:
        codes = [c for c in onbekende_codes(self._alle_shifts()) if c not in self._gevraagd]
        if codes:
            self._vraag_code(codes[0])
            return
        self._naar_controle()

    def _vraag_code(self, code: str) -> None:
        voorbeelden = [x for x in self._alle_shifts() if x.onbekend and code_van(x) == code]
        pagina = OnbekendeCode(code, voorbeelden, self.settings, self._code_gekozen)
        self._toon_extra(pagina)

    def _code_gekozen(self, code: str, sleutel: str, onthoud: bool) -> None:
        self._gevraagd.add(code)
        if sleutel and onthoud:
            self.settings.onthoud_code(code, sleutel)
            self.settings.save()
        elif sleutel:
            self._eenmalig[code] = sleutel
        self._sluit_extra()
        self._deel_in()
        self._vraag_of_ga_door()

    def _toon_extra(self, w: QWidget) -> None:
        """Een volledige pagina over het hoofdscherm (instellingen, instelhulp, vraag)."""
        self._sluit_extra()
        self._extra = w
        self._stack.addWidget(w)
        self._stack.setCurrentWidget(w)

    def _sluit_extra(self) -> None:
        w = getattr(self, "_extra", None)
        if w is not None:
            self._stack.removeWidget(w)
            w.deleteLater()
            self._extra = None
        self._stack.setCurrentIndex(0)

    # ------------------------------------------------------------------
    # Stap 2: controleren
    # ------------------------------------------------------------------
    def _bouw_controle(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(40)

        links = QVBoxLayout()
        links.setSpacing(14)
        self.titel = label("Klopt dit met je rooster?", "bigTitle")
        links.addWidget(self.titel)
        self.ondertitel = label("", "lead", wrap=True)
        links.addWidget(self.ondertitel)
        links.addSpacing(6)
        # Meldingen (verwijderen bevestigen, alleen toevoegen) boven de tegels,
        # zodat het vinkje nooit onder de knoppen wegvalt.
        self.meldingen_links = QVBoxLayout()
        self.meldingen_links.setSpacing(12)
        links.addLayout(self.meldingen_links)
        self.tegels = QGridLayout()
        self.tegels.setSpacing(16)
        links.addLayout(self.tegels)
        links.addStretch()
        links.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        boven = QWidget()
        boven.setLayout(links)
        boven_sa = QScrollArea()
        boven_sa.setWidgetResizable(True)
        boven_sa.setFrameShape(QFrame.Shape.NoFrame)
        boven_sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        boven_sa.setWidget(boven)
        links = QVBoxLayout()
        links.setContentsMargins(0, 0, 0, 0)
        links.setSpacing(12)
        links.addWidget(boven_sa, stretch=1)
        self.status = label("", "statusDim", wrap=True)
        self.status.setVisible(False)
        links.addWidget(self.status)
        self.voortgang = QProgressBar()
        self.voortgang.setVisible(False)
        links.addWidget(self.voortgang)
        self.voortgang_lbl = label("", "statusDim")
        self.voortgang_lbl.setVisible(False)
        links.addWidget(self.voortgang_lbl)
        self.zet_btn = knop("Zet in mijn agenda", "primary", self.start_bijwerken)
        self.zet_btn.setMinimumHeight(64)
        links.addWidget(self.zet_btn)
        self.ander_bestand_btn = knop("Ander bestand kiezen", "big", self.reset_file)
        links.addWidget(self.ander_bestand_btn)
        linkerkant = QWidget()
        linkerkant.setLayout(links)
        linkerkant.setFixedWidth(340)
        lay.addWidget(linkerkant)

        rechts = QFrame()
        rechts.setObjectName("card")
        rl = QVBoxLayout(rechts)
        rl.setContentsMargins(6, 6, 6, 6)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        inhoud = QWidget()
        self.lijst = QVBoxLayout(inhoud)
        self.lijst.setContentsMargins(18, 10, 18, 10)
        self.lijst.setSpacing(0)
        self.lijst.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        sa.setWidget(inhoud)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._lijst_sa = sa
        rl.addWidget(sa)
        lay.addWidget(rechts, stretch=1)
        return w

    def _naar_controle(self) -> None:
        self.plannen = []
        self.stappen.zet(1)
        self.pagina.setCurrentIndex(1)
        self.status.setVisible(False)
        r0 = self.roosters
        soort = sorted({"Conceptrooster" if r.is_concept else "Definitief rooster" for r in r0},
                       reverse=True)
        perioden = [r.periode for r in r0 if r.periode]
        if perioden:
            eerste, laatste = min(p[0] for p in perioden), max(p[1] for p in perioden)
        else:
            dagen = [_dag_van(x) for x in self._alle_shifts()] or [date.today()]
            eerste, laatste = min(dagen), max(dagen)
        self.ondertitel.setText(" en ".join(soort) + "\n" + periode_tekst(eerste, laatste))
        backend = self._koppeling()
        if not backend.can_inspect_calendar:
            self._toon_bestand_plan()
            return
        if not self.settings.calendar_name:
            self._toon_leeg("Kies eerst in welke agenda je diensten moeten komen.")
            self.status.setText("Er is nog geen agenda gekozen. Klik op “Instellingen” of "
                                "ga terug en kies “Andere agenda”.")
            self.status.setVisible(True)
            herpolish(self.status, "statusError")
            return
        self._momentopname = bw.Momentopname(backend)
        self._vraagdagen = {}
        self._plan()

    def _toon_leeg(self, tekst: str) -> None:
        leeg_layout(self.lijst)
        leeg_layout(self.tegels)
        leeg_layout(self.meldingen_links)
        lbl = label(tekst, "lead", wrap=True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lijst.addStretch()
        self.lijst.addWidget(lbl)
        self.lijst.addStretch()
        self.zet_btn.setEnabled(False)

    def _plan(self) -> None:
        """Vergelijk de roosters met de agenda (leest alleen). De eerste keer in
        de achtergrond; daarna uit de momentopname, zonder de agenda te lezen."""
        if self._momentopname is None:
            self._momentopname = bw.Momentopname(self._koppeling())
        backend = self._momentopname
        s = Settings.from_dict(self._indeel_instellingen().to_dict())
        roosters, keuzes = list(self.roosters), self.keuzes
        al_gelezen = backend.gevuld

        def plan():
            naam, sleutel = bw.agenda_kiezen(backend, s.calendar_name, s.calendar_key)
            s.calendar_name, s.calendar_key = naam, sleutel
            beheer = bw.Beheer.laad()
            return naam, sleutel, [bw.maak_plan(r, r.shifts, backend, s, beheer, keuzes)
                                   for r in roosters]

        def klaar(uit) -> None:
            naam, sleutel, plannen = uit
            if (naam, sleutel) != (self.settings.calendar_name, self.settings.calendar_key):
                self.settings.calendar_name, self.settings.calendar_key = naam, sleutel
                self.settings.save()
                self._ververs_agendabalk()
            self.plannen = plannen
            self._toon_plan()

        if al_gelezen:  # alleen rekenen: meteen, zonder wachtscherm
            try:
                uit = plan()
            except Exception as exc:  # noqa: BLE001 - zelfde afhandeling als de achtergrond
                self._fout(str(exc))
                return
            klaar(uit)
            return
        self._toon_leeg("Je agenda wordt bekeken…")
        self._start(plan, klaar)

    def _per_dag(self) -> dict[date, tuple[bw.DagPlan, bw.Plan, Roster]]:
        """Per dag het plan van het rooster dat wint (het laatste op rang)."""
        uit = {}
        for r, p in zip(self.roosters, self.plannen):
            for dp in p.dagen:
                uit[dp.dag] = (dp, p, r)
        return dict(sorted(uit.items()))

    def _soort(self, dp: bw.DagPlan) -> str:
        if dp.dag in self._laten or (dp.keuze_nodig and dp.dag in self._vraagdagen):
            return "laten"
        if dp.keuze_nodig:
            return "kiezen"
        return dp.uitkomst

    def _telt_mee(self, dp: bw.DagPlan, p: bw.Plan) -> bool:
        """Gaat deze dag echt iets veranderen bij de grote knop?"""
        if not dp.stappen or dp.keuze_nodig:
            return False
        return not (dp.netto_weg and not self.keuzes.verwijderen_bevestigd
                    and not p.alleen_toevoegen)

    def _toon_plan(self) -> None:
        dagen = self._per_dag()
        balk = self._lijst_sa.verticalScrollBar()
        positie = balk.value()  # na een vinkje blijft de lijst waar hij was
        # tegels
        leeg_layout(self.tegels)
        tel: dict[str, int] = {}
        for dp, _p, _r in dagen.values():
            tel[self._soort(dp)] = tel.get(self._soort(dp), 0) + 1
        woorden = {**TEGEL, "kiezen": "even kiezen", "laten": "blijft staan"}
        kleuren = {"kiezen": theme.WARN, bw.VERWIJDEREN: theme.DANGER}
        tegels = [(tel[k], woorden[k], kleuren.get(k, theme.TEXT if k != bw.STAAT_ER_AL
                                                   else theme.TEXT_DIM))
                  for k in TEGEL_VOLGORDE if tel.get(k)]
        for i, (n, woord, kleur) in enumerate(tegels):
            t = Tegel(n, woord, kleur)
            t.setMinimumHeight(88)
            self.tegels.addWidget(t, i // 2, i % 2)

        # links: verwijderen of alleen toevoegen
        leeg_layout(self.meldingen_links)
        weg_dagen = sorted(dp.dag for dp, p, _r in dagen.values()
                           if dp.netto_weg and not dp.keuze_nodig and not p.alleen_toevoegen)
        weg = len(weg_dagen)
        alleen = any(p.alleen_toevoegen for p in self.plannen)
        if alleen:
            vak, vl = kaart("warnBox")
            vl.addWidget(self._melding_regel(
                "let-op", theme.WARN, "<b>Deze keer voegt de app alleen toe.</b> Hij past "
                "niets aan en verwijdert niets. Waarom staat rechts."))
            self.meldingen_links.addWidget(vak)
        elif weg:
            vak, vl = kaart("dangerBox")
            vl.addWidget(self._melding_regel(
                "let-op", theme.DANGER,
                "<b>Er gaan diensten uit je agenda</b> op "
                + ", ".join(dag_kort(d) for d in weg_dagen)
                + ", omdat ze niet meer in je rooster staan. Rechts staat welke. "
                "Je eigen afspraken blijven staan."))
            self.verwijder_check = QCheckBox("Ja, dat mag weg")
            self.verwijder_check.setChecked(self.keuzes.verwijderen_bevestigd)
            self.verwijder_check.toggled.connect(self._verwijderen_bevestigd)
            vl.addWidget(self.verwijder_check)
            vl.addWidget(label("Zonder dit vinkje blijven die dagen zoals ze nu zijn.",
                               "statusDim", wrap=True))
            self.meldingen_links.addWidget(vak)
        else:
            vak, vl = kaart()
            vl.addWidget(self._melding_regel(
                "schild", theme.TEXT_DIM,
                f"<b style='color:{theme.TEXT}'>Er wordt niets verwijderd.</b> "
                "Je eigen afspraken blijven staan."))
            self.meldingen_links.addWidget(vak)

        # rechts: meldingen, vragen, dagen
        leeg_layout(self.lijst)
        meldingen = list(dict.fromkeys(m for p in self.plannen for m in p.meldingen))
        for m in meldingen:
            self._vraagkaart(m, [])
        self._vragen(dagen)
        for dag, (dp, p, r) in dagen.items():
            self._dagrijen(dp, p, r)
        self.lijst.addStretch()
        self._ververs_knop()
        QTimer.singleShot(0, lambda: balk.setValue(positie))

    def _melding_regel(self, icoon: str, kleur: str, html_tekst: str) -> QWidget:
        w = QWidget()
        r = QHBoxLayout(w)
        r.setContentsMargins(0, 0, 0, 0)
        r.setSpacing(14)
        r.addWidget(Icoon(icoon, 22, kleur), alignment=Qt.AlignmentFlag.AlignTop)
        t = QLabel(html_tekst)
        t.setTextFormat(Qt.TextFormat.RichText)
        t.setWordWrap(True)
        t.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 15px;")
        r.addWidget(t, stretch=1)
        return w

    def _verwijderen_bevestigd(self, aan: bool) -> None:
        self.keuzes.verwijderen_bevestigd = aan
        self._ververs_knop()

    def _ververs_knop(self) -> None:
        if not self.plannen:
            return
        n = sum(self._telt_mee(dp, p) for dp, p, _r in self._per_dag().values())
        if n:
            self.zet_btn.setText(f"Zet {n} {'wijziging' if n == 1 else 'wijzigingen'} "
                                 "in mijn agenda")
        else:
            self.zet_btn.setText("Er is niets te veranderen")
        self.zet_btn.setEnabled(bool(n) and not self._bezig)

    def _vraagkaart(self, tekst: str, knoppen: list[tuple[str, object]]) -> None:
        vak, vl = kaart("warnBox" if knoppen else "card")
        vl.setContentsMargins(18, 14, 18, 14)
        t = label(tekst, "", wrap=True)
        t.setStyleSheet("font-size: 15px;")
        vl.addWidget(t)
        if knoppen:
            rij = QHBoxLayout()
            for i, (k, actie) in enumerate(knoppen):
                rij.addWidget(knop(k, "smallPrimary" if i == 0 else "small", actie))
            rij.addStretch()
            vl.addLayout(rij)
        self.lijst.addWidget(vak)
        self.lijst.addSpacing(10)

    def _kies(self, **wijziging) -> None:
        """Pas de keuzes aan en plan opnieuw."""
        for k, v in wijziging.items():
            setattr(self.keuzes, k, v)
        self._plan()

    def _kies_dag(self, veld: str, dag: date, aan: bool = True) -> None:
        (getattr(self.keuzes, veld).add if aan else getattr(self.keuzes, veld).discard)(dag)
        # Na het afhandelen van de klik: het vinkje zelf wordt opnieuw opgebouwd.
        QTimer.singleShot(0, self._plan)

    def _kies_alles(self, aan: bool) -> None:
        for dag, (veld, _reden) in self._vraagdagen.items():
            (getattr(self.keuzes, veld).add if aan else getattr(self.keuzes, veld).discard)(dag)
        QTimer.singleShot(0, self._plan)

    def _laat(self, dagen: list[date], nee: str = "") -> None:
        self._laten |= set(dagen)
        if nee:
            self._nee.add(nee)
        self._toon_plan()

    def _vragen(self, dagen) -> None:
        open_ = [(dp, p, r) for dp, p, r in dagen.values()
                 if dp.keuze_nodig and dp.dag not in self._laten]

        def van(uitkomst):
            return [dp.dag for dp, _p, _r in open_ if dp.uitkomst == uitkomst]

        oude = sum(p.oude_items for p in self.plannen)
        if oude and "oude" not in self._nee:
            self._vraagkaart(
                f"In deze agenda staan nog {oude} item(s) die een oudere versie van de app "
                "heeft gezet. Staan in deze agenda alleen jouw eigen diensten? Dan kan de app "
                "die items overnemen en bijwerken.",
                [("Ja, alleen mijn eigen diensten", lambda: self._kies(oude_items_zijn_van_mij=True)),
                 ("Nee, laat ze staan", lambda: self._laat(van(bw.MOGELIJK_DUBBEL), "oude"))])
        ouder = van(bw.OUDER_ROOSTER)
        if ouder:
            self._vraagkaart(
                f"Dit rooster is ouder dan wat al in je agenda staat ({len(ouder)} "
                f"{'dag' if len(ouder) == 1 else 'dagen'}). Toch dit rooster gebruiken?",
                [("Toch verwerken", lambda: self._kies(ouder_toestaan=True)),
                 ("Overslaan", lambda: self._laat(ouder))])
        anders = van(bw.ANDERE_INHOUD)
        if anders:
            self._vraagkaart(
                "Er staat al een rooster met dezelfde datum maar een andere inhoud in je "
                f"agenda ({len(anders)} {'dag' if len(anders) == 1 else 'dagen'}). "
                "Welke wil je houden?",
                [("Dit rooster gebruiken", lambda: self._kies(andere_inhoud_toestaan=True)),
                 ("Laat staan wat er staat", lambda: self._laat(anders))])
        onbegrepen = [dp.dag for dp, _p, _r in open_ if dp.uitkomst == bw.OVERGESLAGEN]
        if onbegrepen:
            regels = [regel for r in self.roosters for regel in r.onbegrepen.get(None, [])]
            self._vraagkaart(
                "In het rooster staat een regel die de app niet begrijpt"
                + (f": “{regels[0]}”" if regels else "") + ". Daarom verandert de app niets. "
                "Wil je toch de diensten toevoegen? Hij past dan niets aan en verwijdert niets.",
                [("Toch alleen toevoegen", lambda: self._kies(onbegrepen_bevestigd=True)),
                 ("Niets doen", lambda: self._laat(onbegrepen))])
        # Dagen met iets van de app dat niet precies past: onthouden, ook als
        # ze na een vinkje geen vraag meer zijn, zodat de lijst niet verspringt.
        for dp, p, _r in dagen.values():
            if not dp.keuze_nodig or dp.dag in self._laten:
                continue
            if dp.uitkomst == bw.ZELF_AANGEPAST:
                self._vraagdagen.setdefault(dp.dag, ("overschrijf_aangepast", dp.reden))
            elif dp.uitkomst == bw.MOGELIJK_DUBBEL and not p.oude_items:
                self._vraagdagen.setdefault(dp.dag, ("vervang_oude_items", dp.reden))
        if self._vraagdagen:
            self._vinkjeskaart()

    def _vinkjeskaart(self) -> None:
        n = len(self._vraagdagen)
        vak, vl = kaart("warnBox")
        vl.setContentsMargins(18, 14, 18, 14)
        t = label(f"Op {n} {'dag' if n == 1 else 'dagen'} staat al iets van de app dat niet "
                  "precies bij het rooster past, bijvoorbeeld omdat je het zelf hebt aangepast. "
                  "Vink aan wat het rooster mag vervangen. Wat je niet aanvinkt, blijft staan.",
                  "", wrap=True)
        t.setStyleSheet("font-size: 15px;")
        vl.addWidget(t)
        rij = QHBoxLayout()
        rij.addWidget(knop("Alles vervangen", "smallPrimary", lambda: self._kies_alles(True)))
        rij.addWidget(knop("Alles laten staan", "small", lambda: self._kies_alles(False)))
        rij.addStretch()
        vl.addLayout(rij)
        for dag, (veld, reden) in sorted(self._vraagdagen.items()):
            regel = QHBoxLayout()
            vink = QCheckBox(dag_kort(dag))
            vink.setChecked(dag in getattr(self.keuzes, veld))
            vink.toggled.connect(lambda aan, d=dag, v=veld: self._kies_dag(v, d, aan))
            regel.addWidget(vink)
            uitleg = label(reden, "statusDim", wrap=True)
            regel.addWidget(uitleg, stretch=1)
            vl.addLayout(regel)
        self.lijst.addWidget(vak)
        self.lijst.addSpacing(10)

    def _rij(self, datum: str, kleur: str | None, naam: str, tijd: str, taak: str,
             pil: QWidget | None, gedimd: bool = False) -> None:
        rij = QFrame()
        rij.setStyleSheet(f"QFrame {{ border: none; border-bottom: 1px solid {theme.BORDER}; }}"
                          " QLabel { border: none; }")
        r = QHBoxLayout(rij)
        r.setContentsMargins(0, 14, 0, 14)
        r.setSpacing(10)
        d = QLabel(datum)
        d.setFixedWidth(84)
        d.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 16px;")
        r.addWidget(d)
        if kleur is None:
            r.addSpacing(16)
        else:
            r.addWidget(Stip(kleur, 16))
        n = QLabel(naam if len(naam) <= 16 else naam[:15] + "…")
        n.setToolTip(naam)
        n.setFixedWidth(124)
        n.setStyleSheet(f"font-size: 17px; font-weight: 700; "
                        f"color: {theme.TEXT_DIM if gedimd else theme.TEXT};")
        r.addWidget(n)
        t = QLabel(tijd)
        t.setFixedWidth(104)
        t.setStyleSheet("font-size: 16px;")
        r.addWidget(t)
        k = QLabel(taak)
        k.setToolTip(taak)
        k.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 15px;")
        k.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        r.addWidget(k, stretch=1)
        if pil is not None:
            r.addWidget(pil)
        self.lijst.addWidget(rij)

    def _naam(self, x: Shift) -> str:
        if x.shift_type == ShiftType.AFSPRAAK:
            return x.display_name.split(" - ")[0]
        naam = self.settings.name_for(x.sleutel)
        if x.is_concept and self.settings.rules.get("mark_concept", True):
            naam += " (concept)"
        return naam

    def _dagrijen(self, dp: bw.DagPlan, p: bw.Plan, r: Roster) -> None:
        s = self._indeel_instellingen()
        diensten = sorted((x for x in bw._zichtbaar(r.shifts, s) if _dag_van(x) == dp.dag),
                          key=lambda x: x.start)
        soort = self._soort(dp)
        pil_soort = dp.uitkomst if soort == "kiezen" else soort
        datum = dag_kort(dp.dag)
        if not diensten:
            self._rij(datum, None, "Geen dienst", "", dp.reden if soort == bw.OVERGESLAGEN else "",
                      _pil(pil_soort), gedimd=True)
            datum = ""
        for i, x in enumerate(diensten):
            taak = x.info if x.shift_type != ShiftType.AFSPRAAK else ""
            stap = next((st for st in dp.stappen if st.actie == "werk_bij" and st.na
                         and st.na.start == x.start and st.voor), None)
            if stap and (stap.voor.start, stap.voor.end) != (stap.na.start, stap.na.end):
                was = tijden(stap.voor.start, stap.voor.end, stap.voor.all_day)
                taak = f"{taak} · was {was}" if taak else f"was {was}"
            if soort == bw.OVERGESLAGEN and dp.reden and i == 0:
                taak = dp.reden
            self._rij(datum if i == 0 else "", theme.kleur_voor(s, x.sleutel), self._naam(x),
                      tijden(x.start, x.end, x.all_day), taak,
                      _pil(pil_soort) if i == 0 else None)
        if dp.netto_weg and not dp.keuze_nodig and diensten:
            for st in dp.stappen:
                if st.actie == "verwijder" and st.voor:
                    v = st.voor
                    naam, _, taak = v.title.partition(" - ")
                    self._rij("", "", naam, tijden(v.start, v.end, v.all_day), taak,
                              _pil(bw.VERWIJDEREN), gedimd=True)

    # ----- .ics-route: geen plan, alleen een bestand --------------------
    def _bestand_shifts(self) -> list[tuple[Roster, list[Shift]]]:
        """Per rooster de diensten die in het bestand komen; bij overlap wint
        per dag het rooster met de hoogste rang."""
        s = self._indeel_instellingen()
        winnaar: dict[date, Roster] = {}
        for r in self.roosters:
            for x in r.shifts:
                winnaar[_dag_van(x)] = r
        return [(r, [x for x in bw._zichtbaar(r.shifts, s) if winnaar[_dag_van(x)] is r])
                for r in self.roosters]

    def _toon_bestand_plan(self) -> None:
        self.plannen = []
        leeg_layout(self.tegels)
        leeg_layout(self.meldingen_links)
        leeg_layout(self.lijst)
        per_rooster = self._bestand_shifts()
        n = sum(len(xs) for _r, xs in per_rooster)
        self.tegels.addWidget(Tegel(n, "diensten in het bestand"), 0, 0)
        vak, vl = kaart("warnBox")
        vl.addWidget(self._melding_regel(
            "info", theme.WARN,
            "<b>De app maakt een bestand dat je zelf in je agenda inleest.</b> Je gekozen "
            "agenda kan de app niet inzien. Bijwerken, verwijderen en ongedaan maken kunnen "
            "hier dus niet."))
        self.meldingen_links.addWidget(vak)
        for m in dict.fromkeys(m for r in self.roosters for m in r.meldingen):
            self._vraagkaart(m, [])
        s = self._indeel_instellingen()
        vorige = None
        for _r, xs in per_rooster:
            for x in sorted(xs, key=lambda x: x.start):
                d = _dag_van(x)
                self._rij(dag_kort(d) if d != vorige else "", theme.kleur_voor(s, x.sleutel),
                          self._naam(x), tijden(x.start, x.end, x.all_day),
                          x.info if x.shift_type != ShiftType.AFSPRAAK else "",
                          _pil("bestand") if d != vorige else None)
                vorige = d
        self.lijst.addStretch()
        self.zet_btn.setText(f"Maak het bestand ({n} {'dienst' if n == 1 else 'diensten'})")
        self.zet_btn.setEnabled(bool(n))

    # ------------------------------------------------------------------
    def start_bijwerken(self) -> None:
        if self._bezig or not self.roosters:
            return
        backend = self._koppeling()
        if not backend.can_inspect_calendar:
            self._maak_bestand(backend)
            return
        s = Settings.from_dict(self._indeel_instellingen().to_dict())
        roosters, plannen, keuzes = list(self.roosters), list(self.plannen), self.keuzes
        self.status.setVisible(False)
        self.voortgang.setRange(0, 0)
        self.voortgang_lbl.setText("Bezig met je agenda…")

        def uitvoeren(voortgang):
            beheer = bw.Beheer.laad()
            totaal = bw.Uitkomst()
            gebruikt = []
            for i, (r, plan) in enumerate(zip(roosters, plannen)):
                if any(_overlapt(r, eerder) for eerder in roosters[:i]):
                    # Een eerder rooster heeft deze dagen net veranderd.
                    plan = bw.maak_plan(r, r.shifts, backend, s, beheer, keuzes)
                uit = bw.voer_uit(plan, backend, beheer, keuzes, voortgang)
                gebruikt.append(plan)
                totaal.toegevoegd += uit.toegevoegd
                totaal.bijgewerkt += uit.bijgewerkt
                totaal.verwijderd += uit.verwijderd
                totaal.dagen_klaar += uit.dagen_klaar
                totaal.niet_bijgewerkt.update(uit.niet_bijgewerkt)
                totaal.fouten += uit.fouten
            return totaal, gebruikt

        self._start(uitvoeren, self._klaar_bijgewerkt, met_voortgang=True)

    def _maak_bestand(self, backend) -> None:
        per_rooster = self._bestand_shifts()
        naam = self.settings.calendar_name
        self.voortgang.setRange(0, 0)
        self.voortgang_lbl.setText("Het bestand wordt gemaakt…")

        def maak():
            backend.begin(naam)
            for r, xs in per_rooster:
                bw.vaste_uids(xs, r.personeelsnummer)
                for x in xs:
                    backend.add_shift(naam, x)
            backend.finalize()
            return backend.last_output, sum(len(xs) for _r, xs in per_rooster)

        self._start(maak, self._klaar_bestand)

    # ------------------------------------------------------------------
    # Stap 3: klaar
    # ------------------------------------------------------------------
    def _bouw_klaar(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 20, 0, 0)
        lay.setSpacing(16)
        lay.addStretch()
        self.vink = Vinkrondje(120)
        lay.addWidget(self.vink, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addSpacing(10)
        self.klaar_titel = label("Je agenda is bijgewerkt", "pageTitle")
        self.klaar_titel.setStyleSheet("font-size: 36px;")
        self.klaar_titel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.klaar_titel)
        self.klaar_tekst = label("", "lead", wrap=True)
        self.klaar_tekst.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.klaar_tekst.setStyleSheet("font-size: 18px;")
        lay.addWidget(self.klaar_tekst)
        lay.addSpacing(12)
        rij = QHBoxLayout()
        rij.addStretch()
        self.nog_een_btn = knop("Nog een rooster inlezen", "primary", self.reset_file)
        self.nog_een_btn.setMinimumWidth(280)
        rij.addWidget(self.nog_een_btn)
        rij.addSpacing(12)
        self.ongedaan_btn = knop("Ongedaan maken", "big", self.maak_ongedaan)
        self.ongedaan_btn.setMinimumWidth(220)
        self.ongedaan_btn.setMinimumHeight(60)
        rij.addWidget(self.ongedaan_btn)
        rij.addStretch()
        lay.addLayout(rij)
        self.veranderd_btn = knop("Bekijk wat er veranderd is", "link", self.toon_veranderingen)
        lay.addWidget(self.veranderd_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.niet_vak = QVBoxLayout()
        lay.addLayout(self.niet_vak)
        lay.addStretch()
        vak, vl = kaart()
        vl.setContentsMargins(22, 16, 22, 16)
        self.klaar_info = self._melding_regel(
            "info", theme.TEXT_DIM, "Krijg je een nieuw rooster? Lees het gewoon opnieuw in. "
            "De app past alleen aan wat veranderd is en raakt je eigen afspraken niet aan.")
        vl.addWidget(self.klaar_info)
        self.klaar_info_lbl = self.klaar_info.findChild(QLabel)
        lay.addWidget(vak)
        return w

    def _naar_klaar(self) -> None:
        self.stappen.zet(2)
        self.pagina.setCurrentIndex(2)
        leeg_layout(self.niet_vak)

    def _klaar_bijgewerkt(self, resultaat) -> None:
        uit, gebruikt = resultaat
        self.uitkomst, self._uitgevoerd = uit, gebruikt
        # Dagen waar eerst een keuze nodig was en die niet gemaakt is.
        for p in gebruikt:
            for dp in p.dagen:
                if dp.keuze_nodig and dp.dag not in uit.dagen_klaar:
                    uit.niet_bijgewerkt.setdefault(
                        dp.dag, "je koos om het te laten staan"
                        if dp.dag in self._laten or dp.dag in self._vraagdagen else dp.reden)
        self._naar_klaar()
        delen = [f"{n} {w}" for n, w in ((uit.toegevoegd, "toegevoegd"),
                                         (uit.bijgewerkt, "aangepast"),
                                         (uit.verwijderd, "verwijderd")) if n]
        delen = delen or ["er hoefde niets te veranderen"]
        delen.append(f"agenda {self.settings.calendar_name}")
        self.klaar_tekst.setText(" · ".join(delen))
        gedaan = uit.toegevoegd + uit.bijgewerkt + uit.verwijderd
        if uit.fouten and not gedaan:
            self.vink.zet(theme.DANGER, "uitroep")
            self.klaar_titel.setText("Het bijwerken is niet gelukt")
            self.klaar_tekst.setText(" ".join(uit.fouten))
        elif uit.niet_bijgewerkt or uit.fouten:
            self.vink.zet(theme.WARN, "uitroep")
            self.klaar_titel.setText("Je agenda is bijgewerkt, op een paar dagen na")
        else:
            self.vink.zet(theme.OK, "vink")
            self.klaar_titel.setText("Je agenda is bijgewerkt")
        if uit.niet_bijgewerkt or (uit.fouten and gedaan):
            vak, vl = kaart("warnBox")
            vak.setFixedWidth(620)
            vl.addWidget(label("Deze dagen zijn niet bijgewerkt:", "", wrap=True))
            for dag, reden in sorted(uit.niet_bijgewerkt.items()):
                vl.addWidget(label(f"{dag_kort(dag)}: {reden}", "statusDim", wrap=True))
            for f in uit.fouten if gedaan else []:
                vl.addWidget(label(f, "statusError", wrap=True))
            self.niet_vak.addWidget(vak, alignment=Qt.AlignmentFlag.AlignCenter)
        self.ongedaan_btn.setVisible(bw.kan_ongedaan())
        self.veranderd_btn.setVisible(bool(uit.dagen_klaar))
        self.klaar_info_lbl.setText(
            "Krijg je een nieuw rooster? Lees het gewoon opnieuw in. De app past alleen aan "
            "wat veranderd is en raakt je eigen afspraken niet aan.")

    def _klaar_bestand(self, resultaat) -> None:
        pad, n = resultaat
        self._naar_klaar()
        self.vink.zet(theme.OK, "vink")
        self.klaar_titel.setText("Je bestand staat klaar")
        self.klaar_tekst.setText(f"{n} {'dienst' if n == 1 else 'diensten'}"
                                 + (f" · {Path(pad).name} in {Path(pad).parent.name}" if pad else ""))
        self.ongedaan_btn.setVisible(False)
        self.veranderd_btn.setVisible(False)
        self.klaar_info_lbl.setText(
            "Open het bestand in je agenda-app om de diensten toe te voegen. De app kan die "
            "agenda niet inzien: bijwerken, verwijderen en ongedaan maken kunnen hier niet.")

    def maak_ongedaan(self) -> None:
        if self._bezig:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Ongedaan maken")
        box.setText("De app zet je agenda terug zoals hij was vóór deze keer. Items die je "
                    "sindsdien zelf hebt veranderd blijven staan.\n\nDoorgaan?")
        ja = box.addButton("Ja, maak ongedaan", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Nee", QMessageBox.ButtonRole.RejectRole)
        box.setStyleSheet(theme.QSS)
        if not self._bevestig(box, ja):
            return
        backend = self._koppeling()
        self.klaar_tekst.setText("Bezig met terugzetten…")
        self._start(lambda: bw.maak_ongedaan(backend, bw.Beheer.laad()), self._klaar_ongedaan)

    def _bevestig(self, box: QMessageBox, ja) -> bool:
        """Toon de vraag; apart zodat een test hem kan beantwoorden."""
        box.exec()
        return box.clickedButton() is ja

    def _klaar_ongedaan(self, uit) -> None:
        leeg_layout(self.niet_vak)
        if uit.fouten and not uit.hersteld:
            self.vink.zet(theme.DANGER, "uitroep")
            self.klaar_titel.setText("Ongedaan maken is niet gelukt")
            self.klaar_tekst.setText(" ".join(uit.fouten))
        else:
            self.vink.zet(theme.OK, "vink")
            self.klaar_titel.setText("Je agenda is teruggezet")
            tekst = f"{uit.hersteld} item(s) teruggezet"
            if uit.blijft_staan:
                tekst += (f" · {len(uit.blijft_staan)} item(s) heb je zelf veranderd; "
                          "die blijven staan")
            if uit.fouten:
                tekst += " · " + " ".join(uit.fouten)
            self.klaar_tekst.setText(tekst)
        self.ongedaan_btn.setVisible(bw.kan_ongedaan() and bool(uit.fouten))
        self.veranderd_btn.setVisible(False)

    def toon_veranderingen(self) -> None:
        regels = []
        klaar = set(self.uitkomst.dagen_klaar) if self.uitkomst else set()
        woord = {"voeg_toe": "erbij", "werk_bij": "aangepast", "verwijder": "weg"}
        for p in getattr(self, "_uitgevoerd", []):
            for dp in p.dagen:
                if dp.dag not in klaar or not dp.stappen:
                    continue
                regels.append(dag_lang(dp.dag))
                for st in dp.stappen:
                    item = st.na if st.actie != "verwijder" else st.voor
                    regels.append(f"   {woord[st.actie]}: {item.title}, "
                                  f"{tijden(item.start, item.end, item.all_day)}")
        d = QDialog(self)
        d.setWindowTitle("Wat er veranderd is")
        d.setStyleSheet(theme.QSS)
        d.resize(620, 520)
        lay = QVBoxLayout(d)
        lay.setContentsMargins(24, 22, 24, 22)
        lay.addWidget(label("Wat er veranderd is", "appTitle"))
        tekst = QPlainTextEdit("\n".join(regels) or "Er is niets veranderd.")
        tekst.setReadOnly(True)
        lay.addWidget(tekst, stretch=1)
        rij = QHBoxLayout()
        rij.addStretch()
        rij.addWidget(knop("Sluiten", "secondary", d.accept))
        lay.addLayout(rij)
        d.exec()

    # ------------------------------------------------------------------
    def reset_file(self) -> None:
        """Terug naar stap 1. Instellingen en de gekozen agenda blijven staan."""
        if self._bezig:
            return
        self.roosters, self.plannen, self.paden = [], [], []
        self._ruw = {}
        self.keuzes = bw.Keuzes()
        self._laten = set()
        self.uitkomst = None
        leeg_layout(self.lijst)
        leeg_layout(self.tegels)
        leeg_layout(self.meldingen_links)
        self.drop_zone.toon_fout("")
        self.stappen.zet(0)
        self.pagina.setCurrentIndex(0)

    # ------------------------------------------------------------------
    def _na_instellingen(self, settings: Settings | None = None) -> None:
        """Instellingen zijn veranderd: opnieuw indelen en plannen."""
        self.settings = settings or Settings.load()
        self._sluit_extra()
        self._ververs_agendabalk()
        if self.roosters and self.pagina.currentIndex() == 1:
            self._deel_in()
            self._naar_controle()

    def open_settings(self) -> None:
        if self._bezig:
            return
        panel = SettingsPanel(self.settings)
        panel.saved.connect(lambda: self._na_instellingen())
        panel.cancelled.connect(self._sluit_extra)
        panel.instelhulp.connect(self.open_instelhulp)
        self._toon_extra(panel)

    def _voorbeeld_shifts(self) -> list[Shift]:
        return [x for r in self.roosters for x in self._ruw.get(id(r), [])]

    def open_instelhulp(self) -> None:
        if self._bezig:
            return
        from .wizard import Instelhulp

        hulp = Instelhulp(self.settings, all_backends(), self._voorbeeld_shifts())
        hulp.klaar.connect(self._na_instellingen)
        hulp.later.connect(self._sluit_extra)
        self._toon_extra(hulp)

    def open_agenda_kiezen(self) -> None:
        if self._bezig:
            return
        from .wizard import Instelhulp

        hulp = Instelhulp(self.settings, all_backends(), alleen_agenda=True)
        hulp.klaar.connect(self._na_instellingen)
        hulp.later.connect(self._sluit_extra)
        self._toon_extra(hulp)

    def open_handleiding(self) -> None:
        from ..resources import asset_path, open_path

        pdf = asset_path("handleiding.pdf")
        if pdf.exists():
            open_path(pdf)

    def open_feedback(self) -> None:
        from .feedback_dialog import FeedbackDialog

        FeedbackDialog(self, rooster=self.paden[0] if self.paden else "").exec()
