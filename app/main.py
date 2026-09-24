"""
Panda MINI Soundboard — application entry point.

    python -m app.main
"""
import faulthandler
import logging
import signal
import sys
import threading
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QLockFile, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from app import paths

log = logging.getLogger("app")
_crash_file = None


def setup_logging() -> None:
    """app.log in the user data folder; uncaught errors (any thread) and hard crashes land there too."""
    global _crash_file
    handlers = []
    try:
        handlers.append(RotatingFileHandler(paths.logs_dir() / "app.log", maxBytes=1_000_000,
                                            backupCount=2, encoding="utf-8", delay=True))
    except OSError:
        pass
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    sys.excepthook = lambda t, v, tb: logging.getLogger("crash").critical("Unhandled error", exc_info=(t, v, tb))
    threading.excepthook = lambda a: logging.getLogger("crash").critical(
        "Unhandled error in thread %s", a.thread.name if a.thread else "?",
        exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    try:
        _crash_file = open(paths.logs_dir() / "crash.log", "a", encoding="utf-8")
        faulthandler.enable(_crash_file)
    except (OSError, RuntimeError):
        pass


def _set_windows_app_id() -> None:
    """Own taskbar button and icon instead of being grouped under python.exe."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PandaMINI.Soundboard")
        except Exception:
            pass


def main() -> int:
    setup_logging()
    _set_windows_app_id()
    # Let the audio callback threads grab the GIL quickly while the GUI is busy.
    sys.setswitchinterval(0.002)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName("Panda MINI Soundboard")
    app.setOrganizationName("PandaMINI")

    # Imported after QApplication exists (widgets and the engine are QObjects).
    from app.gui import theme
    theme.apply(app)
    app.setWindowIcon(theme.app_icon())

    # One copy at a time: a second one would fight over the controller and the settings file.
    lock = QLockFile(str(paths.user_data_dir() / "app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "Panda MINI Soundboard",
                                "Panda MINI Soundboard is already running.\n"
                                "Look for its window on the taskbar.")
        return 0

    try:
        from app.audio.engine import AudioEngine
        from app.config import Config
        from app.gui.main_window import MainWindow
        from app.midi.listener import MidiListener

        config = Config()
        engine = AudioEngine()
        midi = MidiListener(engine)
        window = MainWindow(config, engine, midi)
    except Exception:
        log.exception("Startup failed")
        QMessageBox.critical(None, "Panda MINI Soundboard",
                             "The app couldn't start. Details are in:\n" + str(paths.logs_dir() / "app.log"))
        return 1

    window.show()
    QTimer.singleShot(0, window.start)

    app.aboutToQuit.connect(window.shutdown)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QTimer()           # lets Python notice Ctrl+C while Qt runs
    keepalive.timeout.connect(lambda: None)
    keepalive.start(300)

    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
