"""
PandaMINI Core Engine - Custom Keyboard Widget
3D perspective piano keyboard with visual feedback
"""
import numpy as np
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QPainter, QLinearGradient, QColor, QPen, QBrush, QPainterPath, QRadialGradient


class KeyboardWidget(QWidget):
    """
    Custom piano keyboard widget with 3D perspective rendering.
    Renders 25 keys (15 white, 10 black) spanning 2 octaves.
    """
    
    note_pressed = Signal(int, int)  # note, velocity
    note_released = Signal(int)
    
    # Key dimensions
    WHITE_KEY_WIDTH = 48
    WHITE_KEY_HEIGHT = 256
    BLACK_KEY_WIDTH = 32
    BLACK_KEY_HEIGHT = 160
    
    # Colors from design spec
    COLOR_WHITE_KEY_TOP = QColor(255, 255, 255, 51)
    COLOR_WHITE_KEY_BOTTOM = QColor(255, 255, 255, 12)
    COLOR_BLACK_KEY = QColor(10, 10, 15, 230)
    COLOR_ACTIVE_GLOW = QColor(0, 240, 255, 200)
    COLOR_ACTIVE_FILL = QColor(0, 240, 255, 51)
    COLOR_BORDER = QColor(255, 255, 255, 38)
    
    # MIDI note range
    START_NOTE = 48  # C3
    END_NOTE = 72    # C5
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(800, 280)
        self.setMaximumHeight(300)
        
        # Track active notes
        self._active_notes = set()
        self._pressed_keys = {}  # note -> (x, y) for mouse tracking
        
        # Pre-compute key positions
        self._white_keys = []  # List of (note, x, width)
        self._black_keys = []  # List of (note, x, width)
        self._compute_key_positions()
        
        # Oscilloscope data
        self._osc_phase = 0.0
        self._osc_data_1 = []
        self._osc_data_2 = []
    
    def _compute_key_positions(self) -> None:
        """Pre-compute positions for all keys."""
        white_notes = [0, 2, 4, 5, 7, 9, 11]  # Within octave
        black_notes = [1, 3, 6, 8, 10]  # Within octave
        
        white_key_x = 0
        octave_offset = 0
        
        for note in range(self.START_NOTE, self.END_NOTE + 1):
            octave = (note // 12) - 3
            note_in_octave = note % 12
            
            if note_in_octave in white_notes:
                self._white_keys.append((note, white_key_x, self.WHITE_KEY_WIDTH))
                white_key_x += self.WHITE_KEY_WIDTH + 2  # 2px gap
            elif note_in_octave in black_notes:
                # Position black key between white keys
                black_x = white_key_x - self.BLACK_KEY_WIDTH // 2 - 1
                self._black_keys.append((note, black_x, self.BLACK_KEY_WIDTH))
    
    def get_note_from_pos(self, x: int, y: int) -> tuple:
        """Get note and key type from mouse position."""
        # Check black keys first (they're on top)
        for note, key_x, key_width in self._black_keys:
            if key_x <= x <= key_x + key_width and y < self.BLACK_KEY_HEIGHT:
                return (note, 'black')
        
        # Check white keys
        for note, key_x, key_width in self._white_keys:
            if key_x <= x <= key_x + key_width and y < self.WHITE_KEY_HEIGHT:
                return (note, 'white')
        
        return (None, None)
    
    def mousePressEvent(self, event) -> None:
        """Handle mouse press on keyboard."""
        if event.button() == Qt.LeftButton:
            note, key_type = self.get_note_from_pos(event.x(), event.y())
            if note is not None:
                self._active_notes.add(note)
                self._pressed_keys[note] = (event.x(), event.y())
                self.note_pressed.emit(note, 100)  # Default velocity
                self.update()
    
    def mouseMoveEvent(self, event) -> None:
        """Handle mouse drag across keyboard."""
        if event.buttons() & Qt.LeftButton:
            note, key_type = self.get_note_from_pos(event.x(), event.y())
            if note is not None and note not in self._active_notes:
                self._active_notes.add(note)
                self._pressed_keys[note] = (event.x(), event.y())
                self.note_pressed.emit(note, 100)
                self.update()
            elif note is None:
                # Check if we should release any notes
                for pressed_note in list(self._pressed_keys.keys()):
                    if pressed_note not in self._active_notes:
                        continue
                    # Simple check - if mouse moved far from original position
                    orig_x, orig_y = self._pressed_keys[pressed_note]
                    if abs(event.x() - orig_x) > self.WHITE_KEY_WIDTH // 2:
                        self._active_notes.discard(pressed_note)
                        del self._pressed_keys[pressed_note]
                        self.note_released.emit(pressed_note)
                        self.update()
    
    def mouseReleaseEvent(self, event) -> None:
        """Handle mouse release."""
        note, _ = self.get_note_from_pos(event.x(), event.y())
        
        # Release all currently active notes
        for pressed_note in list(self._active_notes):
            self._active_notes.discard(pressed_note)
            if pressed_note in self._pressed_keys:
                del self._pressed_keys[pressed_note]
            self.note_released.emit(pressed_note)
        
        self.update()
    
    def leaveEvent(self, event) -> None:
        """Handle mouse leaving widget - release all notes."""
        for pressed_note in list(self._active_notes):
            self._active_notes.discard(pressed_note)
            if pressed_note in self._pressed_keys:
                del self._pressed_keys[pressed_note]
            self.note_released.emit(pressed_note)
        self.update()
    
    def paintEvent(self, event) -> None:
        """Render the keyboard with 3D perspective."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        # Draw background
        self._draw_background(painter)
        
        # Draw white keys
        for note, x, width in self._white_keys:
            is_active = note in self._active_notes
            self._draw_white_key(painter, x, self.WHITE_KEY_HEIGHT, width, is_active)
        
        # Draw black keys
        for note, x, width in self._black_keys:
            is_active = note in self._active_notes
            self._draw_black_key(painter, x, self.BLACK_KEY_HEIGHT, width, is_active)
        
        # Draw oscilloscope visualization
        self._draw_oscilloscope(painter)
    
    def _draw_background(self, painter: QPainter) -> None:
        """Draw keyboard background canvas."""
        bg_rect = QRectF(0, 0, self.width(), self.height())
        bg_gradient = QLinearGradient(0, 0, 0, self.height())
        bg_gradient.setColorAt(0, QColor(20, 20, 26, 200))
        bg_gradient.setColorAt(1, QColor(10, 10, 15, 230))
        painter.fillRect(bg_rect, QBrush(bg_gradient))
    
    def _draw_white_key(self, painter: QPainter, x: float, height: float, 
                        width: float, is_active: bool) -> None:
        """Draw a single white key with 3D perspective."""
        # Create key path with rounded bottom
        key_path = QPainterPath()
        key_path.moveTo(x, 0)
        key_path.lineTo(x + width, 0)
        key_path.lineTo(x + width, height - 10)
        key_path.quadTo(x + width, height, x + width // 2, height)
        key_path.quadTo(x, height, x, height - 10)
        key_path.closeSubpath()
        
        # Apply depression transform for active state
        if is_active:
            painter.save()
            painter.translate(0, 3)  # Shift down by 3 pixels
        
        # Draw key gradient (3D effect)
        key_gradient = QLinearGradient(x, 0, x, height)
        key_gradient.setColorAt(0, self.COLOR_WHITE_KEY_TOP)
        key_gradient.setColorAt(1, self.COLOR_WHITE_KEY_BOTTOM)
        painter.fillPath(key_path, QBrush(key_gradient))
        
        # Draw border
        border_pen = QPen(self.COLOR_BORDER, 1)
        painter.setPen(border_pen)
        painter.drawPath(key_path)
        
        # Draw active glow
        if is_active:
            self._draw_active_glow(painter, x, height, width)
        
        if is_active:
            painter.restore()
    
    def _draw_black_key(self, painter: QPainter, x: float, height: float,
                        width: float, is_active: bool) -> None:
        """Draw a single black key with 3D perspective."""
        # Create key path
        key_path = QPainterPath()
        key_path.moveTo(x, 0)
        key_path.lineTo(x + width, 0)
        key_path.lineTo(x + width, height)
        key_path.lineTo(x, height)
        key_path.closeSubpath()
        
        # Apply depression transform for active state
        if is_active:
            painter.save()
            painter.translate(0, 3)
        
        # Fill black key
        painter.fillPath(key_path, QBrush(self.COLOR_BLACK_KEY))
        
        # Draw border
        border_pen = QPen(QColor(255, 255, 255, 20), 1)
        painter.setPen(border_pen)
        painter.drawPath(key_path)
        
        # Draw active glow
        if is_active:
            glow_gradient = QRadialGradient(x + width // 2, height // 2, width)
            glow_gradient.setColorAt(0, QColor(0, 240, 255, 100))
            glow_gradient.setColorAt(1, QColor(0, 240, 255, 0))
            painter.fillPath(key_path, QBrush(glow_gradient))
        
        if is_active:
            painter.restore()
    
    def _draw_active_glow(self, painter: QPainter, x: float, height: float, 
                          width: float) -> None:
        """Draw neon cyan glow effect for active keys."""
        # Inner glow fill
        glow_gradient = QLinearGradient(x, 0, x, height)
        glow_gradient.setColorAt(0, self.COLOR_ACTIVE_FILL)
        glow_gradient.setColorAt(1, QColor(0, 240, 255, 20))
        
        glow_path = QPainterPath()
        glow_path.addRoundedRect(x + 2, 0, width - 4, height - 2, 2, 2)
        painter.fillPath(glow_path, QBrush(glow_gradient))
        
        # Edge glow
        glow_pen = QPen(self.COLOR_ACTIVE_GLOW, 2)
        glow_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(glow_pen)
        
        edge_path = QPainterPath()
        edge_path.moveTo(x + 2, height - 5)
        edge_path.lineTo(x + 2, 5)
        edge_path.lineTo(x + width - 2, 5)
        edge_path.lineTo(x + width - 2, height - 5)
        painter.drawPath(edge_path)
    
    def _draw_oscilloscope(self, painter: QPainter) -> None:
        """Draw oscilloscope visualization at bottom of keyboard."""
        painter.save()
        
        # Update phase
        self._osc_phase += 0.1
        if self._osc_phase > 360:
            self._osc_phase = 0
        
        # Generate sine wave paths
        width = self.width()
        height = self.height()
        
        # First wave (Cyan #00f0ff at 20% opacity)
        wave1_path = QPainterPath()
        wave1_path.moveTo(0, height - 40)
        
        for x in range(int(width)):
            y1 = height - 40 + np.sin((x / width) * 4 * np.pi + self._osc_phase * np.pi / 180) * 15
            if x == 0:
                wave1_path.moveTo(x, y1)
            else:
                wave1_path.lineTo(x, y1)
        
        wave1_pen = QPen(QColor(0, 240, 255, 51), 1.5)
        wave1_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(wave1_pen)
        painter.drawPath(wave1_path)
        
        # Second wave (Emerald Mint #20e291 at 20% opacity)
        wave2_path = QPainterPath()
        for x in range(int(width)):
            y2 = height - 30 + np.sin((x / width) * 4 * np.pi - self._osc_phase * np.pi / 180) * 10
            if x == 0:
                wave2_path.moveTo(x, y2)
            else:
                wave2_path.lineTo(x, y2)
        
        wave2_pen = QPen(QColor(32, 226, 145, 51), 1)
        wave2_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(wave2_pen)
        painter.drawPath(wave2_path)
        
        painter.restore()
    
    def trigger_note(self, note: int) -> None:
        """Programmatically trigger a note (for MIDI input)."""
        if self.START_NOTE <= note <= self.END_NOTE:
            self._active_notes.add(note)
            self.update()
    
    def release_note(self, note: int) -> None:
        """Programmatically release a note."""
        self._active_notes.discard(note)
        self.update()
    
    def all_notes_off(self) -> None:
        """Release all active notes."""
        self._active_notes.clear()
        self.update()
