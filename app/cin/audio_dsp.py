"""Pure NumPy audio helpers for the Phase C mix (spec §8.3). No I/O.

Envelope: SPEECH_DB under speech windows, GAP_DB in gaps >= MIN_GAP and over the final TAIL s.
Word timings are known in advance, so the ATTACK ramp ends exactly at a speech onset (look-ahead)
and the RELEASE ramp starts at the speech end. The tail is a gap whose release ends at D - TAIL."""
from __future__ import annotations

import numpy as np

SR = 48000
SPEECH_DB = -22.0
GAP_DB = -14.0
MIN_GAP = 0.5
TAIL = 1.0
ATTACK = 0.150
RELEASE = 0.300
FADE_IN = 0.3
FADE_OUT = 1.5
LOOP_XFADE = 1.0
CONTROL_RATE = 1000        # the envelope is computed at 1 kHz, then interpolated to SR


def db_to_gain(db):
    return np.power(10.0, np.asarray(db, dtype=np.float64) / 20.0)


def rms_db(x) -> float:
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return float("-inf")
    r = float(np.sqrt(np.mean(np.square(x))))
    return float(20.0 * np.log10(r)) if r > 0 else float("-inf")


def speech_windows(tokens, duration: float, min_gap: float = MIN_GAP) -> list:
    """Merge (t0, t1) word timings into speech windows; silences shorter than min_gap count as speech."""
    spans = sorted((max(0.0, float(a)), min(float(duration), float(b))) for a, b in tokens)
    out = []
    for a, b in spans:
        if b <= a:
            continue
        if out and a - out[-1][1] < min_gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [[round(a, 4), round(b, 4)] for a, b in out]


def duck_curve_db(windows, duration: float, rate: int = CONTROL_RATE) -> np.ndarray:
    """Music gain in dB sampled at `rate` Hz, with linear ATTACK/RELEASE ramps (slew-limited)."""
    n = max(1, int(round(duration * rate)))
    t = np.arange(n) / rate
    tail_start = max(0.0, duration - TAIL - RELEASE)   # release finishes exactly at duration - TAIL
    ducked = np.zeros(n, dtype=bool)
    for a, b in windows:
        b = min(b, tail_start)
        if b <= a:
            continue
        ducked |= (t >= a - ATTACK) & (t < b)
    target = np.where(ducked, SPEECH_DB, GAP_DB)
    down = (GAP_DB - SPEECH_DB) / (ATTACK * rate)      # dB per tick
    up = (GAP_DB - SPEECH_DB) / (RELEASE * rate)
    out = np.empty(n)
    cur = target[0]
    for i in range(n):
        tgt = target[i]
        if tgt < cur:
            cur = max(tgt, cur - down)
        elif tgt > cur:
            cur = min(tgt, cur + up)
        out[i] = cur
    return out


def fade_gain(n: int, sr: int = SR, fade_in: float = FADE_IN, fade_out: float = FADE_OUT) -> np.ndarray:
    g = np.ones(n)
    fi = min(n, int(round(fade_in * sr)))
    fo = min(n, int(round(fade_out * sr)))
    if fi:
        g[:fi] *= np.linspace(0.0, 1.0, fi, endpoint=False)
    if fo:
        g[n - fo:] *= np.linspace(1.0, 0.0, fo)
    return g


def music_gain(windows, duration: float, sr: int = SR) -> np.ndarray:
    """Per-sample linear gain for the music bed: duck curve x fades. Length = round(duration * sr)."""
    n = int(round(duration * sr))
    curve = duck_curve_db(windows, duration)
    tc = np.arange(len(curve)) / CONTROL_RATE
    ts = np.arange(n) / sr
    return db_to_gain(np.interp(ts, tc, curve)) * fade_gain(n, sr)


def loop_to_length(x: np.ndarray, n: int, sr: int = SR, xfade: float = LOOP_XFADE) -> np.ndarray:
    """Repeat x (frames x channels) to exactly n frames with equal-power (sin/cos) crossfades of
    `xfade` seconds; the crossfade shrinks to a third of the track for very short tracks."""
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    if len(x) == 0:
        raise ValueError("empty track")
    if len(x) >= n:
        return x[:n].copy()
    xf = int(min(xfade * sr, len(x) // 3))
    if xf <= 0:
        return np.tile(x, (int(np.ceil(n / len(x))), 1))[:n]
    theta = np.linspace(0.0, np.pi / 2, xf, endpoint=False, dtype=np.float32)[:, None]
    fade_in, fade_out = np.sin(theta), np.cos(theta)
    out = np.zeros((n + len(x), x.shape[1]), dtype=np.float32)
    out[:len(x)] = x
    pos = len(x)                                   # end of the copy written last
    while pos < n:
        start = pos - xf
        out[start:pos] *= fade_out
        seg = x.copy()
        seg[:xf] *= fade_in
        out[start:start + len(x)] += seg
        pos = start + len(x)
    return out[:n]
