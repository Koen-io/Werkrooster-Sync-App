"""Het uiterlijk van de app: één donker thema in de kleuren van het ontwerp.

Geen kleurverloop, geen gekleurde linkerrand op kaarten, geen emoji.
Een lettertype in ``werkrooster_sync/fonts/`` (.ttf of .otf) wordt bij de
start geladen, zodat de app er op Windows en Mac hetzelfde uitziet; zonder
zo'n bestand gebruikt de app het systeemlettertype.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from ..core.models import ShiftType

BG = WINDOW_BG = "#0E1117"
CARD = "#171C28"
CARD_HOVER = "#1C2232"
BORDER = "#2A3245"
INPUT_BG = "#0E1117"
TEXT = "#EEF1F7"
TEXT_DIM = "#9AA3B8"
ACCENT = "#8E9BFF"
ACCENT_HOVER = "#A3AEFF"
ACCENT_PRESSED = "#7A88F0"
ACCENT_TEXT = "#0B0E1A"
#: Kaart die gekozen is (iets blauwer dan een gewone kaart).
SELECTED = "#1C2140"

OCHTEND = "#FFB340"
LAAT = "#FF8A5C"
NACHT = "#A99CFF"
VRIJ = OK = "#34C759"
AFSPRAAK = "#30C8C9"
WARN = "#FFB340"
DANGER = "#FF6B6B"
SWITCH_OFF = BORDER
STEP_BG = CARD

#: Kleur per soort (de dienstsoorten zelf hebben een eigen kleur in de instellingen).
SHIFT_COLORS: dict[ShiftType, str] = {
    ShiftType.VRIJ: VRIJ,
    ShiftType.OCHTEND: OCHTEND,
    ShiftType.LAAT: LAAT,
    ShiftType.NACHT: NACHT,
    ShiftType.DIENST: ACCENT,
    ShiftType.AFSPRAAK: AFSPRAAK,
    ShiftType.NEGEREN: TEXT_DIM,
}

#: Familienaam van het meegeleverde lettertype ("" = systeemlettertype).
FONT_FAMILY = ""


def kleur_voor(settings, sleutel: str) -> str:
    """Kleur van een soort: de eigen kleur van een dienstsoort, anders vast."""
    for d in settings.dienstsoorten:
        if d.get("id") == sleutel and d.get("kleur"):
            return d["kleur"]
    try:
        return SHIFT_COLORS[ShiftType(sleutel)]
    except ValueError:
        return ACCENT


def fonts_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "fonts"
    return Path(__file__).resolve().parents[1] / "fonts"


def laad_lettertype() -> str:
    """Laad de lettertypen uit de map fonts/ (na het maken van de QApplication).
    Geeft de familienaam terug, of "" als er geen lettertype is meegeleverd."""
    global FONT_FAMILY, QSS
    from PySide6.QtGui import QFontDatabase

    families: list[str] = []
    map_ = fonts_dir()
    if map_.is_dir():
        for f in sorted(map_.iterdir()):
            if f.suffix.lower() in (".ttf", ".otf"):
                fid = QFontDatabase.addApplicationFont(str(f))
                if fid >= 0:
                    families += QFontDatabase.applicationFontFamilies(fid)
    FONT_FAMILY = families[0] if families else ""
    QSS = _build_qss()
    return FONT_FAMILY


def _pijl() -> str:
    """Pijltje voor keuzelijsten. Qt kan in een stylesheet alleen een plaatje
    uit een bestand tonen; dit schrijven we één keer in de tijdelijke map, zodat
    het ook in de gebouwde app werkt zonder extra meegeleverde bestanden."""
    pad = Path(tempfile.gettempdir()) / "werkroostersync-pijl.svg"
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="12" height="8">'
           f'<path d="M1 1.5 6 6.5 11 1.5" fill="none" stroke="{TEXT_DIM}" '
           'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    try:
        if not pad.exists() or pad.read_text() != svg:
            pad.write_text(svg)
    except OSError:
        return ""
    return pad.as_posix()


def _build_qss() -> str:
    familie = f'"{FONT_FAMILY}", ' if FONT_FAMILY else ""
    return f"""
* {{
    font-family: {familie}"SF Pro Text", "Segoe UI Variable", "Segoe UI", -apple-system, sans-serif;
    outline: none;
}}
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ color: {TEXT}; font-size: 14px; }}
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
QLabel {{ background: transparent; }}
QLabel#appTitle {{ font-size: 24px; font-weight: 700; }}
QLabel#appSubtitle {{ font-size: 14px; color: {TEXT_DIM}; }}
QLabel#pageTitle {{ font-size: 34px; font-weight: 800; }}
QLabel#bigTitle {{ font-size: 28px; font-weight: 800; }}
QLabel#lead {{ font-size: 16px; color: {TEXT_DIM}; }}
QLabel#sectionTitle {{
    font-size: 12px; font-weight: 700; color: {TEXT_DIM}; letter-spacing: 1px;
}}
QLabel#statusOk {{ color: {OK}; }}
QLabel#statusError {{ color: {DANGER}; }}
QLabel#statusDim {{ color: {TEXT_DIM}; }}
QLabel#statusWarn {{ color: {WARN}; }}
QLabel#link {{ color: {ACCENT}; text-decoration: underline; }}

QFrame#card {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 16px;
}}
QFrame#card QLabel {{ border: none; }}
QFrame#warnBox {{
    background-color: {CARD};
    border: 1px solid {WARN};
    border-radius: 14px;
}}
QFrame#warnBox QLabel {{ border: none; }}
QFrame#dangerBox {{
    background-color: {CARD};
    border: 1px solid {DANGER};
    border-radius: 14px;
}}
QFrame#dangerBox QLabel {{ border: none; }}

QPushButton {{
    background-color: transparent;
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 10px 20px;
    font-weight: 600;
    color: {TEXT};
}}
QPushButton:hover {{ background-color: {CARD_HOVER}; border-color: {ACCENT}; }}
QPushButton:pressed {{ background-color: {CARD}; }}
QPushButton:disabled {{ color: {TEXT_DIM}; border-color: {BORDER}; }}

QPushButton#primary {{
    background-color: {ACCENT};
    border: none;
    color: {ACCENT_TEXT};
    font-size: 17px;
    font-weight: 700;
    padding: 16px 28px;
    border-radius: 14px;
}}
QPushButton#primary:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background-color: {ACCENT_PRESSED}; }}
QPushButton#primary:disabled {{ background-color: {BORDER}; color: {TEXT_DIM}; }}

QPushButton#secondary {{ font-size: 15px; padding: 12px 22px; border-radius: 12px; }}
QPushButton#big {{ font-size: 16px; padding: 15px 26px; border-radius: 14px; }}
QPushButton#link {{
    border: none; background: transparent; color: {ACCENT};
    text-decoration: underline; padding: 4px; font-weight: 500;
}}
QPushButton#link:hover {{ color: {ACCENT_HOVER}; }}
QPushButton#dashed {{
    border: 1px dashed {BORDER}; color: {ACCENT}; padding: 14px; border-radius: 14px;
}}
QPushButton#danger {{ border-color: {DANGER}; color: {DANGER}; }}
QPushButton#small {{ padding: 6px 14px; border-radius: 10px; font-size: 13px; }}
QPushButton#smallPrimary {{
    padding: 6px 14px; border-radius: 10px; font-size: 13px;
    background-color: {ACCENT}; color: {ACCENT_TEXT}; border: none;
}}

QLineEdit, QComboBox, QSpinBox, QDateEdit, QTextEdit, QPlainTextEdit {{
    background-color: {INPUT_BG};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 12px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_TEXT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus,
QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{
    image: url("{_pijl()}");
    width: 12px;
    height: 8px;
    margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_TEXT};
    color: {TEXT};
}}

QCheckBox {{ spacing: 10px; background: transparent; }}
QCheckBox::indicator {{
    width: 20px; height: 20px; border-radius: 5px;
    border: 1px solid {BORDER}; background: {INPUT_BG};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QMessageBox {{ background-color: {CARD}; }}
QMessageBox QLabel {{ color: {TEXT}; font-size: 14px; }}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 14px;
    top: -1px;
    background-color: {CARD};
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_DIM};
    padding: 10px 18px;
    font-weight: 600;
    border: none;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}

QProgressBar {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    max-height: 10px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 5px; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{
    background-color: {CARD}; color: {TEXT};
    border: 1px solid {BORDER}; padding: 6px; border-radius: 6px;
}}
"""


QSS = _build_qss()
