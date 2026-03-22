# FVFactory v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform FVFactory into a professional-grade automated short-form video factory with Flux/Minimax on Replicate, karaoke subtitles, trend discovery, SFX, and CLI batch modes.

**Architecture:** The pipeline stays linear (Topic -> Script -> Assets -> Video) but each stage gains significant new capabilities. New modules are self-contained with clean interfaces. All external API calls go through Replicate (images/video) or direct REST (ElevenLabs/Reddit). Backward compatibility is maintained — v1 behavior works with no flags.

**Tech Stack:** Python 3.12, MoviePy 2.x, Replicate API (Flux, Minimax), ElevenLabs API, OpenAI API, Whisper (local), PIL/Pillow, Streamlit, pytrends, argparse

**Spec:** `docs/superpowers/specs/2026-03-21-fvfactory-v2-design.md`

---

## Phase 1: Foundation (Config + Cost Tracker + Dependencies)

These tasks have no dependencies and set up the foundation for everything else.

### Task 1: Update config.py with v2 settings

**Files:**
- Modify: `app/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write config test**

```python
# tests/test_config.py
from app.config import Settings

def test_v2_settings_have_defaults():
    """All v2 settings should have sensible defaults so v1 behavior is unchanged."""
    s = Settings(openai_api_key="test")
    # Replicate (already exists)
    assert s.replicate_api_token == ""
    # New v2 settings
    assert s.flux_model == "black-forest-labs/flux-1.1-pro"
    assert s.minimax_model == "minimax/image-to-video"
    assert s.elevenlabs_model == "eleven_multilingual_v2"
    assert s.elevenlabs_voice_id == "21m00Tcm4TlvDq8ikWAM"
    assert s.subtitle_style == "bold_impact"
    assert s.crossfade_duration == 0.8
    assert s.enable_sfx is True
    assert s.enable_motion is True
    assert s.enable_intro is False
    assert s.channel_name == ""
    assert s.logo_path == ""
    assert s.color_grade == ""
    assert s.niche == ""
    assert s.sfx_dir == "assets/sfx"
    assert s.max_parallel_workers == 3
    # Cost tracking defaults
    assert s.cost_flux_image == 0.03
    assert s.cost_minimax_video == 0.10
    assert s.cost_elevenlabs_per_1k_chars == 0.01
    assert s.cost_openai_gpt4o == 0.005
    assert s.cost_openai_tts_per_1k_chars == 0.015
    # Trend scout
    assert s.reddit_subreddits == "todayilearned,technology,science,explainlikeimfive"
    assert s.trend_count == 5

def test_v1_settings_unchanged():
    """Existing v1 settings must still work."""
    s = Settings(openai_api_key="test", elevenlabs_api_key="test2")
    assert s.openai_api_key == "test"
    assert s.elevenlabs_api_key == "test2"
    assert s.output_dir == "output"
    assert s.mascot_enabled is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_config.py -v`
Expected: FAIL — new attributes don't exist yet

- [ ] **Step 3: Add v2 settings to config.py**

Add these fields to the `Settings` class in `app/config.py` (after the existing fields):

```python
    # === V2 Settings ===

    # Replicate models
    flux_model: str = "black-forest-labs/flux-1.1-pro"
    minimax_model: str = "minimax/image-to-video"

    # ElevenLabs v2
    elevenlabs_model: str = "eleven_multilingual_v2"
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # Rachel

    # Subtitle styling
    subtitle_style: str = "bold_impact"

    # Transitions
    crossfade_duration: float = 0.8  # seconds

    # SFX
    enable_sfx: bool = True
    sfx_dir: str = "assets/sfx"

    # Motion clips
    enable_motion: bool = True

    # Intro/Outro
    enable_intro: bool = False
    channel_name: str = ""
    logo_path: str = ""

    # Color grading
    color_grade: str = ""  # niche name or empty for no grading
    niche: str = ""

    # Parallel generation
    max_parallel_workers: int = 3

    # Cost tracking (overridable via .env)
    cost_flux_image: float = 0.03
    cost_minimax_video: float = 0.10
    cost_elevenlabs_per_1k_chars: float = 0.01
    cost_openai_gpt4o: float = 0.005
    cost_openai_tts_per_1k_chars: float = 0.015

    # Trend Scout
    reddit_subreddits: str = "todayilearned,technology,science,explainlikeimfive"
    trend_count: int = 5
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add app/config.py tests/test_config.py
git commit -m "feat: add v2 config settings for Flux, Minimax, subtitles, SFX, pacing"
```

---

### Task 2: Create cost_tracker.py

**Files:**
- Create: `app/cost_tracker.py`
- Create: `tests/test_cost_tracker.py`

- [ ] **Step 1: Write cost tracker tests**

```python
# tests/test_cost_tracker.py
import json
import tempfile
from pathlib import Path

from app.cost_tracker import CostTracker


def test_log_single_cost():
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = CostTracker(output_dir=tmpdir)
        tracker.log_cost("video_001", "flux_image", quantity=5)
        data = tracker.get_video_cost("video_001")
        assert data == 0.15  # 5 * 0.03


def test_log_multiple_items():
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = CostTracker(output_dir=tmpdir)
        tracker.log_cost("video_001", "flux_image", quantity=5)
        tracker.log_cost("video_001", "openai_gpt4o", quantity=1)
        total = tracker.get_video_cost("video_001")
        assert abs(total - 0.155) < 0.001  # 0.15 + 0.005


def test_cost_log_persists_to_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = CostTracker(output_dir=tmpdir)
        tracker.log_cost("video_001", "flux_image", quantity=5)
        tracker.save()

        log_path = Path(tmpdir) / "cost_log.json"
        assert log_path.exists()

        with open(log_path) as f:
            data = json.load(f)
        assert "video_001" in data["videos"]


def test_get_total_costs():
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = CostTracker(output_dir=tmpdir)
        tracker.log_cost("video_001", "flux_image", quantity=5)
        tracker.log_cost("video_002", "flux_image", quantity=5)
        totals = tracker.get_total_costs()
        assert abs(totals["total"] - 0.30) < 0.001
        assert totals["video_count"] == 2


def test_unknown_cost_item_raises():
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = CostTracker(output_dir=tmpdir)
        try:
            tracker.log_cost("video_001", "nonexistent_service")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_cost_tracker.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement cost_tracker.py**

```python
# app/cost_tracker.py
"""Cost Tracker - Logs per-video API costs to output/cost_log.json"""

import json
import logging
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class CostTracker:
    """Tracks API costs per video and persists to JSON."""

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir or settings.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.output_dir / "cost_log.json"
        self._costs = self._load()

    @property
    def unit_costs(self) -> dict:
        return {
            "flux_image": settings.cost_flux_image,
            "minimax_video": settings.cost_minimax_video,
            "elevenlabs_tts": settings.cost_elevenlabs_per_1k_chars,
            "openai_gpt4o": settings.cost_openai_gpt4o,
            "openai_tts": settings.cost_openai_tts_per_1k_chars,
            "whisper": 0.00,
        }

    def _load(self) -> dict:
        if self.log_path.exists():
            with open(self.log_path) as f:
                return json.load(f)
        return {"schema_version": 1, "videos": {}}

    def log_cost(self, video_id: str, item: str, quantity: int = 1) -> None:
        if item not in self.unit_costs:
            raise ValueError(f"Unknown cost item: {item}. Valid: {list(self.unit_costs.keys())}")

        cost = self.unit_costs[item] * quantity

        if video_id not in self._costs["videos"]:
            self._costs["videos"][video_id] = {"items": [], "total": 0.0}

        self._costs["videos"][video_id]["items"].append({
            "item": item,
            "quantity": quantity,
            "unit_cost": self.unit_costs[item],
            "cost": round(cost, 4),
        })
        self._costs["videos"][video_id]["total"] = round(
            self._costs["videos"][video_id]["total"] + cost, 4
        )

        logger.debug(f"Cost: {item} x{quantity} = ${cost:.4f} (video: {video_id})")

    def get_video_cost(self, video_id: str) -> float:
        if video_id not in self._costs["videos"]:
            return 0.0
        return self._costs["videos"][video_id]["total"]

    def get_total_costs(self) -> dict:
        total = sum(v["total"] for v in self._costs["videos"].values())
        return {
            "total": round(total, 4),
            "video_count": len(self._costs["videos"]),
            "videos": {vid: v["total"] for vid, v in self._costs["videos"].items()},
        }

    def save(self) -> None:
        with open(self.log_path, "w") as f:
            json.dump(self._costs, f, indent=2)
        logger.info(f"Cost log saved to {self.log_path}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_cost_tracker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add app/cost_tracker.py tests/test_cost_tracker.py
git commit -m "feat: add cost tracker for per-video API spend logging"
```

---

### Task 3: Update requirements.txt

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Update requirements.txt**

Add `pytrends` to `requirements.txt`. All other deps are already present (`replicate`, `requests`, `Pillow`) or are stdlib (`concurrent.futures`, `argparse`).

Add this line to the end of `requirements.txt`:
```
pytrends
```

- [ ] **Step 2: Install dependencies**

Run: `cd /Users/moganes/Projects/FVFactory && pip install pytrends`

- [ ] **Step 3: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add requirements.txt
git commit -m "feat: add pytrends dependency for trend discovery"
```

---

## Phase 2: Content Intelligence (Trend Scout + Enhanced Content Engine)

### Task 4: Create trend_scout.py

**Files:**
- Create: `app/trend_scout.py`
- Create: `tests/test_trend_scout.py`

- [ ] **Step 1: Write trend scout tests**

```python
# tests/test_trend_scout.py
from unittest.mock import patch, MagicMock
from app.trend_scout import TrendScout, TrendTopic


def test_trend_topic_model():
    topic = TrendTopic(
        title="Bitcoin hits new high",
        source="reddit",
        score=100,
        url="https://reddit.com/r/technology/123",
    )
    assert topic.title == "Bitcoin hits new high"
    assert topic.source == "reddit"
    assert topic.score == 100


def test_fetch_reddit_hot_returns_topics():
    """Test Reddit fetch with mocked response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "Scientists discover new species",
                        "score": 5000,
                        "permalink": "/r/science/comments/abc/test",
                        "over_18": False,
                    }
                },
                {
                    "data": {
                        "title": "NSFW post",
                        "score": 3000,
                        "permalink": "/r/science/comments/def/nsfw",
                        "over_18": True,
                    }
                },
            ]
        }
    }

    with patch("app.trend_scout.requests.get", return_value=mock_response):
        scout = TrendScout()
        topics = scout._fetch_reddit_hot(["science"])
        assert len(topics) == 1  # NSFW filtered out
        assert topics[0].title == "Scientists discover new species"
        assert topics[0].source == "reddit"


def test_fetch_google_trends_graceful_failure():
    """pytrends failure should not raise, just return empty list."""
    with patch("app.trend_scout.TrendingSearches") as mock_ts:
        mock_ts.side_effect = Exception("pytrends broke")
        scout = TrendScout()
        topics = scout._fetch_google_trends()
        assert topics == []


def test_discover_topics_combines_sources():
    """discover_topics should merge Reddit + Google Trends results."""
    scout = TrendScout()
    reddit_topics = [
        TrendTopic(title="Topic A", source="reddit", score=100),
        TrendTopic(title="Topic B", source="reddit", score=50),
    ]
    google_topics = [
        TrendTopic(title="Topic C", source="google_trends", score=80),
    ]

    with patch.object(scout, "_fetch_reddit_hot", return_value=reddit_topics):
        with patch.object(scout, "_fetch_google_trends", return_value=google_topics):
            topics = scout.discover_topics(count=3)
            assert len(topics) == 3
            # Should be sorted by score descending
            assert topics[0].title == "Topic A"
            assert topics[1].title == "Topic C"
            assert topics[2].title == "Topic B"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_trend_scout.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement trend_scout.py**

```python
# app/trend_scout.py
"""Trend Scout - Discovers trending topics from Google Trends and Reddit"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import requests

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class TrendTopic:
    """A discovered trending topic."""
    title: str
    source: str  # "reddit" or "google_trends"
    score: int = 0
    url: str = ""


class TrendScout:
    """Discovers trending topics from multiple sources."""

    REDDIT_BASE = "https://www.reddit.com"
    USER_AGENT = "FVFactory/2.0"

    def discover_topics(self, niche: Optional[str] = None, count: int = 0) -> List[TrendTopic]:
        """
        Discover trending topics from Google Trends and Reddit.

        Args:
            niche: Optional niche filter (e.g., "tech", "science")
            count: Number of topics to return (0 = use config default)

        Returns:
            List of TrendTopic sorted by score descending
        """
        if count <= 0:
            count = settings.trend_count

        all_topics: List[TrendTopic] = []

        # Fetch from Google Trends (best-effort)
        google_topics = self._fetch_google_trends()
        all_topics.extend(google_topics)
        logger.info(f"Google Trends: {len(google_topics)} topics")

        # Fetch from Reddit
        subreddits = settings.reddit_subreddits.split(",")
        reddit_topics = self._fetch_reddit_hot(subreddits)
        all_topics.extend(reddit_topics)
        logger.info(f"Reddit: {len(reddit_topics)} topics")

        # Sort by score descending
        all_topics.sort(key=lambda t: t.score, reverse=True)

        # Return top N
        result = all_topics[:count]
        logger.info(f"Top {len(result)} trending topics discovered")
        return result

    def _fetch_google_trends(self) -> List[TrendTopic]:
        """Fetch trending searches from Google Trends. Never raises."""
        try:
            from pytrends.request import TrendReq
            from pytrends.dailydata import TrendingSearches

            pytrends = TrendReq(hl="en-US")
            trending = pytrends.trending_searches(pn="united_states")

            topics = []
            for i, row in trending.iterrows():
                title = str(row[0]).strip()
                if title:
                    topics.append(TrendTopic(
                        title=title,
                        source="google_trends",
                        score=max(100 - i * 5, 10),  # Rank-based score
                    ))

            return topics[:20]  # Cap at 20

        except Exception as e:
            logger.warning(f"Google Trends fetch failed (non-fatal): {e}")
            return []

    def _fetch_reddit_hot(self, subreddits: List[str]) -> List[TrendTopic]:
        """Fetch hot posts from Reddit. Filters NSFW."""
        topics: List[TrendTopic] = []

        for sub in subreddits:
            sub = sub.strip()
            if not sub:
                continue

            try:
                url = f"{self.REDDIT_BASE}/r/{sub}/hot.json?limit=10"
                response = requests.get(
                    url,
                    headers={"User-Agent": self.USER_AGENT},
                    timeout=10,
                )

                if response.status_code != 200:
                    logger.warning(f"Reddit r/{sub}: HTTP {response.status_code}")
                    continue

                data = response.json()
                children = data.get("data", {}).get("children", [])

                for child in children:
                    post = child.get("data", {})

                    # Skip NSFW
                    if post.get("over_18", False):
                        continue

                    title = post.get("title", "").strip()
                    if not title:
                        continue

                    topics.append(TrendTopic(
                        title=title,
                        source="reddit",
                        score=post.get("score", 0),
                        url=f"{self.REDDIT_BASE}{post.get('permalink', '')}",
                    ))

            except Exception as e:
                logger.warning(f"Reddit r/{sub} fetch failed: {e}")
                continue

        return topics
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_trend_scout.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add app/trend_scout.py tests/test_trend_scout.py
git commit -m "feat: add trend scout for auto topic discovery from Google Trends + Reddit"
```

---

### Task 5: Enhance content_engine.py with v2 script features

**Files:**
- Modify: `app/content_engine.py`
- Create: `tests/test_content_engine.py`

- [ ] **Step 1: Write tests for enhanced ScriptOutput and v2 prompt**

```python
# tests/test_content_engine.py
import json
from unittest.mock import patch, MagicMock

from app.content_engine import ScriptOutput, ScriptGenerator


def test_script_output_backward_compatible():
    """v1 fields only should still work — new fields have defaults."""
    script = ScriptOutput(
        hook="Did you know?",
        body="Some body text here.",
        image_prompts=["p1", "p2", "p3", "p4", "p5"],
        keywords=["test"],
    )
    assert script.hook == "Did you know?"
    assert script.motion_prompts == []
    assert script.pacing_hints == []
    assert script.hook_variants == []
    assert script.hook_viral_score == 0
    assert script.emoji_subtitles == []


def test_script_output_v2_fields():
    """v2 fields should be accepted when provided."""
    script = ScriptOutput(
        hook="Did you know?",
        hook_variants=["Alt 1", "Alt 2", "Alt 3"],
        hook_viral_score=8,
        body="Some body text here.",
        image_prompts=["p1", "p2", "p3", "p4", "p5"],
        motion_prompts=["zoom in", "pan left", "tilt up", "zoom out", "static"],
        pacing_hints=["fast", "normal", "slow", "dramatic_pause", "normal"],
        keywords=["test"],
        emoji_subtitles=["Did you know? 🤔", "Mind blown 🤯"],
    )
    assert len(script.motion_prompts) == 5
    assert len(script.pacing_hints) == 5
    assert script.hook_viral_score == 8


def test_v2_system_prompt_includes_motion():
    """When enable_motion=True, system prompt should request motion_prompts."""
    gen = ScriptGenerator.__new__(ScriptGenerator)
    gen.client = MagicMock()
    gen.model = "gpt-4o"

    prompt = gen._build_system_prompt(enable_v2=True)
    assert "motion_prompts" in prompt
    assert "pacing_hints" in prompt
    assert "hook_variants" in prompt
    assert "hook_viral_score" in prompt


def test_v1_system_prompt_no_motion():
    """When enable_v2=False, system prompt should NOT request motion_prompts."""
    gen = ScriptGenerator.__new__(ScriptGenerator)
    gen.client = MagicMock()
    gen.model = "gpt-4o"

    prompt = gen._build_system_prompt(enable_v2=False)
    assert "motion_prompts" not in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_content_engine.py -v`
Expected: FAIL — new fields and `enable_v2` param don't exist

- [ ] **Step 3: Update ScriptOutput model**

In `app/content_engine.py`, update the `ScriptOutput` class to add v2 fields with defaults:

```python
class ScriptOutput(BaseModel):
    """Validated output model for generated scripts"""

    hook: str = Field(..., description="First 3 seconds, very catchy opening line")
    body: str = Field(..., description="Main content, approximately 30-40 seconds reading time")
    image_prompts: List[str] = Field(
        ..., min_length=5, max_length=5,
        description="Exactly 5 distinct, highly visual descriptions for AI image generation"
    )
    keywords: List[str] = Field(..., min_length=1, description="Keywords for metadata and discoverability")

    # V2 fields (optional, backward compatible)
    hook_variants: List[str] = Field(default=[], description="3 alternative hook options")
    hook_viral_score: int = Field(default=0, description="1-10 scroll-stopping score for the hook")
    motion_prompts: List[str] = Field(default=[], description="5 camera/motion descriptions for image-to-video")
    pacing_hints: List[str] = Field(default=[], description="5 pacing values: fast, normal, slow, dramatic_pause")
    emoji_subtitles: List[str] = Field(default=[], description="Key phrases with contextual emojis for subtitles")

    @field_validator("image_prompts")
    @classmethod
    def validate_image_prompts_count(cls, v: List[str]) -> List[str]:
        if len(v) != 5:
            raise ValueError("Exactly 5 image prompts are required")
        return v
```

- [ ] **Step 4: Update _build_system_prompt to support v2**

Update `_build_system_prompt` method in `ScriptGenerator` to accept `enable_v2` parameter:

```python
    V2_INSTRUCTION = """

ADDITIONAL REQUIRED FIELDS:
- "hook_variants": 3 alternative hook options (list of strings)
- "hook_viral_score": Rate the main hook 1-10 on scroll-stopping potential
- "motion_prompts": Exactly 5 camera/motion descriptions for image-to-video generation.
  Each should describe how the camera moves or what animates in the scene.
  Examples: "slow zoom in on the subject, particles floating upward",
  "dramatic pan left revealing the landscape", "static shot with subtle parallax"
- "pacing_hints": Exactly 5 pacing values, one per scene. Use: "fast" for exciting moments,
  "normal" for standard pacing, "slow" for emotional moments, "dramatic_pause" for reveals.
- "emoji_subtitles": 3-5 key phrases from the script with contextual emojis added.
  Example: "Bitcoin crashed 📉😱", "Scientists discovered 🔬🧬"
"""

    def _build_system_prompt(self, enable_v2: bool = False) -> str:
        """Build the system prompt, optionally including mascot and v2 instructions."""
        prompt = self.BASE_SYSTEM_PROMPT

        if settings.mascot_enabled and settings.mascot_prompt:
            mascot_section = self.MASCOT_INSTRUCTION.format(
                mascot_prompt=settings.mascot_prompt
            )
            prompt += mascot_section

        if enable_v2:
            prompt += self.V2_INSTRUCTION

        return prompt
```

- [ ] **Step 5: Update generate_script to accept enable_v2**

Update `generate_script` method signature to pass `enable_v2` through:

```python
    def generate_script(self, topic: str, enable_v2: bool = False) -> ScriptOutput:
        # ... existing validation ...
        system_prompt = self._build_system_prompt(enable_v2=enable_v2)
        # ... rest is the same, Pydantic handles optional v2 fields via defaults ...
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_content_engine.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add app/content_engine.py tests/test_content_engine.py
git commit -m "feat: add v2 script fields (motion prompts, hook variants, viral score, pacing)"
```

---

## Phase 3: Asset Generation (Flux + Motion + Audio Upgrade)

### Task 6: Replace DALL-E with Flux in asset_manager.py

**Files:**
- Modify: `app/asset_manager.py`
- Create: `tests/test_asset_manager.py`

- [ ] **Step 1: Write Flux image generation tests**

```python
# tests/test_asset_manager.py
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.asset_manager import AssetManager


def test_generate_image_flux_downloads_to_path():
    """Flux generation should call Replicate and download the result."""
    mock_output = "https://replicate.delivery/fake/image.png"

    mock_img_response = MagicMock()
    mock_img_response.status_code = 200
    mock_img_response.content = b"fake_png_data"

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = AssetManager()
        manager.TEMP_DIR = Path(tmpdir)
        output_path = Path(tmpdir) / "test_image.png"

        with patch("app.asset_manager.replicate") as mock_replicate:
            mock_replicate.run.return_value = mock_output
            with patch("app.asset_manager.requests.get", return_value=mock_img_response):
                manager._generate_image_flux("a cute robot", output_path)

        assert output_path.exists()
        assert output_path.read_bytes() == b"fake_png_data"

        # Verify Replicate was called with correct model
        mock_replicate.run.assert_called_once()
        call_args = mock_replicate.run.call_args
        assert "flux" in call_args[0][0].lower()


def test_generate_images_uses_flux_not_dalle():
    """When use_mock=False, Flux should be used (not DALL-E)."""
    manager = AssetManager()

    with patch.object(manager, "_generate_image_flux") as mock_flux:
        with patch.object(manager, "_generate_image_dalle") as mock_dalle:
            with tempfile.TemporaryDirectory() as tmpdir:
                manager.TEMP_DIR = Path(tmpdir)
                manager.generate_images(["prompt1"], use_mock=False)

            mock_flux.assert_called_once()
            mock_dalle.assert_not_called()


def test_generate_images_parallel():
    """Multiple images should be generated in parallel."""
    manager = AssetManager()

    call_count = 0
    def mock_flux(prompt, output_path):
        nonlocal call_count
        call_count += 1
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake")

    with patch.object(manager, "_generate_image_flux", side_effect=mock_flux):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager.TEMP_DIR = Path(tmpdir)
            paths = manager.generate_images(
                ["p1", "p2", "p3", "p4", "p5"],
                use_mock=False,
            )

    assert call_count == 5
    assert len(paths) == 5


def test_generate_images_mock_still_works():
    """Mock images should still work for testing."""
    manager = AssetManager()
    with tempfile.TemporaryDirectory() as tmpdir:
        manager.TEMP_DIR = Path(tmpdir)
        paths = manager.generate_images(["prompt1", "prompt2", "prompt3", "prompt4", "prompt5"])
        assert len(paths) == 5
        for p in paths:
            assert Path(p).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_asset_manager.py -v`
Expected: FAIL — `_generate_image_flux` doesn't exist, `replicate` not imported

- [ ] **Step 3: Add Flux image generation and parallel support to asset_manager.py**

At the top of `app/asset_manager.py`, add the `replicate` import:
```python
import replicate
from concurrent.futures import ThreadPoolExecutor
```

Replace `_generate_image_dalle` with `_generate_image_flux`:

```python
    def _generate_image_flux(self, prompt: str, output_path: Path) -> None:
        """Generate image using Flux 1.1 Pro on Replicate."""
        enhanced_prompt = (
            f"{self._enhance_prompt_with_style(prompt)}. "
            "Vertical composition suitable for TikTok/Shorts (9:16 aspect ratio). "
            "High quality, consistent lighting."
        )

        logger.info(f"Flux prompt: {enhanced_prompt[:100]}...")

        output = replicate.run(
            settings.flux_model,
            input={
                "prompt": enhanced_prompt,
                "aspect_ratio": "9:16",
                "output_format": "png",
                "safety_tolerance": 2,
            }
        )

        # Output is a URL or FileOutput — download it
        image_url = str(output[0]) if isinstance(output, list) else str(output)
        img_response = requests.get(image_url)
        if img_response.status_code != 200:
            raise AssetManagerError(f"Failed to download Flux image: {img_response.status_code}")

        with open(output_path, "wb") as f:
            f.write(img_response.content)
```

Update `generate_images` to use Flux and parallel execution:

```python
    def generate_images(
        self,
        prompts: List[str],
        use_mock: bool = True
    ) -> List[str]:
        if not prompts:
            raise AssetManagerError("Prompts list cannot be empty")

        file_paths = [""] * len(prompts)

        if use_mock:
            # Sequential mock generation (fast, no API calls)
            for i, prompt in enumerate(prompts):
                output_path = self.TEMP_DIR / f"image_{i}.png"
                styled_prompt = self._enhance_prompt_with_style(prompt)
                self._generate_mock_image(styled_prompt, output_path, i)
                file_paths[i] = str(output_path)
        else:
            # Parallel Flux generation
            def generate_one(args):
                i, prompt = args
                output_path = self.TEMP_DIR / f"image_{i}.png"
                styled_prompt = self._enhance_prompt_with_style(prompt)
                self._generate_image_flux(styled_prompt, output_path)
                return i, str(output_path)

            with ThreadPoolExecutor(max_workers=settings.max_parallel_workers) as executor:
                results = executor.map(generate_one, enumerate(prompts))
                for i, path in results:
                    file_paths[i] = path

        return file_paths
```

Remove the `_generate_image_dalle` method entirely.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_asset_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add app/asset_manager.py tests/test_asset_manager.py
git commit -m "feat: replace DALL-E with Flux on Replicate, add parallel image generation"
```

---

### Task 7: Upgrade ElevenLabs to Multilingual v2

**Files:**
- Modify: `app/asset_manager.py`

- [ ] **Step 1: Write test for ElevenLabs v2 model**

Append to `tests/test_asset_manager.py`:

```python
def test_elevenlabs_uses_v2_model():
    """ElevenLabs should use eleven_multilingual_v2 model."""
    from app.config import settings
    manager = AssetManager()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"fake_audio_data"

    with patch("app.asset_manager.requests.post", return_value=mock_response) as mock_post:
        with patch.object(manager, "_get_audio_duration", return_value=10.0):
            with tempfile.TemporaryDirectory() as tmpdir:
                manager.TEMP_DIR = Path(tmpdir)
                settings.elevenlabs_api_key = "fake_key"
                try:
                    manager.generate_audio("Hello world")
                finally:
                    settings.elevenlabs_api_key = ""

    # Check the payload used the v2 model
    call_kwargs = mock_post.call_args
    payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs.kwargs.get("json")
    assert payload["model_id"] == "eleven_multilingual_v2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_asset_manager.py::test_elevenlabs_uses_v2_model -v`
Expected: FAIL — still uses `eleven_monolingual_v1`

- [ ] **Step 3: Update ElevenLabs model and voice ID to use config**

In `app/asset_manager.py`, update `_generate_audio_elevenlabs`:

```python
    def _generate_audio_elevenlabs(
        self, text: str, voice_id: str, output_path: Path
    ) -> AudioResult:
        """Generate audio using ElevenLabs API"""
        url = f"{self.ELEVENLABS_API_URL}/{voice_id}"

        headers = {
            "xi-api-key": settings.elevenlabs_api_key,
            "Content-Type": "application/json"
        }

        payload = {
            "text": text,
            "model_id": settings.elevenlabs_model,  # Changed from hardcoded
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }
        # ... rest unchanged ...
```

Also update `generate_audio` to use config voice ID:

```python
    def generate_audio(self, text: str, voice_id: Optional[str] = None) -> AudioResult:
        # ...
        if settings.elevenlabs_api_key:
            try:
                return self._generate_audio_elevenlabs(
                    text, voice_id or settings.elevenlabs_voice_id, output_path
                )
        # ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_asset_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add app/asset_manager.py tests/test_asset_manager.py
git commit -m "feat: upgrade ElevenLabs to Multilingual v2, configurable voice ID"
```

---

### Task 8: Create motion_gen.py (Minimax image-to-video)

**Files:**
- Create: `app/motion_gen.py`
- Create: `tests/test_motion_gen.py`

- [ ] **Step 1: Write motion generator tests**

```python
# tests/test_motion_gen.py
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.motion_gen import MotionGenerator


def test_generate_motion_clip():
    """Should call Replicate Minimax and download result."""
    mock_output = MagicMock()
    mock_output.output.url = "https://replicate.delivery/fake/video.mp4"

    mock_video_response = MagicMock()
    mock_video_response.status_code = 200
    mock_video_response.iter_content = lambda chunk_size: [b"fake_video_data"]

    with tempfile.TemporaryDirectory() as tmpdir:
        gen = MotionGenerator(temp_dir=tmpdir)

        # Create a fake input image
        fake_image = Path(tmpdir) / "input.png"
        fake_image.write_bytes(b"fake_png")

        with patch("app.motion_gen.replicate") as mock_replicate:
            mock_replicate.run.return_value = mock_output
            with patch("app.motion_gen.requests.get", return_value=mock_video_response):
                result = gen.generate_motion_clip(str(fake_image), "slow zoom in")

        assert result is not None
        assert Path(result).suffix == ".mp4"


def test_generate_motion_clip_failure_returns_none():
    """On failure, should return None (caller falls back to Ken Burns)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gen = MotionGenerator(temp_dir=tmpdir)

        fake_image = Path(tmpdir) / "input.png"
        fake_image.write_bytes(b"fake_png")

        with patch("app.motion_gen.replicate") as mock_replicate:
            mock_replicate.run.side_effect = Exception("API error")
            result = gen.generate_motion_clip(str(fake_image), "zoom in")

        assert result is None


def test_generate_all_clips_partial_failure():
    """If some clips fail, those should be None (Ken Burns fallback)."""
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
                return None  # Simulate failure
            clip_path = Path(tmpdir) / f"clip_{call_count}.mp4"
            clip_path.write_bytes(b"fake_mp4")
            return str(clip_path)

        with patch.object(gen, "generate_motion_clip", side_effect=mock_generate):
            results = gen.generate_all_clips(images, ["zoom", "pan", "tilt"])

        assert len(results) == 3
        assert results[1] is None  # Failed clip
        assert results[0] is not None
        assert results[2] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_motion_gen.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement motion_gen.py**

```python
# app/motion_gen.py
"""Motion Generator - Minimax image-to-video via Replicate"""

import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

import replicate
import requests

from app.config import settings

logger = logging.getLogger(__name__)


class MotionGenerator:
    """Generates motion clips from static images using Minimax on Replicate."""

    def __init__(self, temp_dir: Optional[str] = None):
        self.temp_dir = Path(temp_dir or "assets/temp")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def generate_motion_clip(
        self, image_path: str, motion_prompt: str, index: int = 0
    ) -> Optional[str]:
        """
        Generate a 5s motion clip from a static image.

        Returns path to the clip, or None on failure (caller should use Ken Burns fallback).
        """
        try:
            logger.info(f"Generating motion clip {index}: {motion_prompt[:50]}...")

            # Read image as file for Replicate
            with open(image_path, "rb") as img_file:
                output = replicate.run(
                    settings.minimax_model,
                    input={
                        "image": img_file,
                        "prompt": motion_prompt,
                    }
                )

            # Extract video URL from output
            if hasattr(output, "output") and hasattr(output.output, "url"):
                video_url = output.output.url
            elif isinstance(output, str):
                video_url = output
            else:
                video_url = str(output)

            # Download the video
            output_path = self.temp_dir / f"motion_{index}.mp4"
            response = requests.get(video_url, stream=True, timeout=120)

            if response.status_code != 200:
                logger.warning(f"Motion clip {index}: download failed ({response.status_code})")
                return None

            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"Motion clip {index} saved: {output_path}")
            return str(output_path)

        except Exception as e:
            logger.warning(f"Motion clip {index} generation failed (non-fatal): {e}")
            return None

    def generate_all_clips(
        self, image_paths: List[str], motion_prompts: List[str]
    ) -> List[Optional[str]]:
        """
        Generate motion clips for all images in parallel.

        Returns list of clip paths (None entries mean failure — use Ken Burns for those).
        """
        if len(image_paths) != len(motion_prompts):
            raise ValueError("image_paths and motion_prompts must have same length")

        results: List[Optional[str]] = [None] * len(image_paths)

        def generate_one(args):
            i, (img, prompt) = args
            return i, self.generate_motion_clip(img, prompt, index=i)

        with ThreadPoolExecutor(max_workers=settings.max_parallel_workers) as executor:
            for i, clip_path in executor.map(generate_one, enumerate(zip(image_paths, motion_prompts))):
                results[i] = clip_path

        success = sum(1 for r in results if r is not None)
        logger.info(f"Motion clips: {success}/{len(results)} generated successfully")
        return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_motion_gen.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add app/motion_gen.py tests/test_motion_gen.py
git commit -m "feat: add Minimax image-to-video motion clip generator"
```

---

## Phase 4: Video Production Quality (Subtitles + SFX + Transitions + Pacing)

### Task 9: Create subtitle_styles.py (karaoke renderer)

**Files:**
- Create: `app/subtitle_styles.py`
- Create: `tests/test_subtitle_styles.py`

- [ ] **Step 1: Write subtitle style tests**

```python
# tests/test_subtitle_styles.py
import numpy as np
from app.subtitle_styles import SubtitleRenderer, SUBTITLE_PRESETS


def test_presets_exist():
    assert "bold_impact" in SUBTITLE_PRESETS
    assert "clean_minimal" in SUBTITLE_PRESETS
    assert "neon_glow" in SUBTITLE_PRESETS
    assert "fire" in SUBTITLE_PRESETS


def test_preset_has_required_keys():
    for name, preset in SUBTITLE_PRESETS.items():
        assert "active_color" in preset, f"{name} missing active_color"
        assert "inactive_color" in preset, f"{name} missing inactive_color"
        assert "font_size" in preset, f"{name} missing font_size"
        assert "position" in preset, f"{name} missing position"


def test_render_subtitle_frame_returns_rgba():
    """Render should return an RGBA numpy array."""
    renderer = SubtitleRenderer(style="bold_impact", width=1080, height=1920)
    frame = renderer.render_subtitle_frame(
        words=["Hello", "world", "test"],
        active_index=1,
    )
    assert isinstance(frame, np.ndarray)
    assert frame.shape[2] == 4  # RGBA
    assert frame.shape[1] == 1080
    # Height should be reasonable (not full screen)
    assert frame.shape[0] < 400


def test_render_subtitle_frame_different_styles():
    """All presets should render without error."""
    for style_name in SUBTITLE_PRESETS:
        renderer = SubtitleRenderer(style=style_name, width=1080, height=1920)
        frame = renderer.render_subtitle_frame(
            words=["Hello", "world"],
            active_index=0,
        )
        assert isinstance(frame, np.ndarray)


def test_unknown_style_defaults_to_bold_impact():
    renderer = SubtitleRenderer(style="nonexistent", width=1080, height=1920)
    assert renderer.preset == SUBTITLE_PRESETS["bold_impact"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_subtitle_styles.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement subtitle_styles.py**

```python
# app/subtitle_styles.py
"""Karaoke-style subtitle renderer with multiple style presets."""

import logging
from typing import List, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


SUBTITLE_PRESETS = {
    "bold_impact": {
        "active_color": "#FFFF00",
        "inactive_color": "#FFFFFF80",
        "font": "Arial-Bold",
        "font_size": 75,
        "active_scale": 1.15,
        "stroke_color": "#000000",
        "stroke_width": 4,
        "position": "bottom",
        "bg_box": False,
    },
    "clean_minimal": {
        "active_color": "#FFFFFF",
        "inactive_color": "#FFFFFF60",
        "font": "Helvetica",
        "font_size": 60,
        "active_scale": 1.0,
        "stroke_color": None,
        "stroke_width": 0,
        "position": "center",
        "bg_box": True,
        "bg_color": "#00000080",
    },
    "neon_glow": {
        "active_color": "#00FF88",
        "inactive_color": "#FFFFFF40",
        "font": "Arial-Bold",
        "font_size": 70,
        "active_scale": 1.2,
        "stroke_color": "#00FF88",
        "stroke_width": 2,
        "position": "bottom",
        "bg_box": False,
    },
    "fire": {
        "active_color": "#FF4500",
        "inactive_color": "#FFD70080",
        "font": "Impact",
        "font_size": 80,
        "active_scale": 1.25,
        "stroke_color": "#000000",
        "stroke_width": 5,
        "position": "bottom",
        "bg_box": False,
    },
}


def _hex_to_rgba(hex_color: str) -> tuple:
    """Convert hex color (with optional alpha) to RGBA tuple."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        r, g, b = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        return (r, g, b, 255)
    elif len(hex_color) == 8:
        r, g, b, a = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16), int(hex_color[6:8], 16)
        return (r, g, b, a)
    return (255, 255, 255, 255)


class SubtitleRenderer:
    """Renders karaoke-style subtitle frames using PIL."""

    PADDING = 40
    LINE_HEIGHT_MULTIPLIER = 1.3

    def __init__(self, style: str = "bold_impact", width: int = 1080, height: int = 1920):
        self.width = width
        self.height = height

        if style not in SUBTITLE_PRESETS:
            logger.warning(f"Unknown subtitle style '{style}', using 'bold_impact'")
            style = "bold_impact"
        self.preset = SUBTITLE_PRESETS[style]

        # Load fonts
        self._font = self._load_font(self.preset["font"], self.preset["font_size"])
        active_size = int(self.preset["font_size"] * self.preset.get("active_scale", 1.0))
        self._active_font = self._load_font(self.preset["font"], active_size)

    def _load_font(self, font_name: str, size: int) -> ImageFont.FreeTypeFont:
        """Load a font, falling back to default if not found."""
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            try:
                # Try common paths
                for path in ["/System/Library/Fonts/Helvetica.ttc",
                             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                             "arial.ttf"]:
                    try:
                        return ImageFont.truetype(path, size)
                    except OSError:
                        continue
            except Exception:
                pass
            return ImageFont.load_default()

    def render_subtitle_frame(
        self, words: List[str], active_index: int
    ) -> np.ndarray:
        """
        Render a subtitle frame with karaoke highlighting.

        Args:
            words: List of words to display
            active_index: Index of the currently active (highlighted) word

        Returns:
            RGBA numpy array suitable for compositing over video
        """
        active_color = _hex_to_rgba(self.preset["active_color"])
        inactive_color = _hex_to_rgba(self.preset["inactive_color"])
        stroke_color = _hex_to_rgba(self.preset["stroke_color"]) if self.preset.get("stroke_color") else None
        stroke_width = self.preset.get("stroke_width", 0)

        # Calculate total text width to center it
        text_parts = []
        total_width = 0
        max_height = 0

        for i, word in enumerate(words):
            font = self._active_font if i == active_index else self._font
            word_upper = word.upper()
            bbox = font.getbbox(word_upper)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            space_w = font.getbbox(" ")[2] if i < len(words) - 1 else 0
            text_parts.append({
                "text": word_upper,
                "font": font,
                "width": w,
                "height": h,
                "color": active_color if i == active_index else inactive_color,
                "is_active": i == active_index,
            })
            total_width += w + space_w
            max_height = max(max_height, h)

        # Create transparent image for the subtitle bar
        bar_height = max_height + self.PADDING * 2
        img = Image.new("RGBA", (self.width, bar_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Optional background box
        if self.preset.get("bg_box"):
            bg_color = _hex_to_rgba(self.preset.get("bg_color", "#00000080"))
            margin = 20
            box_x1 = (self.width - total_width) // 2 - margin
            box_x2 = (self.width + total_width) // 2 + margin
            draw.rounded_rectangle(
                [box_x1, self.PADDING // 2, box_x2, bar_height - self.PADDING // 2],
                radius=10,
                fill=bg_color,
            )

        # Draw each word
        x = (self.width - total_width) // 2
        y = self.PADDING

        for part in text_parts:
            # Draw stroke/outline
            if stroke_color and stroke_width > 0:
                for dx in range(-stroke_width, stroke_width + 1):
                    for dy in range(-stroke_width, stroke_width + 1):
                        if dx * dx + dy * dy <= stroke_width * stroke_width:
                            draw.text((x + dx, y + dy), part["text"],
                                      font=part["font"], fill=stroke_color[:3] + (stroke_color[3],))

            # Draw the word
            draw.text((x, y), part["text"], font=part["font"], fill=part["color"])

            # Advance x
            space_w = part["font"].getbbox(" ")[2] if part != text_parts[-1] else 0
            x += part["width"] + space_w

        return np.array(img)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_subtitle_styles.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add app/subtitle_styles.py tests/test_subtitle_styles.py
git commit -m "feat: add karaoke subtitle renderer with 4 style presets"
```

---

### Task 10: Create sfx.py (sound effects mixer)

**Files:**
- Create: `app/sfx.py`
- Create: `tests/test_sfx.py`
- Create: `assets/sfx/.gitkeep`

- [ ] **Step 1: Write SFX mixer tests**

```python
# tests/test_sfx.py
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.sfx import SFXMixer


def test_sfx_mixer_init():
    mixer = SFXMixer()
    assert mixer.sfx_dir is not None


def test_build_sfx_track_with_no_sfx_files():
    """If no SFX files exist, should return None gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mixer = SFXMixer(sfx_dir=tmpdir)
        result = mixer.build_sfx_track(
            scene_timestamps=[0.0, 8.0, 16.0, 24.0, 32.0],
            total_duration=40.0,
        )
        assert result is None


def test_get_scene_transition_times():
    """Should calculate correct transition timestamps."""
    mixer = SFXMixer()
    timestamps = [0.0, 8.0, 16.0, 24.0, 32.0]
    transitions = mixer._get_transition_times(timestamps)
    # Transitions happen at scene boundaries (not at 0)
    assert transitions == [8.0, 16.0, 24.0, 32.0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_sfx.py -v`
Expected: FAIL — module does not exist

- [ ] **Step 3: Implement sfx.py**

```python
# app/sfx.py
"""Sound Effects Mixer - Adds whoosh, riser, and impact SFX to videos"""

import logging
from pathlib import Path
from typing import List, Optional

from moviepy import AudioFileClip, CompositeAudioClip, concatenate_audioclips

from app.config import settings

logger = logging.getLogger(__name__)


class SFXMixer:
    """Builds a composite SFX audio track synced to scene transitions."""

    # SFX file names (expected in sfx_dir)
    SFX_FILES = {
        "whoosh": "whoosh.mp3",
        "riser": "riser.mp3",
        "impact": "impact.mp3",
    }

    # Volume levels for each SFX type
    SFX_VOLUMES = {
        "whoosh": 0.3,
        "riser": 0.2,
        "impact": 0.4,
    }

    def __init__(self, sfx_dir: Optional[str] = None):
        self.sfx_dir = Path(sfx_dir or settings.sfx_dir)

    def _load_sfx(self, sfx_type: str) -> Optional[AudioFileClip]:
        """Load an SFX file by type. Returns None if not found."""
        filename = self.SFX_FILES.get(sfx_type)
        if not filename:
            return None

        path = self.sfx_dir / filename
        if not path.exists():
            logger.debug(f"SFX file not found: {path}")
            return None

        try:
            clip = AudioFileClip(str(path))
            volume = self.SFX_VOLUMES.get(sfx_type, 0.3)
            return clip.with_volume_scaled(volume)
        except Exception as e:
            logger.warning(f"Failed to load SFX {sfx_type}: {e}")
            return None

    def _get_transition_times(self, scene_timestamps: List[float]) -> List[float]:
        """Get transition timestamps (all scene starts except the first)."""
        return scene_timestamps[1:] if len(scene_timestamps) > 1 else []

    def build_sfx_track(
        self,
        scene_timestamps: List[float],
        total_duration: float,
    ) -> Optional[AudioFileClip]:
        """
        Build composite SFX track synced to scene timing.

        Placement:
        - Riser at 0.0s (before hook)
        - Impact at 0.5s (hook delivery)
        - Whoosh at each scene transition

        Returns None if no SFX files are available.
        """
        clips = []

        # Load available SFX
        whoosh = self._load_sfx("whoosh")
        riser = self._load_sfx("riser")
        impact = self._load_sfx("impact")

        if not any([whoosh, riser, impact]):
            logger.info("No SFX files available, skipping SFX track")
            return None

        # Riser at start (before hook)
        if riser:
            clips.append(riser.with_start(0.0))

        # Impact at 0.5s (hook delivery)
        if impact:
            clips.append(impact.with_start(0.5))

        # Whoosh at each scene transition
        if whoosh:
            transitions = self._get_transition_times(scene_timestamps)
            for t in transitions:
                # Start whoosh slightly before the transition
                whoosh_start = max(0, t - 0.3)
                clips.append(whoosh.with_start(whoosh_start))

        if not clips:
            return None

        try:
            composite = CompositeAudioClip(clips)
            # Ensure it matches total duration
            if composite.duration and composite.duration > total_duration:
                composite = composite.with_duration(total_duration)
            return composite
        except Exception as e:
            logger.warning(f"Failed to build SFX track: {e}")
            return None
```

- [ ] **Step 4: Create sfx assets directory**

```bash
mkdir -p /Users/moganes/Projects/FVFactory/assets/sfx
touch /Users/moganes/Projects/FVFactory/assets/sfx/.gitkeep
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_sfx.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add app/sfx.py tests/test_sfx.py assets/sfx/.gitkeep
git commit -m "feat: add SFX mixer for whoosh transitions, riser, and impact sounds"
```

---

### Task 11: Upgrade video_editor.py with v2 features

This is the largest task — it integrates karaoke subtitles, cross-fades, dynamic pacing, color grading, SFX, and motion clips into the video assembly pipeline.

**Files:**
- Modify: `app/video_editor.py`
- Create: `tests/test_video_editor.py`

- [ ] **Step 1: Write tests for dynamic pacing**

```python
# tests/test_video_editor.py
from app.video_editor import VideoEditor


def test_calculate_paced_durations_equal():
    """No pacing hints = equal durations."""
    editor = VideoEditor()
    durations = editor._calculate_paced_durations(40.0, 5, pacing_hints=None)
    assert len(durations) == 5
    assert all(abs(d - 8.0) < 0.01 for d in durations)


def test_calculate_paced_durations_weighted():
    """Pacing hints should adjust durations proportionally."""
    editor = VideoEditor()
    hints = ["fast", "normal", "slow", "dramatic_pause", "normal"]
    durations = editor._calculate_paced_durations(40.0, 5, pacing_hints=hints)
    assert len(durations) == 5
    assert abs(sum(durations) - 40.0) < 0.01  # Must sum to total
    # Fast should be shortest, dramatic_pause should be longest
    assert durations[0] < durations[1]  # fast < normal
    assert durations[3] > durations[2]  # dramatic_pause > slow


def test_calculate_paced_durations_unknown_hint():
    """Unknown pacing hints should default to 'normal'."""
    editor = VideoEditor()
    hints = ["unknown", "normal", "normal", "normal", "normal"]
    durations = editor._calculate_paced_durations(40.0, 5, pacing_hints=hints)
    assert len(durations) == 5
    assert abs(sum(durations) - 40.0) < 0.01
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_video_editor.py -v`
Expected: FAIL — `_calculate_paced_durations` doesn't exist

- [ ] **Step 3: Add pacing calculation to video_editor.py**

Add this method to the `VideoEditor` class in `app/video_editor.py`:

```python
    PACING_WEIGHTS = {
        "fast": 0.7,
        "normal": 1.0,
        "slow": 1.3,
        "dramatic_pause": 1.5,
    }

    def _calculate_paced_durations(
        self,
        total_duration: float,
        num_scenes: int,
        pacing_hints: Optional[List[str]] = None,
    ) -> List[float]:
        """
        Calculate per-scene durations based on pacing hints.

        When pacing_hints is None or empty, returns equal durations.
        Otherwise, weights are applied proportionally so they sum to total_duration.
        """
        if not pacing_hints or len(pacing_hints) != num_scenes:
            return [total_duration / num_scenes] * num_scenes

        weights = [self.PACING_WEIGHTS.get(h, 1.0) for h in pacing_hints]
        total_weight = sum(weights)

        return [(w / total_weight) * total_duration for w in weights]
```

- [ ] **Step 4: Run pacing test to verify it passes**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_video_editor.py -v`
Expected: PASS

- [ ] **Step 5: Add color grading method**

Add to `VideoEditor` class:

```python
    COLOR_GRADES = {
        "tech": {"contrast": 1.1, "saturation": 1.2, "blue_shift": 10},
        "finance": {"contrast": 1.05, "saturation": 0.9, "warmth": 15},
        "history": {"contrast": 1.0, "saturation": 0.8, "sepia": 0.3},
        "science": {"contrast": 1.1, "saturation": 1.3, "brightness": 5},
        "default": {"contrast": 1.05, "saturation": 1.1},
    }

    def _apply_color_grade(self, frame: np.ndarray, grade_name: str) -> np.ndarray:
        """Apply color grading to a video frame."""
        grade = self.COLOR_GRADES.get(grade_name, None)
        if not grade:
            return frame

        result = frame.astype(np.float32)

        # Contrast
        if "contrast" in grade:
            mean = result.mean()
            result = (result - mean) * grade["contrast"] + mean

        # Saturation
        if "saturation" in grade:
            gray = np.mean(result, axis=2, keepdims=True)
            result = gray + (result - gray) * grade["saturation"]

        # Blue shift
        if "blue_shift" in grade:
            result[:, :, 2] = result[:, :, 2] + grade["blue_shift"]

        # Warmth (add to red, subtract from blue)
        if "warmth" in grade:
            result[:, :, 0] = result[:, :, 0] + grade["warmth"]
            result[:, :, 2] = result[:, :, 2] - grade["warmth"] * 0.5

        # Brightness
        if "brightness" in grade:
            result = result + grade["brightness"]

        # Sepia
        if "sepia" in grade:
            sepia_amount = grade["sepia"]
            gray = np.mean(result, axis=2, keepdims=True)
            sepia_frame = np.stack([
                gray[:, :, 0] * 1.2,
                gray[:, :, 0] * 1.0,
                gray[:, :, 0] * 0.8,
            ], axis=2)
            result = result * (1 - sepia_amount) + sepia_frame * sepia_amount

        return np.clip(result, 0, 255).astype(np.uint8)
```

- [ ] **Step 6: Update assemble_video with v2 signature**

Update the `assemble_video` method signature to accept v2 parameters. The method should use motion clips when provided, apply pacing, use karaoke subtitles, mix SFX, and apply color grading. Add these imports at the top of the file:

```python
from app.subtitle_styles import SubtitleRenderer
from app.sfx import SFXMixer
```

Update `assemble_video` signature:

```python
    def assemble_video(
        self,
        audio_path: str,
        image_paths: List[str],
        output_filename: str,
        hook_text: Optional[str] = None,
        enable_subtitles: bool = True,
        enable_music: bool = True,
        # V2 parameters
        motion_clip_paths: Optional[List[str]] = None,
        pacing_hints: Optional[List[str]] = None,
        subtitle_style: str = "bold_impact",
        color_grade: Optional[str] = None,
        enable_sfx: bool = True,
        enable_intro: bool = False,
    ) -> str:
```

Inside the method, replace the equal-duration calculation with:

```python
            # Calculate per-scene durations (paced or equal)
            scene_durations = self._calculate_paced_durations(
                audio_duration, len(image_paths), pacing_hints
            )
```

Replace the image clip creation loop to support motion clips:

```python
            # Create scene clips (motion clips or Ken Burns)
            video_clips = []
            scene_timestamps = [0.0]
            cumulative = 0.0

            for i, duration in enumerate(scene_durations):
                if motion_clip_paths and i < len(motion_clip_paths) and motion_clip_paths[i]:
                    # Use motion clip
                    clip = VideoFileClip(motion_clip_paths[i]).with_duration(duration)
                    clip = clip.resized((self.WIDTH, self.HEIGHT))
                else:
                    # Fall back to Ken Burns
                    clip = self._create_ken_burns_clip(image_paths[i], duration)

                # Apply color grading
                if color_grade:
                    clip = clip.image_transform(
                        lambda frame, grade=color_grade: self._apply_color_grade(frame, grade)
                    )

                video_clips.append(clip)
                cumulative += duration
                scene_timestamps.append(cumulative)
```

Replace subtitle generation with karaoke renderer:

```python
            # Generate karaoke-style subtitles
            if enable_subtitles:
                logger.info("Generating karaoke subtitles...")
                try:
                    subtitle_segments = self.generate_subtitles(audio_path)
                    renderer = SubtitleRenderer(
                        style=subtitle_style, width=self.WIDTH, height=self.HEIGHT
                    )
                    subtitle_clips = self._create_karaoke_clips(
                        subtitle_segments, renderer
                    )
                    if subtitle_clips:
                        video = CompositeVideoClip([video] + subtitle_clips)
                except Exception as e:
                    logger.warning(f"Subtitle generation failed: {e}")
```

Add SFX mixing:

```python
            # Build SFX track
            sfx_clip = None
            if enable_sfx and settings.enable_sfx:
                try:
                    sfx_mixer = SFXMixer()
                    sfx_clip = sfx_mixer.build_sfx_track(
                        scene_timestamps=scene_timestamps,
                        total_duration=audio_duration,
                    )
                except Exception as e:
                    logger.warning(f"SFX generation failed: {e}")

            # Mix all audio (voice + music + SFX)
            audio_tracks = [voice_audio.with_volume_scaled(settings.voice_volume)]
            if music_clip:
                audio_tracks.append(music_clip)
            if sfx_clip:
                audio_tracks.append(sfx_clip)

            if len(audio_tracks) > 1:
                final_audio = CompositeAudioClip(audio_tracks)
            else:
                final_audio = audio_tracks[0]
```

- [ ] **Step 7: Add karaoke clip creation method**

Add this method to `VideoEditor`:

```python
    def _create_karaoke_clips(
        self,
        segments: List[SubtitleSegment],
        renderer: SubtitleRenderer,
    ) -> List:
        """Create karaoke-style subtitle overlay clips."""
        from moviepy import ImageClip

        clips = []

        for segment in segments:
            words = segment.text.split()
            if not words:
                continue

            duration = segment.end - segment.start
            if duration <= 0:
                continue

            # Calculate per-word timing within the segment
            word_duration = duration / len(words)

            for word_idx in range(len(words)):
                word_start = segment.start + word_idx * word_duration
                word_end = word_start + word_duration

                try:
                    frame = renderer.render_subtitle_frame(words, active_index=word_idx)

                    subtitle_clip = (
                        ImageClip(frame, is_mask=False)
                        .with_duration(word_end - word_start)
                        .with_start(word_start)
                        .with_position(("center", self.HEIGHT - 350))
                    )
                    clips.append(subtitle_clip)
                except Exception as e:
                    logger.debug(f"Subtitle frame failed: {e}")
                    continue

        return clips
```

- [ ] **Step 8: Add cross-fade assembly**

Replace the `concatenate_videoclips` call with cross-fade logic:

```python
            # Concatenate with cross-fade transitions
            if len(video_clips) > 1 and settings.crossfade_duration > 0:
                crossfade = settings.crossfade_duration
                # Apply crossfade to clips
                for i in range(1, len(video_clips)):
                    video_clips[i] = video_clips[i].with_start(
                        sum(scene_durations[:i]) - crossfade * i
                    ).crossfadein(crossfade)
                video = CompositeVideoClip(video_clips, size=(self.WIDTH, self.HEIGHT))
                # Adjust total duration for overlaps
                video = video.with_duration(audio_duration)
            else:
                video = concatenate_videoclips(video_clips, method="compose")
```

- [ ] **Step 9: Run all tests**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_video_editor.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add app/video_editor.py tests/test_video_editor.py
git commit -m "feat: upgrade video editor with karaoke subs, cross-fades, SFX, pacing, color grading"
```

---

## Phase 5: Metadata + CLI

### Task 12: Create metadata_gen.py

**Files:**
- Create: `app/metadata_gen.py`
- Create: `tests/test_metadata_gen.py`

- [ ] **Step 1: Write metadata generator tests**

```python
# tests/test_metadata_gen.py
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.metadata_gen import MetadataGenerator


def test_generate_metadata_returns_dict():
    """Metadata generation should return a dict with required keys."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({
        "title_tiktok": "You Won't Believe This!",
        "title_youtube": "The Shocking Truth About Bitcoin",
        "description": "In this video we explore...",
        "hashtags": ["#bitcoin", "#crypto", "#finance"],
        "best_posting_time": "Tuesday 6-8 PM EST",
    })

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    gen = MetadataGenerator()
    gen.client = mock_client

    result = gen.generate_metadata(
        topic="Bitcoin price history",
        hook="Did you know Bitcoin was once worth $0?",
        keywords=["bitcoin", "crypto"],
    )

    assert "title_tiktok" in result
    assert "hashtags" in result
    assert isinstance(result["hashtags"], list)


def test_save_metadata_creates_file():
    """Should save metadata JSON to output/metadata/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        gen = MetadataGenerator(output_dir=tmpdir)
        metadata = {
            "title_tiktok": "Test Title",
            "hashtags": ["#test"],
        }
        gen.save_metadata("test_video_001", metadata)

        path = Path(tmpdir) / "metadata" / "test_video_001.json"
        assert path.exists()

        with open(path) as f:
            saved = json.load(f)
        assert saved["title_tiktok"] == "Test Title"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_metadata_gen.py -v`
Expected: FAIL

- [ ] **Step 3: Implement metadata_gen.py**

```python
# app/metadata_gen.py
"""Metadata Generator - Generates titles, descriptions, hashtags, and thumbnails"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

from app.config import settings

logger = logging.getLogger(__name__)


class MetadataGenerator:
    """Generates platform-optimized metadata for videos."""

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir or settings.output_dir)
        self.metadata_dir = self.output_dir / "metadata"
        self.thumbnail_dir = self.output_dir / "thumbnails"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)

        self.client = None
        if settings.openai_api_key:
            self.client = OpenAI(api_key=settings.openai_api_key)

    def generate_metadata(
        self,
        topic: str,
        hook: str,
        keywords: List[str],
        niche: str = "",
    ) -> Dict:
        """Generate platform-optimized metadata using GPT."""
        if not self.client:
            return self._fallback_metadata(topic, hook, keywords)

        prompt = f"""Generate social media metadata for a short-form video.
Topic: {topic}
Hook: {hook}
Keywords: {', '.join(keywords)}
Niche: {niche or 'general'}

Return JSON with:
- "title_tiktok": Short, catchy title for TikTok (max 50 chars)
- "title_youtube": SEO-optimized title for YouTube Shorts (max 70 chars)
- "description": 2-3 sentence description with keywords
- "hashtags": List of 5-10 relevant hashtags (include # prefix)
- "best_posting_time": Recommended posting time"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=500,
            )

            content = response.choices[0].message.content
            return json.loads(content)

        except Exception as e:
            logger.warning(f"Metadata generation failed, using fallback: {e}")
            return self._fallback_metadata(topic, hook, keywords)

    def _fallback_metadata(self, topic: str, hook: str, keywords: List[str]) -> Dict:
        """Generate basic metadata without GPT."""
        return {
            "title_tiktok": topic[:50],
            "title_youtube": topic[:70],
            "description": hook,
            "hashtags": [f"#{kw.replace(' ', '')}" for kw in keywords[:10]],
            "best_posting_time": "Tuesday-Thursday 6-8 PM EST",
        }

    def save_metadata(self, video_id: str, metadata: Dict) -> str:
        """Save metadata to JSON file."""
        path = self.metadata_dir / f"{video_id}.json"
        with open(path, "w") as f:
            json.dump(metadata, f, indent=2)
        logger.info(f"Metadata saved: {path}")
        return str(path)

    def generate_thumbnail(
        self,
        video_path: str,
        video_id: str,
        title: str,
    ) -> Optional[str]:
        """Extract a frame from the video and add title text for thumbnail."""
        try:
            from moviepy import VideoFileClip

            clip = VideoFileClip(video_path)
            # Extract frame at 25% of duration (usually a good frame)
            frame_time = clip.duration * 0.25
            frame = clip.get_frame(frame_time)
            clip.close()

            # Convert to PIL Image
            img = Image.fromarray(frame)

            # Add title text overlay
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("Arial-Bold", 80)
            except OSError:
                font = ImageFont.load_default()

            # Draw text with stroke
            text = title[:40].upper()
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            x = (img.width - text_w) // 2
            y = img.height // 3

            # Stroke
            for dx in range(-3, 4):
                for dy in range(-3, 4):
                    draw.text((x + dx, y + dy), text, font=font, fill="black")
            draw.text((x, y), text, font=font, fill="white")

            # Save
            thumb_path = self.thumbnail_dir / f"{video_id}.png"
            img.save(str(thumb_path))
            logger.info(f"Thumbnail saved: {thumb_path}")
            return str(thumb_path)

        except Exception as e:
            logger.warning(f"Thumbnail generation failed: {e}")
            return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_metadata_gen.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add app/metadata_gen.py tests/test_metadata_gen.py
git commit -m "feat: add metadata generator for titles, descriptions, hashtags, thumbnails"
```

---

### Task 13: Upgrade main.py with CLI modes

**Files:**
- Modify: `main.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write CLI argument parsing tests**

```python
# tests/test_cli.py
from main import parse_args


def test_default_args():
    args = parse_args([])
    assert args.auto is False
    assert args.batch is None
    assert args.series is None
    assert args.parts == 3
    assert args.niche is None
    assert args.no_motion is False
    assert args.subtitle_style == "bold_impact"
    assert args.no_sfx is False
    assert args.no_music is False


def test_auto_mode():
    args = parse_args(["--auto"])
    assert args.auto is True


def test_batch_mode():
    args = parse_args(["--batch", "5"])
    assert args.batch == 5


def test_series_mode():
    args = parse_args(["--series", "History of Money", "--parts", "3"])
    assert args.series == "History of Money"
    assert args.parts == 3


def test_auto_with_niche():
    args = parse_args(["--auto", "--niche", "tech"])
    assert args.auto is True
    assert args.niche == "tech"


def test_style_and_feature_flags():
    args = parse_args(["--auto", "--subtitle-style", "neon_glow", "--no-motion", "--no-sfx"])
    assert args.subtitle_style == "neon_glow"
    assert args.no_motion is True
    assert args.no_sfx is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_cli.py -v`
Expected: FAIL — `parse_args` doesn't exist

- [ ] **Step 3: Add argparse to main.py**

Add `parse_args` function and refactor `main()` to support CLI modes. Add at the top of `main.py`:

```python
import argparse
```

Add the `parse_args` function:

```python
def parse_args(argv=None):
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="FVFactory - Automated short-form video creation"
    )

    # Modes
    parser.add_argument("--auto", action="store_true",
                        help="Auto mode: discover trend, generate, render — zero interaction")
    parser.add_argument("--batch", type=int, default=None,
                        help="Batch mode: generate N videos")
    parser.add_argument("--series", type=str, default=None,
                        help="Series mode: generate connected multi-part videos on a topic")
    parser.add_argument("--parts", type=int, default=3,
                        help="Number of parts for series mode (default: 3)")

    # Options
    parser.add_argument("--niche", type=str, default=None,
                        help="Niche filter for trend discovery")
    parser.add_argument("--topic", type=str, default=None,
                        help="Video topic (skips interactive prompt)")
    parser.add_argument("--no-motion", action="store_true",
                        help="Skip Minimax motion clips, use Ken Burns")
    parser.add_argument("--subtitle-style", type=str, default="bold_impact",
                        help="Subtitle preset: bold_impact, clean_minimal, neon_glow, fire")
    parser.add_argument("--no-sfx", action="store_true",
                        help="Disable sound effects")
    parser.add_argument("--no-music", action="store_true",
                        help="Disable background music")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock images instead of Flux")

    return parser.parse_args(argv)
```

- [ ] **Step 4: Refactor main() to use args and v2 pipeline**

Refactor the `main()` function to:
1. Parse CLI args
2. Support `--auto` mode (use TrendScout to pick topic, run pipeline non-interactively)
3. Support `--batch` mode (loop N times with `--auto` logic)
4. Pass v2 params through to `run_pipeline`

Update `run_pipeline` signature:

```python
def run_pipeline(
    topic: str,
    use_mock_images: bool = False,
    enable_subtitles: bool = True,
    enable_music: bool = True,
    persona: Optional[str] = None,
    use_chroma_key: bool = False,
    # V2 parameters
    enable_motion: bool = True,
    subtitle_style: str = "bold_impact",
    enable_sfx: bool = True,
) -> str:
```

Inside `run_pipeline`, add v2 steps:
- Pass `enable_v2=True` to `script_gen.generate_script()`
- After image generation, generate motion clips if `enable_motion and script.motion_prompts`
- Pass `motion_clip_paths`, `pacing_hints`, `subtitle_style`, `color_grade`, `enable_sfx` to `video_editor.assemble_video()`
- After video render, generate metadata and thumbnail
- Log costs via CostTracker

Update `main()`:

```python
def main():
    args = parse_args()

    # ... banner ...

    if not validate_config():
        sys.exit(1)

    if args.auto or args.batch:
        run_auto_mode(args)
    elif args.series:
        run_series_mode(args)
    else:
        run_interactive_mode(args)
```

Add `run_auto_mode`:

```python
def run_auto_mode(args):
    """Run in auto mode: discover trend, generate, render."""
    from app.trend_scout import TrendScout

    count = args.batch or 1
    scout = TrendScout()

    for i in range(count):
        if args.topic:
            topic = args.topic
        else:
            topics = scout.discover_topics(niche=args.niche, count=1)
            if not topics:
                logger.error("No trending topics found")
                continue
            topic = topics[0].title

        logger.info(f"[{i+1}/{count}] Auto generating: {topic}")

        try:
            run_pipeline(
                topic=topic,
                use_mock_images=args.mock,
                enable_music=not args.no_music,
                enable_motion=not args.no_motion,
                subtitle_style=args.subtitle_style,
                enable_sfx=not args.no_sfx,
            )
        except Exception as e:
            logger.error(f"Failed: {e}")
            continue
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add main.py tests/test_cli.py
git commit -m "feat: add --auto, --batch, --series CLI modes with v2 pipeline integration"
```

---

## Phase 6: Dashboard Update

### Task 14: Update Streamlit dashboard for v2

**Files:**
- Modify: `app/dashboard.py`

- [ ] **Step 1: Add v2 options to sidebar**

Update `render_sidebar()` in `app/dashboard.py` to add:
- Subtitle style selector (dropdown with preset names)
- Enable/disable motion clips checkbox
- Enable/disable SFX checkbox
- Niche/color grade selector

Add under the existing "4. Options" section:

```python
        # V2 Options
        st.subheader("5. V2 Enhancements")

        subtitle_style = st.selectbox(
            "Subtitle Style",
            options=["bold_impact", "clean_minimal", "neon_glow", "fire"],
            help="Karaoke-style subtitle preset"
        )
        st.session_state.subtitle_style = subtitle_style

        enable_motion = st.checkbox("Enable motion clips", value=True,
                                     help="Generate Minimax image-to-video clips (costs ~$0.10/clip)")
        st.session_state.enable_motion = enable_motion

        enable_sfx = st.checkbox("Enable sound effects", value=True,
                                  help="Add whoosh, riser, and impact sounds")
        st.session_state.enable_sfx = enable_sfx
```

- [ ] **Step 2: Update render_video() to pass v2 params**

Update `render_video()` to pass subtitle_style, motion clips, SFX flag to the video editor:

```python
    # In the standard mode branch:
    output_path = video_editor.assemble_video(
        audio_path=st.session_state.audio_result.file_path,
        image_paths=st.session_state.image_paths,
        output_filename=output_filename,
        hook_text=st.session_state.edited_hook,
        enable_subtitles=st.session_state.get("enable_subtitles", True),
        enable_music=st.session_state.get("enable_music", True),
        # V2 params
        motion_clip_paths=st.session_state.get("motion_clip_paths"),
        pacing_hints=st.session_state.get("pacing_hints"),
        subtitle_style=st.session_state.get("subtitle_style", "bold_impact"),
        color_grade=st.session_state.get("color_grade"),
        enable_sfx=st.session_state.get("enable_sfx", True),
    )
```

- [ ] **Step 3: Update generate_assets() to generate motion clips**

Add motion clip generation to `generate_assets()` after image generation:

```python
        # Generate motion clips if enabled
        if st.session_state.get("enable_motion", True) and st.session_state.get("pacing_hints"):
            with st.spinner("Generating motion clips... This may take several minutes."):
                from app.motion_gen import MotionGenerator
                motion_gen = MotionGenerator()
                motion_clips = motion_gen.generate_all_clips(
                    image_paths,
                    st.session_state.get("motion_prompts", []),
                )
                st.session_state.motion_clip_paths = motion_clips

            success = sum(1 for c in motion_clips if c is not None)
            st.success(f"Motion clips: {success}/{len(motion_clips)} generated")
```

- [ ] **Step 4: Update generate_script to use v2 mode**

In `generate_script()`, pass `enable_v2=True`:

```python
    script = generator.generate_script(topic, enable_v2=True)
    # Store v2 fields in session state
    st.session_state.motion_prompts = list(script.motion_prompts)
    st.session_state.pacing_hints = list(script.pacing_hints)
```

- [ ] **Step 5: Add cost display to video preview**

In `render_video_preview()`, add a cost summary section:

```python
        # Cost summary
        from app.cost_tracker import CostTracker
        tracker = CostTracker()
        video_id = Path(st.session_state.video_path).stem
        cost = tracker.get_video_cost(video_id)
        if cost > 0:
            st.metric("Estimated Cost", f"${cost:.2f}")
```

- [ ] **Step 6: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add app/dashboard.py
git commit -m "feat: update Streamlit dashboard with v2 options (subtitle styles, motion, SFX)"
```

---

## Phase 7: Integration + Polish

### Task 15: Wire cost tracking into pipeline

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add cost tracking calls to run_pipeline**

In `run_pipeline()`, create a `CostTracker` instance and log costs at each API call:

```python
    from app.cost_tracker import CostTracker

    # After generating video_id (from output_filename)
    video_id = output_filename.replace(".mp4", "")
    tracker = CostTracker()

    # After script generation
    tracker.log_cost(video_id, "openai_gpt4o")

    # After audio generation
    if settings.elevenlabs_api_key:
        chars = len(full_narration)
        tracker.log_cost(video_id, "elevenlabs_tts", quantity=max(1, chars // 1000))
    else:
        chars = len(full_narration)
        tracker.log_cost(video_id, "openai_tts", quantity=max(1, chars // 1000))

    # After image generation (if not mock)
    if not use_mock_images:
        tracker.log_cost(video_id, "flux_image", quantity=len(image_paths))

    # After motion clip generation
    if motion_clip_paths:
        success_count = sum(1 for c in motion_clip_paths if c is not None)
        if success_count > 0:
            tracker.log_cost(video_id, "minimax_video", quantity=success_count)

    # At end of pipeline
    tracker.save()
    total = tracker.get_video_cost(video_id)
    logger.info(f"Total cost for this video: ${total:.2f}")
```

- [ ] **Step 2: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add main.py
git commit -m "feat: wire cost tracking into pipeline, log per-video API spend"
```

---

### Task 16: Wire metadata generation into pipeline

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add metadata generation after video render**

At the end of `run_pipeline()`, after video is rendered:

```python
    from app.metadata_gen import MetadataGenerator

    # Generate metadata
    logger.info("Generating metadata...")
    meta_gen = MetadataGenerator()
    metadata = meta_gen.generate_metadata(
        topic=topic,
        hook=script.hook,
        keywords=script.keywords,
        niche=settings.niche,
    )
    meta_gen.save_metadata(video_id, metadata)

    # Generate thumbnail
    logger.info("Generating thumbnail...")
    meta_gen.generate_thumbnail(
        video_path=output_path,
        video_id=video_id,
        title=metadata.get("title_tiktok", topic),
    )
```

- [ ] **Step 2: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add main.py
git commit -m "feat: auto-generate metadata and thumbnails after video render"
```

---

### Task 17: Update CLAUDE.md and create .env.example

**Files:**
- Modify: `CLAUDE.md`
- Create: `.env.example`

- [ ] **Step 1: Update CLAUDE.md**

Update the Project Overview and Commands sections to reflect v2:

```markdown
## Project Overview

FVFactory v2 is a professional-grade automated short-form video creation system (TikTok/Shorts).

**Pipeline:** Topic (auto or manual) -> Script (with motion prompts) -> Audio/Images/Motion Clips -> MP4

**APIs Used:**
- OpenAI - Script generation + metadata
- ElevenLabs (Multilingual v2) - Text-to-speech
- Replicate (Flux) - Image generation
- Replicate (Minimax) - Image-to-video motion clips
- Whisper (local) - Word-level transcription for subtitles

## Commands

```bash
# Interactive mode
python main.py

# Auto mode (discover trend, generate, render)
python main.py --auto

# Auto with niche filter
python main.py --auto --niche tech

# Batch mode (5 videos)
python main.py --batch 5 --niche finance

# Series mode
python main.py --series "History of Money" --parts 3

# Options
python main.py --auto --no-motion --subtitle-style neon_glow
python main.py --auto --mock  # Use mock images (free)

# Streamlit dashboard
streamlit run app/dashboard.py
```
```

- [ ] **Step 2: Create .env.example**

```env
# Required
OPENAI_API_KEY=sk-...

# Recommended
ELEVENLABS_API_KEY=...
REPLICATE_API_TOKEN=r8_...

# Optional (talking head mode)
HEDRA_API_KEY=...

# V2 Settings (all have defaults, override if needed)
# FLUX_MODEL=black-forest-labs/flux-1.1-pro
# MINIMAX_MODEL=minimax/image-to-video
# ELEVENLABS_MODEL=eleven_multilingual_v2
# ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
# SUBTITLE_STYLE=bold_impact
# CROSSFADE_DURATION=0.8
# ENABLE_SFX=true
# ENABLE_MOTION=true
# MAX_PARALLEL_WORKERS=3
# NICHE=tech
# REDDIT_SUBREDDITS=todayilearned,technology,science,explainlikeimfive
```

- [ ] **Step 3: Commit**

```bash
cd /Users/moganes/Projects/FVFactory
git add CLAUDE.md .env.example
git commit -m "docs: update CLAUDE.md for v2, add .env.example"
```

---

### Task 18: Run full integration test

- [ ] **Step 1: Run all unit tests**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run mock pipeline end-to-end**

Run: `cd /Users/moganes/Projects/FVFactory && python main.py --topic "Test video" --mock --no-motion --no-sfx --no-music`
Expected: Pipeline completes with mock images, generates output MP4, metadata JSON, and thumbnail

- [ ] **Step 3: Fix any integration issues found**

If any step fails, debug and fix the issue, then re-run.

- [ ] **Step 4: Commit any fixes**

```bash
cd /Users/moganes/Projects/FVFactory
git add -A
git commit -m "fix: integration fixes from end-to-end testing"
```
