"""Integration tests for CinematicEngine."""
import pytest
import numpy as np
from PIL import Image
from pathlib import Path


@pytest.fixture
def test_assets(tmp_path):
    img_paths = []
    for i in range(3):
        path = str(tmp_path / f"scene_{i}.png")
        img = Image.fromarray(np.random.randint(50, 200, (1920, 1080, 3), dtype=np.uint8))
        img.save(path)
        img_paths.append(path)

    import wave, struct
    sr = 16000
    samples = int(sr * 3.0)
    audio_data = [int(16000 * np.sin(2 * np.pi * 440 * i / sr)) for i in range(samples)]
    audio_path = str(tmp_path / "audio.wav")
    with wave.open(audio_path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"{samples}h", *audio_data))

    return {"images": img_paths, "audio": audio_path, "output_dir": str(tmp_path)}


def test_cinematic_renders_video(test_assets):
    from app.cinematic import CinematicEngine
    engine = CinematicEngine(output_dir=test_assets["output_dir"])
    output = engine.render(
        audio_path=test_assets["audio"],
        image_paths=test_assets["images"],
        scene_texts=["First scene.", "Second scene.", "Third scene."],
        output_filename="test_cinematic.mp4",
    )
    assert Path(output).exists()
    assert Path(output).stat().st_size > 0
