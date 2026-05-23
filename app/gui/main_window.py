"""
PandaMINI Core Engine - Main Window
Frameless, transparent 3D glassmorphic desktop interface
"""
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QComboBox, QPushButton, QFrame, QSpacerItem, QSizePolicy
)
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QTimer, QPoint
from PySide6.QtGui import QPainter, QLinearGradient, QColor, QPen, QBrush, QPainterPath, QFont

from app.gui.widgets.keyboard import KeyboardWidget
from app.gui.widgets.controls import VUMeterWidget, FaderWidget, RotaryDialWidget, DrumPadWidget


class GlassPanel(QFrame):
    """Frosted glass panel with refractive edges."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)
    
    def paintEvent(self, event) -> None:
        """Render frosted glass effect."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Base color: rgba(30, 30, 36, 165)
        base_color = QColor(30, 30, 36, 165)
        
        # Draw rounded rect
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        
        # Fill base
        painter.fillPath(path, QBrush(base_color))
        
        # Top and left edge: white gradient pen rgba(255, 255, 255, 38)
        top_left_pen = QPen(QColor(255, 255, 255, 38), 1)
        painter.setPen(top_left_pen)
        
        # Draw top edge
        top_path = QPainterPath()
        top_path.moveTo(12, 1)
        top_path.lineTo(self.width() - 12, 1)
        painter.drawPath(top_path)
        
        # Draw left edge
        left_path = QPainterPath()
        left_path.moveTo(1, 12)
        left_path.lineTo(1, self.height() - 12)
        painter.drawPath(left_path)
        
        # Bottom and right edge: dark blend pen rgba(0, 0, 0, 64)
        bottom_right_pen = QPen(QColor(0, 0, 0, 64), 1)
        painter.setPen(bottom_right_pen)
        
        # Draw bottom edge
        bottom_path = QPainterPath()
        bottom_path.moveTo(12, self.height() - 1)
        bottom_path.lineTo(self.width() - 12, self.height() - 1)
        painter.drawPath(bottom_path)
        
        # Draw right edge
        right_path = QPainterPath()
        right_path.moveTo(self.width() - 1, 12)
        right_path.lineTo(self.width() - 1, self.height() - 12)
        painter.drawPath(right_path)


class MainWindow(QMainWindow):
    """Main application window with frameless glassmorphic design."""
    
    def __init__(self, audio_engine=None, midi_listener=None, config_manager=None):
        super().__init__()
        
        self._audio_engine = audio_engine
        self._midi_listener = midi_listener
        self._config_manager = config_manager
        
        # Window setup - Frameless and transparent
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Fixed dimensions
        self.setFixedSize(1280, 720)
        
        # Drag state
        self._dragging = False
        self._drag_start = QPoint()
        
        # Setup UI
        self._setup_ui()
        
        # Connect signals
        self._connect_signals()
        
        # VU meter update timer
        self._vu_timer = QTimer()
        self._vu_timer.timeout.connect(self._update_vu_meter)
        self._vu_timer.start(50)  # 20 Hz update rate
    
    def _setup_ui(self) -> None:
        """Build the complete UI structure."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Header (56px height)
        header = self._create_header()
        main_layout.addWidget(header)
        
        # Main body (flex-1)
        body = self._create_body()
        main_layout.addWidget(body, 1)
        
        # Footer (40px height)
        footer = self._create_footer()
        main_layout.addWidget(footer)
    
    def _create_header(self) -> GlassPanel:
        """Create application header with title and controls."""
        header = GlassPanel()
        header.setFixedHeight(56)
        header.setMinimumWidth(1280)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 8, 16, 8)
        layout.setSpacing(16)
        
        # Left side: Title and dropdowns
        left_group = QHBoxLayout()
        left_group.setSpacing(24)
        
        # Title label
        title_label = QLabel("PandaMINI // Core Engine")
        title_font = QFont("Geist", 20, QFont.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #dbfcff; letter-spacing: -0.02em;")
        left_group.addWidget(title_label)
        
        # Dropdowns container
        dropdown_layout = QHBoxLayout()
        dropdown_layout.setSpacing(12)
        
        # Soundboard Output dropdown
        sb_combo = QComboBox()
        sb_combo.setObjectName("soundboardOutput")
        sb_combo.setMinimumWidth(180)
        sb_combo.addItem("Soundboard Output")
        sb_combo.setStyleSheet(self._combo_style())
        dropdown_layout.addWidget(sb_combo)
        
        # Sampler Output dropdown
        sampler_combo = QComboBox()
        sampler_combo.setObjectName("samplerOutput")
        sampler_combo.setMinimumWidth(180)
        sampler_combo.addItem("Sampler Output")
        sampler_combo.setStyleSheet(self._combo_style())
        dropdown_layout.addWidget(sampler_combo)
        
        left_group.addLayout(dropdown_layout)
        left_group.addStretch()
        
        layout.addLayout(left_group)
        
        # Right side: Window controls
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(8)
        
        # Minimize button
        minimize_btn = QPushButton()
        minimize_btn.setFixedSize(32, 32)
        minimize_btn.setCursor(Qt.PointingHandCursor)
        minimize_btn.setStyleSheet(self._icon_button_style(False))
        minimize_btn.setText("−")
        minimize_btn.setFont(QFont("Arial", 16))
        minimize_btn.clicked.connect(self.showMinimized)
        controls_layout.addWidget(minimize_btn)
        
        # Close button
        close_btn = QPushButton()
        close_btn.setFixedSize(32, 32)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(self._icon_button_style(True))
        close_btn.setText("×")
        close_btn.setFont(QFont("Arial", 14, QFont.Bold))
        close_btn.clicked.connect(self.close)
        controls_layout.addWidget(close_btn)
        
        layout.addLayout(controls_layout)
        
        return header
    
    def _create_body(self) -> QWidget:
        """Create main body with navigation and panels."""
        body = QWidget()
        layout = QHBoxLayout(body)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        
        # Side Navigation Tray (96px width)
        nav_tray = self._create_nav_tray()
        layout.addWidget(nav_tray)
        
        # Left Panel - Keyboard Canvas (65% width)
        left_panel = self._create_keyboard_panel()
        layout.addWidget(left_panel, 18)  # ~65%
        
        # Right Panel - Control Tower (35% width)
        right_panel = self._create_control_panel()
        layout.addWidget(right_panel, 10)  # ~35%
        
        return body
    
    def _create_nav_tray(self) -> GlassPanel:
        """Create side navigation with tab buttons."""
        nav = GlassPanel()
        nav.setFixedWidth(96)
        layout = QVBoxLayout(nav)
        layout.setContentsMargins(0, 16, 0, 16)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignTop)
        
        # Navigation tabs
        tabs = [
            ("ENGINE", "settings_input_component", True),
            ("MIXER", "equalizer", False),
            ("SAMPLER", "mic_external_on", False),
            ("SEQUENCER", "reorder", False),
            ("FX", "blur_on", False),
        ]
        
        for i, (label, icon, active) in enumerate(tabs):
            btn = self._create_nav_button(label, icon, active, i == 0)
            layout.addWidget(btn)
        
        # Bottom icons
        layout.addStretch()
        
        settings_btn = self._create_icon_only_button("settings")
        layout.addWidget(settings_btn)
        
        terminal_btn = self._create_icon_only_button("terminal")
        layout.addWidget(terminal_btn)
        
        return nav
    
    def _create_nav_button(self, label: str, icon: str, has_icon: bool, active: bool) -> QPushButton:
        """Create a navigation tab button."""
        btn = QPushButton()
        btn.setFixedSize(80, 72)
        btn.setCursor(Qt.PointingHandCursor)
        
        if active:
            # Active state: highlighted background
            bg_color = "rgba(0, 240, 255, 51)"
            text_color = "#00f0ff"
            shadow = "inset 0 0 8px rgba(0, 240, 255, 0.4)"
        else:
            # Inactive state: 60% opacity
            bg_color = "transparent"
            text_color = "rgba(185, 202, 203, 0.6)"
            shadow = "none"
        
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_color};
                border-radius: 12px;
                color: {text_color};
                font-family: 'JetBrains Mono';
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 0.1em;
                box-shadow: {shadow};
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 20);
            }}
        """)
        
        # Button content layout
        content = QVBoxLayout(btn)
        content.setContentsMargins(0, 8, 0, 0)
        content.setSpacing(4)
        content.setAlignment(Qt.AlignCenter)
        
        # Icon placeholder (using text for now)
        icon_label = QLabel("⚙")
        icon_label.setStyleSheet(f"font-size: 24px; color: {text_color};")
        content.addWidget(icon_label)
        
        # Label
        label_widget = QLabel(label)
        label_widget.setStyleSheet(f"font-size: 10px; color: {text_color};")
        label_widget.setAlignment(Qt.AlignCenter)
        content.addWidget(label_widget)
        
        return btn
    
    def _create_icon_only_button(self, icon: str) -> QPushButton:
        """Create an icon-only button for bottom nav."""
        btn = QPushButton()
        btn.setFixedSize(48, 48)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border-radius: 8px;
                color: rgba(185, 202, 203, 0.4);
                font-size: 24px;
            }
            QPushButton:hover {
                color: #00f0ff;
                background-color: rgba(255, 255, 255, 10);
            }
        """)
        btn.setText("⚙")
        return btn
    
    def _create_keyboard_panel(self) -> GlassPanel:
        """Create keyboard canvas panel."""
        panel = GlassPanel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Header
        header_layout = QHBoxLayout()
        
        title_group = QVBoxLayout()
        title_group.setSpacing(4)
        
        title = QLabel("Crystalline Keys")
        title.setFont(QFont("Geist", 24, QFont.Bold))
        title.setStyleSheet("color: #e4e1ea;")
        title_group.addWidget(title)
        
        subtitle = QLabel("Polyphonic Virtual Analog Synthesis")
        subtitle.setFont(QFont("JetBrains Mono", 12, QFont.Normal))
        subtitle.setStyleSheet("color: rgba(185, 202, 203, 0.8);")
        title_group.addWidget(subtitle)
        
        header_layout.addLayout(title_group)
        header_layout.addStretch()
        
        # Octave display
        octave_group = QVBoxLayout()
        octave_group.setAlignment(Qt.AlignRight)
        
        octave_label = QLabel("OCTAVE")
        octave_label.setStyleSheet("color: rgba(185, 202, 203, 0.5); font-size: 10px; font-weight: 700; letter-spacing: 0.1em;")
        octave_group.addWidget(octave_label)
        
        octave_value = QLabel("C3")
        octave_value.setStyleSheet("color: #00f0ff; font-size: 24px; font-weight: 600;")
        octave_group.addWidget(octave_value)
        
        header_layout.addLayout(octave_group)
        
        layout.addLayout(header_layout)
        
        # Keyboard widget
        self._keyboard = KeyboardWidget()
        self._keyboard.note_pressed.connect(self._on_note_pressed)
        self._keyboard.note_released.connect(self._on_note_released)
        layout.addWidget(self._keyboard, 1)
        
        return panel
    
    def _create_control_panel(self) -> QWidget:
        """Create control tower with buttons, mixer, and pads."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        
        # Top: Function buttons + VU meter
        top_section = self._create_top_controls()
        layout.addWidget(top_section, 1)
        
        # Middle: Mixer strip
        mixer_section = self._create_mixer_section()
        layout.addWidget(mixer_section, 1)
        
        # Bottom: Drum pads
        pad_section = self._create_pad_section()
        layout.addWidget(pad_section, 1)
        
        return panel
    
    def _create_top_controls(self) -> QWidget:
        """Create function buttons grid and VU meter."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        
        # Button grid (2x4)
        button_grid = GlassPanel()
        grid_layout = QVBoxLayout(button_grid)
        grid_layout.setContentsMargins(12, 12, 12, 12)
        grid_layout.setSpacing(8)
        
        button_icons = ["sync", "save", "record", "tune", "share", "download", "history", "auto"]
        
        for row in range(2):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(8)
            
            for col in range(4):
                idx = row * 4 + col
                btn = QPushButton()
                btn.setFixedSize(56, 56)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: rgba(255, 255, 255, 20);
                        border: 1px solid rgba(255, 255, 255, 16);
                        border-radius: 8px;
                        color: rgba(185, 202, 203, 0.8);
                        font-size: 18px;
                    }
                    QPushButton:hover {
                        background-color: rgba(0, 240, 255, 32);
                        color: #00f0ff;
                    }
                """)
                btn.setText("⚡")
                row_layout.addWidget(btn)
            
            row_layout.addStretch()
            grid_layout.addLayout(row_layout)
        
        layout.addWidget(button_grid, 1)
        
        # VU Meter
        self._vu_meter = VUMeterWidget()
        layout.addWidget(self._vu_meter)
        
        return container
    
    def _create_mixer_section(self) -> GlassPanel:
        """Create analog mixer with faders and dials."""
        panel = GlassPanel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        
        # Header
        header = QHBoxLayout()
        header.addWidget(QLabel("ANALOG MIXER"))
        header.addStretch()
        header.addWidget(QLabel("⋮"))
        
        header_label = header.itemAt(0).widget()
        header_label.setStyleSheet("color: rgba(185, 202, 203, 0.8); font-size: 10px; font-weight: 700; letter-spacing: 0.1em;")
        header_label_2 = header.itemAt(2).widget()
        header_label_2.setStyleSheet("color: #00f0ff; font-size: 16px;")
        
        layout.addLayout(header)
        
        # Fader channels
        faders_layout = QHBoxLayout()
        faders_layout.setSpacing(16)
        
        self._faders = []
        self._dials = []
        
        for i in range(4):
            channel = QWidget()
            ch_layout = QVBoxLayout(channel)
            ch_layout.setContentsMargins(0, 0, 0, 0)
            ch_layout.setSpacing(8)
            ch_layout.setAlignment(Qt.AlignCenter)
            
            # Fader
            fader = FaderWidget()
            fader.value_changed.connect(lambda v, idx=i: self._on_fader_changed(idx, v))
            fader.set_value(0.8 if i < 2 else 0.5)
            ch_layout.addWidget(fader, 1)
            self._faders.append(fader)
            
            # Rotary dial
            dial = RotaryDialWidget()
            dial.value_changed.connect(lambda v, idx=i: self._on_dial_changed(idx, v))
            ch_layout.addWidget(dial)
            self._dials.append(dial)
            
            # Channel label
            ch_label = QLabel(f"CH {i+1:02d}")
            ch_label.setStyleSheet("color: rgba(185, 202, 203, 0.5); font-size: 8px; font-weight: 700;")
            ch_label.setAlignment(Qt.AlignCenter)
            ch_layout.addWidget(ch_label)
            
            faders_layout.addWidget(channel, 1)
        
        layout.addLayout(faders_layout)
        
        return panel
    
    def _create_pad_section(self) -> GlassPanel:
        """Create 8-pad drum matrix."""
        panel = GlassPanel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # Pad grid (2 rows x 4 columns)
        grid_layout = QVBoxLayout()
        grid_layout.setSpacing(12)
        
        self._pads = []
        
        for row in range(2):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(12)
            
            for col in range(4):
                pad_idx = row * 4 + col
                pad = DrumPadWidget(pad_idx)
                pad.pad_triggered.connect(self._on_pad_triggered)
                pad.sample_dropped.connect(self._on_sample_dropped)
                pad.setMinimumHeight(60)
                row_layout.addWidget(pad, 1)
                self._pads.append(pad)
            
            row_layout.addStretch()
            grid_layout.addLayout(row_layout, 1)
        
        layout.addLayout(grid_layout)
        
        return panel
    
    def _create_footer(self) -> GlassPanel:
        """Create system footer with status and telemetry."""
        footer = GlassPanel()
        footer.setFixedHeight(40)
        footer.setMinimumWidth(1280)
        
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(24, 8, 24, 8)
        
        # Left: Status indicator
        left_layout = QHBoxLayout()
        left_layout.setSpacing(12)
        
        # Status dot with glow
        status_dot = QLabel("●")
        status_dot.setStyleSheet("""
            color: #20e291;
            font-size: 12px;
            qproperty-alignment: AlignCenter;
        """)
        left_layout.addWidget(status_dot)
        
        # Status text
        status_text = QLabel("System Ready: V-Stack Alpha 0.4.2")
        status_text.setStyleSheet("color: rgba(185, 202, 203, 0.6); font-size: 10px; font-weight: 500; letter-spacing: 0.05em;")
        left_layout.addWidget(status_text)
        
        layout.addLayout(left_layout)
        
        # Right: Telemetry
        right_layout = QHBoxLayout()
        right_layout.setSpacing(24)
        
        cpu_label = QLabel("CPU: 14%")
        cpu_label.setStyleSheet("color: rgba(185, 202, 203, 0.4); font-size: 10px; font-family: 'JetBrains Mono';")
        right_layout.addWidget(cpu_label)
        
        ram_label = QLabel("RAM: 2.4GB")
        ram_label.setStyleSheet("color: rgba(185, 202, 203, 0.4); font-size: 10px; font-family: 'JetBrains Mono';")
        right_layout.addWidget(ram_label)
        
        latency_label = QLabel("LATENCY: 4.2ms")
        latency_label.setStyleSheet("color: rgba(185, 202, 203, 0.4); font-size: 10px; font-family: 'JetBrains Mono';")
        right_layout.addWidget(latency_label)
        
        layout.addLayout(right_layout)
        
        return footer
    
    def _connect_signals(self) -> None:
        """Connect MIDI and audio signals."""
        if self._midi_listener:
            self._midi_listener.note_on.connect(self._on_midi_note_on)
            self._midi_listener.note_off.connect(self._on_midi_note_off)
    
    def _on_midi_note_on(self, note: int, velocity: int) -> None:
        """Handle MIDI note on event."""
        if self._audio_engine:
            # Check if it's a key or pad
            if 48 <= note <= 72:
                self._audio_engine.trigger_synth_note(note, velocity)
                self._keyboard.trigger_note(note)
            elif 36 <= note <= 43:
                pad_idx = note - 36
                self._audio_engine.trigger_pad(pad_idx)
                if pad_idx < len(self._pads):
                    self._pads[pad_idx].set_active(True)
    
    def _on_midi_note_off(self, note: int, velocity: int) -> None:
        """Handle MIDI note off event."""
        if self._audio_engine:
            if 48 <= note <= 72:
                self._audio_engine.release_synth_note(note)
                self._keyboard.release_note(note)
            elif 36 <= note <= 43:
                pad_idx = note - 36
                if pad_idx < len(self._pads):
                    self._pads[pad_idx].set_active(False)
    
    def _on_note_pressed(self, note: int, velocity: int) -> None:
        """Handle keyboard note press."""
        if self._audio_engine:
            self._audio_engine.trigger_synth_note(note, velocity)
    
    def _on_note_released(self, note: int) -> None:
        """Handle keyboard note release."""
        if self._audio_engine:
            self._audio_engine.release_synth_note(note)
    
    def _on_pad_triggered(self, pad_index: int) -> None:
        """Handle drum pad trigger."""
        if self._audio_engine:
            self._audio_engine.trigger_pad(pad_index)
    
    def _on_sample_dropped(self, pad_index: int, file_path: str) -> None:
        """Handle sample dropped on pad."""
        if self._audio_engine:
            self._audio_engine.load_pad_sample(pad_index, file_path)
    
    def _on_fader_changed(self, channel: int, value: float) -> None:
        """Handle fader value change."""
        if self._config_manager:
            self._config_manager.set(value, 'mixer', 'channels', channel, 'volume')
    
    def _on_dial_changed(self, param: int, value: float) -> None:
        """Handle rotary dial change."""
        pass  # Could map to synth parameters
    
    def _update_vu_meter(self) -> None:
        """Update VU meter from audio engine level."""
        if self._audio_engine:
            level = self._audio_engine.get_current_level()
            self._vu_meter.set_level(level)
    
    def _combo_style(self) -> str:
        """Get stylesheet for combo boxes."""
        return """
            QComboBox {
                background-color: rgba(255, 255, 255, 20);
                border: 1px solid rgba(255, 255, 255, 16);
                border-radius: 8px;
                padding: 6px 12px;
                color: rgba(185, 202, 203, 0.8);
                font-family: 'JetBrains Mono';
                font-size: 12px;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox::down-arrow {
                image: none;
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: rgba(30, 30, 36, 230);
                border: 1px solid rgba(255, 255, 255, 16);
                selection-background-color: rgba(0, 240, 255, 51);
                color: #e4e1ea;
            }
        """
    
    def _icon_button_style(self, is_close: bool) -> str:
        """Get stylesheet for icon buttons."""
        if is_close:
            return """
                QPushButton {
                    background-color: transparent;
                    border-radius: 16px;
                    color: rgba(185, 202, 203, 0.8);
                }
                QPushButton:hover {
                    background-color: rgba(255, 180, 171, 32);
                    color: #ffb4ab;
                }
            """
        else:
            return """
                QPushButton {
                    background-color: transparent;
                    border-radius: 16px;
                    color: rgba(185, 202, 203, 0.8);
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 8);
                    color: #e4e1ea;
                }
            """
    
    # Frameless window dragging
    def mousePressEvent(self, event) -> None:
        """Start window drag on header."""
        if event.button() == Qt.LeftButton and event.y() < 56:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event) -> None:
        """Drag window."""
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_start)
            event.accept()
    
    def mouseReleaseEvent(self, event) -> None:
        """Stop window drag."""
        self._dragging = False
    
    def cleanup(self) -> None:
        """Clean up resources before closing."""
        self._vu_timer.stop()
        if self._audio_engine:
            self._audio_engine.cleanup()
        if self._midi_listener:
            self._midi_listener.stop_listening()
