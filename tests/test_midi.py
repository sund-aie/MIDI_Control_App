from app.midi.bindings import Binding, ControlMap, MidiEvent
from app.midi.listener import MidiListener, parse


class FakeEngine:
    def __init__(self):
        self.calls = []

    def trigger_pad(self, pad):
        self.calls.append(("trigger", pad))
        return "started"

    def release_pad(self, pad):
        self.calls.append(("release", pad))

    def note_on(self, note, velocity):
        self.calls.append(("note_on", note))

    def note_off(self, note):
        self.calls.append(("note_off", note))


class FakeBackend:
    def __init__(self, names=("WORLDE",), fail=None):
        self.names = list(names)
        self.opened = None
        self.fail = fail

    def list(self):
        return list(self.names)

    def open(self, index, name, on_bytes):
        if self.fail:
            raise self.fail
        self.opened = self.names[index]
        self.on_bytes = on_bytes

    def close(self):
        self.opened = None


def test_parse_messages():
    assert parse(0x99, 36, 100) == MidiEvent("note_on", 9, 36, 100)
    assert parse(0x99, 36, 0) == MidiEvent("note_off", 9, 36, 0)
    assert parse(0x80, 60, 64) == MidiEvent("note_off", 0, 60, 64)
    assert parse(0xB0, 7, 127) == MidiEvent("cc", 0, 7, 127)
    assert parse(0xC3, 5, 0) == MidiEvent("pc", 3, 5, 0)
    assert parse(0xE0, 0, 64) == MidiEvent("pitch", 0, 0, 0)
    assert parse(0xE0, 127, 127).value == 8191
    assert parse(0xF8, 0, 0) is None


def test_control_map_exact_any_and_move():
    cmap = ControlMap([Binding("note", 9, 36)] + [None] * 7, [Binding("cc", None, 7)] + [None] * 3, [None] * 4)
    assert cmap.lookup(MidiEvent("note_on", 9, 36, 90)) == ("pad", 0)
    assert cmap.lookup(MidiEvent("note_on", 0, 36, 90)) is None           # wrong channel
    assert cmap.lookup(MidiEvent("cc", 5, 7, 1)) == ("slider", 0)          # any channel
    moved = cmap.with_binding("pad", 3, Binding("note", 9, 36))
    assert moved.pads[0] is None and moved.pads[3] == Binding("note", 9, 36)
    assert moved.lookup(MidiEvent("note_off", 9, 36, 0)) == ("pad", 3)


def test_pad_notes_trigger_engine_and_signal(qapp, qtbot):
    engine = FakeEngine()
    listener = MidiListener(engine, backend=FakeBackend())
    listener.set_control_map(ControlMap([Binding("note", 9, 40 + i) for i in range(8)], [None] * 4, [None] * 4))
    with qtbot.waitSignal(listener.pad_pressed) as blocker:
        listener.handle(MidiEvent("note_on", 9, 42, 100))
    assert blocker.args == [2]
    listener.handle(MidiEvent("note_off", 9, 42, 0))
    assert engine.calls == [("trigger", 2), ("release", 2)]


def test_keys_go_to_synth_and_unmatched_drum_hits_are_reported(qapp, qtbot):
    engine = FakeEngine()
    listener = MidiListener(engine, backend=FakeBackend())
    listener.handle(MidiEvent("note_on", 0, 60, 100))
    listener.handle(MidiEvent("note_off", 0, 60, 0))
    assert engine.calls == [("note_on", 60), ("note_off", 60)]
    with qtbot.waitSignal(listener.unmatched_pad):
        listener.handle(MidiEvent("note_on", 9, 50, 100))    # not in the default pad map


def test_cc_mode_pads_trigger_once_per_hit(qapp):
    engine = FakeEngine()
    listener = MidiListener(engine, backend=FakeBackend())
    listener.set_control_map(ControlMap([Binding("cc", 0, 20)] + [None] * 7, [None] * 4, [None] * 4))
    for value in (100, 110, 0, 90, 0):
        listener.handle(MidiEvent("cc", 0, 20, value))
    assert engine.calls == [("trigger", 0), ("release", 0), ("trigger", 0), ("release", 0)]


def test_cc_pads_without_release_still_retrigger(qapp):
    import time
    engine = FakeEngine()
    listener = MidiListener(engine, backend=FakeBackend())
    listener.set_control_map(ControlMap([Binding("cc", 0, 20)] + [None] * 7, [None] * 4, [None] * 4))
    listener.handle(MidiEvent("cc", 0, 20, 127))
    time.sleep(0.1)
    listener.handle(MidiEvent("cc", 0, 20, 127))
    assert engine.calls == [("trigger", 0), ("trigger", 0)]


def test_unmatched_drum_hit_does_not_play_synth(qapp):
    engine = FakeEngine()
    listener = MidiListener(engine, backend=FakeBackend())
    listener.handle(MidiEvent("note_on", 9, 50, 100))
    listener.handle(MidiEvent("note_off", 9, 50, 0))
    assert engine.calls == []


def test_program_change_pad_is_not_released_instantly(qapp):
    engine = FakeEngine()
    listener = MidiListener(engine, backend=FakeBackend())
    listener.set_control_map(ControlMap([Binding("pc", 0, 3)] + [None] * 7, [None] * 4, [None] * 4))
    listener.handle(MidiEvent("pc", 0, 3, 0))
    assert engine.calls == [("trigger", 0)]


def test_held_notes_are_released_when_learning_starts_or_unplugged(qapp):
    engine = FakeEngine()
    backend = FakeBackend(names=["WORLDE Panda MINI"])
    listener = MidiListener(engine, backend=backend)
    listener.start(None)
    listener.handle(MidiEvent("note_on", 0, 60, 100))
    listener.learning = True
    assert ("note_off", 60) in engine.calls
    listener.learning = False
    listener.handle(MidiEvent("note_on", 9, 36, 100))           # default Pad 1, held
    backend.names = []
    listener.poll()
    assert engine.calls[-1] == ("release", 0)
    listener.stop()


def test_automatic_mode_switches_to_panda_when_it_appears(qapp):
    backend = FakeBackend(names=["loopMIDI Port"])
    listener = MidiListener(FakeEngine(), backend=backend)
    listener.start(None)
    assert listener.connected == "loopMIDI Port"
    backend.names = ["loopMIDI Port", "WORLDE Panda MINI"]
    listener.poll()
    assert listener.connected == "WORLDE Panda MINI"
    listener.stop()


def test_sliders_emit_normalised_values(qapp, qtbot):
    listener = MidiListener(FakeEngine(), backend=FakeBackend())
    with qtbot.waitSignal(listener.slider_moved) as blocker:
        listener.handle(MidiEvent("cc", 3, 5, 127))            # default slider 3 = CC 5, any channel
    assert blocker.args == [2, 1.0]


def test_learning_captures_instead_of_playing(qapp, qtbot):
    engine = FakeEngine()
    listener = MidiListener(engine, backend=FakeBackend())
    listener.learning = True
    with qtbot.waitSignal(listener.learn_event) as blocker:
        listener.handle(MidiEvent("note_on", 9, 36, 100))
    assert blocker.args[0].number == 36
    assert engine.calls == []                                   # captured, not played


def test_connects_to_panda_and_handles_unplug(qapp, qtbot):
    backend = FakeBackend(names=["Other Synth", "WORLDE easy key", "WORLDE Panda MINI"])
    listener = MidiListener(FakeEngine(), backend=backend)
    with qtbot.waitSignal(listener.status_changed) as blocker:
        listener.start(None)
    assert blocker.args[0] is True and backend.opened == "WORLDE Panda MINI"
    backend.names = ["Other Synth"]
    with qtbot.waitSignal(listener.status_changed) as blocker:
        listener.poll()
    assert blocker.args[0] is False and listener.connected is None   # waits, doesn't hop to Other Synth
    listener.poll()
    assert listener.connected is None and backend.opened is None
    backend.names = ["Other Synth", "WORLDE Panda MINI"]
    listener.poll()
    assert listener.connected == "WORLDE Panda MINI"
    listener.stop()


def test_busy_port_reports_friendly_error(qapp, qtbot):
    from app.midi.listener import MidiError
    listener = MidiListener(FakeEngine(), backend=FakeBackend(fail=MidiError("Another program is using it")))
    with qtbot.waitSignal(listener.status_changed) as blocker:
        listener.start(None)
    assert blocker.args[0] is False and "Another program" in blocker.args[2]
    listener.stop()


def test_first_start_without_panda_uses_first_port(qapp):
    backend = FakeBackend(names=["USB Keyboard"])
    listener = MidiListener(FakeEngine(), backend=backend)
    listener.start(None)
    assert listener.connected == "USB Keyboard"
    listener.stop()


def test_saved_legacy_name_matches_full_port_name(qapp):
    backend = FakeBackend(names=["Other Synth", "WORLDE Panda MINI"])
    listener = MidiListener(FakeEngine(), backend=backend)
    listener.start("WORLDE")                                    # value saved by the old version
    assert listener.connected == "WORLDE Panda MINI"
    listener.stop()
