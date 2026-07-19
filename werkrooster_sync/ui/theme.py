"""Palette-driven theming.

All colors live in a palette; :func:`apply_palette` swaps the active palette
and regenerates the QSS. Widgets read the module-level constants at
construction time, so build windows *after* applying a palette.

Palettes:
- ``donker``       — the original dark look
- ``glas-donker``  — liquid-glass dark: deep gradient, translucent cards
- ``glas-licht``   — liquid-glass light: airy gradient, frosted white cards
- ``apple``        — macOS classic: light grey, white cards, blue accent
"""
from __future__ import annotations

from ..core.models import ShiftType

#: Colors per shift type (consistent across palettes = brand language).
SHIFT_COLORS: dict[ShiftType, str] = {
    ShiftType.VRIJ: "#34C759",
    ShiftType.OCHTEND: "#FFB340",
    ShiftType.LAAT: "#FF7A45",
    ShiftType.NACHT: "#8B7CF6",
    ShiftType.DIENST: "#3E9BF0",
    ShiftType.AFSPRAAK: "#30C8C9",
    ShiftType.NEGEREN: "#8A8F9E",
}

PALETTES: dict[str, dict[str, str]] = {
    "donker": {
        "ACCENT": "#6C7CFF",
        "ACCENT_HOVER": "#8593FF",
        "ACCENT_PRESSED": "#5563E8",
        "BG": "#0E1117",
        "WINDOW_BG": "#0E1117",
        "CARD": "#161B26",
        "CARD_HOVER": "#1B2130",
        "BORDER": "#252C3D",
        "INPUT_BG": "#0E1117",
        "TEXT": "#E8EBF2",
        "TEXT_DIM": "#8B93A7",
        "DANGER": "#F26D6D",
        "OK": "#4FD1A5",
        "WARN": "#F5C15D",
        "SWITCH_OFF": "#3A4256",
        "STEP_BG": "#1A2030",
        "SHADOW": "transparent",
    },
    "glas-donker": {
        "ACCENT": "#7C8CFF",
        "ACCENT_HOVER": "#93A0FF",
        "ACCENT_PRESSED": "#6474F0",
        "BG": "#0B0E1A",
        "WINDOW_BG": (
            "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
            "stop:0 #10142B, stop:0.5 #0B0E1A, stop:1 #1A1030)"
        ),
        "CARD": "rgba(255, 255, 255, 0.055)",
        "CARD_HOVER": "rgba(255, 255, 255, 0.09)",
        "BORDER": "rgba(255, 255, 255, 0.13)",
        "INPUT_BG": "rgba(0, 0, 0, 0.35)",
        "TEXT": "#F2F4FA",
        "TEXT_DIM": "#9AA2B8",
        "DANGER": "#FF6B6B",
        "OK": "#34C759",
        "WARN": "#FFC64D",
        "SWITCH_OFF": "rgba(255, 255, 255, 0.18)",
        "STEP_BG": "rgba(255, 255, 255, 0.08)",
        "SHADOW": "transparent",
    },
    "glas-licht": {
        "ACCENT": "#4A5BFF",
        "ACCENT_HOVER": "#6272FF",
        "ACCENT_PRESSED": "#3A49E0",
        "BG": "#EAEDF6",
        "WINDOW_BG": (
            "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
            "stop:0 #EDF1FB, stop:0.5 #E7EAF5, stop:1 #F0EAF8)"
        ),
        "CARD": "rgba(255, 255, 255, 0.68)",
        "CARD_HOVER": "rgba(255, 255, 255, 0.85)",
        "BORDER": "rgba(20, 30, 60, 0.10)",
        "INPUT_BG": "rgba(255, 255, 255, 0.85)",
        "TEXT": "#1C2333",
        "TEXT_DIM": "#6A7286",
        "DANGER": "#E5484D",
        "OK": "#34C759",
        "WARN": "#C77D0A",
        "SWITCH_OFF": "rgba(20, 30, 60, 0.18)",
        "STEP_BG": "rgba(255, 255, 255, 0.80)",
        "SHADOW": "rgba(30, 40, 80, 0.06)",
    },
    "apple": {
        "ACCENT": "#007AFF",
        "ACCENT_HOVER": "#2E90FF",
        "ACCENT_PRESSED": "#0063D1",
        "BG": "#F5F5F7",
        "WINDOW_BG": "#F5F5F7",
        "CARD": "#FFFFFF",
        "CARD_HOVER": "#F9F9FB",
        "BORDER": "#E2E2E8",
        "INPUT_BG": "#FFFFFF",
        "TEXT": "#1D1D1F",
        "TEXT_DIM": "#7A7A82",
        "DANGER": "#FF3B30",
        "OK": "#34C759",
        "WARN": "#B25000",
        "SWITCH_OFF": "#D6D6DC",
        "STEP_BG": "#FFFFFF",
        "SHADOW": "rgba(0, 0, 0, 0.04)",
    },
}

#: The active palette name; changed via apply_palette().
ACTIVE = "glas-donker"

# Module-level color constants, filled in by apply_palette() below.
ACCENT = ACCENT_HOVER = ACCENT_PRESSED = ""
BG = WINDOW_BG = CARD = CARD_HOVER = BORDER = INPUT_BG = ""
TEXT = TEXT_DIM = DANGER = OK = WARN = SWITCH_OFF = STEP_BG = SHADOW = ""
QSS = ""


def _build_qss() -> str:
    return f"""
* {{
    font-family: "SF Pro Text", "Segoe UI Variable", "Segoe UI", -apple-system, sans-serif;
    outline: none;
}}
QMainWindow, QDialog {{
    background: {WINDOW_BG};
}}
QWidget {{
    color: {TEXT};
    font-size: 14px;
}}
QLabel {{ background: transparent; }}
QLabel#appTitle {{
    font-size: 26px;
    font-weight: 700;
    color: {TEXT};
}}
QLabel#appSubtitle {{
    font-size: 14px;
    color: {TEXT_DIM};
}}
QLabel#sectionTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {TEXT_DIM};
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QLabel#statusOk {{ color: {OK}; }}
QLabel#statusError {{ color: {DANGER}; }}
QLabel#statusDim {{ color: {TEXT_DIM}; }}
QLabel#statusWarn {{ color: {WARN}; }}

QFrame#card {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 16px;
}}
QFrame#stepHeader {{
    background-color: {STEP_BG};
    border: 1px solid {BORDER};
    border-left: 4px solid {ACCENT};
    border-radius: 12px;
}}
QFrame#warnBox {{
    background-color: rgba(245, 193, 93, 0.12);
    border: 1px solid rgba(245, 193, 93, 0.45);
    border-radius: 10px;
}}
QFrame#warnBox QLabel {{
    color: {WARN};
    background: transparent;
    border: none;
}}
QFrame#dangerBox {{
    background-color: rgba(229, 72, 77, 0.07);
    border: 1px solid rgba(229, 72, 77, 0.35);
    border-radius: 10px;
}}

QPushButton {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 10px 20px;
    font-weight: 600;
    color: {TEXT};
}}
QPushButton:hover {{ background-color: {CARD_HOVER}; border-color: {ACCENT}; }}
QPushButton:pressed {{ background-color: {BORDER}; }}
QPushButton:disabled {{ color: {TEXT_DIM}; border-color: {BORDER}; }}

QPushButton#primary {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {ACCENT_HOVER}, stop:1 {ACCENT});
    border: none;
    color: white;
    font-size: 16px;
    font-weight: 700;
    padding: 16px 28px;
    border-radius: 14px;
}}
QPushButton#primary:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background-color: {ACCENT_PRESSED}; }}
QPushButton#primary:disabled {{ background: {BORDER}; color: {TEXT_DIM}; }}

QPushButton#secondary {{
    font-size: 15px;
    padding: 14px 24px;
    border-radius: 14px;
}}
QPushButton#danger {{
    border-color: {DANGER};
    color: {DANGER};
}}
QPushButton#danger:hover {{ background-color: rgba(229, 72, 77, 0.12); }}

QLineEdit, QComboBox, QSpinBox, QDateEdit {{
    background-color: {INPUT_BG};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 12px;
    color: {TEXT};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {TEXT_DIM};
    margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background-color: {CARD if ACTIVE == "donker" else "#FFFFFF" if ACTIVE in ("glas-licht", "apple") else "#1A1F33"};
    border: 1px solid {BORDER};
    border-radius: 10px;
    selection-background-color: {ACCENT};
    selection-color: white;
    color: {TEXT};
}}
QDateEdit::drop-down {{ border: none; width: 24px; }}
QCalendarWidget QWidget {{ background-color: {CARD}; color: {TEXT}; }}
QCalendarWidget QAbstractItemView {{
    background-color: {CARD};
    selection-background-color: {ACCENT};
    selection-color: white;
}}

QMessageBox {{ background-color: {CARD}; }}
QMessageBox QLabel {{ color: {TEXT}; font-size: 14px; }}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 12px;
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

QListWidget, QTableWidget {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 6px;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 8px;
}}
QListWidget::item:selected {{ background-color: {CARD_HOVER}; color: {TEXT}; }}

QProgressBar {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    height: 10px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 7px; }}

QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {TEXT_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

QToolTip {{
    background-color: {CARD};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 6px;
    border-radius: 6px;
}}
"""


def apply_palette(name: str) -> None:
    """Activate a palette and regenerate the QSS. Build windows afterwards."""
    global ACTIVE, QSS
    palette = PALETTES.get(name) or PALETTES["donker"]
    ACTIVE = name if name in PALETTES else "donker"
    for key, value in palette.items():
        globals()[key] = value
    QSS = _build_qss()


apply_palette(ACTIVE)
