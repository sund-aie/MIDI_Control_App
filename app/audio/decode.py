"""
Turn any sound or video file into float32 stereo frames.

soundfile (libsndfile) handles WAV/FLAC/OGG/MP3/AIFF quickly; anything else
(M4A, AAC, WMA, OPUS, MP4/MOV/MKV/WEBM video, ...) goes through PyAV/FFmpeg.
"""
import logging
import os
import shutil
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

log = logging.getLogger(__name__)

MAX_SECONDS = 5 * 60           # longest sound a pad keeps (RAM guard)
MAX_COPY_BYTES = 200 * 1024 ** 2  # bigger files are used in place, not copied
PEAK_TARGET = 0.9              # sounds are normalised towards this peak ...
MAX_GAIN = 8.0                 # ... but never boosted more than +18 dB (hiss stays hiss)
SILENCE_PEAK = 1e-3            # quieter than -60 dBFS counts as "no usable sound"

FILE_FILTER = (
    "Sound or video files (*.wav *.mp3 *.ogg *.oga *.opus *.flac *.m4a *.m4b *.m4r *.aac *.wma "
    "*.aif *.aiff *.aifc *.caf *.amr *.au *.snd *.mp2 *.ac3 *.eac3 *.dts *.wv *.ape *.mka "
    "*.mp4 *.m4v *.mov *.mkv *.webm *.avi *.wmv *.asf *.flv *.3gp *.mpg *.mpeg *.ts *.mts "
    "*.m2ts *.ogv *.vob);;"
    "All files (*)"
)


class DecodeError(Exception):
    """The file could not be turned into sound. The message is user-facing."""


def decode_file(path) -> Tuple[np.ndarray, int]:
    """Return (frames, samplerate): frames is float32, shape (n, 2), peak-normalised."""
    path = Path(path)
    if not path.is_file():
        raise DecodeError("The file doesn't exist any more.")

    try:
        data, rate = _decode_soundfile(path)
    except Exception as sf_error:
        log.info("soundfile could not read %s (%s); trying FFmpeg", path.name, sf_error)
        try:
            data, rate = _decode_av(path)
        except DecodeError:
            raise
        except ImportError:
            raise DecodeError("This file type needs FFmpeg support (pip install av).")
        except Exception as av_error:
            log.warning("FFmpeg could not read %s: %s", path.name, av_error)
            raise DecodeError("This file has no playable sound in it.") from av_error

    return _finish(data, rate)


def _decode_soundfile(path: Path) -> Tuple[np.ndarray, int]:
    import soundfile as sf

    with sf.SoundFile(str(path)) as f:
        rate = int(f.samplerate)
        limit = MAX_SECONDS * rate
        frames = min(f.frames, limit) if f.frames > 0 else limit
        data = f.read(frames, dtype="float32", always_2d=True)
    return data, rate


def _decode_av(path: Path) -> Tuple[np.ndarray, int]:
    import av

    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise DecodeError("This file has no sound in it.")
        stream = container.streams.audio[0]
        rate = int(stream.codec_context.sample_rate or stream.rate or 48000)
        # packed float stereo: to_ndarray() is interleaved L R L R ...
        resampler = av.AudioResampler(format="flt", layout="stereo", rate=rate)
        limit = MAX_SECONDS * rate * 2
        chunks, total = [], 0
        for frame in container.decode(stream):
            frame.pts = None
            for out in _frames(resampler.resample(frame)):
                chunk = out.to_ndarray().reshape(-1)
                chunks.append(chunk)
                total += chunk.shape[0]
            if total >= limit:
                break
        try:
            for out in _frames(resampler.resample(None)):
                chunks.append(out.to_ndarray().reshape(-1))
        except Exception:
            pass
    if not chunks:
        raise DecodeError("This file has no sound in it.")
    data = np.concatenate(chunks)[:limit]
    return data[:data.shape[0] // 2 * 2].reshape(-1, 2), rate


def _frames(result):
    if result is None:
        return []
    return result if isinstance(result, list) else [result]


def _finish(data: np.ndarray, rate: int) -> Tuple[np.ndarray, int]:
    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 1:
        data = data[:, None]
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = _downmix(data)
    data = np.ascontiguousarray(data)
    np.nan_to_num(data, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    if data.shape[0] == 0 or rate <= 0:
        raise DecodeError("This file has no sound in it.")
    peak = float(np.max(np.abs(data)))
    if peak < SILENCE_PEAK:
        raise DecodeError("This file is silent (or nearly silent).")
    data *= min(PEAK_TARGET / peak, MAX_GAIN)
    return data, int(rate)


def _downmix(data: np.ndarray) -> np.ndarray:
    """Surround to stereo. 5.1/7.1 (L R C LFE Ls Rs [Lb Rb]) keep the centre (dialogue)."""
    ch = data.shape[1]
    if ch in (6, 8):
        c = 0.707 * data[:, 2]
        left = data[:, 0] + c + 0.707 * data[:, 4:ch:2].sum(axis=1)
        right = data[:, 1] + c + 0.707 * data[:, 5:ch:2].sum(axis=1)
    else:
        rest = data[:, 2:].mean(axis=1)
        left, right = data[:, 0] + 0.707 * rest, data[:, 1] + 0.707 * rest
    return np.stack([left, right], axis=1)


def resample(data: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Convert (n, 2) float32 frames between sample rates."""
    if src_rate == dst_rate or data.shape[0] == 0:
        return data
    try:
        import soxr
        out = soxr.resample(data, src_rate, dst_rate, quality="HQ")
    except ImportError:
        n_out = max(1, int(round(data.shape[0] * dst_rate / src_rate)))
        x_old = np.arange(data.shape[0], dtype=np.float64)
        x_new = np.linspace(0, data.shape[0] - 1, n_out)
        out = np.stack([np.interp(x_new, x_old, data[:, c]) for c in range(data.shape[1])], axis=1)
    return np.ascontiguousarray(out, dtype=np.float32)


def import_to_library(src, library: Path, data: Optional[np.ndarray] = None, rate: int = 0) -> Path:
    """Keep a copy of a pad's sound in the app's own folder, so moving/deleting the original is harmless.

    Normal files are copied as they are. Very big files (long videos) are stored as a FLAC of the
    decoded sound instead, which is all the pad uses.
    """
    src = Path(src)
    try:
        if src.resolve().parent == library.resolve():
            return src
        size = src.stat().st_size
        if size > MAX_COPY_BYTES:
            if data is None or not rate:
                return src
            return _save_flac(library, src.stem, data, rate)
        target = library / src.name
        n = 2
        while target.exists():
            if target.stat().st_size == size and _same_bytes(target, src):
                return target
            target = library / f"{src.stem} ({n}){src.suffix}"
            n += 1
        part = target.with_name(target.name + ".part")    # a killed copy never looks finished
        shutil.copy2(src, part)
        os.replace(part, target)
        return target
    except OSError as e:
        log.warning("Could not copy %s into the sound library: %s", src, e)
        return src


def _save_flac(library: Path, stem: str, data: np.ndarray, rate: int) -> Path:
    import soundfile as sf

    target = library / f"{stem}.flac"
    n = 2
    while target.exists():
        target = library / f"{stem} ({n}).flac"
        n += 1
    part = target.with_name(target.name + ".part")
    sf.write(str(part), np.clip(data, -1.0, 1.0), rate, format="FLAC", subtype="PCM_24")
    os.replace(part, target)
    return target


def clean_library(library: Path) -> None:
    """Remove half-written copies left by a crash or a kill during import."""
    for leftover in library.glob("*.part"):
        try:
            leftover.unlink()
        except OSError:
            pass


def _same_bytes(a: Path, b: Path, chunk: int = 1 << 20) -> bool:
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            x, y = fa.read(chunk), fb.read(chunk)
            if x != y:
                return False
            if not x:
                return True
