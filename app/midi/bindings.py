"""
Which MIDI message belongs to which control on screen.

A Binding says "note 36 on channel 10" (or a CC / program change). Pads,
sliders and knobs each get one; the user can re-learn any of them by pressing
the physical control, so the app always matches the hardware, whatever mode
or preset the controller is in.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

NUM_PADS = 8
NUM_SLIDERS = 4
NUM_KNOBS = 4
DRUM_CHANNEL = 9  # MIDI channel 10, zero-based

TYPES = ("note", "cc", "pc")


@dataclass(frozen=True)
class MidiEvent:
    kind: str      # 'note_on' | 'note_off' | 'cc' | 'pc' | 'pitch'
    channel: int   # 0-15
    number: int    # note / controller / program (0 for pitch)
    value: int     # velocity / controller value / pitch bend (-8192..8191)

    @property
    def is_press(self) -> bool:
        """A pad-like 'hit': note-on, program change or a CC going above zero."""
        return (self.kind == "note_on" and self.value > 0) or self.kind == "pc" or \
               (self.kind == "cc" and self.value > 0)


@dataclass(frozen=True)
class Binding:
    type: str                  # 'note' | 'cc' | 'pc'
    channel: Optional[int]     # 0-15, None = any channel
    number: int

    @staticmethod
    def from_event(ev: MidiEvent) -> Optional["Binding"]:
        if ev.kind in ("note_on", "note_off"):
            return Binding("note", ev.channel, ev.number)
        if ev.kind == "cc":
            return Binding("cc", ev.channel, ev.number)
        if ev.kind == "pc":
            return Binding("pc", ev.channel, ev.number)
        return None

    @staticmethod
    def from_dict(d) -> Optional["Binding"]:
        try:
            kind = d["type"]
            number = int(d["number"])
            channel = d.get("channel")
            channel = None if channel is None else int(channel)
        except (TypeError, KeyError, ValueError):
            return None
        if kind not in TYPES or not 0 <= number <= 127 or (channel is not None and not 0 <= channel <= 15):
            return None
        return Binding(kind, channel, number)

    def to_dict(self) -> dict:
        return {"type": self.type, "channel": self.channel, "number": self.number}

    def describe(self) -> str:
        ch = "any channel" if self.channel is None else f"ch {self.channel + 1}"
        if self.type == "note":
            return f"note {note_name(self.number)} ({self.number}), {ch}"
        if self.type == "cc":
            return f"CC {self.number}, {ch}"
        return f"program {self.number}, {ch}"


def note_name(note: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return f"{names[note % 12]}{note // 12 - 1}"


# Best-known Panda MINI factory settings (bank 1): pads send notes 36-43 on
# channel 10 in label order, sliders CC 3-6, knobs CC 14-17. Worlde doesn't
# publish a chart and banks/editor presets change them, so "Set up controller"
# (MIDI learn) is how the app really gets matched to the hardware.
DEFAULT_PADS = [Binding("note", DRUM_CHANNEL, 36 + i) for i in range(NUM_PADS)]
DEFAULT_SLIDERS: List[Optional[Binding]] = [Binding("cc", None, n) for n in (3, 4, 5, 6)]
DEFAULT_KNOBS: List[Optional[Binding]] = [Binding("cc", None, n) for n in (14, 15, 16, 17)]


class ControlMap:
    """Immutable lookup from an incoming event to ('pad'|'slider'|'knob', index)."""

    def __init__(self, pads, sliders, knobs):
        self.pads: Tuple[Optional[Binding], ...] = tuple(pads)
        self.sliders: Tuple[Optional[Binding], ...] = tuple(sliders)
        self.knobs: Tuple[Optional[Binding], ...] = tuple(knobs)
        self._exact: Dict[tuple, Tuple[str, int]] = {}
        self._any: Dict[tuple, Tuple[str, int]] = {}
        # Later groups never override earlier ones: pads win over sliders/knobs.
        for group, bindings in (("pad", self.pads), ("slider", self.sliders), ("knob", self.knobs)):
            for i, b in enumerate(bindings):
                if b is None:
                    continue
                if b.channel is None:
                    self._any.setdefault((b.type, b.number), (group, i))
                else:
                    self._exact.setdefault((b.type, b.channel, b.number), (group, i))

    @classmethod
    def defaults(cls) -> "ControlMap":
        return cls(DEFAULT_PADS, DEFAULT_SLIDERS, DEFAULT_KNOBS)

    def lookup(self, ev: MidiEvent) -> Optional[Tuple[str, int]]:
        b = Binding.from_event(ev)
        if b is None:
            return None
        return self._exact.get((b.type, b.channel, b.number)) or self._any.get((b.type, b.number))

    def with_binding(self, group: str, index: int, binding: Binding) -> "ControlMap":
        """Copy with `binding` moved to group[index] (removed from any other control)."""
        def strip(bindings):
            return [None if (b is not None and _overlaps(b, binding)) else b for b in bindings]
        pads, sliders, knobs = strip(self.pads), strip(self.sliders), strip(self.knobs)
        {"pad": pads, "slider": sliders, "knob": knobs}[group][index] = binding
        return ControlMap(pads, sliders, knobs)


def _overlaps(a: Binding, b: Binding) -> bool:
    return a.type == b.type and a.number == b.number and \
        (a.channel is None or b.channel is None or a.channel == b.channel)
