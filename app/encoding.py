"""Upload-grade encode (spec §9.1): video-only x264 render settings, two-pass loudnorm, copy-mux.

probe_video / get_audio_loudness / is_platform_safe are ported from src/encoding.py
(src/ is the legacy pipeline and is not imported by app/).
"""
from __future__ import annotations

import json
import logging
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920
DEFAULT_FPS = 30
X264_PRESET = "slow"
# spec §9.1 step 1 (the preset is passed separately because MoviePy always adds -preset)
X264_PARAMS = ["-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p",
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
# Spec ceiling is -1 dBTP on the delivered file. AAC encoding overshoots the WAV peak by ~0.25 dB,
# so the filter targets -1.5 to land the measured post-AAC true peak at <= -1.0.
TRUE_PEAK_CEILING = -1.0
LOUDNORM = "I=-14:TP=-1.5:LRA=11"
# MoviePy's x264 output only carries colorspace; tag primaries/transfer on the copy-mux.
COLOR_BSF = "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1"
FASTSTART_SCAN_BYTES = 4 * 1024 * 1024   # moov must appear in the first 4 MiB
_LOUDNORM_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


class EncodingError(Exception):
    pass


def find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # noqa: BLE001
        raise EncodingError(f"ffmpeg not found on PATH or via imageio-ffmpeg: {e}")


def find_ffprobe() -> str:
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    sibling = Path(find_ffmpeg()).with_name("ffprobe" + Path(find_ffmpeg()).suffix)
    if sibling.exists():
        return str(sibling)
    raise EncodingError("ffprobe not found. Install ffmpeg (with ffprobe) and add it to PATH.")


def _run(cmd: list, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def probe_video(video_path) -> dict:
    """Ported from src/encoding.py:71, plus color tags and audio sample rate."""
    video_path = str(video_path)
    if not Path(video_path).exists():
        raise EncodingError(f"Video file not found: {video_path}")
    result = _run([find_ffprobe(), "-v", "quiet", "-print_format", "json",
                   "-show_format", "-show_streams", video_path], timeout=30)
    if result.returncode != 0:
        raise EncodingError(f"ffprobe failed: {result.stderr}")
    data = json.loads(result.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if video is None:
        raise EncodingError("No video stream found")
    num, _, den = video.get("r_frame_rate", "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    fmt = data.get("format", {})
    return {
        "duration": round(float(fmt.get("duration", 0)), 3),
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "fps": round(fps, 2),
        "video_codec": video.get("codec_name", "unknown"),
        "pixel_format": video.get("pix_fmt", "unknown"),
        "color_primaries": video.get("color_primaries", "unknown"),
        "color_transfer": video.get("color_transfer", "unknown"),
        "color_space": video.get("color_space", "unknown"),
        "audio_codec": audio.get("codec_name") if audio else None,
        "audio_sample_rate": int(audio.get("sample_rate", 0)) if audio else 0,
        "has_audio": audio is not None,
        "file_size": int(fmt.get("size", 0)),
        "bitrate": int(fmt.get("bit_rate", 0)),
    }


def get_audio_loudness(video_path) -> Optional[dict]:
    """Ported from src/encoding.py:176 (volumedetect mean/max dB)."""
    result = _run([find_ffmpeg(), "-hide_banner", "-i", str(video_path),
                   "-af", "volumedetect", "-f", "null", "-"], timeout=120)
    mean = re.search(r"mean_volume:\s*(-?[\d.]+) dB", result.stderr)
    peak = re.search(r"max_volume:\s*(-?[\d.]+) dB", result.stderr)
    if not mean:
        return None
    return {"mean_volume": float(mean.group(1)), "max_volume": float(peak.group(1)) if peak else None}


def faststart_ok(video_path) -> bool:
    """True when the moov atom precedes mdat (spec §12: faststart atom first)."""
    with open(video_path, "rb") as f:
        head = f.read(FASTSTART_SCAN_BYTES)
    moov, mdat = head.find(b"moov"), head.find(b"mdat")
    return moov != -1 and (mdat == -1 or moov < mdat)


def is_platform_safe(video_path) -> tuple:
    """Ported from src/encoding.py:401, plus the faststart check."""
    try:
        stats = probe_video(video_path)
    except EncodingError as e:
        return False, [str(e)]
    issues = []
    if stats["video_codec"] not in ("h264", "avc1"):
        issues.append(f"Video codec '{stats['video_codec']}' should be H.264")
    if stats["pixel_format"] != "yuv420p":
        issues.append(f"Pixel format '{stats['pixel_format']}' should be yuv420p")
    if stats["has_audio"] and stats["audio_codec"] not in ("aac", "mp4a"):
        issues.append(f"Audio codec '{stats['audio_codec']}' should be AAC")
    if stats["width"] != DEFAULT_WIDTH or stats["height"] != DEFAULT_HEIGHT:
        issues.append(f"Resolution {stats['width']}x{stats['height']} should be {DEFAULT_WIDTH}x{DEFAULT_HEIGHT}")
    if not 24 <= stats["fps"] <= 60:
        issues.append(f"FPS {stats['fps']} should be between 24-60")
    if not faststart_ok(video_path):
        issues.append("moov atom is not at the front (missing +faststart)")
    loud = measure_loudness(video_path) if stats["has_audio"] else None
    if loud and loud["input_tp"] > TRUE_PEAK_CEILING:
        issues.append(f"True peak {loud['input_tp']:.2f} dBTP exceeds {TRUE_PEAK_CEILING} dBTP ceiling")
    return len(issues) == 0, issues


def measure_loudness(media_path) -> Optional[dict]:
    """loudnorm pass 1. Returns floats input_i/input_tp/input_lra/input_thresh/target_offset,
    or None when the input is silent (-inf) or ffmpeg output cannot be parsed."""
    result = _run([find_ffmpeg(), "-hide_banner", "-nostats", "-i", str(media_path),
                   "-af", f"loudnorm={LOUDNORM}:print_format=json", "-f", "null", "-"], timeout=300)
    m = _LOUDNORM_JSON.search(result.stderr)
    if not m:
        logger.warning("loudnorm measurement failed: %s", result.stderr[-500:])
        return None
    try:
        raw = json.loads(m.group(0))
        out = {k: float(raw[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
    except (KeyError, TypeError, ValueError) as e:     # JSONDecodeError is a ValueError
        logger.warning("loudnorm output unparseable (%s): %s", e, m.group(0)[:300])
        return None
    # -inf (silence) and nan (degenerate input) must never reach the second loudnorm pass
    if not all(math.isfinite(v) for v in out.values()) or out["input_i"] < -70:
        return None
    return out


def write_video(clip, out_path, fps: int = DEFAULT_FPS) -> None:
    """Video-only MoviePy render with the spec §9.1 x264 settings."""
    clip.write_videofile(str(out_path), fps=fps, codec="libx264", audio=False,
                         preset=X264_PRESET, ffmpeg_params=list(X264_PARAMS), logger=None)


def mux_final(video_path, wav_path, out_path, measured: Optional[dict]) -> None:
    """loudnorm pass 2 (linear, from pass-1 measurements) + copy-mux (spec §9.1 steps 2-3).
    measured=None (silent mix) muxes without normalization."""
    cmd = [find_ffmpeg(), "-hide_banner", "-y", "-i", str(video_path), "-i", str(wav_path),
           "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-bsf:v", COLOR_BSF]
    if measured:
        cmd += ["-af", (f"loudnorm={LOUDNORM}:measured_I={measured['input_i']}"
                        f":measured_TP={measured['input_tp']}:measured_LRA={measured['input_lra']}"
                        f":measured_thresh={measured['input_thresh']}:offset={measured['target_offset']}"
                        ":linear=true:print_format=summary,aresample=48000")]
    cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out_path)]
    result = _run(cmd)
    if result.returncode != 0:
        raise EncodingError(f"ffmpeg mux failed: {result.stderr[-2000:]}")
