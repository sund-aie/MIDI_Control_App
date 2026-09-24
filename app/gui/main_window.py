"""
Main window: header (controller status, Set up pads, Stop all), output pickers,
and the on-screen Panda MINI. Connects the widgets, the audio engine, the MIDI
listener and the settings.
"""
import logging
import math
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QFileInfo, QObject, Qt, QTimer
from PySide6.QtGui import QActionGroup, QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QSlider, QToolButton, QVBoxLayout, QWidget, QWidgetAction)

from app import paths
from app.audio.decode import FILE_FILTER, MISSING, clean_library, import_to_library
from app.gui import theme
from app.gui.widgets.device import DeviceWidget
from app.midi.bindings import Binding, MidiEvent, NUM_PADS

log = logging.getLogger(__name__)

MODE_LABELS = (
    ("oneshot", "Play once (hit again to restart)"),
    ("toggle", "Play / stop (hit again to stop)"),
    ("hold", "Play while held down"),
    ("loop", "Loop (hit again to stop)"),
)
SLIDER_LEVELS = ("headphones", "mic", "keys", "master")
SLIDER_CAPTIONS = ("HEADPHONES", "MIC", "KEYS", "MASTER")
SLIDER_TIPS = ("volume of the pads in your headphones", "volume of the pads on the Discord mic",
               "volume of the keyboard synth", "master volume")
DISCORD_HELP = """<b>Play your pads into Discord (or OBS, Zoom, …)</b>
<ol>
<li>Install the free <a href="https://vb-audio.com/Cable/">VB-Audio Virtual Cable</a> and restart this app.</li>
<li>Here, set <b>Discord mic</b> to <b>CABLE Input</b> (picked automatically when found).</li>
<li>In Discord: <i>User Settings → Voice &amp; Video → Input Device</i> → <b>CABLE Output</b>.</li>
<li>In the same page turn off <i>Krisp / Noise Suppression</i> and <i>Echo Cancellation</i>,
    otherwise Discord may cut your sounds.</li>
<li>To keep talking with your real microphone too: Windows <i>Sound settings → More sound settings →
    Recording</i> → your microphone → <i>Properties → Listen</i> → tick <b>Listen to this device</b>
    and choose <b>CABLE Input</b>.</li>
</ol>
Each pad's menu lets you choose whether it goes to your headphones, the Discord mic, or both."""


def _short_status(message: str) -> str:
    """Pill text for a controller problem; the full message goes to the tooltip/status bar."""
    m = message.lower()
    for key, short in (("another program", "Controller busy"), ("unplugged", "Controller unplugged"),
                       ("waiting for", "Waiting for controller"), ("looking", "Looking for controller"),
                       ("not available", "MIDI unavailable"), ("no controller", "No controller")):
        if key in m:
            return short
    return "Controller problem" if message else "No controller"


class LevelMeter(QWidget):
    """Tiny horizontal meter so you can see sound going to an output."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(70, 10)
        self.level = 0.0
        self.running = False

    def push(self, peak: float, running: bool) -> None:
        level = max(peak, self.level * 0.82)
        if abs(level - self.level) > 0.005 or running != self.running:
            self.level, self.running = level, running
            self.update()

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2a2c31"))
        p.drawRoundedRect(self.rect(), 4, 4)
        if self.running and self.level > 0.003:
            w = self.width() * min(1.0, math.sqrt(self.level))
            p.setBrush(QColor(theme.DANGER if self.level > 0.98 else theme.OK))
            p.drawRoundedRect(0, 0, int(w), self.height(), 4, 4)
        p.end()


class MainWindow(QMainWindow):
    def __init__(self, config, engine, midi):
        super().__init__()
        self.config = config
        self.engine = engine
        self.midi = midi
        self._assigning = {}          # pad -> file the user just picked (loading)
        self._learn = None            # {'targets': [(group, i)], 'pos': int, 'got': set()}
        self._last_activity = 0.0
        self._prog_until = 0.0
        self._last_unmatched = 0.0
        self._last_output_check = 0.0
        self._keys_held = set()
        self._last_dir = ""
        self._started = False

        self.setWindowTitle("Panda MINI Soundboard")
        self.setWindowIcon(theme.app_icon())
        self.setMinimumSize(900, 580)
        self._restore_geometry()

        root = QWidget(objectName="root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 12, 16, 8)
        layout.setSpacing(10)
        layout.addLayout(self._build_header())
        layout.addLayout(self._build_outputs())
        layout.addWidget(self._build_hint())
        layout.addWidget(self._build_banner())
        self.device = DeviceWidget()
        layout.addWidget(self.device, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Click a pad to add a sound, or drop any sound or video file on it.")

        self._wire_device()
        self._wire_engine_and_midi()

        self._tick = QTimer(self)
        self._tick.setInterval(33)
        self._tick.timeout.connect(self._on_tick)
        QApplication.instance().installEventFilter(self)

    # ── building the window ─────────────────────────────────────

    def _build_header(self):
        row = QHBoxLayout()
        row.setSpacing(10)
        title = QLabel("Panda MINI Soundboard", objectName="title")
        row.addWidget(title)
        row.addSpacing(12)
        self.midi_button = QToolButton(objectName="midi")
        self.midi_button.setPopupMode(QToolButton.InstantPopup)
        self.midi_button.setToolTip("Which MIDI controller to listen to")
        self.midi_menu = QMenu(self)
        self.midi_button.setMenu(self.midi_menu)
        row.addWidget(self.midi_button)
        row.addStretch(1)
        self.setup_button = QPushButton("Set up controller", objectName="primary")
        self.setup_button.setToolTip("Hit each pad (then move each slider and knob) once, "
                                     "so everything here matches your real controller")
        self.setup_button.clicked.connect(self.start_setup)
        row.addWidget(self.setup_button)
        stop = QPushButton("■  Stop all sounds", objectName="stop")
        stop.setToolTip("Stop everything that is playing (Esc)")
        stop.clicked.connect(self.stop_all)
        row.addWidget(stop)
        self._set_midi_status(False, "", "Looking for your controller…")
        return row

    def _build_outputs(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("Headphones"))
        self.hp_combo = QComboBox()
        self.hp_combo.setToolTip("Where you hear the pads and the keys")
        row.addWidget(self.hp_combo)
        self.hp_meter = LevelMeter()
        row.addWidget(self.hp_meter)
        row.addSpacing(26)
        row.addWidget(QLabel("Discord mic"))
        self.mic_combo = QComboBox()
        self.mic_combo.setToolTip("A virtual cable (VB-Cable 'CABLE Input') that Discord/OBS use as a microphone")
        row.addWidget(self.mic_combo)
        self.mic_meter = LevelMeter()
        row.addWidget(self.mic_meter)
        help_button = QToolButton(objectName="help")
        help_button.setText("?")
        help_button.setToolTip("How to send the pads into Discord")
        help_button.clicked.connect(self._show_discord_help)
        row.addWidget(help_button)
        refresh = QToolButton(objectName="help")
        refresh.setText("↻")
        refresh.setToolTip("Look again for headphones / audio devices plugged in after the app started")
        refresh.clicked.connect(lambda: self._reopen_outputs(rescan=True))
        row.addWidget(refresh)
        row.addStretch(1)
        for combo in (self.hp_combo, self.mic_combo):
            combo.setFocusPolicy(Qt.StrongFocus)
        self.hp_combo.activated.connect(lambda _: self._on_output_picked("headphones_output", self.hp_combo))
        self.mic_combo.activated.connect(lambda _: self._on_output_picked("mic_output", self.mic_combo))
        return row

    def _build_hint(self):
        """First-run nudge: match the pads before anything else."""
        self.hint = QWidget()
        row = QHBoxLayout(self.hint)
        row.setContentsMargins(0, 0, 0, 0)
        label = QLabel("<b>First time here?</b> Click <b>Set up controller</b> and hit each pad on your "
                       "Panda MINI once, so every pad on screen matches the real one.", objectName="hint")
        label.setWordWrap(True)
        row.addWidget(label, 1)
        go = QPushButton("Set up controller", objectName="primary")
        go.clicked.connect(self.start_setup)
        row.addWidget(go)
        later = QPushButton("Not now")
        later.clicked.connect(self._dismiss_hint)
        row.addWidget(later)
        self.hint.hide()
        return self.hint

    def _dismiss_hint(self) -> None:
        self.hint.hide()
        self.config.data["midi"]["hint_dismissed"] = True
        self.config.changed()

    def _build_banner(self):
        self.banner = QWidget()
        row = QHBoxLayout(self.banner)
        row.setContentsMargins(0, 0, 0, 0)
        self.banner_label = QLabel(objectName="banner")
        row.addWidget(self.banner_label, 1)
        self.skip_button = QPushButton("Skip")
        self.skip_button.clicked.connect(self._learn_skip)
        row.addWidget(self.skip_button)
        cancel = QPushButton("Done")
        cancel.clicked.connect(lambda: self.stop_learning())
        row.addWidget(cancel)
        self.banner.hide()
        return self.banner

    def _wire_device(self):
        d = self.device
        for pad in d.pads:
            pad.pressed.connect(self._on_pad_pressed)
            pad.released.connect(lambda i: self.engine.release_pad(i))
            pad.add_requested.connect(self.choose_file)
            pad.menu_requested.connect(self._pad_menu)
            pad.files_dropped.connect(self._on_files_dropped)
        for i, slider in enumerate(d.sliders):
            slider.value_changed.connect(lambda v, i=i: self._apply_slider(i, v))
            slider.learn_requested.connect(lambda i=i: self.start_learning([("slider", i)]))
            slider.setToolTip(f"Slider {i + 1}: {SLIDER_TIPS[i]} · right-click to match it to your controller")
        for i, knob in enumerate(d.knobs):
            knob.learn_requested.connect(lambda i=i: self.start_learning([("knob", i)]))
        d.slider_captions = list(SLIDER_CAPTIONS)
        d.keyboard.note_pressed.connect(lambda n, v: self.engine.note_on(n, v))
        d.keyboard.note_released.connect(self.engine.note_off)
        d.buttons["◀"].clicked.connect(lambda: self._shift_keyboard(-12))
        d.buttons["▶"].clicked.connect(lambda: self._shift_keyboard(12))

    def _wire_engine_and_midi(self):
        self.engine.pad_loaded.connect(self._on_pad_loaded)
        m = self.midi
        m.pad_pressed.connect(lambda i: self.device.pads[i].set_held(True))
        m.pad_released.connect(lambda i: self.device.pads[i].set_held(False))
        m.key_on.connect(self._on_key_on)
        m.key_off.connect(lambda n: self.device.keyboard.set_note_active(n, False))
        m.slider_moved.connect(self._on_hw_slider)
        m.knob_moved.connect(lambda i, v: self.device.knobs[i].set_value(v))
        m.pitch_bend.connect(self._on_pitch)
        m.mod_wheel.connect(lambda v: self.device.buttons["MOD"].set_lit(v > 0))
        m.program.connect(self._on_program)
        m.activity.connect(self._on_activity)
        m.unmatched_pad.connect(self._on_unmatched_pad)
        m.learn_event.connect(self._on_learn_event)
        m.status_changed.connect(self._set_midi_status)
        m.devices_changed.connect(self._rebuild_midi_menu)

    # ── startup / shutdown ──────────────────────────────────────

    def _restore_geometry(self) -> None:
        """Saved size/position if it still fits a screen, else a size that fits this one."""
        geometry = self.config.data["window"].get("geometry")
        if geometry and self.restoreGeometry(QByteArray.fromBase64(geometry.encode())):
            if any(scr.availableGeometry().intersects(self.frameGeometry()) for scr in QApplication.screens()):
                return
        screen = self.screen() or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        w, h = min(1280, avail.width() - 40), min(830, avail.height() - 70)
        self.resize(max(w, self.minimumWidth()), max(h, self.minimumHeight()))
        self.move(avail.center() - self.rect().center())

    def start(self) -> None:
        """Apply settings, open audio outputs, load pad sounds, connect the controller."""
        cfg = self.config.data

        self.engine.levels.update(cfg["levels"])
        for i, key in enumerate(SLIDER_LEVELS):
            self.device.sliders[i].set_value(cfg["levels"][key])
        self.device.keyboard.set_base_note(cfg["keyboard"]["base_note"])

        # Outputs first, so the loader resamples straight to their rates.
        self._autodetect_mic()
        self._fill_output_combos()
        self._open_outputs()

        library = paths.library_dir()
        clean_library(library)
        for i in range(NUM_PADS):
            self._apply_pad_settings(i)
            pad_cfg = self.config.pad(i)
            if pad_cfg["file"]:
                path = Path(pad_cfg["file"])
                if not path.is_file() and (library / path.name).is_file():
                    pad_cfg["file"] = str(library / path.name)     # app folder was moved
                    self.config.changed()
                self.device.pads[i].set_loading()
                # also pulls sounds from older versions (e.g. in Downloads) into the library
                self.engine.load_pad(i, pad_cfg["file"],
                                     import_fn=lambda p, d, r: import_to_library(p, library, d, r))

        self.midi.set_control_map(self.config.control_map())
        self.midi.start(cfg["midi"]["input_device"])
        self.hint.setVisible(not cfg["midi"]["matched"] and not cfg["midi"]["hint_dismissed"])
        self._rebuild_midi_menu(self.midi.devices())
        self._tick.start()
        self._started = True

    def closeEvent(self, e) -> None:
        self.shutdown()
        super().closeEvent(e)

    def shutdown(self) -> None:
        if not self._started:
            return
        self._started = False
        self._tick.stop()
        self.config.data["window"]["geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        self.config.save_now()
        self.midi.stop()
        self.engine.close()

    # ── outputs ─────────────────────────────────────────────────

    def _autodetect_mic(self) -> None:
        audio = self.config.data["audio"]
        if audio["mic_output"] is None:          # never chosen: look for VB-Cable
            cable = self.engine.find_output("CABLE Input")
            if cable:
                audio["mic_output"] = cable
                self.config.changed()
                self.statusBar().showMessage(f"Found VB-Cable: pads also play into '{cable}' for Discord.", 8000)

    def _fill_output_combos(self) -> None:
        names = self.engine.list_outputs()
        audio = self.config.data["audio"]
        for combo, first, saved in ((self.hp_combo, ("System default", None), audio["headphones_output"]),
                                    (self.mic_combo, ("Off", ""), audio["mic_output"] or "")):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(*first)
            for name in names:
                combo.addItem(name, name)
            index = combo.findData(saved)
            if index < 0 and saved:
                combo.addItem(f"{saved} (not found)", saved)
                index = combo.count() - 1
            combo.setCurrentIndex(max(0, index))
            combo.blockSignals(False)

    def _on_output_picked(self, key: str, combo: QComboBox) -> None:
        """Save only the picker the user touched (so the mic stays 'not chosen' → VB-Cable auto-detect)."""
        audio = self.config.data["audio"]
        value = combo.currentData()
        if key == "mic_output":
            value = value or ""          # "" = the user turned the Discord mic off on purpose
        if audio[key] == value:
            return
        audio[key] = value
        self.config.changed()
        self._open_outputs()

    def _reopen_outputs(self, rescan: bool, reason: str = "") -> None:
        if rescan:
            self.engine.rescan_devices()
            self._fill_output_combos()
        self._open_outputs()
        if reason and not self.engine.lost_outputs():
            self.statusBar().showMessage(reason, 8000)

    def _open_outputs(self) -> None:
        audio = self.config.data["audio"]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            errors = self.engine.set_outputs(audio["headphones_output"], audio["mic_output"] or None)
        finally:
            QApplication.restoreOverrideCursor()
        if errors:
            self.statusBar().showMessage("  ".join(errors.values()), 12000)
            log.warning("Output problems: %s", errors)

    def _show_discord_help(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Pads into Discord")
        box.setTextFormat(Qt.RichText)
        box.setText(DISCORD_HELP)
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        box.exec()

    # ── pads ────────────────────────────────────────────────────

    def _apply_pad_settings(self, i: int) -> None:
        pad_cfg = self.config.pad(i)
        s = self.engine.settings[i]
        s.volume, s.mode = pad_cfg["volume"], pad_cfg["mode"]
        s.to_headphones, s.to_mic = pad_cfg["to_headphones"], pad_cfg["to_mic"]
        self.device.pads[i].set_options(s.mode, s.to_headphones, s.to_mic)

    def _on_pad_pressed(self, i: int) -> None:
        self.engine.trigger_pad(i)

    def choose_file(self, i: int) -> None:
        start_dir = self._last_dir or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, f"Choose a sound for Pad {i + 1}", start_dir, FILE_FILTER)
        if path:
            self._last_dir = str(Path(path).parent)
            self.assign_file(i, path)

    def _on_files_dropped(self, i: int, dropped: list, web: bool) -> None:
        """First file on this pad, any others on the next empty pads."""
        files = []
        for path in dropped:
            info = QFileInfo(path)
            if info.isShortcut() or info.isSymLink():
                path = info.symLinkTarget() or path          # Windows .lnk shortcuts
            if Path(path).is_file():
                files.append(path)
        if not files:
            self.statusBar().showMessage(
                "Save the file to your computer first, then drop it here." if web
                else "Drop sound or video files here (folders can't go on a pad).", 8000)
            return
        empty = [j for j in list(range(i + 1, NUM_PADS)) + list(range(i))
                 if self.engine.sounds[j] is None and j not in self._assigning and not self.config.pad(j)["file"]]
        targets = [i] + empty
        for pad, path in zip(targets, files):
            self.assign_file(pad, path)
        if len(files) > len(targets):
            self.statusBar().showMessage(f"Used {len(targets)} of {len(files)} files: no more empty pads.", 8000)

    def assign_file(self, i: int, path: str) -> None:
        if not Path(path).is_file():
            QMessageBox.warning(self, "Can't use this", "Please choose a file (not a folder).")
            return
        self._assigning[i] = path
        self.device.pads[i].set_loading()
        self.statusBar().showMessage(f"Loading '{Path(path).name}' onto Pad {i + 1}…")
        library = paths.library_dir()
        self.engine.load_pad(i, path, import_fn=lambda p, d, r: import_to_library(p, library, d, r))

    def _on_pad_loaded(self, i: int, ok: bool, info: str, requested: str) -> None:
        pad_cfg = self.config.pad(i)
        pad = self.device.pads[i]
        user_pick = self._assigning.get(i) == requested
        if user_pick:
            del self._assigning[i]
        if ok:
            if user_pick:
                pad_cfg["file"] = info
                pad_cfg["name"] = Path(requested).stem
                self.config.changed()
                sound = self.engine.sounds[i]
                note = " (only the first 5 minutes are used)" if sound is not None and sound.truncated else ""
                self.statusBar().showMessage(f"Pad {i + 1} is ready: {pad_cfg['name']}{note}", 8000)
            elif pad_cfg["file"] == requested and info != requested:
                pad_cfg["file"] = info             # now points at the library copy
                self.config.changed()
            pad.set_sound(pad_cfg["name"] or Path(info).stem)
            return
        if user_pick:
            # keep whatever the pad had before
            previous = self.engine.sounds[i]
            if previous is not None:
                pad.set_sound(pad_cfg["name"] or Path(previous.path).stem)
            elif pad_cfg["file"]:
                pad.set_error(f"Can't play “{pad_cfg['name'] or Path(pad_cfg['file']).stem}”\n"
                              "Click to choose again")
            else:
                pad.set_sound("")
            QMessageBox.warning(self, "Can't use this file", f"<b>{Path(requested).name}</b><br><br>{info}")
        else:
            name = pad_cfg["name"] or Path(requested).stem
            verb = "find" if info == MISSING else "play"
            pad.set_error(f"Can't {verb} “{name}”\nClick to choose again")
            self.statusBar().showMessage(f"Pad {i + 1} ({name}): {info}", 10000)

    def _pad_menu(self, i: int, pos) -> None:
        pad_cfg = self.config.pad(i)
        has_sound = self.engine.sounds[i] is not None
        menu = QMenu(self)
        title = menu.addAction(f"Pad {i + 1}" + (f" — {pad_cfg['name']}" if has_sound else ""))
        title.setEnabled(False)
        menu.addAction("Change sound…" if has_sound else "Choose sound…", lambda: self.choose_file(i))
        if has_sound:
            menu.addAction("Rename…", lambda: self._rename_pad(i))
            menu.addSeparator()
            modes = menu.addMenu("When you hit the pad")
            group = QActionGroup(modes)
            for mode, label in MODE_LABELS:
                act = modes.addAction(label)
                act.setCheckable(True)
                act.setChecked(pad_cfg["mode"] == mode)
                act.triggered.connect(lambda _=False, mode=mode: self._set_pad_option(i, "mode", mode))
                group.addAction(act)
            menu.addAction(self._volume_action(menu, i))
            hp = menu.addAction("Play in my headphones")
            hp.setCheckable(True)
            hp.setChecked(pad_cfg["to_headphones"])
            hp.toggled.connect(lambda on: self._set_pad_option(i, "to_headphones", on))
            mic = menu.addAction("Send to Discord mic")
            mic.setCheckable(True)
            mic.setChecked(pad_cfg["to_mic"])
            mic.toggled.connect(lambda on: self._set_pad_option(i, "to_mic", on))
        menu.addSeparator()
        binding = self.midi.control_map.pads[i]
        menu.addAction("Match to a pad on my controller…", lambda: self.start_learning([("pad", i)]))
        info = menu.addAction(f"Controller: {binding.describe()}" if binding else "Controller: not matched")
        info.setEnabled(False)
        if has_sound or pad_cfg["file"]:
            menu.addSeparator()
            menu.addAction("Remove sound", lambda: self._remove_sound(i))
        menu.exec(pos)
        menu.deleteLater()

    def _volume_action(self, menu: QMenu, i: int) -> QWidgetAction:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(24, 4, 14, 4)
        row.addWidget(QLabel("Volume"))
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setFixedWidth(150)
        value = int(round(self.config.pad(i)["volume"] * 100))
        slider.setValue(value)
        pct = QLabel(f"{value}%")
        pct.setFixedWidth(40)
        slider.valueChanged.connect(lambda v: (pct.setText(f"{v}%"), self._set_pad_option(i, "volume", v / 100)))
        row.addWidget(slider)
        row.addWidget(pct)
        action = QWidgetAction(menu)
        action.setDefaultWidget(box)
        return action

    def _set_pad_option(self, i: int, key: str, value) -> None:
        self.config.pad(i)[key] = value
        self.config.changed()
        self._apply_pad_settings(i)

    def _rename_pad(self, i: int) -> None:
        pad_cfg = self.config.pad(i)
        name, ok = QInputDialog.getText(self, f"Rename Pad {i + 1}", "Name shown on the pad:",
                                        QLineEdit.Normal, pad_cfg["name"])
        if ok and name.strip():
            pad_cfg["name"] = name.strip()
            self.config.changed()
            self.device.pads[i].set_sound(pad_cfg["name"])

    def _remove_sound(self, i: int) -> None:
        self._assigning.pop(i, None)
        self.engine.clear_pad(i)
        pad_cfg = self.config.pad(i)
        pad_cfg["file"], pad_cfg["name"] = None, ""
        self.config.changed()
        self.device.pads[i].set_sound("")

    def stop_all(self) -> None:
        self.engine.stop_all()
        self.device.keyboard.clear()

    # ── sliders / keyboard / hardware feedback ──────────────────

    def _apply_slider(self, i: int, value: float) -> None:
        key = SLIDER_LEVELS[i]
        self.engine.levels[key] = value
        self.config.data["levels"][key] = value
        self.config.changed()

    def _on_hw_slider(self, i: int, value: float) -> None:
        self.device.sliders[i].set_value(value)
        self._apply_slider(i, value)

    def _shift_keyboard(self, delta: int) -> None:
        kb = self.device.keyboard
        base = min(96, max(12, kb.base_note + delta))
        kb.set_base_note(base)
        self.config.data["keyboard"]["base_note"] = base
        self.config.changed()

    def _on_key_on(self, note: int, velocity: int) -> None:
        kb = self.device.keyboard
        if note < kb.base_note:                         # follow the controller's octave buttons
            kb.set_base_note(max(0, (note // 12) * 12))
        elif note >= kb.base_note + 25:
            kb.set_base_note(min(96, max(0, note - 12) // 12 * 12))
        kb.set_note_active(note, True)

    def _on_pitch(self, value: int) -> None:
        self.device.buttons["PITCH DOWN"].set_lit(value < -512)
        self.device.buttons["PITCH UP"].set_lit(value > 512)

    def _on_program(self, number: int) -> None:
        self._prog_until = time.monotonic() + 0.4
        self.device.buttons["PROG"].set_lit(True)
        self.statusBar().showMessage(f"Your controller sent program change {number}. "
                                     "If the pads stopped working, press PROG again on the controller.", 6000)

    def _on_activity(self) -> None:
        self._last_activity = time.monotonic()
        self.device.set_led(0, True)

    def _on_unmatched_pad(self, ev: MidiEvent) -> None:
        now = time.monotonic()
        if now - self._last_unmatched > 5 and self._learn is None:
            self._last_unmatched = now
            self.statusBar().showMessage(
                f"A pad sent {Binding.from_event(ev).describe()}, which isn't matched to any pad here. "
                "Click “Set up controller” and hit each pad once.", 10000)

    def _on_tick(self) -> None:
        now = time.monotonic()
        for i, pad in enumerate(self.device.pads):
            pad.set_playing(self.engine.is_playing(i), self.engine.progress(i))
        state = self.engine.output_state()
        hp, mic = state.get("headphones"), state.get("mic")
        self.hp_meter.push(hp["peak"] if hp else 0.0, bool(hp and hp["running"]))
        self.mic_meter.push(mic["peak"] if mic else 0.0, bool(mic and mic["running"]))
        if now - self._last_activity > 0.08:
            self.device.set_led(0, False)
        if now - self._last_output_check > 3.0:
            self._last_output_check = now
            lost = self.engine.lost_outputs()
            if lost:
                log.warning("Output stream(s) stopped: %s; reopening", lost)
                self._reopen_outputs(rescan=True, reason="An audio device changed; sound outputs were reopened.")
        if self._prog_until and now > self._prog_until:
            self._prog_until = 0.0
            self.device.buttons["PROG"].set_lit(False)
        if self._learn is not None:
            group, i = self._learn["targets"][self._learn["pos"]]
            if group == "pad":
                self.device.pads[i].set_learning(True, 0.5 + 0.5 * math.sin(now * 6.0))

    # ── controller connection ───────────────────────────────────

    def _set_midi_status(self, ok: bool, name: str, message: str) -> None:
        if ok:
            text, color = f"●  {name}", theme.OK
        else:
            text, color = f"●  {_short_status(message)}", theme.DANGER
        self.midi_button.setText(text)
        self.midi_button.setToolTip((message + "\n\n" if message else "") + "Click to choose which controller to use")
        self.midi_button.setStyleSheet(f"QToolButton#midi {{ color: {color}; }}")
        if not ok and message:
            self.statusBar().showMessage(message, 10000)
        if self._learn is not None:
            self._show_learn_step()

    def _choose_midi(self, name) -> None:
        self.config.data["midi"]["input_device"] = name     # None = automatic
        self.config.changed()
        self.midi.choose(name)

    def _rebuild_midi_menu(self, devices) -> None:
        menu = self.midi_menu
        menu.clear()
        head = menu.addAction("Listen to:")
        head.setEnabled(False)
        if getattr(self, "_midi_group", None) is not None:
            self._midi_group.deleteLater()
        group = self._midi_group = QActionGroup(menu)
        auto = menu.addAction("Automatic (find the Panda MINI)")
        auto.setCheckable(True)
        auto.setChecked(self.midi.wanted is None)
        auto.triggered.connect(lambda: self._choose_midi(None))
        group.addAction(auto)
        for name in devices:
            act = menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(self.midi.wanted == name)
            act.triggered.connect(lambda _=False, name=name: self._choose_midi(name))
            group.addAction(act)
        if not devices:
            none = menu.addAction("(no MIDI devices found)")
            none.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Look again", self.midi.poll)

    # ── learning (matching screen controls to the hardware) ─────

    def start_setup(self) -> None:
        """Walk through the pads, then the sliders (each step can be skipped)."""
        self.start_learning([("pad", i) for i in range(NUM_PADS)] + [("slider", i) for i in range(4)])

    def start_learning(self, targets) -> None:
        self.stop_learning(quiet=True)
        self.hint.hide()
        self._learn = {"targets": list(targets), "pos": 0, "got": set(), "pads": 0}
        self.midi.learning = True
        self.skip_button.setVisible(len(targets) > 1)
        self.banner.show()
        self._show_learn_step()

    def _show_learn_step(self) -> None:
        group, i = self._learn["targets"][self._learn["pos"]]
        self._clear_learn_highlights()
        if group == "pad":
            what = f"Hit <b>Pad {i + 1}</b> on your Panda MINI"
        elif group == "slider":
            what = f"Move <b>slider {i + 1}</b> on your Panda MINI"
            self.device.sliders[i].set_learning(True)
        else:
            what = f"Turn <b>knob {i + 1}</b> on your Panda MINI"
            self.device.knobs[i].set_learning(True)
        total = len(self._learn["targets"])
        step = f"  <span style='color:#9fdcff'>({self._learn['pos'] + 1} of {total})</span>" if total > 1 else ""
        warn = "" if self.midi.connected else "  —  <b>controller not connected</b>"
        self.banner_label.setText(what + step + warn)

    def _clear_learn_highlights(self) -> None:
        for pad in self.device.pads:
            if pad.learning:
                pad.set_learning(False)
        for w in self.device.sliders + self.device.knobs:
            if w.learning:
                w.set_learning(False)

    def _on_learn_event(self, ev: MidiEvent) -> None:
        learn = self._learn
        if learn is None:
            return
        group, i = learn["targets"][learn["pos"]]
        binding = Binding.from_event(ev)
        if binding is None:
            return
        current = self.midi.control_map.lookup(ev)
        if binding in learn["got"]:
            return              # same pad hit twice, or a slider still moving
        if group == "pad":
            if ev.kind == "cc" and current is not None and current[0] != "pad":
                return          # a slider or knob was bumped
        elif ev.kind != "cc":
            return              # sliders and knobs send CC messages
        learn["got"].add(binding)
        if group == "pad":
            learn["pads"] += 1
        cmap = self.midi.control_map.with_binding(group, i, binding)
        self.midi.set_control_map(cmap)
        self.config.set_control_map(cmap)
        label = {"pad": "Pad", "slider": "Slider", "knob": "Knob"}[group]
        self.statusBar().showMessage(f"{label} {i + 1} matched ({binding.describe()}).", 6000)
        self._learn_advance()

    def _learn_skip(self) -> None:
        if self._learn is not None:
            self._learn_advance()

    def _learn_advance(self) -> None:
        learn = self._learn
        finished = learn["targets"][learn["pos"]]
        learn["pos"] += 1
        upcoming = learn["targets"][learn["pos"]] if learn["pos"] < len(learn["targets"]) else None
        if finished == ("pad", NUM_PADS - 1) and len(learn["targets"]) > 1 and learn["pads"]:
            self.config.data["midi"]["matched"] = True   # the walkthrough really matched pads
            self.config.changed()
            self.statusBar().showMessage(f"{learn['pads']} of 8 pads now match your controller.", 8000)
        if upcoming is None:
            self.stop_learning(quiet=True)
            if len(learn["targets"]) > 1:
                self.statusBar().showMessage("All set — your controller is matched.", 8000)
        else:
            self._show_learn_step()

    def stop_learning(self, quiet: bool = False) -> None:
        was_learning = self._learn is not None
        self._learn = None
        self.midi.learning = False
        self._clear_learn_highlights()
        self.banner.hide()
        if was_learning and not quiet:
            self.statusBar().showMessage("Stopped matching. Pads you already hit keep their new match.", 5000)

    # ── computer keyboard: 1-8 play pads, Esc stops ─────────────

    def changeEvent(self, e) -> None:
        if e.type() == QEvent.ActivationChange and not self.isActiveWindow():
            for i in list(self._keys_held):         # key-ups go to the other app after Alt+Tab
                self.device.pads[i].set_held(False)
                self.engine.release_pad(i)
            self._keys_held.clear()
        super().changeEvent(e)

    def eventFilter(self, obj: QObject, e: QEvent) -> bool:
        if e.type() == QEvent.Wheel and isinstance(obj, QComboBox) and not obj.view().isVisible():
            e.ignore()
            return True                              # scrolling past a picker must not switch devices
        if e.type() in (QEvent.KeyPress, QEvent.KeyRelease) and self.isActiveWindow():
            focus = QApplication.focusWidget()
            if isinstance(focus, QLineEdit) or QApplication.activeModalWidget() is not None \
                    or QApplication.activePopupWidget() is not None:
                return False
            key = e.key()
            if key == Qt.Key_Escape and e.type() == QEvent.KeyPress:
                if self._learn is not None:
                    self.stop_learning()
                else:
                    self.stop_all()
                return True
            if Qt.Key_1 <= key <= Qt.Key_8 and not e.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
                i = key - Qt.Key_1
                if e.isAutoRepeat():
                    return True
                if e.type() == QEvent.KeyPress and i not in self._keys_held:
                    self._keys_held.add(i)
                    self.device.pads[i].set_held(True)
                    if self.engine.sounds[i] is not None:
                        self.engine.trigger_pad(i)
                elif e.type() == QEvent.KeyRelease:
                    self._keys_held.discard(i)
                    self.device.pads[i].set_held(False)
                    self.engine.release_pad(i)
                return True
        return super().eventFilter(obj, e)
