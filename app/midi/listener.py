"""
MIDI input: reads the controller on its own driver thread, triggers the audio
engine directly (lowest latency) and tells the GUI what happened via Qt signals.

Windows uses the built-in WinMM API through ctypes (nothing to compile);
other systems use mido + python-rtmidi.
"""
import logging
import sys
import threading
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from app.midi.bindings import DRUM_CHANNEL, ControlMap, MidiEvent

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
PREFERRED_NAMES = ("panda", "worlde")   # in order: other WORLDE models share the prefix


class MidiError(Exception):
    """Opening the MIDI port failed. The message is user-facing."""


class _WinMMBackend:
    MIM_DATA = 0x3C3
    CALLBACK_FUNCTION = 0x30000
    ERRORS = {
        2: "The controller was unplugged.",
        4: "Another program is using the controller. Close your DAW or other MIDI apps and try again.",
        7: "Windows ran out of memory opening the controller.",
    }

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._winmm = ctypes.windll.winmm
        self._handle = None
        self._proc = None

        class MIDIINCAPSW(ctypes.Structure):
            _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
                        ("vDriverVersion", wintypes.UINT), ("szPname", ctypes.c_wchar * 32),
                        ("dwSupport", wintypes.DWORD)]

        self._caps_type = MIDIINCAPSW
        self._proc_type = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.UINT,
                                             ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t)
        w = self._winmm
        w.midiInGetNumDevs.restype = wintypes.UINT
        w.midiInGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(MIDIINCAPSW), wintypes.UINT]
        w.midiInGetDevCapsW.restype = wintypes.UINT
        w.midiInOpen.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.UINT, self._proc_type,
                                 ctypes.c_size_t, wintypes.DWORD]
        w.midiInOpen.restype = wintypes.UINT
        for fn in (w.midiInStart, w.midiInStop, w.midiInReset, w.midiInClose):
            fn.argtypes = [wintypes.HANDLE]
            fn.restype = wintypes.UINT

    def list(self) -> List[str]:
        names = []
        for i in range(self._winmm.midiInGetNumDevs()):
            caps = self._caps_type()
            if self._winmm.midiInGetDevCapsW(i, self._ctypes.byref(caps), self._ctypes.sizeof(caps)) == 0:
                names.append(caps.szPname)
        return names

    def open(self, index: int, on_bytes: Callable[[int, int, int], None]) -> None:
        from ctypes import wintypes

        def proc(handle, msg, instance, param1, param2):
            if msg == self.MIM_DATA:
                on_bytes(param1 & 0xFF, (param1 >> 8) & 0x7F, (param1 >> 16) & 0x7F)

        self._proc = self._proc_type(proc)  # keep a reference or ctypes frees it
        handle = wintypes.HANDLE()
        res = self._winmm.midiInOpen(self._ctypes.byref(handle), index, self._proc, 0, self.CALLBACK_FUNCTION)
        if res != 0:
            self._proc = None
            raise MidiError(self.ERRORS.get(res, f"Windows could not open the controller (error {res})."))
        self._handle = handle
        self._winmm.midiInStart(handle)

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            for fn in (self._winmm.midiInStop, self._winmm.midiInReset, self._winmm.midiInClose):
                try:
                    fn(handle)
                except Exception:
                    pass
        self._proc = None


class _MidoBackend:
    def __init__(self):
        import mido
        self._mido = mido
        self._port = None

    def list(self) -> List[str]:
        return list(self._mido.get_input_names())

    def open(self, index: int, on_bytes: Callable[[int, int, int], None]) -> None:
        name = self.list()[index]

        def callback(msg):
            data = msg.bytes()
            if data:
                on_bytes(data[0], data[1] if len(data) > 1 else 0, data[2] if len(data) > 2 else 0)

        try:
            self._port = self._mido.open_input(name, callback=callback)
        except Exception as e:
            raise MidiError(f"Could not open '{name}': {e}")

    def close(self) -> None:
        port, self._port = self._port, None
        if port is not None:
            try:
                port.close()
            except Exception:
                pass


def _make_backend():
    try:
        return _WinMMBackend() if IS_WINDOWS else _MidoBackend()
    except Exception as e:
        log.warning("No MIDI backend available: %s", e)
        return None


class MidiListener(QObject):
    """Connects to the controller, routes its messages, handles hot-plugging."""

    # All signals are emitted from the MIDI driver thread; Qt queues them to the GUI.
    pad_pressed = Signal(int)           # pad index
    pad_released = Signal(int)
    key_on = Signal(int, int)           # note, velocity
    key_off = Signal(int)
    slider_moved = Signal(int, float)   # index, 0..1
    knob_moved = Signal(int, float)
    pitch_bend = Signal(int)            # -8192..8191
    mod_wheel = Signal(int)             # 0..127
    program = Signal(int)
    activity = Signal()
    unmatched_pad = Signal(object)      # MidiEvent on the drum channel no pad is bound to
    learn_event = Signal(object)        # MidiEvent while learning
    status_changed = Signal(bool, str, str)  # connected, device name, message
    devices_changed = Signal(list)

    def __init__(self, engine=None, parent: Optional[QObject] = None, backend=None):
        super().__init__(parent)
        self._engine = engine
        self._backend = backend if backend is not None else _make_backend()
        self._map = ControlMap.defaults()
        self._cc_pad_down = set()
        self._lock = threading.Lock()
        self.learning = False
        self.wanted: Optional[str] = None       # name the user picked (or None = auto)
        self.connected: Optional[str] = None
        self._last_connected: Optional[str] = None   # reconnect to this after an unplug
        self._devices: List[str] = []
        self._last_error = ""
        self._poll = QTimer(self)
        self._poll.setInterval(1500)
        self._poll.timeout.connect(self.poll)

    # ── configuration ───────────────────────────────────────────

    def set_control_map(self, cmap: ControlMap) -> None:
        self._map = cmap

    @property
    def control_map(self) -> ControlMap:
        return self._map

    # ── connection ──────────────────────────────────────────────

    def devices(self) -> List[str]:
        if self._backend is None:
            return []
        try:
            return self._backend.list()
        except Exception as e:
            log.warning("Listing MIDI inputs failed: %s", e)
            return []

    def start(self, wanted: Optional[str] = None) -> None:
        self.wanted = wanted
        self.poll()
        self._poll.start()

    def choose(self, name: Optional[str]) -> None:
        """User picked a device from the menu (None = automatic)."""
        self.wanted = name
        self._last_connected = None
        self.disconnect()
        self.poll()

    def poll(self) -> None:
        """Hot-plug: notice new/removed devices and (re)connect automatically."""
        devices = self.devices()
        if devices != self._devices:
            self._devices = devices
            self.devices_changed.emit(devices)
        if self.connected is not None and self.connected not in devices:
            log.info("MIDI device %s disappeared", self.connected)
            self.disconnect()
            self._emit_status(False, "", "Controller unplugged. Plug it back in and it will reconnect.")
        if self.connected is None:
            self._try_connect(devices)

    def _pick(self, devices: List[str]) -> Optional[int]:
        """Chosen device, else the one used before, else a Panda/WORLDE; never hop to a random port."""
        if not devices:
            return None
        for target in (self.wanted, self._last_connected):
            if target and target in devices:
                return devices.index(target)
        if self.wanted:
            for i, name in enumerate(devices):
                if self.wanted.lower() in name.lower() or name.lower() in self.wanted.lower():
                    return i
        for preferred in PREFERRED_NAMES:
            for i, name in enumerate(devices):
                if preferred in name.lower():
                    return i
        if self.wanted or self._last_connected:
            return None
        return 0

    def _try_connect(self, devices: List[str]) -> None:
        if self._backend is None:
            self._emit_status(False, "", "MIDI support is not available on this computer.")
            return
        index = self._pick(devices)
        if index is None:
            waiting = self.wanted or self._last_connected
            if devices and waiting:
                self._emit_status(False, "", f"Waiting for {waiting}. Plug it in or pick another controller.")
            else:
                self._emit_status(False, "", "No controller found. Plug in your Panda MINI.")
            return
        name = devices[index]
        try:
            self._backend.open(index, self._on_bytes)
        except MidiError as e:
            self._emit_status(False, name, str(e))
            return
        except Exception as e:
            log.exception("Opening MIDI input %s failed", name)
            self._emit_status(False, name, f"Could not open '{name}' ({e}).")
            return
        self.connected = self._last_connected = name
        log.info("MIDI connected: %s", name)
        self._emit_status(True, name, "")

    def disconnect(self) -> None:
        if self._backend is not None:
            self._backend.close()
        self.connected = None
        self._cc_pad_down.clear()

    def stop(self) -> None:
        self._poll.stop()
        self.disconnect()

    def _emit_status(self, ok: bool, name: str, message: str) -> None:
        key = (ok, name, message)
        if key != self._last_error:
            self._last_error = key
            self.status_changed.emit(ok, name, message)

    # ── message handling (MIDI driver thread) ───────────────────

    def _on_bytes(self, status: int, d1: int, d2: int) -> None:
        try:
            ev = parse(status, d1, d2)
            if ev is not None:
                self.handle(ev)
        except Exception:
            log.exception("MIDI handling error")

    def handle(self, ev: MidiEvent) -> None:
        self.activity.emit()
        if self.learning:
            if ev.is_press:
                self.learn_event.emit(ev)
            return

        target = self._map.lookup(ev)
        engine = self._engine
        if target is not None and target[0] == "pad":
            self._handle_pad(target[1], ev)
            return

        if ev.kind == "note_on":
            if ev.channel == DRUM_CHANNEL:
                self.unmatched_pad.emit(ev)
            if engine is not None:
                engine.note_on(ev.number, ev.value)
            self.key_on.emit(ev.number, ev.value)
        elif ev.kind == "note_off":
            if engine is not None:
                engine.note_off(ev.number)
            self.key_off.emit(ev.number)
        elif ev.kind == "cc":
            if target is not None:
                group, index = target
                signal = self.slider_moved if group == "slider" else self.knob_moved
                signal.emit(index, ev.value / 127.0)
            elif ev.number == 1:
                self.mod_wheel.emit(ev.value)
        elif ev.kind == "pc":
            self.program.emit(ev.number)
        elif ev.kind == "pitch":
            self.pitch_bend.emit(ev.value)

    def _handle_pad(self, pad: int, ev: MidiEvent) -> None:
        engine = self._engine
        if ev.kind == "note_on":
            press = True
        elif ev.kind == "note_off":
            press = False
        elif ev.kind == "cc":
            # Pads in CC mode send >0 on hit and 0 on release; ignore repeats while held.
            with self._lock:
                if ev.value > 0:
                    if pad in self._cc_pad_down:
                        return
                    self._cc_pad_down.add(pad)
                    press = True
                else:
                    self._cc_pad_down.discard(pad)
                    press = False
        elif ev.kind == "pc":
            if engine is not None:
                engine.trigger_pad(pad)
                engine.release_pad(pad)
            self.pad_pressed.emit(pad)
            self.pad_released.emit(pad)
            return
        else:
            return
        if press:
            if engine is not None:
                engine.trigger_pad(pad)
            self.pad_pressed.emit(pad)
        else:
            if engine is not None:
                engine.release_pad(pad)
            self.pad_released.emit(pad)


def parse(status: int, d1: int, d2: int) -> Optional[MidiEvent]:
    kind = status & 0xF0
    ch = status & 0x0F
    if kind == 0x90:
        return MidiEvent("note_on" if d2 > 0 else "note_off", ch, d1, d2)
    if kind == 0x80:
        return MidiEvent("note_off", ch, d1, d2)
    if kind == 0xB0:
        return MidiEvent("cc", ch, d1, d2)
    if kind == 0xC0:
        return MidiEvent("pc", ch, d1, 0)
    if kind == 0xE0:
        return MidiEvent("pitch", ch, 0, ((d2 << 7) | d1) - 8192)
    return None
