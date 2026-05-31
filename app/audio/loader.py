"""
PandaMINI Core Engine - Sample Loader
Asynchronously loads audio files into float32 arrays using soundfile on background threads
"""
import numpy as np
import soundfile as sf
from pathlib import Path
from typing import Dict, Optional, Callable, Any
from PySide6.QtCore import QObject, Signal, QThread
import threading


class SampleLoader(QObject):
    """Thread-safe asynchronous sample loader."""
    
    sample_loaded = Signal(str, np.ndarray, int)  # path, data, sample_rate
    sample_load_failed = Signal(str, str)  # path, error_message
    
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._samples: Dict[str, np.ndarray] = {}
        self._sample_rates: Dict[str, int] = {}
        self._lock = threading.Lock()
        self._worker_thread: Optional[QThread] = None
    
    def load_sample(self, file_path: str, on_complete: Optional[Callable[[str, np.ndarray], None]] = None) -> None:
        """
        Load a sample asynchronously on a background thread.
        
        Args:
            file_path: Path to the audio file
            on_complete: Optional callback when loading completes
        """
        path = Path(file_path)
        if not path.exists():
            self.sample_load_failed.emit(str(path), "File not found")
            return
        
        # Create worker and thread for this load operation
        worker = _LoadWorker(str(path), on_complete)
        thread = QThread(self)
        worker.moveToThread(thread)
        
        # Connect signals
        worker.loaded.connect(self._on_sample_loaded)
        worker.failed.connect(self._on_sample_failed)
        
        # Start the thread
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        
        thread.start()
    
    def _on_sample_loaded(self, path: str, data: np.ndarray, sample_rate: int) -> None:
        """Handle successful sample load."""
        with self._lock:
            self._samples[path] = data
            self._sample_rates[path] = sample_rate
        self.sample_loaded.emit(path, data, sample_rate)
    
    def _on_sample_failed(self, path: str, error: str) -> None:
        """Handle failed sample load."""
        self.sample_load_failed.emit(path, error)
    
    def get_sample(self, path: str) -> Optional[np.ndarray]:
        """Get a loaded sample by path (thread-safe)."""
        with self._lock:
            return self._samples.get(path)
    
    def get_sample_rate(self, path: str) -> int:
        """Get the sample rate of a loaded sample."""
        with self._lock:
            return self._sample_rates.get(path, 48000)
    
    def has_sample(self, path: str) -> bool:
        """Check if a sample is loaded."""
        with self._lock:
            return path in self._samples
    
    def unload_sample(self, path: str) -> None:
        """Unload a sample from memory."""
        with self._lock:
            self._samples.pop(path, None)
            self._sample_rates.pop(path, None)
    
    def clear_all(self) -> None:
        """Clear all loaded samples."""
        with self._lock:
            self._samples.clear()
            self._sample_rates.clear()


class _LoadWorker(QObject):
    """Background worker for loading samples."""
    
    loaded = Signal(str, np.ndarray, int)
    failed = Signal(str, str)
    finished = Signal()
    
    def __init__(self, file_path: str, on_complete: Optional[Callable[[str, np.ndarray], None]] = None):
        super().__init__()
        self._file_path = file_path
        self._on_complete = on_complete
    
    def run(self) -> None:
        """Load the sample file."""
        try:
            # Load audio file as float32
            data, sample_rate = sf.read(self._file_path, dtype='float32')
            
            # Convert to mono if stereo
            if len(data.shape) > 1:
                data = data.mean(axis=1)
            
            # Normalize to prevent clipping
            max_val = np.max(np.abs(data))
            if max_val > 0:
                data = data / max_val * 0.9
            
            self.loaded.emit(self._file_path, data, sample_rate)
            
            if self._on_complete:
                self._on_complete(self._file_path, data)
                
        except Exception as e:
            self.failed.emit(self._file_path, str(e))
        finally:
            self.finished.emit()
