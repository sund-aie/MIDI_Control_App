"""End-to-end GUI flows (offscreen): upload, pad options, controller matching, shortcuts."""
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from app import paths
from app.audio.engine import ROLE_HEADPHONES, AudioEngine, OutputBus
from app.config import Config
from app.gui.main_window import MainWindow
from app.midi.bindings import Binding, MidiEvent
from app.midi.listener import MidiListener
from tests.test_midi import FakeBackend


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("PANDAMINI_DATA_DIR", str(tmp_path / "data"))
    config = Config(tmp_path / "config.json")
    engine = AudioEngine()
    monkeypatch.setattr(engine, "set_outputs", lambda hp, mic: {})
    midi = MidiListener(engine, backend=FakeBackend(names=["WORLDE Panda MINI"]))
    w = MainWindow(config, engine, midi)
    qtbot.addWidget(w)
    w.show()
    w.start()
    bus = OutputBus(engine, ROLE_HEADPHONES, None, "test")
    bus._prepare(48000)
    engine._buses = (bus,)
    yield w
    w.shutdown()


def load(window, qtbot, pad, path):
    with qtbot.waitSignal(window.engine.pad_loaded, timeout=5000):
        window.assign_file(pad, str(path))


def test_first_run_shows_setup_hint(window):
    assert window.hint.isVisible()
    assert window.midi.connected == "WORLDE Panda MINI"


def test_upload_any_file_to_any_pad(window, qtbot, wav):
    for pad in (0, 3, 7):
        src = wav(name=f"clip{pad}.wav")
        load(window, qtbot, pad, src)
        cfg = window.config.pad(pad)
        assert cfg["name"] == f"clip{pad}"
        assert Path(cfg["file"]).parent == paths.library_dir()          # copied into the library
        assert window.device.pads[pad].name == f"clip{pad}"
        assert window.engine.sounds[pad] is not None


def test_bad_file_keeps_old_sound_and_warns(window, qtbot, wav, tmp_path, monkeypatch):
    load(window, qtbot, 2, wav(name="good.wav"))
    warnings = []
    monkeypatch.setattr("app.gui.main_window.QMessageBox.warning", lambda *a: warnings.append(a))
    junk = tmp_path / "broken.mp3"
    junk.write_bytes(b"nope" * 50)
    load(window, qtbot, 2, junk)
    assert warnings and window.device.pads[2].name == "good"
    assert window.config.pad(2)["name"] == "good"


def test_missing_file_on_startup_marks_pad(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("PANDAMINI_DATA_DIR", str(tmp_path / "data"))
    config = Config(tmp_path / "config.json")
    config.pad(1)["file"] = str(tmp_path / "gone.wav")
    config.pad(1)["name"] = "gone"
    engine = AudioEngine()
    monkeypatch.setattr(engine, "set_outputs", lambda hp, mic: {})
    w = MainWindow(config, engine, MidiListener(engine, backend=FakeBackend(names=[])))
    qtbot.addWidget(w)
    w.start()
    qtbot.waitUntil(lambda: bool(w.device.pads[1].error), timeout=5000)
    assert "gone" in w.device.pads[1].error
    assert config.pad(1)["file"]                                        # kept for when it comes back
    w.shutdown()


def test_pad_options_reach_engine_and_config(window, qtbot, wav):
    load(window, qtbot, 0, wav())
    window._set_pad_option(0, "mode", "loop")
    window._set_pad_option(0, "to_mic", False)
    window._set_pad_option(0, "volume", 0.25)
    s = window.engine.settings[0]
    assert (s.mode, s.to_mic, s.volume) == ("loop", False, 0.25)
    assert window.config.pad(0)["mode"] == "loop"
    window._remove_sound(0)
    assert window.engine.sounds[0] is None and window.config.pad(0)["file"] is None


def test_setup_walkthrough_matches_pads_then_sliders(window):
    window.start_setup()
    assert window.midi.learning and window.banner.isVisible()
    notes = [44, 45, 46, 47, 40, 41, 42, 43]                           # e.g. rows swapped on the hardware
    for i, note in enumerate(notes):
        window.midi.handle(MidiEvent("note_on", 9, note, 100))
        window.midi.handle(MidiEvent("note_on", 9, note, 90))          # double hit is ignored
        window.midi.handle(MidiEvent("note_off", 9, note, 0))
        QApplication.processEvents()
    assert window.config.data["midi"]["matched"] is True
    assert not window.hint.isVisible()
    for cc in (70, 70, 71, 72, 73):                                     # slider 1 keeps sending while moving
        window.midi.handle(MidiEvent("cc", 0, cc, 64))
        QApplication.processEvents()
    assert window._learn is None                                         # walkthrough ended after the sliders
    cmap = window.midi.control_map
    assert [b.number for b in cmap.pads] == notes
    assert [b.number for b in cmap.sliders] == [70, 71, 72, 73]
    assert window.config.control_map().pads[0] == Binding("note", 9, 44)
    assert not window.midi.learning


def test_matched_pad_plays_from_hardware(window, qtbot, wav):
    load(window, qtbot, 5, wav())
    window.start_learning([("pad", 5)])
    window.midi.handle(MidiEvent("note_on", 9, 60, 100))
    QApplication.processEvents()
    window.midi.handle(MidiEvent("note_on", 9, 60, 100))
    assert window.engine.is_playing(5)


def test_number_keys_play_pads_and_escape_stops(window, qtbot, wav):
    load(window, qtbot, 1, wav(seconds=2))
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow, timeout=2000)
    QApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, Qt.Key_2, Qt.NoModifier, "2"))
    assert window.engine.is_playing(1)
    QApplication.sendEvent(window, QKeyEvent(QEvent.KeyRelease, Qt.Key_2, Qt.NoModifier, "2"))
    QApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not window.engine.is_playing(1)


def test_sliders_set_levels(window):
    window._on_hw_slider(1, 0.3)
    assert window.engine.levels["mic"] == 0.3
    assert window.config.data["levels"]["mic"] == 0.3
    assert window.device.sliders[1].value() == pytest.approx(0.3)


def test_keyboard_follows_controller_octave(window):
    kb = window.device.keyboard
    window._on_key_on(30, 100)
    assert 30 in kb.note_range()
    window._on_key_on(90, 100)
    assert 90 in kb.note_range()


def test_old_sound_paths_are_pulled_into_library(qtbot, tmp_path, monkeypatch, wav):
    monkeypatch.setenv("PANDAMINI_DATA_DIR", str(tmp_path / "data"))
    src = wav(name="from downloads.wav")
    config = Config(tmp_path / "config.json")
    config.pad(0)["file"], config.pad(0)["name"] = str(src), "from downloads"
    engine = AudioEngine()
    monkeypatch.setattr(engine, "set_outputs", lambda hp, mic: {})
    w = MainWindow(config, engine, MidiListener(engine, backend=FakeBackend(names=[])))
    qtbot.addWidget(w)
    w.start()
    qtbot.waitUntil(lambda: w.device.pads[0].name == "from downloads", timeout=5000)
    assert Path(config.pad(0)["file"]).parent == paths.library_dir()
    w.shutdown()


def test_dialogs_use_dark_palette(qapp):
    from PySide6.QtGui import QPalette
    from app.gui import theme
    theme.apply(qapp)
    pal = qapp.palette()
    assert pal.color(QPalette.Window).lightness() < 60
    assert pal.color(QPalette.Base).lightness() < 60
    assert pal.color(QPalette.Text).lightness() > 200


def test_setup_with_nothing_matched_keeps_first_run_hint(window):
    window.start_setup()
    for _ in range(8):
        window._learn_skip()
    window.stop_learning()
    assert window.config.data["midi"]["matched"] is False


def test_losing_focus_releases_held_number_keys(window, qtbot, wav):
    load(window, qtbot, 0, wav(seconds=2))
    window._set_pad_option(0, "mode", "hold")
    window._keys_held.add(0)
    window.engine.trigger_pad(0)
    window.changeEvent(QEvent(QEvent.ActivationChange))
    if not window.isActiveWindow():
        assert not window._keys_held and not window.engine.is_playing(0)


def test_wheel_over_output_picker_does_not_switch_device(window):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    window.hp_combo.addItem("Other device", "Other device")
    before = window.hp_combo.currentIndex()
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120), Qt.NoButton,
                     Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(window.hp_combo, ev)
    assert window.hp_combo.currentIndex() == before


def test_picking_headphones_leaves_mic_auto_detect_alone(window):
    window.hp_combo.addItem("Other device", "Other device")
    window.hp_combo.setCurrentIndex(window.hp_combo.count() - 1)
    window._on_output_picked("headphones_output", window.hp_combo)
    audio = window.config.data["audio"]
    assert audio["headphones_output"] == "Other device"
    assert audio["mic_output"] is None                              # still "not chosen": VB-Cable auto-detect
    window.mic_combo.setCurrentIndex(0)                             # "Off"
    window._on_output_picked("mic_output", window.mic_combo)
    assert audio["mic_output"] == ""


def test_not_now_is_remembered(window):
    window._dismiss_hint()
    assert window.config.data["midi"]["hint_dismissed"] is True


def test_moved_app_folder_finds_library_copies(qtbot, tmp_path, monkeypatch, wav):
    monkeypatch.setenv("PANDAMINI_DATA_DIR", str(tmp_path / "data"))
    copy = paths.library_dir() / "horn.wav"
    copy.write_bytes(wav(name="horn.wav").read_bytes())
    config = Config(tmp_path / "config.json")
    config.pad(3)["file"] = str(tmp_path / "old place" / "user_data" / "sounds" / "horn.wav")
    config.pad(3)["name"] = "horn"
    engine = AudioEngine()
    monkeypatch.setattr(engine, "set_outputs", lambda hp, mic: {})
    w = MainWindow(config, engine, MidiListener(engine, backend=FakeBackend(names=[])))
    qtbot.addWidget(w)
    w.start()
    qtbot.waitUntil(lambda: w.device.pads[3].name == "horn", timeout=5000)
    assert Path(config.pad(3)["file"]) == copy
    w.shutdown()


def test_dropping_several_files_fills_empty_pads(window, qtbot, wav):
    load(window, qtbot, 1, wav(name="existing.wav"))
    files = [str(wav(name=f"drop{k}.wav")) for k in range(3)]
    with qtbot.waitSignals([window.engine.pad_loaded] * 3, timeout=8000):
        window._on_files_dropped(0, files, False)
    names = [window.config.pad(i)["name"] for i in range(4)]
    assert names == ["drop0", "existing", "drop1", "drop2"]


def test_dropping_a_web_link_explains(window):
    window._on_files_dropped(0, [], True)
    assert "Save the file" in window.statusBar().currentMessage()


def test_unplayable_saved_file_says_cant_play(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("PANDAMINI_DATA_DIR", str(tmp_path / "data"))
    junk = tmp_path / "junk.mp3"
    junk.write_bytes(b"not audio" * 100)
    config = Config(tmp_path / "config.json")
    config.pad(0)["file"], config.pad(0)["name"] = str(junk), "junk"
    engine = AudioEngine()
    monkeypatch.setattr(engine, "set_outputs", lambda hp, mic: {})
    w = MainWindow(config, engine, MidiListener(engine, backend=FakeBackend(names=[])))
    qtbot.addWidget(w)
    w.start()
    qtbot.waitUntil(lambda: bool(w.device.pads[0].error), timeout=5000)
    assert "Can't play" in w.device.pads[0].error
    w.shutdown()
