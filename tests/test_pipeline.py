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
from app.config import settings
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
    assert script == {"preset": "short", "target_seconds": 30, "target_words": 78, "word_range": [67, 89],
                      "draft_words": 24, "words": 24, "revision": "failed",
                      "narration_seconds": 8.0, "seconds_vs_target": -22.0, "words_per_second": 3.0}


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
