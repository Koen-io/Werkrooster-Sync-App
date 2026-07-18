"""Modern dark theme (QSS) and shift-type colors."""
from __future__ import annotations

from ..core.models import ShiftType

ACCENT = "#6C7CFF"
ACCENT_HOVER = "#8593FF"
ACCENT_PRESSED = "#5563E8"
BG = "#0E1117"
CARD = "#161B26"
CARD_HOVER = "#1B2130"
BORDER = "#252C3D"
TEXT = "#E8EBF2"
TEXT_DIM = "#8B93A7"
DANGER = "#F26D6D"
OK = "#4FD1A5"

SHIFT_COLORS: dict[ShiftType, str] = {
    ShiftType.VRIJ: "#4FD1A5",
    ShiftType.OCHTEND: "#F5C15D",
    ShiftType.LAAT: "#F58E5D",
    ShiftType.NACHT: "#8B7CF6",
    ShiftType.DIENST: "#5DA8F5",
    ShiftType.AFSPRAAK: "#5DD5C4",
}

QSS = f"""
* {{
    font-family: "SF Pro Text", "Segoe UI Variable", "Segoe UI", -apple-system, sans-serif;
    outline: none;
}}
QMainWindow, QDialog {{
    background-color: {BG};
}}
QWidget {{
    color: {TEXT};
    font-size: 14px;
}}
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

QFrame#card {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 16px;
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
    background-color: {ACCENT};
    border: none;
    color: white;
    font-size: 16px;
    font-weight: 700;
    padding: 16px 28px;
    border-radius: 14px;
}}
QPushButton#primary:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background-color: {ACCENT_PRESSED}; }}
QPushButton#primary:disabled {{ background-color: {BORDER}; color: {TEXT_DIM}; }}

QPushButton#secondary {{
    font-size: 15px;
    padding: 14px 24px;
    border-radius: 14px;
}}
QPushButton#danger {{
    border-color: {DANGER};
    color: {DANGER};
}}
QPushButton#danger:hover {{ background-color: rgba(242, 109, 109, 0.12); }}

QLineEdit, QComboBox, QSpinBox {{
    background-color: {BG};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 12px;
    color: {TEXT};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {TEXT_DIM};
    margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background-color: {CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    selection-background-color: {ACCENT};
    color: {TEXT};
}}

QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{
    width: 20px; height: 20px;
    border-radius: 6px;
    border: 1px solid {BORDER};
    background-color: {BG};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    image: none;
}}

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
