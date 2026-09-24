import numpy as np
import pytest

from app.audio.decode import DecodeError, PEAK_TARGET, decode_file, import_to_library, resample


def test_mono_wav_becomes_normalised_stereo(wav):
    data, rate = decode_file(wav(seconds=0.25, rate=44100, amp=0.2))
    assert rate == 44100
    assert data.dtype == np.float32 and data.shape == (11025, 2)
    assert np.allclose(data[:, 0], data[:, 1])
    assert abs(np.max(np.abs(data)) - PEAK_TARGET) < 1e-3


def test_surround_keeps_centre_dialogue(tmp_path):
    import soundfile as sf
    n = 4800
    data = np.zeros((n, 6), dtype=np.float32)
    data[:, 2] = 0.5 * np.sin(np.arange(n) / 5)                   # sound only in the centre channel
    sf.write(str(tmp_path / "51.wav"), data, 48000)
    out, _ = decode_file(tmp_path / "51.wav")
    assert out.shape[1] == 2 and np.allclose(out[:, 0], out[:, 1]) and np.max(np.abs(out)) > 0.5


def test_quiet_files_are_not_boosted_into_noise(wav):
    data, _ = decode_file(wav(amp=0.01, name="quiet.wav"))
    assert np.max(np.abs(data)) == pytest.approx(0.08, rel=0.01)  # +18 dB cap
    with pytest.raises(DecodeError):
        decode_file(wav(amp=0.0005, name="hiss.wav"))


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


def test_big_files_are_stored_as_flac_of_the_decoded_sound(tmp_path, wav, monkeypatch):
    import soundfile as sf
    monkeypatch.setattr("app.audio.decode.MAX_COPY_BYTES", 1000)
    library = tmp_path / "library"
    library.mkdir()
    src = wav(seconds=1, name="movie.wav")
    data, rate = decode_file(src)
    stored = import_to_library(src, library, data, rate)
    assert stored.parent == library and stored.suffix == ".flac"
    back, back_rate = sf.read(str(stored), dtype="float32")
    assert back_rate == rate and back.shape == data.shape


def test_half_written_copies_are_cleaned(tmp_path):
    from app.audio.decode import clean_library
    (tmp_path / "clip.mp4.pandamini-tmp").write_bytes(b"x")
    (tmp_path / "keep.wav").write_bytes(b"x")
    clean_library(tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["keep.wav"]


def _encode(av, path, codec, rate=44100, seconds=2.0, layout="mono", fmt=None):
    with av.open(str(path), "w", format=fmt) as out:
        stream = out.add_stream(codec, rate=rate)
        stream.layout = layout
        n = int(rate * seconds)
        t = np.arange(n) / rate
        ch = 1 if layout == "mono" else 2
        samples = np.tile((0.5 * np.sin(2 * np.pi * 330 * t)).astype(np.float32), (ch, 1))
        frame = av.AudioFrame.from_ndarray(samples, format="fltp", layout=layout)
        frame.sample_rate = rate
        for packet in stream.encode(frame):
            out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)


def test_joined_mp3s_are_decoded_in_full(tmp_path):
    av = pytest.importorskip("av")
    a, b = tmp_path / "a.mp3", tmp_path / "b.mp3"
    _encode(av, a, "mp3", seconds=1.0)
    _encode(av, b, "mp3", seconds=2.0)
    joined = tmp_path / "joined.mp3"
    joined.write_bytes(a.read_bytes() + b.read_bytes())          # "copy /b a.mp3+b.mp3"
    data, rate = decode_file(joined)
    assert data.shape[0] / rate > 2.8


def test_damaged_packets_are_skipped(tmp_path):
    av = pytest.importorskip("av")
    clip = tmp_path / "clip.ts"
    _encode(av, clip, "mp2", seconds=3.0, fmt="mpegts")
    raw = bytearray(clip.read_bytes())
    for k in range(len(raw) // 3, len(raw) // 3 + 2000):         # scribble over the middle
        raw[k] = 0xFF
    broken = tmp_path / "broken.ts"
    broken.write_bytes(bytes(raw))
    data, rate = decode_file(broken)
    assert data.shape[0] / rate > 1.5


def test_truncated_download_keeps_what_decodes(tmp_path):
    av = pytest.importorskip("av")
    clip = tmp_path / "full.mp3"
    _encode(av, clip, "mp3", seconds=4.0)
    part = tmp_path / "song.mp3.part"                            # an unfinished browser download
    part.write_bytes(clip.read_bytes()[: clip.stat().st_size * 2 // 3])
    data, rate = decode_file(part)
    assert 2.0 < data.shape[0] / rate < 3.5


def test_wav_with_unfinished_header_falls_back_to_ffmpeg(tmp_path, wav):
    pytest.importorskip("av")
    good = wav(seconds=1.0, name="good.wav")
    raw = bytearray(good.read_bytes())
    k = raw.find(b"data")
    raw[k + 4:k + 8] = b"\x00\x00\x00\x00"                       # recorder crashed before finishing
    bad = tmp_path / "crashed.wav"
    bad.write_bytes(bytes(raw))
    data, rate = decode_file(bad)
    assert data.shape[0] / rate > 0.5
