"""CinematicEngine — orchestrates depth parallax, multi-shot editing,
audio-reactive cuts, particles, transitions, and kinetic typography
into a professional-grade video assembly pipeline.
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
        """Render a cinematic video. Returns path to output file."""
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
        duration = sd["duration"]
        layers = sd["layers"]
        shots = sd["shots"]
        cuts = sd["cuts"]
        scene_start = sd["start"]

        shot_map = {s["type"]: s["crop"] for s in shots}
        cam_motion = random.choice(["drift_right", "drift_left", "drift_up", "push_in"])

        def make_frame(t):
            # Determine active cut
            active_cut = cuts[0]
            for cut in cuts:
                if t >= cut["time"]:
                    active_cut = cut

            shot_type = active_cut["shot_type"]
            progress = t / max(duration, 0.01)
            cam_x, cam_y, cam_zoom = self._camera_motion(progress, cam_motion, audio_info,
                                                          scene_start + t)

            if shot_type in ("wide", "medium"):
                frame = render_parallax_frame(
                    layers, progress,
                    camera_x=cam_x, camera_y=cam_y, camera_zoom=cam_zoom,
                    out_w=WIDTH, out_h=HEIGHT,
                )
            else:
                base = shot_map.get(shot_type, shot_map.get("wide", sd["image"]))
                zoom = 1.0 + progress * 0.1
                h, w = base.shape[:2]
                cw = max(int(w / zoom), 1)
                ch = max(int(h / zoom), 1)
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

        return VideoClip(make_frame, duration=duration).with_fps(FPS)

    def _camera_motion(self, progress: float, style: str,
                       audio_info: dict, global_time: float) -> tuple:
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
        energy = self._get_energy_at(audio_info, global_time)
        zoom_punch = energy * 0.05

        return base_x, base_y, base_zoom + zoom_punch

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
        trans_duration = 0.4

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
