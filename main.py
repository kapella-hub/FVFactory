"""
FVFactory - Automated short-form video creation

Pipeline: Topic -> Script -> Audio/Images or Animated Portrait -> MP4
"""

import logging
import sys
from datetime import datetime
from typing import Optional

from app.config import settings
from app.content_engine import ScriptGenerator, ScriptGeneratorError
from app.asset_manager import AssetManager, AssetManagerError
from app.video_editor import VideoEditor, VideoEditorError
from app.animator import PortraitAnimator, AnimatorError

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
    """Validate that required API keys are configured."""
    errors = []

    if not settings.openai_api_key:
        errors.append("OPENAI_API_KEY is required for script generation")

    if not settings.elevenlabs_api_key and not settings.openai_api_key:
        errors.append("ELEVENLABS_API_KEY or OPENAI_API_KEY required for audio")

    if errors:
        for error in errors:
            logger.error(error)
        return False

    # Warnings (non-fatal)
    if not settings.elevenlabs_api_key:
        logger.warning("ELEVENLABS_API_KEY not set, will use OpenAI TTS fallback")

    if not settings.leonardo_api_key and not settings.midjourney_api_key:
        logger.warning("No image API configured, will use mock images")

    if not settings.hedra_api_key and not settings.replicate_api_token:
        logger.warning("No portrait animation API configured (HEDRA_API_KEY or REPLICATE_API_TOKEN)")

    return True


def generate_output_filename(topic: str) -> str:
    """Generate a unique output filename based on topic and timestamp."""
    # Sanitize topic for filename
    safe_topic = "".join(c if c.isalnum() or c in " -_" else "" for c in topic)
    safe_topic = safe_topic.strip().replace(" ", "_")[:30]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    return f"{safe_topic}_{timestamp}.mp4"


def run_pipeline(
    topic: str,
    use_mock_images: bool = True,
    enable_subtitles: bool = True,
    enable_music: bool = True,
    persona: Optional[str] = None,
    use_chroma_key: bool = False,
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
        script = script_gen.generate_script(topic)

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
        audio_result = asset_manager.generate_audio(full_narration)

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

        if persona:
            # HYBRID MODE: Background images + Talking head overlay
            logger.info(f"Using hybrid mode with persona: {persona}")

            animator = PortraitAnimator()
            persona_path = animator.get_persona_path(persona)

            if not persona_path:
                raise AnimatorError(f"Persona not found: {persona}")

            # Generate animated portrait
            logger.info("Generating animated portrait...")
            animated_video_path = animator.animate_portrait(
                audio_path=audio_result.file_path,
                persona_image_path=str(persona_path),
                output_filename=f"animated_{output_filename}"
            )

            logger.info(f"Portrait animation complete: {animated_video_path}")

            # Render hybrid video (background images + talking head overlay)
            logger.info("Rendering hybrid video...")
            video_editor = VideoEditor()

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
            video_editor = VideoEditor()

            output_path = video_editor.assemble_video(
                audio_path=audio_result.file_path,
                image_paths=image_paths,
                output_filename=output_filename,
                hook_text=script.hook,  # Fallback if subtitles disabled
                enable_subtitles=enable_subtitles,
                enable_music=enable_music,
            )

        logger.info(f"Video rendered successfully: {output_path}")

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


def main():
    """Main entry point for FVFactory."""
    print()
    print("=" * 50)
    print("  FVFactory - Short-form Video Generator")
    print("  Pipeline: Topic -> Script -> Audio/Visuals -> MP4")
    print("=" * 50)
    print()

    # Validate configuration
    if not validate_config():
        logger.error("Configuration validation failed. Check your .env file.")
        sys.exit(1)

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
    use_mock = True
    if settings.openai_api_key:
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
    enable_music = True
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


if __name__ == "__main__":
    main()
