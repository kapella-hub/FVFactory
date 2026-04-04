"""CinematicEngine — multi-shot editing, audio-reactive cuts, particles,
transitions, and smooth camera motion for professional-grade video assembly.
"""

import logging
import math
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
        motion_clip_paths: list[str] = None,
    ) -> str:
        """Render a cinematic video. Returns path to output file."""
        logger.info("=== Cinematic Engine: Starting render ===")

        # 1. Analyze audio
        logger.info("Analyzing audio...")
        audio_info = analyze_audio(audio_path)
        audio_duration = audio_info["duration"]

        # 2. Calculate scene durations from scene_texts
        scene_durations = self._calc_durations(audio_duration, scene_texts, len(image_paths))

        # 3. Prepare scene data — upscale images for motion headroom, extract multi-shot crops
        logger.info("Preparing scenes...")
        scene_data = []
        for i, img_path in enumerate(image_paths):
            img = np.array(Image.open(img_path).convert("RGB").resize((WIDTH, HEIGHT), Image.LANCZOS))
            # Upscale 1.4x for zoom/pan headroom
            big = np.array(Image.fromarray(img).resize(
                (int(WIDTH * 1.4), int(HEIGHT * 1.4)), Image.LANCZOS))
            shots = extract_shots(img)

            # Plan cuts for this scene based on audio emphasis within scene time window
            scene_start = sum(scene_durations[:i])
            scene_end = scene_start + scene_durations[i]
            local_emphasis = [
                t - scene_start for t in audio_info["emphasis_points"]
                if scene_start <= t < scene_end
            ]
            cuts = plan_cuts(scene_durations[i], local_emphasis)

            # Assign a unique camera motion style per scene
            motion_style = random.choice([
                "zoom_in_slow", "zoom_out_drift", "pan_left", "pan_right",
                "pan_up_zoom", "diagonal_drift", "push_in_rotate",
            ])

            # Check if we have a motion clip for this scene
            motion_clip = None
            if motion_clip_paths and i < len(motion_clip_paths) and motion_clip_paths[i]:
                motion_clip = motion_clip_paths[i]

            scene_data.append({
                "image": img,
                "big": big,
                "shots": shots,
                "cuts": cuts,
                "duration": scene_durations[i],
                "start": scene_start,
                "motion_style": motion_style,
                "motion_clip": motion_clip,
            })

        logger.info("Scene preparation complete for %d scenes", len(scene_data))

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
            try:
                from app.video_editor import VideoEditor
                ve = VideoEditor()
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
            try:
                from app.video_editor import VideoEditor
                ve = VideoEditor(music_mood=music_mood)
                music_path = ve._get_random_music_file(music_mood)
                if music_path:
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
        if scene_texts and len(scene_texts) == num_scenes:
            words = [max(len(t.split()), 1) for t in scene_texts]
            total_words = sum(words)
            return [total * w / total_words for w in words]
        return [total / num_scenes] * num_scenes

    def _render_scene(self, sd: dict, audio_info: dict,
                      particles: ParticleSystem) -> VideoClip:
        """Render a scene. Uses motion clip if available, falls back to image animation."""
        from moviepy import VideoFileClip

        duration = sd["duration"]
        motion_clip = sd.get("motion_clip")
        scene_start = sd["start"]

        # If we have a real motion clip from fal.ai, USE IT
        if motion_clip and Path(motion_clip).exists():
            logger.info("  Using motion clip: %s", Path(motion_clip).name)
            raw = VideoFileClip(motion_clip)
            raw = raw.resized((WIDTH, HEIGHT))

            # Adjust speed to fill scene duration
            if raw.duration and abs(raw.duration - duration) > 0.5:
                speed = raw.duration / duration
                clip = raw.with_speed_scaled(speed)
            else:
                clip = raw.with_duration(min(raw.duration, duration))

            # Extend with freeze-frame if clip is shorter than scene
            if clip.duration < duration:
                gap = duration - clip.duration
                last_frame = clip.get_frame(clip.duration - 0.04)
                ext = ImageClip(last_frame).with_duration(gap).with_fps(FPS)
                clip = concatenate_videoclips([clip, ext], method="compose")

            clip = clip.with_duration(duration)

            # Overlay particles on the motion clip
            particles_sys = particles

            def add_particles(get_frame, t):
                frame = get_frame(t)
                pf = particles_sys.render_frame(scene_start + t)
                if pf.shape[2] == 4:
                    alpha = pf[:, :, 3:4].astype(np.float32) / 255.0
                    rgb = pf[:, :, :3].astype(np.float32)
                    frame = (frame.astype(np.float32) * (1 - alpha) + rgb * alpha).astype(np.uint8)
                return frame

            return clip.transform(add_particles).with_fps(FPS)

        # FALLBACK: No motion clip — use image animation
        logger.info("  No motion clip, using image animation")
        big = sd["big"]
        big_h, big_w = big.shape[:2]
        motion_style = sd["motion_style"]

        def make_frame(t):
            progress = t / max(duration, 0.01)
            ease = 0.5 - 0.5 * math.cos(math.pi * progress)
            energy = self._get_energy_at(audio_info, scene_start + t)
            zoom_punch = energy * 0.01

            frame = self._apply_motion(big, big_w, big_h, ease, motion_style, zoom_punch)

            pf = particles.render_frame(scene_start + t)
            if pf.shape[2] == 4:
                alpha = pf[:, :, 3:4].astype(np.float32) / 255.0
                rgb = pf[:, :, :3].astype(np.float32)
                frame = (frame.astype(np.float32) * (1 - alpha) + rgb * alpha).astype(np.uint8)

            return frame

        return VideoClip(make_frame, duration=duration).with_fps(FPS)

    def _apply_motion(self, src: np.ndarray, src_w: int, src_h: int,
                      t: float, style: str, zoom_punch: float = 0.0) -> np.ndarray:
        """Apply camera motion to an upscaled source image. Returns WIDTH x HEIGHT frame."""
        margin_x = src_w - WIDTH
        margin_y = src_h - HEIGHT
        cx = margin_x // 2
        cy = margin_y // 2

        if style == "zoom_in_slow":
            zoom = 1.0 + t * 0.12 + zoom_punch
            cw = max(int(WIDTH / zoom), 1)
            ch = max(int(HEIGHT / zoom), 1)
            x1 = (src_w - cw) // 2
            y1 = (src_h - ch) // 2
            crop = src[y1:y1+ch, x1:x1+cw]
            return np.array(Image.fromarray(crop).resize((WIDTH, HEIGHT), Image.LANCZOS))

        elif style == "zoom_out_drift":
            zoom = 1.12 - t * 0.1 + zoom_punch
            drift_x = int(margin_x * 0.15 * t)
            cw = max(int(WIDTH / zoom), 1)
            ch = max(int(HEIGHT / zoom), 1)
            x1 = max(0, min((src_w - cw) // 2 + drift_x, src_w - cw))
            y1 = (src_h - ch) // 2
            crop = src[y1:y1+ch, x1:x1+cw]
            return np.array(Image.fromarray(crop).resize((WIDTH, HEIGHT), Image.LANCZOS))

        elif style == "pan_left":
            x1 = cx + int(margin_x * 0.3 * (1.0 - t))
            y1 = cy + int(margin_y * 0.04 * math.sin(t * math.pi))
            x1 = max(0, min(x1, margin_x))
            y1 = max(0, min(y1, margin_y))

        elif style == "pan_right":
            x1 = cx - int(margin_x * 0.3 * (1.0 - t))
            y1 = cy - int(margin_y * 0.04 * math.sin(t * math.pi))
            x1 = max(0, min(x1, margin_x))
            y1 = max(0, min(y1, margin_y))

        elif style == "pan_up_zoom":
            zoom = 1.0 + t * 0.08 + zoom_punch
            y_drift = int(margin_y * 0.4 * (1.0 - t))
            cw = max(int(WIDTH / zoom), 1)
            ch = max(int(HEIGHT / zoom), 1)
            x1 = (src_w - cw) // 2
            y1 = max(0, min(cy + y_drift, src_h - ch))
            crop = src[y1:y1+ch, x1:x1+cw]
            return np.array(Image.fromarray(crop).resize((WIDTH, HEIGHT), Image.LANCZOS))

        elif style == "push_in_rotate":
            zoom = 1.0 + t * 0.1 + zoom_punch
            angle = t * 0.8  # very subtle rotation
            cw = max(int(WIDTH / zoom), 1)
            ch = max(int(HEIGHT / zoom), 1)
            x1 = (src_w - cw) // 2
            y1 = (src_h - ch) // 2
            crop = src[y1:y1+ch, x1:x1+cw]
            pil = Image.fromarray(crop).resize((WIDTH, HEIGHT), Image.LANCZOS)
            pil = pil.rotate(angle, resample=Image.BICUBIC, expand=False)
            return np.array(pil)

        elif style == "diagonal_drift":
            x1 = cx + int(margin_x * 0.2 * t)
            y1 = cy + int(margin_y * 0.15 * t)

        else:
            x1 = cx
            y1 = cy

        # Simple crop for pan styles
        x1 = max(0, min(x1, margin_x))
        y1 = max(0, min(y1, margin_y))
        return src[y1:y1+HEIGHT, x1:x1+WIDTH]

    def _get_energy_at(self, audio_info: dict, time: float) -> float:
        times = audio_info["times"]
        envelope = audio_info["energy_envelope"]
        if not times or len(times) < 2:
            return 0.5
        hop = max(times[1] - times[0], 0.001)
        idx = min(int(time / hop), len(envelope) - 1)
        idx = max(0, idx)
        return envelope[idx]

    def _apply_transitions(self, clips: list, scene_data: list) -> list:
        if len(clips) <= 1:
            return clips

        transition_types = list(TRANSITIONS.keys())
        result = []
        trans_duration = 0.6

        for i, clip in enumerate(clips):
            if i == 0:
                result.append(clip)
                continue

            trans_name = transition_types[i % len(transition_types)]
            trans_fn = TRANSITIONS[trans_name]

            try:
                prev_clip = clips[i - 1]
                frame_a = prev_clip.get_frame(max(prev_clip.duration - 0.04, 0))
                frame_b = clip.get_frame(min(0.04, clip.duration))

                def make_trans_frame(t, fa=frame_a, fb=frame_b, fn=trans_fn, td=trans_duration):
                    progress = min(t / td, 1.0)
                    return fn(fa, fb, progress)

                trans_clip = VideoClip(make_trans_frame, duration=trans_duration).with_fps(FPS)

                trimmed_prev = result[-1].with_duration(
                    max(result[-1].duration - trans_duration / 2, 0.5))
                result[-1] = trimmed_prev
                result.append(trans_clip)

                trimmed_curr = clip.subclipped(min(trans_duration / 2, clip.duration - 0.1))
                result.append(trimmed_curr)
            except Exception as e:
                logger.warning("Transition %d failed (%s): %s", i, trans_name, e)
                result.append(clip)

        return result
