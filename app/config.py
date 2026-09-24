"""
Settings stored as JSON (see app.paths.config_path), saved shortly after every change.

Schema version 2. Older files (version 1, written by the first releases) are
migrated automatically.
"""
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QObject, QTimer

from app import paths
from app.midi.bindings import (DEFAULT_KNOBS, DEFAULT_PADS, DEFAULT_SLIDERS, NUM_KNOBS,
                               NUM_PADS, NUM_SLIDERS, Binding, ControlMap)

log = logging.getLogger(__name__)

VERSION = 2
MODES = ("oneshot", "toggle", "hold", "loop")
LEVEL_KEYS = ("headphones", "mic", "keys", "master")


def _default_pad(i: int) -> dict:
    return {"file": None, "name": "", "volume": 0.8, "mode": "oneshot",
            "to_headphones": True, "to_mic": True, "binding": DEFAULT_PADS[i].to_dict()}


def default_config() -> dict:
    return {
        "version": VERSION,
        "audio": {"headphones_output": None, "mic_output": None},
        "levels": {"headphones": 0.8, "mic": 0.8, "keys": 0.6, "master": 1.0},
        "midi": {"input_device": None, "matched": False},
        "pads": [_default_pad(i) for i in range(NUM_PADS)],
        "controls": {
            "sliders": [b.to_dict() if b else None for b in DEFAULT_SLIDERS],
            "knobs": [b.to_dict() if b else None for b in DEFAULT_KNOBS],
        },
        "keyboard": {"base_note": 48},
        "window": {"geometry": None},
    }


class Config(QObject):
    """The settings dict plus debounced, atomic saving."""

    def __init__(self, path: Optional[Path] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.path = Path(path) if path else paths.config_path()
        self.data = self._load()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.save_now)

    # ── access helpers ──────────────────────────────────────────

    def pad(self, i: int) -> dict:
        return self.data["pads"][i]

    def control_map(self) -> ControlMap:
        pads = [Binding.from_dict(p.get("binding")) if p.get("binding") else None for p in self.data["pads"]]
        sliders = [Binding.from_dict(b) if b else None for b in self.data["controls"]["sliders"]]
        knobs = [Binding.from_dict(b) if b else None for b in self.data["controls"]["knobs"]]
        return ControlMap(pads, sliders, knobs)

    def set_control_map(self, cmap: ControlMap) -> None:
        for i, b in enumerate(cmap.pads):
            self.data["pads"][i]["binding"] = b.to_dict() if b else None
        self.data["controls"]["sliders"] = [b.to_dict() if b else None for b in cmap.sliders]
        self.data["controls"]["knobs"] = [b.to_dict() if b else None for b in cmap.knobs]
        self.changed()

    # ── saving ──────────────────────────────────────────────────

    def changed(self) -> None:
        self._timer.start()

    def save_now(self) -> None:
        self._timer.stop()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError as e:
            log.error("Could not save settings to %s: %s", self.path, e)

    # ── loading ─────────────────────────────────────────────────

    def _load(self) -> dict:
        raw = self._read(self.path)
        if raw is None:
            for legacy in paths.legacy_config_paths():
                raw = self._read(legacy)
                if raw is not None:
                    log.info("Importing settings from %s", legacy)
                    break
        if raw is None:
            return default_config()
        if raw.get("version") != VERSION:
            raw = migrate_v1(raw)
        return sanitize(raw)

    def _read(self, path: Path) -> Optional[dict]:
        if not path.is_file():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return raw if isinstance(raw, dict) else None
        except (OSError, ValueError) as e:
            log.error("Settings file %s is unreadable (%s); starting fresh", path, e)
            try:
                os.replace(path, path.with_suffix(".broken.json"))
            except OSError:
                pass
            return None


def migrate_v1(old: dict) -> dict:
    """Convert the original settings layout (parallel lists under 'pads')."""
    new = default_config()
    audio = old.get("audio") or {}
    if isinstance(audio, dict):
        new["audio"]["headphones_output"] = audio.get("sampler_output")
        new["audio"]["mic_output"] = audio.get("soundboard_output")
    midi = old.get("midi") or {}
    if isinstance(midi, dict):
        new["midi"]["input_device"] = midi.get("input_device")

    pads = old.get("pads")
    if isinstance(pads, dict):
        def column(key):
            value = pads.get(key)
            return value if isinstance(value, list) else []
        samples, volumes, modes = column("samples"), column("volumes"), column("modes")
        route_mic, route_mon = column("route_mic"), column("route_mon")
        for i in range(NUM_PADS):
            pad = new["pads"][i]
            if i < len(samples) and isinstance(samples[i], str) and samples[i]:
                pad["file"] = samples[i]
                pad["name"] = Path(samples[i]).stem
            if i < len(volumes):
                pad["volume"] = volumes[i]
            if i < len(modes):
                pad["mode"] = {"gate": "hold"}.get(modes[i], modes[i])
            if i < len(route_mic):
                pad["to_mic"] = route_mic[i]
            if i < len(route_mon):
                pad["to_headphones"] = route_mon[i]
    return new


def sanitize(raw: dict) -> dict:
    """Fill gaps and fix wrong types so the rest of the app can trust the dict."""
    cfg = default_config()

    def section(name):
        value = raw.get(name)
        return value if isinstance(value, dict) else {}

    audio = section("audio")
    for key in ("headphones_output", "mic_output"):
        value = audio.get(key)
        cfg["audio"][key] = value if isinstance(value, str) or value is None else None

    levels = section("levels")
    for key in LEVEL_KEYS:
        cfg["levels"][key] = _unit(levels.get(key), cfg["levels"][key])

    midi = section("midi")
    device = midi.get("input_device")
    cfg["midi"]["input_device"] = device if isinstance(device, str) and device else None
    cfg["midi"]["matched"] = midi.get("matched") is True

    pads = raw.get("pads")
    if isinstance(pads, list):
        for i in range(min(NUM_PADS, len(pads))):
            src = pads[i] if isinstance(pads[i], dict) else {}
            dst = cfg["pads"][i]
            f = src.get("file")
            dst["file"] = f if isinstance(f, str) and f else None
            name = src.get("name")
            dst["name"] = name if isinstance(name, str) else ""
            if dst["file"] and not dst["name"]:
                dst["name"] = Path(dst["file"]).stem
            dst["volume"] = _unit(src.get("volume"), dst["volume"])
            dst["mode"] = src.get("mode") if src.get("mode") in MODES else "oneshot"
            dst["to_headphones"] = bool(src.get("to_headphones", True))
            dst["to_mic"] = bool(src.get("to_mic", True))
            if "binding" in src:
                b = Binding.from_dict(src["binding"]) if src["binding"] else None
                dst["binding"] = b.to_dict() if b else None

    controls = section("controls")
    for key, count in (("sliders", NUM_SLIDERS), ("knobs", NUM_KNOBS)):
        items = controls.get(key)
        if isinstance(items, list):
            out = []
            for i in range(count):
                b = Binding.from_dict(items[i]) if i < len(items) and items[i] else None
                out.append(b.to_dict() if b else None)
            cfg["controls"][key] = out

    base = section("keyboard").get("base_note")
    if isinstance(base, int) and 0 <= base <= 96 and base % 12 == 0:
        cfg["keyboard"]["base_note"] = base

    geometry = section("window").get("geometry")
    cfg["window"]["geometry"] = geometry if isinstance(geometry, str) else None
    return cfg


def _unit(value: Any, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    return min(1.0, max(0.0, v))

