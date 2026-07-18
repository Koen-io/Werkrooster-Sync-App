"""Settings dialog with tabs: calendar, naming & reminders, rules, maintenance."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..calendars.base import CalendarError
from ..calendars.registry import all_backends, get_backend
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
}


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


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._worker: _Worker | None = None
        self.setWindowTitle("Instellingen")
        self.setMinimumSize(620, 560)
        self.setStyleSheet(theme.QSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        tabs = QTabWidget()
        tabs.addTab(self._build_calendar_tab(), "Agenda")
        tabs.addTab(self._build_naming_tab(), "Namen && herinneringen")
        tabs.addTab(self._build_rules_tab(), "Herkenning")
        tabs.addTab(self._build_maintenance_tab(), "Onderhoud")
        layout.addWidget(tabs)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Annuleren")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Opslaan")
        save.setObjectName("primary")
        save.setStyleSheet("QPushButton#primary { padding: 10px 24px; font-size: 14px; }")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------
    def _build_calendar_tab(self) -> QWidget:
        w = QWidget()
        form = QVBoxLayout(w)
        form.setContentsMargins(18, 18, 18, 18)
        form.setSpacing(12)

        intro = QLabel(
            "Kies waar je rooster naartoe gesynchroniseerd wordt. Op een Mac is dat "
            "Apple Agenda, op Windows Microsoft Outlook. Werkt je agenda-app niet "
            "rechtstreeks? Kies dan “.ics export”: het rooster wordt dan als bestand "
            "klaargezet en geopend in je standaard agenda-app."
        )
        intro.setWordWrap(True)
        intro.setObjectName("statusDim")
        form.addWidget(intro)

        self.backend_combo = QComboBox()
        self._backends = all_backends()
        for b in self._backends:
            self.backend_combo.addItem(b.label, b.id)
        idx = self.backend_combo.findData(self.settings.backend_id)
        if idx >= 0:
            self.backend_combo.setCurrentIndex(idx)
        self.backend_combo.currentIndexChanged.connect(self._load_calendars)

        self.calendar_combo = QComboBox()
        self.calendar_combo.setEditable(False)
        refresh = QPushButton("Ververs lijst")
        refresh.clicked.connect(self._load_calendars)

        cal_row = QHBoxLayout()
        cal_row.addWidget(self.calendar_combo, stretch=1)
        cal_row.addWidget(refresh)

        f = QFormLayout()
        f.setSpacing(12)
        f.addRow("Agenda-app:", self.backend_combo)
        f.addRow("Agenda:", cal_row)
        form.addLayout(f)

        self.calendar_status = QLabel("")
        self.calendar_status.setObjectName("statusDim")
        self.calendar_status.setWordWrap(True)
        form.addWidget(self.calendar_status)
        form.addStretch()

        if self.settings.calendar_name:
            self.calendar_combo.addItem(self.settings.calendar_name)
        self._load_calendars()
        return w

    def _load_calendars(self):
        backend = get_backend(self.backend_combo.currentData())
        self.calendar_status.setText("Agenda's ophalen…")
        current = self.calendar_combo.currentText() or self.settings.calendar_name

        def fetch():
            return backend.list_calendars()

        self._worker = _Worker(fetch, self)

        def on_done(names):
            self.calendar_combo.clear()
            self.calendar_combo.addItems(names)
            if current in names:
                self.calendar_combo.setCurrentText(current)
            self.calendar_status.setText(f"{len(names)} agenda('s) gevonden.")

        def on_fail(msg):
            self.calendar_status.setText(msg)

        self._worker.done.connect(on_done)
        self._worker.failed.connect(on_fail)
        self._worker.start()

    # ------------------------------------------------------------------
    def _build_naming_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        intro = QLabel(
            "Bepaal hoe elke dienst in je agenda komt te staan en of je er een "
            "herinnering bij wilt."
        )
        intro.setWordWrap(True)
        intro.setObjectName("statusDim")
        outer.addWidget(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        for col, header in enumerate(["Dienst", "Naam in agenda", "Herinnering", ""]):
            lbl = QLabel(header)
            lbl.setObjectName("sectionTitle")
            grid.addWidget(lbl, 0, col)

        self.name_edits: dict[str, QLineEdit] = {}
        self.reminder_checks: dict[str, QCheckBox] = {}
        self.reminder_combos: dict[str, QComboBox] = {}

        for row, shift_type in enumerate(ShiftType.ordered(), start=1):
            key = shift_type.value
            color = theme.SHIFT_COLORS[shift_type]
            type_lbl = QLabel(f"●  {TYPE_LABELS[shift_type]}")
            type_lbl.setStyleSheet(f"color: {color}; font-weight: 600;")

            name_edit = QLineEdit(self.settings.names.get(key, ""))
            name_edit.setPlaceholderText(TYPE_LABELS[shift_type])

            check = QCheckBox()
            cfg = self.settings.reminders.get(key, {})
            check.setChecked(bool(cfg.get("enabled")))

            combo = QComboBox()
            for label, minutes in REMINDER_PRESETS:
                combo.addItem(label, minutes)
            idx = combo.findData(int(cfg.get("minutes", 0)))
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.setEnabled(check.isChecked())
            check.toggled.connect(combo.setEnabled)

            grid.addWidget(type_lbl, row, 0)
            grid.addWidget(name_edit, row, 1)
            grid.addWidget(check, row, 2, alignment=Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(combo, row, 3)

            self.name_edits[key] = name_edit
            self.reminder_checks[key] = check
            self.reminder_combos[key] = combo

        outer.addLayout(grid)

        self.include_vrij_check = QCheckBox("Vrije dagen ook in de agenda zetten")
        self.include_vrij_check.setChecked(self.settings.include_vrij)
        outer.addWidget(self.include_vrij_check)

        self.vrij_allday_check = QCheckBox("Vrije dagen als hele-dag-item aanmaken")
        self.vrij_allday_check.setChecked(self.settings.vrij_as_all_day)
        outer.addWidget(self.vrij_allday_check)

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
            "de dienst. Woorden scheiden met een komma."
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

        outer.addStretch()
        return w

    # ------------------------------------------------------------------
    def _build_maintenance_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

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
        outer.addStretch()
        return w

    def _current_selection(self):
        backend = get_backend(self.backend_combo.currentData())
        snapshot = Settings.from_dict(self.settings.to_dict())
        snapshot.calendar_name = self.calendar_combo.currentText()
        return backend, snapshot

    def _check_duplicates(self):
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
        from datetime import datetime, timedelta

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
    def _save(self):
        s = self.settings
        s.backend_id = self.backend_combo.currentData() or ""
        s.calendar_name = self.calendar_combo.currentText()
        for key, edit in self.name_edits.items():
            if edit.text().strip():
                s.names[key] = edit.text().strip()
        for key in self.reminder_checks:
            s.reminders[key] = {
                "enabled": self.reminder_checks[key].isChecked(),
                "minutes": self.reminder_combos[key].currentData(),
            }
        s.include_vrij = self.include_vrij_check.isChecked()
        s.vrij_as_all_day = self.vrij_allday_check.isChecked()
        s.rules.setdefault("keywords", {})
        for key, edit in self.keyword_edits.items():
            s.rules["keywords"][key] = [
                part.strip() for part in edit.text().split(",") if part.strip()
            ]
        s.rules.setdefault("time_windows", {})
        for key, (s1, s2) in self.window_spins.items():
            s.rules["time_windows"][key] = [s1.value(), s2.value()]
        s.save()
        self.accept()
