"""The 25-key keyboard (C to C), scaled to fill its area. Click or drag to play."""
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.gui import theme
from app.midi.bindings import note_name

KEY_COUNT = 25
WHITE_STEPS = (0, 2, 4, 5, 7, 9, 11)


class KeyboardWidget(QWidget):
    note_pressed = Signal(int, int)   # note, velocity
    note_released = Signal(int)

    def __init__(self, base_note: int = 48, parent=None):
        super().__init__(parent)
        self.base_note = base_note
        self._active = set()        # notes lit by MIDI
        self._mouse_note = None
        self.setMouseTracking(False)
        self.setCursor(Qt.PointingHandCursor)

    # ── public ──────────────────────────────────────────────────

    def set_base_note(self, base_note: int) -> None:
        self.base_note = base_note
        self.update()

    def note_range(self) -> range:
        return range(self.base_note, self.base_note + KEY_COUNT)

    def set_note_active(self, note: int, active: bool) -> None:
        if active:
            self._active.add(note)
        else:
            self._active.discard(note)
        self.update()

    def clear(self) -> None:
        self._active.clear()
        self.update()

    # ── layout ──────────────────────────────────────────────────

    def _keys(self):
        """[(note, rect, is_black)] white keys first, then black keys (drawn on top)."""
        w, h = self.width(), self.height()
        notes = list(self.note_range())
        whites = [n for n in notes if n % 12 in WHITE_STEPS]
        kw = w / len(whites)
        white_rects, black_rects = [], []
        x = 0.0
        for n in notes:
            if n % 12 in WHITE_STEPS:
                white_rects.append((n, QRectF(x, 0, kw, h), False))
                x += kw
            else:
                bw = kw * 0.58
                black_rects.append((n, QRectF(x - bw / 2, 0, bw, h * 0.6), True))
        return white_rects + black_rects

    def _note_at(self, pos):
        keys = self._keys()
        for n, rect, black in reversed(keys):  # black keys first
            if black and rect.contains(pos):
                return n
        for n, rect, black in keys:
            if not black and rect.contains(pos):
                return n
        return None

    # ── mouse ───────────────────────────────────────────────────

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._mouse_to(self._note_at(e.position()))

    def mouseMoveEvent(self, e) -> None:
        if e.buttons() & Qt.LeftButton:
            self._mouse_to(self._note_at(e.position()))

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._mouse_to(None)

    def _mouse_to(self, note) -> None:
        if note == self._mouse_note:
            return
        if self._mouse_note is not None:
            self.note_released.emit(self._mouse_note)
        self._mouse_note = note
        if note is not None:
            self.note_pressed.emit(note, 100)
        self.update()

    # ── painting ────────────────────────────────────────────────

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        lit = self._active | ({self._mouse_note} if self._mouse_note is not None else set())
        font = QFont(self.font())
        for n, rect, black in self._keys():
            on = n in lit
            r = rect.adjusted(1, 0, -1, -1) if not black else rect
            radius = r.width() * 0.08
            if black:
                p.setPen(QPen(QColor("#000000"), 1))
                p.setBrush(QColor(theme.ACCENT) if on else QColor(theme.BLACK_KEY))
                p.drawRoundedRect(r, radius, radius)
                if not on:
                    p.fillRect(QRectF(r.left() + r.width() * 0.18, r.top(), r.width() * 0.64, r.height() * 0.9),
                               QColor(255, 255, 255, 14))
            else:
                p.setPen(QPen(QColor("#9d9fa5"), 1))
                p.setBrush(QColor(theme.ACCENT) if on else QColor(theme.WHITE_KEY))
                p.drawRoundedRect(r, radius, radius)
                if n % 12 == 0:
                    font.setPixelSize(max(8, int(r.width() * 0.22)))
                    p.setFont(font)
                    p.setPen(QColor("#8a8c92"))
                    p.drawText(r.adjusted(0, 0, 0, -r.height() * 0.04), Qt.AlignHCenter | Qt.AlignBottom,
                               note_name(n))
        p.end()
