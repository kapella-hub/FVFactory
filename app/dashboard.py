"""
FVFactory Streamlit Dashboard
Web UI for video generation pipeline
"""

import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

from app.config import settings
from app.content_engine import ScriptGenerator, ScriptGeneratorError
from app.asset_manager import AssetManager, AssetManagerError
from app.video_editor import VideoEditor, VideoEditorError
from app.animator import PortraitAnimator, AnimatorError


# =============================================================================
# PRESETS / NICHES
# =============================================================================

NICHE_PRESETS = {
    "Default Robot": {
        "mascot_prompt": "A cute, futuristic robot with glowing blue eyes and a cracked screen, vector art style",
        "image_style": "vector art style, vibrant colors, clean lines",
    },
    "Finance Guru": {
        "mascot_prompt": "A wise owl wearing a tiny suit and monocle, holding gold coins, cartoon style",
        "image_style": "cartoon style, professional, gold and navy colors",
    },
    "Tech Explainer": {
        "mascot_prompt": "A friendly android with a holographic display on its chest, sleek design, sci-fi style",
        "image_style": "sci-fi style, neon accents, futuristic, clean",
    },
    "History Buff": {
        "mascot_prompt": "An adventurous explorer cat with a tiny fedora and magnifying glass, vintage illustration style",
        "image_style": "vintage illustration style, sepia tones, detailed",
    },
    "Science Explainer": {
        "mascot_prompt": "A curious scientist hamster in a lab coat with oversized goggles, cute cartoon style",
        "image_style": "cute cartoon style, bright colors, educational",
    },
    "No Mascot": {
        "mascot_prompt": "",
        "image_style": "cinematic, high quality, vibrant colors",
    },
}


# =============================================================================
# SESSION STATE INITIALIZATION
# =============================================================================

def init_session_state():
    """Initialize session state variables."""
    if "stage" not in st.session_state:
        st.session_state.stage = "config"  # config -> script -> assets -> render

    if "script" not in st.session_state:
        st.session_state.script = None

    if "edited_hook" not in st.session_state:
        st.session_state.edited_hook = ""

    if "edited_body" not in st.session_state:
        st.session_state.edited_body = ""

    if "image_prompts" not in st.session_state:
        st.session_state.image_prompts = []

    if "image_paths" not in st.session_state:
        st.session_state.image_paths = []

    if "audio_result" not in st.session_state:
        st.session_state.audio_result = None

    if "video_path" not in st.session_state:
        st.session_state.video_path = None

    if "asset_manager" not in st.session_state:
        st.session_state.asset_manager = None

    if "selected_persona" not in st.session_state:
        st.session_state.selected_persona = None

    if "animated_video_path" not in st.session_state:
        st.session_state.animated_video_path = None

    if "use_chroma_key" not in st.session_state:
        st.session_state.use_chroma_key = False


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def apply_niche_settings(niche_name: str):
    """Apply mascot and style settings for selected niche."""
    preset = NICHE_PRESETS.get(niche_name, NICHE_PRESETS["Default Robot"])

    # Update settings dynamically (these will be used by ScriptGenerator)
    settings.mascot_prompt = preset["mascot_prompt"]
    settings.image_style = preset["image_style"]
    settings.mascot_enabled = bool(preset["mascot_prompt"])


def get_available_personas():
    """Get list of available persona images."""
    animator = PortraitAnimator()
    return animator.get_available_personas()


def has_animation_api():
    """Check if animation API is configured."""
    return bool(settings.hedra_api_key or settings.replicate_api_token)


def reset_pipeline():
    """Reset the pipeline to start fresh."""
    st.session_state.stage = "config"
    st.session_state.script = None
    st.session_state.edited_hook = ""
    st.session_state.edited_body = ""
    st.session_state.image_prompts = []
    st.session_state.image_paths = []
    st.session_state.audio_result = None
    st.session_state.video_path = None
    st.session_state.selected_persona = None
    st.session_state.animated_video_path = None
    st.session_state.use_chroma_key = False

    # Cleanup temp files
    if st.session_state.asset_manager:
        try:
            st.session_state.asset_manager.cleanup_temp()
        except Exception:
            pass
    st.session_state.asset_manager = None


# =============================================================================
# SIDEBAR - CONFIGURATION
# =============================================================================

def render_sidebar():
    """Render the sidebar configuration panel."""
    with st.sidebar:
        st.title("FVFactory")
        st.caption("Short-form Video Generator")

        st.divider()

        # Video Mode Selection
        st.subheader("1. Video Mode")

        personas = get_available_personas()
        has_api = has_animation_api()

        video_mode = st.radio(
            "Select mode",
            options=["Image Slideshow", "Hybrid (Images + Talking Head)"],
            help="Slideshow uses multiple images. Hybrid adds a talking head overlay on top.",
            disabled=not (personas and has_api),
        )

        use_persona = video_mode == "Hybrid (Images + Talking Head)"
        st.session_state.use_persona = use_persona

        # Persona Selection (if hybrid mode)
        if use_persona and personas:
            selected_persona = st.selectbox(
                "Select Persona",
                options=personas,
                help="Choose a master image for the talking head overlay"
            )
            st.session_state.selected_persona = selected_persona

            # Chroma key option for green screen personas
            use_chroma_key = st.checkbox(
                "Use chroma key (green screen)",
                value=False,
                help="Enable if your persona image has a green background"
            )
            st.session_state.use_chroma_key = use_chroma_key

            # Show persona preview
            animator = PortraitAnimator()
            persona_path = animator.get_persona_path(selected_persona)
            if persona_path and persona_path.exists():
                st.image(str(persona_path), caption=selected_persona, width=150)
        else:
            st.session_state.selected_persona = None
            st.session_state.use_chroma_key = False

        if not has_api and personas:
            st.warning("Configure HEDRA_API_KEY or REPLICATE_API_TOKEN for Hybrid mode")

        st.divider()

        # Niche/Mascot Selection
        st.subheader("2. Select Niche")
        selected_niche = st.selectbox(
            "Topic/Niche",
            options=list(NICHE_PRESETS.keys()),
            help="Each niche has a different mascot and visual style"
        )
        apply_niche_settings(selected_niche)

        # Show current mascot preview
        if settings.mascot_enabled:
            with st.expander("Mascot Preview"):
                st.caption(settings.mascot_prompt)
                st.caption(f"Style: {settings.image_style}")

        st.divider()

        # Video Topic Input
        st.subheader("3. Video Topic")
        video_topic = st.text_input(
            "Enter your topic",
            placeholder="e.g., The History of Bitcoin",
            help="What should the video be about?"
        )

        st.divider()

        # Generation Options
        st.subheader("4. Options")

        use_mock_images = st.checkbox("Use mock images", value=True, help="Use placeholder images instead of DALL-E")
        enable_subtitles = st.checkbox("Enable subtitles", value=True, help="Add word-level subtitles")
        enable_music = st.checkbox("Enable background music", value=True, help="Add background music with ducking")

        st.divider()

        # Generate Script Button
        generate_disabled = not video_topic or not settings.openai_api_key
        if st.button("Generate Script", type="primary", disabled=generate_disabled, use_container_width=True):
            generate_script(video_topic)

        if not settings.openai_api_key:
            st.warning("OpenAI API key not configured")

        st.divider()

        # Reset Button
        if st.button("Start Over", use_container_width=True):
            reset_pipeline()
            st.rerun()

        # Store options in session state
        st.session_state.use_mock_images = use_mock_images
        st.session_state.enable_subtitles = enable_subtitles
        st.session_state.enable_music = enable_music
        st.session_state.video_topic = video_topic


# =============================================================================
# SCRIPT GENERATION
# =============================================================================

def generate_script(topic: str):
    """Generate script using ScriptGenerator."""
    try:
        with st.spinner("Generating script..."):
            generator = ScriptGenerator()
            script = generator.generate_script(topic)

            st.session_state.script = script
            st.session_state.edited_hook = script.hook
            st.session_state.edited_body = script.body
            st.session_state.image_prompts = list(script.image_prompts)
            st.session_state.stage = "script"

        st.success("Script generated!")
        st.rerun()

    except ScriptGeneratorError as e:
        st.error(f"Script generation failed: {e}")


# =============================================================================
# MAIN COLUMN - SCRIPT REVIEW
# =============================================================================

def render_script_review():
    """Render the script review stage with editable fields."""
    st.header("Script Review")
    st.caption("Review and edit the generated script before proceeding")

    use_persona = st.session_state.get("use_persona", False)

    col1, col2 = st.columns([2, 1])

    with col1:
        # Editable Hook
        st.subheader("Hook (First 3 seconds)")
        st.session_state.edited_hook = st.text_area(
            "Edit hook",
            value=st.session_state.edited_hook,
            height=100,
            label_visibility="collapsed"
        )

        # Editable Body
        st.subheader("Body (Main Content)")
        st.session_state.edited_body = st.text_area(
            "Edit body",
            value=st.session_state.edited_body,
            height=200,
            label_visibility="collapsed"
        )

    with col2:
        # Script Info
        st.subheader("Info")
        if st.session_state.script:
            st.metric("Keywords", len(st.session_state.script.keywords))
            st.caption(", ".join(st.session_state.script.keywords))

        # Character count
        total_chars = len(st.session_state.edited_hook) + len(st.session_state.edited_body)
        st.metric("Total Characters", total_chars)

        # Estimated duration (rough: ~150 words per minute)
        word_count = len(st.session_state.edited_hook.split()) + len(st.session_state.edited_body.split())
        est_duration = word_count / 2.5  # ~150 words per minute = 2.5 words per second
        st.metric("Est. Duration", f"{est_duration:.0f}s")

        # Show mode
        if use_persona:
            st.info(f"Mode: Hybrid\nPersona: {st.session_state.selected_persona}")

    st.divider()

    # Image Prompts Review (always shown - needed for hybrid mode too)
    st.subheader("Image Prompts")
    if use_persona:
        st.caption("These prompts will be used to generate background images")
    else:
        st.caption("These prompts will be used to generate the video images")

    for i, prompt in enumerate(st.session_state.image_prompts):
        with st.expander(f"Scene {i + 1}", expanded=i == 0):
            st.session_state.image_prompts[i] = st.text_area(
                f"Prompt {i + 1}",
                value=prompt,
                height=80,
                label_visibility="collapsed",
                key=f"prompt_{i}"
            )

    st.divider()

    # Approve Button
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        button_label = "Approve & Generate Hybrid Assets" if use_persona else "Approve & Generate Assets"
        if st.button(button_label, type="primary", use_container_width=True):
            generate_assets()


# =============================================================================
# ASSET GENERATION
# =============================================================================

def generate_assets():
    """Generate audio, images, and optionally animated portrait for hybrid mode."""
    use_persona = st.session_state.get("use_persona", False)

    try:
        with st.spinner("Generating audio..."):
            asset_manager = AssetManager()
            st.session_state.asset_manager = asset_manager

            # Generate audio from edited script
            full_narration = f"{st.session_state.edited_hook} {st.session_state.edited_body}"
            audio_result = asset_manager.generate_audio(full_narration)
            st.session_state.audio_result = audio_result

        st.success(f"Audio generated: {audio_result.duration:.1f}s")

        # Always generate background images (for both standard and hybrid mode)
        with st.spinner("Generating background images..."):
            image_paths = asset_manager.generate_images(
                st.session_state.image_prompts,
                use_mock=st.session_state.get("use_mock_images", True)
            )
            st.session_state.image_paths = image_paths

        st.success(f"Generated {len(image_paths)} images")

        if use_persona:
            # HYBRID MODE: Also generate animated portrait
            with st.spinner("Generating animated portrait with SadTalker... This may take several minutes."):
                animator = PortraitAnimator()
                persona_path = animator.get_persona_path(st.session_state.selected_persona)

                if not persona_path:
                    st.error(f"Persona not found: {st.session_state.selected_persona}")
                    return

                animated_path = animator.animate_portrait(
                    audio_path=audio_result.file_path,
                    persona_image_path=str(persona_path),
                    output_filename="animated_portrait.mp4"
                )

                if animated_path:
                    st.session_state.animated_video_path = animated_path
                    st.success("Portrait animation complete!")
                else:
                    # Content filter blocked the request
                    st.session_state.animated_video_path = None
                    st.session_state.use_persona = False  # Fall back to standard mode
                    st.warning("Portrait animation blocked by content filter. Falling back to standard image slideshow mode.")

        st.session_state.stage = "assets"
        st.rerun()

    except (AssetManagerError, AnimatorError) as e:
        st.error(f"Asset generation failed: {e}")


# =============================================================================
# MAIN COLUMN - ASSET REVIEW
# =============================================================================

def render_asset_review():
    """Render the asset review stage with image grid and animated video preview."""
    st.header("Asset Review")

    use_persona = st.session_state.get("use_persona", False)

    # Audio Preview
    st.subheader("Audio Preview")
    if st.session_state.audio_result:
        audio_path = st.session_state.audio_result.file_path
        if Path(audio_path).exists():
            st.audio(audio_path)
            st.caption(f"Duration: {st.session_state.audio_result.duration:.1f} seconds")

    st.divider()

    # Background Images (shown for both modes)
    st.subheader("Background Images")
    if use_persona:
        st.caption("Review background images - these will appear behind the talking head")
    else:
        st.caption("Review generated images and regenerate if needed")

    cols = st.columns(3)
    for i, img_path in enumerate(st.session_state.image_paths):
        col_idx = i % 3
        with cols[col_idx]:
            if Path(img_path).exists():
                st.image(img_path, caption=f"Scene {i + 1}", use_container_width=True)

                # Regenerate button
                if st.button(f"Regenerate", key=f"regen_{i}", use_container_width=True):
                    regenerate_image(i)
            else:
                st.warning(f"Image {i + 1} not found")

    # Animated Portrait Preview (only for hybrid mode)
    if use_persona:
        st.divider()
        st.subheader("Talking Head Preview")

        if st.session_state.animated_video_path and Path(st.session_state.animated_video_path).exists():
            st.video(st.session_state.animated_video_path)
            st.caption("This talking head will be overlaid on the background images (bottom-right, circle crop)")
        else:
            st.warning("Animated video not found")

    st.divider()

    # Proceed to Render
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        button_label = "Render Hybrid Video" if use_persona else "Render Final Video"
        if st.button(button_label, type="primary", use_container_width=True):
            render_video()


def regenerate_image(index: int):
    """Regenerate a single image."""
    try:
        with st.spinner(f"Regenerating image {index + 1}..."):
            if st.session_state.asset_manager:
                prompt = st.session_state.image_prompts[index]
                output_path = Path("assets/temp") / f"image_{index}.png"

                if st.session_state.get("use_mock_images", True):
                    st.session_state.asset_manager._generate_mock_image(
                        prompt, output_path, index
                    )
                else:
                    st.session_state.asset_manager._generate_image_dalle(
                        prompt, output_path
                    )

                st.session_state.image_paths[index] = str(output_path)

        st.success(f"Image {index + 1} regenerated!")
        st.rerun()

    except Exception as e:
        st.error(f"Failed to regenerate image: {e}")


# =============================================================================
# VIDEO RENDERING
# =============================================================================

def render_video():
    """Render the final video."""
    use_persona = st.session_state.get("use_persona", False)
    animated_path = st.session_state.get("animated_video_path")

    # Check if hybrid mode is possible (persona selected AND animation succeeded)
    use_hybrid = use_persona and animated_path and Path(animated_path).exists()

    try:
        # Generate output filename
        topic = st.session_state.get("video_topic", "video")
        safe_topic = "".join(c if c.isalnum() or c in " -_" else "" for c in topic)
        safe_topic = safe_topic.strip().replace(" ", "_")[:30]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"{safe_topic}_{timestamp}.mp4"

        video_editor = VideoEditor()

        if use_hybrid:
            # Hybrid mode: Background images + Talking head overlay
            with st.spinner("Rendering hybrid video... This may take a few minutes."):
                output_path = video_editor.assemble_hybrid_video(
                    audio_path=st.session_state.audio_result.file_path,
                    image_paths=st.session_state.image_paths,
                    talking_head_path=animated_path,
                    output_filename=output_filename,
                    enable_subtitles=st.session_state.get("enable_subtitles", True),
                    enable_music=st.session_state.get("enable_music", True),
                    use_chroma_key=st.session_state.get("use_chroma_key", False),
                )

                st.session_state.video_path = output_path

        else:
            # Standard mode: Assemble video from images
            with st.spinner("Rendering video... This may take a few minutes."):
                output_path = video_editor.assemble_video(
                    audio_path=st.session_state.audio_result.file_path,
                    image_paths=st.session_state.image_paths,
                    output_filename=output_filename,
                    hook_text=st.session_state.edited_hook,
                    enable_subtitles=st.session_state.get("enable_subtitles", True),
                    enable_music=st.session_state.get("enable_music", True),
                )

                st.session_state.video_path = output_path

        st.session_state.stage = "render"
        st.success("Video rendered successfully!")
        st.rerun()

    except (VideoEditorError, AnimatorError) as e:
        st.error(f"Video rendering failed: {e}")


# =============================================================================
# MAIN COLUMN - VIDEO PREVIEW
# =============================================================================

def render_video_preview():
    """Render the final video preview stage."""
    st.header("Video Complete!")
    st.caption("Your video has been rendered successfully")

    # Video Player
    if st.session_state.video_path and Path(st.session_state.video_path).exists():
        st.video(st.session_state.video_path)

        # Download Button
        with open(st.session_state.video_path, "rb") as f:
            video_bytes = f.read()

        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.download_button(
                label="Download Video",
                data=video_bytes,
                file_name=Path(st.session_state.video_path).name,
                mime="video/mp4",
                use_container_width=True
            )

        # Video Info
        st.divider()
        st.subheader("Video Details")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Resolution", "1080x1920")
        with col2:
            st.metric("FPS", "24")
        with col3:
            file_size = Path(st.session_state.video_path).stat().st_size / (1024 * 1024)
            st.metric("File Size", f"{file_size:.1f} MB")

        # Show mode used
        use_persona = st.session_state.get("use_persona", False)
        if use_persona:
            chroma_key_str = " (chroma key)" if st.session_state.get("use_chroma_key", False) else " (circle crop)"
            st.info(f"Generated using Hybrid mode with persona: {st.session_state.selected_persona}{chroma_key_str}")

    st.divider()

    # Start Over
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("Create Another Video", type="primary", use_container_width=True):
            reset_pipeline()
            st.rerun()


# =============================================================================
# MAIN APPLICATION
# =============================================================================

def main():
    """Main Streamlit application."""
    st.set_page_config(
        page_title="FVFactory",
        page_icon="🎬",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Initialize session state
    init_session_state()

    # Render sidebar
    render_sidebar()

    # Main content based on stage
    if st.session_state.stage == "config":
        st.header("Welcome to FVFactory")
        st.caption("Generate viral short-form videos with AI")

        st.markdown("""
        ### How it works:

        1. **Select Mode** - Choose between Image Slideshow or Hybrid mode
        2. **Enter your Topic** - What should the video be about?
        3. **Generate Script** - AI creates a viral script
        4. **Review & Edit** - Fine-tune the script before generation
        5. **Generate Assets** - Create audio, images, and optionally animated portrait
        6. **Render Video** - Combine everything into a final video

        ---

        ### Video Modes

        **Image Slideshow**: Creates a video with multiple AI-generated images and Ken Burns effect.

        **Hybrid Mode**: Combines background images with an animated talking head overlay (circle crop or chroma key).

        ---

        ### Get Started

        Use the sidebar on the left to configure your video and click **Generate Script** to begin.
        """)

        # Show config status
        st.subheader("Configuration Status")
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            if settings.openai_api_key:
                st.success("OpenAI: Connected")
            else:
                st.error("OpenAI: Not configured")

        with col2:
            if settings.elevenlabs_api_key:
                st.success("ElevenLabs: Connected")
            else:
                st.warning("ElevenLabs: Using OpenAI TTS")

        with col3:
            if settings.hedra_api_key or settings.replicate_api_token:
                st.success("Portrait Animation: Ready")
            else:
                st.warning("Portrait Animation: Not configured")

        with col4:
            personas = get_available_personas()
            if personas:
                st.success(f"Personas: {len(personas)} available")
            else:
                st.warning("Personas: None found")

    elif st.session_state.stage == "script":
        render_script_review()

    elif st.session_state.stage == "assets":
        render_asset_review()

    elif st.session_state.stage == "render":
        render_video_preview()


if __name__ == "__main__":
    main()
