"""One drum pad: shows its sound, lights up while playing, accepts any dropped file."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QTextOption
from PySide6.QtWidgets import QWidget

from app.gui import theme

MODE_TAGS = {"toggle": "ON/OFF", "hold": "HOLD", "loop": "LOOP"}


class PadWidget(QWidget):
    pressed = Signal(int)
    released = Signal(int)
    add_requested = Signal(int)          # empty pad clicked
    menu_requested = Signal(int, object)  # pad, global QPoint
    file_dropped = Signal(int, str)

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.name = ""
        self.mode = "oneshot"
        self.to_headphones = True
        self.to_mic = True
        self.loading = False
        self.error = ""
        self.playing = False
        self.progress = 0.0
        self.held = False          # mouse or hardware press
        self.learning = False
        self.learn_phase = 0.0
        self._drag_over = False
        self._mouse_down = False
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self.setToolTip("Click to play · Right-click for options · Drop any sound or video file here")

    # ── state setters ───────────────────────────────────────────

    def set_sound(self, name: str) -> None:
        self.name, self.loading, self.error = name, False, ""
        self.update()

    def set_loading(self) -> None:
        self.loading, self.error = True, ""
        self.update()

    def set_error(self, message: str) -> None:
        self.loading, self.error = False, message
        self.update()

    def set_options(self, mode: str, to_headphones: bool, to_mic: bool) -> None:
        self.mode, self.to_headphones, self.to_mic = mode, to_headphones, to_mic
        self.update()

    def set_playing(self, playing: bool, progress: float) -> None:
        if playing != self.playing or (playing and abs(progress - self.progress) > 0.004):
            self.playing, self.progress = playing, progress
            self.update()

    def set_held(self, held: bool) -> None:
        if held != self.held:
            self.held = held
            self.update()

    def set_learning(self, learning: bool, phase: float = 0.0) -> None:
        self.learning, self.learn_phase = learning, phase
        self.update()

    @property
    def has_sound(self) -> bool:
        return bool(self.name) and not self.loading

    # ── geometry helpers ────────────────────────────────────────

    def _body(self) -> QRectF:
        return QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)

    def _menu_rect(self) -> QRectF:
        r = self._body()
        s = max(18.0, min(r.width(), r.height()) * 0.2)
        return QRectF(r.right() - s - 4, r.top() + 4, s, s)

    # ── mouse / drag & drop ─────────────────────────────────────

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.RightButton:
            self.menu_requested.emit(self.index, e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton:
            return
        if self._menu_rect().contains(e.position()) and (self.has_sound or self.error):
            self.menu_requested.emit(self.index, e.globalPosition().toPoint())
            return
        if not self.has_sound:
            if not self.loading:
                self.add_requested.emit(self.index)
            return
        self._mouse_down = True
        self.set_held(True)
        self.pressed.emit(self.index)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self._mouse_down:
            self._mouse_down = False
            self.set_held(False)
            self.released.emit(self.index)

    def mouseMoveEvent(self, e) -> None:
        self.update()

    def leaveEvent(self, e) -> None:
        self.update()

    def dragEnterEvent(self, e) -> None:
        if any(u.isLocalFile() for u in e.mimeData().urls()):
            e.acceptProposedAction()
            self._drag_over = True
            self.update()

    def dragLeaveEvent(self, e) -> None:
        self._drag_over = False
        self.update()

    def dropEvent(self, e) -> None:
        self._drag_over = False
        self.update()
        for url in e.mimeData().urls():
            if url.isLocalFile():
                e.acceptProposedAction()
                self.file_dropped.emit(self.index, url.toLocalFile())
                return

    # ── painting ────────────────────────────────────────────────

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._body()
        radius = min(r.width(), r.height()) * 0.08
        base = min(r.width(), r.height())
        hover = self.underMouse()

        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)

        if self.has_sound or self.error:
            if self.playing:
                fill = QColor(theme.ACCENT)
            elif self.error:
                fill = QColor("#e7c9c9")
            else:
                fill = QColor(theme.PAD).lighter(104) if hover else QColor(theme.PAD)
            if self.held:
                fill = fill.darker(112)
            p.fillPath(path, fill)
            if self.playing and self.progress > 0:
                bar = QRectF(r.left(), r.bottom() - base * 0.06, r.width() * self.progress, base * 0.06)
                p.save()
                p.setClipPath(path)
                p.fillRect(bar, QColor(0, 0, 0, 70))
                p.restore()
            text_color = QColor(theme.PAD_TEXT)
        else:
            p.fillPath(path, QColor(theme.PAD_EMPTY).lighter(118) if hover else QColor(theme.PAD_EMPTY))
            text_color = QColor(theme.TEXT_DIM)

        # outline
        if self.learning:
            glow = QColor(theme.LEARN)
            glow.setAlphaF(0.55 + 0.45 * self.learn_phase)
            p.setPen(QPen(glow, max(3.0, base * 0.035)))
        elif self._drag_over:
            p.setPen(QPen(QColor(theme.LEARN), max(2.0, base * 0.025), Qt.DashLine))
        elif not (self.has_sound or self.error):
            p.setPen(QPen(QColor(theme.TEXT_FAINT), 1.4, Qt.DashLine))
        else:
            p.setPen(QPen(QColor(0, 0, 0, 90), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, radius, radius)

        pad_in = base * 0.08
        text_rect = r.adjusted(pad_in, pad_in + base * 0.12, -pad_in, -pad_in - base * 0.12)

        if self.learning:
            self._text(p, text_rect, "Hit this pad on\nyour controller", QColor(theme.LEARN) if not self.has_sound
                       else text_color, base * 0.1, bold=True)
        elif self._drag_over:
            self._text(p, text_rect, "Drop to use\nthis sound", QColor(theme.LEARN), base * 0.11, bold=True)
        elif self.loading:
            self._text(p, text_rect, "Loading…", QColor(theme.TEXT_DIM), base * 0.11)
        elif self.error:
            self._text(p, text_rect, self.error, QColor("#8a1f1f"), base * 0.085, bold=True)
        elif self.has_sound:
            self._text(p, text_rect, self.name, text_color, base * 0.115, bold=True)
        else:
            self._text(p, text_rect.adjusted(0, -base * 0.05, 0, 0), "+", QColor(theme.TEXT_DIM), base * 0.22)
            sub = QRectF(text_rect.left(), text_rect.center().y() + base * 0.06, text_rect.width(), base * 0.3)
            self._text(p, sub, "Add sound", QColor(theme.TEXT_DIM), base * 0.09, align=Qt.AlignHCenter | Qt.AlignTop)

        # small tags: play mode (top-left) and routing (bottom)
        if self.has_sound and not self.learning:
            tag_font = base * 0.075
            tag = MODE_TAGS.get(self.mode)
            if tag:
                at = QPointF(r.left() + pad_in * 0.8, r.top() + pad_in * 0.8)
                self._tag(p, at, tag, tag_font, self._menu_rect().left() - at.x() - 4)
            if not self.to_headphones and not self.to_mic:
                route = "MUTED"
            elif not self.to_headphones:
                route = "NO HEADPHONES"
            elif not self.to_mic:
                route = "NO MIC"
            else:
                route = ""
            if route:
                self._text(p, QRectF(r.left(), r.bottom() - base * 0.2, r.width(), base * 0.16),
                           route, QColor(150, 20, 20) if route == "MUTED" else QColor(0, 0, 0, 150),
                           base * 0.07, bold=True)

        # options button
        if self.has_sound or self.error:
            m = self._menu_rect()
            hot = hover and m.contains(self.mapFromGlobal(self.cursor().pos()).toPointF())
            p.setPen(QPen(QColor(0, 0, 0, 60), 1))
            p.setBrush(QColor("#ffffff") if hot else QColor("#f4f4f4"))
            p.drawEllipse(m)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 190))
            d = m.width() * 0.11
            for k in (-1, 0, 1):
                p.drawEllipse(QPointF(m.center().x() + k * m.width() * 0.24, m.center().y()), d, d)
        p.end()

    def _text(self, p: QPainter, rect: QRectF, text: str, color: QColor, px: float,
              bold: bool = False, align=Qt.AlignCenter) -> None:
        font = QFont(self.font())
        font.setPixelSize(max(9, int(px)))
        font.setBold(bold)
        p.setFont(font)
        p.setPen(color)
        metrics = QFontMetricsF(font)
        lines = _wrap(text, metrics, rect.width(), max(1, int(rect.height() // metrics.lineSpacing())))
        option = QTextOption(align)
        option.setWrapMode(QTextOption.NoWrap)
        p.drawText(rect, "\n".join(lines), option)

    def _tag(self, p: QPainter, at: QPointF, text: str, px: float, max_w: float) -> None:
        font = QFont(self.font())
        font.setPixelSize(max(8, int(px)))
        font.setBold(True)
        metrics = QFontMetricsF(font)
        if max_w < metrics.horizontalAdvance(text) + px * 0.9:
            return                              # no room: never cover the options button
        w = metrics.horizontalAdvance(text) + px * 0.9
        rect = QRectF(at.x(), at.y(), w, metrics.height() + px * 0.2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRoundedRect(rect, rect.height() * 0.3, rect.height() * 0.3)
        p.setFont(font)
        p.setPen(QColor("#ffffff"))
        p.drawText(rect, Qt.AlignCenter, text)


def _wrap(text: str, metrics: QFontMetricsF, width: float, max_lines: int) -> list:
    """Word-wrap into at most max_lines lines, eliding the last one."""
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if metrics.horizontalAdvance(candidate) <= width or not line:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1] + " …"
    return [metrics.elidedText(line, Qt.ElideRight, width) for line in lines]
