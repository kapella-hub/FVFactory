import tempfile

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.motion_gen import MotionGenerator


def test_generate_motion_clip_fal():
    """Test fal.ai motion generation path."""
    mock_settings = MagicMock()
    mock_settings.motion_provider = "fal"
    mock_settings.fal_api_key = "test-key"
    mock_settings.fal_video_model = "hailuo"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"fake_video_data"

    with tempfile.TemporaryDirectory() as tmpdir:
        gen = MotionGenerator(temp_dir=tmpdir)
        fake_image = Path(tmpdir) / "input.png"
        fake_image.write_bytes(b"fake_png")

        mock_fal = MagicMock()
        mock_fal.upload_file.return_value = "https://fal.media/uploaded.png"
        mock_fal.subscribe.return_value = {"video": {"url": "https://fal.media/output.mp4"}}

        with patch("app.motion_gen.settings", mock_settings):
            with patch.dict("sys.modules", {"fal_client": mock_fal}):
                with patch("app.motion_gen.requests.get", return_value=mock_response):
                    # Need to reimport to pick up mocked fal_client
                    import importlib
                    import app.motion_gen
                    importlib.reload(app.motion_gen)
                    gen2 = app.motion_gen.MotionGenerator(temp_dir=tmpdir)
                    result = gen2._generate_fal(str(fake_image), "slow zoom in", 0)

        assert result is not None
        assert Path(result).suffix == ".mp4"


def test_generate_motion_clip_replicate():
    """Test Replicate motion generation path."""
    mock_video_response = MagicMock()
    mock_video_response.status_code = 200
    mock_video_response.iter_content = lambda chunk_size: [b"fake_video_data"]

    with tempfile.TemporaryDirectory() as tmpdir:
        gen = MotionGenerator(temp_dir=tmpdir)
        fake_image = Path(tmpdir) / "input.png"
        fake_image.write_bytes(b"fake_png")

        mock_settings = MagicMock()
        mock_settings.motion_provider = "replicate"
        mock_settings.minimax_model = "minimax/test"

        with patch("app.motion_gen.settings", mock_settings):
            with patch("app.replicate_api.replicate_run", return_value="https://replicate.delivery/fake/video.mp4"):
                with patch("app.motion_gen.requests.get", return_value=mock_video_response):
                    result = gen.generate_motion_clip(str(fake_image), "slow zoom in")

        assert result is not None
        assert Path(result).suffix == ".mp4"


def test_generate_motion_clip_failure_returns_none():
    with tempfile.TemporaryDirectory() as tmpdir:
        gen = MotionGenerator(temp_dir=tmpdir)
        fake_image = Path(tmpdir) / "input.png"
        fake_image.write_bytes(b"fake_png")

        mock_settings = MagicMock()
        mock_settings.motion_provider = "replicate"
        mock_settings.minimax_model = "minimax/test"

        with patch("app.motion_gen.settings", mock_settings):
            with patch("app.replicate_api.replicate_run", side_effect=Exception("API error")):
                with patch("app.motion_gen.requests.get", side_effect=Exception("API error")):
                    result = gen.generate_motion_clip(str(fake_image), "zoom in")

        assert result is None


def test_generate_all_clips_partial_failure():
    with tempfile.TemporaryDirectory() as tmpdir:
        gen = MotionGenerator(temp_dir=tmpdir)

        images = []
        for i in range(3):
            img = Path(tmpdir) / f"img_{i}.png"
            img.write_bytes(b"fake_png")
            images.append(str(img))

        call_count = 0
        def mock_generate(image_path, motion_prompt, index=0):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return None
            clip_path = Path(tmpdir) / f"clip_{call_count}.mp4"
            clip_path.write_bytes(b"fake_mp4")
            return str(clip_path)

        with patch.object(gen, "generate_motion_clip", side_effect=mock_generate):
            results = gen.generate_all_clips(images, ["zoom", "pan", "tilt"])

        assert len(results) == 3
        assert results[1] is None
        assert results[0] is not None
        assert results[2] is not None


import math

from app.motion_gen import CLIP_MODELS, clip_model_for, max_duration, snap_duration


def test_snap_duration_rounds_up_to_supported_lengths():
    assert snap_duration(2.8, (6.0,)) == 6.0
    assert snap_duration(6.2, (6.0,)) is None          # too long: caller must split the scene
    assert snap_duration(5.0, (5.0, 10.0)) == 5.0
    assert snap_duration(5.01, (5.0, 10.0)) == 10.0
    assert snap_duration(7.333, None) == 7.33           # any-length model: exact request


def test_max_duration():
    assert max_duration((5.0, 10.0)) == 10.0
    assert max_duration(None) == math.inf


def test_clip_model_for_providers():
    assert clip_model_for("fal", "kling").key == "kling"
    assert clip_model_for("fal", "unknown-model").key == "hailuo"
    assert clip_model_for("replicate", "kling").key == "replicate-minimax"
    assert clip_model_for("local", "hailuo").durations is None
    assert CLIP_MODELS["hailuo"].durations == (6.0,)
    assert CLIP_MODELS["kling"].duration_format == "int_str"


def _fake_fal():
    fal = MagicMock()
    fal.upload_file.return_value = "https://fal.media/in.png"
    fal.subscribe.return_value = {"video": {"url": "https://fal.media/out.mp4"}}
    return fal


def _ok_response():
    response = MagicMock()
    response.status_code = 200
    response.content = b"fake_mp4"
    return response


def _clip_paths(tmp_path):
    image = tmp_path / "in.png"
    image.write_bytes(b"png")
    out = tmp_path / "clips" / "scene00_a.mp4"
    out.parent.mkdir()
    return image, out


def test_generate_clip_kling_requests_snapped_duration(tmp_path, monkeypatch):
    from app.config import settings
    from app.motion_gen import CLIP_MODELS, MotionGenerator
    monkeypatch.setattr(settings, "motion_provider", "fal")
    fal = _fake_fal()
    image, out = _clip_paths(tmp_path)
    with patch.dict("sys.modules", {"fal_client": fal}), \
            patch("app.motion_gen.requests.get", return_value=_ok_response()):
        result = MotionGenerator(temp_dir=str(tmp_path)).generate_clip(
            str(image), "orbit", str(out), duration=6.2, model_key="kling")
    assert result == str(out) and out.read_bytes() == b"fake_mp4"
    assert fal.subscribe.call_args.args[0] == CLIP_MODELS["kling"].endpoint
    assert fal.subscribe.call_args.kwargs["arguments"] == {
        "prompt": "orbit", "start_image_url": "https://fal.media/in.png",
        "generate_audio": False, "duration": "7"}


def test_generate_clip_hailuo_sends_no_duration(tmp_path, monkeypatch):
    from app.config import settings
    from app.motion_gen import MotionGenerator
    monkeypatch.setattr(settings, "motion_provider", "fal")
    fal = _fake_fal()
    image, out = _clip_paths(tmp_path)
    with patch.dict("sys.modules", {"fal_client": fal}), \
            patch("app.motion_gen.requests.get", return_value=_ok_response()):
        MotionGenerator(temp_dir=str(tmp_path)).generate_clip(
            str(image), "push in", str(out), duration=4.0, model_key="hailuo")
    assert "duration" not in fal.subscribe.call_args.kwargs["arguments"]


def test_missing_fal_client_counts_as_clip_failure(tmp_path, monkeypatch):
    from app.config import settings
    from app.motion_gen import MotionGenerator
    monkeypatch.setattr(settings, "motion_provider", "fal")
    image, out = _clip_paths(tmp_path)
    with patch.dict("sys.modules", {"fal_client": None}):
        assert MotionGenerator(temp_dir=str(tmp_path)).generate_clip(str(image), "p", str(out)) is None
    assert not out.exists()


def test_unknown_or_non_fal_model_key_fails_clip(tmp_path, monkeypatch):
    from app.config import settings
    from app.motion_gen import MotionGenerator
    monkeypatch.setattr(settings, "motion_provider", "fal")
    image, out = _clip_paths(tmp_path)
    for key in ("nonsense", "replicate-minimax", "local"):
        fal = _fake_fal()
        with patch.dict("sys.modules", {"fal_client": fal}), \
                patch("app.motion_gen.requests.get", return_value=_ok_response()):
            assert MotionGenerator(temp_dir=str(tmp_path)).generate_clip(
                str(image), "p", str(out), model_key=key) is None
        fal.subscribe.assert_not_called()


# ---------------------------------------------------------------- quality tiers (spec 2026-10-03 §5)

def test_clip_model_table_points_kling_keys_at_v3():
    from app.motion_gen import CLIP_MODELS, H3_LENGTHS, KLING_V3_LENGTHS
    assert CLIP_MODELS["kling"].endpoint == "fal-ai/kling-video/v3/standard/image-to-video"
    assert CLIP_MODELS["kling-pro"].endpoint == "fal-ai/kling-video/v3/pro/image-to-video"
    assert CLIP_MODELS["h3-turbo"].endpoint == "minimax/h3-max-turbo/image-to-video"
    assert CLIP_MODELS["h3"].endpoint == "minimax/h3-max/image-to-video"
    assert KLING_V3_LENGTHS == tuple(float(d) for d in range(3, 16))
    assert H3_LENGTHS == tuple(float(d) for d in range(5, 16))
    assert all(m.key == k and m.label for k, m in CLIP_MODELS.items())


@pytest.mark.parametrize("key", ["kling", "kling-pro"])
def test_kling_v3_payload_never_bills_audio(key):
    """Cost correctness: fal's generate_audio default is true and costs more (spec §5)."""
    from app.motion_gen import CLIP_MODELS, build_fal_arguments
    args = build_fal_arguments(CLIP_MODELS[key], "https://fal.media/in.png", "orbit", 4.7)
    assert args == {"prompt": "orbit", "start_image_url": "https://fal.media/in.png",
                    "generate_audio": False, "duration": "5"}
    assert "image_url" not in args and "aspect_ratio" not in args


@pytest.mark.parametrize("duration, expected", [(None, "3"), (2.0, "3"), (5.0, "5"), (5.01, "6"),
                                                (14.9, "15"), (20.0, "15")])
def test_kling_duration_snaps_up_to_whole_seconds(duration, expected):
    from app.motion_gen import CLIP_MODELS, build_fal_arguments
    assert build_fal_arguments(CLIP_MODELS["kling"], "u", "p", duration)["duration"] == expected


@pytest.mark.parametrize("key", ["h3-turbo", "h3"])
def test_h3_payload_has_numeric_duration_and_768p(key):
    from app.motion_gen import CLIP_MODELS, build_fal_arguments
    args = build_fal_arguments(CLIP_MODELS[key], "https://fal.media/in.png", "pan", 6.2)
    assert args == {"prompt": "pan", "image_url": "https://fal.media/in.png", "resolution": "768P",
                    "prompt_expansion_mode": "balanced", "duration": 7}
    assert build_fal_arguments(CLIP_MODELS[key], "u", "p", 2.0)["duration"] == 5


def test_hailuo_payload_has_no_duration():
    from app.motion_gen import CLIP_MODELS, build_fal_arguments
    assert build_fal_arguments(CLIP_MODELS["hailuo"], "u", "p", 4.0) == {"prompt": "p", "image_url": "u"}


def test_generate_fal_sends_the_builder_payload(tmp_path, monkeypatch):
    from app.config import settings
    from app.motion_gen import CLIP_MODELS, MotionGenerator, build_fal_arguments
    monkeypatch.setattr(settings, "motion_provider", "fal")
    fal = _fake_fal()
    image, out = _clip_paths(tmp_path)
    with patch.dict("sys.modules", {"fal_client": fal}), \
            patch("app.motion_gen.requests.get", return_value=_ok_response()):
        MotionGenerator(temp_dir=str(tmp_path)).generate_clip(
            str(image), "orbit", str(out), duration=6.2, model_key="h3-turbo")
    assert fal.subscribe.call_args.args[0] == CLIP_MODELS["h3-turbo"].endpoint
    assert fal.subscribe.call_args.kwargs["arguments"] == build_fal_arguments(
        CLIP_MODELS["h3-turbo"], "https://fal.media/in.png", "orbit", 6.2)


def test_classic_clip_keeps_five_seconds_on_kling_v3(tmp_path, monkeypatch):
    """The classic editor passes no length; it used to get Kling's old 5 s minimum (spec §8.7: unchanged)."""
    from app.config import settings
    from app.motion_gen import MotionGenerator
    monkeypatch.setattr(settings, "motion_provider", "fal")
    monkeypatch.setattr(settings, "fal_video_model", "kling")
    fal = _fake_fal()
    image, _ = _clip_paths(tmp_path)
    with patch.dict("sys.modules", {"fal_client": fal}), \
            patch("app.motion_gen.requests.get", return_value=_ok_response()):
        assert MotionGenerator(temp_dir=str(tmp_path)).generate_motion_clip(str(image), "orbit") is not None
    assert fal.subscribe.call_args.kwargs["arguments"]["duration"] == "5"


def test_every_clip_model_has_list_pricing():
    from app.config import Settings
    from app.motion_gen import CLIP_MODELS
    pricing = Settings(_env_file=None).clip_pricing
    assert set(CLIP_MODELS) <= set(pricing)
    assert pricing["kling"] == {"per_second": 0.084} and pricing["kling-pro"] == {"per_second": 0.112}
    assert pricing["h3-turbo"] == {"per_second": 0.04} and pricing["h3"] == {"per_second": 0.08}
    assert pricing["hailuo"] == {"per_clip": 0.50}
