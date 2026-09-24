"""Colours, stylesheet and the app icon."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

WINDOW = "#101114"
BODY = "#17181b"
BODY_EDGE = "#26282d"
PLATE = "#1d1e22"
PLATE_EDGE = "#2c2e34"
TEXT = "#ececee"
TEXT_DIM = "#8d9099"
TEXT_FAINT = "#5c5f67"
ACCENT = "#ffa62b"        # playing
ACCENT_SOFT = "#ffcf8a"
LEARN = "#3ec5ff"         # waiting for a controller hit
OK = "#40d98a"
DANGER = "#ff5d5d"
PAD = "#dedede"           # silicone pad with a sound
PAD_TEXT = "#1b1c1f"
PAD_EMPTY = "#24262b"
BUTTON = "#2b2c31"
BUTTON_EDGE = "#3a3c42"
KNOB = "#0c0c0d"
LED_OFF = "#4a1c1c"
LED_ON = "#ff3b30"
WHITE_KEY = "#f3f3f3"
BLACK_KEY = "#111214"

STYLESHEET = f"""
QMainWindow, QWidget#root {{ background: {WINDOW}; }}
QWidget {{ color: {TEXT}; font-size: 10pt; }}
QLabel#title {{ font-size: 14pt; font-weight: 600; }}
QLabel#dim {{ color: {TEXT_DIM}; }}
QLabel#banner {{
    background: #12384a; color: #dff5ff; border: 1px solid {LEARN};
    border-radius: 8px; padding: 8px 12px; font-size: 11pt;
}}
QLabel#hint {{
    background: #2a2412; color: #ffe7bf; border: 1px solid #6b5520;
    border-radius: 8px; padding: 8px 12px;
}}
QComboBox {{
    background: #1d1f24; border: 1px solid {BUTTON_EDGE}; border-radius: 6px;
    padding: 5px 10px; min-width: 190px;
}}
QComboBox:hover {{ border-color: #50535b; }}
QComboBox QAbstractItemView {{
    background: #1d1f24; border: 1px solid {BUTTON_EDGE}; selection-background-color: #34507a;
}}
QPushButton, QToolButton {{
    background: {BUTTON}; border: 1px solid {BUTTON_EDGE}; border-radius: 6px; padding: 6px 14px;
}}
QPushButton:hover, QToolButton:hover {{ background: #34363c; }}
QPushButton:pressed, QToolButton:pressed {{ background: #3d4047; }}
QPushButton#primary {{ background: #2d4f73; border-color: #3f6b99; }}
QPushButton#primary:hover {{ background: #355d87; }}
QPushButton#stop {{ background: #4a2226; border-color: #6d2f35; }}
QPushButton#stop:hover {{ background: #5a282d; }}
QToolButton#midi {{ border-radius: 14px; padding: 5px 14px; }}
QToolButton#midi::menu-indicator {{ image: none; width: 0; }}
QToolButton#help {{ border-radius: 12px; padding: 2px 8px; min-width: 10px; }}
QMenu {{ background: #1d1f24; border: 1px solid {BUTTON_EDGE}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 24px; border-radius: 4px; }}
QMenu::item:selected {{ background: #34507a; }}
QMenu::item:disabled {{ color: {TEXT_FAINT}; }}
QMenu::separator {{ height: 1px; background: {BUTTON_EDGE}; margin: 4px 8px; }}
QStatusBar {{ background: #0c0d0f; color: {TEXT_DIM}; }}
QStatusBar::item {{ border: none; }}
QToolTip {{ background: #24262b; color: {TEXT}; border: 1px solid {BUTTON_EDGE}; padding: 4px; }}
QSlider::groove:horizontal {{ height: 6px; background: #33353b; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 14px; margin: -5px 0; border-radius: 7px; }}
"""


def app_icon() -> QIcon:
    """Drawn at runtime: a dark tile with the 2×4 pad grid, one pad lit."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1f2126"))
        p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
        m = size * 0.14
        gap = size * 0.06
        w = (size - 2 * m - 3 * gap) / 4
        h = (size - 2 * m - gap) / 2
        for r in range(2):
            for c in range(4):
                lit = (r, c) == (0, 1)
                p.setBrush(QColor(ACCENT if lit else "#d9d9d9"))
                p.drawRoundedRect(QRectF(m + c * (w + gap), m + r * (h + gap), w, h), w * 0.2, w * 0.2)
        p.end()
        icon.addPixmap(pix)
    return icon
