"""Instellingen voor wie alles zelf wil regelen, als pagina in het hoofdvenster.

Bovenaan staat "Instelhulp starten". Tabbladen: diensten, namen en
herinneringen, herkenning, onderhoud. Er wordt gewerkt op een kopie van de
instellingen; pas "Opslaan" schrijft ze weg.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..calendars.base import CalendarError
from ..calendars.registry import get_backend
from ..core.models import ShiftType
from ..core.settings import Settings
from . import theme
from .widgets import ToggleSwitch, herpolish, knop, label, leeg_layout

REMINDER_PRESETS: list[tuple[str, int]] = [
    ("Op het tijdstip zelf", 0),
    ("5 minuten ervoor", 5),
    ("15 minuten ervoor", 15),
    ("30 minuten ervoor", 30),
    ("1 uur ervoor", 60),
    ("2 uur ervoor", 120),
    ("4 uur ervoor", 240),
    ("12 uur ervoor", 720),
    ("1 dag ervoor", 1440),
]

TYPE_LABELS = {
    ShiftType.VRIJ: "Vrij",
    ShiftType.OCHTEND: "Ochtenddienst",
    ShiftType.LAAT: "Late dienst",
    ShiftType.NACHT: "Nachtdienst",
    ShiftType.DIENST: "Overige dienst",
    ShiftType.AFSPRAAK: "Afspraak",
    ShiftType.NEGEREN: "Negeren",
}

DISPLAY_OPTIONS: list[tuple[str, str]] = [
    ("Exacte tijden", "timed"),
    ("Hele dag", "all_day"),
]

log = logging.getLogger(__name__)


class _Worker(QThread):
    """Voer een functie uit buiten de schermdraad. Met ``met_voortgang`` krijgt
    de functie een terugroepfunctie (gedaan, totaal, tekst) mee."""

    done = Signal(object)
    failed = Signal(str)
    voortgang = Signal(int, int, str)

    def __init__(self, fn, parent=None, met_voortgang: bool = False):
        super().__init__(parent)
        self._fn = fn
        self._met_voortgang = met_voortgang

    def run(self):
        try:
            if self._met_voortgang:
                self.done.emit(self._fn(self.voortgang.emit))
            else:
                self.done.emit(self._fn())
        except CalendarError as exc:
            log.warning("Agenda-fout: %s", exc)
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("Onverwachte fout in achtergrondtaak")
            self.failed.emit(
                f"Er ging iets onverwachts mis ({type(exc).__name__}: {exc}). "
                "De fout staat in het logboek."
            )


class SettingsPanel(QWidget):
    """Instellingen als volledige pagina in het hoofdvenster."""

    saved = Signal()
    cancelled = Signal()
    instelhulp = Signal()

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = Settings.from_dict(settings.to_dict())
        self._worker: _Worker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(56, 32, 56, 32)
        layout.setSpacing(16)

        kop = QHBoxLayout()
        kop.addWidget(label("Instellingen", "appTitle"))
        kop.addStretch()
        self.wizard_btn = knop("Instelhulp starten", "secondary", self.instelhulp.emit)
        kop.addWidget(self.wizard_btn)
        layout.addLayout(kop)
        uitleg = label("Liever stap voor stap? Start de instelhulp. Hieronder kun je alles "
                       "ook zelf regelen.", "statusDim", wrap=True)
        layout.addWidget(uitleg)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_diensten_tab(), "Diensten")
        self.tabs.addTab(self._scroll(self._build_naming_tab()), "Namen && herinneringen")
        self.tabs.addTab(self._scroll(self._build_rules_tab()), "Herkenning")
        self.tabs.addTab(self._build_maintenance_tab(), "Onderhoud")
        layout.addWidget(self.tabs, stretch=1)

        buttons = QHBoxLayout()
        self.save_error = label("", "statusError", wrap=True)
        buttons.addWidget(self.save_error, stretch=1)
        cancel = knop("Annuleren", "secondary", self.cancelled.emit)
        save = knop("Opslaan", "primary", self._save)
        save.setMinimumWidth(180)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    @staticmethod
    def _scroll(w: QWidget) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setWidget(w)
        return sa

    # ------------------------------------------------------------------
    def _selected_backend(self):
        return get_backend(self.settings.backend_id)

    # ------------------------------------------------------------------
    def _build_diensten_tab(self) -> QWidget:
        from .wizard import DienstsoortenEditor, Tijdbalk

        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(22, 22, 22, 22)
        outer.setSpacing(14)
        outer.addWidget(label(
            "Elke dienst krijgt een naam op basis van de begintijd. De tijdvakken mogen "
            "niet overlappen. Een dienst die in geen enkel vak begint, heet “Dienst”.",
            "statusDim", wrap=True))
        self.tijdbalk = Tijdbalk(self.settings)
        outer.addWidget(self.tijdbalk)
        self.soorten_editor = DienstsoortenEditor(self.settings)
        self.soorten_editor.gewijzigd.connect(self.tijdbalk.update)
        self.soorten_editor.gewijzigd.connect(self._vul_namen)
        sa = self._scroll(self.soorten_editor)
        outer.addWidget(sa, stretch=1)
        return w

    # ------------------------------------------------------------------
    def _naam_sleutels(self) -> list[str]:
        return ([ShiftType.VRIJ.value] + [d["id"] for d in self.settings.dienstsoorten]
                + [ShiftType.DIENST.value, ShiftType.AFSPRAAK.value])

    def _build_naming_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(22, 22, 22, 22)
        outer.setSpacing(14)
        outer.addWidget(label(
            "Bepaal hoe elk soort item in je agenda komt: de naam, als blok op de tijden of "
            "als hele-dag-item bovenaan de dag, en of er een herinnering bij komt. De namen "
            "van de dienstsoorten pas je aan bij Diensten. Afspraken die geen dienst zijn "
            "houden hun eigen titel uit het rooster.", "statusDim", wrap=True))
        self.naam_grid = QGridLayout()
        self.naam_grid.setHorizontalSpacing(14)
        self.naam_grid.setVerticalSpacing(10)
        self.naam_grid.setColumnStretch(5, 1)
        outer.addLayout(self.naam_grid)
        self.name_edits: dict[str, QLineEdit] = {}
        self.display_combos: dict[str, QComboBox] = {}
        self.reminder_checks: dict[str, ToggleSwitch] = {}
        self.reminder_combos: dict[str, QComboBox] = {}
        self._vul_namen()

        self.info_title_check = ToggleSwitch(
            "De taak uit het rooster achter de naam zetten (bijvoorbeeld “Ochtend - Teamdag”)")
        self.info_title_check.setChecked(self.settings.info_in_title)
        outer.addWidget(self.info_title_check)
        self.include_vrij_check = ToggleSwitch("Vrije dagen ook in de agenda zetten")
        self.include_vrij_check.setChecked(self.settings.include_vrij)
        outer.addWidget(self.include_vrij_check)
        self.include_afspraken_check = ToggleSwitch(
            "Afspraken die geen dienst zijn ook in de agenda zetten")
        self.include_afspraken_check.setChecked(self.settings.include_afspraken)
        outer.addWidget(self.include_afspraken_check)
        outer.addStretch()
        return w

    def _namen_naar_instellingen(self) -> None:
        s = self.settings
        for key, edit in self.name_edits.items():
            if edit.isEnabled() and edit.text().strip():
                s.names[key] = edit.text().strip()
        for key, check in self.reminder_checks.items():
            s.reminders[key] = {"enabled": check.isChecked(),
                                "minutes": self.reminder_combos[key].currentData()}
        for key, combo in self.display_combos.items():
            s.display[key] = combo.currentData()

    def _vul_namen(self) -> None:
        """(Her)bouw de rijen; nodig als er een dienstsoort bij komt of af gaat."""
        if self.name_edits or self.reminder_checks:
            self._namen_naar_instellingen()
        leeg_layout(self.naam_grid)
        self.name_edits.clear()
        self.display_combos.clear()
        self.reminder_checks.clear()
        self.reminder_combos.clear()
        for col, kop in enumerate(["Soort", "Naam in agenda", "Weergave", "Herinnering", ""]):
            self.naam_grid.addWidget(label(kop.upper(), "sectionTitle"), 0, col)
        soorten = {d["id"] for d in self.settings.dienstsoorten}
        for row, key in enumerate(self._naam_sleutels(), start=1):
            kleur = theme.kleur_voor(self.settings, key)
            try:
                titel = TYPE_LABELS[ShiftType(key)]
            except ValueError:
                titel = self.settings.names.get(key) or "Dienstsoort"
            if key in soorten:
                titel = self.settings.names.get(key) or titel
            soort = QLabel(f"●  {titel}")
            soort.setStyleSheet(f"color: {kleur}; font-weight: 700;")

            if key in soorten:
                naam = label("zie Diensten", "statusDim")
            else:
                naam = QLineEdit(self.settings.names.get(key, ""))
                naam.setPlaceholderText(titel)
                naam.setFixedWidth(220)
                if key == ShiftType.AFSPRAAK.value:
                    naam.setText("")
                    naam.setPlaceholderText("eigen titel uit rooster")
                    naam.setEnabled(False)
                self.name_edits[key] = naam

            weergave = QComboBox()
            weergave.setFixedWidth(170)
            for tekst, waarde in DISPLAY_OPTIONS:
                weergave.addItem(tekst, waarde)
            weergave.setCurrentIndex(max(0, weergave.findData(self.settings.display_for(key))))

            cfg = self.settings.reminders.get(key) or {}
            check = ToggleSwitch()
            check.setChecked(bool(cfg.get("enabled")))
            combo = QComboBox()
            combo.setFixedWidth(190)
            for tekst, m in REMINDER_PRESETS:
                combo.addItem(tekst, m)
            combo.setCurrentIndex(max(0, combo.findData(int(cfg.get("minutes", 0)))))
            combo.setEnabled(check.isChecked())
            check.toggled.connect(combo.setEnabled)

            self.naam_grid.addWidget(soort, row, 0)
            self.naam_grid.addWidget(naam, row, 1)
            self.naam_grid.addWidget(weergave, row, 2)
            self.naam_grid.addWidget(check, row, 3, alignment=Qt.AlignmentFlag.AlignCenter)
            self.naam_grid.addWidget(combo, row, 4)
            self.display_combos[key] = weergave
            self.reminder_checks[key] = check
            self.reminder_combos[key] = combo

    # ------------------------------------------------------------------
    def _build_rules_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(22, 22, 22, 22)
        outer.setSpacing(14)
        outer.addWidget(label(
            "Zo herkent de app wat een regel in het rooster is. Bevat de soort een van deze "
            "woorden, dan beslist het woord; anders beslist de begintijd (zie Diensten). "
            "Items met een woord bij Negeren komen nooit in je agenda. Woorden scheiden met "
            "een komma.", "statusDim", wrap=True))

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.keyword_edits: dict[str, QLineEdit] = {}
        keywords = self.settings.rules.get("keywords", {})
        for shift_type in ShiftType.ordered():
            key = shift_type.value
            edit = QLineEdit(", ".join(keywords.get(key, [])))
            lbl = QLabel(f"●  {TYPE_LABELS[shift_type]}")
            lbl.setStyleSheet(f"color: {theme.SHIFT_COLORS[shift_type]}; font-weight: 700;")
            lbl.setFixedWidth(200)
            form.addRow(lbl, edit)
            self.keyword_edits[key] = edit
        outer.addLayout(form)

        self.empty_day_check = ToggleSwitch("Lege dagen en dagen met alleen [Rust] als Vrij zien")
        self.empty_day_check.setChecked(bool(self.settings.rules.get("empty_day_is_vrij", True)))
        outer.addWidget(self.empty_day_check)
        nacht_row = QHBoxLayout()
        nacht_row.addWidget(QLabel("De vrije dag na een nachtdienst:"))
        self.na_nacht_combo = QComboBox()
        for tekst, waarde in (("Slaapdag", "slaapdag"), ("Vrij", "vrij"),
                              ("Leeg laten", "leeg")):
            self.na_nacht_combo.addItem(tekst, waarde)
        self.na_nacht_combo.setCurrentIndex(max(0, self.na_nacht_combo.findData(
            self.settings.rules.get("na_nachtdienst", "slaapdag"))))
        nacht_row.addWidget(self.na_nacht_combo)
        nacht_row.addStretch()
        outer.addLayout(nacht_row)
        self.parse_times_check = ToggleSwitch(
            "Tijden uit de soort halen (bijvoorbeeld “DIENST 07:00-16:00” wordt een dienst "
            "van 07:00 tot 16:00)")
        self.parse_times_check.setChecked(
            bool(self.settings.rules.get("parse_times_from_title", True)))
        outer.addWidget(self.parse_times_check)
        self.mark_concept_check = ToggleSwitch(
            "Diensten uit een conceptrooster herkenbaar maken met “(concept)”")
        self.mark_concept_check.setChecked(bool(self.settings.rules.get("mark_concept", True)))
        outer.addWidget(self.mark_concept_check)

        dur_lbl = label("WAT TELT ALS DIENST?", "sectionTitle")
        outer.addWidget(dur_lbl)
        dur_row = QHBoxLayout()
        dur_row.addWidget(QLabel("Een regel zonder herkend woord is een dienst vanaf"))
        self.min_shift_spin = QSpinBox()
        self.min_shift_spin.setRange(1, 24)
        self.min_shift_spin.setSuffix(" uur")
        self.min_shift_spin.setValue(int(self.settings.rules.get("min_shift_hours", 5)))
        dur_row.addWidget(self.min_shift_spin)
        dur_row.addWidget(QLabel("lang; korter is een losse afspraak"))
        dur_row.addStretch()
        outer.addLayout(dur_row)
        outer.addStretch()
        return w

    # ------------------------------------------------------------------
    def _build_maintenance_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(22, 22, 22, 22)
        outer.setSpacing(14)

        outer.addWidget(label("LAATSTE BIJWERKING ONGEDAAN MAKEN", "sectionTitle"))
        outer.addWidget(label(
            "Zet je agenda terug zoals hij was vóór de laatste keer dat je een rooster "
            "inlas. Alleen items van de app worden teruggezet; items die je sindsdien zelf "
            "hebt veranderd en je eigen afspraken blijven staan.", "statusDim", wrap=True))
        rij = QHBoxLayout()
        self.undo_btn = knop("Laatste bijwerking ongedaan maken", "", self._ongedaan)
        rij.addWidget(self.undo_btn)
        rij.addStretch()
        outer.addLayout(rij)
        self.undo_result = label("", "statusDim", wrap=True)
        outer.addWidget(self.undo_result)
        from ..core.bijwerken import kan_ongedaan

        if not self._selected_backend().can_inspect_calendar:
            self.undo_btn.setEnabled(False)
            self.undo_result.setText("Met “Een andere agenda” kan de app je agenda niet "
                                     "inzien; ongedaan maken kan dan niet.")
        elif not kan_ongedaan():
            self.undo_btn.setEnabled(False)
            self.undo_result.setText("Er is nog niets om ongedaan te maken.")

        outer.addSpacing(10)
        outer.addWidget(label("UPDATES", "sectionTitle"))
        upd_row = QHBoxLayout()
        self.update_btn = knop("Zoek naar updates", "", self._check_updates)
        upd_row.addWidget(self.update_btn)
        from ..core.updater import current_version

        self.update_result = label(f"Huidige versie: v{current_version()}", "statusDim",
                                   wrap=True)
        upd_row.addWidget(self.update_result, stretch=1)
        outer.addLayout(upd_row)
        outer.addStretch()
        return w

    def _ongedaan(self) -> None:
        from ..core.bijwerken import Beheer, maak_ongedaan

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Ongedaan maken")
        box.setText("De app zet je agenda terug zoals hij was vóór de laatste bijwerking. "
                    "Items die je sindsdien zelf hebt veranderd blijven staan.\n\nDoorgaan?")
        ja = box.addButton("Ja, maak ongedaan", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Nee", QMessageBox.ButtonRole.RejectRole)
        box.setStyleSheet(theme.QSS)
        box.exec()
        if box.clickedButton() is not ja:
            return
        backend = self._selected_backend()
        self.undo_btn.setEnabled(False)
        self.undo_result.setText("Bezig met terugzetten…")
        herpolish(self.undo_result, "statusDim")
        self._worker = _Worker(lambda: maak_ongedaan(backend, Beheer.laad()), self)

        def klaar(uit) -> None:
            tekst = f"{uit.hersteld} item(s) teruggezet."
            if uit.blijft_staan:
                tekst += f" {len(uit.blijft_staan)} item(s) heb je zelf veranderd; die blijven staan."
            if uit.fouten:
                tekst += " " + " ".join(uit.fouten)
            self.undo_result.setText(tekst)
            herpolish(self.undo_result, "statusError" if uit.fouten else "statusOk")

        def mislukt(melding: str) -> None:
            self.undo_btn.setEnabled(True)
            self.undo_result.setText(melding)
            herpolish(self.undo_result, "statusError")

        self._worker.done.connect(klaar)
        self._worker.failed.connect(mislukt)
        self._worker.start()

    def _check_updates(self):
        from ..core.updater import check_for_update, current_version

        self.update_btn.setEnabled(False)
        self.update_result.setText("Controleren…")
        herpolish(self.update_result, "statusDim")
        self._worker = _Worker(check_for_update, self)

        def on_done(update):
            self.update_btn.setEnabled(True)
            if update is None:
                self.update_result.setText(f"Je hebt de nieuwste versie (v{current_version()}).")
                herpolish(self.update_result, "statusOk")
                from .update_dialog import UpToDateDialog

                UpToDateDialog(current_version(), self).exec()
            else:
                self.update_result.setText(f"Versie v{update.version} is beschikbaar.")
                herpolish(self.update_result, "statusOk")
                from .update_dialog import UpdateDialog

                UpdateDialog(update, current_version(), self).exec()

        def on_fail(msg):
            self.update_btn.setEnabled(True)
            self.update_result.setText(msg)
            herpolish(self.update_result, "statusError")

        self._worker.done.connect(on_done)
        self._worker.failed.connect(on_fail)
        self._worker.start()

    # ------------------------------------------------------------------
    def _save(self):
        if not self.soorten_editor.controleer():
            self.tabs.setCurrentIndex(0)
            self.save_error.setText("Kijk even bij Diensten: daar klopt nog iets niet.")
            return
        s = self.settings
        self._namen_naar_instellingen()
        s.info_in_title = self.info_title_check.isChecked()
        s.include_vrij = self.include_vrij_check.isChecked()
        s.include_afspraken = self.include_afspraken_check.isChecked()
        s.rules["min_shift_hours"] = self.min_shift_spin.value()
        s.rules["parse_times_from_title"] = self.parse_times_check.isChecked()
        s.rules["mark_concept"] = self.mark_concept_check.isChecked()
        s.rules["empty_day_is_vrij"] = self.empty_day_check.isChecked()
        s.rules["na_nachtdienst"] = self.na_nacht_combo.currentData()
        s.rules.setdefault("keywords", {})
        for key, edit in self.keyword_edits.items():
            s.rules["keywords"][key] = [
                part.strip() for part in edit.text().split(",") if part.strip()
            ]
        s.save()
        self.saved.emit()

