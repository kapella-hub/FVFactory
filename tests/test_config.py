from app.config import Settings

def test_v2_settings_have_defaults():
    """All v2 settings should have sensible defaults so v1 behavior is unchanged."""
    s = Settings(openai_api_key="test")
    assert s.replicate_api_token == ""
    assert s.flux_model == "black-forest-labs/flux-1.1-pro"
    assert s.minimax_model == "minimax/image-to-video"
    assert s.elevenlabs_model == "eleven_multilingual_v2"
    assert s.elevenlabs_voice_id == "pqHfZKP75CvOlQylNhV4"  # Bill
    assert s.subtitle_style == "bold_impact"
    assert s.crossfade_duration == 0.8
    assert s.youtube_client_secrets == "client_secrets.json"
    assert s.youtube_token_path == "youtube_token.json"
    assert s.youtube_privacy == "public"
    assert "bill" in s.voice_presets
    assert "stoicism" in s.voice_niche_map
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


def test_provider_settings_defaults():
    """New provider settings have correct defaults."""
    from app.config import Settings
    s = Settings(openai_api_key="test", elevenlabs_api_key="test")
    assert s.provider_mode == "local"
    assert s.llm_provider == "claude_cli"
    assert s.image_provider == "local"
    assert s.motion_provider == "local"
    assert s.wan_model_size == "1.3b"
    assert s.data_dir == "data"
    assert s.claude_cli_timeout == 120


def test_provider_mode_api():
    """provider_mode 'api' should be readable."""
    from app.config import Settings
    s = Settings(openai_api_key="test", provider_mode="api")
    assert s.provider_mode == "api"
