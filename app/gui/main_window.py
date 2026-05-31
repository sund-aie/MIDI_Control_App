"""
PandaMINI Core Engine - Main Window Redesign
Fully integrated physical instrument layout mirroring the WORLDE Panda MINI controller
Frosted Glassmorphic acrylic design with low-latency device routing console
"""
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QComboBox, QPushButton, QFrame, QDialog, QGridLayout
)
from PySide6.QtCore import Qt, QRectF, Signal, QTimer, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QFont

from app.gui.widgets.keyboard import KeyboardWidget
from app.gui.widgets.controls import (
    VUMeterWidget, FaderWidget, RotaryDialWidget, DrumPadWidget, PadConfigDialog
)


class GlassPanel(QFrame):
    """Frosted glass panel with refractive edges for controller beds."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(False)
    
    def paintEvent(self, event) -> None:
        """Render frosted glass effect."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Base color: rgba(30, 30, 36, 150)
        base_color = QColor(25, 25, 32, 175)
        
        rect = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        
        # Fill base
        painter.fillPath(path, QBrush(base_color))
        
        # Draw high-tech refractive neon-accent borders
        border_pen = QPen(QColor(255, 255, 255, 25), 1.5)
        painter.setPen(border_pen)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 16, 16)


class MainWindow(QMainWindow):
    """Main application window recreating the WORLDE Panda MINI MIDI Controller."""
    
    def __init__(self, audio_engine=None, midi_listener=None, config_manager=None):
        super().__init__()
        
        self._audio_engine = audio_engine
        self._midi_listener = midi_listener
        self._config_manager = config_manager
        
        # Window setup - Frameless and transparent
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(1280, 720)
        
        # State tracking
        self._dragging = False
        self._drag_start = QPoint()
        self._octave_offset = 0
        self._mod_enabled = False
        
        # Setup UI
        self._setup_ui()
        
        # Populate Audio Devices and Connect
        self._populate_audio_devices()
        self._connect_signals()
        
        # VU meter update timer
        self._vu_timer = QTimer()
        self._vu_timer.timeout.connect(self._update_vu_meter)
        self._vu_timer.start(50)  # 20 Hz update rate
        
    def _setup_ui(self) -> None:
        """Construct the physical controller layout in Qt."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)
        
        # Top Header Area (Frameless Window Title & Output Selectors)
        header = self._create_header()
        main_layout.addWidget(header)
        
        # Middle Area: Main Physical Instrument Bed
        instrument_bed = GlassPanel()
        bed_layout = QVBoxLayout(instrument_bed)
        bed_layout.setContentsMargins(20, 20, 20, 20)
        bed_layout.setSpacing(24)
        
        # Top Row of Controller: Buttons Column, Faders, Drum Pads, Knobs, Cockpit
        controls_panel = QWidget()
        controls_layout = QHBoxLayout(controls_panel)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(20)
        
        # 1. Left Side Column: Hardware Utility Buttons (Pitch, Octave, Mod)
        buttons_column = self._create_utility_buttons()
        controls_layout.addWidget(buttons_column)
        
        # 2. Mixer Section: 4 Physical Volume Faders
        fader_section = self._create_fader_section()
        controls_layout.addWidget(fader_section)
        
        # 3. Soundboard Pads Matrix: 8 Drum Pads (2x4)
        pads_section = self._create_pads_section()
        controls_layout.addWidget(pads_section)
        
        # 4. Potentiometers Section: 4 Rotary Knobs
        knobs_section = self._create_knobs_section()
        controls_layout.addWidget(knobs_section)
        
        # 5. Right Cockpit Panel: VU Meter, Device dropdowns and Telemetry
        cockpit_panel = self._create_cockpit_panel()
        controls_layout.addWidget(cockpit_panel)
        
        bed_layout.addWidget(controls_panel, 1)
        
        # Bottom Row of Controller: Centered 25-Key perspective Piano Keyboard
        keyboard_section = QWidget()
        keyboard_layout = QHBoxLayout(keyboard_section)
        keyboard_layout.setContentsMargins(0, 0, 0, 0)
        
        self._keyboard = KeyboardWidget()
        self._keyboard.note_pressed.connect(self._on_note_pressed)
        self._keyboard.note_released.connect(self._on_note_released)
        
        keyboard_layout.addWidget(self._keyboard)
        bed_layout.addWidget(keyboard_section)
        
        main_layout.addWidget(instrument_bed, 1)
        
        # Footer
        footer = self._create_footer()
        main_layout.addWidget(footer)
        
    def _create_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(8, 0, 8, 0)
        
        title_label = QLabel("WORLDE Panda MINI // Core Engine")
        title_label.setFont(QFont("Geist", 18, QFont.Bold))
        title_label.setStyleSheet("color: #dbfcff; letter-spacing: -0.01em;")
        layout.addWidget(title_label)
        
        layout.addStretch()
        
        # Minimize and Close buttons
        minimize_btn = QPushButton("−")
        minimize_btn.setFixedSize(30, 30)
        minimize_btn.setCursor(Qt.PointingHandCursor)
        minimize_btn.setStyleSheet(self._icon_button_style(False))
        minimize_btn.clicked.connect(self.showMinimized)
        layout.addWidget(minimize_btn)
        
        close_btn = QPushButton("×")
        close_btn.setFixedSize(30, 30)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(self._icon_button_style(True))
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
        
        return header
        
    def _create_utility_buttons(self) -> QWidget:
        container = QWidget()
        container.setFixedWidth(140)
        layout = QGridLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Physical Buttons mapping matching Panda MINI precisely
        buttons_info = [
            ("BANK", "bank"), ("PROG", "prog"),
            ("CC MOD", "cc"), ("MOD", "mod"),
            ("OCT −", "oct_down"), ("OCT +", "oct_up"),
            ("PITCH −", "pitch_down"), ("PITCH +", "pitch_up")
        ]
        
        self._util_buttons = {}
        for idx, (label, action) in enumerate(buttons_info):
            row = idx // 2
            col = idx % 2
            
            btn = QPushButton(label)
            btn.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
            btn.setFixedSize(66, 38)
            btn.setCursor(Qt.PointingHandCursor)
            
            if action in ["pitch_down", "pitch_up", "oct_down", "oct_up"]:
                btn.setStyleSheet(self._util_btn_style("rgba(0, 240, 255, 30)", "#00f0ff"))
            else:
                btn.setStyleSheet(self._util_btn_style("rgba(255, 255, 255, 12)", "#e4e1ea"))
                
            # Connect actions
            if action == "oct_up":
                btn.clicked.connect(self._on_octave_up)
            elif action == "oct_down":
                btn.clicked.connect(self._on_octave_down)
            elif action == "mod":
                btn.clicked.connect(self._on_modulation)
                
            layout.addWidget(btn, row, col)
            self._util_buttons[action] = btn
            
        return container
        
    def _create_fader_section(self) -> GlassPanel:
        panel = GlassPanel()
        panel.setFixedWidth(200)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        
        # Header label
        header_label = QLabel("VOL SLIDERS (CC 10-13)")
        header_label.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
        header_label.setStyleSheet("color: rgba(185, 202, 203, 0.5);")
        header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_label)
        
        faders_row = QHBoxLayout()
        faders_row.setSpacing(8)
        
        self._faders = []
        for i in range(4):
            ch_col = QVBoxLayout()
            ch_col.setSpacing(6)
            
            fader = FaderWidget()
            fader.value_changed.connect(lambda v, idx=i: self._on_fader_changed(idx, v))
            fader.set_value(self._config_manager.get('mixer', 'channels', i, 'volume', default=0.8))
            ch_col.addWidget(fader, 1)
            self._faders.append(fader)
            
            lbl = QLabel(f"F{i+1}")
            lbl.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
            lbl.setStyleSheet("color: rgba(185, 202, 203, 0.4);")
            lbl.setAlignment(Qt.AlignCenter)
            ch_col.addWidget(lbl)
            
            faders_row.addLayout(ch_col)
            
        layout.addLayout(faders_row)
        return panel
        
    def _create_pads_section(self) -> GlassPanel:
        panel = GlassPanel()
        panel.setFixedWidth(360)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        
        header_label = QLabel("SILICONE DRUM PADS (PAD 1-8 / MIDI 36-43)")
        header_label.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
        header_label.setStyleSheet("color: rgba(185, 202, 203, 0.5);")
        header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_label)
        
        grid = QVBoxLayout()
        grid.setSpacing(8)
        
        self._pads = []
        for row in range(2):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(8)
            for col in range(4):
                pad_idx = row * 4 + col
                pad = DrumPadWidget(pad_idx)
                
                # Retrieve path from engine (includes built-in defaults)
                if self._audio_engine:
                    path = self._audio_engine._pad_sample_paths.get(pad_idx, "")
                    if path:
                        pad.set_sample_path(path)
                    
                pad.pad_triggered.connect(self._on_pad_triggered)
                pad.pad_released.connect(self._on_pad_released)
                pad.pad_config_requested.connect(self._on_pad_config_requested)
                pad.sample_dropped.connect(self._on_sample_dropped)
                
                row_layout.addWidget(pad)
                self._pads.append(pad)
            grid.addLayout(row_layout)
            
        layout.addLayout(grid)
        return panel
        
    def _create_knobs_section(self) -> GlassPanel:
        panel = GlassPanel()
        panel.setFixedWidth(200)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        
        header_label = QLabel("POTENTIOMETERS")
        header_label.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
        header_label.setStyleSheet("color: rgba(185, 202, 203, 0.5);")
        header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_label)
        
        knobs_row = QHBoxLayout()
        knobs_row.setSpacing(8)
        
        knob_names = ["CUTOFF", "RESO", "ATTACK", "RELEASE"]
        self._dials = []
        for i in range(4):
            ch_col = QVBoxLayout()
            ch_col.setSpacing(6)
            ch_col.setAlignment(Qt.AlignCenter)
            
            dial = RotaryDialWidget()
            dial.value_changed.connect(lambda v, idx=i: self._on_dial_changed(idx, v))
            ch_col.addWidget(dial)
            self._dials.append(dial)
            
            lbl = QLabel(knob_names[i])
            lbl.setFont(QFont("JetBrains Mono", 7, QFont.Bold))
            lbl.setStyleSheet("color: rgba(185, 202, 203, 0.4);")
            lbl.setAlignment(Qt.AlignCenter)
            ch_col.addWidget(lbl)
            
            knobs_row.addLayout(ch_col)
            
        layout.addLayout(knobs_row)
        return panel
        
    def _create_cockpit_panel(self) -> GlassPanel:
        panel = GlassPanel()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)
        
        # Left side inside Cockpit: Combo boxes & Telemetry
        cockpit_info = QVBoxLayout()
        cockpit_info.setSpacing(10)
        
        # Audio dropdowns
        self._sampler_combo = QComboBox()
        self._sampler_combo.setMinimumWidth(180)
        self._sampler_combo.setStyleSheet(self._combo_style())
        self._sampler_combo.currentIndexChanged.connect(self._on_device_changed)
        cockpit_info.addWidget(self._sampler_combo)
        
        self._soundboard_combo = QComboBox()
        self._soundboard_combo.setMinimumWidth(180)
        self._soundboard_combo.setStyleSheet(self._combo_style())
        self._soundboard_combo.currentIndexChanged.connect(self._on_device_changed)
        cockpit_info.addWidget(self._soundboard_combo)
        
        # Decibel Telemetry Labels
        telemetry = QVBoxLayout()
        telemetry.setSpacing(4)
        
        self.octave_label = QLabel("OCTAVE: C3 (TRANS: 0)")
        self.octave_label.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
        self.octave_label.setStyleSheet("color: #00f0ff;")
        telemetry.addWidget(self.octave_label)
        
        status_lbl = QLabel("STREAM: ACTIVE WASAPI")
        status_lbl.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
        status_lbl.setStyleSheet("color: rgba(185, 202, 203, 0.6);")
        telemetry.addWidget(status_lbl)
        
        cockpit_info.addLayout(telemetry)
        layout.addLayout(cockpit_info, 1)
        
        # Right side inside Cockpit: Vertical Stereo VU Meter
        self._vu_meter = VUMeterWidget()
        layout.addWidget(self._vu_meter)
        
        return panel
        
    def _create_footer(self) -> QWidget:
        footer = QWidget()
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(8, 0, 8, 0)
        
        self.status_label = QLabel("●  Core Soundboard & Synth Controller Engine Ready")
        self.status_label.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
        self.status_label.setStyleSheet("color: #20e291;")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
        
        telemetry = QLabel("LATENCY: 4.2ms | CPU: 9% | ACTIVE VOICES: 0")
        telemetry.setObjectName("telemetry_text")
        telemetry.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
        telemetry.setStyleSheet("color: rgba(185, 202, 203, 0.4);")
        layout.addWidget(telemetry)
        
        return footer
        
    def _connect_signals(self) -> None:
        """Connect incoming MIDI triggers directly to UI rendering."""
        if self._midi_listener:
            self._midi_listener.note_on.connect(self._on_midi_note_on)
            self._midi_listener.note_off.connect(self._on_midi_note_off)
            self._midi_listener.control_change.connect(self._on_midi_cc)
            self._midi_listener.device_list_updated.connect(self._on_midi_devices_updated)
            self._update_midi_status()
            
        if self._audio_engine:
            self._audio_engine.pad_loaded.connect(self._on_pad_loaded_async)
            
    def _on_pad_loaded_async(self, pad_index: int, path: str) -> None:
        """Handle async sample loaded signal to update UI immediately."""
        if 0 <= pad_index < len(self._pads):
            self._pads[pad_index].set_sample_path(path)
            
    def _on_midi_devices_updated(self, devices: list) -> None:
        """Handle device hot-plug updates dynamically."""
        self._update_midi_status()
        
    def _update_midi_status(self) -> None:
        """Update visual MIDI connection status in the footer."""
        if self._midi_listener and self._midi_listener._running:
            dev_name = self._midi_listener._input_device or "MIDI Device"
            self.status_label.setText(f"●  CONNECTED: {dev_name.upper()}")
            self.status_label.setStyleSheet("color: #20e291;")
        else:
            self.status_label.setText("●  DISCONNECTED (NO MIDI KEYBOARD)")
            self.status_label.setStyleSheet("color: #ff5050;")
            
    def _populate_audio_devices(self) -> None:
        """Query host drivers for active outputs and populate dropdowns."""
        devices = self._audio_engine.get_available_devices()
        
        self._soundboard_combo.blockSignals(True)
        self._sampler_combo.blockSignals(True)
        
        self._soundboard_combo.clear()
        self._sampler_combo.clear()
        
        self._soundboard_combo.addItem("Soundboard: Default", None)
        self._sampler_combo.addItem("Sampler: Default", None)
        
        saved_sb = self._config_manager.get('audio', 'soundboard_output')
        saved_sampler = self._config_manager.get('audio', 'sampler_output')
        
        sb_idx = 0
        sampler_idx = 0
        
        for dev in devices:
            self._soundboard_combo.addItem(dev['name'], dev['name'])
            self._sampler_combo.addItem(dev['name'], dev['name'])
            
            if saved_sb == dev['name']:
                sb_idx = self._soundboard_combo.count() - 1
            if saved_sampler == dev['name']:
                sampler_idx = self._sampler_combo.count() - 1
                
        self._soundboard_combo.setCurrentIndex(sb_idx)
        self._sampler_combo.setCurrentIndex(sampler_idx)
        
        self._soundboard_combo.blockSignals(False)
        self._sampler_combo.blockSignals(False)
        
    def _on_device_changed(self) -> None:
        """Restart streams instantly when the user chooses a different physical endpoint."""
        sb_name = self._soundboard_combo.currentData()
        sampler_name = self._sampler_combo.currentData()
        
        # Stop streams
        self._audio_engine.stop_streams()
        
        # Update config manager
        self._config_manager.set(sb_name, 'audio', 'soundboard_output', trigger_save=False)
        self._config_manager.set(sampler_name, 'audio', 'sampler_output', trigger_save=False)
        self._config_manager.save_now()
        
        # Start streams with selected devices
        self._audio_engine.start_streams(
            sampler_device=sampler_name,
            soundboard_device=sb_name
        )
        
    def _on_midi_note_on(self, note: int, velocity: int) -> None:
        """Handle hardware MIDI note on event."""
        # Process synth key (Note 48-72)
        if 48 <= note <= 72:
            shifted_note = note + (self._octave_offset * 12)
            self._audio_engine.trigger_synth_note(shifted_note, velocity)
            self._keyboard.trigger_note(note)
            
        # Process soundboard pad (Note 36-43)
        elif 36 <= note <= 43:
            pad_idx = note - 36
            self._audio_engine.trigger_pad(pad_idx)
            if pad_idx < len(self._pads):
                self._pads[pad_idx].set_active(True)
                
    def _on_midi_note_off(self, note: int, velocity: int) -> None:
        """Handle hardware MIDI note off event."""
        # Release synth key
        if 48 <= note <= 72:
            shifted_note = note + (self._octave_offset * 12)
            self._audio_engine.release_synth_note(shifted_note)
            self._keyboard.release_note(note)
            
        # Release soundboard pad
        elif 36 <= note <= 43:
            pad_idx = note - 36
            self._audio_engine.release_pad(pad_idx)
            if pad_idx < len(self._pads):
                self._pads[pad_idx].set_active(False)
                
    def _on_midi_cc(self, channel: int, cc: int, value: int) -> None:
        """Handle hardware knobs/faders control change."""
        # Map physical faders CC 10-13 to UI sliders
        if 10 <= cc <= 13:
            idx = cc - 10
            normalized = value / 127.0
            if idx < len(self._faders):
                self._faders[idx].set_value(normalized)
                self._audio_engine.set_pad_volume(idx, normalized)
                
        # Map physical knobs CC 20-23 to UI dials
        elif 20 <= cc <= 23:
            idx = cc - 20
            normalized = value / 127.0
            if idx < len(self._dials):
                self._dials[idx].set_value(normalized)
                
    def _on_note_pressed(self, note: int, velocity: int) -> None:
        """Keyboard click note trigger."""
        shifted_note = note + (self._octave_offset * 12)
        self._audio_engine.trigger_synth_note(shifted_note, velocity)
        
    def _on_note_released(self, note: int) -> None:
        """Keyboard click note release."""
        shifted_note = note + (self._octave_offset * 12)
        self._audio_engine.release_synth_note(shifted_note)
        
    def _on_pad_triggered(self, pad_index: int) -> None:
        """Click pad trigger."""
        self._audio_engine.trigger_pad(pad_index)
        
    def _on_pad_released(self, pad_index: int) -> None:
        """Release pad trigger."""
        self._audio_engine.release_pad(pad_index)
        
    def _on_pad_config_requested(self, pad_index: int) -> None:
        """Launch the custom glass settings dialog for the pad."""
        dialog = PadConfigDialog(pad_index, self._audio_engine, self)
        if dialog.exec() == QDialog.Accepted:
            # Sync paths
            path = self._audio_engine._pad_sample_paths.get(pad_index, "")
            self._pads[pad_index].set_sample_path(path)
            
    def _on_sample_dropped(self, pad_index: int, file_path: str) -> None:
        """Load dragged & dropped audio file."""
        self._audio_engine.load_pad_sample(pad_index, file_path)
        
    def _on_fader_changed(self, idx: int, value: float) -> None:
        """Handle UI fader slide."""
        self._audio_engine.set_pad_volume(idx, value)
        
    def _on_dial_changed(self, idx: int, value: float) -> None:
        """Handle UI rotary knob turn."""
        pass
        
    def _on_octave_up(self) -> None:
        """Pitch octave up shift button."""
        self._octave_offset = min(3, self._octave_offset + 1)
        self._update_octave_display()
        
    def _on_octave_down(self) -> None:
        """Pitch octave down shift button."""
        self._octave_offset = max(-3, self._octave_offset - 1)
        self._update_octave_display()
        
    def _on_modulation(self) -> None:
        """Modulation trigger toggle."""
        self._mod_enabled = not self._mod_enabled
        btn = self._util_buttons.get("mod")
        if self._mod_enabled:
            btn.setStyleSheet(self._util_btn_style("rgba(32, 226, 145, 60)", "#20e291"))
        else:
            btn.setStyleSheet(self._util_btn_style("rgba(255, 255, 255, 12)", "#e4e1ea"))
            
    def _update_octave_display(self) -> None:
        oct_val = 3 + self._octave_offset
        self.octave_label.setText(f"OCTAVE: C{oct_val} (TRANS: {self._octave_offset * 12})")
        
    def _update_vu_meter(self) -> None:
        """Update neon VU meter and active voice indicators."""
        if self._audio_engine:
            level = self._audio_engine.get_current_level()
            self._vu_meter.set_level(level)
            
            # Decay peak level
            self._audio_engine._current_level *= 0.85
            
            # Telemetry count update
            active_count = self._audio_engine.voice_manager.get_active_count()
            for pad_idx in range(8):
                if self._audio_engine._pad_active_mon[pad_idx] or self._audio_engine._pad_active_mic[pad_idx]:
                    active_count += 1
            
            footer_telemetry = self.findChild(QLabel, "telemetry_text")
            if footer_telemetry:
                footer_telemetry.setText(f"LATENCY: 4.2ms | CPU: 9% | ACTIVE VOICES: {active_count}")
                
    def _util_btn_style(self, bg: str, text_col: str) -> str:
        return f"""
            QPushButton {{
                background-color: {bg};
                border: 1px solid rgba(255, 255, 255, 16);
                border-radius: 6px;
                color: {text_col};
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 24);
                border-color: rgba(255, 255, 255, 40);
            }}
            QPushButton:pressed {{
                background-color: rgba(0, 240, 255, 50);
                border-color: #00f0ff;
                color: #00f0ff;
            }}
        """
        
    def _combo_style(self) -> str:
        return """
            QComboBox {
                background-color: rgba(0, 0, 0, 80);
                border: 1px solid rgba(255, 255, 255, 12);
                border-radius: 8px;
                padding: 6px 12px;
                color: rgba(185, 202, 203, 0.8);
                font-family: 'JetBrains Mono';
                font-size: 11px;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: rgba(30, 30, 36, 245);
                border: 1px solid rgba(0, 240, 255, 100);
                selection-background-color: rgba(0, 240, 255, 51);
                color: #dbfcff;
            }
        """
        
    def _icon_button_style(self, is_close: bool) -> str:
        if is_close:
            return """
                QPushButton {
                    background-color: transparent;
                    border-radius: 15px;
                    color: rgba(185, 202, 203, 0.8);
                    font-size: 16px;
                    border: none;
                }
                QPushButton:hover {
                    background-color: rgba(255, 80, 80, 50);
                    color: #ff5050;
                }
            """
        else:
            return """
                QPushButton {
                    background-color: transparent;
                    border-radius: 15px;
                    color: rgba(185, 202, 203, 0.8);
                    font-size: 16px;
                    border: none;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 12);
                    color: #ffffff;
                }
            """
            
    def mousePressEvent(self, event) -> None:
        """Window drag press."""
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            
    def mouseMoveEvent(self, event) -> None:
        """Window drag move."""
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_start)
            event.accept()
            
    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        
    def cleanup(self) -> None:
        self._vu_timer.stop()
        if self._audio_engine:
            self._audio_engine.cleanup()
        if self._midi_listener:
            self._midi_listener.stop_listening()
