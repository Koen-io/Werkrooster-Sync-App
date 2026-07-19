"""Styled feedback / questions form that emails the developer via Web3Forms."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.feedback import FeedbackError, send_feedback
from ..core.updater import current_version
from ..resources import asset_path
from . import theme


class _SendWorker(QThread):
    done = Signal()
    failed = Signal(str)

    def __init__(self, name, message, email, parent=None):
        super().__init__(parent)
        self._args = (name, message, email)

    def run(self):
        name, message, email = self._args
        try:
            send_feedback(name, message, email=email, app_version=current_version())
            self.done.emit()
        except FeedbackError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(f"Onverwachte fout: {exc}")


class FeedbackDialog(QDialog):
    """Name (required) + email (optional) + message, sent to the developer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _SendWorker | None = None
        self.setWindowTitle("Feedback & Vragen")
        self.setModal(True)
        self.setFixedWidth(520)
        self.setStyleSheet(
            theme.QSS
            + f"""
            QDialog {{
                background: {theme.WINDOW_BG};
                border: 1px solid {theme.BORDER};
            }}
            QTextEdit {{
                background-color: {theme.INPUT_BG};
                border: 1px solid {theme.BORDER};
                border-radius: 10px;
                padding: 8px 12px;
                color: {theme.TEXT};
                selection-background-color: {theme.ACCENT};
            }}
            QTextEdit:focus {{ border-color: {theme.ACCENT}; }}
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._stack = QStackedWidget()
        outer.addWidget(self._stack)
        self._stack.addWidget(self._build_form())   # page 0
        self._stack.addWidget(self._build_success())  # page 1

    # ------------------------------------------------------------------
    def _build_form(self) -> QWidget:
        page = QWidget()
        self._layout = QVBoxLayout(page)
        self._layout.setContentsMargins(28, 26, 28, 24)
        self._layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(14)
        logo = QLabel()
        logo_file = asset_path("logo.png")
        if logo_file.exists():
            logo.setPixmap(
                QPixmap(str(logo_file)).scaled(
                    48, 48,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("Feedback & Vragen")
        title.setStyleSheet(f"font-size: 19px; font-weight: 700; color: {theme.TEXT};")
        sub = QLabel("Je bericht gaat rechtstreeks naar de ontwikkelaar.")
        sub.setStyleSheet(f"font-size: 13px; color: {theme.TEXT_DIM};")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        header.addWidget(logo)
        header.addLayout(title_box)
        header.addStretch()
        self._layout.addLayout(header)

        name_lbl = QLabel("Naam")
        name_lbl.setObjectName("sectionTitle")
        self._layout.addWidget(name_lbl)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Je naam")
        self._layout.addWidget(self.name_edit)

        email_lbl = QLabel("E-mailadres (optioneel)")
        email_lbl.setObjectName("sectionTitle")
        self._layout.addWidget(email_lbl)
        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("naam@voorbeeld.nl — voor een antwoord")
        self._layout.addWidget(self.email_edit)

        msg_lbl = QLabel("Feedback of vraag")
        msg_lbl.setObjectName("sectionTitle")
        self._layout.addWidget(msg_lbl)
        self.message_edit = QTextEdit()
        self.message_edit.setPlaceholderText(
            "Wat werkt goed, wat kan beter, of stel je vraag…"
        )
        self.message_edit.setMinimumHeight(130)
        self._layout.addWidget(self.message_edit)

        self.status = QLabel("")
        self.status.setObjectName("statusDim")
        self.status.setWordWrap(True)
        self._layout.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_btn = QPushButton("Annuleren")
        self.cancel_btn.clicked.connect(self.reject)
        self.send_btn = QPushButton("Verstuur")
        self.send_btn.setObjectName("primary")
        self.send_btn.setStyleSheet(
            "QPushButton#primary { padding: 11px 24px; font-size: 14px; }"
        )
        self.send_btn.clicked.connect(self._send)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.send_btn)
        self._layout.addLayout(buttons)
        return page

    # ------------------------------------------------------------------
    def _build_success(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(28, 26, 28, 24)
        box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.setSpacing(14)

        check = QLabel("✓")
        check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        check.setStyleSheet(f"font-size: 52px; font-weight: 800; color: {theme.OK};")
        title = QLabel("Bedankt voor je bericht!")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {theme.TEXT};")
        sub = QLabel("Je feedback is verstuurd naar de ontwikkelaar.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(f"font-size: 14px; color: {theme.TEXT_DIM};")

        box.addStretch()
        box.addWidget(check)
        box.addWidget(title)
        box.addWidget(sub)
        box.addSpacing(8)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Sluiten")
        close_btn.setObjectName("primary")
        close_btn.setStyleSheet(
            "QPushButton#primary { padding: 11px 28px; font-size: 14px; }"
        )
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        close_row.addStretch()
        box.addLayout(close_row)
        box.addStretch()
        return page

    # ------------------------------------------------------------------
    def _send(self) -> None:
        name = self.name_edit.text().strip()
        message = self.message_edit.toPlainText().strip()
        if not name:
            self._error("Vul je naam in.")
            return
        if not message:
            self._error("Vul je feedback of vraag in.")
            return

        self.send_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.status.setObjectName("statusDim")
        self.status.setText("Versturen…")
        self.status.style().polish(self.status)

        self._worker = _SendWorker(name, message, self.email_edit.text().strip(), self)
        self._worker.done.connect(self._show_success)
        self._worker.failed.connect(self._error_after_send)
        self._worker.start()

    def _error(self, message: str) -> None:
        self.status.setObjectName("statusError")
        self.status.setText(message)
        self.status.style().polish(self.status)

    def _error_after_send(self, message: str) -> None:
        self.send_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self._error(message)

    # ------------------------------------------------------------------
    def _show_success(self) -> None:
        self._stack.setCurrentIndex(1)
