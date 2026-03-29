"""Audio analysis for cinematic editing — energy envelope, emphasis, pauses."""

import logging
import numpy as np

logger = logging.getLogger(__name__)


def compute_energy_envelope(audio: np.ndarray, sr: int, hop_size: int = 0) -> list[float]:
    if hop_size <= 0:
        hop_size = sr // 10
    envelope = []
    for start in range(0, len(audio), hop_size):
        chunk = audio[start:start + hop_size]
        rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
        envelope.append(rms)
    peak = max(envelope) if envelope else 1.0
    if peak > 0:
        envelope = [e / peak for e in envelope]
    return envelope


def find_emphasis_points(envelope: list[float], times: list[float],
                         threshold: float = 0.7) -> list[float]:
    peaks = []
    for i in range(1, len(envelope) - 1):
        if (envelope[i] > threshold and
                envelope[i] >= envelope[i - 1] and
                envelope[i] >= envelope[i + 1]):
            peaks.append(times[i])
    return peaks


def detect_pauses(envelope: list[float], times: list[float],
                  silence_threshold: float = 0.05,
                  min_duration: float = 0.2) -> list[dict]:
    pauses = []
    in_silence = False
    silence_start = 0.0
    for i, energy in enumerate(envelope):
        t = times[i] if i < len(times) else i * 0.1
        if energy < silence_threshold:
            if not in_silence:
                silence_start = t
                in_silence = True
        else:
            if in_silence:
                dur = t - silence_start
                if dur >= min_duration:
                    pauses.append({"start": silence_start, "end": t, "duration": dur})
                in_silence = False
    return pauses


def analyze_audio(audio_path: str, hop_ms: int = 50) -> dict:
    from moviepy import AudioFileClip
    clip = AudioFileClip(audio_path)
    sr = clip.fps or 44100
    duration = clip.duration
    audio_arr = clip.to_soundarray()
    if audio_arr.ndim > 1:
        audio_arr = audio_arr.mean(axis=1)
    audio_arr = audio_arr.astype(np.float32)
    hop_size = int(sr * hop_ms / 1000)
    envelope = compute_energy_envelope(audio_arr, sr, hop_size)
    times = [i * hop_ms / 1000 for i in range(len(envelope))]
    emphasis = find_emphasis_points(envelope, times)
    pauses = detect_pauses(envelope, times)
    logger.info("Audio analysis: %.1fs, %d emphasis points, %d pauses",
                duration, len(emphasis), len(pauses))
    clip.close()
    return {
        "energy_envelope": envelope,
        "times": times,
        "emphasis_points": emphasis,
        "pauses": pauses,
        "duration": duration,
        "sample_rate": sr,
    }
