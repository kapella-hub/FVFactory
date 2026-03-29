# Cinematic AI Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the slideshow-like video assembly with a cinematic editing engine that uses depth-based parallax, multi-shot editing within scenes, audio-reactive cut timing, kinetic typography, atmospheric particles, and smart transitions — producing output that looks hand-edited, not auto-generated.

**Architecture:** New `app/cinematic.py` module replaces the video assembly logic in `video_editor.py`. It takes the same inputs (audio, images, scene_texts, subtitle_style) but produces radically different output by: (1) extracting depth maps with Depth Anything v2 to create 2.5D parallax, (2) cropping each image into multiple "shots" and cutting between them synced to audio energy, (3) adding floating particles between depth layers, (4) rendering key words as kinetic typography instead of static subtitles, (5) using whip-pan and zoom-through transitions instead of crossfades. All CPU/PIL/numpy — no GPU models except the tiny depth estimator (~24MB on MPS, <1s per image).

**Tech Stack:** Python, PIL/Pillow, numpy, moviepy, transformers (Depth Anything v2 Small — 24.8M params), scipy (audio FFT), existing Whisper word timestamps

---

## File Map

### New Files

| File | Responsibility |
|---|---|
| `app/cinematic.py` | CinematicEngine — main orchestrator. Takes audio + images + metadata, produces final video. Coordinates all sub-modules. |
| `app/cin/depth.py` | Depth extraction using Depth Anything v2. Returns depth maps and splits images into layers. |
| `app/cin/parallax.py` | 2.5D parallax compositor. Takes depth layers, applies differential motion, renders frames. |
| `app/cin/multishot.py` | Multi-shot editor. Crops single image into wide/medium/close-up/detail shots. Decides cut timing from audio energy. |
| `app/cin/audio_analysis.py` | Audio energy analysis. Extracts volume envelope, detects emphasis points, pauses, speech rhythm from Whisper timestamps. |
| `app/cin/transitions.py` | Smart transitions between scenes — whip-pan, zoom-through, flash, glitch. |
| `app/cin/particles.py` | Atmospheric particle system — dust, embers, bokeh, snow. Renders as transparent overlay per frame. |
| `app/cin/kinetic_text.py` | Kinetic typography for key words — slam-in, scale-up, fly-across. Uses Whisper word timestamps. |
| `app/cin/__init__.py` | Package init |
| `tests/test_cinematic.py` | Integration test for CinematicEngine |
| `tests/test_cin_depth.py` | Depth extraction tests |
| `tests/test_cin_multishot.py` | Multi-shot editor tests |
| `tests/test_cin_audio.py` | Audio analysis tests |

### Modified Files

| File | Changes |
|---|---|
| `app/video_editor.py` | `assemble_video()` gains `cinematic: bool` param. When True, delegates to CinematicEngine instead of Ken Burns pipeline. |
| `main.py` | Pass `cinematic=True` by default to `assemble_video()`. Add `--classic` CLI flag to use old pipeline. |
| `app/config.py` | Add `cinematic_enabled`, `particle_style`, `depth_parallax_strength` settings |
| `requirements.txt` | Add `scipy` (for audio FFT) |

---

## Task 1: Audio Analysis Module

The foundation — everything else depends on knowing where the emphasis points, pauses, and energy peaks are in the narration.

**Files:**
- Create: `app/cin/__init__.py`
- Create: `app/cin/audio_analysis.py`
- Create: `tests/test_cin_audio.py`

- [ ] **Step 1: Create package and write tests**

```python
# app/cin/__init__.py
# (empty)
```

```python
# tests/test_cin_audio.py
"""Tests for audio analysis module."""
import pytest
import numpy as np


def test_compute_energy_envelope():
    from app.cin.audio_analysis import compute_energy_envelope
    # 1 second of sine wave at 44100 Hz
    sr = 44100
    t = np.linspace(0, 1.0, sr)
    audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    envelope = compute_energy_envelope(audio, sr, hop_size=4410)
    assert len(envelope) == 10  # 1 second / 0.1s hop = 10 bins
    assert all(e >= 0 for e in envelope)


def test_find_emphasis_points():
    from app.cin.audio_analysis import find_emphasis_points
    # Energy with clear peaks
    envelope = [0.1, 0.2, 0.9, 0.2, 0.1, 0.8, 0.1, 0.1, 0.7, 0.1]
    times = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    peaks = find_emphasis_points(envelope, times, threshold=0.6)
    assert len(peaks) >= 2  # should find at least 2 peaks above threshold


def test_detect_pauses():
    from app.cin.audio_analysis import detect_pauses
    envelope = [0.5, 0.5, 0.01, 0.01, 0.01, 0.5, 0.5, 0.01, 0.01, 0.5]
    times = [i * 0.1 for i in range(10)]
    pauses = detect_pauses(envelope, times, silence_threshold=0.05, min_duration=0.2)
    assert len(pauses) >= 1  # should detect at least 1 pause


def test_analyze_audio_full(tmp_path):
    from app.cin.audio_analysis import analyze_audio
    # Create a simple WAV file
    import wave, struct
    sr = 16000
    duration = 2.0
    samples = int(sr * duration)
    audio_data = [int(32767 * np.sin(2 * np.pi * 440 * i / sr)) for i in range(samples)]

    wav_path = str(tmp_path / "test.wav")
    with wave.open(wav_path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"{len(audio_data)}h", *audio_data))

    result = analyze_audio(wav_path)
    assert "energy_envelope" in result
    assert "emphasis_points" in result
    assert "pauses" in result
    assert "duration" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_cin_audio.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement audio analysis**

```python
# app/cin/audio_analysis.py
"""Audio analysis for cinematic editing — energy envelope, emphasis, pauses."""

import logging
import numpy as np

logger = logging.getLogger(__name__)


def compute_energy_envelope(audio: np.ndarray, sr: int, hop_size: int = 0) -> list[float]:
    """Compute RMS energy envelope from raw audio samples.

    Returns a list of energy values, one per time window.
    """
    if hop_size <= 0:
        hop_size = sr // 10  # 100ms windows by default

    envelope = []
    for start in range(0, len(audio), hop_size):
        chunk = audio[start:start + hop_size]
        rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
        envelope.append(rms)

    # Normalize to 0.0-1.0
    peak = max(envelope) if envelope else 1.0
    if peak > 0:
        envelope = [e / peak for e in envelope]

    return envelope


def find_emphasis_points(envelope: list[float], times: list[float],
                         threshold: float = 0.7) -> list[float]:
    """Find timestamps where energy spikes above threshold (emphasis moments)."""
    peaks = []
    for i in range(1, len(envelope) - 1):
        if (envelope[i] > threshold and
                envelope[i] >= envelope[i - 1] and
                envelope[i] >= envelope[i + 1]):
            peaks.append(times[i])
    return peaks


def detect_pauses(envelope: list[float], times: list[float],
                  silence_threshold: float = 0.05,
                  min_duration: float = 0.2) -> list[dict]:
    """Detect silent pauses in audio. Returns list of {start, end, duration}."""
    pauses = []
    in_silence = False
    silence_start = 0.0

    for i, energy in enumerate(envelope):
        t = times[i] if i < len(times) else i * 0.1
        if energy < silence_threshold:
            if not in_silence:
                silence_start = t
                in_silence = True
        else:
            if in_silence:
                dur = t - silence_start
                if dur >= min_duration:
                    pauses.append({"start": silence_start, "end": t, "duration": dur})
                in_silence = False

    return pauses


def analyze_audio(audio_path: str, hop_ms: int = 50) -> dict:
    """Full audio analysis: energy envelope, emphasis points, pauses.

    Reads audio file via moviepy, returns analysis dict.
    """
    from moviepy import AudioFileClip

    clip = AudioFileClip(audio_path)
    sr = clip.fps or 44100
    duration = clip.duration

    # Extract raw samples
    audio_arr = clip.to_soundarray()
    if audio_arr.ndim > 1:
        audio_arr = audio_arr.mean(axis=1)  # mono
    audio_arr = audio_arr.astype(np.float32)

    hop_size = int(sr * hop_ms / 1000)
    envelope = compute_energy_envelope(audio_arr, sr, hop_size)
    times = [i * hop_ms / 1000 for i in range(len(envelope))]

    emphasis = find_emphasis_points(envelope, times)
    pauses = detect_pauses(envelope, times)

    logger.info("Audio analysis: %.1fs, %d emphasis points, %d pauses",
                duration, len(emphasis), len(pauses))

    clip.close()

    return {
        "energy_envelope": envelope,
        "times": times,
        "emphasis_points": emphasis,
        "pauses": pauses,
        "duration": duration,
        "sample_rate": sr,
    }
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_cin_audio.py -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/cin/ tests/test_cin_audio.py
git commit -m "feat: add audio analysis module — energy envelope, emphasis, pause detection"
```

---

## Task 2: Depth Extraction Module

**Files:**
- Create: `app/cin/depth.py`
- Create: `tests/test_cin_depth.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_cin_depth.py
"""Tests for depth extraction module."""
import pytest
import numpy as np
from PIL import Image


def test_estimate_depth_returns_array(tmp_path):
    from app.cin.depth import estimate_depth
    img_path = str(tmp_path / "test.png")
    Image.fromarray(np.random.randint(0, 255, (256, 256, 3), dtype=np.uint8)).save(img_path)
    depth = estimate_depth(img_path)
    assert isinstance(depth, np.ndarray)
    assert depth.shape[:2] == (256, 256)  # same spatial dims as input


def test_split_into_layers():
    from app.cin.depth import split_into_layers
    img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
    depth = np.random.rand(100, 100).astype(np.float32)
    layers = split_into_layers(img, depth, num_layers=3)
    assert len(layers) == 3
    for layer in layers:
        assert layer["rgba"].shape == (100, 100, 4)
        assert "depth_range" in layer
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_cin_depth.py -v`
Expected: FAIL

- [ ] **Step 3: Implement depth extraction**

```python
# app/cin/depth.py
"""Depth estimation using Depth Anything v2 Small.

Model: ~24MB, runs in <1s per image on Apple Silicon MPS.
Falls back to gradient-based pseudo-depth if model unavailable.
"""

import logging
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_depth_pipeline = None


def _get_depth_pipeline():
    """Lazy-load the depth estimation pipeline."""
    global _depth_pipeline
    if _depth_pipeline is not None:
        return _depth_pipeline

    try:
        from transformers import pipeline
        _depth_pipeline = pipeline(
            "depth-estimation",
            model="depth-anything/Depth-Anything-V2-Small-hf",
            device="mps",
        )
        logger.info("Depth Anything v2 Small loaded on MPS")
    except Exception as e:
        logger.warning("Depth model unavailable (%s), using gradient fallback", e)
        _depth_pipeline = "fallback"

    return _depth_pipeline


def estimate_depth(image_path: str) -> np.ndarray:
    """Estimate depth map from an image. Returns float32 array normalized 0-1.

    Uses Depth Anything v2 Small if available, otherwise gradient-based fallback.
    """
    img = Image.open(image_path).convert("RGB")
    pipe = _get_depth_pipeline()

    if pipe != "fallback" and pipe is not None:
        try:
            result = pipe(img)
            depth = np.array(result["depth"]).astype(np.float32)
            # Resize to match input if needed
            if depth.shape[:2] != (img.height, img.width):
                depth_img = Image.fromarray(depth).resize((img.width, img.height), Image.BILINEAR)
                depth = np.array(depth_img).astype(np.float32)
        except Exception as e:
            logger.warning("Depth estimation failed: %s, using fallback", e)
            depth = _gradient_depth(img.width, img.height)
    else:
        depth = _gradient_depth(img.width, img.height)

    # Normalize to 0-1
    dmin, dmax = depth.min(), depth.max()
    if dmax > dmin:
        depth = (depth - dmin) / (dmax - dmin)
    else:
        depth = np.zeros_like(depth)

    return depth


def _gradient_depth(width: int, height: int) -> np.ndarray:
    """Fallback: vertical gradient (top=far, bottom=near). Works surprisingly
    well for the parallax effect since most scenes have sky/bg at top."""
    return np.linspace(0.0, 1.0, height, dtype=np.float32)[:, np.newaxis].repeat(width, axis=1)


def split_into_layers(img_arr: np.ndarray, depth: np.ndarray,
                      num_layers: int = 3) -> list[dict]:
    """Split an image into depth layers with alpha masks.

    Each layer is a dict with:
      - rgba: RGBA numpy array (transparent where not this layer)
      - depth_range: (min_depth, max_depth) tuple
      - speed: parallax speed multiplier (bg=slow, fg=fast)
    """
    h, w = img_arr.shape[:2]
    layers = []

    for i in range(num_layers):
        lo = i / num_layers
        hi = (i + 1) / num_layers

        # Create alpha mask for this depth range
        mask = ((depth >= lo) & (depth < hi)).astype(np.float32)

        # Smooth the mask edges to avoid hard cuts
        from PIL import ImageFilter
        mask_img = Image.fromarray((mask * 255).astype(np.uint8))
        mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=3))
        mask = np.array(mask_img).astype(np.float32) / 255.0

        # Create RGBA layer
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[:, :, :3] = img_arr[:, :, :3]
        rgba[:, :, 3] = (mask * 255).astype(np.uint8)

        # Speed: background layers (low depth) move slow, foreground fast
        speed = 0.3 + (i / max(num_layers - 1, 1)) * 1.4  # 0.3x to 1.7x

        layers.append({
            "rgba": rgba,
            "depth_range": (lo, hi),
            "speed": speed,
        })

    return layers


def unload_depth_model():
    """Free the depth model from memory."""
    global _depth_pipeline
    if _depth_pipeline is not None and _depth_pipeline != "fallback":
        del _depth_pipeline
    _depth_pipeline = None
    logger.info("Depth model unloaded")
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_cin_depth.py -v`
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/cin/depth.py tests/test_cin_depth.py
git commit -m "feat: add depth extraction with Depth Anything v2 + gradient fallback"
```

---

## Task 3: Parallax Compositor

**Files:**
- Create: `app/cin/parallax.py`

- [ ] **Step 1: Implement parallax rendering**

```python
# app/cin/parallax.py
"""2.5D parallax compositor — moves depth layers at different speeds."""

import math
import numpy as np
from PIL import Image


def render_parallax_frame(layers: list[dict], t: float,
                          camera_x: float = 0.0, camera_y: float = 0.0,
                          camera_zoom: float = 1.0,
                          out_w: int = 1080, out_h: int = 1920) -> np.ndarray:
    """Render a single parallax frame by compositing depth layers.

    Args:
        layers: From depth.split_into_layers() — each has rgba, speed
        t: Time progress 0.0 to 1.0
        camera_x: Horizontal camera offset (-1 to 1, fraction of frame)
        camera_y: Vertical camera offset (-1 to 1, fraction of frame)
        camera_zoom: Zoom level (1.0 = normal)
        out_w, out_h: Output dimensions

    Returns:
        RGB numpy array
    """
    # Start with black background
    canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)

    for layer in layers:
        rgba = layer["rgba"]
        speed = layer["speed"]
        h, w = rgba.shape[:2]

        # Each layer moves at its own speed
        offset_x = int(camera_x * w * 0.1 * speed)
        offset_y = int(camera_y * h * 0.05 * speed)

        # Zoom: foreground zooms more than background
        layer_zoom = 1.0 + (camera_zoom - 1.0) * speed

        if layer_zoom != 1.0 or offset_x != 0 or offset_y != 0:
            # Calculate crop region
            crop_w = int(w / layer_zoom)
            crop_h = int(h / layer_zoom)
            cx = w // 2 + offset_x
            cy = h // 2 + offset_y

            x1 = max(0, min(cx - crop_w // 2, w - crop_w))
            y1 = max(0, min(cy - crop_h // 2, h - crop_h))

            crop = rgba[y1:y1+crop_h, x1:x1+crop_w]
            # Resize to output
            pil = Image.fromarray(crop).resize((out_w, out_h), Image.LANCZOS)
            layer_frame = np.array(pil)
        else:
            # Simple resize
            pil = Image.fromarray(rgba).resize((out_w, out_h), Image.LANCZOS)
            layer_frame = np.array(pil)

        # Alpha composite onto canvas
        alpha = layer_frame[:, :, 3:4].astype(np.float32) / 255.0
        rgb = layer_frame[:, :, :3].astype(np.float32)
        canvas_f = canvas.astype(np.float32)
        canvas = (rgb * alpha + canvas_f * (1.0 - alpha)).astype(np.uint8)

    return canvas
```

- [ ] **Step 2: Commit**

```bash
git add app/cin/parallax.py
git commit -m "feat: add 2.5D parallax compositor for depth layers"
```

---

## Task 4: Multi-Shot Editor

**Files:**
- Create: `app/cin/multishot.py`
- Create: `tests/test_cin_multishot.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_cin_multishot.py
"""Tests for multi-shot editor."""
import pytest
import numpy as np
from PIL import Image


def test_extract_shots():
    from app.cin.multishot import extract_shots
    img = np.random.randint(0, 255, (1920, 1080, 3), dtype=np.uint8)
    shots = extract_shots(img)
    assert len(shots) >= 3
    for shot in shots:
        assert "crop" in shot
        assert "type" in shot
        assert shot["crop"].shape[0] > 0 and shot["crop"].shape[1] > 0


def test_plan_cuts():
    from app.cin.multishot import plan_cuts
    emphasis = [0.5, 1.5, 3.0]
    scene_duration = 5.0
    cuts = plan_cuts(scene_duration, emphasis_points=emphasis)
    assert len(cuts) >= 2
    for cut in cuts:
        assert "time" in cut
        assert "shot_type" in cut
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_cin_multishot.py -v`
Expected: FAIL

- [ ] **Step 3: Implement multi-shot editor**

```python
# app/cin/multishot.py
"""Multi-shot editor — extracts multiple shots from a single image
and plans cuts synced to audio emphasis."""

import logging
import random

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Shot types with crop regions (relative to 1080x1920 image)
# Each is (x_frac, y_frac, w_frac, h_frac)
SHOT_DEFS = {
    "wide": (0.0, 0.0, 1.0, 1.0),                # Full frame
    "medium": (0.1, 0.05, 0.8, 0.65),             # Upper 65%, slight inset
    "close_up": (0.15, 0.15, 0.7, 0.5),           # Center 70x50%
    "detail_top": (0.1, 0.0, 0.6, 0.4),           # Top-left detail
    "detail_bottom": (0.2, 0.5, 0.7, 0.5),        # Bottom-right detail
    "ultra_close": (0.25, 0.25, 0.5, 0.35),       # Tight center crop
}


def extract_shots(img_arr: np.ndarray, out_w: int = 1080,
                  out_h: int = 1920) -> list[dict]:
    """Extract multiple shot framings from a single image.

    Returns list of {type, crop} where crop is a numpy array resized to out_w x out_h.
    """
    h, w = img_arr.shape[:2]
    shots = []

    for shot_type, (xf, yf, wf, hf) in SHOT_DEFS.items():
        x1 = int(w * xf)
        y1 = int(h * yf)
        cw = max(int(w * wf), 1)
        ch = max(int(h * hf), 1)
        x2 = min(x1 + cw, w)
        y2 = min(y1 + ch, h)

        crop = img_arr[y1:y2, x1:x2]
        # Resize to output maintaining aspect ratio then center-crop
        resized = np.array(Image.fromarray(crop).resize((out_w, out_h), Image.LANCZOS))

        shots.append({"type": shot_type, "crop": resized})

    return shots


def plan_cuts(scene_duration: float, emphasis_points: list[float] = None,
              min_shot_duration: float = 0.8) -> list[dict]:
    """Plan cut timing within a scene based on audio emphasis.

    Returns list of {time, shot_type, duration} defining when to cut and to what.
    """
    if not emphasis_points:
        emphasis_points = []

    cuts = []
    shot_types = list(SHOT_DEFS.keys())

    # Always start with wide shot
    cuts.append({"time": 0.0, "shot_type": "wide", "duration": 0.0})

    # Cut to closer shots on emphasis points
    close_shots = ["close_up", "detail_top", "detail_bottom", "medium", "ultra_close"]
    last_cut_time = 0.0

    for emp_time in emphasis_points:
        if emp_time < last_cut_time + min_shot_duration:
            continue
        if emp_time >= scene_duration - min_shot_duration:
            break

        shot = random.choice(close_shots)
        cuts.append({"time": emp_time, "shot_type": shot, "duration": 0.0})
        last_cut_time = emp_time

    # If no emphasis cuts happened, add periodic cuts for visual interest
    if len(cuts) == 1 and scene_duration > 2.0:
        interval = scene_duration / 3
        cuts.append({"time": interval, "shot_type": "medium", "duration": 0.0})
        if scene_duration > 4.0:
            cuts.append({"time": interval * 2, "shot_type": "close_up", "duration": 0.0})

    # Calculate durations
    for i in range(len(cuts)):
        if i + 1 < len(cuts):
            cuts[i]["duration"] = cuts[i + 1]["time"] - cuts[i]["time"]
        else:
            cuts[i]["duration"] = scene_duration - cuts[i]["time"]

    return cuts
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_cin_multishot.py -v`
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/cin/multishot.py tests/test_cin_multishot.py
git commit -m "feat: add multi-shot editor — extract shots from images, plan cuts from audio"
```

---

## Task 5: Particles System

**Files:**
- Create: `app/cin/particles.py`

- [ ] **Step 1: Implement particle renderer**

```python
# app/cin/particles.py
"""Atmospheric particle system — dust, embers, bokeh, snow.

Renders floating particles as a transparent RGBA overlay.
Each particle has position, size, opacity, and drift speed.
"""

import math
import random
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

PARTICLE_PRESETS = {
    "dust": {"count": 40, "size_range": (2, 6), "opacity_range": (30, 80),
             "color": (255, 255, 240), "speed": 0.3, "blur": 1},
    "embers": {"count": 25, "size_range": (3, 8), "opacity_range": (60, 160),
               "color": (255, 120, 30), "speed": 0.6, "blur": 2},
    "bokeh": {"count": 15, "size_range": (15, 40), "opacity_range": (20, 60),
              "color": (255, 255, 255), "speed": 0.15, "blur": 4},
    "snow": {"count": 60, "size_range": (3, 8), "opacity_range": (80, 180),
             "color": (230, 240, 255), "speed": 0.5, "blur": 1},
    "none": {"count": 0},
}

# Map video style to particle preset
STYLE_PARTICLES = {
    "photorealistic": "dust",
    "cartoon": "bokeh",
    "anime": "bokeh",
    "stop_motion": "dust",
    "comic_book": "none",
    "3d_render": "dust",
    "pixel_art": "none",
    "watercolor": "dust",
    "oil_painting": "dust",
    "noir": "dust",
}


class ParticleSystem:
    """Generates and renders floating atmospheric particles."""

    def __init__(self, preset: str = "dust", width: int = 1080, height: int = 1920,
                 seed: int = 42):
        self.width = width
        self.height = height
        self.config = PARTICLE_PRESETS.get(preset, PARTICLE_PRESETS["dust"])

        if self.config["count"] == 0:
            self.particles = []
            return

        random.seed(seed)
        self.particles = []
        for _ in range(self.config["count"]):
            self.particles.append({
                "x": random.uniform(0, width),
                "y": random.uniform(0, height),
                "size": random.uniform(*self.config["size_range"]),
                "opacity": random.randint(*self.config["opacity_range"]),
                "dx": random.uniform(-0.3, 0.3) * self.config["speed"],
                "dy": random.uniform(-0.5, -0.1) * self.config["speed"],  # drift up
                "phase": random.uniform(0, 2 * math.pi),  # for wobble
            })

    def render_frame(self, t: float) -> np.ndarray:
        """Render particle overlay for time t (seconds). Returns RGBA array."""
        img = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))

        if not self.particles:
            return np.array(img)

        draw = ImageDraw.Draw(img)
        color = self.config["color"]

        for p in self.particles:
            # Update position with time
            x = (p["x"] + p["dx"] * t * 60) % self.width
            y = (p["y"] + p["dy"] * t * 60) % self.height
            # Wobble
            x += math.sin(t * 2 + p["phase"]) * 3
            # Twinkle opacity
            opacity = int(p["opacity"] * (0.6 + 0.4 * math.sin(t * 3 + p["phase"])))
            opacity = max(0, min(255, opacity))

            r = p["size"]
            draw.ellipse([x - r, y - r, x + r, y + r],
                         fill=color + (opacity,))

        # Apply blur for softness
        blur_radius = self.config.get("blur", 1)
        if blur_radius > 0:
            img = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))

        return np.array(img)
```

- [ ] **Step 2: Commit**

```bash
git add app/cin/particles.py
git commit -m "feat: add atmospheric particle system — dust, embers, bokeh, snow"
```

---

## Task 6: Transitions Module

**Files:**
- Create: `app/cin/transitions.py`

- [ ] **Step 1: Implement transitions**

```python
# app/cin/transitions.py
"""Smart transitions between scenes — whip-pan, flash, zoom-through."""

import numpy as np
from PIL import Image, ImageFilter
import math


def whip_pan(frame_a: np.ndarray, frame_b: np.ndarray, t: float,
             direction: str = "right") -> np.ndarray:
    """Whip pan: horizontal motion blur transition. t goes 0→1."""
    h, w = frame_a.shape[:2]

    if t < 0.5:
        # First half: blur frame_a increasingly
        blur_amount = int(t * 2 * 80)  # up to 80px blur
        if blur_amount > 0:
            pil = Image.fromarray(frame_a)
            pil = pil.filter(ImageFilter.BoxBlur(blur_amount))
            return np.array(pil)
        return frame_a
    else:
        # Second half: deblur frame_b
        blur_amount = int((1.0 - t) * 2 * 80)
        if blur_amount > 0:
            pil = Image.fromarray(frame_b)
            pil = pil.filter(ImageFilter.BoxBlur(blur_amount))
            return np.array(pil)
        return frame_b


def flash_transition(frame_a: np.ndarray, frame_b: np.ndarray,
                     t: float) -> np.ndarray:
    """Brief white flash transition. t goes 0→1."""
    if t < 0.3:
        # Brighten frame_a
        brightness = t / 0.3
        white = np.full_like(frame_a, 255)
        return (frame_a.astype(float) * (1 - brightness) +
                white.astype(float) * brightness).astype(np.uint8)
    elif t < 0.5:
        return np.full_like(frame_a, 255)  # pure white
    else:
        # Fade in frame_b from white
        brightness = (1.0 - t) / 0.5
        white = np.full_like(frame_b, 255)
        return (frame_b.astype(float) * (1 - brightness) +
                white.astype(float) * brightness).astype(np.uint8)


def zoom_through(frame_a: np.ndarray, frame_b: np.ndarray,
                 t: float) -> np.ndarray:
    """Zoom into center of frame_a, emerge from frame_b. t goes 0→1."""
    h, w = frame_a.shape[:2]

    if t < 0.5:
        # Zoom into frame_a
        zoom = 1.0 + t * 6  # zoom up to 4x
        crop_w = max(int(w / zoom), 1)
        crop_h = max(int(h / zoom), 1)
        x1 = (w - crop_w) // 2
        y1 = (h - crop_h) // 2
        crop = frame_a[y1:y1+crop_h, x1:x1+crop_w]
        return np.array(Image.fromarray(crop).resize((w, h), Image.LANCZOS))
    else:
        # Zoom out from frame_b
        zoom = 1.0 + (1.0 - t) * 6
        crop_w = max(int(w / zoom), 1)
        crop_h = max(int(h / zoom), 1)
        x1 = (w - crop_w) // 2
        y1 = (h - crop_h) // 2
        crop = frame_b[y1:y1+crop_h, x1:x1+crop_w]
        return np.array(Image.fromarray(crop).resize((w, h), Image.LANCZOS))


TRANSITIONS = {
    "whip_pan": whip_pan,
    "flash": flash_transition,
    "zoom_through": zoom_through,
}
```

- [ ] **Step 2: Commit**

```bash
git add app/cin/transitions.py
git commit -m "feat: add smart transitions — whip-pan, flash, zoom-through"
```

---

## Task 7: Kinetic Typography

**Files:**
- Create: `app/cin/kinetic_text.py`

- [ ] **Step 1: Implement kinetic text renderer**

```python
# app/cin/kinetic_text.py
"""Kinetic typography — animated text for key moments.

Renders emphasis words with slam-in, scale-up, and pop effects
instead of static subtitles during high-energy moments.
"""

import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for name in ["Impact", "Arial-Bold", "/System/Library/Fonts/Helvetica.ttc"]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_slam_in(word: str, t: float, width: int = 1080, height: int = 1920,
                   color: tuple = (255, 255, 255)) -> np.ndarray:
    """Word slams in from large to normal size. t: 0→1 over ~0.3s.

    Returns RGBA numpy array.
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Slam: starts 3x size, settles to 1x with overshoot
    if t < 0.5:
        scale = 3.0 - t * 4.0  # 3.0 → 1.0
    else:
        # Slight bounce
        bounce = math.sin((t - 0.5) * math.pi * 2) * 0.15
        scale = 1.0 + bounce * (1.0 - t)

    scale = max(0.5, scale)
    font_size = int(120 * scale)
    font = _load_font(font_size)

    word_upper = word.upper()
    bbox = font.getbbox(word_upper)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    x = (width - tw) // 2
    y = height // 2 - th // 2

    # Opacity: fully visible from t=0.1
    opacity = min(255, int(t * 10 * 255))

    # Black stroke
    stroke_w = max(3, int(4 * scale))
    for dx in range(-stroke_w, stroke_w + 1):
        for dy in range(-stroke_w, stroke_w + 1):
            if dx * dx + dy * dy <= stroke_w * stroke_w:
                draw.text((x + dx, y + dy), word_upper, font=font,
                          fill=(0, 0, 0, opacity))

    draw.text((x, y), word_upper, font=font, fill=color + (opacity,))

    return np.array(img)


def render_pop(word: str, t: float, width: int = 1080, height: int = 1920,
               color: tuple = (255, 69, 0)) -> np.ndarray:
    """Word pops up with elastic bounce. t: 0→1 over ~0.4s."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Elastic ease-out
    if t < 0.01:
        scale = 0.0
    else:
        p = t
        scale = 1.0 + (2 ** (-10 * p)) * math.sin((p * 10 - 0.75) * (2 * math.pi / 3)) * -1
        scale = max(0.0, min(1.5, scale))

    if scale < 0.01:
        return np.array(img)

    font_size = int(100 * scale)
    font = _load_font(max(font_size, 10))

    word_upper = word.upper()
    bbox = font.getbbox(word_upper)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    x = (width - tw) // 2
    y = height // 2 - th // 2

    # Stroke
    for dx in range(-4, 5):
        for dy in range(-4, 5):
            if dx * dx + dy * dy <= 16:
                draw.text((x + dx, y + dy), word_upper, font=font, fill=(0, 0, 0, 255))

    draw.text((x, y), word_upper, font=font, fill=color + (255,))

    return np.array(img)
```

- [ ] **Step 2: Commit**

```bash
git add app/cin/kinetic_text.py
git commit -m "feat: add kinetic typography — slam-in and pop effects for emphasis words"
```

---

## Task 8: Cinematic Engine — Main Orchestrator

This is the big one. It wires everything together.

**Files:**
- Create: `app/cinematic.py`
- Create: `tests/test_cinematic.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_cinematic.py
"""Integration tests for CinematicEngine."""
import pytest
import numpy as np
from PIL import Image
from pathlib import Path


@pytest.fixture
def test_assets(tmp_path):
    """Create minimal test assets."""
    # Create 3 test images
    img_paths = []
    for i in range(3):
        path = str(tmp_path / f"scene_{i}.png")
        img = Image.fromarray(np.random.randint(50, 200, (1920, 1080, 3), dtype=np.uint8))
        img.save(path)
        img_paths.append(path)

    # Create test audio (simple WAV)
    import wave, struct
    sr = 16000
    samples = int(sr * 3.0)  # 3 seconds
    audio_data = [int(16000 * np.sin(2 * np.pi * 440 * i / sr)) for i in range(samples)]
    audio_path = str(tmp_path / "audio.wav")
    with wave.open(audio_path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"{samples}h", *audio_data))

    return {
        "images": img_paths,
        "audio": audio_path,
        "output_dir": str(tmp_path),
    }


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_cinematic.py -v`
Expected: FAIL

- [ ] **Step 3: Implement CinematicEngine**

```python
# app/cinematic.py
"""CinematicEngine — orchestrates depth parallax, multi-shot editing,
audio-reactive cuts, particles, transitions, and kinetic typography
into a professional-grade video assembly pipeline.
"""

import logging
import math
import os
import random
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image
from moviepy import (
    VideoClip, AudioFileClip, CompositeAudioClip,
    CompositeVideoClip, ImageClip, concatenate_videoclips,
)

from app.config import settings
from app.cin.audio_analysis import analyze_audio
from app.cin.depth import estimate_depth, split_into_layers, unload_depth_model
from app.cin.parallax import render_parallax_frame
from app.cin.multishot import extract_shots, plan_cuts
from app.cin.particles import ParticleSystem, STYLE_PARTICLES
from app.cin.transitions import TRANSITIONS
from app.subtitle_styles import SubtitleRenderer

logger = logging.getLogger(__name__)

FPS = 24
WIDTH = 1080
HEIGHT = 1920


class CinematicEngine:
    """Produces cinematic videos from images + audio using depth parallax,
    multi-shot editing, audio-reactive timing, and atmospheric effects."""

    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def render(
        self,
        audio_path: str,
        image_paths: list[str],
        output_filename: str,
        scene_texts: list[str] = None,
        subtitle_style: str = "bold_impact",
        video_style: str = "photorealistic",
        title: str = "",
        enable_music: bool = True,
        music_mood: str = "",
    ) -> str:
        """Render a cinematic video.

        Returns path to the output video file.
        """
        logger.info("=== Cinematic Engine: Starting render ===")

        # 1. Analyze audio
        logger.info("Analyzing audio...")
        audio_info = analyze_audio(audio_path)
        audio_duration = audio_info["duration"]

        # 2. Calculate scene durations from scene_texts
        scene_durations = self._calc_durations(audio_duration, scene_texts, len(image_paths))

        # 3. Extract depth maps and prepare layers for each image
        logger.info("Extracting depth maps...")
        scene_data = []
        for i, img_path in enumerate(image_paths):
            img = np.array(Image.open(img_path).convert("RGB").resize((WIDTH, HEIGHT), Image.LANCZOS))
            depth = estimate_depth(img_path)
            layers = split_into_layers(img, depth, num_layers=3)
            shots = extract_shots(img)

            # Plan cuts for this scene based on audio emphasis within scene time window
            scene_start = sum(scene_durations[:i])
            scene_end = scene_start + scene_durations[i]
            local_emphasis = [
                t - scene_start for t in audio_info["emphasis_points"]
                if scene_start <= t < scene_end
            ]
            cuts = plan_cuts(scene_durations[i], local_emphasis)

            scene_data.append({
                "image": img,
                "layers": layers,
                "shots": shots,
                "cuts": cuts,
                "duration": scene_durations[i],
                "start": scene_start,
            })

        unload_depth_model()
        logger.info("Depth processing complete for %d scenes", len(scene_data))

        # 4. Set up particle system
        particle_preset = STYLE_PARTICLES.get(video_style, "dust")
        particles = ParticleSystem(preset=particle_preset, width=WIDTH, height=HEIGHT)

        # 5. Render scene clips
        logger.info("Rendering cinematic scenes...")
        scene_clips = []
        for i, sd in enumerate(scene_data):
            logger.info("  Scene %d/%d (%.1fs, %d cuts)",
                        i + 1, len(scene_data), sd["duration"], len(sd["cuts"]))
            clip = self._render_scene(sd, audio_info, particles)
            scene_clips.append(clip)

        # 6. Apply transitions between scenes
        logger.info("Applying transitions...")
        final_clips = self._apply_transitions(scene_clips, scene_data)

        # 7. Combine into final video
        video = concatenate_videoclips(final_clips, method="compose")

        # Ensure video covers full audio duration
        if video.duration < audio_duration:
            gap = audio_duration - video.duration
            last_frame = scene_data[-1]["image"]
            ext = ImageClip(last_frame).with_duration(gap).with_fps(FPS)
            video = concatenate_videoclips([video, ext], method="compose")

        video = video.with_duration(audio_duration)

        # 8. Add title overlay
        if title:
            from app.video_editor import VideoEditor
            ve = VideoEditor()
            try:
                title_clip = ve._create_title_overlay(title, duration=4.0).with_start(0)
                video = CompositeVideoClip([video, title_clip], size=(WIDTH, HEIGHT))
                video = video.with_duration(audio_duration)
            except Exception as e:
                logger.warning("Title overlay failed: %s", e)

        # 9. Add subtitles
        logger.info("Adding subtitles...")
        try:
            from app.video_editor import VideoEditor
            ve = VideoEditor()
            segments = ve.generate_subtitles(audio_path)
            renderer = SubtitleRenderer(style=subtitle_style, width=WIDTH, height=HEIGHT)
            skip_time = 4.0 if title else 0.0
            sub_clips = ve._create_karaoke_clips(segments, renderer, skip_until=skip_time)
            if sub_clips:
                video = CompositeVideoClip([video] + sub_clips)
        except Exception as e:
            logger.warning("Subtitle generation failed: %s", e)

        # 10. Audio: load voice, add music
        voice = AudioFileClip(audio_path).with_volume_scaled(settings.voice_volume)
        audio_tracks = [voice]

        if enable_music and settings.music_enabled:
            from app.video_editor import VideoEditor
            ve = VideoEditor(music_mood=music_mood)
            music_path = ve._get_random_music_file(music_mood)
            if music_path:
                try:
                    mc = ve._prepare_background_music(music_path, audio_duration)
                    audio_tracks.append(mc)
                except Exception:
                    pass

        final_audio = CompositeAudioClip(audio_tracks) if len(audio_tracks) > 1 else audio_tracks[0]
        video = video.with_audio(final_audio)

        # 11. Write output
        output_path = str(self.output_dir / output_filename)
        logger.info("Writing cinematic video: %s", output_path)
        video.write_videofile(
            output_path,
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            logger=None,
        )

        logger.info("=== Cinematic Engine: Render complete ===")
        return output_path

    def _calc_durations(self, total: float, scene_texts: list[str],
                        num_scenes: int) -> list[float]:
        """Word-count proportional scene durations."""
        if scene_texts and len(scene_texts) == num_scenes:
            words = [max(len(t.split()), 1) for t in scene_texts]
            total_words = sum(words)
            return [total * w / total_words for w in words]
        return [total / num_scenes] * num_scenes

    def _render_scene(self, sd: dict, audio_info: dict,
                      particles: ParticleSystem) -> VideoClip:
        """Render a single scene with parallax + multi-shot cuts + particles."""
        duration = sd["duration"]
        layers = sd["layers"]
        shots = sd["shots"]
        cuts = sd["cuts"]
        scene_start = sd["start"]

        # Build shot lookup
        shot_map = {s["type"]: s["crop"] for s in shots}

        # Pre-decide camera motion for parallax
        cam_motion = random.choice(["drift_right", "drift_left", "drift_up", "push_in"])

        frames_cache = {}  # cache rendered frames to avoid recomputation

        def make_frame(t):
            # Determine active cut (which shot framing to use)
            active_cut = cuts[0]
            for cut in cuts:
                if t >= cut["time"]:
                    active_cut = cut

            shot_type = active_cut["shot_type"]

            # Camera motion for parallax
            progress = t / max(duration, 0.01)
            cam_x, cam_y, cam_zoom = self._camera_motion(progress, cam_motion, audio_info,
                                                          scene_start + t)

            # If this is a "wide" shot, use parallax depth layers
            if shot_type == "wide" or shot_type == "medium":
                frame = render_parallax_frame(
                    layers, progress,
                    camera_x=cam_x, camera_y=cam_y, camera_zoom=cam_zoom,
                    out_w=WIDTH, out_h=HEIGHT,
                )
            else:
                # For close-up/detail shots, use the cropped shot with subtle motion
                base = shot_map.get(shot_type, shot_map.get("wide", sd["image"]))
                # Apply subtle zoom on the crop
                zoom = 1.0 + progress * 0.1
                h, w = base.shape[:2]
                cw = int(w / zoom)
                ch = int(h / zoom)
                x1 = (w - cw) // 2 + int(cam_x * 20)
                y1 = (h - ch) // 2 + int(cam_y * 10)
                x1 = max(0, min(x1, w - cw))
                y1 = max(0, min(y1, h - ch))
                crop = base[y1:y1+ch, x1:x1+cw]
                frame = np.array(Image.fromarray(crop).resize((WIDTH, HEIGHT), Image.LANCZOS))

            # Overlay particles
            particle_frame = particles.render_frame(scene_start + t)
            if particle_frame.shape[2] == 4:
                alpha = particle_frame[:, :, 3:4].astype(np.float32) / 255.0
                rgb = particle_frame[:, :, :3].astype(np.float32)
                frame = (frame.astype(np.float32) * (1 - alpha) + rgb * alpha).astype(np.uint8)

            return frame

        clip = VideoClip(make_frame, duration=duration).with_fps(FPS)
        return clip

    def _camera_motion(self, progress: float, style: str,
                       audio_info: dict, global_time: float) -> tuple:
        """Calculate camera x, y, zoom based on motion style and audio energy."""
        # Base motion from style
        ease = 0.5 - 0.5 * math.cos(math.pi * progress)

        if style == "drift_right":
            base_x, base_y = ease * 2 - 1, math.sin(progress * math.pi) * 0.3
        elif style == "drift_left":
            base_x, base_y = -(ease * 2 - 1), math.sin(progress * math.pi) * 0.3
        elif style == "drift_up":
            base_x, base_y = math.sin(progress * math.pi) * 0.3, -(ease * 2 - 1) * 0.5
        else:  # push_in
            base_x, base_y = 0, 0

        base_zoom = 1.0 + ease * 0.2 if style == "push_in" else 1.0 + ease * 0.08

        # Audio reactivity: add punch on high energy
        energy = self._get_energy_at(audio_info, global_time)
        zoom_punch = energy * 0.05  # subtle zoom pulse on loud parts

        return base_x, base_y, base_zoom + zoom_punch

    def _get_energy_at(self, audio_info: dict, time: float) -> float:
        """Get audio energy at a specific time."""
        times = audio_info["times"]
        envelope = audio_info["energy_envelope"]
        if not times:
            return 0.5
        # Find closest time bin
        idx = min(int(time / max(times[1] - times[0], 0.001)), len(envelope) - 1)
        idx = max(0, idx)
        return envelope[idx]

    def _apply_transitions(self, clips: list, scene_data: list) -> list:
        """Apply smart transitions between scene clips."""
        if len(clips) <= 1:
            return clips

        transition_types = list(TRANSITIONS.keys())
        result = []
        trans_duration = 0.4  # 400ms transitions

        for i, clip in enumerate(clips):
            if i == 0:
                result.append(clip)
                continue

            # Pick transition (cycle through types for variety)
            trans_name = transition_types[i % len(transition_types)]
            trans_fn = TRANSITIONS[trans_name]

            # Get last frame of previous and first frame of current
            prev_clip = clips[i - 1]

            try:
                frame_a = prev_clip.get_frame(prev_clip.duration - 0.04)
                frame_b = clip.get_frame(0.04)

                def make_trans_frame(t, fa=frame_a, fb=frame_b, fn=trans_fn):
                    progress = t / trans_duration
                    return fn(fa, fb, min(progress, 1.0))

                trans_clip = VideoClip(make_trans_frame, duration=trans_duration).with_fps(FPS)

                # Trim transition duration from scene clips
                trimmed_prev = result[-1].with_duration(
                    max(result[-1].duration - trans_duration / 2, 0.5))
                result[-1] = trimmed_prev
                result.append(trans_clip)

                trimmed_curr = clip.subclipped(trans_duration / 2)
                result.append(trimmed_curr)
            except Exception as e:
                logger.warning("Transition %d failed (%s), using direct cut: %s", i, trans_name, e)
                result.append(clip)

        return result
```

- [ ] **Step 4: Run test**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_cinematic.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/cinematic.py tests/test_cinematic.py
git commit -m "feat: add CinematicEngine — depth parallax, multi-shot, audio-reactive, particles, transitions"
```

---

## Task 9: Wire CinematicEngine into Video Editor + Pipeline

**Files:**
- Modify: `app/video_editor.py`
- Modify: `main.py`
- Modify: `app/config.py`

- [ ] **Step 1: Add config setting**

In `app/config.py`, add after `video_duration`:

```python
    cinematic_enabled: bool = True          # Use cinematic engine (depth parallax, multi-shot, etc.)
```

- [ ] **Step 2: Update assemble_video to delegate to CinematicEngine**

In `app/video_editor.py`, modify `assemble_video()` — add `cinematic` and `video_style` params. At the top of the method body (after validation), add:

```python
        # Use Cinematic Engine if enabled
        if cinematic and settings.cinematic_enabled:
            try:
                from app.cinematic import CinematicEngine
                engine = CinematicEngine(output_dir=str(self.output_dir))
                return engine.render(
                    audio_path=audio_path,
                    image_paths=image_paths,
                    output_filename=output_filename,
                    scene_texts=scene_texts,
                    subtitle_style=subtitle_style,
                    video_style=video_style,
                    title=title or "",
                    enable_music=enable_music,
                    music_mood=self.music_mood,
                )
            except Exception as e:
                logger.warning("Cinematic engine failed, falling back to classic: %s", e)
```

Add `cinematic: bool = True` and `video_style: str = "photorealistic"` to the method signature.

- [ ] **Step 3: Update main.py run_pipeline to pass cinematic params**

In the `assemble_video()` call in `run_pipeline`, add:

```python
                cinematic=True,
                video_style=video_style,
```

Add `--classic` CLI flag that sets `cinematic=False`.

- [ ] **Step 4: Run full test suite**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add app/video_editor.py main.py app/config.py
git commit -m "feat: wire CinematicEngine into pipeline — cinematic mode on by default, --classic for old"
```

---

## Task 10: Install scipy + Integration Test

- [ ] **Step 1: Add scipy to requirements**

Append to requirements.txt: `scipy>=1.14.0`

- [ ] **Step 2: Install**

Run: `pip install scipy`

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/ -v`

- [ ] **Step 4: Manual end-to-end test**

```bash
./stop.sh && ./start.sh
```

Open http://localhost:8000, generate a video. Watch for cinematic engine logs:
```
=== Cinematic Engine: Starting render ===
Analyzing audio...
Extracting depth maps...
Rendering cinematic scenes...
Applying transitions...
Writing cinematic video...
=== Cinematic Engine: Render complete ===
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt
git commit -m "feat: add scipy dependency for audio analysis"
```
