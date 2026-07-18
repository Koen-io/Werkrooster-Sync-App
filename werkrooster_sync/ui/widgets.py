"""Reusable UI widgets: drop zone and shift badges."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
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


class StepHeader(QWidget):
    """'Stap N' header: accent circle with the number + bold title."""

    def __init__(self, number: int, title: str, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
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
