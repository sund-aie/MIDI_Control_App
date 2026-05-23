"""
PandaMINI Core Engine - Custom Control Widgets
VU Meter, Faders, Rotary Dials, and Drum Pads
"""
import numpy as np
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame
from PySide6.QtCore import Qt, QRectF, Signal, QTimer, QPointF
from PySide6.QtGui import QPainter, QLinearGradient, QColor, QPen, QBrush, QPainterPath, QConicalGradient


class VUMeterWidget(QWidget):
    """8-segment LED VU meter with green-cyan to red transition."""
    
    SEGMENT_COUNT = 8
    
    # Colors
    COLOR_LOW = QColor(32, 226, 145)  # Emerald Mint
    COLOR_MID = QColor(0, 240, 255)   # Cyan
    COLOR_HIGH = QColor(255, 191, 0)  # Liquid Amber
    COLOR_PEAK = QColor(255, 80, 80)  # Error Red
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(48)
        self.setMaximumWidth(64)
        self._level = 0.0
        self._peak_level = 0.0
    
    def set_level(self, level: float) -> None:
        """Set VU meter level (0.0 to 1.0)."""
        self._level = max(0.0, min(1.0, level))
        if self._level > self._peak_level:
            self._peak_level = self._level
        self.update()
    
    def paintEvent(self, event) -> None:
        """Render VU meter segments."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        segment_height = (self.height() - 8) / self.SEGMENT_COUNT
        
        for i in range(self.SEGMENT_COUNT):
            # Calculate segment position (bottom to top)
            y = 4 + (self.SEGMENT_COUNT - 1 - i) * segment_height
            
            # Determine if segment should be lit
            threshold = i / self.SEGMENT_COUNT
            is_lit = self._level >= threshold
            
            # Get segment color based on position
            if i >= 7:
                color = self.COLOR_PEAK
            elif i >= 5:
                color = self.COLOR_HIGH
            elif i >= 3:
                color = self.COLOR_MID
            else:
                color = self.COLOR_LOW
            
            # Draw segment background (off state)
            bg_rect = QRectF(4, y, self.width() - 8, segment_height - 2)
            bg_color = QColor(color)
            bg_color.setAlpha(30)
            painter.fillRect(bg_rect, QBrush(bg_color))
            
            # Draw lit segment
            if is_lit:
                lit_rect = QRectF(6, y + 1, self.width() - 12, segment_height - 4)
                color.setAlpha(200)
                painter.fillRect(lit_rect, QBrush(color))
                
                # Add glow effect
                glow_pen = QPen(color, 1)
                painter.setPen(glow_pen)
                painter.drawRoundedRect(lit_rect, 2, 2)


class FaderWidget(QWidget):
    """Vertical fader with translucent thumb controller."""
    
    value_changed = Signal(float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(32)
        self.setMaximumWidth(48)
        self._value = 0.5
        self._dragging = False
    
    def set_value(self, value: float) -> None:
        """Set fader value (0.0 to 1.0)."""
        self._value = max(0.0, min(1.0, value))
        self.update()
    
    def get_value(self) -> float:
        """Get current fader value."""
        return self._value
    
    def mousePressEvent(self, event) -> None:
        """Start dragging fader."""
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._update_value_from_pos(event.y())
    
    def mouseMoveEvent(self, event) -> None:
        """Drag fader."""
        if self._dragging:
            self._update_value_from_pos(event.y())
    
    def mouseReleaseEvent(self, event) -> None:
        """Stop dragging."""
        self._dragging = False
    
    def _update_value_from_pos(self, y: int) -> None:
        """Update value based on mouse Y position."""
        track_height = self.height() - 40
        thumb_y = y - 20
        value = 1.0 - (thumb_y / track_height)
        self._value = max(0.0, min(1.0, value))
        self.value_changed.emit(self._value)
        self.update()
    
    def paintEvent(self, event) -> None:
        """Render fader track and thumb."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw track
        track_rect = QRectF(self.width() // 2 - 2, 20, 4, self.height() - 40)
        track_gradient = QLinearGradient(0, 0, 0, self.height())
        track_gradient.setColorAt(0, QColor(0, 0, 0, 100))
        track_gradient.setColorAt(0.5, QColor(30, 30, 36, 150))
        track_gradient.setColorAt(1, QColor(0, 0, 0, 100))
        painter.fillRect(track_rect, QBrush(track_gradient))
        
        # Draw thumb
        thumb_y = 20 + (1.0 - self._value) * (self.height() - 40)
        thumb_rect = QRectF(self.width() // 2 - 12, thumb_y - 8, 24, 16)
        
        thumb_gradient = QLinearGradient(0, thumb_y, 0, thumb_y + 16)
        thumb_gradient.setColorAt(0, QColor(255, 255, 255, 80))
        thumb_gradient.setColorAt(0.5, QColor(255, 255, 255, 40))
        thumb_gradient.setColorAt(1, QColor(0, 0, 0, 80))
        
        painter.fillRoundedRect(thumb_rect, 3, 3, QBrush(thumb_gradient))
        
        # Thumb border
        border_pen = QPen(QColor(255, 255, 255, 60), 1)
        painter.setPen(border_pen)
        painter.drawRoundedRect(thumb_rect, 3, 3)


class RotaryDialWidget(QWidget):
    """Rotary dial with conic gradient and tick mark indicator."""
    
    value_changed = Signal(float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(48, 48)
        self.setMaximumSize(64, 64)
        self._value = 0.5
        self._dragging = False
    
    def set_value(self, value: float) -> None:
        """Set dial value (0.0 to 1.0)."""
        self._value = max(0.0, min(1.0, value))
        self.update()
    
    def get_value(self) -> float:
        """Get current dial value."""
        return self._value
    
    def mousePressEvent(self, event) -> None:
        """Start dragging dial."""
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._last_y = event.y()
    
    def mouseMoveEvent(self, event) -> None:
        """Drag dial vertically."""
        if self._dragging:
            delta = self._last_y - event.y()
            self._value = max(0.0, min(1.0, self._value + delta / 100.0))
            self._last_y = event.y()
            self.value_changed.emit(self._value)
            self.update()
    
    def mouseReleaseEvent(self, event) -> None:
        """Stop dragging."""
        self._dragging = False
    
    def paintEvent(self, event) -> None:
        """Render rotary dial."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        center_x = self.width() // 2
        center_y = self.height() // 2
        radius = min(center_x, center_y) - 4
        
        # Draw conic gradient background
        dial_rect = QRectF(center_x - radius, center_y - radius, 
                          radius * 2, radius * 2)
        
        conic_gradient = QConicalGradient(center_x, center_y, 0)
        conic_gradient.setColorAt(0.0, QColor(52, 52, 59))
        conic_gradient.setColorAt(0.5, QColor(31, 31, 37))
        conic_gradient.setColorAt(1.0, QColor(52, 52, 59))
        
        painter.setBrush(QBrush(conic_gradient))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(dial_rect)
        
        # Draw border
        border_pen = QPen(QColor(255, 255, 255, 40), 1)
        painter.setPen(border_pen)
        painter.drawEllipse(dial_rect)
        
        # Draw indicator tick
        angle = self._value * 270 - 135  # Map 0-1 to -135 to 135 degrees
        angle_rad = np.radians(angle)
        
        tick_start_x = center_x + np.cos(angle_rad) * (radius - 8)
        tick_start_y = center_y + np.sin(angle_rad) * (radius - 8)
        tick_end_x = center_x + np.cos(angle_rad) * (radius - 3)
        tick_end_y = center_y + np.sin(angle_rad) * (radius - 3)
        
        tick_pen = QPen(QColor(0, 240, 255), 2)
        tick_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(tick_pen)
        painter.drawLine(QPointF(tick_start_x, tick_start_y), 
                        QPointF(tick_end_x, tick_end_y))


class DrumPadWidget(QWidget):
    """Silicone-style drum pad with drag-drop support."""
    
    pad_triggered = Signal(int)
    sample_dropped = Signal(int, str)  # pad_index, file_path
    
    def __init__(self, pad_index: int, parent=None):
        super().__init__(parent)
        self._pad_index = pad_index
        self._active = False
        self._has_sample = False
        
        # Colors from design spec
        self._color_inactive = QColor(255, 255, 255, 20)
        self._color_active = QColor(255, 191, 0, 102)
        self._glow_color = QColor(255, 191, 0, 150)
        
        self.setAcceptDrops(True)
    
    def set_active(self, active: bool) -> None:
        """Set pad active state."""
        self._active = active
        self.update()
    
    def set_has_sample(self, has_sample: bool) -> None:
        """Set whether pad has a sample loaded."""
        self._has_sample = has_sample
        self.update()
    
    def mousePressEvent(self, event) -> None:
        """Trigger pad on click."""
        if event.button() == Qt.LeftButton:
            self._active = True
            self.pad_triggered.emit(self._pad_index)
            self.update()
    
    def mouseReleaseEvent(self, event) -> None:
        """Release pad."""
        self._active = False
        self.update()
    
    def dragEnterEvent(self, event) -> None:
        """Accept drag enter if it contains URLs."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def dropEvent(self, event) -> None:
        """Handle dropped audio file."""
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if file_path.lower().endswith(('.wav', '.aiff', '.mp3', '.flac')):
                self.sample_dropped.emit(self._pad_index, file_path)
                self._has_sample = True
                self.update()
    
    def paintEvent(self, event) -> None:
        """Render drum pad."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Pad rectangle
        pad_rect = QRectF(4, 4, self.width() - 8, self.height() - 8)
        
        if self._active:
            # Active state - amber tint with glow
            painter.fillRect(pad_rect, QBrush(self._color_active))
            
            # Glow effect
            glow_pen = QPen(self._glow_color, 2)
            painter.setPen(glow_pen)
            painter.drawRoundedRect(pad_rect, 8, 8)
            
            # Inner highlight
            inner_rect = QRectF(8, 8, self.width() - 16, self.height() - 16)
            inner_color = QColor(255, 191, 0, 50)
            painter.fillRect(inner_rect, QBrush(inner_color))
        else:
            # Inactive state
            painter.fillRoundedRect(pad_rect, 8, 8, QBrush(self._color_inactive))
            
            # Border
            border_pen = QPen(QColor(255, 255, 255, 40), 1)
            painter.setPen(border_pen)
            painter.drawRoundedRect(pad_rect, 8, 8)
        
        # Sample indicator
        if self._has_sample:
            indicator_rect = QRectF(self.width() - 12, 4, 8, 8)
            indicator_color = QColor(32, 226, 145) if not self._active else QColor(255, 255, 255)
            painter.fillRoundedRect(indicator_rect, 2, 2, QBrush(indicator_color))
