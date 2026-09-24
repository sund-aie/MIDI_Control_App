"""Knob, slider and small function button drawn like the Panda MINI's own controls."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.gui import theme


class _ValueControl(QWidget):
    """Shared behaviour: 0..1 value, drag / wheel to change, right-click to learn."""

    value_changed = Signal(float)       # user moved it on screen
    learn_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._drag_from = None
        self.learning = False
        self.setCursor(Qt.SizeVerCursor)

    def value(self) -> float:
        return self._value

    def set_value(self, value: float) -> None:
        value = min(1.0, max(0.0, float(value)))
        if abs(value - self._value) > 1e-4:
            self._value = value
            self.update()

    def set_learning(self, learning: bool) -> None:
        self.learning = learning
        self.update()

    def _user_set(self, value: float) -> None:
        old = self._value
        self.set_value(value)
        if self._value != old:
            self.value_changed.emit(self._value)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.RightButton:
            self.learn_requested.emit()
        elif e.button() == Qt.LeftButton:
            self._drag_from = (e.position().y(), self._value)
            self._press(e)

    def mouseMoveEvent(self, e) -> None:
        if self._drag_from is not None:
            self._drag(e)

    def mouseReleaseEvent(self, e) -> None:
        self._drag_from = None

    def wheelEvent(self, e) -> None:
        steps = e.angleDelta().y() / 120.0
        self._user_set(self._value + steps * 0.04)

    def _press(self, e) -> None:
        pass

    def _drag(self, e) -> None:
        y0, v0 = self._drag_from
        self._user_set(v0 + (y0 - e.position().y()) / 150.0)


class KnobWidget(_ValueControl):
    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        size = min(self.width(), self.height())
        c = QPointF(self.width() / 2, self.height() / 2)
        outer = size / 2 - 1
        body = outer * 0.74

        # dotted scale from MIN (-135°) to MAX (+135°), like the printed dots
        p.setPen(Qt.NoPen)
        for k in range(21):
            a = math.radians(-225 + k * 13.5)
            lit = k / 20 <= self._value + 1e-6
            p.setBrush(QColor(theme.ACCENT if lit and self._value > 0 else "#6c6f77"))
            r = outer * (0.055 if k % 5 else 0.075)
            p.drawEllipse(QPointF(c.x() + math.cos(a) * outer * 0.9, c.y() + math.sin(a) * outer * 0.9), r, r)

        p.setBrush(QColor(theme.KNOB))
        p.setPen(QPen(QColor(theme.LEARN) if self.learning else QColor("#2e3036"),
                      3 if self.learning else 1.5))
        p.drawEllipse(c, body, body)

        a = math.radians(-225 + self._value * 270)
        p.setPen(QPen(QColor("#f0f0f0"), max(2.0, size * 0.045), Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(c.x() + math.cos(a) * body * 0.25, c.y() + math.sin(a) * body * 0.25),
                   QPointF(c.x() + math.cos(a) * body * 0.88, c.y() + math.sin(a) * body * 0.88))
        p.end()


class SliderWidget(_ValueControl):
    """Vertical fader: slot, printed ticks on the left, black cap with a white line."""

    def _geometry(self):
        h = self.height()
        cap_h = max(12.0, h * 0.09)
        top, bottom = cap_h / 2 + 2, h - cap_h / 2 - 2
        return top, bottom, cap_h

    def _press(self, e) -> None:
        top, bottom, _ = self._geometry()
        self._user_set((bottom - e.position().y()) / max(1.0, bottom - top))
        self._drag_from = (e.position().y(), self._value)

    def _drag(self, e) -> None:
        top, bottom, _ = self._geometry()
        y0, v0 = self._drag_from
        self._user_set(v0 + (y0 - e.position().y()) / max(1.0, bottom - top))

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        top, bottom, cap_h = self._geometry()
        cx = w * 0.62

        # ticks
        p.setPen(QPen(QColor("#9a9da5"), 1.2))
        for k in range(11):
            y = top + (bottom - top) * k / 10
            length = w * (0.24 if k in (0, 5, 10) else 0.15)
            p.drawLine(QPointF(w * 0.08, y), QPointF(w * 0.08 + length, y))

        # slot
        slot_w = max(4.0, w * 0.09)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#050506"))
        p.drawRoundedRect(QRectF(cx - slot_w / 2, top - 2, slot_w, bottom - top + 4), slot_w / 2, slot_w / 2)

        # fill (level) inside the slot
        y = bottom - (bottom - top) * self._value
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(QRectF(cx - slot_w / 4, y, slot_w / 2, bottom - y), slot_w / 4, slot_w / 4)

        # cap
        cap_w = min(w * 0.7, cap_h * 2.4)
        cap = QRectF(cx - cap_w / 2, y - cap_h / 2, cap_w, cap_h)
        p.setBrush(QColor("#0d0d0f"))
        p.setPen(QPen(QColor(theme.LEARN) if self.learning else QColor("#3a3c42"), 3 if self.learning else 1))
        p.drawRoundedRect(cap, 3, 3)
        p.setPen(QPen(QColor("#f0f0f0"), max(1.5, cap_h * 0.12)))
        p.drawLine(QPointF(cap.left() + 3, cap.center().y()), QPointF(cap.right() - 3, cap.center().y()))
        p.end()


class FunctionButton(QWidget):
    """Small rubber button (CC MODE, BANK, arrows ...). Lights up on related MIDI."""

    clicked = Signal()

    def __init__(self, label: str, clickable: bool = False, tooltip: str = "", parent=None):
        super().__init__(parent)
        self.label = label
        self.clickable = clickable
        self.lit = False
        self._down = False
        if clickable:
            self.setCursor(Qt.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)

    def set_lit(self, lit: bool) -> None:
        if lit != self.lit:
            self.lit = lit
            self.update()

    def mousePressEvent(self, e) -> None:
        if self.clickable and e.button() == Qt.LeftButton:
            self._down = True
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if self._down:
            self._down = False
            self.update()
            if self.rect().contains(e.position().toPoint()):
                self.clicked.emit()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        fill = QColor(theme.BUTTON)
        if self.lit:
            fill = QColor("#5a4320")
        if self._down:
            fill = fill.lighter(130)
        p.setBrush(fill)
        p.setPen(QPen(QColor(theme.ACCENT) if self.lit else QColor(theme.BUTTON_EDGE), 1.2))
        p.drawRoundedRect(r, 4, 4)
        font = QFont(self.font())
        is_arrow = self.label in ("◀", "▶")
        font.setPixelSize(max(7, int(r.height() * (0.42 if is_arrow else 0.24))))
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(theme.ACCENT_SOFT if self.lit else "#d6d7db"))
        p.drawText(r, Qt.AlignCenter | Qt.TextWordWrap, self.label)
        p.end()
