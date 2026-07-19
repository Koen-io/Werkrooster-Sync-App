"""Main application window."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..calendars.base import CalendarError
from ..calendars.registry import all_backends, get_backend
from ..core.classifier import apply_classification
from ..core.ics_parser import IcsParseError, parse_ics
from ..core.models import Shift, ShiftType, SyncReport
from ..core.settings import Settings
from ..core.sync import mark_already_imported, sync_shifts
from . import theme
from .settings_dialog import SettingsPanel, _Worker
from .widgets import CountChip, DropZone, StepHeader

WEEKDAYS = ["ma", "di", "wo", "do", "vr", "za", "zo"]


class _SyncWorker(QThread):
    progress = Signal(int, int, str)
    finished_report = Signal(object)
    failed = Signal(str)

    def __init__(self, shifts: list[Shift], settings: Settings, parent=None):
        super().__init__(parent)
        self._shifts = shifts
        self._settings = settings

    def run(self):
        try:
            backend = get_backend(self._settings.backend_id)
            report = sync_shifts(
                self._shifts,
                backend,
                self._settings,
                progress=lambda i, n, msg: self.progress.emit(i, n, msg),
            )
            self.finished_report.emit(report)
        except CalendarError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(f"Onverwachte fout: {exc}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.shifts: list[Shift] = []
        self._worker: _SyncWorker | None = None

        self.setWindowTitle("Werkrooster Sync")
        self.setMinimumSize(680, 720)
        self.setStyleSheet(theme.QSS)

        # Stacked pages: 0 = main view, 1 = the in-app settings panel.
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)
        main_page = QWidget()
        self._stack.addWidget(main_page)
        root = QVBoxLayout(main_page)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        # Header ------------------------------------------------------
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Werkrooster Sync")
        title.setObjectName("appTitle")
        subtitle = QLabel("Zet je rooster in drie stappen in je agenda")
        subtitle.setObjectName("appSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        settings_btn = QPushButton("⚙  Instellingen")
        settings_btn.setObjectName("secondary")
        settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        settings_btn.clicked.connect(self.open_settings)
        header.addWidget(settings_btn, alignment=Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        # Stap 1: agenda kiezen --------------------------------------
        root.addWidget(StepHeader(1, "Kies je agenda"))
        step1 = QFrame()
        step1.setObjectName("card")
        s1 = QFormLayout(step1)
        s1.setContentsMargins(18, 14, 18, 14)
        s1.setSpacing(10)
        s1.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.backend_combo = QComboBox()
        self._backends = all_backends()
        for b in self._backends:
            self.backend_combo.addItem(b.label, b.id)
        idx = self.backend_combo.findData(
            self.settings.backend_id or self._backends[0].id
        )
        if idx >= 0:
            self.backend_combo.setCurrentIndex(idx)

        self.calendar_combo = QComboBox()
        if self.settings.calendar_name:
            self.calendar_combo.addItem(self.settings.calendar_name)
        refresh_btn = QPushButton("Ververs")
        refresh_btn.clicked.connect(self._load_calendars)
        for combo in (self.backend_combo, self.calendar_combo):
            combo.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
        cal_row = QHBoxLayout()
        cal_row.addWidget(self.calendar_combo, stretch=1)
        cal_row.addWidget(refresh_btn)

        s1.addRow("Agenda-app:", self.backend_combo)
        s1.addRow("Agenda:", cal_row)
        self.agenda_status = QLabel("")
        self.agenda_status.setObjectName("statusDim")
        self.agenda_status.setWordWrap(True)
        s1.addRow("", self.agenda_status)
        root.addWidget(step1)

        self._loading_calendars = False
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        self.calendar_combo.currentIndexChanged.connect(self._on_calendar_changed)

        # Stap 2: rooster kiezen -------------------------------------
        root.addWidget(StepHeader(2, "Sleep je rooster hierheen"))
        self.drop_zone = DropZone()
        self.drop_zone.file_selected.connect(self.load_file)
        root.addWidget(self.drop_zone)

        # Summary chips ----------------------------------------------
        self.chips_row = QHBoxLayout()
        self.chips_row.setSpacing(6)
        chips_holder = QWidget()
        chips_holder.setLayout(self.chips_row)
        root.addWidget(chips_holder)

        # Preview list ------------------------------------------------
        self.preview = QListWidget()
        self.preview.setVisible(False)
        self.preview.setMinimumHeight(160)
        root.addWidget(self.preview, stretch=1)

        # Stap 3: synchroniseren -------------------------------------
        root.addWidget(StepHeader(3, "Synchroniseer"))
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        root.addWidget(self.progress_bar)

        self.status = QLabel("Nog geen rooster geladen.")
        self.status.setObjectName("statusDim")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)
        self.sync_btn = QPushButton("Synchroniseer naar agenda")
        self.sync_btn.setObjectName("primary")
        self.sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync_btn.setEnabled(False)
        self.sync_btn.clicked.connect(self.start_sync)
        bottom_row.addWidget(self.sync_btn, stretch=1)

        self.reset_btn = QPushButton("↺  Opnieuw")
        self.reset_btn.setObjectName("secondary")
        self.reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_btn.setToolTip(
            "Wis het geladen rooster en begin opnieuw (instellingen blijven staan)."
        )
        self.reset_btn.setEnabled(False)
        self.reset_btn.clicked.connect(self.reset_file)
        bottom_row.addWidget(self.reset_btn)
        root.addLayout(bottom_row)

        self._load_calendars()

    # ------------------------------------------------------------------
    # Stap 1: agenda selection (auto-saved on every change)
    # ------------------------------------------------------------------
    def _on_backend_changed(self) -> None:
        self.settings.backend_id = self.backend_combo.currentData() or ""
        self.settings.save()
        self._load_calendars()

    def _on_calendar_changed(self) -> None:
        if self._loading_calendars:
            return
        self.settings.calendar_name = self.calendar_combo.currentText()
        self.settings.save()
        if self.shifts:
            self._auto_check_duplicates()

    def _load_calendars(self) -> None:
        backend = get_backend(self.backend_combo.currentData())
        if not backend.can_inspect_calendar:
            self.agenda_status.setObjectName("statusWarn")
            self.agenda_status.setText(
                "⚠  In .ics export-modus kan de app je agenda niet inzien; je "
                "agenda-app controleert zelf op dubbele items bij het importeren."
            )
            self.agenda_status.style().polish(self.agenda_status)

        current = self.calendar_combo.currentText() or self.settings.calendar_name
        self._cal_worker = _Worker(backend.list_calendars, self)

        def on_done(names: list) -> None:
            self._loading_calendars = True
            self.calendar_combo.clear()
            self.calendar_combo.addItems(names)
            self._loading_calendars = False
            if current in names:
                self.calendar_combo.setCurrentText(current)
            else:
                self._on_calendar_changed()
            if backend.can_inspect_calendar:
                self.agenda_status.setObjectName("statusDim")
                self.agenda_status.setText(f"{len(names)} agenda('s) gevonden.")
                self.agenda_status.style().polish(self.agenda_status)

        def on_fail(msg: str) -> None:
            if backend.can_inspect_calendar:
                self.agenda_status.setObjectName("statusError")
                self.agenda_status.setText(msg)
                self.agenda_status.style().polish(self.agenda_status)

        self._cal_worker.done.connect(on_done)
        self._cal_worker.failed.connect(on_fail)
        self._cal_worker.start()

    # ------------------------------------------------------------------
    def _set_status(self, text: str, kind: str = "statusDim") -> None:
        self.status.setObjectName(kind)
        self.status.setText(text)
        self.status.style().polish(self.status)

    # ------------------------------------------------------------------
    def load_file(self, path: str) -> None:
        try:
            if path.lower().endswith(".pdf"):
                from ..core.pdf_parser import parse_pdf

                shifts = parse_pdf(path, self.settings)
            else:
                shifts = parse_ics(path)
        except IcsParseError as exc:
            self._set_status(str(exc), "statusError")
            return
        self.shifts = apply_classification(shifts, self.settings)
        self._refresh_preview()
        self.sync_btn.setEnabled(True)
        self.reset_btn.setEnabled(True)
        first = min(s.start for s in self.shifts)
        last = max(s.start for s in self.shifts)
        ignored = sum(1 for s in self.shifts if s.shift_type == ShiftType.NEGEREN)
        note = f", waarvan {ignored} roosterruis (grijs, wordt overgeslagen)" if ignored else ""
        self._set_status(
            f"{len(self.shifts)} items geladen "
            f"({first:%d-%m-%Y} t/m {last:%d-%m-%Y}){note}. "
            f"Klaar om te synchroniseren.",
            "statusOk",
        )
        self._auto_check_duplicates()

    # ------------------------------------------------------------------
    def reset_file(self) -> None:
        """Clear the loaded roster so the user can start over. Settings and
        the chosen agenda are left untouched."""
        self.shifts = []
        self.preview.clear()
        self.preview.setVisible(False)
        while self.chips_row.count():
            item = self.chips_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.progress_bar.setVisible(False)
        self.sync_btn.setEnabled(False)
        self.reset_btn.setEnabled(False)
        self._set_status("Nog geen rooster geladen.", "statusDim")

    # ------------------------------------------------------------------
    def _auto_check_duplicates(self) -> None:
        """Automatically compare the loaded roster with the chosen calendar
        and mark items that are already in it."""
        backend = get_backend(self.settings.backend_id)
        if not self.shifts:
            return
        if not backend.can_inspect_calendar:
            self._set_status(
                f"{len(self.shifts)} items geladen. ⚠ Let op: in .ics export-modus "
                f"kan de app niet controleren op dubbele items — dat gebeurt in de "
                f"agenda-app waarin je het bestand importeert.",
                "statusWarn",
            )
            return
        if not self.settings.calendar_name:
            return
        shifts, settings = self.shifts, self.settings

        self._check_worker = _Worker(
            lambda: mark_already_imported(shifts, backend, settings), self
        )

        def on_done(count: int) -> None:
            if shifts is not self.shifts:
                return  # a different file was loaded meanwhile
            self._refresh_preview()
            if count:
                self._set_status(
                    f"{len(self.shifts)} items geladen, waarvan {count} al in je "
                    f"agenda staan (rood). Die worden bij synchroniseren "
                    f"automatisch overgeslagen.",
                    "statusOk",
                )

        def on_fail(msg: str) -> None:
            self._set_status(
                f"Rooster geladen. Automatische controle op dubbele items lukte "
                f"niet: {msg}",
                "statusError",
            )

        self._check_worker.done.connect(on_done)
        self._check_worker.failed.connect(on_fail)
        self._check_worker.start()

    def _refresh_preview(self) -> None:
        # Chips
        while self.chips_row.count():
            item = self.chips_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        counts: dict[ShiftType, int] = {}
        for s in self.shifts:
            counts[s.shift_type] = counts.get(s.shift_type, 0) + 1
        for t in ShiftType.ordered():
            if counts.get(t):
                self.chips_row.addWidget(
                    CountChip(t, self.settings.name_for(t), counts[t])
                )
        self.chips_row.addStretch()

        # List
        self.preview.clear()
        for s in self.shifts:
            day = WEEKDAYS[s.start.weekday()]
            when = (
                f"{day} {s.start:%d-%m-%Y}   hele dag"
                if s.all_day
                else f"{day} {s.start:%d-%m-%Y}   {s.start:%H:%M}–{s.end:%H:%M}"
            )
            if s.shift_type == ShiftType.NEGEREN:
                item = QListWidgetItem(
                    f"{when}    {s.display_name}    —  wordt niet gesynchroniseerd"
                )
                item.setForeground(QColor(theme.SHIFT_COLORS[ShiftType.NEGEREN]))
                item.setToolTip(
                    "Dit item is herkend als roosterruis (zie Instellingen → "
                    "Herkenning → Negeren) en komt niet in je agenda."
                )
            elif s.already_imported:
                item = QListWidgetItem(
                    f"{when}    {s.display_name}    —  staat al in je agenda"
                )
                item.setForeground(QColor(theme.DANGER))
                item.setToolTip(
                    "Dit item is al eerder geïmporteerd en wordt bij "
                    "synchroniseren overgeslagen.\n"
                    f"Origineel: {s.original_summary or '(leeg)'}"
                )
            else:
                item = QListWidgetItem(f"{when}    {s.display_name}")
                item.setForeground(QColor(theme.SHIFT_COLORS[s.shift_type]))
                item.setToolTip(f"Origineel: {s.original_summary or '(leeg)'}")
            self.preview.addItem(item)
        self.preview.setVisible(True)

    # ------------------------------------------------------------------
    def open_settings(self) -> None:
        """Show the settings as a full-window page inside the app."""
        panel = SettingsPanel(self.settings)
        self._stack.addWidget(panel)
        self._stack.setCurrentWidget(panel)

        def close_panel() -> None:
            self._stack.setCurrentIndex(0)
            self._stack.removeWidget(panel)
            panel.deleteLater()

        def on_saved() -> None:
            self.settings = Settings.load()
            if self.shifts:
                self.shifts = apply_classification(self.shifts, self.settings)
                self._refresh_preview()
                self._auto_check_duplicates()
            self._set_status("Instellingen opgeslagen.", "statusOk")
            close_panel()

        panel.saved.connect(on_saved)
        panel.cancelled.connect(close_panel)

    # ------------------------------------------------------------------
    def start_sync(self) -> None:
        if not self.shifts:
            return
        backend = get_backend(self.settings.backend_id)
        if backend.id != "ics_export" and not self.settings.calendar_name:
            self._set_status(
                "Kies eerst een agenda via ⚙ Instellingen → Agenda.", "statusError"
            )
            return
        self.sync_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(self.shifts))
        self.progress_bar.setValue(0)
        self._set_status("Bezig met synchroniseren…")

        self._worker = _SyncWorker(self.shifts, self.settings, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_report.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, done: int, total: int, message: str) -> None:
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        self._set_status(f"Toevoegen {done}/{total}: {message}")

    def _on_done(self, report: SyncReport) -> None:
        self.progress_bar.setVisible(False)
        self.sync_btn.setEnabled(True)
        parts = [f"{len(report.added)} toegevoegd"]
        if report.concept_removed:
            parts.append(
                f"{report.concept_removed} verouderde conceptdienst(en) vervangen"
            )
        if report.skipped_existing:
            parts.append(f"{len(report.skipped_existing)} stond(en) er al in")
        if report.skipped_by_settings:
            parts.append(
                f"{len(report.skipped_by_settings)} overgeslagen (instellingen)"
            )
        summary = "Klaar: " + ", ".join(parts) + "."
        if report.errors:
            summary += " Fouten: " + " | ".join(report.errors[:3])
            self._set_status(summary, "statusError")
        else:
            self._set_status(summary + " ✓", "statusOk")
        # Everything that was just added is now "already imported": show it.
        for shift in report.added + report.skipped_existing:
            shift.already_imported = True
        self._refresh_preview()

    def _on_failed(self, message: str) -> None:
        self.progress_bar.setVisible(False)
        self.sync_btn.setEnabled(True)
        self._set_status(message, "statusError")
