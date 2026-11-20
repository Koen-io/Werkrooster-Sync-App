"""Bouwstenen voor de schermen: sleepvak, stappenbalk, tegels, labels,
schakelaars, getekende pictogrammen en datums in het Nederlands."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme

WEEKDAGEN = ["ma", "di", "wo", "do", "vr", "za", "zo"]
WEEKDAGEN_LANG = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
MAANDEN = ["jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
MAANDEN_LANG = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus",
                "september", "oktober", "november", "december"]


def dag_kort(d: date) -> str:
    """vr 20 nov"""
    return f"{WEEKDAGEN[d.weekday()]} {d.day} {MAANDEN[d.month - 1]}"


def dag_lang(d: date) -> str:
    """vrijdag 20 november"""
    return f"{WEEKDAGEN_LANG[d.weekday()]} {d.day} {MAANDEN_LANG[d.month - 1]}"


def periode_tekst(eerste: date, laatste: date) -> str:
    """20 t/m 29 november 2026"""
    if eerste.year != laatste.year:
        return (f"{eerste.day} {MAANDEN_LANG[eerste.month - 1]} {eerste.year} t/m "
                f"{laatste.day} {MAANDEN_LANG[laatste.month - 1]} {laatste.year}")
    if eerste.month != laatste.month:
        return (f"{eerste.day} {MAANDEN_LANG[eerste.month - 1]} t/m "
                f"{laatste.day} {MAANDEN_LANG[laatste.month - 1]} {laatste.year}")
    return f"{eerste.day} t/m {laatste.day} {MAANDEN_LANG[laatste.month - 1]} {laatste.year}"


def tijden(start: datetime, end: datetime, all_day: bool) -> str:
    return "hele dag" if all_day else f"{start:%H:%M}–{end:%H:%M}"


def herpolish(w: QWidget, naam: str) -> None:
    """Verander de objectName en laat de stijl opnieuw toepassen."""
    w.setObjectName(naam)
    w.style().unpolish(w)
    w.style().polish(w)


def label(tekst: str = "", naam: str = "", wrap: bool = False) -> QLabel:
    lbl = QLabel(tekst)
    if naam:
        lbl.setObjectName(naam)
    lbl.setWordWrap(wrap)
    return lbl


def knop(tekst: str, naam: str = "", klik=None) -> QPushButton:
    b = QPushButton(tekst)
    if naam:
        b.setObjectName(naam)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if klik:
        b.clicked.connect(klik)
    return b


def kaart(naam: str = "card") -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName(naam)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(22, 18, 22, 18)
    lay.setSpacing(8)
    return f, lay


def leeg_layout(layout) -> None:
    """Haal alles uit een layout (ook geneste layouts)."""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif item.layout():
            leeg_layout(item.layout())


# ----------------------------------------------------------------------
# Getekende pictogrammen (geen emoji: die zien er op elk systeem anders uit)
# ----------------------------------------------------------------------
class Icoon(QWidget):
    """Een eenvoudig lijnpictogram: upload, download, agenda, mail, schild, info."""

    def __init__(self, soort: str, maat: int = 28, kleur: str = theme.ACCENT, parent=None):
        super().__init__(parent)
        self.soort, self.kleur = soort, kleur
        self.setFixedSize(maat, maat)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self.width() / 24.0
        p.scale(s, s)
        pen = QPen(QColor(self.kleur), 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.soort in ("upload", "download"):
            pad = QPainterPath()
            pad.moveTo(14, 2.5)
            pad.lineTo(6.5, 2.5)
            pad.quadTo(4.5, 2.5, 4.5, 4.5)
            pad.lineTo(4.5, 19.5)
            pad.quadTo(4.5, 21.5, 6.5, 21.5)
            pad.lineTo(17.5, 21.5)
            pad.quadTo(19.5, 21.5, 19.5, 19.5)
            pad.lineTo(19.5, 8)
            pad.closeSubpath()
            p.drawPath(pad)
            p.drawPolyline([QPointF(14, 2.5), QPointF(14, 8), QPointF(19.5, 8)])
            p.drawLine(QPointF(12, 11), QPointF(12, 18))
            if self.soort == "upload":
                p.drawPolyline([QPointF(9, 14), QPointF(12, 11), QPointF(15, 14)])
            else:
                p.drawPolyline([QPointF(9, 15), QPointF(12, 18), QPointF(15, 15)])
        elif self.soort == "agenda":
            p.drawRoundedRect(QRectF(3.5, 5, 17, 15.5), 2.5, 2.5)
            p.drawLine(QPointF(3.5, 10), QPointF(20.5, 10))
            p.drawLine(QPointF(8, 3), QPointF(8, 7))
            p.drawLine(QPointF(16, 3), QPointF(16, 7))
        elif self.soort == "mail":
            p.drawRoundedRect(QRectF(3, 5.5, 18, 13), 2.5, 2.5)
            p.drawPolyline([QPointF(3.5, 7), QPointF(12, 13), QPointF(20.5, 7)])
        elif self.soort == "schild":
            pad = QPainterPath()
            pad.moveTo(12, 3)
            pad.lineTo(19, 6)
            pad.lineTo(19, 11)
            pad.quadTo(19, 17.5, 12, 21)
            pad.quadTo(5, 17.5, 5, 11)
            pad.lineTo(5, 6)
            pad.closeSubpath()
            p.drawPath(pad)
            p.drawPolyline([QPointF(9, 12), QPointF(11.2, 14.2), QPointF(15, 10)])
        elif self.soort == "info":
            p.drawEllipse(QRectF(3, 3, 18, 18))
            p.drawLine(QPointF(12, 11), QPointF(12, 16.5))
            p.setBrush(QColor(self.kleur))
            p.drawEllipse(QRectF(11.1, 7, 1.8, 1.8))
        elif self.soort == "let-op":
            pad = QPainterPath()
            pad.moveTo(12, 3.5)
            pad.lineTo(21, 19.5)
            pad.lineTo(3, 19.5)
            pad.closeSubpath()
            p.drawPath(pad)
            p.drawLine(QPointF(12, 9.5), QPointF(12, 14))
            p.setBrush(QColor(self.kleur))
            p.drawEllipse(QRectF(11.1, 16, 1.8, 1.8))
        p.end()


class Vinkrondje(QWidget):
    """Groot rond vinkje (of uitroepteken) voor het klaar-scherm."""

    def __init__(self, maat: int = 120, kleur: str = theme.OK, soort: str = "vink", parent=None):
        super().__init__(parent)
        self.kleur, self.soort = kleur, soort
        self.setFixedSize(maat, maat)

    def zet(self, kleur: str, soort: str) -> None:
        self.kleur, self.soort = kleur, soort
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.kleur))
        p.drawEllipse(QRectF(0, 0, w, w))
        pen = QPen(QColor(theme.ACCENT_TEXT), w * 0.07)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        if self.soort == "vink":
            p.drawPolyline([QPointF(w * .32, w * .52), QPointF(w * .45, w * .65),
                            QPointF(w * .69, w * .38)])
        else:  # uitroepteken
            p.drawLine(QPointF(w * .5, w * .28), QPointF(w * .5, w * .56))
            p.drawPoint(QPointF(w * .5, w * .72))
        p.end()


class Stip(QWidget):
    """Gekleurde stip; leeg rondje als de kleur leeg is."""

    def __init__(self, kleur: str, maat: int = 14, parent=None):
        super().__init__(parent)
        self.kleur = kleur
        self.setFixedSize(maat, maat)

    def zet(self, kleur: str) -> None:
        self.kleur = kleur
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        if self.kleur:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(self.kleur))
        else:
            p.setPen(QPen(QColor(theme.TEXT_DIM), 2))
        p.drawEllipse(r)
        p.end()


class Pil(QLabel):
    """Label in een afgerond vlak, bijvoorbeeld "+ Nieuw" of "Gewijzigd"."""

    def __init__(self, tekst: str, achter: str = "", voor: str = theme.TEXT,
                 rand: str = "", parent=None):
        super().__init__(tekst, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(30)
        self.setStyleSheet(
            f"background: {achter or 'transparent'}; color: {voor};"
            f"border: {'1px solid ' + rand if rand else 'none'};"
            "border-radius: 15px; padding: 0px 14px; font-weight: 700; font-size: 14px;")
        self.setMinimumWidth(self.sizeHint().width())


# ----------------------------------------------------------------------
class DropZone(QFrame):
    """Groot sleepvak voor het pdf-rooster, met de knop "Kies pdf-bestand".
    Geeft een lijst paden: concept en definitief mogen er tegelijk in."""

    files_selected = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._actief = True
        self._stijl(False)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)
        layout.setContentsMargins(40, 40, 40, 40)

        icoon = Icoon("upload", 64)
        layout.addWidget(icoon, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(8)
        titel = label("Sleep je rooster hierheen", "pageTitle")
        titel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(titel)
        sub = label("Het pdf-bestand “Medewerker Rooster” uit BVCM. Je conceptrooster "
                    "en je definitieve rooster mogen er tegelijk in.", "lead", wrap=True)
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setFixedWidth(640)
        layout.addWidget(sub, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(10)
        self.kies_btn = knop("Kies pdf-bestand", "primary", self.kies)
        self.kies_btn.setMinimumWidth(300)
        layout.addWidget(self.kies_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.hulp_btn = knop("Hoe haal ik de pdf uit BVCM?", "link")
        layout.addWidget(self.hulp_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self.fout = label("", "statusError", wrap=True)
        self.fout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fout.setMaximumWidth(620)
        self.fout.setVisible(False)
        layout.addWidget(self.fout, alignment=Qt.AlignmentFlag.AlignCenter)

    def _stijl(self, hover: bool) -> None:
        self.setStyleSheet(
            f"DropZone {{ background-color: {theme.CARD_HOVER if hover else theme.CARD};"
            f" border: 2px dashed {theme.ACCENT if hover else theme.BORDER};"
            " border-radius: 22px; }")

    def set_actief(self, aan: bool) -> None:
        """Tijdens het bijwerken kan er geen nieuw rooster in."""
        self._actief = aan
        self.setAcceptDrops(aan)
        self.kies_btn.setEnabled(aan)

    def toon_fout(self, tekst: str) -> None:
        self.fout.setText(tekst)
        self.fout.setVisible(bool(tekst))

    def kies(self) -> None:
        paden, _ = QFileDialog.getOpenFileNames(
            self, "Kies je rooster", str(Path.home()), "Roosters (*.pdf)")
        if paden:
            self.files_selected.emit(paden)

    def dragEnterEvent(self, event: QDragEnterEvent):  # noqa: N802 (Qt API)
        if self._actief and self._pdfs(event):
            event.acceptProposedAction()
            self._stijl(True)

    def dragLeaveEvent(self, event):  # noqa: N802 (Qt API)
        self._stijl(False)

    def dropEvent(self, event: QDropEvent):  # noqa: N802 (Qt API)
        self._stijl(False)
        paden = self._pdfs(event)
        if self._actief and paden:
            event.acceptProposedAction()
            self.files_selected.emit(paden)

    @staticmethod
    def _pdfs(event) -> list[str]:
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls() if u.toLocalFile().lower().endswith(".pdf")]


class ToggleSwitch(QCheckBox):
    """Aan/uit-schuifje: groen als hij aan staat. Zelfde gebruik als QCheckBox."""

    TRACK_W, TRACK_H, KNOB = 50, 28, 22

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(30)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        w = self.TRACK_W
        if self.text():
            w += 12 + self.fontMetrics().horizontalAdvance(self.text())
        return QSize(w + 4, 30)

    def hitButton(self, pos) -> bool:  # noqa: N802 (Qt API)
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        y = (self.height() - self.TRACK_H) / 2
        track = QColor(theme.OK if on else theme.SWITCH_OFF)
        if not self.isEnabled():
            track.setAlphaF(0.45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, y, self.TRACK_W, self.TRACK_H),
                          self.TRACK_H / 2, self.TRACK_H / 2)
        knob_x = self.TRACK_W - self.KNOB - 3 if on else 3
        p.setBrush(QColor(theme.BG if on else theme.TEXT_DIM))
        p.drawEllipse(QRectF(knob_x, y + 3, self.KNOB, self.KNOB))
        if self.text():
            p.setPen(QColor(theme.TEXT if self.isEnabled() else theme.TEXT_DIM))
            p.setFont(self.font())
            p.drawText(QRectF(self.TRACK_W + 12, 0, self.width() - self.TRACK_W - 12,
                              self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        p.end()


class StepBar(QWidget):
    """De drie stappen bovenaan: Rooster kiezen — Controleren — Klaar."""

    NAMEN = ["Rooster kiezen", "Controleren", "Klaar"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stap = 0
        self.setFixedHeight(64)

    def zet(self, stap: int) -> None:
        self.stap = stap
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = self.font()
        f.setPixelSize(19)
        f.setWeight(f.Weight.DemiBold)
        p.setFont(f)
        fm = p.fontMetrics()
        r, cy = 28, self.height() / 2
        breedte = [2 * r + 18 + fm.horizontalAdvance(n) for n in self.NAMEN]
        rest = self.width() - sum(breedte)
        gat = max(40, rest / 2)
        x = 0.0
        for i, naam in enumerate(self.NAMEN):
            klaar, nu = i < self.stap, i == self.stap
            cirkel = QRectF(x, cy - r, 2 * r, 2 * r)
            if nu:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(theme.ACCENT))
            elif klaar:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(theme.BORDER))
            else:
                p.setPen(QPen(QColor(theme.BORDER), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(cirkel.adjusted(1, 1, -1, -1))
            if klaar:
                pen = QPen(QColor(theme.ACCENT), 2.6)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawPolyline([QPointF(x + r * .62, cy + 1), QPointF(x + r * .88, cy + r * .28),
                                QPointF(x + r * 1.38, cy - r * .3)])
            else:
                p.setPen(QColor(theme.ACCENT_TEXT if nu else theme.TEXT_DIM))
                p.drawText(cirkel, Qt.AlignmentFlag.AlignCenter, str(i + 1))
            p.setPen(QColor(theme.TEXT if nu else theme.TEXT_DIM))
            tx = x + 2 * r + 18
            p.drawText(QRectF(tx, 0, breedte[i], self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, naam)
            x += breedte[i]
            if i < 2:
                p.setPen(QPen(QColor(theme.ACCENT if i < self.stap else theme.BORDER), 2))
                p.drawLine(QPointF(x + 14, cy), QPointF(x + gat - 14, cy))
                x += gat
        p.end()


class Tegel(QFrame):
    """Tegel met een groot getal en een woord eronder ("5 / nieuw")."""

    def __init__(self, getal: int, tekst: str, kleur: str = theme.TEXT, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 10, 18, 10)
        lay.setSpacing(0)
        g = QLabel(str(getal))
        g.setStyleSheet(f"font-size: 32px; font-weight: 800; color: {kleur}; border: none;")
        t = label(tekst, "statusDim", wrap=True)
        t.setStyleSheet("font-size: 16px; border: none;")
        lay.addWidget(g)
        lay.addWidget(t)
        lay.addStretch()


class KeuzeKaart(QFrame):
    """Aanklikbare kaart met stip of pictogram, titel en uitleg."""

    clicked = Signal()

    def __init__(self, titel: str, uitleg: str, stip: str | None = None,
                 icoon: str = "", parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gekozen = False
        self._stijl()
        self.titel = titel
        lay = QHBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(18)
        if stip is not None:
            lay.addWidget(Stip(stip, 26), alignment=Qt.AlignmentFlag.AlignVCenter)
        tekst = QVBoxLayout()
        tekst.setSpacing(6)
        if icoon:
            boven = QHBoxLayout()
            boven.addWidget(Icoon(icoon, 40))
            boven.addStretch()
            self.badge = Pil("Gekozen", theme.ACCENT, theme.ACCENT_TEXT)
            self.badge.setVisible(False)
            boven.addWidget(self.badge, alignment=Qt.AlignmentFlag.AlignTop)
            tekst.addLayout(boven)
            tekst.addStretch()
        t = QLabel(titel)
        t.setStyleSheet("font-size: 22px; font-weight: 700; border: none;")
        u = label(uitleg, "statusDim", wrap=True)
        u.setStyleSheet("font-size: 15px; border: none;")
        if not icoon:
            tekst.addStretch()  # titel en uitleg samen naast de stip, niet uit elkaar
        tekst.addWidget(t)
        tekst.addWidget(u)
        if not icoon:
            tekst.addStretch()
        lay.addLayout(tekst, stretch=1)

    def _stijl(self) -> None:
        self.setStyleSheet(
            f"KeuzeKaart {{ background: {theme.SELECTED if self._gekozen else theme.CARD};"
            f" border: {2 if self._gekozen else 1}px solid "
            f"{theme.ACCENT if self._gekozen else theme.BORDER}; border-radius: 18px; }}"
            f"KeuzeKaart:hover {{ border-color: {theme.ACCENT}; }}")

    def zet_gekozen(self, aan: bool) -> None:
        self._gekozen = aan
        if hasattr(self, "badge"):
            self.badge.setVisible(aan)
        self._stijl()

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt API)
        if self.isEnabled() and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
