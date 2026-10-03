"""run_pipeline wiring: job folder, reorder, failure semantics, strict, classic, concurrency (spec §4, §9.2, §10).
Every test is offline: LLM, TTS, Whisper, metadata, fal and HTTP are patched."""
import json
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

import main
from app.asset_manager import AssetManager, AudioResult
from app.cin.clip_sourcing import StrictModeError
from app.cin.renderer import RenderError
from app.config import Settings, settings
from app.content_engine import ScriptOutput
from tests.conftest import make_tone


@pytest.fixture
def offline(monkeypatch, tmp_path, gold):
    """Zero-network run_pipeline. Returns .out (output dir) and .state (set state["scene_texts"] to override)."""
    import requests

    def no_network(*args, **kwargs):
        raise AssertionError("network call attempted")

    out = tmp_path / "output"
    monkeypatch.setattr(settings, "output_dir", str(out))
    monkeypatch.setattr(settings, "music_enabled", False)
    monkeypatch.setattr(settings, "enable_sfx", False)
    monkeypatch.setattr(settings, "motion_provider", "fal")
    monkeypatch.setattr(settings, "fal_video_model", "hailuo")
    monkeypatch.setattr(settings, "quality_tier", "custom")        # = fal_video_model (hailuo)
    monkeypatch.setattr(settings, "max_cost_per_video", 0.0)
    monkeypatch.setattr(settings, "llm_provider", "claude_cli")
    monkeypatch.setattr(settings, "clip_pricing", Settings(_env_file=None).clip_pricing)
    monkeypatch.setattr(settings, "cost_flux_image", 0.03)
    monkeypatch.setattr(settings, "cost_elevenlabs_per_1k_chars", 0.01)
    monkeypatch.setattr(settings, "cost_openai_gpt4o", 0.005)
    monkeypatch.setattr(settings, "cost_claude_cli", 0.0)
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(requests, "get", no_network)
    monkeypatch.setattr(requests, "post", no_network)
    monkeypatch.setitem(sys.modules, "fal_client", None)

    state = {"scene_texts": gold["scene_texts"]}

    def fake_script(self, topic, **kwargs):
        return ScriptOutput(hook=gold["scene_texts"][0], body=gold["scene_texts"][1],
                            image_prompts=["gold bar", "gold cube", "vault", "scale", "hand"],
                            keywords=["gold"], motion_prompts=["slow push", "orbit"],
                            scene_texts=state["scene_texts"], scene_roles=state.get("scene_roles", []),
                            hook_headline=state.get("hook_headline", ""))

    def fake_tts(self, text, voice_id=None, output_path=None):
        make_tone(output_path, gold["duration"])
        return AudioResult(file_path=str(output_path), duration=gold["duration"])

    def no_llm(*args, **kwargs):
        raise AssertionError("LLM call attempted")

    monkeypatch.setattr(main.ScriptGenerator, "generate_script", fake_script)
    monkeypatch.setattr("app.content_engine.generate_json", no_llm)   # the length revision fails -> draft kept
    monkeypatch.setattr(AssetManager, "generate_audio", fake_tts)
    monkeypatch.setattr("app.cin.align.transcribe_words", lambda path, model: gold["words"])
    monkeypatch.setattr(main.MetadataGenerator, "generate_metadata",
                        lambda self, topic, hook, keywords, niche="": {"title_tiktok": topic})
    monkeypatch.setattr(main.MetadataGenerator, "generate_thumbnail", lambda self, **kwargs: None)
    return SimpleNamespace(out=out, state=state)


def fake_render(job, plan, options, report):
    job.final.write_bytes(b"final")
    return job.final


def only_job(out):
    jobs = [p for p in out.iterdir() if p.is_dir() and (p / "sources").is_dir()]
    assert len(jobs) == 1
    return jobs[0]


def report_of(job_dir):
    return json.loads((job_dir / "run_report.json").read_text(encoding="utf-8"))


def test_job_folder_and_sources_written(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", fake_render)
    out_path = main.run_pipeline("Gold facts", use_mock_images=True)
    job = only_job(offline.out)
    assert out_path == str(job / "final.mp4")
    for rel in ("sources/narration.mp3", "sources/words.json", "sources/alignment.json",
                "sources/shot_plan.json", "sources/images/scene00.png", "sources/images/scene01.png"):
        assert (job / rel).exists(), rel
    report = report_of(job)
    assert report["status"] == "ok"
    assert [w["code"] for w in report["warnings"]] == [
        "prompt_count_normalized",      # 5 prompts, 2 scenes
        "scene_roles_derived",          # the fake script has no scene_roles
        "script_length_off_target",     # 24 words; the revision call fails (no LLM) and the draft is kept
        "hook_headline_fallback",       # the fake script has no hook_headline
    ]
    assert set(report["durations"]) >= {"script", "tts", "align", "images", "clips"}
    plan = json.loads((job / "sources/shot_plan.json").read_text(encoding="utf-8"))
    assert all(s["source"]["type"] == "still" for s in plan["shots"])                 # --mock: stills, no warning
    assert plan["scenes"][1]["t0"] == 2.32


def test_paraphrased_scene_texts_render_with_alignment_fallback(offline, monkeypatch):
    offline.state["scene_texts"] = ["Gold is heavy.", "A small cube weighs as much as a car."]
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True)
    report = report_of(only_job(offline.out))
    assert report["status"] == "ok"
    assert "alignment_fallback" in [w["code"] for w in report["warnings"]]


def test_renderer_error_fails_run_and_keeps_sources(offline, monkeypatch):
    def boom(*args, **kwargs):
        raise RenderError("boom")

    def classic_must_not_run(*args, **kwargs):
        raise AssertionError("classic editor used as a silent fallback")

    monkeypatch.setattr(main, "render_job", boom)
    monkeypatch.setattr(main.VideoEditor, "assemble_video", classic_must_not_run)
    with pytest.raises(RenderError):
        main.run_pipeline("Gold facts", use_mock_images=True)
    job = only_job(offline.out)
    report = report_of(job)
    assert report["status"] == "failed" and "boom" in report["error"]
    assert (job / "sources/narration.mp3").exists() and (job / "sources/shot_plan.json").exists()


@pytest.mark.parametrize("strict", [True, False])
def test_strict_mode_fails_before_render_on_still_fallback(offline, monkeypatch, strict):
    original = AssetManager.generate_images
    monkeypatch.setattr(AssetManager, "generate_images",
                        lambda self, prompts, use_mock=True, output_dir=None: original(self, prompts, True, output_dir))
    rendered = []
    monkeypatch.setattr(main, "render_job", lambda *a: rendered.append(1) or fake_render(*a))
    if strict:
        with pytest.raises(StrictModeError):
            main.run_pipeline("Gold facts", strict=True)          # fal_client missing -> every clip fails
        assert rendered == []
    else:
        main.run_pipeline("Gold facts", strict=False)
        assert rendered == [1]
    report = report_of(only_job(offline.out))
    assert report["status"] == ("failed" if strict else "ok")
    assert [w["code"] for w in report["warnings"]].count("still_fallback") == 3   # 3 hailuo segments
    assert report["clips"]["failed"] == 3


def test_classic_flag_uses_old_editor_inside_job_folder(offline, monkeypatch):
    calls = {}

    def fake_assemble(self, **kwargs):
        calls.update(kwargs, output_dir=self.output_dir)
        path = self.output_dir / kwargs["output_filename"]
        path.write_bytes(b"classic")
        return str(path)

    monkeypatch.setattr(main.VideoEditor, "assemble_video", fake_assemble)
    out_path = main.run_pipeline("Gold facts", use_mock_images=True, classic=True)
    job = only_job(offline.out)
    assert out_path == str(job / "final.mp4")
    assert calls["output_filename"] == "final.mp4" and calls["output_dir"] == job


def test_concurrent_runs_get_separate_job_folders(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", fake_render)
    results, errors = [], []

    def go():
        try:
            results.append(main.run_pipeline("Same topic", use_mock_images=True))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(set(results)) == 2
    jobs = [p for p in offline.out.iterdir() if (p / "sources").is_dir()]
    assert len(jobs) == 2 and all((j / "sources/narration.mp3").exists() for j in jobs)


def test_old_sources_pruned_at_start(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", fake_render)
    old = offline.out / "20250101_000000_old"
    (old / "sources").mkdir(parents=True)
    (old / "run_report.json").write_text("{}", encoding="utf-8")
    stamp = time.time() - 30 * 86400
    os.utime(old / "sources", (stamp, stamp))
    main.run_pipeline("Gold facts", use_mock_images=True)
    assert not (old / "sources").exists() and (old / "run_report.json").exists()


def test_validate_config_mock_skips_image_and_motion_keys(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "claude_cli")
    monkeypatch.setattr(settings, "provider_mode", "mixed")
    monkeypatch.setattr(settings, "image_provider", "fal")
    monkeypatch.setattr(settings, "motion_provider", "fal")
    monkeypatch.setattr(settings, "fal_api_key", "")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "x")
    assert main.validate_config(use_mock=True) is True
    assert main.validate_config() is False


def test_unknown_pacing_rejected_before_any_work(offline):
    with pytest.raises(ValueError):
        main.run_pipeline("Gold facts", use_mock_images=True, pacing="hyper")
    assert not offline.out.exists() or not any(offline.out.iterdir())


def _raise(exc):
    def f(*args, **kwargs):
        raise exc
    return f


def test_cost_logging_errors_never_fail_run(offline, monkeypatch):
    """P5b: any cost-log error (unknown clip model, disk failure) warns and the run continues."""
    monkeypatch.setattr(main, "render_job", fake_render)
    monkeypatch.setattr(main.CostTracker, "log_clip", _raise(ValueError("No clip pricing for model 'x'")))
    monkeypatch.setattr(main.CostTracker, "log_cost", _raise(RuntimeError("disk full")))
    monkeypatch.setattr(main.CostTracker, "save", _raise(OSError("read-only")))
    out_path = main.run_pipeline("Gold facts", use_mock_images=True)
    assert out_path.endswith("final.mp4")
    assert report_of(only_job(offline.out))["status"] == "ok"


@pytest.mark.render
def test_mock_run_end_to_end(offline):
    from app.encoding import probe_video
    out_path = main.run_pipeline("Gold facts", use_mock_images=True, enable_music=False, enable_sfx=False)
    job = only_job(offline.out)
    info = probe_video(out_path)
    assert (info["width"], info["height"], info["fps"], info["pixel_format"]) == (1080, 1920, 30.0, "yuv420p")
    assert abs(info["duration"] - 8.0) <= 0.05
    report = report_of(job)
    assert report["status"] == "ok" and report["platform_safe"]["ok"] is True
    assert -15.0 <= report["loudness"]["I"] <= -13.0
    assert (job / "sources/mix.wav").exists() and not (job / "_render").exists()


def test_shot_plan_gets_hook_headline_from_script(offline, monkeypatch):
    """Spec §7: the hook's first sentence (<= 8 words) becomes the top-band headline for [0, 2.5 s]."""
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True)
    plan = json.loads((only_job(offline.out) / "sources/shot_plan.json").read_text(encoding="utf-8"))
    assert plan["hook_headline"] == {"text": "Gold is heavier than you think", "t0": 0.0, "t1": 2.5}


def test_music_source_reaches_render_and_plan_saved_after_render(offline, monkeypatch):
    seen = {}

    def render_with_music(job, plan, options, report):
        seen["music_source"] = options.music_source
        plan.music = {"file": "assets/music/epic/x.mp3", "mood": "", "source": options.music_source,
                      "duck_windows": [[0.0, 1.0]]}
        plan.sfx = [{"t": 0.0, "kind": "impact", "file": "assets/sfx/impact.mp3", "gain_db": -6.0}]
        return fake_render(job, plan, options, report)

    monkeypatch.setattr(main, "render_job", render_with_music)
    main.run_pipeline("Gold facts", use_mock_images=True, music_source="generated")
    job = only_job(offline.out)
    plan = json.loads((job / "sources/shot_plan.json").read_text(encoding="utf-8"))
    assert seen["music_source"] == "generated"
    assert plan["music"]["source"] == "generated" and plan["sfx"][0]["kind"] == "impact"
    assert report_of(job)["options"]["music_source"] == "generated"


def test_music_source_defaults_to_settings_and_rejects_unknown(offline, monkeypatch):
    seen = {}
    monkeypatch.setattr(settings, "music_source", "mine")
    monkeypatch.setattr(main, "render_job",
                        lambda job, plan, options, report: seen.update(src=options.music_source) or fake_render(job, plan, options, report))
    main.run_pipeline("Gold facts", use_mock_images=True)
    assert seen["src"] == "mine"
    with pytest.raises(ValueError):
        main.run_pipeline("Gold facts", use_mock_images=True, music_source="spotify")


def test_failed_run_exposes_job_dir_without_changing_exception_type(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", _raise(RenderError("boom")))
    with pytest.raises(RenderError) as info:
        main.run_pipeline("Gold facts", use_mock_images=True)
    job = only_job(offline.out)
    assert info.value.job_dir == str(job)
    assert report_of(job)["status"] == "failed"


def test_report_write_failure_does_not_mask_the_pipeline_error(offline, monkeypatch):
    from app.cin.report import RunReport
    monkeypatch.setattr(main, "render_job", _raise(RenderError("render died")))
    monkeypatch.setattr(RunReport, "save", _raise(OSError("disk full")))
    with pytest.raises(RenderError, match="render died"):
        main.run_pipeline("Gold facts", use_mock_images=True)


def test_report_write_failure_does_not_fail_a_finished_run(offline, monkeypatch):
    from app.cin.report import RunReport
    monkeypatch.setattr(main, "render_job", fake_render)
    monkeypatch.setattr(RunReport, "save", _raise(OSError("disk full")))
    out = main.run_pipeline("Gold facts", use_mock_images=True)
    assert out.endswith("final.mp4")


def test_cost_tracker_construction_failure_never_fails_run(offline, monkeypatch):
    """Phase C review: CostTracker() itself (corrupt cost_log.json) must not fail a run."""
    monkeypatch.setattr(main, "render_job", fake_render)
    monkeypatch.setattr(main, "CostTracker", _raise(ValueError("corrupt cost_log.json")))
    out_path = main.run_pipeline("Gold facts", use_mock_images=True)
    assert out_path.endswith("final.mp4")
    assert report_of(only_job(offline.out))["status"] == "ok"


def test_post_render_plan_save_failure_does_not_fail_run(offline, monkeypatch):
    """final.mp4 exists: a locked shot_plan.json on the post-render save warns, the run still succeeds."""
    from app.cin.shot_plan import ShotPlan
    monkeypatch.setattr(main, "render_job", fake_render)
    real, calls = ShotPlan.save, []

    def save(self, path):
        calls.append(1)
        if len(calls) >= 2:
            raise PermissionError("shot_plan.json locked")
        return real(self, path)

    monkeypatch.setattr(ShotPlan, "save", save)
    out_path = main.run_pipeline("Gold facts", use_mock_images=True)
    assert out_path.endswith("final.mp4") and len(calls) == 2
    rep = report_of(only_job(offline.out))
    assert rep["status"] == "ok"
    assert [w["code"] for w in rep["warnings"] if w["code"] == "plan_save_failed"] == ["plan_save_failed"]
    assert rep["cost"]["actual"]            # cost logging still ran



def test_report_records_word_budget_and_narration_timing(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True, video_duration="short")
    script = report_of(only_job(offline.out))["script"]
    assert script == {"preset": "short", "target_seconds": 30, "target_words": 66, "word_range": [57, 75],
                      "draft_words": 24, "words": 24, "revision": "failed",
                      "narration_seconds": 8.0, "seconds_vs_target": -22.0, "words_per_second": 3.0,
                      "llm_provider": "claude_cli"}


def test_script_roles_and_headline_reach_the_shot_plan(offline, monkeypatch):
    offline.state["scene_roles"] = ["hook", "loop"]
    offline.state["hook_headline"] = "HEAVIER THAN A CAR"
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True)
    job = only_job(offline.out)
    plan = json.loads((job / "sources/shot_plan.json").read_text(encoding="utf-8"))
    assert [s["role"] for s in plan["scenes"]] == ["hook", "loop"]
    assert plan["hook_headline"]["text"] == "HEAVIER THAN A CAR"
    styled = [s["scene"] for s in plan["shots"] if s["transition_in"] != "cut"]
    assert styled == [1]                                   # the loop scene
    codes = [w["code"] for w in report_of(job)["warnings"]]
    assert "scene_roles_derived" not in codes and "hook_headline_fallback" not in codes


def test_roles_survive_alignment_fallback(offline, monkeypatch):
    offline.state["scene_texts"] = ["Gold is heavy.", "A small cube weighs as much as a car."]   # paraphrased
    offline.state["scene_roles"] = ["hook", "loop"]
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True)
    job = only_job(offline.out)
    assert "alignment_fallback" in [w["code"] for w in report_of(job)["warnings"]]
    plan = json.loads((job / "sources/shot_plan.json").read_text(encoding="utf-8"))
    assert [s["role"] for s in plan["scenes"]] == ["hook", "loop"]
    assert [s["scene"] for s in plan["shots"] if s["transition_in"] != "cut"] == [1]



def test_run_video_style_reaches_the_image_prompts(offline, monkeypatch):
    seen = []
    original = AssetManager._enhance_prompt_with_style
    monkeypatch.setattr(AssetManager, "_enhance_prompt_with_style",
                        lambda self, prompt: seen.append(self.video_style) or original(self, prompt))
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True, video_style="cartoon")
    assert seen and set(seen) == {"cartoon"}


def test_no_headline_warning_when_subtitles_are_off(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True, enable_subtitles=False)
    codes = [w["code"] for w in report_of(only_job(offline.out))["warnings"]]
    assert "hook_headline_fallback" not in codes



# ---------------------------------------------------------------- quality tiers (spec 2026-10-03 §8)
# Gold fixture: 24 words, 2 scenes, 8.0 s narration (scene 1 starts at 2.32 s).

def _real_images(monkeypatch):
    """use_mock_images=False (motion on, images priced) but the image files are drawn locally."""
    original = AssetManager.generate_images
    monkeypatch.setattr(AssetManager, "generate_images",
                        lambda self, prompts, use_mock=True, output_dir=None: original(self, prompts, True, output_dir))


def _clip_calls(monkeypatch, make=False):
    """Replace the motion generator. make=True writes a real tiny clip, else every clip fails."""
    from tests.conftest import make_test_clip
    calls = []

    def generate_clip(self, image_path, prompt, output_path, duration=None, model_key=None):
        calls.append((model_key, duration))
        return str(make_test_clip(output_path, duration)) if make else None

    monkeypatch.setattr("app.motion_gen.MotionGenerator.generate_clip", generate_clip)
    return calls


def test_cap_below_pre_tts_estimate_stops_before_tts(offline, monkeypatch):
    """hailuo pre_tts: 24 words / 2.2 = 10.91 s -> 2 scenes of 5.95 s -> 2 clips $1.00 + 2 images $0.06."""
    _real_images(monkeypatch)
    tts_calls = []
    monkeypatch.setattr(AssetManager, "generate_audio", lambda *a, **k: tts_calls.append(1))
    with pytest.raises(main.CostCapError, match="before text-to-speech") as info:
        main.run_pipeline("Gold facts", max_cost=1.0)
    job = only_job(offline.out)
    assert tts_calls == [] and info.value.job_dir == str(job)
    rep = report_of(job)
    assert rep["status"] == "failed" and rep["error"].startswith("CostCapError")
    cap = [w for w in rep["warnings"] if w["code"] == "cost_cap_exceeded"]
    assert cap == [{"code": "cost_cap_exceeded", "message": cap[0]["message"],
                    "detail": {"stage": "pre_tts", "estimate": 1.06, "cap": 1.0}}]
    assert rep["cost"]["estimated"] == {"pre_tts": {
        "stage": "pre_tts", "clips": 1.0, "images": 0.06, "tts": 0.0, "llm": 0.0, "spent": 0.0,
        "total": 1.06, "model": "hailuo", "clip_seconds": 12.0}}
    assert rep["cost"]["cap"] == 1.0


def test_cap_between_estimates_stops_before_any_clip(offline, monkeypatch):
    """pre_tts $1.06 passes a $1.30 cap; the real alignment needs 3 hailuo clips (scene 1 is 6.18 s),
    so pre_clips is $1.56 and the run stops before the first clip, keeping the job folder."""
    _real_images(monkeypatch)
    calls = _clip_calls(monkeypatch)
    rendered = []
    monkeypatch.setattr(main, "render_job", lambda *a: rendered.append(1) or fake_render(*a))
    with pytest.raises(main.CostCapError, match="kept in") as info:
        main.run_pipeline("Gold facts", max_cost=1.3)
    job = only_job(offline.out)
    assert calls == [] and rendered == [] and str(job) in str(info.value)
    assert (job / "sources/narration.mp3").exists() and (job / "sources/images/scene00.png").exists()
    rep = report_of(job)
    assert rep["status"] == "failed"
    assert rep["cost"]["estimated"]["pre_tts"]["total"] == 1.06
    assert rep["cost"]["estimated"]["pre_clips"] == {
        "stage": "pre_clips", "clips": 1.5, "images": 0.06, "tts": 0.0, "llm": 0.0, "spent": 0.06,
        "total": 1.56, "model": "hailuo", "clip_seconds": 18.0}
    assert [w["detail"]["stage"] for w in rep["warnings"] if w["code"] == "cost_cap_exceeded"] == ["pre_clips"]


def test_cap_equal_to_the_estimate_is_not_exceeded(offline, monkeypatch):
    _real_images(monkeypatch)
    calls = _clip_calls(monkeypatch)                 # every clip fails -> still fallback, not strict
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", max_cost=1.56)
    rep = report_of(only_job(offline.out))
    assert rep["status"] == "ok" and len(calls) == 6          # 3 segments x (try + retry)
    assert "cost_cap_exceeded" not in [w["code"] for w in rep["warnings"]]


def test_no_cap_run_logs_exactly_the_pre_clips_estimate(offline, monkeypatch):
    """Standard tier (Kling v3): scene 0 2.32 s + 0.5 -> 3 s, scene 1 5.68 s + 0.5 -> 7 s = 10 s x $0.084.
    OpenAI LLM with a failed revision = 2 calls; ElevenLabs TTS = 1 unit. Every clip succeeds."""
    monkeypatch.setattr(settings, "quality_tier", "standard")
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "x")
    _real_images(monkeypatch)
    calls = _clip_calls(monkeypatch, make=True)
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts")
    rep = report_of(only_job(offline.out))
    assert rep["status"] == "ok" and sorted(calls) == [("kling", 3.0), ("kling", 7.0)]
    est = rep["cost"]["estimated"]
    assert set(est) == {"pre_tts", "pre_clips"} and rep["cost"]["cap"] == 0.0
    assert est["pre_clips"] == {"stage": "pre_clips", "clips": 0.84, "images": 0.06, "tts": 0.01, "llm": 0.01,
                                "spent": 0.08, "total": 0.92, "model": "kling", "clip_seconds": 10.0}
    assert round(est["pre_clips"]["spent"] + est["pre_clips"]["clips"], 4) == rep["cost"]["total"] == 0.92
    assert [i["item"] for i in rep["cost"]["actual"]].count("openai_gpt4o") == 2
    assert rep["options"]["quality_tier"] == "standard" and rep["options"]["clip_model"] == "kling"
    assert rep["options"]["max_cost"] == 0.0


def test_claude_cli_script_is_logged_at_zero(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True)
    rep = report_of(only_job(offline.out))
    assert [(i["item"], i["cost"]) for i in rep["cost"]["actual"]] == [("claude_cli", 0.0), ("claude_cli", 0.0)]
    assert rep["cost"]["total"] == 0.0


def test_explicit_tier_with_mock_images_warns_tier_ignored(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True, quality_tier="premium")
    rep = report_of(only_job(offline.out))
    assert "tier_ignored" in [w["code"] for w in rep["warnings"]]
    assert rep["options"]["quality_tier"] == "premium" and rep["options"]["clip_model"] == "kling-pro"
    assert rep["cost"]["estimated"]["pre_tts"]["clips"] == 0.0


def test_settings_default_tier_never_warns(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True)
    assert "tier_ignored" not in [w["code"] for w in report_of(only_job(offline.out))["warnings"]]


@pytest.mark.parametrize("provider, model", [("local", "local"), ("replicate", "replicate-minimax")])
def test_tier_has_no_effect_on_local_or_replicate_motion(offline, monkeypatch, provider, model):
    _real_images(monkeypatch)
    calls = _clip_calls(monkeypatch)
    monkeypatch.setattr(settings, "motion_provider", provider)
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", quality_tier="premium")
    rep = report_of(only_job(offline.out))
    assert rep["options"]["clip_model"] == model and {key for key, _ in calls} == {model}
    assert "tier_ignored" in [w["code"] for w in rep["warnings"]]


def test_classic_run_records_its_model_without_estimates(offline, monkeypatch):
    def fake_assemble(self, **kwargs):
        path = self.output_dir / kwargs["output_filename"]
        path.write_bytes(b"classic")
        return str(path)

    monkeypatch.setattr(main.VideoEditor, "assemble_video", fake_assemble)
    main.run_pipeline("Gold facts", use_mock_images=True, classic=True, quality_tier="standard", max_cost=0.01)
    rep = report_of(only_job(offline.out))
    assert rep["status"] == "ok" and rep["options"]["clip_model"] == "hailuo"
    assert rep["cost"]["estimated"] == {"pre_tts": {               # mock images: motion off, nothing priced
        "stage": "pre_tts", "clips": 0.0, "images": 0.0, "tts": 0.0, "llm": 0.0, "spent": 0.0,
        "total": 0.0, "model": "hailuo", "clip_seconds": 0.0}}
    assert rep["cost"]["cap"] == 0.01
    assert "tier_ignored" in [w["code"] for w in rep["warnings"]]


@pytest.mark.parametrize("kwargs", [{"quality_tier": "gold"}, {"max_cost": -1}, {"max_cost": float("nan")},
                                    {"max_cost": float("inf")}, {"max_cost": "abc"}, {"max_cost": True}])
def test_bad_tier_or_cap_rejected_before_any_work(offline, kwargs):
    with pytest.raises(ValueError):
        main.run_pipeline("Gold facts", use_mock_images=True, **kwargs)
    assert not offline.out.exists() or not any(offline.out.iterdir())


@pytest.mark.parametrize("model", ["sora", "local"])
def test_unknown_custom_model_rejected_before_any_work(offline, monkeypatch, model):
    monkeypatch.setattr(settings, "fal_video_model", model)
    with pytest.raises(ValueError, match="h3-turbo"):
        main.run_pipeline("Gold facts", quality_tier="custom")
    assert not offline.out.exists() or not any(offline.out.iterdir())


def test_settings_cap_applies_when_no_cap_is_passed(offline, monkeypatch):
    _real_images(monkeypatch)
    monkeypatch.setattr(settings, "max_cost_per_video", 0.5)
    with pytest.raises(main.CostCapError):
        main.run_pipeline("Gold facts")
    assert report_of(only_job(offline.out))["cost"]["cap"] == 0.5
    with pytest.raises(main.CostCapError):
        main.run_pipeline("Gold facts", max_cost=None)


def test_classic_run_enforces_the_cap_before_tts(offline, monkeypatch):
    """Classic: the script normalizes to 2 scenes -> one hailuo clip per image ($0.50 x 2) + 2 images ($0.06)
    = $1.06 > $1.00 -> stop before TTS (previously classic runs ignored the cap)."""
    _real_images(monkeypatch)
    tts_calls = []
    monkeypatch.setattr(AssetManager, "generate_audio", lambda *a, **k: tts_calls.append(1))
    with pytest.raises(main.CostCapError, match="before text-to-speech"):
        main.run_pipeline("Gold facts", classic=True, max_cost=1.0)
    rep = report_of(only_job(offline.out))
    assert tts_calls == [] and rep["status"] == "failed"
    assert rep["cost"]["estimated"]["pre_tts"] == {
        "stage": "pre_tts", "clips": 1.0, "images": 0.06, "tts": 0.0, "llm": 0.0, "spent": 0.0,
        "total": 1.06, "model": "hailuo", "clip_seconds": 12.0}
    codes = [w["code"] for w in rep["warnings"]]
    assert "cost_cap_exceeded" in codes and "cap_ignored" not in codes


def test_cap_stop_at_pre_clips_logs_what_was_already_paid(offline, monkeypatch):
    """The images (2 x $0.03) were paid before the pre_clips stop; they reach cost_log.json and the report."""
    _real_images(monkeypatch)
    _clip_calls(monkeypatch)
    with pytest.raises(main.CostCapError):
        main.run_pipeline("Gold facts", max_cost=1.3)
    job = only_job(offline.out)
    rep = report_of(job)
    assert rep["cost"]["total"] == 0.06
    assert [i["item"] for i in rep["cost"]["actual"]] == ["claude_cli", "claude_cli", "flux_image"]
    log = json.loads((offline.out / "cost_log.json").read_text(encoding="utf-8"))
    assert round(sum(i["cost"] for i in log["videos"][job.name]["items"]), 4) == 0.06


def test_cap_stop_at_pre_tts_logs_only_the_script(offline, monkeypatch):
    _real_images(monkeypatch)
    with pytest.raises(main.CostCapError):
        main.run_pipeline("Gold facts", max_cost=1.0)
    rep = report_of(only_job(offline.out))
    assert [i["item"] for i in rep["cost"]["actual"]] == ["claude_cli", "claude_cli"] and rep["cost"]["total"] == 0.0


def test_failure_after_cost_logging_does_not_log_twice(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", fake_render)
    monkeypatch.setattr(main.MetadataGenerator, "generate_metadata", _raise(RuntimeError("metadata down")))
    with pytest.raises(RuntimeError, match="metadata down"):
        main.run_pipeline("Gold facts", use_mock_images=True)
    job = only_job(offline.out)
    log = json.loads((offline.out / "cost_log.json").read_text(encoding="utf-8"))
    assert [i["item"] for i in log["videos"][job.name]["items"]] == ["claude_cli", "claude_cli"]


def test_pre_tts_stop_logs_no_narration_even_with_a_tts_key(offline, monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "x")
    _real_images(monkeypatch)
    with pytest.raises(main.CostCapError):
        main.run_pipeline("Gold facts", max_cost=1.0)
    assert [i["item"] for i in report_of(only_job(offline.out))["cost"]["actual"]] == ["claude_cli", "claude_cli"]


def test_pre_clips_stop_logs_the_narration_it_paid_for(offline, monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "x")
    _real_images(monkeypatch)
    _clip_calls(monkeypatch)
    with pytest.raises(main.CostCapError):
        main.run_pipeline("Gold facts", max_cost=1.3)
    items = [i["item"] for i in report_of(only_job(offline.out))["cost"]["actual"]]
    assert items == ["claude_cli", "claude_cli", "elevenlabs_tts", "flux_image"]


def test_render_failure_still_logs_the_generated_clips(offline, monkeypatch):
    monkeypatch.setattr(settings, "quality_tier", "standard")
    _real_images(monkeypatch)
    _clip_calls(monkeypatch, make=True)
    monkeypatch.setattr(main, "render_job", _raise(RuntimeError("encoder crashed")))
    with pytest.raises(RuntimeError, match="encoder crashed"):
        main.run_pipeline("Gold facts")
    rep = report_of(only_job(offline.out))
    clips = sorted((i["item"], i["seconds"]) for i in rep["cost"]["actual"] if i["item"].startswith("clip:"))
    assert clips == [("clip:kling", 3.0), ("clip:kling", 7.0)] and rep["cost"]["total"] == 0.9


def test_classic_assemble_failure_still_logs_the_generated_clips(offline, monkeypatch):
    _real_images(monkeypatch)
    monkeypatch.setattr(main.MotionGenerator, "generate_all_clips", lambda self, imgs, prompts: ["a.mp4", "b.mp4"])
    monkeypatch.setattr(main.VideoEditor, "assemble_video", _raise(RuntimeError("assemble failed")))
    with pytest.raises(RuntimeError, match="assemble failed"):
        main.run_pipeline("Gold facts", classic=True)
    items = report_of(only_job(offline.out))["cost"]["actual"]
    assert [(i["item"], i["quantity"]) for i in items if i["item"].startswith("clip:")] == [("clip:hailuo", 2)]


def test_partial_cost_logging_never_masks_the_original_error(offline, monkeypatch):
    _real_images(monkeypatch)
    monkeypatch.setattr(main, "_log_costs", _raise(KeyError("broken helper")))
    with pytest.raises(main.CostCapError):
        main.run_pipeline("Gold facts", max_cost=1.0)


def test_mock_image_run_that_fails_logs_no_images(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", _raise(RuntimeError("encoder crashed")))
    with pytest.raises(RuntimeError):
        main.run_pipeline("Gold facts", use_mock_images=True)
    items = [i["item"] for i in report_of(only_job(offline.out))["cost"]["actual"]]
    assert items == ["claude_cli", "claude_cli"]


def _answered_by(monkeypatch, provider):
    """Wrap the offline fake script so the script stage reports `provider` as the LLM that answered."""
    import app.llm
    fake = main.ScriptGenerator.generate_script

    def script(self, topic, **kwargs):
        app.llm._set_last_provider(provider)
        return fake(self, topic, **kwargs)

    monkeypatch.setattr(main.ScriptGenerator, "generate_script", script)


def test_report_records_the_llm_provider_that_answered(offline, monkeypatch):
    """claude_cli is configured but the fallback (OpenAI) answered: the report, the estimate and the
    cost log all follow the provider that answered."""
    import app.llm
    _answered_by(monkeypatch, "openai")
    monkeypatch.setattr(main, "render_job", fake_render)
    try:
        main.run_pipeline("Gold facts", use_mock_images=True)
    finally:
        app.llm.reset_last_provider()
    rep = report_of(only_job(offline.out))
    assert rep["status"] == "ok" and rep["script"]["llm_provider"] == "openai"
    items = [i["item"] for i in rep["cost"]["actual"]]
    assert items.count("openai_gpt4o") == 2 and "claude_cli" not in items      # draft + failed revision
    assert rep["cost"]["estimated"]["pre_tts"]["llm"] == 0.01


def test_failed_run_logs_the_llm_provider_that_answered(offline, monkeypatch):
    import app.llm
    _answered_by(monkeypatch, "codex")
    monkeypatch.setattr(main, "render_job", _raise(RuntimeError("encoder crashed")))
    try:
        with pytest.raises(RuntimeError, match="encoder crashed"):
            main.run_pipeline("Gold facts", use_mock_images=True)
    finally:
        app.llm.reset_last_provider()
    rep = report_of(only_job(offline.out))
    assert rep["script"]["llm_provider"] == "codex"
    assert [i["item"] for i in rep["cost"]["actual"]] == ["codex_cli", "codex_cli"]


def test_report_llm_provider_is_the_setting_when_no_llm_answered(offline, monkeypatch):
    """A stale thread-local value from an earlier run in this thread is never reused."""
    import app.llm
    app.llm._set_last_provider("codex")
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True)
    rep = report_of(only_job(offline.out))
    assert rep["script"]["llm_provider"] == "claude_cli"
    assert [i["item"] for i in rep["cost"]["actual"]] == ["claude_cli", "claude_cli"]
