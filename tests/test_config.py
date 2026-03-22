from app.config import Settings

def test_v2_settings_have_defaults():
    """All v2 settings should have sensible defaults so v1 behavior is unchanged."""
    s = Settings(openai_api_key="test")
    assert s.replicate_api_token == ""
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
    assert s.cost_flux_image == 0.03
    assert s.cost_minimax_video == 0.10
    assert s.cost_elevenlabs_per_1k_chars == 0.01
    assert s.cost_openai_gpt4o == 0.005
    assert s.cost_openai_tts_per_1k_chars == 0.015
    assert s.reddit_subreddits == "todayilearned,technology,science,explainlikeimfive"
    assert s.trend_count == 5

def test_v1_settings_unchanged():
    """Existing v1 settings must still work."""
    s = Settings(openai_api_key="test", elevenlabs_api_key="test2")
    assert s.openai_api_key == "test"
    assert s.elevenlabs_api_key == "test2"
    assert s.output_dir == "output"
    assert s.mascot_enabled is True
