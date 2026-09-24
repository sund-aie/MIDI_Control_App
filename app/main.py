"""
Panda MINI Soundboard — application entry point.

    python -m app.main
"""
import logging
import signal
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from app import paths


def setup_logging() -> None:
    handlers = []
    try:
        handlers.append(RotatingFileHandler(paths.logs_dir() / "app.log", maxBytes=1_000_000,
                                            backupCount=2, encoding="utf-8"))
    except OSError:
        pass
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> int:
    setup_logging()
    # Let the audio callback threads grab the GIL quickly while the GUI is busy.
    sys.setswitchinterval(0.002)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName("Panda MINI Soundboard")
    app.setOrganizationName("PandaMINI")

    # Imported after QApplication exists (widgets and the engine are QObjects).
    from app.audio.engine import AudioEngine
    from app.config import Config
    from app.gui import theme
    from app.gui.main_window import MainWindow
    from app.midi.listener import MidiListener

    theme.apply(app)
    app.setWindowIcon(theme.app_icon())

    config = Config()
    engine = AudioEngine()
    midi = MidiListener(engine)
    window = MainWindow(config, engine, midi)
    window.show()
    QTimer.singleShot(0, window.start)

    app.aboutToQuit.connect(window.shutdown)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QTimer()           # lets Python notice Ctrl+C while Qt runs
    keepalive.timeout.connect(lambda: None)
    keepalive.start(300)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
