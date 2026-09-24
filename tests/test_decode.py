import numpy as np
import pytest

from app.audio.decode import DecodeError, PEAK_TARGET, decode_file, import_to_library, resample


def test_mono_wav_becomes_normalised_stereo(wav):
    data, rate = decode_file(wav(seconds=0.25, rate=44100, amp=0.2))
    assert rate == 44100
    assert data.dtype == np.float32 and data.shape == (11025, 2)
    assert np.allclose(data[:, 0], data[:, 1])
    assert abs(np.max(np.abs(data)) - PEAK_TARGET) < 1e-3


def test_multichannel_keeps_front_pair(wav):
    data, _ = decode_file(wav(channels=6, name="surround.wav"))
    assert data.shape[1] == 2


def test_unicode_file_name(wav):
    data, _ = decode_file(wav(name="هذا اكبر كويحه بالمنطقه.wav"))
    assert data.shape[0] > 0


def test_m4a_goes_through_ffmpeg(tmp_path):
    av = pytest.importorskip("av")
    path = tmp_path / "clip.m4a"
    rate = 44100
    with av.open(str(path), "w") as out:
        stream = out.add_stream("aac", rate=rate)
        stream.layout = "mono"
        t = np.arange(rate) / rate
        samples = (0.5 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)[None, :]
        frame = av.AudioFrame.from_ndarray(samples, format="flt", layout="mono")
        frame.sample_rate = rate
        for packet in stream.encode(frame):
            out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    data, got_rate = decode_file(path)
    assert got_rate == rate
    assert data.shape[1] == 2 and data.shape[0] > rate * 0.8


def test_video_without_audio_is_rejected(tmp_path):
    av = pytest.importorskip("av")
    path = tmp_path / "silent_video.mp4"
    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=10)
        stream.width, stream.height, stream.pix_fmt = 32, 32, "yuv420p"
        for _ in range(3):
            frame = av.VideoFrame.from_ndarray(np.zeros((32, 32, 3), dtype=np.uint8), format="rgb24")
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    with pytest.raises(DecodeError):
        decode_file(path)


def test_garbage_missing_and_silent_files(tmp_path, wav):
    junk = tmp_path / "notes.txt"
    junk.write_text("definitely not audio")
    with pytest.raises(DecodeError):
        decode_file(junk)
    with pytest.raises(DecodeError):
        decode_file(tmp_path / "missing.wav")
    with pytest.raises(DecodeError):
        decode_file(wav(amp=0.0, name="silence.wav"))


def test_resample_length_and_type():
    data = np.zeros((44100, 2), dtype=np.float32)
    out = resample(data, 44100, 48000)
    assert out.dtype == np.float32 and abs(out.shape[0] - 48000) <= 2
    assert resample(data, 48000, 48000) is data


def test_import_to_library_copies_once(tmp_path, wav):
    library = tmp_path / "library"
    library.mkdir()
    src = wav(name="horn.wav")
    first = import_to_library(src, library)
    assert first.parent == library and first.read_bytes() == src.read_bytes()
    assert import_to_library(src, library) == first            # same content: reused
    assert import_to_library(first, library) == first          # already inside
    other = wav(name="horn.wav", amp=0.3)                      # same name, new content
    second = import_to_library(other, library)
    assert second != first and second.name == "horn (2).wav"
