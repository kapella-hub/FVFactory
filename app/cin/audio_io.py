"""ffmpeg-backed decode to NumPy and stdlib WAV write for the Phase C mix (spec §8.3)."""
from __future__ import annotations

import os
import subprocess
import wave
from pathlib import Path
from typing import Optional

import numpy as np

from app.encoding import EncodingError, find_ffmpeg

SR = 48000
VOICE_POLISH = "highpass=f=80,acompressor=threshold=-18dB:ratio=3:attack=10:release=150"   # spec §8.3


class AudioDecodeError(Exception):
    pass


def decode_audio(path, sr: int = SR, channels: int = 2, af: Optional[str] = None,
                 max_seconds: Optional[float] = None) -> np.ndarray:
    """Decode any ffmpeg-readable file to float32 (frames, channels) at `sr`.
    Raises AudioDecodeError when ffmpeg fails or yields no samples (corrupt / non-audio files)."""
    name = Path(path).name
    try:
        cmd = [find_ffmpeg(), "-hide_banner", "-v", "error", "-nostdin", "-i", str(path)]
    except EncodingError as e:
        raise AudioDecodeError(str(e)) from e
    if max_seconds:
        cmd += ["-t", f"{max_seconds:.3f}"]
    if af:
        cmd += ["-af", af]
    cmd += ["-vn", "-ac", str(channels), "-ar", str(sr), "-f", "f32le", "-"]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AudioDecodeError(f"{name}: {e}") from e
    if res.returncode != 0:
        raise AudioDecodeError(f"{name}: {res.stderr.decode('utf-8', 'replace').strip()[-300:]}")
    data = np.frombuffer(res.stdout, dtype="<f4")
    frames = len(data) // channels
    if frames == 0:
        raise AudioDecodeError(f"{name}: no audio samples")
    return data[: frames * channels].reshape(frames, channels).copy()


def write_wav(path, x: np.ndarray, sr: int = SR) -> None:
    """16-bit PCM WAV (clipped to [-1, 1]); written to a temp file and renamed."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).round().astype("<i2")
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    os.replace(tmp, path)
