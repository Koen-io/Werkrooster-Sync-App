"""De instelhulp: agenda kiezen, diensten benoemen, kiezen wat je wilt zien.

Met een live voorbeeld uit het eigen rooster als dat er al is, anders uit een
ingebouwd voorbeeld. Er wordt pas iets opgeslagen bij "Klaar, opslaan";
"Later afmaken" laat de instellingen zoals ze waren.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.classifier import apply_classification
from ..core.models import Shift, ShiftType
from ..core.settings import Settings, controleer_dienstsoorten, minuten
from . import theme
from .settings_dialog import REMINDER_PRESETS, _Worker
from .widgets import (
    KeuzeKaart,
    Stip,
    ToggleSwitch,
    dag_lang,
    herpolish,
    kaart,
    knop,
    label,
    leeg_layout,
)

#: Kleuren voor nieuwe dienstsoorten, op volgorde.
STANDAARD = {t.value for t in ShiftType}  # ochtend, laat, nacht: blijven altijd staan
NIEUWE_KLEUREN = ["#5AC8FA", "#FF6B9A", "#C8E05A", "#E0A2FF", "#30C8C9"]

#: Tekst op de kaarten van stap 1, per koppeling.
KOPPELING_TEKST = {
    "apple_calendar": ("Apple Agenda", "Op je Mac, en via iCloud ook op je iPhone.", "agenda"),
    "outlook": ("Outlook", "Op je Windows-computer.", "mail"),
    "ics_export": ("Een andere agenda",
                   "Google Agenda en andere. Je krijgt een bestand dat je zelf inleest.",
                   "download"),
}


def ingebouwd_voorbeeld() -> list[Shift]:
    """Een paar diensten zoals ze uit een rooster komen, voor als er nog geen
    eigen rooster gekozen is."""
    def dienst(dag: int, soort: str, info: str = "", concept: bool = False) -> Shift:
        d = datetime(2026, 11, dag)
        x = Shift(start=d, end=d + timedelta(days=1), original_summary=soort,
                  all_day=True, info=info)
        x.roster_date, x.is_concept = d.date(), concept
        return x
    return [
        dienst(23, "DIENST 07:00-16:30", "Bureaudienst Despatcher"),
        dienst(24, "DIENST 14:00-22:30", "Bureaudienst Despatcher"),
        dienst(25, "DIENST 23:00-07:00", "Bureaudienst Despatcher"),
        dienst(26, "DIENST 09:30-20:00", "Teamdag"),
        dienst(28, "Vrij"),
        dienst(30, "DIENST 07:00-16:30", "Bureaudienst Despatcher", concept=True),
    ]


def ingedeeld(ruw: list[Shift], s: Settings) -> list[Shift]:
    """Een kopie van de diensten, ingedeeld met deze instellingen."""
    return apply_classification(copy.deepcopy(ruw), s)


# ----------------------------------------------------------------------
class Tijdbalk(QWidget):
    """De dag van 00:00 tot 24:00 met een gekleurd vak per dienstsoort."""

    def __init__(self, s: Settings, parent=None):
        super().__init__(parent)
        self.s = s
        self.setMinimumHeight(86)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), 54.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.CARD))
        p.drawRoundedRect(QRectF(0, 0, w, h), 14, 14)
        f = self.font()
        f.setPixelSize(15)
        f.setBold(True)
        p.setFont(f)
        grenzen = {0, 1440}
        p.setClipRect(QRectF(0, 0, w, h))
        for d in self.s.dienstsoorten:
            lo, hi = minuten(d.get("van", "")), minuten(d.get("tot", ""))
            if lo is None or hi is None or lo == hi:
                continue
            grenzen |= {lo, hi}
            stukken = [(lo, hi)] if lo < hi else [(lo, 1440), (0, hi)]
            for a, b in stukken:
                r = QRectF(w * a / 1440, 0, w * (b - a) / 1440, h)
                pad_r = r.adjusted(1 if a else 0, 0, -1 if b < 1440 else 0, 0)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(d.get("kleur") or theme.ACCENT))
                if a == 0 or b == 1440:
                    p.drawRoundedRect(pad_r, 14, 14)
                    # alleen de buitenkant rond
                    p.drawRect(pad_r.adjusted(14 if a == 0 else 0, 0, -14 if b == 1440 else 0, 0))
                else:
                    p.drawRect(pad_r)
                p.setPen(QColor(theme.ACCENT_TEXT))
                naam = self.s.names.get(d.get("id", ""), "")
                if r.width() > p.fontMetrics().horizontalAdvance(naam) + 8:
                    p.drawText(r, Qt.AlignmentFlag.AlignCenter, naam)
        p.setClipping(False)
        f.setBold(False)
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT_DIM))
        for m in sorted(grenzen):
            tekst = f"{m // 60:02d}:{m % 60:02d}"
            tw = p.fontMetrics().horizontalAdvance(tekst)
            x = min(max(0.0, w * m / 1440 - tw / 2), w - tw)
            p.drawText(QPointF(x, h + 24), tekst)
        p.end()


class DienstsoortenEditor(QWidget):
    """De lijst dienstsoorten: naam, begintijd van-tot, kleur. Werkt direct op
    de meegegeven instellingen (een kopie); ``gewijzigd`` bij elke verandering."""

    gewijzigd = Signal()

    def __init__(self, s: Settings, parent=None):
        super().__init__(parent)
        self.s = s
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(12)
        self._rijen = QVBoxLayout()
        self._rijen.setSpacing(12)
        self._lay.addLayout(self._rijen)
        self.toevoegen_btn = knop("+ Nog een dienstsoort, bijvoorbeeld Dagdienst", "dashed",
                                  self._voeg_toe)
        self._lay.addWidget(self.toevoegen_btn)
        self.fout = label("", "statusError", wrap=True)
        self.fout.setVisible(False)
        self._lay.addWidget(self.fout)
        self._bouw()

    def _bouw(self) -> None:
        leeg_layout(self._rijen)
        self.naam_edits: dict[str, QLineEdit] = {}
        for d in self.s.dienstsoorten:
            sid = d["id"]
            rij = QFrame()
            rij.setObjectName("card")
            lay = QHBoxLayout(rij)
            lay.setContentsMargins(20, 12, 16, 12)
            lay.setSpacing(10)
            lay.addWidget(Stip(d.get("kleur") or theme.ACCENT, 22))
            naam = QLineEdit(self.s.names.get(sid, ""))
            naam.setPlaceholderText("Naam")
            naam.setMinimumWidth(110)
            naam.setStyleSheet("font-size: 17px; font-weight: 600;")
            naam.textChanged.connect(lambda t, sid=sid: self._zet_naam(sid, t))
            self.naam_edits[sid] = naam
            lay.addWidget(naam, stretch=2)
            lay.addWidget(label("begint tussen", "statusDim"))
            for veld in ("van", "tot"):
                e = QLineEdit(d.get(veld, ""))
                e.setInputMask("99:99")
                e.setFixedWidth(82)
                e.setAlignment(Qt.AlignmentFlag.AlignCenter)
                e.setStyleSheet("font-size: 17px; font-weight: 600;")
                e.textChanged.connect(lambda t, d=d, veld=veld: self._zet_tijd(d, veld, t))
                lay.addWidget(e)
                if veld == "van":
                    lay.addWidget(label("en", "statusDim"))
            if sid not in STANDAARD and len(self.s.dienstsoorten) > 1:
                weg = knop("Weg", "small", lambda _=False, sid=sid: self._verwijder(sid))
                weg.setToolTip("Deze dienstsoort weghalen")
                lay.addWidget(weg)
            else:
                lay.addStretch()
            self._rijen.addWidget(rij)

    def _zet_naam(self, sid: str, tekst: str) -> None:
        self.s.names[sid] = tekst.strip()
        self.gewijzigd.emit()

    def _zet_tijd(self, d: dict, veld: str, tekst: str) -> None:
        d[veld] = tekst if minuten(tekst) is not None else tekst.strip(":")
        self.gewijzigd.emit()

    def _voeg_toe(self) -> None:
        gebruikt = {d.get("kleur") for d in self.s.dienstsoorten}
        kleur = next((k for k in NIEUWE_KLEUREN if k not in gebruikt), NIEUWE_KLEUREN[0])
        self.s.nieuwe_dienstsoort("Dagdienst", "", "", kleur)
        self._bouw()
        self.gewijzigd.emit()

    def _verwijder(self, sid: str) -> None:
        self.s.verwijder_dienstsoort(sid)
        self._bouw()
        self.gewijzigd.emit()

    def controleer(self) -> bool:
        """Toon wat er mis is; True als alles klopt (overlap mag niet)."""
        fouten = controleer_dienstsoorten(self.s.dienstsoorten, self.s.names)
        self.fout.setText("\n".join(fouten))
        self.fout.setVisible(bool(fouten))
        return not fouten


# ----------------------------------------------------------------------
class Instelhulp(QWidget):
    """Instelhulp in drie stappen, of met ``alleen_agenda`` alleen stap 1."""

    klaar = Signal(object)   # de nieuwe Settings, al opgeslagen
    later = Signal()

    def __init__(self, settings: Settings, backends: list, voorbeeld: list[Shift] | None = None,
                 alleen_agenda: bool = False, parent=None):
        super().__init__(parent)
        self.s = Settings.from_dict(settings.to_dict())
        self.backends = backends
        self.alleen_agenda = alleen_agenda
        ruw = list(voorbeeld or [])
        self.eigen_rooster = bool(ruw)
        ruw = ruw or ingebouwd_voorbeeld()
        if not any(x.is_concept for x in ruw):
            # Laat ook zien hoe een conceptdienst eruitziet: een week later.
            dienst = next((x for x in ruw if "DIENST" in x.original_summary.upper()), None)
            if dienst:
                c = copy.deepcopy(dienst)
                c.start, c.end = c.start + timedelta(days=7), c.end + timedelta(days=7)
                c.roster_date = (c.roster_date or dienst.start.date()) + timedelta(days=7)
                c.is_concept = True
                ruw.append(c)
        self.ruw = ruw
        self._worker: _Worker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(56, 32, 56, 32)
        root.setSpacing(18)

        kop = QHBoxLayout()
        kop.setSpacing(16)
        kop.addWidget(label("Agenda kiezen" if alleen_agenda else "Instelhulp", "appTitle"))
        self.streepjes = []
        if not alleen_agenda:
            for _ in range(3):
                st = QFrame()
                st.setFixedSize(40, 6)
                self.streepjes.append(st)
                kop.addWidget(st)
            self.stap_lbl = label("", "statusDim")
            self.stap_lbl.setStyleSheet("font-size: 16px;")
            kop.addWidget(self.stap_lbl)
        kop.addStretch()
        self.later_btn = knop("Annuleren" if alleen_agenda else "Later afmaken", "secondary",
                              self.later.emit)
        kop.addWidget(self.later_btn)
        root.addLayout(kop)

        self.pagina = QStackedWidget()
        self.pagina.addWidget(self._stap_agenda())
        if not alleen_agenda:
            self.pagina.addWidget(self._stap_diensten())
            self.pagina.addWidget(self._stap_voorkeuren())
        root.addWidget(self.pagina, stretch=1)

        onder = QHBoxLayout()
        self.terug_btn = knop("Terug", "big", self._terug)
        self.terug_btn.setMinimumWidth(130)
        onder.addWidget(self.terug_btn)
        onder.addStretch()
        self.hint = label("", "statusDim")
        self.hint.setStyleSheet("font-size: 15px;")
        onder.addWidget(self.hint)
        onder.addSpacing(16)
        self.volgende_btn = knop("Volgende", "primary", self._volgende)
        self.volgende_btn.setMinimumWidth(200)
        onder.addWidget(self.volgende_btn)
        root.addLayout(onder)
        self._toon(0)

    # ------------------------------------------------------------------
    def _toon(self, i: int) -> None:
        self.pagina.setCurrentIndex(i)
        laatste = self.alleen_agenda or i == 2
        self.terug_btn.setVisible(i > 0)
        self.volgende_btn.setText("Opslaan" if self.alleen_agenda
                                  else "Klaar, opslaan" if laatste else "Volgende")
        self.hint.setText("Opnieuw doorlopen kan altijd via Instellingen › Instelhulp starten."
                          if laatste and not self.alleen_agenda else "")
        if self.streepjes:
            self.stap_lbl.setText(f"Stap {i + 1} van 3")
            for n, st in enumerate(self.streepjes):
                st.setStyleSheet(f"background: {theme.ACCENT if n <= i else theme.BORDER};"
                                 "border-radius: 3px;")
        if i == 1:
            self._ververs_diensten()
        if i == 2:
            self._ververs_voorkeuren()

    def _terug(self) -> None:
        self._toon(max(0, self.pagina.currentIndex() - 1))

    def _volgende(self) -> None:
        i = self.pagina.currentIndex()
        if i == 0 and not self._agenda_ok():
            return
        if i == 1 and not self.editor.controleer():
            return
        if self.alleen_agenda or i == 2:
            self._opslaan()
        else:
            self._toon(i + 1)

    def _opslaan(self) -> None:
        if not self.alleen_agenda:
            self._voorkeuren_toepassen()
        self.s.save()
        self.klaar.emit(self.s)

    # ------------------------------------------------------------------
    # Stap 1: agenda
    # ------------------------------------------------------------------
    def _kop(self, lay: QVBoxLayout, titel: str, uitleg: str) -> None:
        lay.addWidget(label(titel, "pageTitle"))
        u = label(uitleg, "lead", wrap=True)
        u.setMaximumWidth(900)
        lay.addWidget(u)
        lay.addSpacing(10)

    def _stap_agenda(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self._kop(lay, "Waar wil je je rooster zien?",
                  "Kies de agenda die je op je telefoon gebruikt. Je kunt dit later altijd "
                  "veranderen via Instellingen.")
        kaarten = QHBoxLayout()
        kaarten.setSpacing(20)
        self.kaarten: dict[str, KeuzeKaart] = {}
        for b in self.backends:
            titel, uitleg, icoon = KOPPELING_TEKST.get(b.id, (b.label, "", "agenda"))
            k = KeuzeKaart(titel, uitleg, icoon=icoon)
            k.setMinimumHeight(220)
            k.clicked.connect(lambda b=b: self._kies_koppeling(b))
            self.kaarten[b.id] = k
            kaarten.addWidget(k, stretch=1)
        lay.addLayout(kaarten)
        lay.addSpacing(14)

        self.agenda_vak = QWidget()
        av = QVBoxLayout(self.agenda_vak)
        av.setContentsMargins(0, 0, 0, 0)
        av.setSpacing(10)
        vraag = QLabel("In welke agenda moeten je diensten komen?")
        vraag.setStyleSheet("font-size: 17px; font-weight: 700;")
        av.addWidget(vraag)
        rij = QHBoxLayout()
        rij.setSpacing(16)
        self.agenda_combo = QComboBox()
        self.agenda_combo.setMinimumHeight(52)
        self.agenda_combo.setStyleSheet("font-size: 17px; font-weight: 600;")
        rij.addWidget(self.agenda_combo, stretch=1)
        self.zoek_btn = knop("Opnieuw zoeken", "big", self._laad_agendas)
        rij.addWidget(self.zoek_btn)
        av.addLayout(rij)
        self.agenda_status = label("Tip: een aparte agenda voor je rooster, bijvoorbeeld "
                                   "“Werkrooster”, houdt je diensten en je eigen afspraken uit "
                                   "elkaar. Die maak je in je agenda-app.", "statusDim", wrap=True)
        av.addWidget(self.agenda_status)
        lay.addWidget(self.agenda_vak)

        self.ics_uitleg = label(
            "De app maakt een bestand met je diensten. Dat open je zelf in je agenda-app. "
            "Let op: de app kan die agenda niet inzien. Bijwerken, verwijderen en ongedaan "
            "maken kunnen daar dus niet; lees je een nieuw rooster in, dan krijg je een nieuw "
            "bestand.", "lead", wrap=True)
        self.ics_uitleg.setMaximumWidth(900)
        lay.addWidget(self.ics_uitleg)
        lay.addStretch()

        huidig = next((b for b in self.backends if b.id == self.s.backend_id), None)
        self._kies_koppeling(huidig or (self.backends[0] if self.backends else None))
        return w

    def _kies_koppeling(self, backend) -> None:
        self.koppeling = backend
        for bid, k in self.kaarten.items():
            k.zet_gekozen(backend is not None and bid == backend.id)
        kan_inzien = bool(backend and backend.can_inspect_calendar)
        self.agenda_vak.setVisible(kan_inzien)
        self.ics_uitleg.setVisible(not kan_inzien)
        if kan_inzien:
            self._laad_agendas()

    def _laad_agendas(self) -> None:
        backend = self.koppeling
        self.agenda_combo.clear()
        self.agenda_combo.addItem("Agenda's zoeken…", None)
        self.agenda_combo.setEnabled(False)
        self.zoek_btn.setEnabled(False)
        self._worker = _Worker(backend.calendars, self)

        def klaar(lijst: list) -> None:
            if backend is not self.koppeling:
                return
            self.agenda_combo.clear()
            for naam, sleutel in lijst:
                self.agenda_combo.addItem(naam, sleutel)
            self.agenda_combo.setEnabled(True)
            self.zoek_btn.setEnabled(True)
            i = next((n for n, (naam, k) in enumerate(lijst)
                      if self.s.calendar_key and k == self.s.calendar_key), -1)
            if i < 0:
                i = self.agenda_combo.findText(self.s.calendar_name)
            if i >= 0:
                self.agenda_combo.setCurrentIndex(i)
            if not lijst:
                self._agenda_fout("Er zijn geen agenda's gevonden. Maak er eerst een aan in "
                                  "je agenda-app en klik dan op “Opnieuw zoeken”.")

        def mislukt(melding: str) -> None:
            if backend is not self.koppeling:
                return
            self.agenda_combo.clear()
            self.zoek_btn.setEnabled(True)
            self._agenda_fout(f"De agenda's konden niet worden opgehaald. {melding}")

        self._worker.done.connect(klaar)
        self._worker.failed.connect(mislukt)
        self._worker.start()

    def _agenda_fout(self, tekst: str) -> None:
        self.agenda_status.setText(tekst)
        herpolish(self.agenda_status, "statusError")

    def _agenda_ok(self) -> bool:
        b = self.koppeling
        if b is None:
            return False
        self.s.backend_id = b.id
        if not b.can_inspect_calendar:
            self.s.calendar_key = ""
            return True
        if self.agenda_combo.currentData() is None or not self.agenda_combo.currentText():
            self._agenda_fout("Kies eerst een agenda.")
            return False
        naam = self.agenda_combo.currentText()
        self.s.calendar_name, self.s.calendar_key = naam, self.agenda_combo.currentData() or ""
        return True

    # ------------------------------------------------------------------
    # Stap 2: diensten
    # ------------------------------------------------------------------
    def _stap_diensten(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self._kop(lay, "Hoe heten de diensten bij jullie?",
                  "De app geeft elke dienst een naam op basis van de begintijd. Pas de namen "
                  "en tijden aan zoals jullie het op het werk zeggen.")
        self.balk = Tijdbalk(self.s)
        lay.addWidget(self.balk)
        lay.addSpacing(6)
        rij = QHBoxLayout()
        rij.setSpacing(36)
        self.editor = DienstsoortenEditor(self.s)
        self.editor.gewijzigd.connect(self._ververs_diensten)
        links = QVBoxLayout()
        links.addWidget(self.editor)
        links.addStretch()
        rij.addLayout(links, stretch=5)
        vak, self._diensten_lay = kaart()
        vak.setMinimumWidth(360)
        rij.addWidget(vak, stretch=3)
        lay.addLayout(rij, stretch=1)
        return w

    def _ververs_diensten(self) -> None:
        self.balk.update()
        lay = self._diensten_lay
        leeg_layout(lay)
        lay.addWidget(label("ZO WORDT JOUW ROOSTER", "sectionTitle"))
        gezien = []
        for x in ingedeeld(self.ruw, self.s):
            if x.all_day or x.shift_type in (ShiftType.VRIJ, ShiftType.AFSPRAAK,
                                             ShiftType.NEGEREN):
                continue
            tijd = f"{x.start:%H:%M}–{x.end:%H:%M}"
            if tijd in [t for t, _ in gezien]:
                continue
            gezien.append((tijd, x))
        for tijd, x in gezien[:7]:
            r = QHBoxLayout()
            t = QLabel(tijd)
            t.setStyleSheet("font-size: 17px;")
            r.addWidget(t)
            r.addStretch()
            n = QLabel(self.s.name_for(x.sleutel) or "Dienst")
            n.setStyleSheet(f"font-size: 17px; font-weight: 700; "
                            f"color: {theme.kleur_voor(self.s, x.sleutel)};")
            r.addWidget(n)
            lay.addLayout(r)
        lay.addSpacing(8)
        lay.addWidget(label(
            ("Dit zijn de tijden uit het rooster dat je net koos." if self.eigen_rooster
             else "Dit is een voorbeeld; met je eigen rooster zie je hier je eigen tijden.")
            + " Verander je hiernaast iets, dan zie je het hier meteen.", "statusDim", wrap=True))
        lay.addStretch()

    # ------------------------------------------------------------------
    # Stap 3: voorkeuren
    # ------------------------------------------------------------------
    def _schakel(self, lay, titel: str, uitleg: str, aan: bool) -> ToggleSwitch:
        vak = QFrame()
        vak.setObjectName("card")
        r = QHBoxLayout(vak)
        r.setContentsMargins(26, 18, 22, 18)
        tekst = QVBoxLayout()
        tekst.setSpacing(4)
        t = QLabel(titel)
        t.setStyleSheet("font-size: 18px; font-weight: 700;")
        tekst.addWidget(t)
        tekst.addWidget(label(uitleg, "statusDim", wrap=True))
        r.addLayout(tekst, stretch=1)
        sw = ToggleSwitch()
        sw.setChecked(aan)
        sw.toggled.connect(self._ververs_voorkeuren)
        r.addWidget(sw)
        lay.addWidget(vak)
        return sw

    def _stap_voorkeuren(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self._kop(lay, "Wat wil je in je agenda zien?", "Rechts zie je meteen hoe het eruit "
                  "komt te zien.")
        rij = QHBoxLayout()
        rij.setSpacing(36)
        links = QVBoxLayout()
        links.setSpacing(14)
        self.vrij_sw = self._schakel(links, "Vrije dagen ook tonen",
                                     "Elke vrije dag krijgt een item “Vrij” bovenaan de dag.",
                                     self.s.include_vrij)
        self.taak_sw = self._schakel(links, "Taak achter de naam zetten",
                                     "Bijvoorbeeld “Ochtend - Teamdag” in plaats van alleen "
                                     "“Ochtend”.", self.s.info_in_title)
        self.concept_sw = self._schakel(
            links, "Conceptdiensten herkenbaar maken",
            "Ze krijgen “(concept)” achter de naam. Het definitieve rooster vervangt ze "
            "vanzelf.", bool(self.s.rules.get("mark_concept", True)))
        vak = QFrame()
        vak.setObjectName("card")
        r = QHBoxLayout(vak)
        r.setContentsMargins(26, 16, 18, 16)
        t = QLabel("Herinnering vóór een dienst")
        t.setStyleSheet("font-size: 18px; font-weight: 700;")
        r.addWidget(t, stretch=1)
        self.herinnering = QComboBox()
        self.herinnering.setMinimumWidth(220)
        self.herinnering.addItem("Geen herinnering", None)
        for tekst, m in REMINDER_PRESETS:
            self.herinnering.addItem(tekst, m)
        i = self.herinnering.findData(self.s.reminder_for(ShiftType.OCHTEND.value))
        self.herinnering.setCurrentIndex(max(0, i))
        self.herinnering.currentIndexChanged.connect(self._ververs_voorkeuren)
        r.addWidget(self.herinnering)
        links.addWidget(vak)
        links.addStretch()
        rij.addLayout(links, stretch=5)
        vb, self._voorbeeld_lay = kaart()
        vb.setMinimumWidth(380)
        rij.addWidget(vb, stretch=3)
        lay.addLayout(rij, stretch=1)
        return w

    def _voorkeuren_toepassen(self) -> None:
        s = self.s
        s.include_vrij = self.vrij_sw.isChecked()
        s.info_in_title = self.taak_sw.isChecked()
        s.rules["mark_concept"] = self.concept_sw.isChecked()
        minuten_ = self.herinnering.currentData()
        for sleutel in [d["id"] for d in s.dienstsoorten] + [ShiftType.DIENST.value]:
            oud = s.reminders.get(sleutel) or {}
            s.reminders[sleutel] = {"enabled": minuten_ is not None,
                                    "minutes": minuten_ if minuten_ is not None
                                    else int(oud.get("minutes", 60))}

    def _ververs_voorkeuren(self) -> None:
        if not hasattr(self, "_voorbeeld_lay"):
            return
        self._voorkeuren_toepassen()
        lay = self._voorbeeld_lay
        leeg_layout(lay)
        lay.addWidget(label("ZO KOMT HET IN JE AGENDA", "sectionTitle"))
        lay.addSpacing(4)
        alles = ingedeeld(self.ruw, self.s)
        diensten = [x for x in alles if not x.all_day and x.shift_type not in
                    (ShiftType.VRIJ, ShiftType.AFSPRAAK, ShiftType.NEGEREN)]
        def_dienst = next((x for x in diensten if x.info and not x.is_concept),
                          next((x for x in diensten if not x.is_concept), None))
        vrij = next((x for x in alles if x.shift_type == ShiftType.VRIJ), None)
        concept = next((x for x in diensten if x.is_concept), None)
        for x in (def_dienst, vrij, concept):
            if x is None:
                continue
            lay.addWidget(label(dag_lang(x.roster_date or x.start.date()), "statusDim"))
            if x.shift_type == ShiftType.VRIJ and not self.s.include_vrij:
                lay.addWidget(label("Vrije dagen komen niet in je agenda.", "statusDim"))
                continue
            lay.addWidget(self._agenda_blok(x))
            lay.addSpacing(6)
        lay.addStretch()

    def _agenda_blok(self, x: Shift) -> QFrame:
        kleur = theme.kleur_voor(self.s, x.sleutel)
        blok = QFrame()
        if x.is_concept:
            blok.setStyleSheet(f"QFrame {{ background: transparent; border: 2px dashed {kleur};"
                               " border-radius: 12px; } QLabel { border: none; }")
            tekst_kleur = kleur
        else:
            blok.setStyleSheet(f"QFrame {{ background: {kleur}; border-radius: 12px; }}"
                               " QLabel { border: none; }")
            tekst_kleur = theme.ACCENT_TEXT
        lay = QVBoxLayout(blok)
        lay.setContentsMargins(22, 12, 22, 12)
        lay.setSpacing(2)
        t = QLabel(x.display_name)
        t.setWordWrap(True)
        t.setStyleSheet(f"color: {tekst_kleur}; font-size: 18px; font-weight: 800;")
        lay.addWidget(t)
        if not x.all_day:
            tijd = QLabel(f"{x.start:%H:%M} – {x.end:%H:%M}")
            tijd.setStyleSheet(f"color: {tekst_kleur}; font-size: 16px;")
            lay.addWidget(tijd)
            if x.reminder_minutes is not None and not x.is_concept:
                om = x.start - timedelta(minutes=x.reminder_minutes)
                h = QLabel(f"Herinnering om {om:%H:%M}")
                h.setStyleSheet(f"color: {tekst_kleur}; font-size: 15px;")
                lay.addWidget(h)
        blok.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        return blok

