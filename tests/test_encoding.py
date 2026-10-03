"""Encode helpers: probe, loudness, platform check, two-pass loudnorm mux (spec §9.1)."""
from pathlib import Path

import numpy as np
import pytest

from app.encoding import (
    X264_PARAMS, faststart_ok, find_ffmpeg, find_ffprobe, get_audio_loudness, is_platform_safe,
    measure_loudness, mux_final, probe_video, write_video,
)
from tests.conftest import make_silence, make_test_clip, make_tone


def test_ffmpeg_and_ffprobe_found():
    assert Path(find_ffmpeg()).exists()
    assert Path(find_ffprobe()).exists()


def test_x264_params_match_spec():
    assert X264_PARAMS == ["-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p", "-colorspace", "bt709",
                           "-color_primaries", "bt709", "-color_trc", "bt709"]


def test_probe_video(tmp_path):
    clip = make_test_clip(tmp_path / "c.mp4", 1.0)
    info = probe_video(clip)
    assert (info["width"], info["height"], info["fps"]) == (108, 192, 30.0)
    assert info["video_codec"] == "h264" and info["has_audio"] is False


def test_measure_loudness_tone_and_silence(tmp_path):
    tone = measure_loudness(make_tone(tmp_path / "t.wav", 3.0))
    assert tone is not None and -45 < tone["input_i"] < -20
    assert measure_loudness(make_silence(tmp_path / "s.wav", 3.0)) is None


def test_write_video_then_mux_hits_targets(tmp_path):
    from moviepy import VideoClip
    clip = VideoClip(lambda t: np.full((192, 108, 3), int(t * 30) % 255, np.uint8), duration=8.0)
    video = tmp_path / "video.mp4"
    write_video(clip, video)
    wav = make_tone(tmp_path / "mix.wav", 8.0)
    out = tmp_path / "final.mp4"
    mux_final(video, wav, out, measure_loudness(wav))

    info = probe_video(out)
    assert info["fps"] == 30.0 and info["pixel_format"] == "yuv420p"
    assert (info["color_primaries"], info["color_transfer"], info["color_space"]) == ("bt709", "bt709", "bt709")
    assert info["audio_codec"] == "aac" and info["audio_sample_rate"] == 48000
    assert abs(info["duration"] - 8.0) <= 0.05
    assert faststart_ok(out)
    loud = measure_loudness(out)
    assert -15.0 <= loud["input_i"] <= -13.0
    assert loud["input_tp"] <= -1.0
    assert get_audio_loudness(out)["mean_volume"] < 0


def test_mux_without_measurement_still_muxes(tmp_path):
    video = make_test_clip(tmp_path / "v.mp4", 2.0)
    out = tmp_path / "final.mp4"
    mux_final(video, make_silence(tmp_path / "s.wav", 2.0), out, None)
    assert probe_video(out)["has_audio"] is True


def test_platform_check_flags_wrong_resolution(tmp_path):
    ok, issues = is_platform_safe(make_test_clip(tmp_path / "c.mp4", 1.0))
    assert ok is False
    assert "Resolution 108x192 should be 1080x1920" in issues
