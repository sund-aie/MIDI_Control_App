"""
PandaMINI Core Engine - MIDI Listener
Thread B (RtMidi Thread) catches low-latency hardware triggers
Maps keys (Notes 48-72), drum pads (Notes 36-43), faders (CC 10-13), and knobs (CC 20-23)
"""
import mido
from typing import Dict, Optional, Callable, List, Any
from PySide6.QtCore import QObject, Signal, QThread
import threading
import time


class MidiListener(QObject):
    """
    MIDI listener running on dedicated thread for low-latency input.
    Uses python-rtmidi backend via mido library.
    """
    
    note_on = Signal(int, int)  # note, velocity
    note_off = Signal(int, int)  # note, velocity  
    control_change = Signal(int, int, int)  # channel, cc, value
    program_change = Signal(int, int)  # channel, program
    midi_error = Signal(str)
    device_list_updated = Signal(list)
    
    # MIDI mappings for Worlde Panda MINI
    KEY_NOTE_START = 48  # C3
    KEY_NOTE_END = 72    # C5
    PAD_NOTE_START = 36  # C2
    PAD_NOTE_END = 43    # G#2
    
    # CC mappings
    FADER_CC_MAP = {10: 0, 11: 1, 12: 2, 13: 3}  # CC 10-13 -> Channel 0-3
    KNOB_CC_MAP = {20: 0, 21: 1, 22: 2, 23: 3}   # CC 20-23 -> Parameter 0-3
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        
        self._input_device: Optional[str] = None
        self._port: Optional[mido.InputPort] = None
        self._thread: Optional[QThread] = None
        self._running = False
        self._lock = threading.Lock()
        
        # Device tracking
        self._available_devices: List[str] = []
        self._refresh_interval = 2.0  # seconds
        self._last_refresh = 0.0
    
    def get_available_devices(self) -> List[str]:
        """Get list of available MIDI input devices."""
        try:
            devices = mido.get_input_names()
            return devices
        except Exception as e:
            self.midi_error.emit(f"Error getting MIDI devices: {e}")
            return []
    
    def start_listening(self, device_name: Optional[str] = None) -> bool:
        """
        Start listening for MIDI messages on the specified device.
        
        Args:
            device_name: Name of the MIDI input device, or None for default
            
        Returns:
            True if listening started successfully
        """
        if self._running:
            self.stop_listening()
        
        try:
            # Open port with rtmidi backend
            self._port = mido.open_input(
                name=device_name,
                callback=self._on_midi_message,
                api='rtmidi'
            )
            
            self._input_device = device_name
            self._running = True
            
            return True
            
        except Exception as e:
            self.midi_error.emit(f"Failed to open MIDI device: {e}")
            return False
    
    def stop_listening(self) -> None:
        """Stop listening for MIDI messages."""
        self._running = False
        
        if self._port:
            try:
                self._port.close()
            except:
                pass
            self._port = None
    
    def _on_midi_message(self, msg: mido.Message) -> None:
        """Handle incoming MIDI message."""
        if not self._running:
            return
        
        msg_type = msg.type
        
        if msg_type == 'note_on':
            if msg.velocity > 0:
                self._handle_note_on(msg.note, msg.velocity)
            else:
                self._handle_note_off(msg.note, 0)
                
        elif msg_type == 'note_off':
            self._handle_note_off(msg.note, msg.velocity)
            
        elif msg_type == 'control_change':
            self._handle_control_change(msg.control, msg.value)
            
        elif msg_type == 'program_change':
            self.program_change.emit(msg.channel, msg.value)
    
    def _handle_note_on(self, note: int, velocity: int) -> None:
        """Process note on event based on mapping."""
        # Check if it's a key (48-72)
        if self.KEY_NOTE_START <= note <= self.KEY_NOTE_END:
            self.note_on.emit(note, velocity)
        
        # Check if it's a pad (36-43)
        elif self.PAD_NOTE_START <= note <= self.PAD_NOTE_END:
            pad_index = note - self.PAD_NOTE_START
            self.note_on.emit(note, velocity)  # Also emit raw note
    
    def _handle_note_off(self, note: int, velocity: int) -> None:
        """Process note off event based on mapping."""
        # Check if it's a key (48-72)
        if self.KEY_NOTE_START <= note <= self.KEY_NOTE_END:
            self.note_off.emit(note, velocity)
        
        # Check if it's a pad (36-43)
        elif self.PAD_NOTE_START <= note <= self.PAD_NOTE_END:
            pad_index = note - self.PAD_NOTE_START
            self.note_off.emit(note, velocity)  # Also emit raw note
    
    def _handle_control_change(self, cc: int, value: int) -> None:
        """Process control change event based on mapping."""
        # Check fader mapping (CC 10-13)
        if cc in self.FADER_CC_MAP:
            channel = self.FADER_CC_MAP[cc]
            self.control_change.emit(channel, cc, value)
        
        # Check knob mapping (CC 20-23)
        elif cc in self.KNOB_CC_MAP:
            param = self.KNOB_CC_MAP[cc]
            self.control_change.emit(param, cc, value)
        
        # Emit raw CC for any other handling
        self.control_change.emit(-1, cc, value)
    
    def refresh_devices(self) -> None:
        """Refresh the list of available MIDI devices."""
        current_time = time.time()
        if current_time - self._last_refresh < self._refresh_interval:
            return
        
        self._last_refresh = current_time
        devices = self.get_available_devices()
        
        with self._lock:
            if devices != self._available_devices:
                self._available_devices = devices
                self.device_list_updated.emit(devices)
