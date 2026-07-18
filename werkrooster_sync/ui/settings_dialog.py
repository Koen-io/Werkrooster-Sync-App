"""In-app settings panel with tabs: calendar, naming & reminders, rules,
maintenance. Shown inside the main window (no separate dialog); Opslaan and
Annuleren emit signals that return the user to the main view."""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QDate, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..calendars.base import CalendarError
from ..calendars.registry import get_backend
from ..core.models import ShiftType
from ..core.settings import Settings
from ..core.sync import find_duplicates
from . import theme

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
    ShiftType.NEGEREN: "Negeren (niet synchroniseren)",
}

DISPLAY_OPTIONS: list[tuple[str, str]] = [
    ("Exacte tijden", "timed"),
    ("Hele dag", "all_day"),
]


class _Worker(QThread):
    """Run a callable off the UI thread."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn())
        except CalendarError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(f"Onverwachte fout: {exc}")


class SettingsPanel(QWidget):
    """Full-window settings page embedded in the main window."""

    saved = Signal()
    cancelled = Signal()

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._worker: _Worker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title = QLabel("Instellingen")
        title.setObjectName("appTitle")
        layout.addWidget(title)

        tabs = QTabWidget()
        tabs.addTab(self._build_naming_tab(), "Namen && herinneringen")
        tabs.addTab(self._build_rules_tab(), "Herkenning")
        tabs.addTab(self._build_maintenance_tab(), "Onderhoud")
        layout.addWidget(tabs, stretch=1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Annuleren")
        cancel.clicked.connect(self.cancelled.emit)
        save = QPushButton("Opslaan")
        save.setObjectName("primary")
        save.setStyleSheet("QPushButton#primary { padding: 10px 24px; font-size: 14px; }")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------
    def _selected_backend(self):
        """The backend chosen in Stap 1 of the main window."""
        return get_backend(self.settings.backend_id)

    # ------------------------------------------------------------------
    def _build_naming_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        intro = QLabel(
            "Bepaal hoe elk soort item in je agenda komt te staan: de naam, of er "
            "een herinnering bij komt, en of het als blok op de exacte tijden of "
            "als hele-dag-item bovenaan de dag verschijnt. Afspraken die geen "
            "dienst zijn houden altijd hun eigen titel uit het rooster."
        )
        intro.setWordWrap(True)
        intro.setObjectName("statusDim")
        outer.addWidget(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        # Keep the aligned, compact layout of the original design even in a
        # wide window: fixed-ish field widths plus a stretch column at the end.
        grid.setColumnStretch(5, 1)
        for col, header in enumerate(
            ["Soort", "Naam in agenda", "Weergave", "Herinnering", ""]
        ):
            lbl = QLabel(header)
            lbl.setObjectName("sectionTitle")
            grid.addWidget(lbl, 0, col)

        self.name_edits: dict[str, QLineEdit] = {}
        self.display_combos: dict[str, QComboBox] = {}
        self.reminder_checks: dict[str, QCheckBox] = {}
        self.reminder_combos: dict[str, QComboBox] = {}

        naming_types = [t for t in ShiftType.ordered() if t != ShiftType.NEGEREN]
        for row, shift_type in enumerate(naming_types, start=1):
            key = shift_type.value
            color = theme.SHIFT_COLORS[shift_type]
            type_lbl = QLabel(f"●  {TYPE_LABELS[shift_type]}")
            type_lbl.setStyleSheet(f"color: {color}; font-weight: 600;")

            name_edit = QLineEdit(self.settings.names.get(key, ""))
            name_edit.setPlaceholderText(TYPE_LABELS[shift_type])
            name_edit.setFixedWidth(220)
            if shift_type == ShiftType.AFSPRAAK:
                name_edit.setText("")
                name_edit.setPlaceholderText("eigen titel uit rooster")
                name_edit.setEnabled(False)
                name_edit.setToolTip(
                    "Afspraken houden hun originele titel uit het rooster."
                )

            display_combo = QComboBox()
            display_combo.setFixedWidth(190)
            for label, value in DISPLAY_OPTIONS:
                display_combo.addItem(label, value)
            didx = display_combo.findData(
                self.settings.display.get(key, "timed")
            )
            display_combo.setCurrentIndex(didx if didx >= 0 else 0)

            check = QCheckBox()
            cfg = self.settings.reminders.get(key, {})
            check.setChecked(bool(cfg.get("enabled")))

            combo = QComboBox()
            combo.setFixedWidth(190)
            for label, minutes in REMINDER_PRESETS:
                combo.addItem(label, minutes)
            idx = combo.findData(int(cfg.get("minutes", 0)))
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.setEnabled(check.isChecked())
            check.toggled.connect(combo.setEnabled)

            grid.addWidget(type_lbl, row, 0)
            grid.addWidget(name_edit, row, 1)
            grid.addWidget(display_combo, row, 2)
            grid.addWidget(check, row, 3, alignment=Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(combo, row, 4)

            self.name_edits[key] = name_edit
            self.display_combos[key] = display_combo
            self.reminder_checks[key] = check
            self.reminder_combos[key] = combo

        outer.addLayout(grid)

        self.include_vrij_check = QCheckBox("Vrije dagen ook in de agenda zetten")
        self.include_vrij_check.setChecked(self.settings.include_vrij)
        outer.addWidget(self.include_vrij_check)

        self.include_afspraken_check = QCheckBox(
            "Afspraken die geen dienst zijn ook synchroniseren"
        )
        self.include_afspraken_check.setChecked(self.settings.include_afspraken)
        outer.addWidget(self.include_afspraken_check)

        outer.addStretch()
        return w

    # ------------------------------------------------------------------
    def _build_rules_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        intro = QLabel(
            "Zo herkent de app het soort dienst. Eerst wordt gekeken of de titel in "
            "het rooster een van deze woorden bevat; anders beslist de begintijd van "
            "de dienst. Items met een 'Negeren'-woord (zoals [Rust]-blokken) komen "
            "nooit in je agenda. Woorden scheiden met een komma."
        )
        intro.setWordWrap(True)
        intro.setObjectName("statusDim")
        outer.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(10)
        self.keyword_edits: dict[str, QLineEdit] = {}
        keywords = self.settings.rules.get("keywords", {})
        for shift_type in ShiftType.ordered():
            key = shift_type.value
            edit = QLineEdit(", ".join(keywords.get(key, [])))
            color = theme.SHIFT_COLORS[shift_type]
            lbl = QLabel(f"●  {TYPE_LABELS[shift_type]}")
            lbl.setStyleSheet(f"color: {color}; font-weight: 600;")
            form.addRow(lbl, edit)
            self.keyword_edits[key] = edit
        outer.addLayout(form)

        self.empty_day_check = QCheckBox(
            "Lege dagen (of hele dag [Rust]) in een PDF-rooster als Vrij aanmerken"
        )
        self.empty_day_check.setChecked(
            bool(self.settings.rules.get("empty_day_is_vrij", True))
        )
        outer.addWidget(self.empty_day_check)

        self.parse_times_check = QCheckBox(
            "Tijden uit de titel halen (bijv. “DIENST 07:00 - 16:00” op een "
            "hele-dag-item wordt een dienst van 07:00 tot 16:00)"
        )
        self.parse_times_check.setChecked(
            bool(self.settings.rules.get("parse_times_from_title", True))
        )
        outer.addWidget(self.parse_times_check)

        self.mark_concept_check = QCheckBox(
            "Conceptdiensten ([C1]/[C2] in het rooster) markeren met “(concept)”"
        )
        self.mark_concept_check.setChecked(
            bool(self.settings.rules.get("mark_concept", True))
        )
        outer.addWidget(self.mark_concept_check)

        self.replace_concept_check = QCheckBox(
            "Conceptdiensten automatisch vervangen zodra het definitieve (of een "
            "nieuwer concept-) rooster wordt geïmporteerd"
        )
        self.replace_concept_check.setChecked(self.settings.replace_concept)
        outer.addWidget(self.replace_concept_check)

        time_lbl = QLabel("Begintijd-regels (als geen woord past)")
        time_lbl.setObjectName("sectionTitle")
        outer.addWidget(time_lbl)

        self.window_spins: dict[str, tuple[QSpinBox, QSpinBox]] = {}
        windows = self.settings.rules.get("time_windows", {})
        tf = QFormLayout()
        tf.setSpacing(10)
        for shift_type in (ShiftType.OCHTEND, ShiftType.LAAT, ShiftType.NACHT):
            key = shift_type.value
            lo, hi = windows.get(key, [0, 0])
            s1, s2 = QSpinBox(), QSpinBox()
            for s in (s1, s2):
                s.setRange(0, 23)
                s.setSuffix(":00")
            s1.setValue(int(lo))
            s2.setValue(int(hi))
            row = QHBoxLayout()
            row.addWidget(QLabel("start tussen"))
            row.addWidget(s1)
            row.addWidget(QLabel("en"))
            row.addWidget(s2)
            row.addStretch()
            color = theme.SHIFT_COLORS[shift_type]
            lbl = QLabel(f"●  {TYPE_LABELS[shift_type]}")
            lbl.setStyleSheet(f"color: {color}; font-weight: 600;")
            tf.addRow(lbl, row)
            self.window_spins[key] = (s1, s2)
        outer.addLayout(tf)

        dur_lbl = QLabel("Wat telt als dienst?")
        dur_lbl.setObjectName("sectionTitle")
        outer.addWidget(dur_lbl)

        dur_row = QHBoxLayout()
        dur_row.addWidget(QLabel("Een item zonder herkend woord is een dienst vanaf"))
        self.min_shift_spin = QSpinBox()
        self.min_shift_spin.setRange(1, 24)
        self.min_shift_spin.setSuffix(" uur")
        self.min_shift_spin.setValue(int(self.settings.rules.get("min_shift_hours", 5)))
        dur_row.addWidget(self.min_shift_spin)
        dur_row.addWidget(QLabel("duur; korter = losse afspraak"))
        dur_row.addStretch()
        outer.addLayout(dur_row)

        outer.addStretch()
        return w

    # ------------------------------------------------------------------
    def _build_maintenance_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        dup_title = QLabel("Dubbele items")
        dup_title.setObjectName("sectionTitle")
        outer.addWidget(dup_title)

        intro = QLabel(
            "Controleer of er dubbele roosteritems in je agenda staan (zelfde naam "
            "én zelfde begintijd), bijvoorbeeld doordat een rooster twee keer is "
            "geïmporteerd. Je kunt ze daarna in één keer opruimen."
        )
        intro.setWordWrap(True)
        intro.setObjectName("statusDim")
        outer.addWidget(intro)

        row = QHBoxLayout()
        self.check_btn = QPushButton("Controleer op dubbele items")
        self.check_btn.clicked.connect(self._check_duplicates)
        self.clean_btn = QPushButton("Verwijder dubbele items")
        self.clean_btn.setObjectName("danger")
        self.clean_btn.setEnabled(False)
        self.clean_btn.clicked.connect(self._remove_duplicates)
        row.addWidget(self.check_btn)
        row.addWidget(self.clean_btn)
        row.addStretch()
        outer.addLayout(row)

        self.dup_result = QLabel("")
        self.dup_result.setWordWrap(True)
        outer.addWidget(self.dup_result)

        # ------------------------------------------------------ old roster
        old_title = QLabel("Oud rooster verwijderen")
        old_title.setObjectName("sectionTitle")
        outer.addSpacing(6)
        outer.addWidget(old_title)

        old_box = QFrame()
        old_box.setObjectName("dangerBox")
        old_layout = QVBoxLayout(old_box)
        old_layout.setContentsMargins(14, 12, 14, 12)
        old_layout.setSpacing(10)

        old_intro = QLabel(
            "Verwijdert in één keer alle roosteritems die door Werkrooster Sync "
            "zijn aangemaakt in de gekozen periode — handig wanneer het rooster "
            "is gewijzigd en je opnieuw wilt importeren. Items die je zelf hebt "
            "aangemaakt worden nooit aangeraakt: alleen items met de "
            "verborgen Werkrooster Sync-code worden verwijderd."
        )
        old_intro.setWordWrap(True)
        old_intro.setObjectName("statusDim")
        old_layout.addWidget(old_intro)

        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("Periode:"))
        today = QDate.currentDate()
        self.old_from = QDateEdit(today)
        self.old_to = QDateEdit(today.addDays(180))
        for de in (self.old_from, self.old_to):
            de.setCalendarPopup(True)
            de.setDisplayFormat("dd-MM-yyyy")
        range_row.addWidget(self.old_from)
        range_row.addWidget(QLabel("t/m"))
        range_row.addWidget(self.old_to)
        range_row.addStretch()

        self.remove_old_btn = QPushButton("Verwijder oud rooster…")
        self.remove_old_btn.setObjectName("danger")
        self.remove_old_btn.clicked.connect(self._remove_old_roster)
        range_row.addWidget(self.remove_old_btn)
        old_layout.addLayout(range_row)

        self.old_result = QLabel("")
        self.old_result.setWordWrap(True)
        old_layout.addWidget(self.old_result)

        outer.addWidget(old_box)
        outer.addStretch()
        return w

    def _guard_can_inspect(self, result_label: QLabel) -> bool:
        """Show the export-mode warning if the backend can't see the calendar."""
        if self._selected_backend().can_inspect_calendar:
            return True
        result_label.setObjectName("statusWarn")
        result_label.setText(
            "⚠  In .ics export-modus kan de app je agenda niet inzien. "
            "Controleren en opruimen moet dan gebeuren in de agenda-app "
            "waarin je het bestand importeert."
        )
        result_label.style().polish(result_label)
        return False

    def _current_selection(self):
        backend = self._selected_backend()
        snapshot = Settings.from_dict(self.settings.to_dict())
        return backend, snapshot

    def _check_duplicates(self):
        if not self._guard_can_inspect(self.dup_result):
            return
        backend, snapshot = self._current_selection()
        self.check_btn.setEnabled(False)
        self.dup_result.setObjectName("statusDim")
        self.dup_result.setText("Bezig met controleren…")

        self._worker = _Worker(lambda: find_duplicates(backend, snapshot), self)

        def on_done(dups: dict):
            self.check_btn.setEnabled(True)
            if not dups:
                self.dup_result.setObjectName("statusOk")
                self.dup_result.setText("Geen dubbele items gevonden. ✓")
                self.clean_btn.setEnabled(False)
            else:
                extra = sum(c - 1 for c in dups.values())
                self.dup_result.setObjectName("statusError")
                self.dup_result.setText(
                    f"{extra} dubbele item(s) gevonden bij {len(dups)} "
                    f"agendapunt(en). Klik op “Verwijder dubbele items” om op te ruimen."
                )
                self.clean_btn.setEnabled(True)
            self.dup_result.style().polish(self.dup_result)

        def on_fail(msg):
            self.check_btn.setEnabled(True)
            self.dup_result.setObjectName("statusError")
            self.dup_result.setText(msg)
            self.dup_result.style().polish(self.dup_result)

        self._worker.done.connect(on_done)
        self._worker.failed.connect(on_fail)
        self._worker.start()

    def _remove_duplicates(self):
        if not self._guard_can_inspect(self.dup_result):
            return
        backend, snapshot = self._current_selection()
        start = datetime.now() - timedelta(days=90)
        end = datetime.now() + timedelta(days=180)
        self.clean_btn.setEnabled(False)
        self.dup_result.setText("Dubbele items verwijderen…")

        self._worker = _Worker(
            lambda: backend.remove_duplicates(snapshot.calendar_name, start, end), self
        )

        def on_done(count):
            self.dup_result.setObjectName("statusOk")
            self.dup_result.setText(f"{count} dubbele item(s) verwijderd. ✓")
            self.dup_result.style().polish(self.dup_result)

        def on_fail(msg):
            self.clean_btn.setEnabled(True)
            self.dup_result.setObjectName("statusError")
            self.dup_result.setText(msg)
            self.dup_result.style().polish(self.dup_result)

        self._worker.done.connect(on_done)
        self._worker.failed.connect(on_fail)
        self._worker.start()

    # ------------------------------------------------------------------
    def _remove_old_roster(self):
        """Two-step flow: count the app's items in the range, ask for explicit
        confirmation showing that exact count, then delete."""
        if not self._guard_can_inspect(self.old_result):
            return
        backend, snapshot = self._current_selection()
        if not snapshot.calendar_name:
            self.old_result.setObjectName("statusError")
            self.old_result.setText("Kies eerst een agenda hierboven.")
            self.old_result.style().polish(self.old_result)
            return

        d1 = self.old_from.date()
        d2 = self.old_to.date()
        start = datetime(d1.year(), d1.month(), d1.day(), 0, 0)
        end = datetime(d2.year(), d2.month(), d2.day(), 23, 59)
        if end < start:
            self.old_result.setObjectName("statusError")
            self.old_result.setText("De einddatum ligt vóór de begindatum.")
            self.old_result.style().polish(self.old_result)
            return

        self.remove_old_btn.setEnabled(False)
        self.old_result.setObjectName("statusDim")
        self.old_result.setText("Roosteritems tellen…")
        self.old_result.style().polish(self.old_result)

        self._worker = _Worker(
            lambda: backend.count_synced(snapshot.calendar_name, start, end), self
        )

        def on_counted(count: int) -> None:
            self.remove_old_btn.setEnabled(True)
            if not count:
                self.old_result.setObjectName("statusOk")
                self.old_result.setText(
                    "Geen door Werkrooster Sync aangemaakte items gevonden in "
                    "deze periode."
                )
                self.old_result.style().polish(self.old_result)
                return
            self._confirm_and_remove(backend, snapshot, start, end, count)

        def on_fail(msg: str) -> None:
            self.remove_old_btn.setEnabled(True)
            self.old_result.setObjectName("statusError")
            self.old_result.setText(msg)
            self.old_result.style().polish(self.old_result)

        self._worker.done.connect(on_counted)
        self._worker.failed.connect(on_fail)
        self._worker.start()

    def _confirm_and_remove(self, backend, snapshot, start, end, count: int):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Oud rooster verwijderen")
        box.setText(
            f"Weet je zeker dat je het oude rooster wilt verwijderen?\n\n"
            f"Er worden {count} roosteritem(s) verwijderd uit agenda "
            f"“{snapshot.calendar_name}”\n"
            f"in de periode {start:%d-%m-%Y} t/m {end:%d-%m-%Y}.\n\n"
            f"Alleen items die door Werkrooster Sync zijn aangemaakt worden "
            f"verwijderd; je eigen afspraken blijven staan. "
            f"Dit kan niet ongedaan worden gemaakt."
        )
        delete_btn = box.addButton(
            f"Ja, verwijder {count} item(s)", QMessageBox.ButtonRole.DestructiveRole
        )
        delete_btn.setObjectName("danger")
        cancel_btn = box.addButton("Annuleren", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.setStyleSheet(theme.QSS)
        box.exec()
        if box.clickedButton() is not delete_btn:
            self.old_result.setObjectName("statusDim")
            self.old_result.setText("Geannuleerd — er is niets verwijderd.")
            self.old_result.style().polish(self.old_result)
            return

        self.remove_old_btn.setEnabled(False)
        self.old_result.setObjectName("statusDim")
        self.old_result.setText("Oud rooster verwijderen…")
        self.old_result.style().polish(self.old_result)

        self._worker = _Worker(
            lambda: backend.remove_synced(snapshot.calendar_name, start, end), self
        )

        def on_done(removed: int) -> None:
            self.remove_old_btn.setEnabled(True)
            self.old_result.setObjectName("statusOk")
            self.old_result.setText(f"{removed} roosteritem(s) verwijderd. ✓")
            self.old_result.style().polish(self.old_result)

        def on_fail(msg: str) -> None:
            self.remove_old_btn.setEnabled(True)
            self.old_result.setObjectName("statusError")
            self.old_result.setText(msg)
            self.old_result.style().polish(self.old_result)

        self._worker.done.connect(on_done)
        self._worker.failed.connect(on_fail)
        self._worker.start()

    # ------------------------------------------------------------------
    def _save(self):
        s = self.settings
        for key, edit in self.name_edits.items():
            if edit.isEnabled() and edit.text().strip():
                s.names[key] = edit.text().strip()
        for key in self.reminder_checks:
            s.reminders[key] = {
                "enabled": self.reminder_checks[key].isChecked(),
                "minutes": self.reminder_combos[key].currentData(),
            }
        for key, combo in self.display_combos.items():
            s.display[key] = combo.currentData()
        s.include_vrij = self.include_vrij_check.isChecked()
        s.include_afspraken = self.include_afspraken_check.isChecked()
        s.rules["min_shift_hours"] = self.min_shift_spin.value()
        s.rules["parse_times_from_title"] = self.parse_times_check.isChecked()
        s.rules["mark_concept"] = self.mark_concept_check.isChecked()
        s.rules["empty_day_is_vrij"] = self.empty_day_check.isChecked()
        s.replace_concept = self.replace_concept_check.isChecked()
        s.rules.setdefault("keywords", {})
        for key, edit in self.keyword_edits.items():
            s.rules["keywords"][key] = [
                part.strip() for part in edit.text().split(",") if part.strip()
            ]
        s.rules.setdefault("time_windows", {})
        for key, (s1, s2) in self.window_spins.items():
            s.rules["time_windows"][key] = [s1.value(), s2.value()]
        s.save()
        self.saved.emit()
