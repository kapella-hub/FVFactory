import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """MoviePy's load_dotenv() copies .env into os.environ on import, so
    _env_file=None alone is not hermetic; scrub every Settings field too."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.upper(), raising=False)


def make(**kw):
    """_env_file=None keeps these tests independent of the developer's .env."""
    return Settings(_env_file=None, **kw)


def test_v2_settings_have_defaults():
    s = make(openai_api_key="test")
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
    assert s.clip_pricing["hailuo"] == {"per_clip": 0.50}
    assert s.clip_pricing["kling"] == {"per_second": 0.045}
    assert not hasattr(s, "cost_minimax_video")
    assert s.cost_elevenlabs_per_1k_chars == 0.01
    assert s.cost_openai_gpt4o == 0.005
    assert s.cost_openai_tts_per_1k_chars == 0.015
    assert s.reddit_subreddits == (
        "todayilearned,Damnthatsinteresting,interestingasfuck,space,technology,science,Futurology"
    )
    assert s.trend_count == 5


def test_v1_settings_unchanged():
    s = make(openai_api_key="test", elevenlabs_api_key="test2")
    assert s.openai_api_key == "test"
    assert s.elevenlabs_api_key == "test2"
    assert s.output_dir == "output"
    assert s.mascot_enabled is True


def test_provider_settings_defaults():
    s = make(openai_api_key="test", elevenlabs_api_key="test")
    assert s.provider_mode == "api"
    assert s.llm_provider == "claude_cli"
    assert s.image_provider == "fal"
    assert s.motion_provider == "fal"
    assert s.wan_model_size == "enhanced"
    assert s.data_dir == "data"
    assert s.claude_cli_timeout == 120


def test_provider_mode_api():
    s = make(openai_api_key="test", provider_mode="api")
    assert s.provider_mode == "api"


def test_legacy_env_keys_are_ignored(tmp_path):
    env = tmp_path / ".env"
    env.write_text("AYRSHARE_API_KEY=dummy\nPEXELS_API_KEY=dummy\nCHANNEL_NAME=fromfile\n", encoding="utf-8")
    s = Settings(_env_file=str(env))
    assert s.channel_name == "fromfile"
    assert not hasattr(s, "ayrshare_api_key")
    assert not hasattr(s, "pexels_api_key")


def test_shot_editor_settings_defaults():
    s = make()
    assert s.whisper_model == "small"
    assert s.motion_concurrency == 4
    assert s.keep_sources_days == 14
    assert s.fal_video_fallback_model == ""
    assert s.pacing == "standard"
    assert s.strict is False


def test_pacing_rejects_unknown_value():
    with pytest.raises(ValidationError):
        make(pacing="hyper")
