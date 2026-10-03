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


def test_local_images_are_written_into_the_job_folder_not_shared_temp(tmp_path, monkeypatch):
    """spec §4: intermediates live in the job folder. The real LocalImageGenerator needs torch,
    so a stand-in module replaces app.local_image_gen."""
    import sys
    import types
    from app.config import settings
    seen = {}

    class FakeLocalGen:
        def __init__(self, model_id=None):
            pass

        def generate_batch(self, prompts, width, height, output_dir):
            seen["dir"] = Path(output_dir)
            out = []
            for i, _ in enumerate(prompts):
                p = Path(output_dir) / f"scene_{i:03d}.png"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"png%d" % i)
                out.append(str(p))
            return out

        def unload(self):
            seen["unloaded"] = True

    shared = tmp_path / "shared_temp"
    monkeypatch.setitem(sys.modules, "app.local_image_gen", types.SimpleNamespace(LocalImageGenerator=FakeLocalGen))
    monkeypatch.setattr(settings, "image_provider", "local")
    monkeypatch.setattr(AssetManager, "TEMP_DIR", shared)
    images = tmp_path / "job" / "sources" / "images"
    paths = AssetManager().generate_images(["a", "b"], use_mock=False, output_dir=images)
    assert paths == [str(images / "scene00.png"), str(images / "scene01.png")]
    assert (images / "scene01.png").read_bytes() == b"png1"
    assert seen["dir"] == images and seen["unloaded"] is True
    assert not list(images.glob("scene_*.png"))                 # renamed in place, no leftovers
    assert not list(shared.glob("*.png"))                       # shared temp untouched



# ------------------------------------------------------------------ style suffix (spec 2026-10-03 §9)

def test_photoreal_prompts_get_photographic_keywords_not_vector_art(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "image_style", "")
    out = AssetManager(video_style="photorealistic")._enhance_prompt_with_style("a gold bar on a scale")
    assert out.startswith("a gold bar on a scale, ") and "photorealistic photograph" in out
    for word in ("vector", "cartoon", "clean lines", "robot"):
        assert word not in out


def test_non_photoreal_prompts_keep_their_own_style(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "image_style", "")
    prompt = "a gold bar on a scale, cartoon style, vibrant colors"
    assert AssetManager(video_style="cartoon")._enhance_prompt_with_style(prompt) == prompt


def test_explicit_image_style_setting_still_overrides(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "image_style", "35mm film grain")
    out = AssetManager(video_style="photorealistic")._enhance_prompt_with_style("a vault door")
    assert out == "a vault door, 35mm film grain"
    assert AssetManager(video_style="cartoon")._enhance_prompt_with_style("a vault door") == "a vault door, 35mm film grain"


def test_run_style_defaults_to_the_setting(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "video_style", "anime")
    assert AssetManager().video_style == "anime"
    assert AssetManager(video_style="noir").video_style == "noir"


def test_mock_image_never_mentions_the_mascot_for_photoreal(monkeypatch, tmp_path):
    from PIL import ImageDraw
    from app.config import settings
    monkeypatch.setattr(settings, "mascot_enabled", True)
    drawn = []
    original = ImageDraw.ImageDraw.text
    monkeypatch.setattr(ImageDraw.ImageDraw, "text",
                        lambda self, xy, text, *a, **k: drawn.append(text) or original(self, xy, text, *a, **k))
    AssetManager(video_style="photorealistic").generate_images(["p"], use_mock=True, output_dir=tmp_path / "a")
    assert drawn and not any("MASCOT" in t for t in drawn)
    drawn.clear()
    AssetManager(video_style="cartoon").generate_images(["p"], use_mock=True, output_dir=tmp_path / "b")
    assert any("MASCOT" in t for t in drawn)
