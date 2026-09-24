import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PANDAMINI_DATA_DIR"] = tempfile.mkdtemp(prefix="pandamini-test-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import soundfile as sf  # noqa: E402


@pytest.fixture
def wav(tmp_path):
    """Write a test tone and return its path. make(seconds, rate, channels, name)."""
    def make(seconds=0.5, rate=48000, channels=1, name="tone.wav", amp=0.5):
        n = int(seconds * rate)
        t = np.arange(n) / rate
        tone = (amp * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        data = tone if channels == 1 else np.stack([tone] * channels, axis=1)
        path = tmp_path / name
        sf.write(str(path), data, rate)
        return path
    return make
