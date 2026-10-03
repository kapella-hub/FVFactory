import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.asset_manager import AssetManager


def test_generate_image_flux_downloads_to_path():
    mock_img_response = MagicMock()
    mock_img_response.status_code = 200
    mock_img_response.content = b"fake_png_data"

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AssetManager()
        manager.TEMP_DIR = Path(tmpdir)
        output_path = Path(tmpdir) / "test_image.png"

        with patch("app.asset_manager.replicate_run", return_value="https://replicate.delivery/fake/image.png") as mock_run:
            with patch("app.asset_manager.requests.get", return_value=mock_img_response):
                manager._generate_image_flux("a cute robot", output_path)

        assert output_path.exists()
        assert output_path.read_bytes() == b"fake_png_data"
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "flux" in call_args[0][0].lower()


def test_generate_images_uses_flux_not_dalle():
    from app.config import settings

    manager = AssetManager()

    original_provider = settings.image_provider
    original_mode = settings.provider_mode
    try:
        settings.image_provider = "replicate"
        settings.provider_mode = "api"
        with patch.object(manager, "_generate_image_flux") as mock_flux:
            with tempfile.TemporaryDirectory() as tmpdir:
                manager.TEMP_DIR = Path(tmpdir)
                manager.generate_images(["prompt1"], use_mock=False)
            mock_flux.assert_called_once()
    finally:
        settings.image_provider = original_provider
        settings.provider_mode = original_mode


def test_generate_images_mock_still_works():
    manager = AssetManager()
    with tempfile.TemporaryDirectory() as tmpdir:
        manager.TEMP_DIR = Path(tmpdir)
        paths = manager.generate_images(["p1", "p2", "p3", "p4", "p5"])
        assert len(paths) == 5
        for p in paths:
            assert Path(p).exists()


def test_elevenlabs_uses_v2_model():
    from app.config import settings
    manager = AssetManager()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"fake_audio_data"

    original_key = settings.elevenlabs_api_key
    try:
        settings.elevenlabs_api_key = "fake_key"
        with patch("app.asset_manager.requests.post", return_value=mock_response) as mock_post:
            with patch.object(manager, "_get_audio_duration", return_value=10.0):
                with tempfile.TemporaryDirectory() as tmpdir:
                    manager.TEMP_DIR = Path(tmpdir)
                    manager.generate_audio("Hello world")

        call_kwargs = mock_post.call_args
        payload = call_kwargs[1].get("json") or call_kwargs.kwargs.get("json")
        assert payload["model_id"] == "eleven_multilingual_v2"
    finally:
        settings.elevenlabs_api_key = original_key


def test_generate_audio_writes_to_requested_job_path(tmp_path):
    from app.config import settings
    manager = AssetManager()
    response = MagicMock(status_code=200, content=b"fake_audio")
    target = tmp_path / "job" / "sources" / "narration.mp3"
    original_key = settings.elevenlabs_api_key
    try:
        settings.elevenlabs_api_key = "fake_key"
        with patch("app.asset_manager.requests.post", return_value=response), \
                patch.object(manager, "_get_audio_duration", return_value=3.0):
            result = manager.generate_audio("Hello world", output_path=target)
    finally:
        settings.elevenlabs_api_key = original_key
    assert result.file_path == str(target)
    assert target.read_bytes() == b"fake_audio"


def test_mock_images_written_as_scene_files(tmp_path):
    paths = AssetManager().generate_images(["p1", "p2"], use_mock=True, output_dir=tmp_path / "images")
    assert paths == [str(tmp_path / "images" / "scene00.png"), str(tmp_path / "images" / "scene01.png")]
    assert all(Path(p).exists() for p in paths)


def test_fal_images_written_into_output_dir(tmp_path, monkeypatch):
    from app.config import settings
    fal = MagicMock()
    fal.subscribe.return_value = {"images": [{"url": "https://fal.media/img.png"}]}
    monkeypatch.setattr(settings, "image_provider", "fal")
    with patch.dict("sys.modules", {"fal_client": fal}), \
            patch("app.asset_manager.requests.get", return_value=MagicMock(status_code=200, content=b"png")):
        paths = AssetManager().generate_images(["a", "b"], use_mock=False, output_dir=tmp_path)
    assert paths == [str(tmp_path / "scene00.png"), str(tmp_path / "scene01.png")]
    assert (tmp_path / "scene01.png").read_bytes() == b"png"
