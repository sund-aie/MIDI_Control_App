"""
PandaMINI Core Engine - MIDI Listener
Thread-safe low-latency hardware triggers with ctypes-based Windows Multimedia API (winmm.dll)
Fallbacks to rtmidi/mido backend if not on Windows
"""
from typing import Dict, Optional, Callable, List, Any
from PySide6.QtCore import QObject, Signal, QTimer
import threading
import time
import sys

# Windows MIDI imports and setup
IS_WINDOWS = sys.platform == 'win32'
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes
    
    # Multimedia API Constants
    MIM_DATA = 0x3C3
    CALLBACK_FUNCTION = 0x30000
    
    # Types
    HMIDIIN = wintypes.HANDLE
    LPHMIDIIN = ctypes.POINTER(HMIDIIN)
    DWORD_PTR = ctypes.c_size_t
    
    class MIDIINCAPS(ctypes.Structure):
        _fields_ = [
            ("wMid", wintypes.WORD),
            ("wPid", wintypes.WORD),
            ("vDriverVersion", wintypes.DWORD),
            ("szPname", ctypes.c_wchar * 32),
            ("dwSupport", wintypes.DWORD)
        ]
        
    MIDIINPROC = ctypes.WINFUNCTYPE(
        None,
        HMIDIIN,
        wintypes.UINT,
        DWORD_PTR,
        DWORD_PTR,
        DWORD_PTR
    )
else:
    # Try importing mido as cross-platform fallback
    try:
        import mido
    except ImportError:
        mido = None


class MidiListener(QObject):
    """
    MIDI listener running on native drivers for low-latency.
    Uses WinMM Multimedia API on Windows (zero compile dependencies)
    and falls back to python-rtmidi via mido elsewhere.
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
        self._running = False
        self._lock = threading.Lock()
        
        # WinMM handle
        self._h_midi: Optional[Any] = None
        self._winmm = None
        self._callback_func = None
        
        # Mido backend fallback
        self._mido_port = None
        
        # Device tracking
        self._available_devices: List[str] = []
        
        # Load WinMM DLL if on Windows
        if IS_WINDOWS:
            try:
                self._winmm = ctypes.windll.winmm
            except Exception as e:
                self.midi_error.emit(f"Error loading winmm.dll: {e}")
                
        # Setup polling timer to detect MIDI device hot-plugs
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self.refresh_devices)
        self._poll_timer.start(2000)  # Check every 2 seconds
        
    def get_available_devices(self) -> List[str]:
        """Get list of available MIDI input devices."""
        devices = []
        if IS_WINDOWS and self._winmm:
            try:
                num_devs = self._winmm.midiInGetNumDevs()
                for i in range(num_devs):
                    caps = MIDIINCAPS()
                    res = self._winmm.midiInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps))
                    if res == 0:
                        devices.append(caps.szPname)
            except Exception as e:
                self.midi_error.emit(f"Windows MIDI query error: {e}")
        else:
            # Fallback to mido
            if 'mido' in globals() and mido:
                try:
                    devices = mido.get_input_names()
                except Exception:
                    pass
        return devices
        
    def start_listening(self, device_name: Optional[str] = None) -> bool:
        """Start low-latency listening on the specified device name or index."""
        if self._running:
            self.stop_listening()
            
        if not device_name:
            devices = self.get_available_devices()
            if not devices:
                return False
            device_name = devices[0]
            
        try:
            if IS_WINDOWS and self._winmm:
                # Find device index by name matching
                devices = self.get_available_devices()
                dev_idx = -1
                for idx, name in enumerate(devices):
                    if device_name in name or name in device_name:
                        dev_idx = idx
                        break
                        
                if dev_idx == -1:
                    # Fallback to first
                    dev_idx = 0 if devices else -1
                    
                if dev_idx == -1:
                    return False
                    
                # Bind callback to prevent garbage collection
                self._callback_func = MIDIINPROC(self._on_winmm_message)
                
                self._h_midi = HMIDIIN()
                res = self._winmm.midiInOpen(
                    ctypes.byref(self._h_midi),
                    dev_idx,
                    self._callback_func,
                    0,
                    CALLBACK_FUNCTION
                )
                
                if res == 0:
                    self._winmm.midiInStart(self._h_midi)
                    self._input_device = device_name
                    self._running = True
                    return True
                else:
                    self.midi_error.emit(f"midiInOpen failed: code {res}")
                    return False
            else:
                # Fallback to Mido
                if 'mido' in globals() and mido:
                    self._mido_port = mido.open_input(
                        name=device_name,
                        callback=self._on_mido_message,
                        api='rtmidi'
                    )
                    self._input_device = device_name
                    self._running = True
                    return True
                else:
                    self.midi_error.emit("Mido backend not available.")
                    return False
        except Exception as e:
            self.midi_error.emit(f"Failed to open MIDI device: {e}")
            return False
            
    def stop_listening(self) -> None:
        """Stop MIDI event capture."""
        self._running = False
        
        # Stop Windows multimedia
        if IS_WINDOWS and self._winmm and self._h_midi:
            try:
                self._winmm.midiInStop(self._h_midi)
                self._winmm.midiInClose(self._h_midi)
            except Exception:
                pass
            self._h_midi = None
            self._callback_func = None
            
        # Stop Mido
        if self._mido_port:
            try:
                self._mido_port.close()
            except Exception:
                pass
            self._mido_port = None
            
    def _on_winmm_message(self, hmin, wmsg, dwinstance, dwparam1, dwparam2) -> None:
        """High-frequency Windows driver callback."""
        if not self._running or wmsg != MIM_DATA:
            return
            
        # Parse packed 32-bit MIDI packet
        status = dwparam1 & 0xFF
        data1 = (dwparam1 >> 8) & 0xFF
        data2 = (dwparam1 >> 16) & 0xFF
        
        msg_type = status & 0xF0
        channel = status & 0x0F
        
        # Route signals
        if msg_type == 0x90:  # Note On
            if data2 > 0:
                self._handle_note_on(data1, data2)
            else:
                self._handle_note_off(data1, 0)
        elif msg_type == 0x80:  # Note Off
            self._handle_note_off(data1, data2)
        elif msg_type == 0xB0:  # Control Change
            self._handle_control_change(data1, data2)
        elif msg_type == 0xC0:  # Program Change
            self.program_change.emit(channel, data1)
            
    def _on_mido_message(self, msg) -> None:
        """Fallback callback for mido backend."""
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
        """Distribute keys vs trigger pads notes."""
        if self.KEY_NOTE_START <= note <= self.KEY_NOTE_END:
            self.note_on.emit(note, velocity)
        elif self.PAD_NOTE_START <= note <= self.PAD_NOTE_END:
            self.note_on.emit(note, velocity)
            
    def _handle_note_off(self, note: int, velocity: int) -> None:
        if self.KEY_NOTE_START <= note <= self.KEY_NOTE_END:
            self.note_off.emit(note, velocity)
        elif self.PAD_NOTE_START <= note <= self.PAD_NOTE_END:
            self.note_off.emit(note, velocity)
            
    def _handle_control_change(self, cc: int, value: int) -> None:
        # Faders (CC 10-13)
        if 10 <= cc <= 13:
            channel = cc - 10
            self.control_change.emit(channel, cc, value)
        # Knobs (CC 20-23)
        elif 20 <= cc <= 23:
            param = cc - 20
            self.control_change.emit(param, cc, value)
        else:
            self.control_change.emit(-1, cc, value)
            
    def refresh_devices(self) -> None:
        """Hot-plug detection: scan ports and emit list changes."""
        devices = self.get_available_devices()
        with self._lock:
            if devices != self._available_devices:
                self._available_devices = devices
                self.device_list_updated.emit(devices)
