"""Sound Effects Mixer - Adds whoosh, riser, and impact SFX to videos"""

import logging
from pathlib import Path
from typing import List, Optional

from moviepy import AudioFileClip, CompositeAudioClip

from app.config import settings

logger = logging.getLogger(__name__)


class SFXMixer:
    """Builds a composite SFX audio track synced to scene transitions."""

    SFX_FILES = {
        "whoosh": "whoosh.mp3",
        "riser": "riser.mp3",
        "impact": "impact.mp3",
    }

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
        Placement: riser at 0.0s, impact at 0.5s, whoosh at each transition.
        Returns None if no SFX files are available.
        """
        clips = []

        whoosh = self._load_sfx("whoosh")
        riser = self._load_sfx("riser")
        impact = self._load_sfx("impact")

        if not any([whoosh, riser, impact]):
            logger.info("No SFX files available, skipping SFX track")
            return None

        if riser:
            clips.append(riser.with_start(0.0))
        if impact:
            clips.append(impact.with_start(0.5))

        if whoosh:
            transitions = self._get_transition_times(scene_timestamps)
            for t in transitions:
                whoosh_start = max(0, t - 0.3)
                clips.append(whoosh.with_start(whoosh_start))

        if not clips:
            return None

        try:
            composite = CompositeAudioClip(clips)
            if composite.duration and composite.duration > total_duration:
                composite = composite.with_duration(total_duration)
            return composite
        except Exception as e:
            logger.warning(f"Failed to build SFX track: {e}")
            return None
