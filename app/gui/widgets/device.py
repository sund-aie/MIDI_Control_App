"""
The on-screen Panda MINI. Every control sits where it is on the real device
(seen from the player's side):

  ┌───────────────────────────────────────────────────────────────────────┐
  │ logo           K1    K2    K3    K4     Pad 1  Pad 2  Pad 3  Pad 4    │
  │ [CC MODE][MOD]  ◯     ◯     ◯     ◯     [   ]  [   ]  [   ]  [   ]    │
  │ [BANK]  [PROG]  ║     ║     ║     ║     Pad 5  Pad 6  Pad 7  Pad 8    │
  │ [PITCH↓][PITCH↑]║     ║     ║     ║     [   ]  [   ]  [   ]  [   ]    │
  │ [◀]     [▶]     1     2     3     4                                   │
  │ ● ● ● ●                                                               │
  ├───────────────────────────────────────────────────────── Panda MINI ──┤
  │ 25 keys, C to C                                                       │
  └───────────────────────────────────────────────────────────────────────┘

Positions are in a fixed 1400×840 design space and scaled uniformly, so the
proportions match the hardware at any window size.
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.gui import theme
from app.gui.widgets.hardware import FunctionButton, KnobWidget, SliderWidget
from app.gui.widgets.keyboard import KeyboardWidget
from app.gui.widgets.pad import PadWidget

DESIGN_W, DESIGN_H = 1400.0, 840.0

PLATE = QRectF(22, 22, 1356, 446)
KEY_BED = QRectF(22, 478, 1356, 344)
KEYS = QRectF(46, 508, 1308, 304)
LOGO = QRectF(44, 38, 200, 44)

BUTTON_ROWS = (("CC MODE", "MOD"), ("BANK", "PROG"), ("PITCH DOWN", "PITCH UP"), ("◀", "▶"))
BUTTON_COLS = (44, 148)
BUTTON_TOPS = (98, 166, 234, 302)
BUTTON_SIZE = (96, 54)
LED_Y, LED_XS, LED_R = 402, (70, 118, 166, 214), 7

STRIP_CENTERS = (329, 435, 541, 647)
KNOB_TOP, KNOB_SIZE = 54, 84
SLIDER_TOP, SLIDER_H, SLIDER_W = 168, 236, 80

PAD_XS = (724, 886, 1048, 1210)
PAD_ROWS = (60, 268)
PAD_SIZE = (146, 170)
PAD_LABEL_H = 22


class DeviceWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(700, 420)
        self.scale = 1.0
        self.origin = QPointF(0, 0)
        self.leds = [False] * 4
        self.slider_captions = ["", "", "", ""]
        self.knob_captions = ["", "", "", ""]

        self.buttons = {}
        tips = {"◀": "Shift the on-screen keyboard down an octave",
                "▶": "Shift the on-screen keyboard up an octave"}
        for row in BUTTON_ROWS:
            for label in row:
                self.buttons[label] = FunctionButton(label, clickable=label in tips,
                                                     tooltip=tips.get(label, ""), parent=self)
        self.knobs = [KnobWidget(self) for _ in range(4)]
        self.sliders = [SliderWidget(self) for _ in range(4)]
        for i, w in enumerate(self.knobs):
            w.setToolTip(f"Knob {i + 1} · right-click to match it to your controller")
        self.pads = [PadWidget(i, self) for i in range(8)]
        self.keyboard = KeyboardWidget(parent=self)

    # ── geometry ────────────────────────────────────────────────

    def map_rect(self, r: QRectF) -> QRectF:
        s = self.scale
        return QRectF(self.origin.x() + r.x() * s, self.origin.y() + r.y() * s, r.width() * s, r.height() * s)

    def pad_rect(self, i: int) -> QRectF:
        return QRectF(PAD_XS[i % 4], PAD_ROWS[i // 4], *PAD_SIZE)

    def resizeEvent(self, e) -> None:
        s = min(self.width() / DESIGN_W, self.height() / DESIGN_H)
        self.scale = s
        self.origin = QPointF((self.width() - DESIGN_W * s) / 2, (self.height() - DESIGN_H * s) / 2)

        for r, row in enumerate(BUTTON_ROWS):
            for c, label in enumerate(row):
                rect = QRectF(BUTTON_COLS[c], BUTTON_TOPS[r], *BUTTON_SIZE)
                self.buttons[label].setGeometry(self.map_rect(rect).toRect())
        for i, cx in enumerate(STRIP_CENTERS):
            self.knobs[i].setGeometry(self.map_rect(QRectF(cx - KNOB_SIZE / 2, KNOB_TOP, KNOB_SIZE, KNOB_SIZE)).toRect())
            self.sliders[i].setGeometry(self.map_rect(QRectF(cx - SLIDER_W / 2, SLIDER_TOP, SLIDER_W, SLIDER_H)).toRect())
        for i, pad in enumerate(self.pads):
            pad.setGeometry(self.map_rect(self.pad_rect(i)).toRect())
        self.keyboard.setGeometry(self.map_rect(KEYS).toRect())

    # ── LEDs ────────────────────────────────────────────────────

    def set_led(self, i: int, on: bool) -> None:
        if self.leds[i] != on:
            self.leds[i] = on
            c = self.map_rect(QRectF(LED_XS[i] - LED_R * 2, LED_Y - LED_R * 2, LED_R * 4, LED_R * 4))
            self.update(c.toRect().adjusted(-2, -2, 2, 2))

    # ── painting ────────────────────────────────────────────────

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.scale

        body = self.map_rect(QRectF(0, 0, DESIGN_W, DESIGN_H))
        p.setPen(QPen(QColor(theme.BODY_EDGE), 1.5))
        p.setBrush(QColor(theme.BODY))
        p.drawRoundedRect(body, 30 * s, 30 * s)

        p.setPen(QPen(QColor(theme.PLATE_EDGE), 1.2))
        p.setBrush(QColor(theme.PLATE))
        p.drawRoundedRect(self.map_rect(PLATE), 18 * s, 18 * s)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#0e0f11"))
        p.drawRoundedRect(self.map_rect(KEY_BED), 14 * s, 14 * s)

        self._logo(p)
        self._labels(p)
        self._leds(p)
        p.end()

    def _font(self, px: float, bold: bool = False) -> QFont:
        f = QFont(self.font())
        f.setPixelSize(max(7, int(px * self.scale)))
        f.setBold(bold)
        return f

    def _logo(self, p: QPainter) -> None:
        r = self.map_rect(LOGO)
        s = self.scale
        tile = QRectF(r.left(), r.top() + (r.height() - 30 * s) / 2, 30 * s, 30 * s)
        p.setPen(Qt.NoPen)
        gap = 2.5 * s
        w, h = (tile.width() - 3 * gap) / 4, (tile.height() - gap) / 2
        for row in range(2):
            for col in range(4):
                p.setBrush(QColor(theme.ACCENT if (row, col) == (0, 1) else "#d9d9d9"))
                p.drawRoundedRect(QRectF(tile.left() + col * (w + gap), tile.top() + row * (h + gap), w, h),
                                  1.5 * s, 1.5 * s)
        p.setFont(self._font(19, bold=True))
        p.setPen(QColor("#f2f2f2"))
        p.drawText(r.adjusted(40 * s, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, "SOUNDBOARD")

    def _labels(self, p: QPainter) -> None:
        # "Pad N" printed above each pad, like on the device
        p.setFont(self._font(15))
        p.setPen(QColor("#d8d9dc"))
        for i in range(8):
            pr = self.pad_rect(i)
            p.drawText(self.map_rect(QRectF(pr.left(), pr.top() - PAD_LABEL_H - 2, pr.width(), PAD_LABEL_H)),
                       Qt.AlignCenter, f"Pad {i + 1}")

        # knob MIN/MAX, slider numbers and what each control does
        for i, cx in enumerate(STRIP_CENTERS):
            p.setFont(self._font(10, bold=True))
            p.setPen(QColor(theme.TEXT_DIM))
            y = KNOB_TOP + KNOB_SIZE + 1
            p.drawText(self.map_rect(QRectF(cx - 48, y, 40, 14)), Qt.AlignLeft | Qt.AlignVCenter, "MIN")
            p.drawText(self.map_rect(QRectF(cx + 8, y, 40, 14)), Qt.AlignRight | Qt.AlignVCenter, "MAX")
            if self.knob_captions[i]:
                p.drawText(self.map_rect(QRectF(cx - 53, KNOB_TOP - 18, 106, 14)), Qt.AlignCenter,
                           self.knob_captions[i])
            p.setFont(self._font(16, bold=True))
            p.setPen(QColor("#e6e6e8"))
            slot_x = cx - SLIDER_W / 2 + SLIDER_W * 0.62
            p.drawText(self.map_rect(QRectF(slot_x - 20, SLIDER_TOP + SLIDER_H + 2, 40, 22)), Qt.AlignCenter,
                       str(i + 1))
            if self.slider_captions[i]:
                font = self._font(10.5, bold=True)
                p.setFont(font)
                p.setPen(QColor(theme.TEXT_DIM))
                box = self.map_rect(QRectF(cx - 50, SLIDER_TOP + SLIDER_H + 25, 100, 16))
                p.drawText(box, Qt.AlignCenter,
                           QFontMetricsF(font).elidedText(self.slider_captions[i], Qt.ElideRight, box.width()))

        # model name between the panel and the keys
        p.setFont(self._font(17))
        p.setPen(QColor("#eeeeee"))
        p.drawText(self.map_rect(QRectF(KEYS.right() - 300, KEY_BED.top() + 3, 300, 26)),
                   Qt.AlignRight | Qt.AlignVCenter, "Panda MINI")

    def _leds(self, p: QPainter) -> None:
        s = self.scale
        for i, x in enumerate(LED_XS):
            c = QPointF(self.origin.x() + x * s, self.origin.y() + LED_Y * s)
            if self.leds[i]:
                glow = QColor(theme.LED_ON)
                glow.setAlpha(70)
                p.setPen(Qt.NoPen)
                p.setBrush(glow)
                p.drawEllipse(c, LED_R * 2 * s, LED_R * 2 * s)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.LED_ON if self.leds[i] else theme.LED_OFF))
            p.drawEllipse(c, LED_R * s, LED_R * s)
