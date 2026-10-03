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


@pytest.fixture(autouse=True)
def _isolated_music_usage(tmp_path, monkeypatch):
    """No test may write the real data/music_usage.json."""
    monkeypatch.setattr("app.cin.music_library.default_usage_path",
                        lambda: tmp_path / "data" / "music_usage.json")


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


def make_tone_wav(path, seconds: float, freq: float, amp: float, windows=None) -> Path:
    """Stereo 48 kHz sine written with the stdlib; silent outside `windows` ([[t0, t1], ...]) if given."""
    import numpy as np
    from app.cin.audio_io import write_wav
    t = np.arange(int(round(seconds * 48000))) / 48000
    x = amp * np.sin(2 * np.pi * freq * t)
    if windows is not None:
        mask = np.zeros_like(t, dtype=bool)
        for a, b in windows:
            mask |= (t >= a) & (t < b)
        x = x * mask
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    write_wav(path, np.stack([x, x], axis=1))
    return Path(path)


# ---------------------------------------------------------------- job builder (Task 11)

def build_gold_job(tmp_path, durations=(5.0, 10.0), clip_size: str = "360x640", topic: str = "gold test"):
    """A ready-to-render job from the gold fixture: tone narration, scene images, synthetic clips.
    Returns (job, alignment, clip_specs). durations=(5, 10) keeps one segment per scene."""
    from PIL import Image
    from app.cin.job import create_job
    from app.cin.shot_plan import ClipSpec, plan_segments

    fx = load_fixture("words_gold_8s.json")
    alignment = fixture_alignment("words_gold_8s.json")
    job = create_job(topic, Path(tmp_path) / "output")
    make_tone(job.narration, fx["duration"])
    job.words.write_text(json.dumps(fx["words"]), encoding="utf-8")
    job.alignment.write_text(json.dumps(alignment.to_json()), encoding="utf-8")
    specs = []
    for seg in plan_segments(alignment, durations):
        image = job.image(seg.scene)
        if not image.exists():
            Image.new("RGB", (1080, 1920), (60 + 90 * seg.scene, 80, 150)).save(image)
        clip = make_test_clip(job.clip(seg.name), seg.requested_len, size=clip_size,
                              color=("red", "blue", "green")[seg.scene % 3])
        specs.append(ClipSpec(seg.scene, seg.index, seg.t0, seg.t1, seg.requested_len, job.rel(image),
                              path=job.rel(clip), duration=seg.requested_len, model="kling", attempts=1))
    return job, alignment, specs
