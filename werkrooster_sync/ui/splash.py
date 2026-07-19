"""Animated splash screen.

A native Qt reimplementation of the designed HTML splash (design source:
assets/splash_animated.html): a dark card that scales in, logo / title /
tagline / dots sliding up staggered, a pulsing purple glow and three
loading dots pulsing in sequence. Runs at 60 fps without needing a browser
engine inside the app.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

CARD_W, CARD_H = 560, 360
MARGIN = 40  # transparent border around the card (room for the entrance scale)

BG_TOP = QColor("#0E1117")
BG_BOTTOM = QColor("#12121F")
BORDER = QColor("#252C3D")
TEXT = QColor("#E8EBF2")
TEXT_DIM = QColor("#8B93A7")
ACCENT = QColor("#6C7CFF")
GLOW = QColor(139, 124, 246)
DOT_COLORS = [QColor("#5DA8F5"), QColor("#6C7CFF"), QColor("#8B7CF6")]
LOGO_BLUE = QColor("#5DA8F5")
LOGO_PURPLE = QColor("#8B7CF6")


def _ease_out(x: float) -> float:
    """Approximation of cubic-bezier(0.22, 1, 0.36, 1)."""
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _fade_up(t: float, delay: float, duration: float = 0.8) -> tuple[float, float]:
    """(opacity, y-offset) for the staggered slide-up entrance."""
    p = _ease_out((t - delay) / duration)
    return p, 8.0 * (1 - p)


class AnimatedSplash(QWidget):
    """Frameless always-on-top splash with the designed entrance + loops."""

    def __init__(self, version: str = "v1.0.0"):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SplashScreen,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(CARD_W + 2 * MARGIN, CARD_H + 2 * MARGIN)
        self._version = version
        self._start = time.monotonic()
        self._time_override: float | None = None  # for tests/screenshots
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(16)

    # ------------------------------------------------------------------
    def _t(self) -> float:
        if self._time_override is not None:
            return self._time_override
        return time.monotonic() - self._start

    def finish(self, window) -> None:
        self._timer.stop()
        self.close()

    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        t = self._t()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Entrance: scale 0.92 -> 1 and fade in (0.7 s).
        enter = _ease_out(t / 0.7)
        p.setOpacity(enter)
        cx, cy = self.width() / 2, self.height() / 2
        scale = 0.92 + 0.08 * enter
        p.translate(cx, cy)
        p.scale(scale, scale)
        p.translate(-cx, -cy)

        card = QRectF(MARGIN, MARGIN, CARD_W, CARD_H)
        path = QPainterPath()
        path.addRoundedRect(card, 24, 24)

        grad = QLinearGradient(card.topLeft(), card.bottomLeft())
        grad.setColorAt(0.0, BG_TOP)
        grad.setColorAt(1.0, BG_BOTTOM)
        p.fillPath(path, QBrush(grad))
        p.setPen(QPen(BORDER, 1))
        p.drawPath(path)

        p.setClipPath(path)

        # Pulsing radial glow (4.5 s loop): opacity 0.55 -> 1 -> 0.55.
        pulse = 0.775 + 0.225 * math.sin(2 * math.pi * t / 4.5 - math.pi / 2)
        glow_center = card.center().x(), card.top() + 0.42 * CARD_H
        glow = QRadialGradient(glow_center[0], glow_center[1], 0.6 * CARD_W)
        g = QColor(GLOW)
        g.setAlphaF(0.13 * pulse)
        glow.setColorAt(0.0, g)
        glow.setColorAt(0.7, QColor(0, 0, 0, 0))
        p.fillRect(card, QBrush(glow))

        # ---- logo (two pills, screen-blended overlap, hub dot) --------
        op, dy = _fade_up(t, 0.1)
        p.setOpacity(enter * op)
        lx = card.center().x() - 60
        ly = card.top() + 92 + dy
        p.save()
        p.translate(lx, ly)
        p.setPen(Qt.PenStyle.NoPen)
        blue = QColor(LOGO_BLUE)
        blue.setAlphaF(0.85)
        p.setBrush(blue)
        p.drawRoundedRect(QRectF(18, 14, 52, 56), 14, 14)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        purple = QColor(LOGO_PURPLE)
        purple.setAlphaF(0.85)
        p.setBrush(purple)
        p.drawRoundedRect(QRectF(50, 14, 52, 56), 14, 14)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        strip = QColor(TEXT)
        strip.setAlphaF(0.16)
        p.setBrush(strip)
        p.drawRect(QRectF(50, 14, 20, 56))
        p.setBrush(TEXT)
        p.drawEllipse(QRectF(53, 35, 14, 14))
        p.restore()

        # ---- name -----------------------------------------------------
        op, dy = _fade_up(t, 0.2)
        p.setOpacity(enter * op)
        name_font = QFont()
        name_font.setPixelSize(30)
        name_font.setWeight(QFont.Weight.Bold)
        p.setFont(name_font)
        fm = p.fontMetrics()
        part1, part2 = "Werkrooster ", "Sync"
        total = fm.horizontalAdvance(part1 + part2)
        nx = card.center().x() - total / 2
        ny = card.top() + 216 + dy
        p.setPen(TEXT)
        p.drawText(QRectF(nx, ny - 30, total + 10, 40), 0, part1)
        p.setPen(ACCENT)
        p.drawText(
            QRectF(nx + fm.horizontalAdvance(part1), ny - 30, total, 40), 0, part2
        )

        # ---- tagline --------------------------------------------------
        op, dy = _fade_up(t, 0.3)
        p.setOpacity(enter * op)
        tag_font = QFont()
        tag_font.setPixelSize(15)
        p.setFont(tag_font)
        p.setPen(TEXT_DIM)
        tag = "Jouw rooster — Snel · Simpel · Overal"
        tw = p.fontMetrics().horizontalAdvance(tag)
        p.drawText(QRectF(card.center().x() - tw / 2, card.top() + 228 + dy, tw + 10, 24), 0, tag)

        # ---- loading dots (1.2 s pulse, staggered) --------------------
        op, dy = _fade_up(t, 0.4)
        dots_y = card.top() + 286 + dy
        for i, color in enumerate(DOT_COLORS):
            dot_pulse = 0.775 + 0.225 * math.sin(
                2 * math.pi * (t - 0.2 * i) / 1.2 - math.pi / 2
            )
            p.setOpacity(enter * op * dot_pulse)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            x = card.center().x() - 12 + i * 16
            p.drawEllipse(QRectF(x - 4, dots_y, 8, 8))

        # ---- meta -----------------------------------------------------
        op, _ = _fade_up(t, 0.4)
        p.setOpacity(enter * op)
        meta_font = QFont("Menlo")
        meta_font.setStyleHint(QFont.StyleHint.Monospace)
        meta_font.setPixelSize(12)
        p.setFont(meta_font)
        p.setPen(TEXT_DIM)
        meta = f"{self._version}   ·   Windows & macOS"
        mw = p.fontMetrics().horizontalAdvance(meta)
        p.drawText(
            QRectF(card.center().x() - mw / 2, card.bottom() - 46, mw + 10, 20), 0, meta
        )
        p.end()
