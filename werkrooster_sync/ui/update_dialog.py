"""Styled "nieuwe versie beschikbaar" dialog with download progress."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from ..core.updater import UpdateError, UpdateInfo, download, install_and_restart
from ..resources import asset_path
from . import theme


class _DownloadWorker(QThread):
    progress = Signal(int, int)
    finished_path = Signal(object)
    failed = Signal(str)

    def __init__(self, update: UpdateInfo, parent=None):
        super().__init__(parent)
        self._update = update

    def run(self):
        try:
            path = download(
                self._update,
                progress=lambda done, total: self.progress.emit(done, total),
            )
            self.finished_path.emit(path)
        except UpdateError as exc:
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    """Prompt → gradient progress bar → install & relaunch."""

    def __init__(self, update: UpdateInfo, current_version: str, parent=None):
        super().__init__(parent)
        self.update_info = update
        self._worker: _DownloadWorker | None = None
        self.setWindowTitle("Update beschikbaar")
        self.setModal(True)
        self.setFixedWidth(500)
        self.setMinimumHeight(300)
        self.setStyleSheet(
            theme.QSS
            + f"""
            QDialog {{
                background: {theme.WINDOW_BG};
                border: 1px solid {theme.BORDER};
            }}
            QProgressBar#updateBar {{
                background-color: {theme.CARD};
                border: 1px solid {theme.BORDER};
                border-radius: 9px;
                min-height: 18px;
                max-height: 18px;
                text-align: center;
                color: white;
                font-size: 11px;
                font-weight: 700;
            }}
            QProgressBar#updateBar::chunk {{
                border-radius: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {theme.ACCENT}, stop:1 #8B7CF6);
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(14)
        logo = QLabel()
        logo_file = asset_path("logo.png")
        if logo_file.exists():
            pix = QPixmap(str(logo_file)).scaled(
                52, 52,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo.setPixmap(pix)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Nieuwe versie beschikbaar")
        title.setStyleSheet(
            f"font-size: 19px; font-weight: 700; color: {theme.TEXT};"
        )
        version = QLabel(f"v{current_version}  →  v{update.version}")
        version.setStyleSheet(
            f"font-size: 14px; font-weight: 600; color: {theme.ACCENT};"
        )
        title_box.addWidget(title)
        title_box.addWidget(version)
        header.addWidget(logo)
        header.addLayout(title_box)
        header.addStretch()
        layout.addLayout(header)

        if update.notes:
            notes = QLabel(self._plain_notes(update.notes))
            notes.setWordWrap(True)
            notes.setObjectName("statusDim")
            notes.setMinimumHeight(70)
            layout.addWidget(notes)
        layout.addStretch()

        self.progress = QProgressBar()
        self.progress.setObjectName("updateBar")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setObjectName("statusDim")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.later_btn = QPushButton("Later")
        self.later_btn.clicked.connect(self.reject)
        self.install_btn = QPushButton("Download && installeer")
        self.install_btn.setObjectName("primary")
        self.install_btn.setStyleSheet(
            "QPushButton#primary { padding: 11px 22px; font-size: 14px; }"
        )
        self.install_btn.clicked.connect(self._start_download)
        buttons.addWidget(self.later_btn)
        buttons.addWidget(self.install_btn)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------
    @staticmethod
    def _plain_notes(notes: str, limit: int = 350) -> str:
        import re

        text = re.sub(r"[#*`>]|\[(.*?)\]\(.*?\)", r"\1", notes)
        text = "\n".join(l.strip() for l in text.splitlines() if l.strip())
        return text[:limit] + ("…" if len(text) > limit else "")

    # ------------------------------------------------------------------
    def _start_download(self) -> None:
        self.install_btn.setEnabled(False)
        self.later_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.status.setObjectName("statusDim")
        self.status.setText("Downloaden…")
        self.status.style().polish(self.status)

        self._worker = _DownloadWorker(self.update_info, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_path.connect(self._on_downloaded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            pct = int(done * 100 / total)
            self.progress.setValue(pct)
            self.progress.setFormat(f"{pct}%")
            mb_done, mb_total = done / 1e6, total / 1e6
            self.status.setText(f"Downloaden… {mb_done:.0f} van {mb_total:.0f} MB")
        else:
            self.progress.setRange(0, 0)  # indeterminate

    def _on_downloaded(self, path) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.progress.setFormat("100%")
        self.status.setObjectName("statusOk")
        self.status.setText("Installeren en opnieuw starten…")
        self.status.style().polish(self.status)
        try:
            install_and_restart(self.update_info, path)
        except UpdateError as exc:
            self._on_failed(str(exc))

    def _on_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.install_btn.setEnabled(True)
        self.later_btn.setEnabled(True)
        self.status.setObjectName("statusError")
        self.status.setText(message)
        self.status.style().polish(self.status)
