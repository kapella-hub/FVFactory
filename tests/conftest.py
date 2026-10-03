"""Shared test helpers for the shot-based editor."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fixture_alignment(name: str):
    from app.cin.align import align_words
    fx = load_fixture(name)
    return align_words(fx["words"], fx["scene_texts"], fx["narration"], fx["duration"])


@pytest.fixture
def rolex() -> dict:
    return load_fixture("words_rolex_40s.json")


@pytest.fixture
def gold() -> dict:
    return load_fixture("words_gold_8s.json")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "render: renders real frames/encodes with ffmpeg (slow, 10-120 s). Skip with -m \"not render\".",
    )


# ---------------------------------------------------------------- synthetic media

def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def make_test_clip(path, seconds: float, size: str = "108x192", color: str = "red", rate: int = 30) -> Path:
    """Synthetic motion clip: ffmpeg testsrc blended with a solid colour."""
    subprocess.run([ffmpeg_exe(), "-v", "error", "-y",
                    "-f", "lavfi", "-i", f"testsrc=size={size}:rate={rate}:duration={seconds}",
                    "-f", "lavfi", "-i", f"color=c={color}:size={size}:rate={rate}:duration={seconds}",
                    "-filter_complex", "[0][1]blend=all_mode=average",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return Path(path)


def make_color_clip(path, seconds: float, color: str, size: str = "108x192", rate: int = 30) -> Path:
    """Solid-colour clip (renderer colour assertions)."""
    subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-f", "lavfi",
                    "-i", f"color=c={color}:size={size}:rate={rate}:duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return Path(path)


def make_tone(path, seconds: float, volume: float = 0.3) -> Path:
    """Speech-like test tone (220 Hz, 3 Hz tremolo). Container/codec follow the extension."""
    subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-f", "lavfi",
                    "-i", f"sine=frequency=220:sample_rate=48000:duration={seconds}",
                    "-af", f"volume={volume},tremolo=f=3:d=0.7", str(path)], check=True)
    return Path(path)


def make_silence(path, seconds: float) -> Path:
    subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-f", "lavfi",
                    "-i", "anullsrc=r=48000:cl=stereo", "-t", str(seconds), str(path)], check=True)
    return Path(path)
