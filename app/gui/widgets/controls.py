"""
PandaMINI Core Engine - Custom Control Widgets
VU Meter, Faders, Rotary Dials, and Drum Pads
"""
import numpy as np
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QDialog, QLabel, QPushButton, QSlider, QCheckBox, QComboBox, QFileDialog
from PySide6.QtCore import Qt, QRectF, Signal, QTimer, QPointF
from PySide6.QtGui import QPainter, QLinearGradient, QColor, QPen, QBrush, QPainterPath, QConicalGradient, QFont


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
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(thumb_gradient))
        painter.drawRoundedRect(thumb_rect, 3, 3)
        
        # Thumb border
        border_pen = QPen(QColor(255, 255, 255, 60), 1)
        painter.setPen(border_pen)
        painter.setBrush(Qt.NoBrush)
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
    """Silicone-style drum pad with drag-drop and custom settings support."""
    
    pad_triggered = Signal(int)
    pad_released = Signal(int)
    sample_dropped = Signal(int, str)  # pad_index, file_path
    pad_config_requested = Signal(int)
    
    def __init__(self, pad_index: int, parent=None):
        super().__init__(parent)
        self._pad_index = pad_index
        self._active = False
        self._has_sample = False
        self._sample_path = ""
        
        # Colors from design spec
        self._color_inactive = QColor(255, 255, 255, 12)
        self._color_active = QColor(255, 191, 0, 150)
        self._glow_color = QColor(255, 191, 0, 220)
        
        self.setAcceptDrops(True)
        
    def set_sample_path(self, path: str) -> None:
        """Set sample path and update state."""
        self._sample_path = path
        self._has_sample = bool(path)
        self.update()
    
    def set_active(self, active: bool) -> None:
        """Set pad active state."""
        self._active = active
        self.update()
    
    def set_has_sample(self, has_sample: bool) -> None:
        """Set whether pad has a sample loaded."""
        self._has_sample = has_sample
        self.update()
    
    def mousePressEvent(self, event) -> None:
        """Trigger pad on click — always plays (built-in sounds available)."""
        if event.button() == Qt.LeftButton:
            self._active = True
            self.pad_triggered.emit(self._pad_index)
            self.update()
    
    def mouseReleaseEvent(self, event) -> None:
        """Release pad."""
        if event.button() == Qt.LeftButton:
            self._active = False
            self.pad_released.emit(self._pad_index)
            self.update()
            
    def mouseDoubleClickEvent(self, event) -> None:
        """Open settings on double-click."""
        if event.button() == Qt.LeftButton:
            self.pad_config_requested.emit(self._pad_index)
            
    def contextMenuEvent(self, event) -> None:
        """Open settings on right-click."""
        self.pad_config_requested.emit(self._pad_index)
        event.accept()
    
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
                self._sample_path = file_path
                self._has_sample = True
                self.update()
    
    def paintEvent(self, event) -> None:
        """Render drum pad with physical silicone aesthetics."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Pad rectangle
        pad_rect = QRectF(4, 4, self.width() - 8, self.height() - 8)
        
        # Draw glossy pad body
        if self._active:
            # Active state - beautiful backlit glow
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(self._color_active))
            painter.drawRoundedRect(pad_rect, 10, 10)
            
            # Glow border
            glow_pen = QPen(self._glow_color, 2)
            painter.setPen(glow_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(pad_rect, 10, 10)
        else:
            # Inactive state - dark translucent silicone
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(self._color_inactive))
            painter.drawRoundedRect(pad_rect, 10, 10)
            
            # Subtly backlit if a sample is loaded, otherwise dim border
            if self._has_sample:
                border_pen = QPen(QColor(0, 240, 255, 60), 1.5)
            else:
                border_pen = QPen(QColor(255, 255, 255, 20), 1)
            painter.setPen(border_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(pad_rect, 10, 10)
            
        # Draw sample name in the center
        painter.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
        if self._has_sample:
            import os
            filename = os.path.basename(self._sample_path) if self._sample_path else f"Pad {self._pad_index + 1}"
            # Shorten if too long
            if len(filename) > 11:
                filename = filename[:9] + ".."
            
            painter.setPen(QColor(255, 255, 255, 220) if self._active else QColor(0, 240, 255, 200))
            painter.drawText(pad_rect, Qt.AlignCenter, filename)
        else:
            painter.setPen(QColor(185, 202, 203, 50))
            painter.drawText(pad_rect, Qt.AlignCenter, f"PAD {self._pad_index + 1}\n(Empty)")
        
        # Draw a small corner indicator for hover/edit actions
        indicator_rect = QRectF(self.width() - 14, 8, 6, 6)
        if self._has_sample:
            indicator_color = QColor(32, 226, 145) if not self._active else QColor(255, 255, 255)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(indicator_color))
            painter.drawRoundedRect(indicator_rect, 1.5, 1.5)


class PadConfigDialog(QDialog):
    """Sleek, transparent, glassmorphic Pad Configuration Dialog."""
    
    def __init__(self, pad_index: int, audio_engine, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(400, 420)
        
        self._pad_index = pad_index
        self._audio_engine = audio_engine
        
        # Query values from engine
        self._sample_path = self._audio_engine._pad_sample_paths.get(pad_index, "")
        self._volume = self._audio_engine._pad_volumes.get(pad_index, 1.0)
        self._mode = self._audio_engine._pad_modes.get(pad_index, "oneshot")
        self._route_mic = self._audio_engine._pad_route_mic.get(pad_index, True)
        self._route_mon = self._audio_engine._pad_route_mon.get(pad_index, True)
        
        self._setup_ui()
        
    def paintEvent(self, event) -> None:
        """Render absolute stunning custom glass container."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Outer card background
        bg_color = QColor(24, 24, 30, 245)
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        painter.fillPath(path, QBrush(bg_color))
        
        # High-tech glowing cyan border
        border_pen = QPen(QColor(0, 240, 255, 120), 2)
        painter.setPen(border_pen)
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 16, 16)
        
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Header title
        header = QHBoxLayout()
        title = QLabel(f"PAD {self._pad_index + 1} CONFIGURATION")
        title.setFont(QFont("Geist", 14, QFont.Bold))
        title.setStyleSheet("color: #00f0ff; letter-spacing: 0.05em;")
        header.addWidget(title)
        
        close_btn = QPushButton("×")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: rgba(255, 255, 255, 150);
                font-size: 20px;
                border: none;
            }
            QPushButton:hover {
                color: #ff5050;
            }
        """)
        close_btn.clicked.connect(self.reject)
        header.addWidget(close_btn)
        layout.addLayout(header)
        
        # Divider line
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("background-color: rgba(255, 255, 255, 20); height: 1px; border: none;")
        layout.addWidget(div)
        
        # File path field
        file_layout = QVBoxLayout()
        file_layout.setSpacing(6)
        file_label = QLabel("AUDIO SAMPLE SOURCE")
        file_label.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
        file_label.setStyleSheet("color: rgba(185, 202, 203, 0.6);")
        file_layout.addWidget(file_label)
        
        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        self.path_display = QLabel(self._sample_path if self._sample_path else "(No Sound Loaded)")
        self.path_display.setFont(QFont("JetBrains Mono", 9))
        self.path_display.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 80);
                border: 1px solid rgba(255, 255, 255, 12);
                border-radius: 6px;
                padding: 6px 10px;
                color: #dbfcff;
            }
        """)
        file_row.addWidget(self.path_display, 1)
        
        browse_btn = QPushButton("BROWSE")
        browse_btn.setFont(QFont("JetBrains Mono", 9, QFont.Bold))
        browse_btn.setCursor(Qt.PointingHandCursor)
        browse_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 240, 255, 30);
                border: 1px solid rgba(0, 240, 255, 100);
                border-radius: 6px;
                color: #00f0ff;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: rgba(0, 240, 255, 60);
            }
        """)
        browse_btn.clicked.connect(self._on_browse)
        file_row.addWidget(browse_btn)
        file_layout.addLayout(file_row)
        layout.addLayout(file_layout)
        
        # Volume slider
        vol_layout = QVBoxLayout()
        vol_layout.setSpacing(6)
        vol_header = QHBoxLayout()
        vol_label = QLabel("PAD VOLUME / GAIN")
        vol_label.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
        vol_label.setStyleSheet("color: rgba(185, 202, 203, 0.6);")
        vol_header.addWidget(vol_label)
        
        self.vol_value_label = QLabel(f"{int(self._volume * 100)}%")
        self.vol_value_label.setFont(QFont("JetBrains Mono", 9, QFont.Bold))
        self.vol_value_label.setStyleSheet("color: #00f0ff;")
        vol_header.addWidget(self.vol_value_label)
        vol_layout.addLayout(vol_header)
        
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(int(self._volume * 100))
        self.vol_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: rgba(255, 255, 255, 16);
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #00f0ff;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 14px;
                height: 14px;
                margin-top: -4px;
                margin-bottom: -4px;
                border-radius: 7px;
            }
        """)
        self.vol_slider.valueChanged.connect(self._on_vol_changed)
        vol_layout.addWidget(self.vol_slider)
        layout.addLayout(vol_layout)
        
        # Mode selector
        mode_layout = QVBoxLayout()
        mode_layout.setSpacing(6)
        mode_label = QLabel("PLAYBACK MODE")
        mode_label.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
        mode_label.setStyleSheet("color: rgba(185, 202, 203, 0.6);")
        mode_layout.addWidget(mode_label)
        
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("One-Shot (Play Entire File)", "oneshot")
        self.mode_combo.addItem("Gate (Play While Held)", "gate")
        self.mode_combo.addItem("Loop (Loop Continuously)", "loop")
        self.mode_combo.setStyleSheet("""
            QComboBox {
                background-color: rgba(0, 0, 0, 80);
                border: 1px solid rgba(255, 255, 255, 12);
                border-radius: 6px;
                padding: 6px 12px;
                color: #dbfcff;
                font-family: 'JetBrains Mono';
                font-size: 11px;
            }
            QComboBox QAbstractItemView {
                background-color: #1e1e24;
                border: 1px solid rgba(0, 240, 255, 100);
                color: #dbfcff;
                selection-background-color: rgba(0, 240, 255, 50);
            }
        """)
        # Select current mode
        idx = self.mode_combo.findData(self._mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        mode_layout.addWidget(self.mode_combo)
        layout.addLayout(mode_layout)
        
        # Routing checklist
        route_layout = QVBoxLayout()
        route_layout.setSpacing(8)
        route_label = QLabel("AUDIO ROUTING CHANNELS")
        route_label.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
        route_label.setStyleSheet("color: rgba(185, 202, 203, 0.6);")
        route_layout.addWidget(route_label)
        
        self.chk_mic = QCheckBox("Send to Discord / Mic Output (Virtual Cable)")
        self.chk_mic.setFont(QFont("JetBrains Mono", 9))
        self.chk_mic.setChecked(self._route_mic)
        self.chk_mic.setStyleSheet("""
            QCheckBox {
                color: #dbfcff;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                background-color: rgba(0, 0, 0, 80);
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 4px;
            }
            QCheckBox::indicator:checked {
                background-color: #00f0ff;
                border: 1px solid #00f0ff;
            }
        """)
        route_layout.addWidget(self.chk_mic)
        
        self.chk_mon = QCheckBox("Monitor in Headphones / Local Output")
        self.chk_mon.setFont(QFont("JetBrains Mono", 9))
        self.chk_mon.setChecked(self._route_mon)
        self.chk_mon.setStyleSheet("""
            QCheckBox {
                color: #dbfcff;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                background-color: rgba(0, 0, 0, 80);
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 4px;
            }
            QCheckBox::indicator:checked {
                background-color: #00f0ff;
                border: 1px solid #00f0ff;
            }
        """)
        route_layout.addWidget(self.chk_mon)
        layout.addLayout(route_layout)
        
        layout.addSpacing(4)
        
        # Save / Cancel Actions
        actions = QHBoxLayout()
        actions.setSpacing(12)
        
        cancel_btn = QPushButton("CANCEL")
        cancel_btn.setFont(QFont("JetBrains Mono", 10, QFont.Bold))
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 8px;
                color: rgba(255, 255, 255, 180);
                padding: 8px 16px;
            }
            QPushButton:hover {
                border-color: rgba(255, 255, 255, 80);
                color: #ffffff;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        actions.addWidget(cancel_btn)
        
        save_btn = QPushButton("SAVE CONFIG")
        save_btn.setFont(QFont("JetBrains Mono", 10, QFont.Bold))
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #00f0ff;
                border: none;
                border-radius: 8px;
                color: #121216;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #5effff;
            }
        """)
        save_btn.clicked.connect(self._on_save)
        actions.addWidget(save_btn)
        
        layout.addLayout(actions)
        
    def _on_vol_changed(self, val: int) -> None:
        self.vol_value_label.setText(f"{val}%")
        
    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Pad Sound Sample",
            "",
            "Audio Files (*.wav *.mp3 *.flac *.aiff)"
        )
        if path:
            self._sample_path = path
            self.path_display.setText(path)
            
    def _on_save(self) -> None:
        """Apply and save configurations to engine."""
        self._volume = self.vol_slider.value() / 100.0
        self._mode = self.mode_combo.currentData()
        self._route_mic = self.chk_mic.isChecked()
        self._route_mon = self.chk_mon.isChecked()
        
        # Apply changes to audio engine
        if self._sample_path:
            # Set path map synchronously to prevent async visual race condition
            self._audio_engine._pad_sample_paths[self._pad_index] = self._sample_path
            self._audio_engine.load_pad_sample(self._pad_index, self._sample_path)
            
        self._audio_engine.set_pad_volume(self._pad_index, self._volume)
        self._audio_engine.set_pad_mode(self._pad_index, self._mode)
        self._audio_engine.set_pad_routing(self._pad_index, self._route_mic, self._route_mon)
        
        self.accept()
