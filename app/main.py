"""
PandaMINI Core Engine - Application Bootstrapper
Handles clean teardowns and background thread joins on exit
"""
import sys
import signal
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QThread
from PySide6.QtGui import QFontDatabase

from app.audio.engine import AudioEngine
from app.midi.listener import MidiListener
from app.config import ConfigManager
from app.gui.main_window import MainWindow
from app.paths import get_logs_dir


class PandaMiniApp:
    """Main application class managing all components."""
    
    def __init__(self):
        self._app = QApplication(sys.argv)
        self._app.setApplicationName("PandaMINI Core Engine")
        self._app.setOrganizationName("V-Stack")
        
        # Load custom fonts if available
        self._load_fonts()
        
        # Initialize core components
        self._config_manager = ConfigManager()
        self._audio_engine = AudioEngine(config_manager=self._config_manager)
        self._midi_listener = MidiListener()
        
        # Create main window
        self._main_window = MainWindow(
            audio_engine=self._audio_engine,
            midi_listener=self._midi_listener,
            config_manager=self._config_manager
        )
        
        # Setup signal handlers for clean shutdown
        self._setup_signal_handlers()
        
        # Schedule startup tasks
        QTimer.singleShot(100, self._on_startup)
    
    def _load_fonts(self) -> None:
        """Load custom fonts if available."""
        # Try to load Geist and JetBrains Mono fonts
        font_paths = [
            "fonts/Geist-Regular.ttf",
            "fonts/Geist-Bold.ttf",
            "fonts/JetBrainsMono-Regular.ttf",
            "fonts/JetBrainsMono-Bold.ttf",
        ]
        
        for font_path in font_paths:
            try:
                from app.paths import resource_path
                full_path = resource_path(font_path)
                if full_path.exists():
                    QFontDatabase.addApplicationFont(str(full_path))
            except Exception as e:
                pass  # Fonts are optional
    
    def _setup_signal_handlers(self) -> None:
        """Setup OS signal handlers for clean shutdown."""
        def signal_handler(signum, frame):
            self.shutdown()
        
        # Handle SIGINT (Ctrl+C) and SIGTERM
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def _on_startup(self) -> None:
        """Tasks to run after UI is displayed."""
        # Show main window
        self._main_window.show()
        
        # Restore window position from config if available
        self._restore_window_position()
        
        # Start MIDI listener with configured device or auto-detect first device
        midi_device = self._config_manager.get('midi', 'input_device')
        available = self._midi_listener.get_available_devices()
        
        if not midi_device and available:
            # Auto-select the first available device (e.g. WORLDE)
            midi_device = available[0]
            self._config_manager.set(midi_device, 'midi', 'input_device', trigger_save=True)
            
        if midi_device:
            self._midi_listener.start_listening(midi_device)
        
        # Start audio streams with configured devices (None = system default)
        sampler_device = self._config_manager.get('audio', 'sampler_output')
        soundboard_device = self._config_manager.get('audio', 'soundboard_output')
        
        self._audio_engine.start_streams(
            sampler_device=sampler_device,
            soundboard_device=soundboard_device
        )
    
    def _restore_window_position(self) -> None:
        """Restore window position from saved config."""
        x = self._config_manager.get('window', 'x')
        y = self._config_manager.get('window', 'y')
        
        if x is not None and y is not None:
            self._main_window.move(int(x), int(y))
    
    def _save_window_position(self) -> None:
        """Save current window position to config."""
        pos = self._main_window.pos()
        self._config_manager.set(pos.x(), 'window', 'x', trigger_save=False)
        self._config_manager.set(pos.y(), 'window', 'y', trigger_save=False)
        self._config_manager.save_now()
    
    def run(self) -> int:
        """Run the application event loop."""
        # Setup timer to handle Python signals during Qt event loop
        timer = QTimer()
        timer.timeout.connect(lambda: None)
        timer.start(500)  # Check every 500ms
        
        return self._app.exec()
    
    def shutdown(self) -> None:
        """Clean shutdown of all components."""
        # Save window position
        self._save_window_position()
        
        # Stop audio engine
        if self._audio_engine:
            self._audio_engine.cleanup()
        
        # Stop MIDI listener
        if self._midi_listener:
            self._midi_listener.stop_listening()
        
        # Cleanup main window
        if self._main_window:
            self._main_window.cleanup()
        
        # Force save config
        if self._config_manager:
            self._config_manager.save_now()
        
        # Quit application
        self._app.quit()


def main() -> int:
    """Main entry point."""
    # Ensure logs directory exists
    try:
        get_logs_dir().mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    
    # Create and run application
    app = PandaMiniApp()
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
