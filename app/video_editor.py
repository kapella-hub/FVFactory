"""
Video Editor - Assembles audio and images into a final video with MoviePy
Includes dynamic word-level subtitles using Whisper transcription
Includes background music with audio ducking
"""

import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from moviepy import (
    ImageClip,
    AudioFileClip,
    TextClip,
    VideoFileClip,
    CompositeVideoClip,
    CompositeAudioClip,
    concatenate_videoclips,
    concatenate_audioclips,
)
import numpy as np

from app.config import settings
from app.subtitle_styles import SubtitleRenderer
from app.sfx import SFXMixer

logger = logging.getLogger(__name__)


@dataclass
class SubtitleSegment:
    """Represents a single subtitle segment with timing"""
    text: str
    start: float  # Start time in seconds
    end: float    # End time in seconds


class VideoEditorError(Exception):
    """Base exception for video editing errors"""
    pass


class VideoEditor:
    """Assembles video from audio and image assets with Ken Burns effect, subtitles, and music"""

    # Video settings for vertical short-form content (TikTok/Shorts)
    WIDTH = 1080
    HEIGHT = 1920
    FPS = 24
    CODEC = "libx264"

    # Ken Burns effect settings
    ZOOM_START = 1.0
    ZOOM_END = 1.1

    # Subtitle settings
    HOOK_DURATION = 3  # seconds
    SUBTITLE_FONT_SIZE = 70
    SUBTITLE_FONT = "Arial-Bold"
    SUBTITLE_COLOR = "yellow"
    SUBTITLE_STROKE_COLOR = "black"
    SUBTITLE_STROKE_WIDTH = 3
    WORDS_PER_CHUNK = 3  # Fallback chunking if word-level not available

    # Supported music file extensions
    MUSIC_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac"}

    # Talking head overlay settings (for hybrid mode)
    TALKING_HEAD_SIZE_RATIO = 0.30  # 30% of screen width
    TALKING_HEAD_PADDING = 40  # Padding from edges in pixels
    TALKING_HEAD_POSITION = "bottom-right"  # Position on screen

    # Chroma key settings (for green screen removal)
    CHROMA_KEY_COLOR = [0, 177, 64]  # Standard green screen RGB
    CHROMA_KEY_THRESHOLD = 100  # Color similarity threshold

    # Dynamic pacing weights
    PACING_WEIGHTS = {
        "fast": 0.7,
        "normal": 1.0,
        "slow": 1.3,
        "dramatic_pause": 1.5,
    }

    # Color grading presets
    COLOR_GRADES = {
        "tech": {"contrast": 1.1, "saturation": 1.2, "blue_shift": 10},
        "finance": {"contrast": 1.05, "saturation": 0.9, "warmth": 15},
        "history": {"contrast": 1.0, "saturation": 0.8, "sepia": 0.3},
        "science": {"contrast": 1.1, "saturation": 1.3, "brightness": 5},
        "default": {"contrast": 1.05, "saturation": 1.1},
    }

    def __init__(self, music_mood: str = ""):
        self.output_dir = Path(settings.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._whisper_model = None
        self.music_dir = Path(settings.music_dir)
        self.music_mood = music_mood

    def _get_whisper_model(self):
        """Lazy-load Whisper model to avoid loading until needed."""
        if self._whisper_model is None:
            try:
                import whisper
                logger.info("Loading Whisper 'base' model...")
                self._whisper_model = whisper.load_model("base")
                logger.info("Whisper model loaded successfully")
            except ImportError:
                raise VideoEditorError(
                    "openai-whisper not installed. Run: pip install openai-whisper torch"
                )
        return self._whisper_model

    def _get_random_music_file(self, mood: str = "") -> Optional[Path]:
        """
        Get a random music file, preferring mood-specific subfolder.

        Folder structure:
          assets/music/           — fallback (any mood)
          assets/music/epic/      — epic, dramatic tracks
          assets/music/chill/     — calm, ambient tracks
          assets/music/upbeat/    — energetic, fun tracks
          assets/music/dark/      — moody, suspenseful tracks
          assets/music/cinematic/ — orchestral, documentary tracks

        Returns:
            Path to a random music file, or None if no music files found
        """
        if not self.music_dir.exists():
            logger.warning(f"Music directory not found: {self.music_dir}")
            return None

        # Try mood-specific subfolder first
        search_dirs = []
        if mood:
            mood_dir = self.music_dir / mood
            if mood_dir.exists():
                search_dirs.append(mood_dir)

        # Always fall back to root music dir
        search_dirs.append(self.music_dir)

        for search_dir in search_dirs:
            music_files = [
                f for f in search_dir.iterdir()
                if f.is_file() and f.suffix.lower() in self.MUSIC_EXTENSIONS
            ]
            if music_files:
                selected = random.choice(music_files)
                logger.info(f"Selected background music ({mood or 'any'}): {selected.name}")
                return selected

        logger.warning(f"No music files found in {self.music_dir}")
        return None

    def _prepare_background_music(
        self,
        music_path: Path,
        target_duration: float
    ) -> AudioFileClip:
        """
        Prepare background music to match the target duration.

        - If music is shorter than target: loop it
        - If music is longer than target: trim it
        - Apply volume ducking

        Args:
            music_path: Path to the music file
            target_duration: Duration to match (in seconds)

        Returns:
            AudioFileClip with adjusted duration and volume
        """
        music = AudioFileClip(str(music_path))
        music_duration = music.duration

        if music_duration < target_duration:
            # Loop the music to fill the duration
            logger.info(f"Looping music ({music_duration:.1f}s -> {target_duration:.1f}s)")

            loops_needed = int(target_duration / music_duration) + 1
            music_clips = [music] * loops_needed

            # Concatenate and trim to exact duration
            looped_music = concatenate_audioclips(music_clips)
            music = looped_music.with_duration(target_duration)

        elif music_duration > target_duration:
            # Trim the music
            logger.info(f"Trimming music ({music_duration:.1f}s -> {target_duration:.1f}s)")
            music = music.with_duration(target_duration)

        # Apply volume ducking
        music = music.with_volume_scaled(settings.music_volume)
        logger.info(f"Music volume set to {settings.music_volume * 100:.0f}%")

        return music

    def _mix_audio(
        self,
        voice_audio: AudioFileClip,
        music_audio: Optional[AudioFileClip]
    ) -> AudioFileClip:
        """
        Mix voiceover and background music into a single audio track.

        Args:
            voice_audio: The main voiceover audio
            music_audio: Optional background music (already volume-adjusted)

        Returns:
            Mixed audio clip
        """
        # Apply voice volume
        voice_audio = voice_audio.with_volume_scaled(settings.voice_volume)

        if music_audio is None:
            return voice_audio

        # Composite both audio tracks
        logger.info("Mixing voiceover and background music...")
        mixed_audio = CompositeAudioClip([music_audio, voice_audio])

        return mixed_audio

    def generate_subtitles(self, audio_path: str) -> List[SubtitleSegment]:
        """
        Transcribe audio and generate word-level subtitle segments.

        Args:
            audio_path: Path to the audio file to transcribe

        Returns:
            List of SubtitleSegment objects with text and timing

        Raises:
            VideoEditorError: If transcription fails
        """
        if not Path(audio_path).exists():
            raise VideoEditorError(f"Audio file not found: {audio_path}")

        try:
            model = self._get_whisper_model()

            logger.info("Transcribing audio with Whisper...")
            result = model.transcribe(
                audio_path,
                word_timestamps=True,
                language="en",
            )

            segments = []

            # Try to extract word-level timestamps
            if "segments" in result:
                for segment in result["segments"]:
                    # Check if word-level timestamps are available
                    if "words" in segment and segment["words"]:
                        # Use word-level timestamps
                        segments.extend(
                            self._process_word_level(segment["words"])
                        )
                    else:
                        # Fall back to chunking segment text
                        segments.extend(
                            self._chunk_segment(
                                segment["text"],
                                segment["start"],
                                segment["end"]
                            )
                        )

            logger.info(f"Generated {len(segments)} subtitle segments")
            return segments

        except Exception as e:
            raise VideoEditorError(f"Transcription failed: {e}")

    def _process_word_level(self, words: List[dict]) -> List[SubtitleSegment]:
        """
        Process word-level timestamps into grouped subtitle segments.
        Groups words into chunks of WORDS_PER_CHUNK for readability.
        """
        segments = []
        chunk_words = []
        chunk_start = None

        for word_info in words:
            word = word_info.get("word", "").strip()
            if not word:
                continue

            if chunk_start is None:
                chunk_start = word_info.get("start", 0)

            chunk_words.append(word)

            # Create segment when chunk is full
            if len(chunk_words) >= self.WORDS_PER_CHUNK:
                segments.append(SubtitleSegment(
                    text=" ".join(chunk_words),
                    start=chunk_start,
                    end=word_info.get("end", chunk_start + 0.5)
                ))
                chunk_words = []
                chunk_start = None

        # Don't forget remaining words
        if chunk_words and chunk_start is not None:
            segments.append(SubtitleSegment(
                text=" ".join(chunk_words),
                start=chunk_start,
                end=words[-1].get("end", chunk_start + 0.5)
            ))

        return segments

    def _chunk_segment(
        self,
        text: str,
        start: float,
        end: float
    ) -> List[SubtitleSegment]:
        """
        Split a segment into 2-3 word chunks with interpolated timing.
        Used as fallback when word-level timestamps aren't available.
        """
        words = text.strip().split()
        if not words:
            return []

        segments = []
        duration = end - start

        i = 0
        while i < len(words):
            chunk = words[i:i + self.WORDS_PER_CHUNK]
            chunk_text = " ".join(chunk)

            # Interpolate timing based on word position
            chunk_start = start + (i / len(words)) * duration
            chunk_end = start + ((i + len(chunk)) / len(words)) * duration

            segments.append(SubtitleSegment(
                text=chunk_text,
                start=chunk_start,
                end=chunk_end
            ))

            i += self.WORDS_PER_CHUNK

        return segments

    def _create_subtitle_clips(
        self,
        segments: List[SubtitleSegment]
    ) -> List[TextClip]:
        """
        Create styled TextClips for each subtitle segment.

        Style: Yellow text with black stroke (classic viral TikTok style)
        Position: Bottom-center of frame
        """
        clips = []

        for segment in segments:
            duration = segment.end - segment.start
            if duration <= 0:
                continue

            try:
                text_clip = TextClip(
                    text=segment.text.upper(),  # Uppercase for impact
                    font_size=self.SUBTITLE_FONT_SIZE,
                    color=self.SUBTITLE_COLOR,
                    font=self.SUBTITLE_FONT,
                    stroke_color=self.SUBTITLE_STROKE_COLOR,
                    stroke_width=self.SUBTITLE_STROKE_WIDTH,
                    method="caption",
                    size=(self.WIDTH - 100, None),
                    text_align="center",
                )

                # Position at bottom-center with padding from bottom
                text_clip = (
                    text_clip
                    .with_position(("center", self.HEIGHT - 350))
                    .with_start(segment.start)
                    .with_duration(duration)
                )

                clips.append(text_clip)

            except Exception as e:
                logger.warning(f"Failed to create subtitle clip: {e}")
                continue

        return clips

    def _calculate_paced_durations(
        self,
        total_duration: float,
        num_scenes: int,
        pacing_hints: Optional[List[str]] = None,
        scene_texts: Optional[List[str]] = None,
    ) -> List[float]:
        """
        Calculate per-scene durations based on scene_texts word counts.
        Falls back to pacing_hints weights, then equal splits.

        scene_texts is the best signal — each scene's duration is proportional
        to how many words of narration go with it.
        """
        # Best: use word count from scene_texts
        if scene_texts and len(scene_texts) == num_scenes:
            word_counts = [max(len(t.split()), 1) for t in scene_texts]
            total_words = sum(word_counts)
            durations = [(wc / total_words) * total_duration for wc in word_counts]
            logger.info(f"Scene durations (word-based): {[f'{d:.1f}s' for d in durations]}")
            return durations

        # Fallback: pacing hints
        if pacing_hints and len(pacing_hints) == num_scenes:
            weights = [self.PACING_WEIGHTS.get(h, 1.0) for h in pacing_hints]
            total_weight = sum(weights)
            return [(w / total_weight) * total_duration for w in weights]

        # Last resort: equal splits
        return [total_duration / num_scenes] * num_scenes

    def _apply_color_grade(self, frame: np.ndarray, grade_name: str) -> np.ndarray:
        """Apply color grading to a video frame."""
        grade = self.COLOR_GRADES.get(grade_name, None)
        if not grade:
            return frame

        result = frame.astype(np.float32)

        if "contrast" in grade:
            mean = result.mean()
            result = (result - mean) * grade["contrast"] + mean

        if "saturation" in grade:
            gray = np.mean(result, axis=2, keepdims=True)
            result = gray + (result - gray) * grade["saturation"]

        if "blue_shift" in grade:
            result[:, :, 2] = result[:, :, 2] + grade["blue_shift"]

        if "warmth" in grade:
            result[:, :, 0] = result[:, :, 0] + grade["warmth"]
            result[:, :, 2] = result[:, :, 2] - grade["warmth"] * 0.5

        if "brightness" in grade:
            result = result + grade["brightness"]

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

    def _create_karaoke_clips(
        self,
        segments: List[SubtitleSegment],
        renderer: SubtitleRenderer,
        skip_until: float = 0.0,
    ) -> List:
        """Create karaoke-style subtitle overlay clips. Skips subtitles before skip_until seconds."""
        clips = []

        for segment in segments:
            words = segment.text.split()
            if not words:
                continue

            duration = segment.end - segment.start
            if duration <= 0:
                continue

            # Skip subtitles that overlap with title card
            if segment.end <= skip_until:
                continue

            word_duration = duration / len(words)

            for word_idx in range(len(words)):
                word_start = segment.start + word_idx * word_duration
                word_end = word_start + word_duration

                # Skip individual words that fall within title period
                if word_start < skip_until:
                    continue

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

    TITLE_DURATION = 4.0  # seconds the title is shown

    def _create_title_overlay(self, title: str, duration: float = 4.0) -> ImageClip:
        """
        Create a bold title overlay on a semi-transparent dark backdrop.
        Cyan/teal text to contrast with yellow subtitles. No fade-in (visible from frame 1).
        Dynamically reduces font size to fit within 3 lines max.
        """
        from PIL import Image, ImageDraw, ImageFont
        from moviepy.video.fx import CrossFadeOut

        # Strip emojis and clean up the title for overlay
        clean_title = title.encode("ascii", "ignore").decode("ascii").strip()
        if not clean_title:
            clean_title = title

        img = Image.new("RGBA", (self.WIDTH, self.HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Full-width dark overlay band
        overlay_top = self.HEIGHT // 4
        overlay_bottom = self.HEIGHT * 3 // 4
        draw.rectangle(
            [0, overlay_top, self.WIDTH, overlay_bottom],
            fill=(0, 0, 0, 190),
        )

        # Try decreasing font sizes until the title fits in 3 lines max
        max_width = self.WIDTH - 140
        max_lines = 3
        font = None
        lines = []

        for font_size in [82, 70, 60, 50, 42]:
            font = None
            for font_name in ["Impact", "Arial-Bold", "/System/Library/Fonts/Helvetica.ttc",
                              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]:
                try:
                    font = ImageFont.truetype(font_name, font_size)
                    break
                except OSError:
                    continue
            if font is None:
                font = ImageFont.load_default()

            # Word-wrap title
            words = clean_title.upper().split()
            lines = []
            current_line = []
            for word in words:
                test_line = " ".join(current_line + [word])
                bbox = font.getbbox(test_line)
                if bbox[2] - bbox[0] > max_width and current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    current_line.append(word)
            if current_line:
                lines.append(" ".join(current_line))

            if len(lines) <= max_lines:
                break

        # If still too many lines, truncate and add ellipsis
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1][:30] + "..."

        # Draw centered text — CYAN color (#00E5FF) to contrast yellow subtitles
        line_height = font_size + 16
        total_height = len(lines) * line_height
        y_start = (self.HEIGHT - total_height) // 2

        text_color = (0, 229, 255, 255)  # Bright cyan
        stroke_color = (0, 0, 0, 255)

        for i, line in enumerate(lines):
            bbox = font.getbbox(line)
            text_w = bbox[2] - bbox[0]
            x = (self.WIDTH - text_w) // 2
            y = y_start + i * line_height

            # Thick stroke for visibility
            for dx in range(-4, 5):
                for dy in range(-4, 5):
                    if dx * dx + dy * dy <= 16:
                        draw.text((x + dx, y + dy), line, font=font, fill=stroke_color)
            draw.text((x, y), line, font=font, fill=text_color)

        frame = np.array(img)

        title_clip = (
            ImageClip(frame)
            .with_duration(duration)
            .with_effects([CrossFadeOut(1.0)])
        )

        return title_clip

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
        title: Optional[str] = None,
        scene_texts: Optional[List[str]] = None,
    ) -> str:
        """
        Assemble a video from audio and images with Ken Burns effect, subtitles, and music.

        Args:
            audio_path: Path to the voiceover audio file
            image_paths: List of paths to image files
            output_filename: Name of the output video file
            hook_text: Optional text to overlay for the first 3 seconds (deprecated)
            enable_subtitles: If True, generate and overlay word-level subtitles
            enable_music: If True, add background music with ducking

        Returns:
            str: Path to the generated video file

        Raises:
            VideoEditorError: If video assembly fails
        """
        if not audio_path or not Path(audio_path).exists():
            raise VideoEditorError(f"Audio file not found: {audio_path}")

        if not image_paths:
            raise VideoEditorError("No images provided")

        for img_path in image_paths:
            if not Path(img_path).exists():
                raise VideoEditorError(f"Image file not found: {img_path}")

        subtitle_clips = []
        music_clip = None

        try:
            # Load voiceover audio and get duration
            voice_audio = AudioFileClip(audio_path)
            audio_duration = voice_audio.duration

            # Calculate paced durations per scene (word-count based when scene_texts available)
            scene_durations = self._calculate_paced_durations(
                audio_duration, len(image_paths), pacing_hints, scene_texts
            )

            # Create video clips with Ken Burns effect or motion clips + color grading
            video_clips = []
            scene_timestamps = [0.0]
            cumulative = 0.0

            for i, duration in enumerate(scene_durations):
                if motion_clip_paths and i < len(motion_clip_paths) and motion_clip_paths[i]:
                    raw_clip = VideoFileClip(motion_clip_paths[i])
                    raw_clip = raw_clip.resized((self.WIDTH, self.HEIGHT))
                    # Slow down the clip to fill the scene duration
                    # e.g., 5.6s clip for 10s scene = 0.56x speed
                    if raw_clip.duration and raw_clip.duration < duration:
                        speed_factor = raw_clip.duration / duration
                        clip = raw_clip.with_speed_scaled(speed_factor)
                    else:
                        clip = raw_clip.with_duration(duration)
                else:
                    clip = self._create_ken_burns_clip(image_paths[i], duration)

                if color_grade:
                    clip = clip.image_transform(
                        lambda frame, grade=color_grade: self._apply_color_grade(frame, grade)
                    )

                video_clips.append(clip)
                cumulative += duration
                scene_timestamps.append(cumulative)

            # Use cross-fade transitions if available
            if len(video_clips) > 1 and settings.crossfade_duration > 0:
                from moviepy.video.fx import CrossFadeIn
                crossfade = settings.crossfade_duration
                for i in range(1, len(video_clips)):
                    video_clips[i] = video_clips[i].with_start(
                        sum(scene_durations[:i]) - crossfade * i
                    ).with_effects([CrossFadeIn(crossfade)])
                video = CompositeVideoClip(video_clips, size=(self.WIDTH, self.HEIGHT))
                video = video.with_duration(audio_duration)
            else:
                video = concatenate_videoclips(video_clips, method="compose")

            # Add title overlay on top of first scene
            if title:
                logger.info(f"Adding title overlay: {title[:50]}...")
                try:
                    title_overlay = self._create_title_overlay(title, duration=4.0)
                    title_overlay = title_overlay.with_start(0)
                    video = CompositeVideoClip([video, title_overlay], size=(self.WIDTH, self.HEIGHT))
                    video = video.with_duration(audio_duration)
                except Exception as e:
                    logger.warning(f"Title overlay failed: {e}")

            # Generate and add karaoke subtitles if enabled
            if enable_subtitles:
                logger.info("Generating karaoke subtitles...")
                try:
                    subtitle_segments = self.generate_subtitles(audio_path)
                    renderer = SubtitleRenderer(
                        style=subtitle_style, width=self.WIDTH, height=self.HEIGHT
                    )
                    skip_time = self.TITLE_DURATION if title else 0.0
                    subtitle_clips = self._create_karaoke_clips(
                        subtitle_segments, renderer, skip_until=skip_time
                    )
                    if subtitle_clips:
                        logger.info(f"Adding {len(subtitle_clips)} karaoke subtitle overlays...")
                        video = CompositeVideoClip([video] + subtitle_clips)
                except Exception as e:
                    logger.warning(f"Subtitle generation failed: {e}")
            elif hook_text:
                video = self._add_hook_overlay(video, hook_text)

            # Prepare background music if enabled
            if enable_music and settings.music_enabled:
                music_path = self._get_random_music_file(self.music_mood)
                if music_path:
                    try:
                        music_clip = self._prepare_background_music(
                            music_path, audio_duration
                        )
                    except Exception as e:
                        logger.warning(f"Failed to load music, continuing without: {e}")
                        music_clip = None

            # Build SFX track if enabled
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

            # Mix all audio tracks (voice + music + sfx)
            audio_tracks = [voice_audio.with_volume_scaled(settings.voice_volume)]
            if music_clip:
                audio_tracks.append(music_clip)
            if sfx_clip:
                audio_tracks.append(sfx_clip)

            if len(audio_tracks) > 1:
                final_audio = CompositeAudioClip(audio_tracks)
            else:
                final_audio = audio_tracks[0]

            # Set mixed audio to video
            video = video.with_audio(final_audio)

            # Generate output path
            output_path = self.output_dir / output_filename
            if not output_path.suffix:
                output_path = output_path.with_suffix(".mp4")

            # Write video file
            video.write_videofile(
                str(output_path),
                fps=self.FPS,
                codec=self.CODEC,
                audio_codec="aac",
                temp_audiofile="temp-audio.m4a",
                remove_temp=True,
                logger="bar",
            )

            # Clean up
            voice_audio.close()
            if music_clip:
                music_clip.close()
            video.close()
            for clip in video_clips:
                clip.close()
            for clip in subtitle_clips:
                clip.close()

            return str(output_path)

        except Exception as e:
            raise VideoEditorError(f"Failed to assemble video: {e}")

    def _create_ken_burns_clip(self, image_path: str, duration: float) -> ImageClip:
        """
        Create an ImageClip with Ken Burns zoom effect.

        The effect slowly zooms from ZOOM_START to ZOOM_END over the clip duration,
        keeping the image centered.
        """
        clip = ImageClip(image_path).with_duration(duration)

        # Resize image to fill frame with room for zoom
        # Scale up initially so zoom out doesn't show edges
        base_scale = max(
            self.WIDTH / clip.w,
            self.HEIGHT / clip.h
        ) * self.ZOOM_END

        clip = clip.resized(base_scale)

        def ken_burns_effect(get_frame, t):
            """Apply zoom effect based on time"""
            # Calculate current zoom level (interpolate from ZOOM_END to ZOOM_START)
            # This creates a zoom-out effect which feels more natural
            progress = t / duration
            current_zoom = self.ZOOM_END - (progress * (self.ZOOM_END - self.ZOOM_START))

            frame = get_frame(t)

            # Calculate crop dimensions for current zoom
            crop_w = int(self.WIDTH / current_zoom)
            crop_h = int(self.HEIGHT / current_zoom)

            # Center crop
            center_x = frame.shape[1] // 2
            center_y = frame.shape[0] // 2

            x1 = max(0, center_x - crop_w // 2)
            y1 = max(0, center_y - crop_h // 2)
            x2 = x1 + crop_w
            y2 = y1 + crop_h

            cropped = frame[y1:y2, x1:x2]

            # Resize to output dimensions
            from PIL import Image
            import numpy as np

            img = Image.fromarray(cropped)
            img = img.resize((self.WIDTH, self.HEIGHT), Image.Resampling.LANCZOS)

            return np.array(img)

        # Apply the Ken Burns effect using transform
        clip = clip.transform(ken_burns_effect)

        return clip

    def _add_hook_overlay(
        self,
        video: CompositeVideoClip,
        hook_text: str
    ) -> CompositeVideoClip:
        """
        Add a text overlay with the hook for the first few seconds.
        Legacy method - subtitles are now preferred.

        Args:
            video: The video clip to add overlay to
            hook_text: The text to display

        Returns:
            CompositeVideoClip with text overlay
        """
        # Create text clip
        text_clip = TextClip(
            text=hook_text,
            font_size=60,
            color="white",
            font="Arial-Bold",
            stroke_color="black",
            stroke_width=2,
            method="caption",
            size=(self.WIDTH - 100, None),  # Width with padding
            text_align="center",
        )

        # Position in center and set duration
        text_clip = (
            text_clip
            .with_position("center")
            .with_duration(min(self.HOOK_DURATION, video.duration))
            .with_start(0)
        )

        # Composite text over video
        return CompositeVideoClip([video, text_clip])

    def _create_circle_mask(self, size: int) -> np.ndarray:
        """
        Create a circular alpha mask.

        Args:
            size: Diameter of the circle (width and height)

        Returns:
            numpy array with circular mask (255 inside, 0 outside)
        """
        y, x = np.ogrid[:size, :size]
        center = size // 2
        radius = size // 2

        # Create circular mask
        mask = ((x - center) ** 2 + (y - center) ** 2 <= radius ** 2).astype(np.uint8) * 255

        return mask

    def _apply_circle_crop(
        self,
        clip: VideoFileClip,
        target_size: int
    ) -> VideoFileClip:
        """
        Crop a video clip into a circle and resize.

        Args:
            clip: The video clip to crop
            target_size: Target diameter for the circle

        Returns:
            Video clip with circular mask applied
        """
        from PIL import Image

        # Calculate crop dimensions (square, centered on frame)
        clip_w, clip_h = clip.size
        crop_size = min(clip_w, clip_h)

        # Center crop to square
        x_center = clip_w // 2
        y_center = clip_h // 2
        x1 = x_center - crop_size // 2
        y1 = y_center - crop_size // 2

        # Crop to square
        cropped_clip = clip.cropped(x1=x1, y1=y1, width=crop_size, height=crop_size)

        # Resize to target size
        cropped_clip = cropped_clip.resized((target_size, target_size))

        # Create circular mask
        circle_mask = self._create_circle_mask(target_size)

        def apply_mask(frame):
            """Apply circular mask to frame"""
            # Convert to RGBA if needed
            if frame.shape[2] == 3:
                # Add alpha channel
                rgba = np.zeros((frame.shape[0], frame.shape[1], 4), dtype=np.uint8)
                rgba[:, :, :3] = frame
                rgba[:, :, 3] = circle_mask
                return rgba
            else:
                frame[:, :, 3] = circle_mask
                return frame

        # Apply mask using image_transform
        masked_clip = cropped_clip.image_transform(apply_mask)

        return masked_clip

    def _apply_chroma_key(
        self,
        clip: VideoFileClip,
        key_color: Optional[List[int]] = None,
        threshold: Optional[int] = None
    ) -> VideoFileClip:
        """
        Remove green screen background using chroma key.

        Args:
            clip: The video clip to process
            key_color: RGB color to key out (default: standard green)
            threshold: Color similarity threshold (default: class setting)

        Returns:
            Video clip with green screen removed (alpha channel added)
        """
        if key_color is None:
            key_color = self.CHROMA_KEY_COLOR
        if threshold is None:
            threshold = self.CHROMA_KEY_THRESHOLD

        key_color = np.array(key_color)

        def chroma_key_filter(frame):
            """Remove green screen from frame"""
            # Calculate color distance from key color
            diff = np.sqrt(np.sum((frame[:, :, :3].astype(float) - key_color) ** 2, axis=2))

            # Create alpha mask (transparent where close to key color)
            alpha = np.where(diff < threshold, 0, 255).astype(np.uint8)

            # Smooth the edges a bit
            from scipy import ndimage
            alpha = ndimage.gaussian_filter(alpha.astype(float), sigma=1)
            alpha = np.clip(alpha, 0, 255).astype(np.uint8)

            # Create RGBA frame
            if frame.shape[2] == 3:
                rgba = np.zeros((frame.shape[0], frame.shape[1], 4), dtype=np.uint8)
                rgba[:, :, :3] = frame
                rgba[:, :, 3] = alpha
                return rgba
            else:
                frame[:, :, 3] = alpha
                return frame

        return clip.image_transform(chroma_key_filter)

    def assemble_hybrid_video(
        self,
        audio_path: str,
        image_paths: List[str],
        talking_head_path: str,
        output_filename: str,
        enable_subtitles: bool = True,
        enable_music: bool = True,
        use_chroma_key: bool = False,
    ) -> str:
        """
        Assemble a hybrid video with background images and talking head overlay.

        Layer 1 (Background): Ken Burns effect on images
        Layer 2 (Foreground): Talking head video (circle cropped or chroma keyed)
        Layer 3 (Top): Word-level subtitles

        Audio comes from the talking head video, mixed with background music.

        Args:
            audio_path: Path to the original voiceover audio (for subtitles)
            image_paths: List of paths to background image files
            talking_head_path: Path to the animated talking head video
            output_filename: Name of the output video file
            enable_subtitles: If True, generate word-level subtitles
            enable_music: If True, add background music
            use_chroma_key: If True, use chroma key instead of circle crop

        Returns:
            str: Path to the generated video file

        Raises:
            VideoEditorError: If video assembly fails
        """
        if not Path(audio_path).exists():
            raise VideoEditorError(f"Audio file not found: {audio_path}")

        if not image_paths:
            raise VideoEditorError("No images provided")

        if not Path(talking_head_path).exists():
            raise VideoEditorError(f"Talking head video not found: {talking_head_path}")

        for img_path in image_paths:
            if not Path(img_path).exists():
                raise VideoEditorError(f"Image file not found: {img_path}")

        subtitle_clips = []
        music_clip = None
        clips_to_close = []

        try:
            # Load the talking head video (this determines the duration)
            logger.info("Loading talking head video...")
            talking_head = VideoFileClip(talking_head_path)
            clips_to_close.append(talking_head)
            video_duration = talking_head.duration

            # Extract audio from talking head
            talking_head_audio = talking_head.audio
            if talking_head_audio is None:
                raise VideoEditorError("Talking head video has no audio")

            logger.info(f"Video duration: {video_duration:.1f}s")

            # Calculate duration per image
            duration_per_image = video_duration / len(image_paths)

            # LAYER 1: Create background from images with Ken Burns effect
            logger.info("Creating background layer with Ken Burns effect...")
            background_clips = []
            for i, img_path in enumerate(image_paths):
                clip = self._create_ken_burns_clip(img_path, duration_per_image)
                background_clips.append(clip)
                clips_to_close.append(clip)

            background = concatenate_videoclips(background_clips, method="compose")
            clips_to_close.append(background)

            # LAYER 2: Prepare talking head overlay
            logger.info("Preparing talking head overlay...")

            # Calculate target size for talking head (30% of screen width)
            target_size = int(self.WIDTH * self.TALKING_HEAD_SIZE_RATIO)

            if use_chroma_key:
                logger.info("Applying chroma key to talking head...")
                processed_head = self._apply_chroma_key(talking_head)
                # Resize to target size (maintain aspect ratio)
                scale = target_size / min(talking_head.w, talking_head.h)
                processed_head = processed_head.resized(scale)
            else:
                logger.info("Applying circle crop to talking head...")
                processed_head = self._apply_circle_crop(talking_head, target_size)

            clips_to_close.append(processed_head)

            # Calculate position for talking head (bottom-right with padding)
            if self.TALKING_HEAD_POSITION == "bottom-right":
                head_x = self.WIDTH - target_size - self.TALKING_HEAD_PADDING
                head_y = self.HEIGHT - target_size - self.TALKING_HEAD_PADDING - 200  # Extra padding for subtitles
            elif self.TALKING_HEAD_POSITION == "bottom-left":
                head_x = self.TALKING_HEAD_PADDING
                head_y = self.HEIGHT - target_size - self.TALKING_HEAD_PADDING - 200
            elif self.TALKING_HEAD_POSITION == "top-right":
                head_x = self.WIDTH - target_size - self.TALKING_HEAD_PADDING
                head_y = self.TALKING_HEAD_PADDING
            else:  # top-left
                head_x = self.TALKING_HEAD_PADDING
                head_y = self.TALKING_HEAD_PADDING

            # Position the talking head
            positioned_head = processed_head.with_position((head_x, head_y))

            # Composite background and talking head
            composite = CompositeVideoClip(
                [background, positioned_head],
                size=(self.WIDTH, self.HEIGHT)
            )
            clips_to_close.append(composite)

            # LAYER 3: Generate and add subtitles if enabled
            if enable_subtitles:
                logger.info("Generating subtitles...")
                try:
                    subtitle_segments = self.generate_subtitles(audio_path)
                    subtitle_clips = self._create_subtitle_clips(subtitle_segments)

                    if subtitle_clips:
                        logger.info(f"Adding {len(subtitle_clips)} subtitle overlays...")
                        composite = CompositeVideoClip(
                            [composite] + subtitle_clips,
                            size=(self.WIDTH, self.HEIGHT)
                        )
                except Exception as e:
                    logger.warning(f"Subtitle generation failed, continuing without: {e}")

            # AUDIO: Use audio from talking head, mix with background music
            voice_audio = talking_head_audio.with_volume_scaled(settings.voice_volume)

            if enable_music and settings.music_enabled:
                music_path = self._get_random_music_file(self.music_mood)
                if music_path:
                    try:
                        music_clip = self._prepare_background_music(music_path, video_duration)
                    except Exception as e:
                        logger.warning(f"Failed to load music: {e}")
                        music_clip = None

            # Mix audio tracks
            final_audio = self._mix_audio(voice_audio, music_clip)

            # Set audio to composite
            final_video = composite.with_audio(final_audio)

            # Generate output path
            output_path = self.output_dir / output_filename
            if not output_path.suffix:
                output_path = output_path.with_suffix(".mp4")

            # Write video file
            logger.info(f"Rendering hybrid video to {output_path}...")
            final_video.write_videofile(
                str(output_path),
                fps=self.FPS,
                codec=self.CODEC,
                audio_codec="aac",
                temp_audiofile="temp-audio.m4a",
                remove_temp=True,
                logger="bar",
            )

            # Clean up
            for clip in clips_to_close:
                try:
                    clip.close()
                except Exception:
                    pass
            for clip in subtitle_clips:
                try:
                    clip.close()
                except Exception:
                    pass
            if music_clip:
                try:
                    music_clip.close()
                except Exception:
                    pass

            return str(output_path)

        except Exception as e:
            # Clean up on error
            for clip in clips_to_close:
                try:
                    clip.close()
                except Exception:
                    pass
            raise VideoEditorError(f"Failed to assemble hybrid video: {e}")

    def add_music_to_video(
        self,
        video_path: str,
        output_filename: str,
    ) -> str:
        """
        Add background music to an existing video file.

        Used for persona mode to add music to animated portraits.

        Args:
            video_path: Path to the input video file
            output_filename: Name of the output video file

        Returns:
            str: Path to the output video with music

        Raises:
            VideoEditorError: If processing fails
        """
        from moviepy import VideoFileClip

        if not Path(video_path).exists():
            raise VideoEditorError(f"Video file not found: {video_path}")

        music_clip = None

        try:
            # Load the video
            video = VideoFileClip(video_path)
            video_duration = video.duration

            # Get background music
            music_path = self._get_random_music_file(self.music_mood)
            if music_path:
                try:
                    music_clip = self._prepare_background_music(music_path, video_duration)
                except Exception as e:
                    logger.warning(f"Failed to load music: {e}")
                    music_clip = None

            # Mix audio if music available
            if music_clip and video.audio:
                # Get original video audio
                original_audio = video.audio.with_volume_scaled(settings.voice_volume)
                # Composite with music
                mixed_audio = CompositeAudioClip([music_clip, original_audio])
                video = video.with_audio(mixed_audio)
            elif music_clip:
                # Video has no audio, just add music
                video = video.with_audio(music_clip)

            # Generate output path
            output_path = self.output_dir / output_filename
            if not output_path.suffix:
                output_path = output_path.with_suffix(".mp4")

            # Write video file
            video.write_videofile(
                str(output_path),
                fps=self.FPS,
                codec=self.CODEC,
                audio_codec="aac",
                temp_audiofile="temp-audio.m4a",
                remove_temp=True,
                logger="bar",
            )

            # Clean up
            video.close()
            if music_clip:
                music_clip.close()

            return str(output_path)

        except Exception as e:
            raise VideoEditorError(f"Failed to add music to video: {e}")


def assemble_video(
    audio_path: str,
    image_paths: List[str],
    output_filename: str,
    hook_text: Optional[str] = None,
    enable_subtitles: bool = True,
    enable_music: bool = True,
) -> str:
    """
    Convenience function to assemble a video.

    Args:
        audio_path: Path to the voiceover audio file
        image_paths: List of paths to image files
        output_filename: Name of the output video file
        hook_text: Optional text to overlay for the first 3 seconds
        enable_subtitles: If True, generate word-level subtitles from audio
        enable_music: If True, add background music with ducking

    Returns:
        str: Path to the generated video file
    """
    editor = VideoEditor()
    return editor.assemble_video(
        audio_path, image_paths, output_filename, hook_text,
        enable_subtitles, enable_music
    )
