"""Phase C mix (spec §8.3): voice polish, ducking depth, loop, SFX, 48 kHz, exact length."""
import wave

import numpy as np
import pytest

from app.cin.audio_io import AudioDecodeError, decode_audio, write_wav
from app.cin.mix import mix_tracks
from tests.conftest import make_tone, make_tone_wav

SR = 48000
WINDOWS = [[0.2, 2.0], [3.0, 5.0], [5.8, 7.2]]   # gap 2.0-3.0 (>= 0.5 s)


def read_wav(path):
    with wave.open(str(path)) as w:
        assert w.getframerate() == 48000 and w.getsampwidth() == 2 and w.getnchannels() == 2
        frames = w.getnframes()
        x = np.frombuffer(w.readframes(frames), "<i2").reshape(-1, 2) / 32767.0
    return x, frames


def band_db(x, freq, t0, t1):
    """Energy (dB, relative) in a +-30 Hz band; compare only equal-length windows."""
    seg = x[int(t0 * SR):int(t1 * SR), 0]
    spec = np.fft.rfft(seg * np.hanning(len(seg)))
    f = np.fft.rfftfreq(len(seg), 1 / SR)
    band = (f > freq - 30) & (f < freq + 30)
    return 10 * np.log10(np.sum(np.abs(spec[band]) ** 2) + 1e-20)


def test_decode_rejects_corrupt_and_respects_max_seconds(tmp_path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not audio" * 200)
    with pytest.raises(AudioDecodeError):
        decode_audio(bad)
    tone = make_tone(tmp_path / "t.wav", 4.0)
    assert decode_audio(tone, max_seconds=1.0).shape == (SR, 2)
    assert decode_audio(tone, channels=1).shape == (4 * SR, 1)


def test_write_wav_is_s16_48k_exact_frames(tmp_path):
    write_wav(tmp_path / "o.wav", np.zeros((12345, 2)))
    _, frames = read_wav(tmp_path / "o.wav")
    assert frames == 12345


def test_ducking_depth_and_format(tmp_path):
    """Music is a 1 kHz tone LONGER than the video: a looped tone would add the expected +3 dB
    equal-power bump on correlated content and blur the depth measurement."""
    nar = make_tone_wav(tmp_path / "n.wav", 8.0, 220, 0.3, WINDOWS)
    mus = make_tone_wav(tmp_path / "m.wav", 12.0, 1000, 0.5)
    info = mix_tracks(nar, tmp_path / "mix.wav", 8.0, music_path=mus, duck_windows=WINDOWS)
    x, frames = read_wav(tmp_path / "mix.wav")
    assert frames == 8 * SR
    voice = band_db(x, 220, 3.5, 4.5)
    assert band_db(x, 1000, 3.5, 4.5) - voice == pytest.approx(-22.0, abs=2.0)          # under speech
    assert band_db(x, 1000, 2.35, 2.85) - band_db(x, 220, 3.5, 4.0) == pytest.approx(-14.0, abs=2.0)  # gap
    assert band_db(x, 1000, 7.0, 7.4) - band_db(x, 220, 3.5, 3.9) < -14.0               # fading out
    assert info["music"] == mus.as_posix() and info["sfx"] == 0


def test_continuous_speech_keeps_music_at_minus_22(tmp_path):
    nar = make_tone_wav(tmp_path / "n.wav", 8.0, 220, 0.3)
    mus = make_tone_wav(tmp_path / "m.wav", 12.0, 1000, 0.5)
    mix_tracks(nar, tmp_path / "mix.wav", 8.0, music_path=mus, duck_windows=[[0.0, 8.0]])
    x, _ = read_wav(tmp_path / "mix.wav")
    for t0 in (1.0, 3.0, 5.0, 6.0):
        assert band_db(x, 1000, t0, t0 + 0.5) - band_db(x, 220, t0, t0 + 0.5) == pytest.approx(-22.0, abs=2.0)


def test_short_music_is_looped_to_full_length(tmp_path):
    rng = np.random.default_rng(3)
    write_wav(tmp_path / "m.wav", (rng.standard_normal((4 * SR, 2)) * 0.1))
    nar = make_tone_wav(tmp_path / "n.wav", 10.0, 220, 0.3, [[0.5, 3.0]])
    mix_tracks(nar, tmp_path / "mix.wav", 10.0, music_path=tmp_path / "m.wav", duck_windows=[[0.5, 3.0]])
    x, frames = read_wav(tmp_path / "mix.wav")
    assert frames == 10 * SR
    assert np.sqrt(np.mean(x[int(6 * SR):int(8 * SR)] ** 2)) > 1e-3                    # music after 4 s


def test_sfx_longer_than_video_is_truncated(tmp_path):
    nar = make_tone_wav(tmp_path / "n.wav", 8.0, 220, 0.3, [[0.0, 3.0]])
    riser = make_tone_wav(tmp_path / "riser_long.wav", 20.0, 3000, 0.5)
    ev = [{"t": 2.0, "kind": "riser", "file": "x", "gain_db": -12.0, "path": riser}]
    info = mix_tracks(nar, tmp_path / "mix.wav", 8.0, duck_windows=[[0.0, 3.0]], sfx=ev)
    x, frames = read_wav(tmp_path / "mix.wav")
    assert frames == 8 * SR and info["sfx"] == 1
    assert band_db(x, 3000, 1.0, 1.9) < band_db(x, 3000, 7.0, 7.9) - 30                 # starts at 2.0, runs to the end


def test_sfx_offset_and_gain(tmp_path):
    nar = make_tone_wav(tmp_path / "n.wav", 6.0, 220, 0.3, [[0.0, 6.0]])
    hit = make_tone_wav(tmp_path / "impact.wav", 2.0, 2000, 0.5, [[0.0, 1.0]])           # 1 s on, 1 s silent
    ev = [{"t": 0.0, "kind": "impact", "file": "a", "gain_db": -6.0, "path": hit, "offset": 1.0}]
    mix_tracks(nar, tmp_path / "mix.wav", 6.0, duck_windows=[[0.0, 6.0]], sfx=ev)
    x, _ = read_wav(tmp_path / "mix.wav")
    assert band_db(x, 2000, 0.1, 0.9) < band_db(x, 220, 0.1, 0.9) - 30                  # offset skipped the tone
    ev[0].pop("offset")
    mix_tracks(nar, tmp_path / "mix2.wav", 6.0, duck_windows=[[0.0, 6.0]], sfx=ev)
    x2, _ = read_wav(tmp_path / "mix2.wav")
    # RMS-normalised to the voice over the whole 2 s file, then -6 dB: the 1 s burst is ~ -3 dB rel. voice
    assert band_db(x2, 2000, 0.1, 0.9) - band_db(x2, 220, 0.1, 0.9) == pytest.approx(-3.0, abs=2.0)


def test_corrupt_music_reports_error_and_still_mixes_voice(tmp_path):
    nar = make_tone_wav(tmp_path / "n.wav", 4.0, 220, 0.3, [[0.0, 4.0]])
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"\x00garbage" * 500)
    bad_sfx = tmp_path / "whoosh_bad.mp3"
    bad_sfx.write_bytes(b"junk" * 100)
    info = mix_tracks(nar, tmp_path / "mix.wav", 4.0, music_path=bad, duck_windows=[[0.0, 4.0]],
                      sfx=[{"t": 1.0, "kind": "whoosh", "file": "w", "gain_db": -10.0, "path": bad_sfx}])
    assert info["music"] is None and info["music_error"]
    assert info["sfx"] == 0 and info["sfx_errors"][0]["file"] == bad_sfx.as_posix()
    x, frames = read_wav(tmp_path / "mix.wav")
    assert frames == 4 * SR and np.max(np.abs(x)) > 0.05


def test_silent_voice_uses_fallback_reference(tmp_path):
    nar = make_tone_wav(tmp_path / "n.wav", 3.0, 220, 0.0)
    mus = make_tone_wav(tmp_path / "m.wav", 5.0, 1000, 0.5)
    info = mix_tracks(nar, tmp_path / "mix.wav", 3.0, music_path=mus, duck_windows=[])
    assert info["voice_ref_db"] == -20.0
    x, _ = read_wav(tmp_path / "mix.wav")
    assert np.max(np.abs(x)) > 0.01


def test_peak_guard_and_missing_narration(tmp_path):
    nar = make_tone_wav(tmp_path / "n.wav", 3.0, 220, 0.99, [[0.0, 3.0]])
    hit = make_tone_wav(tmp_path / "impact.wav", 3.0, 220, 0.99)
    mix_tracks(nar, tmp_path / "mix.wav", 3.0, duck_windows=[[0.0, 3.0]],
               sfx=[{"t": 0.0, "kind": "impact", "file": "i", "gain_db": 6.0, "path": hit}])
    x, _ = read_wav(tmp_path / "mix.wav")
    assert np.max(np.abs(x)) <= 0.8913 + 1e-3
    with pytest.raises(AudioDecodeError):
        mix_tracks(tmp_path / "nope.mp3", tmp_path / "m.wav", 3.0)
