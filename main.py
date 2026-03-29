"""
FVFactory - Automated short-form video creation

Pipeline: Topic -> Script -> Audio/Images or Animated Portrait -> MP4
"""

import argparse
import logging
import sys
from datetime import datetime
from typing import Optional

from app.config import settings
from app.content_engine import ScriptGenerator, ScriptGeneratorError
from app.asset_manager import AssetManager, AssetManagerError
from app.video_editor import VideoEditor, VideoEditorError
from app.animator import PortraitAnimator, AnimatorError
from app.trend_scout import TrendScout
from app.motion_gen import MotionGenerator
from app.cost_tracker import CostTracker
from app.metadata_gen import MetadataGenerator
from app.uploader import YouTubeUploader, UploaderError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


def validate_config() -> bool:
    """Validate that required API keys are configured for selected providers."""
    errors = []

    # LLM: only need OpenAI key if using OpenAI provider
    if settings.llm_provider == "openai" or settings.provider_mode == "api":
        if not settings.openai_api_key:
            errors.append("OPENAI_API_KEY is required when llm_provider=openai")

    # Image: only need Replicate key if using Replicate provider
    if settings.image_provider == "replicate" or settings.provider_mode == "api":
        if not settings.replicate_api_token:
            errors.append("REPLICATE_API_TOKEN is required when image_provider=replicate")

    # Motion: only need Replicate key if using Replicate provider
    if settings.motion_provider == "replicate" or settings.provider_mode == "api":
        if not settings.replicate_api_token:
            errors.append("REPLICATE_API_TOKEN is required when motion_provider=replicate")

    # TTS: always needs at least one TTS key
    if not settings.elevenlabs_api_key and not settings.openai_api_key:
        errors.append("ELEVENLABS_API_KEY or OPENAI_API_KEY required for audio")

    if errors:
        for error in errors:
            logger.error(error)
        return False

    return True


def generate_output_filename(topic: str) -> str:
    """Generate a unique output filename based on topic and timestamp."""
    # Sanitize topic for filename
    safe_topic = "".join(c if c.isalnum() or c in " -_" else "" for c in topic)
    safe_topic = safe_topic.strip().replace(" ", "_")[:30]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    return f"{safe_topic}_{timestamp}.mp4"


def resolve_voice(voice: Optional[str] = None, niche: Optional[str] = None,
                   video_style: Optional[str] = None) -> Optional[str]:
    """Resolve a voice preset name or 'auto' to an ElevenLabs voice ID.

    When voice is 'auto', picks based on niche and video style:
    - Niche mapping is primary (stoicism→bill, tech→daniel, etc.)
    - Video style adjusts the default when niche has no specific mapping:
      energetic styles (cartoon, anime, pixel_art, comic_book) → josh
      dramatic styles (noir, oil_painting) → bill
      artistic styles (watercolor, illustration, stop_motion) → george
      technical styles (3d_render, photorealistic) → daniel

    Returns None to use the default from config.
    """
    if not voice:
        return None

    if voice == "auto":
        niche_key = (niche or "").lower().strip()

        # First try niche-specific mapping
        preset = settings.voice_niche_map.get(niche_key)

        # If no niche match, use video style to pick voice
        if not preset and video_style:
            STYLE_VOICE = {
                "cartoon": "josh",
                "anime": "josh",
                "pixel_art": "josh",
                "comic_book": "josh",
                "noir": "bill",
                "oil_painting": "bill",
                "watercolor": "george",
                "illustration": "george",
                "stop_motion": "george",
                "3d_render": "daniel",
                "photorealistic": "daniel",
            }
            preset = STYLE_VOICE.get(video_style)

        preset = preset or "george"  # safe default
        voice_id = settings.voice_presets.get(preset)
        logger.info(f"Auto-selected voice '{preset}' for niche='{niche_key}' style='{video_style or ''}'")
        return voice_id

    # Direct preset name
    if voice.lower() in settings.voice_presets:
        return settings.voice_presets[voice.lower()]

    # Assume it's a raw ElevenLabs voice ID
    return voice


def resolve_music_mood(niche: Optional[str] = None, video_style: Optional[str] = None) -> str:
    """Pick a music mood based on niche and video style.

    Returns a mood string matching a subfolder in assets/music/:
      epic, chill, upbeat, dark, cinematic

    Falls back to empty string (root music dir) if no match.
    """
    # Style takes priority for mood
    STYLE_MOOD = {
        "cartoon": "upbeat",
        "anime": "epic",
        "pixel_art": "upbeat",
        "comic_book": "epic",
        "stop_motion": "upbeat",
        "noir": "dark",
        "oil_painting": "cinematic",
        "watercolor": "chill",
        "illustration": "chill",
        "3d_render": "cinematic",
        "photorealistic": "cinematic",
    }

    NICHE_MOOD = {
        "stoicism": "cinematic",
        "philosophy": "chill",
        "self-improvement": "epic",
        "motivation": "epic",
        "history": "cinematic",
        "science": "cinematic",
        "tech": "upbeat",
        "technology": "upbeat",
        "finance": "cinematic",
        "crypto": "dark",
        "gaming": "upbeat",
        "entertainment": "upbeat",
        "pop culture": "upbeat",
        "health": "chill",
        "lifestyle": "chill",
    }

    mood = ""
    if video_style:
        mood = STYLE_MOOD.get(video_style, "")
    if not mood and niche:
        mood = NICHE_MOOD.get(niche.lower().strip(), "")

    logger.info(f"Music mood: '{mood}' for niche='{niche or ''}' style='{video_style or ''}'")
    return mood


def resolve_subtitle_style(subtitle_style: str, video_style: Optional[str] = None) -> str:
    """Auto-select subtitle style based on video style when set to 'auto' or default.

    Available styles: bold_impact, clean_minimal, neon_glow, fire
    """
    if subtitle_style == "auto" and video_style:
        STYLE_SUBTITLE = {
            "cartoon": "bold_impact",
            "anime": "neon_glow",
            "pixel_art": "neon_glow",
            "comic_book": "bold_impact",
            "stop_motion": "bold_impact",
            "noir": "clean_minimal",
            "oil_painting": "clean_minimal",
            "watercolor": "clean_minimal",
            "3d_render": "neon_glow",
            "illustration": "clean_minimal",
            "photorealistic": "fire",
        }
        resolved = STYLE_SUBTITLE.get(video_style, "bold_impact")
        logger.info(f"Auto-selected subtitle style '{resolved}' for video style '{video_style}'")
        return resolved
    return subtitle_style


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
    voice: Optional[str] = None,
    upload: bool = False,
    niche: Optional[str] = None,
    # V3 parameters
    video_style: str = "",
    video_duration: str = "",
) -> str:
    """
    Run the full video generation pipeline.

    Args:
        topic: The topic for the video
        use_mock_images: If True, use placeholder images instead of DALL-E
        enable_subtitles: If True, generate word-level subtitles using Whisper
        enable_music: If True, add background music with ducking
        persona: Optional persona image filename for hybrid/talking head mode
        use_chroma_key: If True, use chroma key for green screen personas
        enable_motion: If True, generate motion clips via Minimax
        subtitle_style: Subtitle preset name (default bold_impact)
        enable_sfx: If True, enable sound effects

    Returns:
        str: Path to the generated video file

    Raises:
        Exception: If any step of the pipeline fails
    """
    asset_manager = None

    try:
        # Step 1: Generate Script
        logger.info("Generating script...")
        script_gen = ScriptGenerator()
        # Use v2 script generation when motion is enabled
        script = script_gen.generate_script(
            topic, enable_v2=enable_motion,
            video_style=video_style, video_duration=video_duration,
        )

        # Resolve subtitle style based on video style if set to auto
        subtitle_style = resolve_subtitle_style(subtitle_style, video_style)
        logger.info("Script generated successfully!")
        print()
        print("=" * 50)
        print("GENERATED SCRIPT")
        print("=" * 50)
        print(f"\nHOOK: {script.hook}")
        print(f"\nBODY:\n{script.body}")

        # Always show image prompts (needed for hybrid mode too)
        print(f"\nIMAGE PROMPTS:")
        for i, prompt in enumerate(script.image_prompts, 1):
            print(f"  {i}. {prompt}")

        print(f"\nKEYWORDS: {', '.join(script.keywords)}")
        print("=" * 50)
        print()

        # Step 2: Generate Audio
        logger.info("Generating audio narration...")
        asset_manager = AssetManager()

        # Combine hook and body for narration
        full_narration = f"{script.hook} {script.body}"
        audio_result = asset_manager.generate_audio(full_narration, voice_id=voice)

        logger.info(f"Audio generated: {audio_result.duration:.1f} seconds")

        # Step 3: Generate visuals
        output_filename = generate_output_filename(topic)

        # Always generate background images (for both standard and hybrid mode)
        logger.info("Generating background images...")
        image_paths = asset_manager.generate_images(
            script.image_prompts,
            use_mock=use_mock_images
        )
        logger.info(f"Generated {len(image_paths)} images")

        # Generate motion clips if enabled
        motion_clip_paths = None
        if enable_motion and script.motion_prompts and not use_mock_images:
            logger.info("Generating motion clips...")
            motion_gen = MotionGenerator()
            motion_clip_paths = motion_gen.generate_all_clips(
                image_paths, script.motion_prompts
            )
            success = sum(1 for c in motion_clip_paths if c is not None)
            logger.info(f"Motion clips: {success}/{len(motion_clip_paths)} generated")

        # Check if hybrid mode is requested and possible
        animated_video_path = None
        use_hybrid_mode = False

        if persona:
            # HYBRID MODE: Background images + Talking head overlay
            logger.info(f"Using hybrid mode with persona: {persona}")

            animator = PortraitAnimator()
            persona_path = animator.get_persona_path(persona)

            if not persona_path:
                raise AnimatorError(f"Persona not found: {persona}")

            # Generate animated portrait (may return None if content filter blocks)
            logger.info("Generating animated portrait with SadTalker...")
            animated_video_path = animator.animate_portrait(
                audio_path=audio_result.file_path,
                persona_image_path=str(persona_path),
                output_filename=f"animated_{output_filename}"
            )

            if animated_video_path:
                logger.info(f"Portrait animation complete: {animated_video_path}")
                use_hybrid_mode = True
            else:
                logger.warning("Portrait animation failed (content filter), falling back to standard mode")

        if use_hybrid_mode and animated_video_path:
            # Render hybrid video (background images + talking head overlay)
            logger.info("Rendering hybrid video...")
            video_editor = VideoEditor(music_mood=resolve_music_mood(niche, video_style))

            output_path = video_editor.assemble_hybrid_video(
                audio_path=audio_result.file_path,
                image_paths=image_paths,
                talking_head_path=animated_video_path,
                output_filename=output_filename,
                enable_subtitles=enable_subtitles,
                enable_music=enable_music,
                use_chroma_key=use_chroma_key,
            )

        else:
            # STANDARD MODE: Just background images
            logger.info("Rendering video...")
            video_editor = VideoEditor(music_mood=resolve_music_mood(niche, video_style))

            output_path = video_editor.assemble_video(
                audio_path=audio_result.file_path,
                image_paths=image_paths,
                output_filename=output_filename,
                hook_text=script.hook,
                enable_subtitles=enable_subtitles,
                enable_music=enable_music,
                # V2 params
                motion_clip_paths=motion_clip_paths,
                pacing_hints=script.pacing_hints if script.pacing_hints else None,
                subtitle_style=subtitle_style,
                color_grade=settings.color_grade if settings.color_grade else None,
                enable_sfx=enable_sfx,
                title=script.hook,
                scene_texts=script.scene_texts if script.scene_texts else None,
                # V3 params
                cinematic=True,
                video_style=video_style,
            )

        logger.info(f"Video rendered successfully: {output_path}")

        # Cost tracking
        video_id = output_filename.replace(".mp4", "")
        tracker = CostTracker()
        tracker.log_cost(video_id, "openai_gpt4o")

        if settings.elevenlabs_api_key:
            chars = len(full_narration)
            tracker.log_cost(video_id, "elevenlabs_tts", quantity=max(1, chars // 1000))
        elif settings.openai_api_key:
            chars = len(full_narration)
            tracker.log_cost(video_id, "openai_tts", quantity=max(1, chars // 1000))

        if not use_mock_images:
            tracker.log_cost(video_id, "flux_image", quantity=len(image_paths))

        if motion_clip_paths:
            success_count = sum(1 for c in motion_clip_paths if c is not None)
            if success_count > 0:
                tracker.log_cost(video_id, "minimax_video", quantity=success_count)

        tracker.save()
        total_cost = tracker.get_video_cost(video_id)
        logger.info(f"Total cost for this video: ${total_cost:.2f}")

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

        # Upload to YouTube if requested
        if upload:
            try:
                yt_uploader = YouTubeUploader()
                video_url = yt_uploader.upload(
                    video_path=output_path,
                    video_id=video_id,
                    niche=niche,
                )
                logger.info(f"YouTube upload complete: {video_url}")
            except UploaderError as e:
                logger.error(f"YouTube upload failed: {e}")

        # Step 5: Cleanup temporary assets
        logger.info("Cleaning up temporary files...")
        asset_manager.cleanup_temp()
        logger.info("Cleanup complete")

        return output_path

    except (ScriptGeneratorError, AssetManagerError, VideoEditorError, AnimatorError) as e:
        logger.error(f"Pipeline failed: {e}")
        # Attempt cleanup even on failure
        if asset_manager:
            try:
                asset_manager.cleanup_temp()
            except Exception:
                pass
        raise


def list_personas() -> list:
    """List available personas."""
    animator = PortraitAnimator()
    return animator.get_available_personas()


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="FVFactory v2 - Short-form Video Generator"
    )

    parser.add_argument("--auto", action="store_true",
                        help="Auto mode (discover trend, generate, render)")
    parser.add_argument("--batch", type=int, default=None,
                        help="Batch mode (generate N videos)")
    parser.add_argument("--series", type=str, default=None,
                        help="Series mode topic")
    parser.add_argument("--parts", type=int, default=3,
                        help="Number of parts for series (default 3)")
    parser.add_argument("--niche", type=str, default=None,
                        help="Niche filter")
    parser.add_argument("--topic", type=str, default=None,
                        help="Provide topic directly")
    parser.add_argument("--no-motion", action="store_true",
                        help="Skip Minimax, use Ken Burns")
    parser.add_argument("--subtitle-style", type=str, default="bold_impact",
                        help="Subtitle preset (default bold_impact)")
    parser.add_argument("--no-sfx", action="store_true",
                        help="Disable SFX")
    parser.add_argument("--no-music", action="store_true",
                        help="Disable music")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock images")
    parser.add_argument("--voice", type=str, default=None,
                        help="Voice preset (bill, george, daniel, josh, rachel, auto) or ElevenLabs voice ID")
    parser.add_argument("--upload", action="store_true",
                        help="Upload to YouTube after rendering")
    parser.add_argument("--local", action="store_true",
                        help="Use all local models (no API calls for LLM/image/video)")
    parser.add_argument("--api", action="store_true",
                        help="Use all API models (original behavior)")
    parser.add_argument("--serve", action="store_true",
                        help="Start the FastAPI web server")
    parser.add_argument("--classic", action="store_true",
                        help="Use classic Ken Burns video assembly instead of cinematic engine")

    return parser.parse_args(argv)


def run_auto_mode(args):
    """Run in auto mode: discover trend, generate, render."""
    count = args.batch or 1

    for i in range(count):
        if args.topic:
            topic = args.topic
        else:
            scout = TrendScout()
            topics = scout.discover_topics(niche=args.niche, count=1)
            if not topics:
                logger.error("No trending topics found")
                continue
            topic = topics[0].title

        logger.info(f"[{i+1}/{count}] Auto generating: {topic}")

        # Resolve voice (supports "auto" to pick based on niche)
        voice_id = resolve_voice(args.voice, niche=args.niche)

        try:
            run_pipeline(
                topic=topic,
                use_mock_images=args.mock,
                enable_music=not args.no_music,
                enable_motion=not args.no_motion,
                subtitle_style=args.subtitle_style,
                enable_sfx=not args.no_sfx,
                voice=voice_id,
                upload=args.upload,
                niche=args.niche,
            )
        except Exception as e:
            logger.error(f"Failed: {e}")
            continue


def run_interactive_mode(args):
    """Run in interactive mode with user prompts."""
    # Get topic from user
    try:
        topic = input("Enter video topic: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        sys.exit(0)

    if not topic:
        logger.error("Topic cannot be empty")
        sys.exit(1)

    print()
    logger.info(f"Starting video generation for topic: '{topic}'")
    print()

    # Check for available personas
    personas = list_personas()
    selected_persona = None
    use_chroma_key = False

    if personas and (settings.hedra_api_key or settings.replicate_api_token):
        print("Available Personas (Hybrid Mode - Background Images + Talking Head):")
        print("  0. None (use image slideshow only)")
        for i, persona in enumerate(personas, 1):
            print(f"  {i}. {persona}")

        try:
            choice = input("Select persona (0 for none): ").strip()
            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(personas):
                    selected_persona = personas[idx - 1]
                    logger.info(f"Selected persona: {selected_persona}")

                    # Ask about chroma key for green screen personas
                    choice = input("Use chroma key for green screen? (y/N): ").strip().lower()
                    use_chroma_key = choice == "y"
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            sys.exit(0)

        print()

    # Image generation options
    use_mock = args.mock
    if not use_mock and settings.openai_api_key:
        try:
            choice = input("Use mock images? (Y/n): ").strip().lower()
            use_mock = choice != "n"
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            sys.exit(0)

    # Ask about subtitles
    enable_subs = True
    try:
        choice = input("Enable word-level subtitles? (Y/n): ").strip().lower()
        enable_subs = choice != "n"
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        sys.exit(0)

    # Ask about background music
    enable_music = not args.no_music
    if enable_music:
        try:
            choice = input("Enable background music? (Y/n): ").strip().lower()
            enable_music = choice != "n"
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            sys.exit(0)

    print()

    try:
        output_path = run_pipeline(
            topic,
            use_mock_images=use_mock,
            enable_subtitles=enable_subs,
            enable_music=enable_music,
            persona=selected_persona,
            use_chroma_key=use_chroma_key,
            enable_motion=not args.no_motion,
            subtitle_style=args.subtitle_style,
            enable_sfx=not args.no_sfx,
        )

        print()
        print("=" * 50)
        print("  VIDEO GENERATION COMPLETE!")
        print("=" * 50)
        print(f"  Output: {output_path}")
        print("=" * 50)
        print()

    except Exception as e:
        logger.error(f"Video generation failed: {e}")
        sys.exit(1)


def main():
    """Main entry point for FVFactory."""
    args = parse_args()

    # Provider mode override from CLI flags
    if args.local:
        settings.provider_mode = "local"
    elif args.api:
        settings.provider_mode = "api"

    if args.classic:
        settings.cinematic_enabled = False

    # Web server mode
    if args.serve:
        from app.web.server import start_server
        start_server()
        sys.exit(0)

    print()
    print("=" * 50)
    print("  FVFactory v2 - Short-form Video Generator")
    print("  Pipeline: Topic -> Script -> Audio/Visuals -> MP4")
    print("=" * 50)
    print()

    if not validate_config():
        logger.error("Configuration validation failed. Check your .env file.")
        sys.exit(1)

    if args.auto or args.batch:
        run_auto_mode(args)
    else:
        run_interactive_mode(args)


if __name__ == "__main__":
    main()
