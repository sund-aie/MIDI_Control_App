"""
Where the app keeps its files.

- User data (config, imported sounds, logs) lives in %APPDATA%\\PandaMINI when
  running as a packaged .exe, and in <repo>/user_data when running from source.
  Set PANDAMINI_DATA_DIR to override (used by the tests).
- Read-only bundled resources are resolved relative to the PyInstaller bundle
  (sys._MEIPASS) or the repository root.
"""
import os
import sys
from pathlib import Path

APP_DIR_NAME = "PandaMINI"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    override = os.environ.get("PANDAMINI_DATA_DIR")
    if override:
        base = Path(override)
    elif is_frozen():
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA") or Path.home()) / APP_DIR_NAME
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
        else:
            base = Path.home() / ".local" / "share" / APP_DIR_NAME
    else:
        base = repo_root() / "user_data"
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path() -> Path:
    return user_data_dir() / "config.json"


def legacy_config_paths() -> list:
    """Config files written by older versions of the app (migrated on first run)."""
    if os.environ.get("PANDAMINI_DATA_DIR") or is_frozen():
        return []
    return [repo_root() / "assets" / "config.json"]


def library_dir() -> Path:
    """Folder holding copies of every sound the user put on a pad."""
    path = user_data_dir() / "sounds"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = user_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resource_path(relative_path: str) -> Path:
    """Absolute path to a bundled read-only resource (dev and PyInstaller)."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = repo_root()
    return base / relative_path
