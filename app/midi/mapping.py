"""
PandaMINI Core Engine - MIDI Mapping
Maps physical Worlde Panda MINI controller to processing paths
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from enum import Enum


class ControlType(Enum):
    """Types of MIDI controls."""
    KEY = "key"
    PAD = "pad"
    FADER = "fader"
    KNOB = "knob"
    BUTTON = "button"


@dataclass
class ControlMapping:
    """Represents a single control mapping."""
    control_type: ControlType
    midi_value: int  # Note number or CC number
    channel: int = 0
    name: str = ""
    min_value: float = 0.0
    max_value: float = 1.0
    curve: str = "linear"  # linear, exponential, logarithmic
    action: Optional[Callable] = None


class MidiMapper:
    """
    Maps MIDI messages from Worlde Panda MINI to application functions.
    
    Mappings:
    - Keys: Notes 48-72 (C3 to C5) -> Synth voices
    - Drum Pads: Notes 36-43 (C2 to G#2) -> Soundboard triggers
    - Faders: CC 10-13 -> Mixer channel volumes
    - Knobs: CC 20-23 -> Synth parameters
    """
    
    def __init__(self):
        self._mappings: Dict[str, ControlMapping] = {}
        self._note_to_key: Dict[int, int] = {}  # MIDI note -> key index
        self._note_to_pad: Dict[int, int] = {}  # MIDI note -> pad index
        self._cc_to_fader: Dict[int, int] = {}  # CC number -> fader index
        self._cc_to_knob: Dict[int, int] = {}  # CC number -> knob index
        
        self._setup_default_mappings()
    
    def _setup_default_mappings(self) -> None:
        """Set up default mappings for Worlde Panda MINI."""
        
        # Keyboard keys (Notes 48-72) - 25 keys spanning 2 octaves
        for i, note in enumerate(range(48, 73)):
            key_name = self._note_to_name(note)
            mapping = ControlMapping(
                control_type=ControlType.KEY,
                midi_value=note,
                name=f"Key {key_name}",
                min_value=0.0,
                max_value=1.0,
            )
            self._mappings[f"key_{note}"] = mapping
            self._note_to_key[note] = i
        
        # Drum pads (Notes 36-43) - 8 pads
        for i, note in enumerate(range(36, 44)):
            mapping = ControlMapping(
                control_type=ControlType.PAD,
                midi_value=note,
                name=f"Pad {i + 1}",
                min_value=0.0,
                max_value=1.0,
            )
            self._mappings[f"pad_{note}"] = mapping
            self._note_to_pad[note] = i
        
        # Faders (CC 10-13) - 4 faders for mixer channels
        for i, cc in enumerate(range(10, 14)):
            mapping = ControlMapping(
                control_type=ControlType.FADER,
                midi_value=cc,
                name=f"Fader {i + 1}",
                min_value=0.0,
                max_value=1.0,
            )
            self._mappings[f"fader_{cc}"] = mapping
            self._cc_to_fader[cc] = i
        
        # Knobs (CC 20-23) - 4 knobs for synth parameters
        knob_names = ["Cutoff", "Resonance", "Attack", "Release"]
        for i, cc in enumerate(range(20, 24)):
            mapping = ControlMapping(
                control_type=ControlType.KNOB,
                midi_value=cc,
                name=knob_names[i] if i < len(knob_names) else f"Knob {i + 1}",
                min_value=0.0,
                max_value=1.0,
            )
            self._mappings[f"knob_{cc}"] = mapping
            self._cc_to_knob[cc] = i
    
    @staticmethod
    def _note_to_name(note: int) -> str:
        """Convert MIDI note number to note name."""
        note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        octave = (note // 12) - 1
        note_name = note_names[note % 12]
        return f"{note_name}{octave}"
    
    def get_key_for_note(self, note: int) -> Optional[int]:
        """Get key index for a MIDI note."""
        return self._note_to_key.get(note)
    
    def get_pad_for_note(self, note: int) -> Optional[int]:
        """Get pad index for a MIDI note."""
        return self._note_to_pad.get(note)
    
    def get_fader_for_cc(self, cc: int) -> Optional[int]:
        """Get fader index for a CC number."""
        return self._cc_to_fader.get(cc)
    
    def get_knob_for_cc(self, cc: int) -> Optional[int]:
        """Get knob index for a CC number."""
        return self._cc_to_knob.get(cc)
    
    def is_key_note(self, note: int) -> bool:
        """Check if a note is mapped to a keyboard key."""
        return 48 <= note <= 72
    
    def is_pad_note(self, note: int) -> bool:
        """Check if a note is mapped to a drum pad."""
        return 36 <= note <= 43
    
    def is_fader_cc(self, cc: int) -> bool:
        """Check if a CC is mapped to a fader."""
        return 10 <= cc <= 13
    
    def is_knob_cc(self, cc: int) -> bool:
        """Check if a CC is mapped to a knob."""
        return 20 <= cc <= 23
    
    def get_mapping(self, key: str) -> Optional[ControlMapping]:
        """Get a mapping by key."""
        return self._mappings.get(key)
    
    def add_mapping(self, key: str, mapping: ControlMapping) -> None:
        """Add or update a mapping."""
        self._mappings[key] = mapping
    
    def remove_mapping(self, key: str) -> None:
        """Remove a mapping."""
        self._mappings.pop(key, None)
    
    def get_all_mappings(self) -> Dict[str, ControlMapping]:
        """Get all mappings."""
        return self._mappings.copy()
    
    def scale_cc_value(self, cc: int, value: int) -> float:
        """
        Scale a CC value (0-127) to normalized range (0.0-1.0).
        Applies curve if specified.
        """
        mapping = self._mappings.get(f"knob_{cc}") or self._mappings.get(f"fader_{cc}")
        if not mapping:
            return value / 127.0
        
        normalized = value / 127.0
        
        if mapping.curve == "exponential":
            scaled = pow(normalized, 2.0)
        elif mapping.curve == "logarithmic":
            scaled = pow(normalized, 0.5)
        else:  # linear
            scaled = normalized
        
        return mapping.min_value + scaled * (mapping.max_value - mapping.min_value)
    
    def note_to_frequency(self, note: int) -> float:
        """Convert MIDI note to frequency in Hz."""
        return 440.0 * pow(2.0, (note - 69) / 12.0)
    
    def frequency_to_note(self, freq: float) -> float:
        """Convert frequency in Hz to MIDI note number."""
        return 69 + 12 * (np.log2(freq / 440.0))


# Import numpy only when needed for frequency conversion
try:
    import numpy as np
except ImportError:
    np = None
