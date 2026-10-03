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
