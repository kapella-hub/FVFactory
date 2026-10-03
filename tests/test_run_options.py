"""Per-video options for the web form, scheduler and worker (spec §11) and the run-report payloads
(spec §10). Pure helpers: the web app and scheduler cannot be imported in the local venv."""
import json

import pytest

from app.config import Settings, settings
from app.run_options import (MUSIC_SOURCE_CHOICES, PACING_CHOICES, OptionError, apply_saved_settings,
                             apply_settings_updates, clean_settings_updates, load_config_file,
                             pipeline_kwargs, to_bool)


def test_choices_follow_spec_order():
    assert PACING_CHOICES == ("calm", "standard", "fast")
    assert MUSIC_SOURCE_CHOICES == ("mine", "generated", "any", "none")


def test_empty_config_means_settings_defaults(monkeypatch):
    monkeypatch.setattr(settings, "subtitle_style", "neon_glow")
    kw = pipeline_kwargs({})
    assert kw == {"use_mock_images": False, "enable_subtitles": True, "enable_motion": True,
                  "enable_sfx": True, "enable_music": True, "subtitle_style": "neon_glow",
                  "niche": None, "video_style": "", "video_duration": "",
                  "pacing": None, "music_source": None, "strict": None}


def test_old_scheduler_slot_without_new_keys_runs_with_defaults():
    """A slot saved by the pre-Phase-D UI: only niche/voice/enable_motion/enable_sfx."""
    kw = pipeline_kwargs({"niche": "tech", "voice": "auto", "enable_motion": False, "enable_sfx": True})
    assert kw["niche"] == "tech" and kw["enable_motion"] is False and kw["enable_music"] is True
    assert (kw["pacing"], kw["music_source"], kw["strict"]) == (None, None, None)
    assert "voice" not in kw and "topic" not in kw            # callers resolve these


def test_web_request_body_maps_to_run_pipeline_kwargs():
    body = {"topic": "x", "niche": "", "voice": "auto", "subtitle_style": "fire", "enable_motion": True,
            "enable_sfx": False, "enable_music": False, "use_mock": True, "auto_topic": False,
            "video_style": "anime", "video_duration": "short",
            "pacing": "fast", "music_source": "generated", "strict": True}
    kw = pipeline_kwargs(body)
    assert kw["use_mock_images"] is True and kw["enable_music"] is False and kw["enable_sfx"] is False
    assert kw["niche"] is None and kw["subtitle_style"] == "fire" and kw["video_style"] == "anime"
    assert (kw["pacing"], kw["music_source"], kw["strict"]) == ("fast", "generated", True)


def test_non_string_text_fields_fall_back_to_defaults(monkeypatch):
    monkeypatch.setattr(settings, "subtitle_style", "bold_impact")
    kw = pipeline_kwargs({"subtitle_style": 5, "niche": ["x"], "video_style": None})
    assert kw["subtitle_style"] == "bold_impact" and kw["niche"] is None and kw["video_style"] == ""


@pytest.mark.parametrize("value", ["", "  ", None])
def test_blank_choice_means_default(value):
    kw = pipeline_kwargs({"pacing": value, "music_source": value})
    assert kw["pacing"] is None and kw["music_source"] is None


def test_choices_are_case_and_space_tolerant():
    kw = pipeline_kwargs({"pacing": " Fast ", "music_source": "MINE"})
    assert (kw["pacing"], kw["music_source"]) == ("fast", "mine")


@pytest.mark.parametrize("key,value", [("pacing", "warp"), ("music_source", "spotify"), ("pacing", 3)])
def test_unknown_choice_is_rejected_with_the_choices(key, value):
    with pytest.raises(OptionError, match="choose one of"):
        pipeline_kwargs({key: value})


@pytest.mark.parametrize("value,expected", [(True, True), (False, False), ("true", True), ("False", False),
                                            ("1", True), ("0", False), ("yes", True), ("off", False),
                                            (1, True), (0, False)])
def test_bool_strings_are_parsed_never_truthy(value, expected):
    assert pipeline_kwargs({"strict": value})["strict"] is expected
    assert pipeline_kwargs({"enable_sfx": value})["enable_sfx"] is expected


@pytest.mark.parametrize("value", ["maybe", 2, [], {}])
def test_bad_bool_is_rejected(value):
    with pytest.raises(OptionError, match="true or false"):
        to_bool("strict", value, None)


def test_settings_update_cleaning():
    out = clean_settings_updates({"pacing": "Calm", "music_source": "none", "strict": "true", "niche": "tech"})
    assert out == {"pacing": "calm", "music_source": "none", "strict": True, "niche": "tech"}
    for bad in ({"pacing": "warp"}, {"pacing": ""}, {"music_source": ""}, {"strict": "maybe"}):
        with pytest.raises(OptionError):
            clean_settings_updates(bad)


def test_apply_settings_updates_sets_known_keys_only():
    s = Settings(_env_file=None)
    applied = apply_settings_updates(s, {"pacing": "fast", "not_a_setting": 1})
    assert applied == ["pacing"] and s.pacing == "fast" and not hasattr(s, "not_a_setting")


def test_saved_config_with_bad_values_never_stops_startup():
    """Hand-edited data/config.json: bad option values are skipped, good ones applied."""
    s = Settings(_env_file=None)
    saved = json.loads('{"pacing": "warp", "music_source": "mine", "strict": "maybe", "niche": "tech"}')
    applied = apply_saved_settings(s, saved)
    assert sorted(applied) == ["music_source", "niche"]
    assert s.pacing == "standard" and s.music_source == "mine" and s.strict is False and s.niche == "tech"


def test_config_file_missing_corrupt_or_not_an_object_is_empty(tmp_path):
    p = tmp_path / "config.json"
    assert load_config_file(p) == {}
    for bad in ("{oops", "[1, 2]", "\"text\""):
        p.write_text(bad, encoding="utf-8")
        assert load_config_file(p) == {}
    p.write_text('{"pacing": "fast"}', encoding="utf-8")
    assert load_config_file(p) == {"pacing": "fast"}
