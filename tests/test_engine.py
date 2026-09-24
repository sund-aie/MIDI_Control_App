"""Mixing tests that drive the output callbacks directly (no sound card needed)."""
import time

import numpy as np
import pytest

from app.audio.engine import (ROLE_BOTH, ROLE_HEADPHONES, ROLE_MIC, AudioEngine, OutputBus,
                              PadSound)

BLOCK = 480


@pytest.fixture
def engine(qapp):
    eng = AudioEngine()
    eng.levels.update(headphones=1.0, mic=1.0, keys=1.0, master=1.0)
    return eng


def attach(engine, *specs):
    """specs: (role, rate). Creates buses without opening PortAudio streams."""
    buses = []
    for role, rate in specs:
        bus = OutputBus(engine, role, None, role)
        bus._prepare(rate)
        buses.append(bus)
    engine._buses = tuple(buses)
    return buses


def sound(seconds=0.1, rate=48000, value=0.5):
    return PadSound(np.full((int(seconds * rate), 2), value, dtype=np.float32), rate, "test.wav")


def render(bus, blocks=1, frames=BLOCK):
    out = np.zeros((frames * blocks, 2), dtype=np.float32)
    for b in range(blocks):
        chunk = np.zeros((frames, 2), dtype=np.float32)
        bus.mix(chunk, frames)
        out[b * frames:(b + 1) * frames] = chunk
    return out


def test_pad_plays_once_then_stops(engine):
    (bus,) = attach(engine, (ROLE_HEADPHONES, 48000))
    engine._install(0, sound(seconds=0.02))       # 960 frames = 2 blocks
    engine.settings[0].volume = 1.0
    assert engine.trigger_pad(0) == "started"
    out = render(bus, blocks=3)
    assert np.allclose(out[:960], 0.5)
    assert np.allclose(out[960:], 0.0)
    assert bus.voices == []


def test_empty_pad_does_nothing(engine):
    attach(engine, (ROLE_HEADPHONES, 48000))
    assert engine.trigger_pad(3) == "empty"


def test_each_output_keeps_its_own_position(engine):
    """Regression: both outputs used to share one play position, garbling the Discord feed."""
    hp, mic = attach(engine, (ROLE_HEADPHONES, 48000), (ROLE_MIC, 44100))
    engine._install(0, sound(seconds=0.05))
    engine.settings[0].volume = 1.0
    engine.trigger_pad(0)
    out_hp = render(hp, blocks=10)
    out_mic = render(mic, blocks=10)
    assert abs(np.count_nonzero(out_hp[:, 0]) - 2400) <= 2
    assert abs(np.count_nonzero(out_mic[:, 0]) - 2205) <= 4     # resampled to 44.1k, full length


def test_routing_flags(engine):
    hp, mic = attach(engine, (ROLE_HEADPHONES, 48000), (ROLE_MIC, 48000))
    engine._install(0, sound())
    engine.settings[0].to_headphones = False
    engine.trigger_pad(0)
    assert not render(hp).any()
    assert render(mic).any()


def test_shared_device_plays_once(engine):
    (both,) = attach(engine, (ROLE_BOTH, 48000))
    engine._install(0, sound(value=0.25))
    engine.settings[0].volume = 1.0
    engine.settings[0].to_headphones = False     # still reaches the device via the mic route
    engine.trigger_pad(0)
    assert np.allclose(render(both)[:100], 0.25)


def test_volume_levels_multiply(engine):
    (bus,) = attach(engine, (ROLE_MIC, 48000))
    engine._install(0, sound(value=0.5))
    engine.settings[0].volume = 0.5
    engine.levels.update(mic=0.5, master=0.5)
    engine.trigger_pad(0)
    assert np.allclose(render(bus)[:10], 0.5 * 0.5 * 0.5 * 0.5)


def test_retrigger_restarts_with_fade(engine):
    (bus,) = attach(engine, (ROLE_HEADPHONES, 48000))
    engine._install(0, PadSound(np.linspace(0, 0.9, 48000, dtype=np.float32)[:, None].repeat(2, 1),
                                48000, "ramp"))
    engine.settings[0].volume = 1.0
    engine.trigger_pad(0)
    render(bus, blocks=20)
    engine.trigger_pad(0)
    out = render(bus, blocks=2)
    assert len(bus.voices) == 1                          # the old voice faded out and was dropped
    assert np.max(np.abs(np.diff(out[:, 0]))) < 0.05     # no click at the restart


def test_toggle_and_loop_modes(engine):
    (bus,) = attach(engine, (ROLE_HEADPHONES, 48000))
    engine._install(0, sound(seconds=0.01))
    engine.settings[0].mode = "loop"
    assert engine.trigger_pad(0) == "started"
    assert render(bus, blocks=20)[-10:].any()             # still looping long after the end
    assert engine.is_playing(0)
    assert engine.trigger_pad(0) == "stopped"
    render(bus, blocks=2)
    assert not render(bus).any()
    engine.settings[0].mode = "toggle"
    engine._install(1, sound(seconds=2))
    engine.settings[1].mode = "toggle"
    assert engine.trigger_pad(1) == "started"
    assert engine.trigger_pad(1) == "stopped"


def test_hold_mode_stops_on_release(engine):
    (bus,) = attach(engine, (ROLE_HEADPHONES, 48000))
    engine._install(0, sound(seconds=2))
    engine.settings[0].mode = "hold"
    engine.trigger_pad(0)
    assert render(bus).any()
    engine.release_pad(0)
    render(bus, blocks=2)                                 # fade out
    assert not render(bus).any()
    assert not engine.is_playing(0)


def test_stop_all_and_progress(engine):
    (bus,) = attach(engine, (ROLE_HEADPHONES, 48000))
    engine._install(0, sound(seconds=1))
    engine._install(1, sound(seconds=1))
    engine.trigger_pad(0)
    engine.trigger_pad(1)
    time.sleep(0.05)
    assert 0 < engine.progress(0) < 0.5
    engine.stop_all()
    render(bus, blocks=2)
    assert not render(bus).any()
    assert engine.progress(0) == 0.0


def test_new_sound_replaces_old_one_mid_play(engine):
    (bus,) = attach(engine, (ROLE_HEADPHONES, 48000))
    engine._install(0, sound(seconds=1, value=0.5))
    engine.settings[0].volume = 1.0
    engine.trigger_pad(0)
    render(bus)
    engine._install(0, sound(seconds=1, value=0.2))
    render(bus, blocks=2)
    assert not render(bus).any()                          # old sound faded, nothing restarted
    engine.trigger_pad(0)
    assert np.allclose(render(bus)[:10], 0.2)


def test_synth_only_on_headphones(engine):
    hp, mic = attach(engine, (ROLE_HEADPHONES, 48000), (ROLE_MIC, 48000))
    engine.note_on(60, 100)
    assert render(hp, blocks=4).any()
    assert not render(mic, blocks=4).any()
    engine.note_off(60)
    render(hp, blocks=40)                                 # release tail
    assert not render(hp).any()


def test_output_never_clips_and_meter_reads(engine):
    (bus,) = attach(engine, (ROLE_HEADPHONES, 48000))
    for i in range(8):
        engine._install(i, sound(value=0.9))
        engine.settings[i].volume = 1.0
        engine.trigger_pad(i)
    out = render(bus)
    assert np.max(np.abs(out)) <= 1.0
    assert engine.output_state()[ROLE_HEADPHONES]["peak"] == pytest.approx(1.0)
    assert engine.output_state()[ROLE_HEADPHONES]["peak"] == 0.0   # reading resets


def test_mono_device_gets_a_downmix(engine):
    (bus,) = attach(engine, (ROLE_HEADPHONES, 48000))
    engine._install(0, sound(value=0.4))
    engine.settings[0].volume = 1.0
    engine.trigger_pad(0)
    out = np.zeros((BLOCK, 1), dtype=np.float32)
    bus.mix(out, BLOCK)
    assert np.allclose(out[:10, 0], 0.4)


def test_async_load_emits_and_installs(engine, qtbot, wav, tmp_path):
    attach(engine, (ROLE_HEADPHONES, 48000))
    stored = tmp_path / "copied.wav"

    def fake_import(p):
        stored.write_bytes(p.read_bytes())
        return stored

    with qtbot.waitSignal(engine.pad_loaded, timeout=5000) as blocker:
        engine.load_pad(2, str(wav(rate=44100)), import_fn=fake_import)
    pad, ok, info, requested = blocker.args
    assert (pad, ok, info) == (2, True, str(stored))
    assert engine.sounds[2] is not None
    assert engine._buses[0].commands[-1][0] == "set"


def test_failed_load_keeps_previous_sound(engine, qtbot, tmp_path):
    attach(engine, (ROLE_HEADPHONES, 48000))
    engine._install(0, sound())
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"\x00\x01" * 100)
    with qtbot.waitSignal(engine.pad_loaded, timeout=5000) as blocker:
        engine.load_pad(0, str(junk))
    assert blocker.args[1] is False and blocker.args[2]
    assert engine.sounds[0] is not None


def test_superseded_load_is_ignored(engine, qtbot, wav):
    attach(engine, (ROLE_HEADPHONES, 48000))
    first, second = wav(name="a.wav"), wav(name="b.wav", seconds=0.2)
    results = []
    engine.pad_loaded.connect(lambda *a: results.append(a))
    engine.load_pad(0, str(first))
    engine.load_pad(0, str(second))
    qtbot.waitUntil(lambda: len(results) >= 1, timeout=5000)
    qtbot.wait(300)
    assert [r[3] for r in results] == [str(second)]
    assert engine.sounds[0].duration == pytest.approx(0.2, abs=0.01)
