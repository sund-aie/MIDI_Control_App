"""
Audio engine: plays pad sounds (and the keyboard synth) to up to two outputs,
the user's headphones and a virtual microphone cable (VB-Cable) for Discord/OBS.

Threading
- The GUI thread and the MIDI thread call trigger_pad(), release_pad(),
  note_on() ... Those take a short lock and append commands to each output's
  deque; they never touch audio buffers.
- Every output has its own PortAudio callback thread that drains its deque and
  mixes its own voices, so the two outputs never share play positions.
- Decoding and resampling run one job at a time on a single worker thread (so
  they can't crowd the audio callbacks off the GIL); results come back to the
  GUI thread through queued Qt signals.
"""
import collections
import logging
import math
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from app.audio.decode import MAX_SECONDS, DecodeError, decode_file, resample

try:
    import sounddevice as sd
except Exception:  # PortAudio missing
    sd = None

log = logging.getLogger(__name__)

NUM_PADS = 8
MODES = ("oneshot", "toggle", "hold", "loop")
MAX_PAD_VOICES = 24
FADE_SECONDS = 0.006
# Seconds of audio queued ahead of the speakers (WASAPI). Enough headroom that a
# busy GUI thread holding the GIL can't starve the callback, tight enough for pads.
OUTPUT_LATENCY = 0.03
LIMIT = 0.95                  # limiter ceiling so stacked pads don't hard-clip
LIMITER_RELEASE = 0.12        # seconds

ROLE_HEADPHONES = "headphones"
ROLE_MIC = "mic"
ROLE_BOTH = "both"
VIRTUAL_OUTPUT_HINTS = ("cable", "voicemeeter", "virtual")


@dataclass
class PadSettings:
    volume: float = 0.8
    mode: str = "oneshot"
    to_headphones: bool = True
    to_mic: bool = True


class PadSound:
    """A decoded sound, kept only at the sample rates the open outputs use."""

    def __init__(self, data: np.ndarray, rate: int, path: str):
        self.path = path
        self.duration = data.shape[0] / float(rate)
        self.truncated = self.duration >= MAX_SECONDS - 0.05
        self._cache: Dict[int, np.ndarray] = {rate: data}
        self._lock = threading.Lock()

    def cached(self, rate: int) -> Optional[np.ndarray]:
        with self._lock:
            return self._cache.get(rate)

    def at_rate(self, rate: int) -> np.ndarray:
        """Frames at `rate`, resampling (slow for long sounds: worker thread only)."""
        with self._lock:
            out = self._cache.get(rate)
            if out is not None:
                return out
            src_rate = max(self._cache)
            src = self._cache[src_rate]
        out = resample(src, src_rate, rate)
        with self._lock:
            return self._cache.setdefault(rate, out)

    def trim(self, rates) -> None:
        """Drop copies no open output uses (keeps at least one to resample from)."""
        rates = set(rates)
        with self._lock:
            if rates & set(self._cache):
                for r in list(self._cache):
                    if r not in rates:
                        del self._cache[r]


class _Voice:
    __slots__ = ("pad", "data", "pos", "loop", "fade_left")

    def __init__(self, pad: int, data: np.ndarray, loop: bool):
        self.pad = pad
        self.data = data
        self.pos = 0
        self.loop = loop
        self.fade_left = None


class _Synth:
    """Small polyphonic synth for the piano keys (sine with a couple of harmonics)."""

    MAX_VOICES = 16

    def __init__(self, rate: int):
        self.rate = rate
        self.voices: List[list] = []  # [note, phase, inc, amp, env, releasing]
        self.attack_step = 1.0 / max(1, int(0.005 * rate))
        self.release_step = 1.0 / max(1, int(0.18 * rate))

    def note_on(self, note: int, velocity: int) -> None:
        self.note_off(note)
        if len(self.voices) >= self.MAX_VOICES:
            self.voices.pop(0)
        freq = 440.0 * 2.0 ** ((note - 69) / 12.0)
        amp = 0.18 * (0.25 + 0.75 * velocity / 127.0)
        self.voices.append([note, 0.0, 2.0 * math.pi * freq / self.rate, amp, 0.0, False])

    def note_off(self, note: int) -> None:
        for v in self.voices:
            if v[0] == note:
                v[5] = True

    def all_off(self) -> None:
        for v in self.voices:
            v[5] = True

    def render(self, buf: np.ndarray, frames: int, gain: float) -> None:
        if not self.voices:
            return
        t = np.arange(1, frames + 1, dtype=np.float64)
        alive = []
        for v in self.voices:
            _, phase, inc, amp, env, releasing = v
            ph = phase + inc * t
            wave = np.sin(ph) + 0.3 * np.sin(2 * ph) + 0.12 * np.sin(3 * ph)
            if releasing:
                envs = np.maximum(env - self.release_step * t, 0.0)
            else:
                envs = np.minimum(env + self.attack_step * t, 1.0)
            buf += (wave * envs * (amp * gain)).astype(np.float32)[:, None]
            v[1] = float(ph[-1] % (2.0 * math.pi))
            v[4] = float(envs[-1])
            if not (releasing and v[4] <= 0.0):
                alive.append(v)
        self.voices = alive


class OutputBus:
    """One PortAudio output stream with its own voices and sound bank."""

    def __init__(self, engine: "AudioEngine", role: str, device: Optional[int], name: str):
        self.engine = engine
        self.role = role
        self.device = device
        self.name = name
        self.commands = collections.deque()
        self.bank: List[Optional[np.ndarray]] = [None] * NUM_PADS
        self.voices: List[_Voice] = []
        self.synth: Optional[_Synth] = None
        self.samplerate = 0
        self.fade_frames = 1
        self.stream = None
        self.error = ""
        self.peak = 0.0
        self.limiter_gain = 1.0
        self._release_per_frame = 1.0
        self._buf = np.zeros((4096, 2), dtype=np.float32)

    # ── lifecycle ───────────────────────────────────────────────

    def open(self) -> bool:
        if sd is None:
            self.error = "Audio library missing (PortAudio)."
            return False
        last_error = "No usable output device."
        for device, rate, extra in _stream_attempts(self.device):
            stream = None
            try:
                info = sd.query_devices(device if device is not None else sd.default.device[1])
                channels = max(1, min(2, int(info["max_output_channels"])))
                latency = OUTPUT_LATENCY
                if "WASAPI" not in _host_api_name(device):
                    latency = max(OUTPUT_LATENCY, float(info["default_low_output_latency"]))
                stream = sd.OutputStream(
                    device=device, samplerate=rate, channels=channels, dtype="float32",
                    latency=latency, extra_settings=extra, callback=self._callback,
                )
                self._prepare(int(stream.samplerate))
                stream.start()
            except Exception as e:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
                last_error = str(e)
                log.info("Output %s: device %s @ %s Hz failed: %s", self.role, device, rate, e)
                continue
            self.stream = stream
            log.info("Output %s open: %s @ %d Hz (%s)", self.role, self.name, self.samplerate,
                     _host_api_name(device))
            return True
        self.error = last_error
        return False

    def _prepare(self, rate: int) -> None:
        """Set the rate and fill the bank with what is already resampled (never resamples)."""
        self.samplerate = int(rate)
        self.fade_frames = max(1, int(FADE_SECONDS * rate))
        self._release_per_frame = 1.0 / (LIMITER_RELEASE * rate)
        self.bank = [s.cached(self.samplerate) if s is not None else None for s in self.engine.sounds]
        self.voices = []
        self.commands.clear()
        self.limiter_gain = 1.0
        self.synth = _Synth(self.samplerate) if self.role in (ROLE_HEADPHONES, ROLE_BOTH) else None

    def close(self) -> None:
        stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.abort()
                stream.close()
            except Exception:
                pass

    @property
    def running(self) -> bool:
        try:
            return self.stream is not None and bool(self.stream.active)
        except Exception:
            return False

    # ── audio thread ────────────────────────────────────────────

    def _callback(self, outdata, frames, time_info, status) -> None:
        try:
            self.mix(outdata, frames)
        except Exception:
            outdata.fill(0)
            log.exception("Audio callback error on %s output", self.role)

    def mix(self, outdata: np.ndarray, frames: int) -> None:
        self._process_commands()
        if self._buf.shape[0] < frames:
            self._buf = np.zeros((frames, 2), dtype=np.float32)
        buf = self._buf[:frames]
        buf.fill(0.0)

        if self.voices:
            engine = self.engine
            settings = engine.settings
            for v in self.voices:
                if v.fade_left is None and not engine.routes(v.pad, self.role):
                    v.fade_left = self.fade_frames      # routing switched off while playing
            self.voices = [v for v in self.voices
                           if self._render_voice(v, buf, frames, settings[v.pad].volume)]
            gain = engine.pad_gain(self.role)
            if gain != 1.0:
                buf *= gain
        if self.synth is not None and self.synth.voices:
            self.synth.render(buf, frames, self.engine.keys_gain())

        if frames:
            self._limit(buf, frames)
        if outdata.shape[1] == 1:
            outdata[:, 0] = buf.mean(axis=1)
        else:
            outdata[:, :2] = buf
            if outdata.shape[1] > 2:
                outdata[:, 2:] = 0.0

    def _limit(self, buf: np.ndarray, frames: int) -> None:
        """Peak limiter: instant attack, smooth release, then a hard safety clip."""
        peak = float(np.max(np.abs(buf)))
        wanted = 1.0 if peak <= LIMIT else LIMIT / peak
        old = self.limiter_gain
        if wanted < old:
            buf *= wanted
            new = wanted
        else:
            new = min(wanted, old + self._release_per_frame * frames)
            if new != 1.0 or old != 1.0:
                buf *= np.linspace(old, new, frames, dtype=np.float32)[:, None]
        self.limiter_gain = new
        np.clip(buf, -1.0, 1.0, out=buf)
        out_peak = min(1.0, peak * new)
        if out_peak > self.peak:
            self.peak = out_peak

    def _render_voice(self, v: _Voice, buf: np.ndarray, frames: int, volume: float) -> bool:
        data = v.data
        total = data.shape[0]
        if total == 0:
            return False
        out = 0
        while out < frames:
            if v.pos >= total:
                if not v.loop:
                    return False
                v.pos = 0
            n = min(frames - out, total - v.pos)
            chunk = data[v.pos:v.pos + n]
            if v.fade_left is None:
                buf[out:out + n] += chunk * volume
            else:
                n = min(n, v.fade_left)
                env = np.arange(v.fade_left, v.fade_left - n, -1, dtype=np.float32)
                env *= volume / self.fade_frames
                buf[out:out + n] += chunk[:n] * env[:, None]
                v.fade_left -= n
                if v.fade_left <= 0:
                    return False
            v.pos += n
            out += n
        return v.loop or v.pos < total

    def _process_commands(self) -> None:
        q = self.commands
        while q:
            try:
                cmd = q.popleft()
            except IndexError:
                break
            op = cmd[0]
            if op == "start":
                _, pad, loop = cmd
                self._fade_pad(pad)
                data = self.bank[pad]
                if data is not None and self.engine.routes(pad, self.role):
                    if len(self.voices) >= MAX_PAD_VOICES:
                        self.voices.pop(0)
                    self.voices.append(_Voice(pad, data, loop))
            elif op == "stop":
                self._fade_pad(cmd[1])
            elif op == "stop_all":
                for v in self.voices:
                    if v.fade_left is None:
                        v.fade_left = self.fade_frames
                if self.synth is not None:
                    self.synth.all_off()
            elif op == "set":
                _, pad, data = cmd
                self.bank[pad] = data
                self._fade_pad(pad)
            elif op == "fill":
                _, pad, data = cmd
                if self.bank[pad] is None:       # late resample: don't cut a playing sound
                    self.bank[pad] = data
            elif op == "note_on" and self.synth is not None:
                self.synth.note_on(cmd[1], cmd[2])
            elif op == "note_off" and self.synth is not None:
                self.synth.note_off(cmd[1])

    def _fade_pad(self, pad: int) -> None:
        for v in self.voices:
            if v.pad == pad and v.fade_left is None:
                v.fade_left = self.fade_frames


class _Worker:
    """One background thread running jobs in order (decode, resample, copy)."""

    def __init__(self):
        self._jobs: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="audio-loader", daemon=True)
        self._thread.start()

    def submit(self, job: Callable[[], None]) -> None:
        self._jobs.put(job)

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                job()
            except Exception:
                log.exception("Background audio job failed")


class AudioEngine(QObject):
    """Owns the output buses, the pad sounds and the play state of every pad."""

    pad_loaded = Signal(int, bool, str, str)   # pad, ok, path (ok) / message (failed), request path
    _load_done = Signal(int, int, object, str, str)
    _rates_ready = Signal(int, object)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.settings = [PadSettings() for _ in range(NUM_PADS)]
        self.sounds: List[Optional[PadSound]] = [None] * NUM_PADS
        self.levels = {"headphones": 0.8, "mic": 0.8, "keys": 0.6, "master": 1.0}
        self._buses: tuple = ()
        self._lock = threading.Lock()
        self._play_until = [0.0] * NUM_PADS
        self._started = [0.0] * NUM_PADS
        self._tokens = [0] * NUM_PADS
        self._worker = _Worker()
        self._load_done.connect(self._on_load_done)
        self._rates_ready.connect(self._on_rates_ready)

    # ── outputs ─────────────────────────────────────────────────

    @staticmethod
    def list_outputs() -> List[str]:
        """Output device names, one entry per device (preferring the WASAPI list on Windows)."""
        if sd is None:
            return []
        try:
            api = _preferred_host_api()
            names = []
            for dev in sd.query_devices():
                if dev["max_output_channels"] > 0 and (api is None or dev["hostapi"] == api):
                    if dev["name"] not in names:
                        names.append(dev["name"])
            return names
        except Exception as e:
            log.warning("Could not list audio devices: %s", e)
            return []

    @staticmethod
    def find_output(fragment: str) -> Optional[str]:
        for name in AudioEngine.list_outputs():
            if fragment.lower() in name.lower():
                return name
        return None

    def rescan_devices(self) -> None:
        """Let PortAudio see devices plugged in/out since start (closes the outputs)."""
        self.close()
        if sd is None:
            return
        try:
            sd._terminate()
            sd._initialize()
        except Exception as e:
            log.warning("Rescanning audio devices failed: %s", e)

    def set_outputs(self, headphones: Optional[str], mic: Optional[str]) -> Dict[str, str]:
        """(Re)open the outputs. headphones=None means system default; mic=None/'' means off.

        Returns {role: message} for outputs that failed to open or were adjusted.
        """
        self.close()
        errors = {}
        hp_index = _resolve_output(headphones) if headphones else _default_output()
        hp_name = headphones or "System default"
        if headphones and hp_index is None:
            errors[ROLE_HEADPHONES] = f"'{headphones}' was not found; using the system default."
            hp_index, hp_name = _default_output(), "System default"
        mic_index = _resolve_output(mic) if mic else None
        if mic and mic_index is None:
            errors[ROLE_MIC] = f"'{mic}' was not found."

        if not headphones and hp_index is not None and _is_virtual(_device_name(hp_index)):
            # Installing VB-Cable often makes it Windows' default playback device.
            real = _first_real_output()
            if real is not None:
                hp_index, hp_name = real, _device_name(real)
                errors[ROLE_HEADPHONES] = (f"Windows' default playback device is a virtual cable, so "
                                           f"you'll hear the pads on '{hp_name}'. Pick your headphones "
                                           f"above if that's wrong.")
            else:
                errors[ROLE_HEADPHONES] = ("Windows' default playback device is a virtual cable. "
                                           "Pick your real headphones above.")

        if mic_index is not None and mic_index == hp_index:
            buses = [OutputBus(self, ROLE_BOTH, hp_index, hp_name)]
        else:
            buses = [OutputBus(self, ROLE_HEADPHONES, hp_index, hp_name)]
            if mic_index is not None:
                buses.append(OutputBus(self, ROLE_MIC, mic_index, mic))

        opened = []
        for bus in buses:
            if bus.open():
                opened.append(bus)
            else:
                role = ROLE_HEADPHONES if bus.role == ROLE_BOTH else bus.role
                errors[role] = f"Couldn't open '{bus.name}': {bus.error}"
        with self._lock:
            self._buses = tuple(opened)
        self._fill_missing_rates()
        return errors

    def close(self) -> None:
        with self._lock:
            buses, self._buses = self._buses, ()
            self._play_until = [0.0] * NUM_PADS
        for bus in buses:
            bus.close()

    def lost_outputs(self) -> List[str]:
        """Roles whose stream stopped by itself (device unplugged, format changed ...)."""
        return [bus.role for bus in self._buses if not bus.running]

    def output_state(self) -> Dict[str, dict]:
        """{role: {'running': bool, 'peak': float}} — reading resets the peaks."""
        state = {}
        for bus in self._buses:
            peak, bus.peak = bus.peak, 0.0
            roles = (ROLE_HEADPHONES, ROLE_MIC) if bus.role == ROLE_BOTH else (bus.role,)
            for role in roles:
                state[role] = {"running": bus.running, "peak": peak}
        return state

    # ── gains (read by the audio threads) ───────────────────────

    def pad_gain(self, role: str) -> float:
        lv = self.levels
        key = "mic" if role == ROLE_MIC else "headphones"
        return lv[key] * lv["master"]

    def keys_gain(self) -> float:
        return self.levels["keys"] * self.levels["master"]

    def routes(self, pad: int, role: str) -> bool:
        s = self.settings[pad]
        if role == ROLE_HEADPHONES:
            return s.to_headphones
        if role == ROLE_MIC:
            return s.to_mic
        return s.to_headphones or s.to_mic

    # ── pads ────────────────────────────────────────────────────

    def trigger_pad(self, pad: int) -> str:
        """Hit a pad. Returns 'started', 'stopped' or 'empty'. Safe from any thread."""
        if not 0 <= pad < NUM_PADS:
            return "empty"
        with self._lock:
            sound = self.sounds[pad]
            if sound is None:
                return "empty"
            mode = self.settings[pad].mode
            now = time.monotonic()
            if mode in ("toggle", "loop") and now < self._play_until[pad]:
                self._send(("stop", pad))
                self._play_until[pad] = 0.0
                return "stopped"
            loop = mode == "loop"
            self._send(("start", pad, loop))
            self._started[pad] = now
            self._play_until[pad] = math.inf if loop else now + sound.duration
            return "started"

    def release_pad(self, pad: int) -> None:
        if not 0 <= pad < NUM_PADS:
            return
        with self._lock:
            if self.settings[pad].mode == "hold" and self._play_until[pad] > 0.0:
                self._send(("stop", pad))
                self._play_until[pad] = 0.0

    def stop_pad(self, pad: int) -> None:
        with self._lock:
            self._send(("stop", pad))
            self._play_until[pad] = 0.0

    def stop_all(self) -> None:
        with self._lock:
            self._send(("stop_all",))
            self._play_until = [0.0] * NUM_PADS

    def is_playing(self, pad: int) -> bool:
        return time.monotonic() < self._play_until[pad]

    def progress(self, pad: int) -> float:
        """0..1 position of the pad's current playback (0 when idle)."""
        sound = self.sounds[pad]
        if sound is None or not self.is_playing(pad) or sound.duration <= 0:
            return 0.0
        elapsed = time.monotonic() - self._started[pad]
        return (elapsed % sound.duration) / sound.duration

    def _send(self, cmd: tuple) -> None:
        for bus in self._buses:
            bus.commands.append(cmd)

    # ── keyboard synth ──────────────────────────────────────────

    def note_on(self, note: int, velocity: int = 100) -> None:
        self._send(("note_on", int(note), int(velocity)))

    def note_off(self, note: int) -> None:
        self._send(("note_off", int(note)))

    # ── loading sounds ──────────────────────────────────────────

    def load_pad(self, pad: int, path: str,
                 import_fn: Optional[Callable[[Path, np.ndarray, int], Path]] = None) -> None:
        """Decode `path` on the worker thread, then put it on the pad.

        import_fn(path, frames, rate) (optional) runs on the worker after a successful
        decode and returns the path to remember (e.g. a copy in the sound library).
        Emits pad_loaded(pad, ok, stored path or error message, requested path).
        """
        self._tokens[pad] += 1
        token = self._tokens[pad]

        def job():
            if token != self._tokens[pad]:
                return                      # replaced before it started
            try:
                data, rate = decode_file(path)
                sound = PadSound(data, rate, str(path))
                for bus in self._buses:
                    sound.at_rate(bus.samplerate)
                stored = Path(path)
                if import_fn is not None:
                    stored = import_fn(stored, data, rate)
                sound.path = str(stored)
                self._load_done.emit(pad, token, sound, "", str(path))
            except DecodeError as e:
                self._load_done.emit(pad, token, None, str(e), str(path))
            except MemoryError:
                self._load_done.emit(pad, token, None, "This file is too big to load.", str(path))
            except Exception as e:
                log.exception("Loading %s failed", path)
                self._load_done.emit(pad, token, None, f"Couldn't load this file ({e}).", str(path))

        self._worker.submit(job)

    @Slot(int, int, object, str, str)
    def _on_load_done(self, pad: int, token: int, sound, message: str, requested: str) -> None:
        if token != self._tokens[pad]:
            return  # a newer load or a clear replaced this one
        if sound is None:
            self.pad_loaded.emit(pad, False, message, requested)
            return
        self._install(pad, sound)
        self.pad_loaded.emit(pad, True, sound.path, requested)

    def clear_pad(self, pad: int) -> None:
        self._tokens[pad] += 1
        self._install(pad, None)

    def _install(self, pad: int, sound: Optional[PadSound]) -> None:
        with self._lock:
            self.sounds[pad] = sound
            self._play_until[pad] = 0.0
            for bus in self._buses:
                data = sound.cached(bus.samplerate) if sound else None
                bus.commands.append(("set", pad, data))
        if sound is not None:
            self._fill_missing_rates([pad])

    def _fill_missing_rates(self, pads=None) -> None:
        """Resample (on the worker) for any open output rate a sound lacks."""
        rates = {bus.samplerate for bus in self._buses}
        for pad in (range(NUM_PADS) if pads is None else pads):
            sound = self.sounds[pad]
            if sound is None:
                continue
            if all(sound.cached(r) is not None for r in rates):
                sound.trim(rates)
                continue

            def job(pad=pad, sound=sound, rates=rates):
                for r in rates:
                    sound.at_rate(r)
                self._rates_ready.emit(pad, sound)

            self._worker.submit(job)

    @Slot(int, object)
    def _on_rates_ready(self, pad: int, sound) -> None:
        if self.sounds[pad] is not sound:
            return
        rates = set()
        for bus in self._buses:
            data = sound.cached(bus.samplerate)
            rates.add(bus.samplerate)
            if data is not None:
                bus.commands.append(("fill", pad, data))
        sound.trim(rates)


# ── PortAudio helpers ───────────────────────────────────────────


def _preferred_host_api() -> Optional[int]:
    """WASAPI on Windows (low latency, full device names); otherwise the default API."""
    try:
        for i, api in enumerate(sd.query_hostapis()):
            if "WASAPI" in api["name"]:
                return i
        return sd.default.hostapi
    except Exception:
        return None


def _host_api_name(device: Optional[int]) -> str:
    try:
        idx = device if device is not None else sd.default.device[1]
        return sd.query_hostapis(sd.query_devices(idx)["hostapi"])["name"]
    except Exception:
        return "?"


def _device_name(index: Optional[int]) -> str:
    try:
        return sd.query_devices(index)["name"] if index is not None else ""
    except Exception:
        return ""


def _is_virtual(name: str) -> bool:
    return any(h in name.lower() for h in VIRTUAL_OUTPUT_HINTS)


def _default_output() -> Optional[int]:
    if sd is None:
        return None
    try:
        api = _preferred_host_api()
        if api is not None:
            idx = sd.query_hostapis(api)["default_output_device"]
            if idx is not None and idx >= 0:
                return idx
        idx = sd.default.device[1]
        return idx if idx is not None and idx >= 0 else None
    except Exception:
        return None


def _first_real_output() -> Optional[int]:
    """A physical output (headphones/speakers first) in the preferred host API."""
    try:
        api = _preferred_host_api()
        outputs = [(i, d["name"]) for i, d in enumerate(sd.query_devices())
                   if d["max_output_channels"] > 0 and (api is None or d["hostapi"] == api)
                   and not _is_virtual(d["name"])]
    except Exception:
        return None
    for hint in ("headphone", "headset", "speaker"):
        for i, name in outputs:
            if hint in name.lower():
                return i
    return outputs[0][0] if outputs else None


def _resolve_output(name: str) -> Optional[int]:
    """Device index for a saved name: exact match in the preferred API, then looser matches."""
    if sd is None or not name:
        return None
    try:
        devices = list(enumerate(sd.query_devices()))
    except Exception:
        return None
    api = _preferred_host_api()
    outputs = [(i, d) for i, d in devices if d["max_output_channels"] > 0]
    preferred = [(i, d) for i, d in outputs if api is None or d["hostapi"] == api]
    for pool in (preferred, outputs):
        for i, d in pool:
            if d["name"] == name:
                return i
    for pool in (preferred, outputs):
        for i, d in pool:
            if d["name"].startswith(name) or name.startswith(d["name"]):
                return i
    return None


def _stream_attempts(device: Optional[int]):
    """Ways to open `device`, best first: native rate, WASAPI auto-convert, same device on MME."""
    try:
        info = sd.query_devices(device if device is not None else sd.default.device[1])
    except Exception:
        return
    rate = int(info["default_samplerate"] or 48000)
    yield device, rate, None
    if "WASAPI" in _host_api_name(device):
        try:
            yield device, 48000, sd.WasapiSettings(auto_convert=True)
        except TypeError:
            pass
    for i, d in enumerate(sd.query_devices()):
        if i == device or d["max_output_channels"] <= 0:
            continue
        other_api = sd.query_hostapis(d["hostapi"])["name"]
        if "MME" in other_api and (info["name"].startswith(d["name"]) or d["name"].startswith(info["name"])):
            yield i, int(d["default_samplerate"] or 44100), None
            break
