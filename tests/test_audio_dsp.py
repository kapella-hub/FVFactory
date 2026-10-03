"""Ducking envelope and looping (spec §8.3) — pure NumPy, no media."""
import numpy as np
import pytest

from app.cin.audio_dsp import (CONTROL_RATE, SR, duck_curve_db, fade_gain, loop_to_length, music_gain,
                               rms_db, speech_windows)

WINDOWS = [[0.2, 2.0], [3.0, 5.0], [5.8, 7.2]]


def at(curve, t):
    return curve[int(round(t * CONTROL_RATE))]


def test_speech_windows_merge_short_gaps_keep_long_ones():
    toks = [(0.2, 0.5), (0.6, 1.0), (1.2, 2.0),      # gaps 0.1, 0.2 -> one window
            (3.0, 3.4), (3.9, 5.0),                   # gap 0.5 exactly -> kept apart
            (7.0, 7.0), (8.5, 9.5)]                   # zero-length dropped; clipped to duration
    assert speech_windows(toks, 9.0) == [[0.2, 2.0], [3.0, 3.4], [3.9, 5.0], [8.5, 9.0]]
    assert speech_windows([], 5.0) == []


def test_duck_curve_levels():
    c = duck_curve_db(WINDOWS, 8.0)
    assert at(c, 0.0) == -14                 # 0.2 s of lead-in is not ducked yet ...
    assert at(c, 0.2) == -22                 # ... but the attack finishes at the onset
    assert at(c, 1.0) == -22
    assert -22 < at(c, 2.15) < -14           # releasing over 300 ms
    assert at(c, 2.31) == -14 and at(c, 2.5) == -14
    assert at(c, 2.80) == -14 and at(c, 3.0) == -22     # attack starts 150 ms before speech
    assert at(c, 7.5) == -14


def test_attack_and_release_slopes():
    c = duck_curve_db([[1.0, 2.0]], 5.0)
    assert at(c, 0.84) == -14 and at(c, 0.925) == pytest.approx(-18.0, abs=0.1)
    assert at(c, 2.15) == pytest.approx(-18.0, abs=0.1) and at(c, 2.3) == -14


def test_no_gaps_ducks_everything_but_the_tail():
    toks = [(i * 0.3, i * 0.3 + 0.29) for i in range(30)]       # continuous speech to 9.0 s
    w = speech_windows(toks, 9.0)
    assert w == [[0.0, 8.99]]
    c = duck_curve_db(w, 9.0)
    assert at(c, 0.0) == -22 and at(c, 4.0) == -22 and at(c, 7.69) == -22
    assert at(c, 8.0) == -14 and at(c, 8.99) == -14              # -14 reached exactly at D - 1.0
    assert np.all(np.diff(c[: int(7.7 * CONTROL_RATE)]) == 0)    # no pumping


def test_no_speech_is_all_gap_level():
    c = duck_curve_db([], 3.0)
    assert np.all(c == -14)


def test_fades_and_music_gain_length():
    g = fade_gain(SR * 4)
    assert g[0] == 0.0 and g[int(0.3 * SR)] == 1.0 and g[-1] == 0.0
    assert g[int(2.5 * SR)] == 1.0 and 0.0 < g[int(3.5 * SR)] < 1.0
    mg = music_gain(WINDOWS, 8.0)
    assert len(mg) == 8 * SR
    assert 20 * np.log10(mg[int(1.0 * SR)]) == pytest.approx(-22.0, abs=0.01)
    assert 20 * np.log10(mg[int(2.5 * SR)]) == pytest.approx(-14.0, abs=0.01)
    assert len(music_gain([], 0.01)) == 480


def test_loop_exact_length_and_starts_with_original():
    x = np.arange(SR * 3, dtype=np.float32).reshape(-1, 1) / (SR * 3)
    y = loop_to_length(x, SR * 10)
    assert y.shape == (SR * 10, 1) and y.dtype == np.float32
    assert np.array_equal(y[: SR * 2], x[: SR * 2])             # untouched before the first crossfade


def test_loop_crossfade_is_equal_power_on_uncorrelated_audio():
    """Noise, not a tone: equal-power fades keep power constant only for uncorrelated content
    (an in-phase sine would bump by up to +3 dB in the overlap, which is expected)."""
    rng = np.random.default_rng(1)
    x = (rng.standard_normal((3 * SR, 2)) * 0.1).astype(np.float32)
    y = loop_to_length(x, 10 * SR)
    body = rms_db(y[int(0.5 * SR):int(1.5 * SR)])
    for centre in (2.5, 4.5, 6.5, 8.5):                          # copy k starts at 2k s, overlaps 1 s
        seg = y[int((centre - 0.3) * SR):int((centre + 0.3) * SR)]
        assert abs(rms_db(seg) - body) < 1.5


def test_loop_very_short_track_does_not_crash():
    y = loop_to_length(np.ones((100, 2), np.float32), 1000)
    assert y.shape == (1000, 2)
    y1 = loop_to_length(np.ones(2, np.float32), 7)              # mono 1-D input, crossfade 0
    assert y1.shape == (7, 1)


def test_loop_longer_track_is_truncated_and_empty_rejected():
    x = np.ones((SR * 5, 2), np.float32)
    assert loop_to_length(x, SR).shape == (SR, 2)
    with pytest.raises(ValueError):
        loop_to_length(np.zeros((0, 2), np.float32), 10)


def test_rms_db():
    assert rms_db(np.zeros(10)) == float("-inf") and rms_db(np.zeros(0)) == float("-inf")
    assert rms_db(np.full(100, 0.5)) == pytest.approx(-6.02, abs=0.01)
