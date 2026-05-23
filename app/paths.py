"""
PandaMINI Core Engine - Frozen-aware asset location paths
Handles development directories and bundled %APPDATA%\\PandaMINI assets
"""
import os
import sys
from pathlib import Path


def get_app_data_dir() -> Path:
    """Get the application data directory based on platform and frozen state."""
    if getattr(sys, 'frozen', False):
        # Running as bundled executable
        if sys.platform == 'win32':
            app_data = Path(os.environ.get('APPDATA', '')) / 'PandaMINI'
        elif sys.platform == 'darwin':
            app_data = Path.home() / 'Library' / 'Application Support' / 'PandaMINI'
        else:
            app_data = Path.home() / '.local' / 'share' / 'PandaMINI'
    else:
        # Running in development mode
        app_data = Path(__file__).parent.parent / 'assets'
    
    app_data.mkdir(parents=True, exist_ok=True)
    return app_data


def get_samples_dir() -> Path:
    """Get the samples directory for user-loaded audio files."""
    samples_dir = get_app_data_dir() / 'samples'
    samples_dir.mkdir(parents=True, exist_ok=True)
    return samples_dir


def get_config_path() -> Path:
    """Get the configuration file path."""
    return get_app_data_dir() / 'config.json'


def get_presets_dir() -> Path:
    """Get the presets directory for saved synth patches."""
    presets_dir = get_app_data_dir() / 'presets'
    presets_dir.mkdir(parents=True, exist_ok=True)
    return presets_dir


def get_logs_dir() -> Path:
    """Get the logs directory for application logs."""
    logs_dir = get_app_data_dir() / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def get_default_sample_path(sample_name: str) -> Path:
    """Get the default path for a sample file."""
    return get_samples_dir() / sample_name


def resource_path(relative_path: str) -> Path:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    if getattr(sys, 'frozen', False):
        base_path = Path(sys.executable).parent
    else:
        base_path = Path(__file__).parent.parent
    
    return base_path / relative_path
