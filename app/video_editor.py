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
    CompositeVideoClip,
    CompositeAudioClip,
    concatenate_videoclips,
    concatenate_audioclips,
)

from app.config import settings

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

    def __init__(self):
        self.output_dir = Path(settings.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._whisper_model = None
        self.music_dir = Path(settings.music_dir)

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

    def _get_random_music_file(self) -> Optional[Path]:
        """
        Get a random music file from the music directory.

        Returns:
            Path to a random music file, or None if no music files found
        """
        if not self.music_dir.exists():
            logger.warning(f"Music directory not found: {self.music_dir}")
            return None

        music_files = [
            f for f in self.music_dir.iterdir()
            if f.is_file() and f.suffix.lower() in self.MUSIC_EXTENSIONS
        ]

        if not music_files:
            logger.warning(f"No music files found in {self.music_dir}")
            return None

        selected = random.choice(music_files)
        logger.info(f"Selected background music: {selected.name}")
        return selected

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

    def assemble_video(
        self,
        audio_path: str,
        image_paths: List[str],
        output_filename: str,
        hook_text: Optional[str] = None,
        enable_subtitles: bool = True,
        enable_music: bool = True,
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

            # Calculate duration per image
            duration_per_image = audio_duration / len(image_paths)

            # Create image clips with Ken Burns effect
            video_clips = []
            for i, img_path in enumerate(image_paths):
                clip = self._create_ken_burns_clip(img_path, duration_per_image)
                video_clips.append(clip)

            # Concatenate all image clips
            video = concatenate_videoclips(video_clips, method="compose")

            # Generate and add subtitles if enabled
            if enable_subtitles:
                logger.info("Generating subtitles...")
                try:
                    subtitle_segments = self.generate_subtitles(audio_path)
                    subtitle_clips = self._create_subtitle_clips(subtitle_segments)

                    if subtitle_clips:
                        logger.info(f"Adding {len(subtitle_clips)} subtitle overlays...")
                        video = CompositeVideoClip([video] + subtitle_clips)
                except Exception as e:
                    logger.warning(f"Subtitle generation failed, continuing without: {e}")

            # Legacy hook overlay (if subtitles disabled and hook provided)
            elif hook_text:
                video = self._add_hook_overlay(video, hook_text)

            # Prepare background music if enabled
            if enable_music and settings.music_enabled:
                music_path = self._get_random_music_file()
                if music_path:
                    try:
                        music_clip = self._prepare_background_music(
                            music_path, audio_duration
                        )
                    except Exception as e:
                        logger.warning(f"Failed to load music, continuing without: {e}")
                        music_clip = None

            # Mix audio tracks (voice + music)
            final_audio = self._mix_audio(voice_audio, music_clip)

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
            music_path = self._get_random_music_file()
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
