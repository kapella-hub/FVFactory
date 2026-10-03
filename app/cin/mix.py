"""Phase A audio mix (spec §8.3 placeholder): narration + the existing music and SFX code paths,
written as a 48 kHz WAV to sources/mix.wav. Phase C replaces this with the music library,
ducking and voice polish; loudness normalization happens later, in app.encoding.mux_final."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from app.config import settings
from app.encoding import EncodingError, find_ffmpeg

import logging

import numpy as np

from app.cin.audio_dsp import SR, db_to_gain, loop_to_length, music_gain, rms_db
from app.cin.audio_io import VOICE_POLISH, AudioDecodeError, decode_audio, write_wav

logger = logging.getLogger(__name__)

REF_DB = -20.0            # voice reference when the narration is silent
SILENCE_DB = -60.0
PEAK_CEILING = 0.8913     # -1 dBFS; loudnorm restores the level afterwards
MUSIC_DECODE_PAD = 5.0    # decode only what the video needs (+ margin) from long tracks


def _fit_duration(wav: Path, duration: float) -> None:
    """Pad with silence / trim so the WAV is exactly `duration` s (the mux has no -shortest)."""
    fixed = wav.with_name(wav.stem + ".fit.wav")
    cmd = [find_ffmpeg(), "-hide_banner", "-v", "error", "-y", "-i", str(wav),
           "-af", f"apad=whole_dur={duration:.6f},atrim=end={duration:.6f}",
           "-ar", "48000", "-c:a", "pcm_s16le", str(fixed)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise EncodingError(f"mix duration fit failed: {result.stderr[-1000:]}")
    os.replace(fixed, wav)


def mix_audio(narration, out_wav, duration: float, *, music_path: Optional[Path] = None,
              scene_starts=(), enable_sfx: bool = True) -> dict:
    """Returns {"music": posix path or None, "sfx": bool}. The WAV is exactly `duration` long."""
    from moviepy import AudioFileClip, CompositeAudioClip
    from app.sfx import SFXMixer
    from app.video_editor import VideoEditor

    voice = AudioFileClip(str(narration))
    tracks = [voice.with_volume_scaled(settings.voice_volume)]
    info = {"music": None, "sfx": False}
    try:
        if music_path:
            tracks.append(VideoEditor()._prepare_background_music(Path(music_path), duration))
            info["music"] = Path(music_path).as_posix()
        if enable_sfx:
            sfx = SFXMixer().build_sfx_track(scene_timestamps=list(scene_starts), total_duration=duration)
            if sfx is not None:
                tracks.append(sfx)
                info["sfx"] = True
        mixed = CompositeAudioClip(tracks).with_duration(duration)
        mixed.write_audiofile(str(out_wav), fps=48000, nbytes=2, codec="pcm_s16le", logger=None)
    finally:
        for clip in [voice] + tracks:
            try:
                clip.close()
            except Exception:  # noqa: BLE001
                pass
    _fit_duration(Path(out_wav), duration)
    return info


def _fit(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) >= n:
        return x[:n]
    return np.concatenate([x, np.zeros((n - len(x), x.shape[1]), dtype=x.dtype)])


def _speech_mask(windows, n: int) -> np.ndarray:
    mask = np.zeros(n, dtype=bool)
    for a, b in windows:
        mask[int(a * SR):int(b * SR)] = True
    return mask


def mix_tracks(narration, out_wav, duration: float, *, music_path: Optional[Path] = None,
               duck_windows=(), sfx=()) -> dict:
    """spec §8.3: polished voice + looped, ducked music + SFX -> 48 kHz s16 WAV of exactly `duration`.
    0 dB reference = polished voice RMS over duck_windows (REF_DB if silent). Music and SFX are
    RMS-normalised to it before their gains. Unreadable music/SFX are reported, never raised."""
    n = int(round(duration * SR))
    voice = _fit(decode_audio(narration, af=VOICE_POLISH), n)
    mask = _speech_mask(duck_windows, n)
    ref = rms_db(voice[mask]) if mask.any() else float("-inf")
    if not np.isfinite(ref) or ref < SILENCE_DB:
        ref = REF_DB
    mix = voice.astype(np.float32)
    info = {"music": None, "music_error": "", "sfx": 0, "sfx_errors": [], "voice_ref_db": round(float(ref), 2)}

    if music_path is not None:
        try:
            bed = loop_to_length(decode_audio(music_path, max_seconds=duration + MUSIC_DECODE_PAD), n)
            level = rms_db(bed)
            if not np.isfinite(level) or level < SILENCE_DB:
                raise AudioDecodeError(f"{Path(music_path).name}: silent track")
            gain = music_gain(duck_windows, duration) * db_to_gain(ref - level)
            mix += (bed * gain[:, None]).astype(np.float32)
            info["music"] = Path(music_path).as_posix()
        except AudioDecodeError as e:
            info["music_error"] = str(e)[:300]
            logger.warning("Music skipped in mix: %s", e)

    cache = {}
    for ev in sfx:
        path = Path(ev["path"])
        if path not in cache:
            try:
                cache[path] = decode_audio(path, max_seconds=duration + 60.0)
            except AudioDecodeError as e:
                info["sfx_errors"].append({"file": path.as_posix(), "reason": str(e)[:300]})
                logger.warning("SFX skipped in mix: %s", e)
                cache[path] = None
        clip = cache[path]
        if clip is None:
            continue
        clip = clip[int(round(float(ev.get("offset", 0.0)) * SR)):]
        level = rms_db(clip) if len(clip) else float("-inf")
        start = int(round(float(ev["t"]) * SR))
        if not np.isfinite(level) or level < SILENCE_DB or start >= n:
            continue
        end = min(n, start + len(clip))
        mix[start:end] += (clip[: end - start] * db_to_gain(ref - level + float(ev.get("gain_db", -6.0)))
                           ).astype(np.float32)
        info["sfx"] += 1

    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > PEAK_CEILING:
        mix *= PEAK_CEILING / peak
    write_wav(out_wav, mix)
    return info
