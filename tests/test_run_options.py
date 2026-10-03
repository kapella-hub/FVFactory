"""Per-video options for the web form, scheduler and worker (spec §11) and the run-report payloads
(spec §10). Pure helpers: the web app and scheduler cannot be imported in the local venv."""
import json

import pytest

from app.config import Settings, settings
from app.run_options import (MUSIC_SOURCE_CHOICES, PACING_CHOICES, TIER_CHOICES, OptionError, apply_saved_settings,
                             apply_settings_updates, clean_settings_updates, load_config_file,
                             pipeline_kwargs, to_bool, to_max_cost, validate_settings_updates)


def test_choices_follow_spec_order():
    assert PACING_CHOICES == ("calm", "standard", "fast")
    assert MUSIC_SOURCE_CHOICES == ("mine", "generated", "any", "none")


def test_empty_config_means_settings_defaults(monkeypatch):
    monkeypatch.setattr(settings, "subtitle_style", "neon_glow")
    kw = pipeline_kwargs({})
    assert kw == {"use_mock_images": False, "enable_subtitles": True, "enable_motion": True,
                  "enable_sfx": True, "enable_music": True, "subtitle_style": "neon_glow",
                  "niche": None, "video_style": "", "video_duration": "",
                  "pacing": None, "music_source": None, "strict": None,
                  "quality_tier": None, "max_cost": None}


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


def test_non_field_keys_are_skipped_not_raised():
    s = Settings(_env_file=None)
    assert apply_settings_updates(s, {"model_dump": 1}) == []
    assert apply_saved_settings(s, {"model_dump": 1, "model_config": {}}) == []
    assert callable(s.model_dump)


def test_wrong_typed_values_are_skipped_good_ones_applied():
    s = Settings(_env_file=None)
    before = s.music_volume
    assert apply_settings_updates(s, {"music_volume": "loud"}) == []
    assert s.music_volume == before
    assert apply_settings_updates(s, {"music_volume": 0.2}) == ["music_volume"] and s.music_volume == 0.2
    applied = apply_saved_settings(s, {"music_volume": "x", "niche": "tech", "model_dump": 1, "enable_sfx": False})
    assert sorted(applied) == ["enable_sfx", "niche"] and s.music_volume == 0.2


def test_validate_settings_updates_reports_each_bad_key():
    valid, errors = validate_settings_updates(Settings(_env_file=None), {"music_volume": "loud", "niche": "tech", "nope": 1})
    assert valid == {"niche": "tech"} and set(errors) == {"music_volume", "nope"}


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


def test_run_result_carries_report_warnings(tmp_path):
    from app.cin.report import RunReport
    from app.run_options import run_result
    job = tmp_path / "20261003_1200_gold"
    job.mkdir()
    report = RunReport(job=job.name, status="ok")
    report.warn("music_missing", "No music files", {"mood": "epic"})
    report.save(job / "run_report.json")
    out = run_result(job / "final.mp4")
    assert out["video_id"] == job.name and out["path"] == str(job / "final.mp4")
    assert out["status"] == "ok" and [w["code"] for w in out["warnings"]] == ["music_missing"]


def test_run_result_without_report_still_has_video_id(tmp_path):
    from app.run_options import run_result
    out = run_result(tmp_path / "jobz" / "final.20261003_120000.mp4")      # locked-final fallback name
    assert out["video_id"] == "jobz" and out["warnings"] == [] and out["status"] == "unknown"


def test_run_failure_reads_the_failed_jobs_report(tmp_path):
    from app.cin.report import RunReport
    from app.run_options import run_failure
    job = tmp_path / "jobf"
    job.mkdir()
    report = RunReport(job="jobf", status="failed", error="StrictModeError: strict mode")
    report.warn("still_fallback", "scene 0 is a still", {})
    report.save(job / "run_report.json")
    err = RuntimeError("strict mode")
    err.job_dir = str(job)
    out = run_failure(err)
    assert out["video_id"] == "jobf" and out["status"] == "failed"
    assert [w["code"] for w in out["warnings"]] == ["still_fallback"]
    assert run_failure(ValueError("no topics")) == {"video_id": None, "status": "failed", "warnings": []}



# ---------------------------------------------------------------- quality tiers (spec 2026-10-03 §9)

def test_tier_choices():
    assert TIER_CHOICES == ("standard", "premium", "custom")


@pytest.mark.parametrize("value, expected", [("", None), (None, None), ("  ", None), ("premium", "premium"),
                                             (" Custom ", "custom"), ("STANDARD", "standard")])
def test_quality_tier_option(value, expected):
    assert pipeline_kwargs({"quality_tier": value})["quality_tier"] == expected


@pytest.mark.parametrize("value", ["gold", 2, True])
def test_unknown_quality_tier_rejected(value):
    with pytest.raises(OptionError, match="choose one of standard, premium, custom"):
        pipeline_kwargs({"quality_tier": value})


@pytest.mark.parametrize("value, expected", [("", None), (None, None), (" ", None), ("0", 0.0), (0, 0.0),
                                             ("4.5", 4.5), (" 4.5 ", 4.5), (3, 3.0), (2.25, 2.25)])
def test_max_cost_option(value, expected):
    assert pipeline_kwargs({"max_cost": value})["max_cost"] == expected


@pytest.mark.parametrize("value", ["-1", -0.01, "abc", "nan", "inf", float("nan"), float("inf"), True, [], {}])
def test_bad_max_cost_rejected(value):
    with pytest.raises(OptionError, match=">= 0"):
        pipeline_kwargs({"max_cost": value})


def test_to_max_cost_default_for_blank():
    assert to_max_cost("max_cost", "", 2.0) == 2.0


def test_settings_update_cleaning_for_tier_and_cap():
    out = clean_settings_updates({"quality_tier": "Premium", "max_cost_per_video": "4.5"})
    assert out == {"quality_tier": "premium", "max_cost_per_video": 4.5}
    assert clean_settings_updates({"max_cost_per_video": 0})["max_cost_per_video"] == 0.0
    for bad in ({"quality_tier": "gold"}, {"quality_tier": ""}, {"max_cost_per_video": ""},
                {"max_cost_per_video": "-1"}, {"max_cost_per_video": "abc"}, {"max_cost_per_video": "nan"}):
        with pytest.raises(OptionError):
            clean_settings_updates(bad)


def test_saved_tier_and_cap_applied_and_bad_ones_skipped():
    s = Settings(_env_file=None)
    assert sorted(apply_saved_settings(s, {"quality_tier": "premium", "max_cost_per_video": "3"})) == [
        "max_cost_per_video", "quality_tier"]
    assert s.quality_tier == "premium" and s.max_cost_per_video == 3.0
    assert apply_saved_settings(s, {"quality_tier": "gold", "max_cost_per_video": -2}) == []
    assert s.quality_tier == "premium" and s.max_cost_per_video == 3.0
