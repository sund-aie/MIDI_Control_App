import json

from app.config import Config, default_config, migrate_v1, sanitize
from app.midi.bindings import Binding, ControlMap

LEGACY = {
    "audio": {"soundboard_output": "CABLE Input (VB-Audio Virtual Cable)", "sampler_output": None},
    "midi": {"input_device": "WORLDE", "channel": 1},
    "pads": {
        "samples": ["C:/Users/SAM22/Downloads/هذا اكبر كويحه بالمنطقه.mp3"] + [None] * 7,
        "volumes": [0.748, 0.708, 0.535, 1.0, 1.0, 1.0, 1.0, 1.0],
        "modes": ["oneshot", "gate", "loop"] + ["oneshot"] * 5,
        "route_mic": [True] * 8,
        "route_mon": [True, False] + [True] * 6,
    },
}


def test_migrates_first_version_settings():
    cfg = sanitize(migrate_v1(LEGACY))
    assert cfg["version"] == 2
    assert cfg["audio"]["mic_output"] == "CABLE Input (VB-Audio Virtual Cable)"
    assert cfg["audio"]["headphones_output"] is None
    assert cfg["midi"]["input_device"] == "WORLDE"
    pad0 = cfg["pads"][0]
    assert pad0["file"].endswith("بالمنطقه.mp3") and pad0["name"] == "هذا اكبر كويحه بالمنطقه"
    assert pad0["volume"] == 0.748
    assert cfg["pads"][1]["mode"] == "hold" and cfg["pads"][1]["to_headphones"] is False
    assert cfg["pads"][2]["mode"] == "loop"
    assert cfg["pads"][3]["file"] is None


def test_round_trip_and_reload(tmp_path, qapp):
    path = tmp_path / "config.json"
    cfg = Config(path)
    cfg.pad(4)["file"] = str(tmp_path / "x.wav")
    cfg.pad(4)["name"] = "Airhorn"
    cfg.data["levels"]["mic"] = 0.3
    cmap = cfg.control_map().with_binding("pad", 4, Binding("note", 9, 40))
    cfg.set_control_map(cmap)
    cfg.save_now()
    again = Config(path)
    assert again.pad(4)["name"] == "Airhorn"
    assert again.data["levels"]["mic"] == 0.3
    assert again.control_map().pads[4] == Binding("note", 9, 40)


def test_legacy_file_is_upgraded_in_place(tmp_path, qapp):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(LEGACY), encoding="utf-8")
    cfg = Config(path)
    assert cfg.data["version"] == 2 and cfg.pad(0)["file"]


def test_broken_file_starts_fresh_and_is_kept_aside(tmp_path, qapp):
    path = tmp_path / "config.json"
    path.write_text("{ not json", encoding="utf-8")
    cfg = Config(path)
    assert cfg.data == default_config()
    assert (tmp_path / "config.broken.json").exists()


def test_sanitize_fixes_bad_values():
    raw = default_config()
    raw["pads"][0].update(volume="loud", mode="explode", binding={"type": "note", "number": 300})
    raw["levels"]["master"] = 7
    raw["keyboard"]["base_note"] = 50
    cfg = sanitize(raw)
    assert cfg["pads"][0]["volume"] == 0.8 and cfg["pads"][0]["mode"] == "oneshot"
    assert cfg["pads"][0]["binding"] is None
    assert cfg["levels"]["master"] == 1.0
    assert cfg["keyboard"]["base_note"] == 48


def test_default_map_matches_defaults():
    assert isinstance(ControlMap.defaults(), ControlMap)


def test_bom_file_is_read_not_reset(tmp_path, qapp):
    path = tmp_path / "config.json"
    cfg = Config(path)
    cfg.pad(2)["name"] = "Kept"
    cfg.save_now()
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())       # saved by Notepad "UTF-8 with BOM"
    assert Config(path).pad(2)["name"] == "Kept"


def test_corrupt_file_falls_back_to_backup(tmp_path, qapp):
    path = tmp_path / "config.json"
    cfg = Config(path)
    cfg.pad(0)["name"] = "First"
    cfg.save_now()
    cfg.pad(0)["name"] = "Second"
    cfg.save_now()                                               # previous file -> config.bak.json
    path.write_text("{ truncated", encoding="utf-8")
    assert Config(path).pad(0)["name"] == "First"
    assert (tmp_path / "config.broken.json").exists()


def test_legacy_file_is_never_modified(tmp_path, qapp, monkeypatch):
    legacy = tmp_path / "legacy.json"
    legacy.write_text("{ broken", encoding="utf-8")
    monkeypatch.setattr("app.paths.legacy_config_paths", lambda: [legacy])
    Config(tmp_path / "config.json")
    assert legacy.read_text(encoding="utf-8") == "{ broken"
    assert not (tmp_path / "legacy.broken.json").exists()


def test_newer_version_is_backed_up_not_wiped(tmp_path, qapp):
    path = tmp_path / "config.json"
    raw = default_config()
    raw["version"] = 3
    raw["pads"][1]["name"] = "Future"
    raw["pads"][1]["file"] = "x.wav"
    path.write_text(json.dumps(raw), encoding="utf-8")
    cfg = Config(path)
    assert cfg.pad(1)["name"] == "Future"
    assert (tmp_path / "config.v3.bak.json").exists()


def test_absurd_values_do_not_stop_startup(tmp_path, qapp):
    path = tmp_path / "config.json"
    path.write_text('{"version": 2, "levels": {"mic": 1e400}, '
                    '"pads": [{"volume": 1e999, "binding": {"type": "note", "number": 1e400}}]}',
                    encoding="utf-8")
    cfg = Config(path)
    assert cfg.pad(0)["binding"] is None and cfg.data["levels"]["mic"] == 1.0
