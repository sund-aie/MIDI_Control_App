"""
PandaMINI Core Engine - Audio Engine (Rewritten)
Bulletproof audio playback with synchronous loading, default drum sounds,
and proper WASAPI/MME device handling.
"""
import numpy as np
import sounddevice as sd
import soundfile as sf
from pathlib import Path
from typing import Dict, List, Optional, Any
from PySide6.QtCore import QObject, Signal
import threading


class AudioEngine(QObject):
    """
    Audio engine with reliable pad playback.
    
    Key design decisions:
    - Samples are loaded SYNCHRONOUSLY to guarantee they are ready before playback
    - Built-in default drum sounds so pads always produce audio
    - Buffer size adapts to actual callback frames (not pre-allocated)
    - WASAPI used only when device supports it, with MME fallback
    """
    
    stream_started = Signal()
    stream_stopped = Signal()
    audio_error = Signal(str)
    vu_update = Signal(float)
    pad_loaded = Signal(int, str)  # pad_index, path
    
    NUM_PADS = 8
    
    def __init__(self, config_manager: Optional[Any] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._config_manager = config_manager
        
        self._sample_rate = 44100  # Use 44100 for maximum compatibility
        self._blocksize = 512
        self._latency = 'low'
        
        # Voice management (import lazily to avoid circular imports)
        from app.audio.voice import VoiceManager
        self._voice_manager = VoiceManager()
        
        # Sample loader (kept for API compatibility but we load synchronously)
        from app.audio.loader import SampleLoader
        self._sample_loader = SampleLoader()
        
        # Loaded samples for sampler voices
        self._sampler_samples: Dict[int, np.ndarray] = {}
        
        # Soundboard pad samples and paths
        self._pad_samples: Dict[int, np.ndarray] = {}
        self._pad_sample_paths: Dict[int, str] = {}
        
        # Play positions (one set — plays to ALL active streams)
        self._pad_play_pos: Dict[int, int] = {i: 0 for i in range(self.NUM_PADS)}
        self._pad_active: Dict[int, bool] = {i: False for i in range(self.NUM_PADS)}
        self._pad_gate_held: Dict[int, bool] = {i: False for i in range(self.NUM_PADS)}
        
        # For backward compat with UI code that reads these
        self._pad_active_mon = self._pad_active
        self._pad_active_mic = self._pad_active
        self._pad_play_pos_mon = self._pad_play_pos
        self._pad_play_pos_mic = self._pad_play_pos
        
        # Pad config
        self._pad_volumes: Dict[int, float] = {i: 1.0 for i in range(self.NUM_PADS)}
        self._pad_modes: Dict[int, str] = {i: 'oneshot' for i in range(self.NUM_PADS)}
        self._pad_route_mic: Dict[int, bool] = {i: True for i in range(self.NUM_PADS)}
        self._pad_route_mon: Dict[int, bool] = {i: True for i in range(self.NUM_PADS)}
        
        # Stream references
        self._sampler_stream: Optional[sd.OutputStream] = None
        self._soundboard_stream: Optional[sd.OutputStream] = None
        
        # Output devices
        self._sampler_device: Optional[int] = None
        self._soundboard_device: Optional[int] = None
        
        # Level metering
        self._current_level = 0.0
        self._level_lock = threading.Lock()
        
        self._is_running = False
        
        # Generate built-in default drum sounds
        self._generate_default_sounds()
        
        # Load pad configs from file
        if self._config_manager:
            self._load_pads_from_config()
    
    # ──────────────────────────────────────────────
    # Default sounds — pads always produce audio
    # ──────────────────────────────────────────────
    
    def _generate_default_sounds(self) -> None:
        """Generate 8 built-in drum sounds so pads work immediately."""
        sr = self._sample_rate
        
        # Pad 1: Kick drum
        t = np.linspace(0, 0.4, int(sr * 0.4), dtype=np.float32)
        freq = 150 * np.exp(-t * 8) + 40
        phase = np.cumsum(freq / sr) * 2 * np.pi
        kick = np.sin(phase) * np.exp(-t * 6) * 0.9
        
        # Pad 2: Snare
        t = np.linspace(0, 0.25, int(sr * 0.25), dtype=np.float32)
        noise = np.random.randn(len(t)).astype(np.float32)
        tone = np.sin(2 * np.pi * 200 * t) * np.exp(-t * 20)
        snare = (noise * 0.4 + tone * 0.6) * np.exp(-t * 10) * 0.8
        
        # Pad 3: Closed hi-hat
        t = np.linspace(0, 0.08, int(sr * 0.08), dtype=np.float32)
        hh = np.random.randn(len(t)).astype(np.float32) * np.exp(-t * 40) * 0.6
        
        # Pad 4: Open hi-hat
        t = np.linspace(0, 0.3, int(sr * 0.3), dtype=np.float32)
        ohh = np.random.randn(len(t)).astype(np.float32) * np.exp(-t * 8) * 0.5
        
        # Pad 5: Clap
        t = np.linspace(0, 0.2, int(sr * 0.2), dtype=np.float32)
        clap_env = np.zeros_like(t)
        for burst_start in [0.0, 0.015, 0.03]:
            mask = t >= burst_start
            clap_env[mask] += np.exp(-(t[mask] - burst_start) * 30)
        clap = np.random.randn(len(t)).astype(np.float32) * clap_env * 0.3
        
        # Pad 6: Tom
        t = np.linspace(0, 0.35, int(sr * 0.35), dtype=np.float32)
        tom_freq = 120 * np.exp(-t * 5) + 60
        tom_phase = np.cumsum(tom_freq / sr) * 2 * np.pi
        tom = np.sin(tom_phase) * np.exp(-t * 7) * 0.8
        
        # Pad 7: Rim shot
        t = np.linspace(0, 0.06, int(sr * 0.06), dtype=np.float32)
        rim = (np.sin(2 * np.pi * 800 * t) * 0.5 + 
               np.random.randn(len(t)).astype(np.float32) * 0.3) * np.exp(-t * 50) * 0.7
        
        # Pad 8: Cymbal crash
        t = np.linspace(0, 0.8, int(sr * 0.8), dtype=np.float32)
        cymbal = np.random.randn(len(t)).astype(np.float32) * np.exp(-t * 3) * 0.4
        
        defaults = [kick, snare, hh, ohh, clap, tom, rim, cymbal]
        default_names = ["Kick", "Snare", "HiHat-C", "HiHat-O", "Clap", "Tom", "Rim", "Crash"]
        
        for i, (sound, name) in enumerate(zip(defaults, default_names)):
            sound = sound.astype(np.float32)
            # Only set if no user sample is already loaded
            if i not in self._pad_samples:
                self._pad_samples[i] = sound
                self._pad_sample_paths[i] = f"(Built-in: {name})"
        
        print(f"[AudioEngine] Generated {len(defaults)} built-in drum sounds")
    
    # ──────────────────────────────────────────────
    # Config loading
    # ──────────────────────────────────────────────
    
    def _load_pads_from_config(self) -> None:
        """Load pad settings from ConfigManager on startup."""
        for i in range(self.NUM_PADS):
            vol = self._config_manager.get('pads', 'volumes', i, default=1.0)
            self._pad_volumes[i] = float(vol)
            
            mode = self._config_manager.get('pads', 'modes', i, default='oneshot')
            self._pad_modes[i] = str(mode)
            
            mic = self._config_manager.get('pads', 'route_mic', i, default=True)
            self._pad_route_mic[i] = bool(mic)
            
            mon = self._config_manager.get('pads', 'route_mon', i, default=True)
            self._pad_route_mon[i] = bool(mon)
            
            # Load user sample if path exists (synchronously!)
            path = self._config_manager.get('pads', 'samples', i)
            if path and Path(path).exists():
                self._load_sample_sync(i, path)
    
    # ──────────────────────────────────────────────
    # Properties
    # ──────────────────────────────────────────────
    
    @property
    def voice_manager(self):
        return self._voice_manager
    
    @property
    def sample_loader(self):
        return self._sample_loader
    
    # ──────────────────────────────────────────────
    # Device management
    # ──────────────────────────────────────────────
    
    def get_available_devices(self) -> List[Dict]:
        """Get list of available audio output devices."""
        try:
            devices = sd.query_devices()
            output_devices = []
            for i, dev in enumerate(devices):
                if dev['max_output_channels'] > 0:
                    output_devices.append({
                        'index': i,
                        'name': dev['name'],
                        'channels': dev['max_output_channels'],
                        'sample_rate': int(dev['default_samplerate']),
                    })
            return output_devices
        except Exception as e:
            self.audio_error.emit(f"Error querying devices: {e}")
            return []
    
    def _resolve_device(self, device_name_or_index) -> Optional[int]:
        """Resolve a device name string to its sounddevice index."""
        if device_name_or_index is None:
            return None
        if isinstance(device_name_or_index, int):
            return device_name_or_index
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if dev['max_output_channels'] > 0 and device_name_or_index in dev['name']:
                    return i
        except Exception:
            pass
        return None
    
    def _is_wasapi_device(self, device_index: int) -> bool:
        """Check if a device belongs to the WASAPI host API."""
        if device_index is None:
            return False
        try:
            dev_info = sd.query_devices(device_index)
            host_api = sd.query_hostapis(dev_info['hostapi'])
            return 'WASAPI' in host_api['name']
        except Exception:
            return False
    
    # ──────────────────────────────────────────────
    # Stream management
    # ──────────────────────────────────────────────
    
    def _open_stream(self, device_idx, callback, label: str) -> Optional[sd.OutputStream]:
        """Try to open an output stream, with WASAPI fallback to MME."""
        # Attempt 1: with WASAPI if applicable
        if device_idx is not None and self._is_wasapi_device(device_idx):
            try:
                extra = sd.WasapiSettings(exclusive=False)
                stream = sd.OutputStream(
                    device=device_idx,
                    samplerate=self._sample_rate,
                    blocksize=self._blocksize,
                    latency=self._latency,
                    channels=2,
                    dtype=np.float32,
                    extra_settings=extra,
                    callback=callback,
                )
                stream.start()
                print(f"[AudioEngine] {label} stream started (WASAPI) on device {device_idx}")
                return stream
            except Exception as e:
                print(f"[AudioEngine] {label} WASAPI failed: {e}")
        
        # Attempt 2: plain stream (no WASAPI settings)
        try:
            stream = sd.OutputStream(
                device=device_idx,
                samplerate=self._sample_rate,
                blocksize=self._blocksize,
                latency=self._latency,
                channels=2,
                dtype=np.float32,
                callback=callback,
            )
            stream.start()
            print(f"[AudioEngine] {label} stream started (MME) on device {device_idx}")
            return stream
        except Exception as e:
            print(f"[AudioEngine] {label} MME also failed: {e}")
        
        # Attempt 3: let sounddevice pick everything (no device, no samplerate)
        try:
            stream = sd.OutputStream(
                channels=2,
                dtype=np.float32,
                callback=callback,
            )
            stream.start()
            self._sample_rate = int(stream.samplerate)
            print(f"[AudioEngine] {label} stream started (auto) sr={self._sample_rate}")
            return stream
        except Exception as e:
            print(f"[AudioEngine] {label} auto-config also failed: {e}")
            return None
    
    def start_streams(self, sampler_device=None, soundboard_device=None) -> bool:
        """Start audio output streams."""
        if self._is_running:
            return True
        
        sampler_idx = self._resolve_device(sampler_device)
        soundboard_idx = self._resolve_device(soundboard_device)
        
        self._sampler_device = sampler_idx
        self._soundboard_device = soundboard_idx
        
        # Start sampler/monitor stream (this is the main audio output)
        self._sampler_stream = self._open_stream(sampler_idx, self._sampler_callback, "Sampler")
        
        # Start soundboard/discord stream only if it's a different device
        if soundboard_idx is not None and soundboard_idx != sampler_idx:
            self._soundboard_stream = self._open_stream(soundboard_idx, self._soundboard_callback, "Soundboard")
        else:
            self._soundboard_stream = None
            print("[AudioEngine] Soundboard shares sampler device, skipping separate stream")
        
        if self._sampler_stream:
            self._is_running = True
            self.stream_started.emit()
            print(f"[AudioEngine] Engine is RUNNING. Pads loaded: {list(self._pad_samples.keys())}")
            return True
        else:
            self.audio_error.emit("Failed to start audio stream")
            return False
    
    def stop_streams(self) -> None:
        """Stop both output streams."""
        self._is_running = False
        for stream_attr in ('_sampler_stream', '_soundboard_stream'):
            stream = getattr(self, stream_attr, None)
            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass
                setattr(self, stream_attr, None)
        self.stream_stopped.emit()
    
    # ──────────────────────────────────────────────
    # Pad triggering
    # ──────────────────────────────────────────────
    
    def trigger_pad(self, pad_index: int) -> None:
        """Trigger a soundboard pad playback."""
        if not (0 <= pad_index < self.NUM_PADS):
            return
        
        has_sample = pad_index in self._pad_samples
        print(f"[AudioEngine] trigger_pad({pad_index}) has_sample={has_sample} running={self._is_running}")
        
        if not has_sample:
            return
        
        mode = self._pad_modes.get(pad_index, 'oneshot')
        
        if mode == 'loop' and self._pad_active[pad_index]:
            # Toggle off
            self._pad_active[pad_index] = False
        else:
            self._pad_play_pos[pad_index] = 0
            self._pad_active[pad_index] = True
            if mode == 'gate':
                self._pad_gate_held[pad_index] = True
    
    def release_pad(self, pad_index: int) -> None:
        """Release a soundboard pad (for Gate mode)."""
        if 0 <= pad_index < self.NUM_PADS:
            self._pad_gate_held[pad_index] = False
            if self._pad_modes[pad_index] == 'gate':
                self._pad_active[pad_index] = False
    
    def trigger_synth_note(self, note: int, velocity: int) -> None:
        """Trigger a synth note."""
        self._voice_manager.note_on(note, velocity)
    
    def release_synth_note(self, note: int) -> None:
        """Release a synth note."""
        self._voice_manager.note_off(note)
    
    # ──────────────────────────────────────────────
    # Sample loading (SYNCHRONOUS — guaranteed ready)
    # ──────────────────────────────────────────────
    
    def _load_sample_sync(self, pad_index: int, file_path: str) -> bool:
        """Load an audio file synchronously. Returns True on success."""
        try:
            path = Path(file_path)
            if not path.exists():
                try:
                    print(f"[AudioEngine] File not found: {file_path}")
                except UnicodeEncodeError:
                    print("[AudioEngine] File not found (path contains special characters)")
                return False
            
            data, file_sr = sf.read(str(path), dtype='float32')
            
            # Convert stereo to mono
            if len(data.shape) > 1:
                data = data.mean(axis=1)
            
            # Resample if needed
            if file_sr != self._sample_rate:
                # Simple linear interpolation resampling
                ratio = self._sample_rate / file_sr
                new_len = int(len(data) * ratio)
                indices = np.linspace(0, len(data) - 1, new_len)
                data = np.interp(indices, np.arange(len(data)), data).astype(np.float32)
            
            # Normalize
            peak = np.max(np.abs(data))
            if peak > 0:
                data = data / peak * 0.9
            
            self._pad_samples[pad_index] = data
            self._pad_sample_paths[pad_index] = str(path)
            
            try:
                print(f"[AudioEngine] Loaded pad {pad_index}: {path.name} ({len(data)} samples, {len(data)/self._sample_rate:.2f}s)")
            except UnicodeEncodeError:
                print(f"[AudioEngine] Loaded pad {pad_index}: (unicode name) ({len(data)} samples)")
            return True
            
        except Exception as e:
            try:
                print(f"[AudioEngine] Failed to load {file_path}: {e}")
            except UnicodeEncodeError:
                print(f"[AudioEngine] Failed to load sample for pad {pad_index}: {e}")
            return False
    
    def load_pad_sample(self, pad_index: int, sample_path: str) -> None:
        """Load a sample for a drum pad (synchronously)."""
        if self._load_sample_sync(pad_index, sample_path):
            # Save to config (on main thread, safe for QTimer)
            if self._config_manager:
                self._config_manager.set(sample_path, 'pads', 'samples', pad_index)
            self.pad_loaded.emit(pad_index, sample_path)
    
    def load_sampler_sample(self, note: int, sample_path: str) -> None:
        """Load a sample for a specific MIDI note."""
        try:
            data, file_sr = sf.read(sample_path, dtype='float32')
            if len(data.shape) > 1:
                data = data.mean(axis=1)
            self._sampler_samples[note] = data
        except Exception as e:
            print(f"[AudioEngine] Failed to load sampler sample: {e}")
    
    # ──────────────────────────────────────────────
    # Pad configuration
    # ──────────────────────────────────────────────
    
    def set_pad_volume(self, pad_index: int, volume: float) -> None:
        if 0 <= pad_index < self.NUM_PADS:
            self._pad_volumes[pad_index] = volume
            if self._config_manager:
                self._config_manager.set(volume, 'pads', 'volumes', pad_index)
                
    def set_pad_mode(self, pad_index: int, mode: str) -> None:
        if 0 <= pad_index < self.NUM_PADS:
            self._pad_modes[pad_index] = mode
            if self._config_manager:
                self._config_manager.set(mode, 'pads', 'modes', pad_index)
                
    def set_pad_routing(self, pad_index: int, route_mic: bool, route_mon: bool) -> None:
        if 0 <= pad_index < self.NUM_PADS:
            self._pad_route_mic[pad_index] = route_mic
            self._pad_route_mon[pad_index] = route_mon
            if self._config_manager:
                self._config_manager.set(route_mic, 'pads', 'route_mic', pad_index)
                self._config_manager.set(route_mon, 'pads', 'route_mon', pad_index)
    
    # ──────────────────────────────────────────────
    # Audio callbacks
    # ──────────────────────────────────────────────
    
    def _sampler_callback(self, outdata: np.ndarray, frames: int,
                          time_info: dict, status: sd.CallbackFlags) -> None:
        """Main audio callback — mixes synth voices and pad samples."""
        if not self._is_running:
            outdata.fill(0)
            return
        
        # Create mix buffer matching actual frame count
        mix = np.zeros(frames, dtype=np.float32)
        
        # --- Synth voices ---
        active_voices = 0
        for voice in self._voice_manager._voices:
            if not voice.is_active:
                continue
            active_voices += 1
            note_diff = voice.note - 60
            step = pow(2.0, note_diff / 12.0)
            
            sample = self._sampler_samples.get(voice.note)
            if sample is not None:
                sample_len = len(sample)
                pos = int(voice.play_pos)
                end = min(pos + frames, sample_len)
                n = end - pos
                if n > 0 and pos >= 0:
                    mix[:n] += sample[pos:end] * voice.velocity
                voice.play_pos += frames
                if voice.play_pos >= sample_len:
                    voice.is_active = False
            else:
                # Sine wave synth
                freq = 440.0 * step
                t = (voice.play_pos + np.arange(frames)) / self._sample_rate
                wave = np.sin(2.0 * np.pi * freq * t).astype(np.float32)
                mix += wave * voice.velocity * 0.3
                voice.play_pos += frames
            
            if voice.is_releasing:
                release_frames = int(0.05 * self._sample_rate)
                progress = (voice.play_pos - voice.release_start) / max(release_frames, 1)
                if progress >= 1.0:
                    voice.is_active = False
                    voice.is_releasing = False
        
        # --- Drum pad samples ---
        for pad_idx in range(self.NUM_PADS):
            if not self._pad_active[pad_idx]:
                continue
            
            sample = self._pad_samples.get(pad_idx)
            if sample is None:
                self._pad_active[pad_idx] = False
                continue
            
            pos = self._pad_play_pos[pad_idx]
            sample_len = len(sample)
            
            if pos >= sample_len:
                if self._pad_modes[pad_idx] == 'loop':
                    pos = 0
                    self._pad_play_pos[pad_idx] = 0
                else:
                    self._pad_active[pad_idx] = False
                    continue
            
            end = min(pos + frames, sample_len)
            n = end - pos
            if n > 0:
                vol = self._pad_volumes.get(pad_idx, 1.0)
                mix[:n] += sample[pos:end] * vol
            
            self._pad_play_pos[pad_idx] = end
            
            if end >= sample_len and self._pad_modes[pad_idx] != 'loop':
                self._pad_active[pad_idx] = False
        
        # Normalize
        if active_voices > 1:
            mix *= 1.0 / np.sqrt(active_voices)
        
        # Apply master gain
        mix *= 0.8
        
        # Clamp
        np.clip(mix, -1.0, 1.0, out=mix)
        
        # Level meter
        peak = float(np.max(np.abs(mix)))
        with self._level_lock:
            self._current_level = peak
        
        # Write to stereo output
        outdata[:, 0] = mix
        outdata[:, 1] = mix
    
    def _soundboard_callback(self, outdata: np.ndarray, frames: int,
                             time_info: dict, status: sd.CallbackFlags) -> None:
        """Soundboard callback for Discord/virtual cable output."""
        if not self._is_running:
            outdata.fill(0)
            return
        
        mix = np.zeros(frames, dtype=np.float32)
        
        for pad_idx in range(self.NUM_PADS):
            if not self._pad_active[pad_idx] or not self._pad_route_mic.get(pad_idx, True):
                continue
            
            sample = self._pad_samples.get(pad_idx)
            if sample is None:
                continue
            
            pos = self._pad_play_pos[pad_idx]
            sample_len = len(sample)
            
            if pos >= sample_len:
                continue
            
            end = min(pos + frames, sample_len)
            n = end - pos
            if n > 0:
                vol = self._pad_volumes.get(pad_idx, 1.0)
                mix[:n] += sample[pos:end] * vol
        
        np.clip(mix, -1.0, 1.0, out=mix)
        outdata[:, 0] = mix
        outdata[:, 1] = mix
    
    # ──────────────────────────────────────────────
    # Utility
    # ──────────────────────────────────────────────
    
    def get_current_level(self) -> float:
        with self._level_lock:
            return self._current_level
    
    def all_notes_off(self) -> None:
        self._voice_manager.all_notes_off()
    
    def cleanup(self) -> None:
        self.stop_streams()
        self._sample_loader.clear_all()
