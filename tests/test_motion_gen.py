import tempfile
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
