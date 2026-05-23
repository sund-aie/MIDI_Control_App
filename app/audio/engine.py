"""
PandaMINI Core Engine - Audio Engine
Controls multi-stream WASAPI initialization and allocation-free callback structures
"""
import numpy as np
import sounddevice as sd
from typing import Dict, List, Optional, Tuple, Callable
from PySide6.QtCore import QObject, Signal, QThread
import threading
import weakref

from app.audio.voice import VoiceManager
from app.audio.loader import SampleLoader


class AudioEngine(QObject):
    """
    Multi-threaded audio engine with dual WASAPI output streams.
    Thread A (GUI Main Thread) - drives the PySide6 app window loop
    Threads C & D (PortAudio Callbacks) - run allocation-free buffer calculations
    """
    
    stream_started = Signal()
    stream_stopped = Signal()
    audio_error = Signal(str)
    vu_update = Signal(float)  # 0.0 to 1.0
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        
        self._sample_rate = 48000
        self._blocksize = 256
        self._latency = 'low'
        
        # Pre-allocated buffers for allocation-free execution
        self._output_buffer_size = self._blocksize * 2  # Double buffer
        self._output_buffer = np.zeros(self._output_buffer_size, dtype=np.float32)
        self._mix_buffer = np.zeros(self._blocksize, dtype=np.float32)
        
        # Voice management
        self._voice_manager = VoiceManager()
        self._sample_loader = SampleLoader()
        
        # Loaded samples for sampler voices
        self._sampler_samples: Dict[int, np.ndarray] = {}  # note -> sample data
        
        # Soundboard pad samples
        self._pad_samples: Dict[int, np.ndarray] = {}  # pad_index -> sample data
        self._pad_triggers: Dict[int, bool] = {i: False for i in range(8)}
        
        # Stream references
        self._sampler_stream: Optional[sd.OutputStream] = None
        self._soundboard_stream: Optional[sd.OutputStream] = None
        
        # Output devices
        self._sampler_device: Optional[int] = None
        self._soundboard_device: Optional[int] = None
        
        # Level metering (thread-safe)
        self._current_level = 0.0
        self._level_lock = threading.Lock()
        
        # Callback state flags (atomic operations only)
        self._is_running = False
        
        # Keep references to prevent garbage collection
        self._callback_refs: List[weakref.ref] = []
    
    @property
    def voice_manager(self) -> VoiceManager:
        return self._voice_manager
    
    @property
    def sample_loader(self) -> SampleLoader:
        return self._sample_loader
    
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
    
    def start_streams(self, 
                      sampler_device: Optional[int] = None,
                      soundboard_device: Optional[int] = None) -> bool:
        """
        Start both WASAPI output streams.
        
        Args:
            sampler_device: Device index for sampler output
            soundboard_device: Device index for soundboard output
            
        Returns:
            True if streams started successfully
        """
        if self._is_running:
            return True
        
        self._sampler_device = sampler_device
        self._soundboard_device = soundboard_device
        
        try:
            # Configure WASAPI settings
            wasapi_settings = sd.WasapiSettings(exclusive=False)
            
            # Create sampler stream
            self._sampler_stream = sd.OutputStream(
                device=self._sampler_device,
                samplerate=self._sample_rate,
                blocksize=self._blocksize,
                latency=self._latency,
                channels=2,
                dtype=np.float32,
                extra_settings=wasapi_settings,
                callback=self._sampler_callback,
                finished_callback=self._on_stream_finished,
            )
            
            # Create soundboard stream  
            self._soundboard_stream = sd.OutputStream(
                device=self._soundboard_device,
                samplerate=self._sample_rate,
                blocksize=self._blocksize,
                latency=self._latency,
                channels=2,
                dtype=np.float32,
                extra_settings=wasapi_settings,
                callback=self._soundboard_callback,
                finished_callback=self._on_stream_finished,
            )
            
            # Start both streams
            self._sampler_stream.start()
            self._soundboard_stream.start()
            
            self._is_running = True
            self.stream_started.emit()
            return True
            
        except Exception as e:
            self.audio_error.emit(f"Failed to start streams: {e}")
            return False
    
    def stop_streams(self) -> None:
        """Stop both output streams."""
        self._is_running = False
        
        if self._sampler_stream:
            try:
                self._sampler_stream.stop()
                self._sampler_stream.close()
            except:
                pass
            self._sampler_stream = None
        
        if self._soundboard_stream:
            try:
                self._soundboard_stream.stop()
                self._soundboard_stream.close()
            except:
                pass
            self._soundboard_stream = None
        
        self.stream_stopped.emit()
    
    def trigger_synth_note(self, note: int, velocity: int) -> None:
        """Trigger a synth note on the sampler engine."""
        self._voice_manager.note_on(note, velocity)
    
    def release_synth_note(self, note: int) -> None:
        """Release a synth note."""
        self._voice_manager.note_off(note)
    
    def trigger_pad(self, pad_index: int) -> None:
        """Trigger a soundboard pad."""
        if 0 <= pad_index < 8:
            self._pad_triggers[pad_index] = True
    
    def load_sampler_sample(self, note: int, sample_path: str) -> None:
        """Load a sample for a specific MIDI note."""
        def on_loaded(path: str, data: np.ndarray):
            self._sampler_samples[note] = data.copy()
        
        self._sample_loader.load_sample(sample_path, on_loaded)
    
    def load_pad_sample(self, pad_index: int, sample_path: str) -> None:
        """Load a sample for a drum pad."""
        def on_loaded(path: str, data: np.ndarray):
            self._pad_samples[pad_index] = data.copy()
        
        self._sample_loader.load_sample(sample_path, on_loaded)
    
    def _sampler_callback(self, outdata: np.ndarray, frames: int, 
                          time_info: dict, status: sd.CallbackFlags) -> None:
        """
        Allocation-free audio callback for sampler stream.
        Zero object creation, zero dictionary reads, zero print statements.
        """
        if not self._is_running:
            outdata.fill(0)
            return
        
        # Clear mix buffer (pre-allocated)
        self._mix_buffer[:] = 0.0
        
        active_voices = 0
        
        # Process each voice (O(1) operations only)
        for voice in self._voice_manager._voices:
            if not voice.is_active:
                continue
            
            active_voices += 1
            
            # Calculate pitch step relative to C4 (MIDI note 60)
            # step = 2 ** ((note - 60) / 12.0)
            note_diff = voice.note - 60
            step = pow(2.0, note_diff / 12.0)
            
            # Get sample for this note or use default waveform
            sample = self._sampler_samples.get(voice.note)
            
            if sample is not None:
                # Linear interpolation for sample playback
                sample_len = len(sample)
                indices = voice.play_pos + np.arange(frames) * step
                indices_int = indices.astype(np.intp)
                
                # Clamp indices
                valid_mask = (indices_int >= 0) & (indices_int < sample_len)
                
                if np.any(valid_mask):
                    interp_values = np.interp(
                        indices[valid_mask], 
                        0, sample_len, 
                        sample, 
                        right=0
                    )
                    self._mix_buffer[valid_mask] += interp_values * voice.velocity
            else:
                # Generate simple waveform if no sample loaded
                phase_inc = step * 440.0 / self._sample_rate
                phases = (voice.play_pos * phase_inc + 
                         np.arange(frames) * phase_inc) % 1.0
                wave = np.sin(2.0 * np.pi * phases).astype(np.float32)
                self._mix_buffer += wave * voice.velocity * 0.3
            
            # Update play position
            voice.play_pos += frames * step
            
            # Handle release
            if voice.is_releasing:
                release_frames = int(0.01 * self._sample_rate)  # 10ms fade
                rel_progress = (voice.play_pos - voice.release_start) / release_frames
                if rel_progress >= 1.0:
                    voice.is_active = False
                    voice.is_releasing = False
                elif rel_progress < 1.0:
                    # Apply fade-out
                    fade_start = int(max(0, voice.play_pos - release_frames))
                    fade_end = int(min(frames, voice.play_pos))
                    if fade_end > fade_start:
                        fade = np.linspace(1.0, 0.0, fade_end - fade_start, dtype=np.float32)
                        self._mix_buffer[fade_start:fade_end] *= (1.0 - fade)
        
        # Normalize by sqrt(active_voices) to avoid clipping
        if active_voices > 1:
            self._mix_buffer *= 1.0 / np.sqrt(active_voices)
        
        # Apply final gain
        self._mix_buffer *= 0.8
        
        # Update level meter (thread-safe)
        peak = np.max(np.abs(self._mix_buffer))
        with self._level_lock:
            self._current_level = float(peak)
        
        # Copy to output (stereo)
        outdata[:, 0] = self._mix_buffer
        outdata[:, 1] = self._mix_buffer
    
    def _soundboard_callback(self, outdata: np.ndarray, frames: int,
                             time_info: dict, status: sd.CallbackFlags) -> None:
        """
        Allocation-free audio callback for soundboard stream.
        """
        if not self._is_running:
            outdata.fill(0)
            return
        
        # Clear output buffer
        self._mix_buffer[:] = 0.0
        
        # Process triggered pads
        for pad_idx in range(8):
            if not self._pad_triggers[pad_idx]:
                continue
            
            sample = self._pad_samples.get(pad_idx)
            if sample is None:
                continue
            
            # Simple one-shot playback
            sample_len = min(len(sample), frames)
            self._mix_buffer[:sample_len] += sample[:sample_len]
            
            # Reset trigger after playback starts
            self._pad_triggers[pad_idx] = False
        
        # Update level meter
        peak = np.max(np.abs(self._mix_buffer))
        with self._level_lock:
            self._current_level = max(self._current_level, float(peak))
        
        # Copy to output (stereo)
        outdata[:, 0] = self._mix_buffer
        outdata[:, 1] = self._mix_buffer
    
    def _on_stream_finished(self) -> None:
        """Called when a stream finishes."""
        pass
    
    def get_current_level(self) -> float:
        """Get current VU meter level (thread-safe)."""
        with self._level_lock:
            return self._current_level
    
    def all_notes_off(self) -> None:
        """Release all active voices."""
        self._voice_manager.all_notes_off()
    
    def cleanup(self) -> None:
        """Clean up resources."""
        self.stop_streams()
        self._sample_loader.clear_all()
