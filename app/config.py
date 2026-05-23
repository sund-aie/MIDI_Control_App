"""
PandaMINI Core Engine - Configuration Management
Handles JSON state serialization with a 500ms debounce save timer
"""
import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional
from PySide6.QtCore import QTimer, QObject, Signal

from app.paths import get_config_path


class ConfigManager(QObject):
    """Thread-safe configuration manager with debounced saving."""
    
    config_changed = Signal(dict)
    config_saved = Signal()
    
    DEFAULT_CONFIG = {
        'audio': {
            'soundboard_output': None,
            'sampler_output': None,
            'blocksize': 256,
            'latency': 'low',
            'sample_rate': 48000,
        },
        'midi': {
            'input_device': None,
            'channel': 1,
        },
        'synth': {
            'octave': 3,
            'volume': 0.75,
            'voices': 16,
        },
        'mixer': {
            'channels': [
                {'volume': 0.8, 'pan': 0.0, 'mute': False, 'solo': False},
                {'volume': 0.8, 'pan': 0.0, 'mute': False, 'solo': False},
                {'volume': 0.8, 'pan': 0.0, 'mute': False, 'solo': False},
                {'volume': 0.8, 'pan': 0.0, 'mute': False, 'solo': False},
            ],
        },
        'pads': {
            'samples': [None] * 8,
            'volumes': [1.0] * 8,
        },
        'window': {
            'x': None,
            'y': None,
            'width': 1280,
            'height': 720,
        },
    }
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._config: Dict[str, Any] = {}
        self._config_path = get_config_path()
        self._lock = threading.Lock()
        
        # Debounce timer for saving
        self._save_timer = QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._do_save)
        self._debounce_ms = 500
        
        # Load initial config
        self.load()
    
    def load(self) -> None:
        """Load configuration from disk."""
        with self._lock:
            if self._config_path.exists():
                try:
                    with open(self._config_path, 'r', encoding='utf-8') as f:
                        loaded = json.load(f)
                    # Merge with defaults to ensure all keys exist
                    self._config = self._deep_merge(self.DEFAULT_CONFIG, loaded)
                except (json.JSONDecodeError, IOError) as e:
                    print(f"Warning: Could not load config: {e}")
                    self._config = self._deep_copy(self.DEFAULT_CONFIG)
            else:
                self._config = self._deep_copy(self.DEFAULT_CONFIG)
        
        self.config_changed.emit(self._config)
    
    def get(self, *keys: str, default: Any = None) -> Any:
        """Get a nested configuration value using dot notation keys."""
        with self._lock:
            value = self._config
            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return default
            return value
    
    def set(self, value: Any, *keys: str, trigger_save: bool = True) -> None:
        """Set a nested configuration value and optionally trigger debounced save."""
        with self._lock:
            config = self._config
            for key in keys[:-1]:
                if key not in config:
                    config[key] = {}
                config = config[key]
            config[keys[-1]] = value
        
        self.config_changed.emit(self._config)
        if trigger_save:
            self.schedule_save()
    
    def schedule_save(self) -> None:
        """Schedule a save operation with debounce."""
        self._save_timer.start(self._debounce_ms)
    
    def save_now(self) -> None:
        """Force immediate save without debounce."""
        self._save_timer.stop()
        self._do_save()
    
    def _do_save(self) -> None:
        """Perform the actual save operation."""
        with self._lock:
            try:
                self._config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._config_path, 'w', encoding='utf-8') as f:
                    json.dump(self._config, f, indent=2)
                self.config_saved.emit()
            except IOError as e:
                print(f"Error saving config: {e}")
    
    def reset_to_defaults(self) -> None:
        """Reset configuration to default values."""
        with self._lock:
            self._config = self._deep_copy(self.DEFAULT_CONFIG)
        self.config_changed.emit(self._config)
        self.save_now()
    
    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Deep merge two dictionaries."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigManager._deep_merge(result[key], value)
            else:
                result[key] = value
        return result
    
    @staticmethod
    def _deep_copy(obj: Any) -> Any:
        """Create a deep copy of a nested structure."""
        if isinstance(obj, dict):
            return {k: ConfigManager._deep_copy(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [ConfigManager._deep_copy(item) for item in obj]
        else:
            return obj
