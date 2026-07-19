"""Reusable UI widgets: drop zone, badges, toggle switches, step headers."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..core.models import ShiftType
from . import theme


class DropZone(QFrame):
    """Large drag & drop / click-to-browse area for the .ics file."""

    file_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(190)
        self._base_style = f"""
            DropZone {{
                background-color: {theme.CARD};
                border: 2px dashed {theme.BORDER};
                border-radius: 18px;
            }}
        """
        self._hover_style = f"""
            DropZone {{
                background-color: {theme.CARD_HOVER};
                border: 2px dashed {theme.ACCENT};
                border-radius: 18px;
            }}
        """
        self.setStyleSheet(self._base_style)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(6)

        icon = QLabel("📅")
        icon.setStyleSheet("font-size: 44px; background: transparent; border: none;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Sleep je rooster hierheen (.ics of .pdf)")
        title.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {theme.TEXT};"
            "background: transparent; border: none;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        sub = QLabel("of klik om een bestand te kiezen")
        sub.setStyleSheet(
            f"font-size: 14px; color: {theme.TEXT_DIM};"
            "background: transparent; border: none;"
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(sub)

    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Kies je rooster",
            str(Path.home()),
            "Roosterbestanden (*.ics *.pdf)",
        )
        if path:
            self.file_selected.emit(path)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if self._ics_url(event):
            event.acceptProposedAction()
            self.setStyleSheet(self._hover_style)

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self._base_style)

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet(self._base_style)
        url = self._ics_url(event)
        if url:
            self.file_selected.emit(url)
            event.acceptProposedAction()

    @staticmethod
    def _ics_url(event) -> str | None:
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                local = url.toLocalFile()
                if local.lower().endswith((".ics", ".pdf")):
                    return local
        return None


def badge_html(shift_type: ShiftType, name: str) -> str:
    color = theme.SHIFT_COLORS[shift_type]
    return (
        f'<span style="color:{color}; font-weight:700;">●</span>'
        f'&nbsp;<b>{name}</b>'
    )


class ToggleSwitch(QCheckBox):
    """iOS-style on/off slider: green track when on, grey when off, with a
    white knob. Drop-in replacement for QCheckBox (same API/signals)."""

    TRACK_W, TRACK_H, KNOB = 42, 24, 20

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(28)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        w = self.TRACK_W
        if self.text():
            w += 12 + self.fontMetrics().horizontalAdvance(self.text())
        return QSize(w + 4, 28)

    def hitButton(self, pos) -> bool:  # noqa: N802 (Qt API)
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        y = (self.height() - self.TRACK_H) / 2

        track = QColor(theme.ACCENT) if on else QColor(theme.SWITCH_OFF)
        if not self.isEnabled():
            track.setAlphaF(0.45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(
            QRectF(0, y, self.TRACK_W, self.TRACK_H),
            self.TRACK_H / 2, self.TRACK_H / 2,
        )

        knob_x = self.TRACK_W - self.KNOB - 2 if on else 2
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(knob_x, y + 2, self.KNOB, self.KNOB))

        if self.text():
            p.setPen(QColor(theme.TEXT if self.isEnabled() else theme.TEXT_DIM))
            p.setFont(self.font())
            p.drawText(
                QRectF(self.TRACK_W + 12, 0, self.width() - self.TRACK_W - 12,
                       self.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                self.text(),
            )
        p.end()


class StepHeader(QFrame):
    """'Stap N' title box: a full-width bar with an accent number badge and a
    bold title — styled via the QFrame#stepHeader rule in the theme."""

    def __init__(self, number: int, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("stepHeader")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)

        badge = QLabel(str(number))
        badge.setFixedSize(30, 30)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"""
            QLabel {{
                background-color: {theme.ACCENT};
                color: white;
                border-radius: 15px;
                font-size: 15px;
                font-weight: 800;
                border: none;
            }}
            """
        )

        text = QLabel(title)
        text.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {theme.TEXT};"
            "background: transparent; border: none;"
        )

        row.addWidget(badge)
        row.addWidget(text)
        row.addStretch()


class CountChip(QLabel):
    """Small pill showing e.g. '● Ochtend × 6'."""

    def __init__(self, shift_type: ShiftType, name: str, count: int, parent=None):
        super().__init__(parent)
        color = theme.SHIFT_COLORS[shift_type]
        self.setText(f"● {name} ×{count}")
        self.setStyleSheet(
            f"""
            QLabel {{
                color: {color};
                background-color: {theme.CARD};
                border: 1px solid {theme.BORDER};
                border-radius: 12px;
                padding: 4px 9px;
                font-weight: 600;
                font-size: 12px;
            }}
            """
        )
