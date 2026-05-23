"""
PandaMINI Core Engine - Voice Management
Tracks voice properties for polyphonic synthesis with oldest-first voice stealing
"""
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
import threading


@dataclass
class Voice:
    """Represents a single polyphonic voice."""
    note: int = 0
    velocity: float = 0.0
    play_pos: float = 0.0
    is_active: bool = False
    age: int = 0
    release_start: float = 0.0
    is_releasing: bool = False
    
    def reset(self) -> None:
        """Reset voice to default state."""
        self.note = 0
        self.velocity = 0.0
        self.play_pos = 0.0
        self.is_active = False
        self.age = 0
        self.release_start = 0.0
        self.is_releasing = False


class VoiceManager:
    """Manages up to 16 voices with oldest-first voice stealing."""
    
    MAX_VOICES = 16
    
    def __init__(self):
        self._voices = [Voice() for _ in range(self.MAX_VOICES)]
        self._lock = threading.Lock()
        self._global_age = 0
    
    def note_on(self, note: int, velocity: float) -> Optional[Voice]:
        """
        Trigger note on for a voice. Uses oldest-first voice stealing if all voices are active.
        Returns the voice that was triggered, or None if no voice could be allocated.
        """
        with self._lock:
            self._global_age += 1
            
            # First, check if this note is already playing (re-trigger)
            for voice in self._voices:
                if voice.is_active and voice.note == note and not voice.is_releasing:
                    voice.velocity = velocity / 127.0
                    voice.play_pos = 0.0
                    voice.age = self._global_age
                    voice.is_releasing = False
                    return voice
            
            # Find an inactive voice
            for voice in self._voices:
                if not voice.is_active:
                    self._activate_voice(voice, note, velocity)
                    return voice
            
            # All voices active - steal the oldest non-releasing voice
            oldest_voice = None
            oldest_age = float('inf')
            
            for voice in self._voices:
                if not voice.is_releasing and voice.age < oldest_age:
                    oldest_age = voice.age
                    oldest_voice = voice
            
            if oldest_voice is not None:
                self._activate_voice(oldest_voice, note, velocity)
                return oldest_voice
            
            return None
    
    def _activate_voice(self, voice: Voice, note: int, velocity: float) -> None:
        """Activate a voice with the given note and velocity."""
        voice.note = note
        voice.velocity = velocity / 127.0
        voice.play_pos = 0.0
        voice.is_active = True
        voice.age = self._global_age
        voice.is_releasing = False
        voice.release_start = 0.0
    
    def note_off(self, note: int) -> None:
        """Trigger note off for all voices playing the given note."""
        with self._lock:
            for voice in self._voices:
                if voice.is_active and voice.note == note and not voice.is_releasing:
                    voice.is_releasing = True
                    voice.release_start = voice.play_pos
    
    def get_active_voices(self) -> list:
        """Get list of currently active voices (thread-safe copy)."""
        with self._lock:
            return [v for v in self._voices if v.is_active]
    
    def get_active_count(self) -> int:
        """Get count of currently active voices."""
        with self._lock:
            return sum(1 for v in self._voices if v.is_active)
    
    def all_notes_off(self) -> None:
        """Release all active voices."""
        with self._lock:
            for voice in self._voices:
                if voice.is_active:
                    voice.is_releasing = True
                    voice.release_start = voice.play_pos
    
    def reset(self) -> None:
        """Reset all voices."""
        with self._lock:
            for voice in self._voices:
                voice.reset()
            self._global_age = 0
