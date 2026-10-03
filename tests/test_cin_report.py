"""run_report.json writer (spec §10)."""
import json

from app.cin.report import RunReport


def test_warn_records_code_message_detail():
    report = RunReport(job="j")
    report.warn("still_fallback", "scene 2 is a still", {"scene": 2})
    assert report.warnings == [{"code": "still_fallback", "message": "scene 2 is a still", "detail": {"scene": 2}}]


def test_stage_accumulates_durations():
    report = RunReport(job="j")
    with report.stage("render"):
        pass
    with report.stage("render"):
        pass
    assert set(report.durations) == {"render"} and report.durations["render"] >= 0.0


def test_save_and_load_roundtrip(tmp_path):
    report = RunReport(job="j", options={"pacing": "fast"})
    report.status = "ok"
    report.loudness = {"I": -14.0, "TP": -1.5, "LRA": 4.0}
    report.warn("music_missing", "no music")
    path = tmp_path / "run_report.json"
    report.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "ok" and data["warnings"][0]["code"] == "music_missing"
    assert set(data) >= {"job", "options", "status", "error", "warnings", "loudness",
                         "platform_safe", "cost", "durations", "clips", "version"}
    assert RunReport.load(path).to_json() == data
    assert not (tmp_path / "run_report.json.tmp").exists()


def test_load_ignores_unknown_keys(tmp_path):
    path = tmp_path / "run_report.json"
    path.write_text(json.dumps({"job": "j", "status": "ok", "future_field": 1}), encoding="utf-8")
    assert RunReport.load(path).status == "ok"


def test_load_summary_of_a_saved_report(tmp_path):
    from app.cin.report import load_summary
    job = tmp_path / "20261003_1200_gold"
    job.mkdir()
    report = RunReport(job=job.name, status="ok")
    report.warn("still_fallback", "scene 1 is a still", {"scene": 1})
    report.loudness = {"I": -14.1, "TP": -1.2, "LRA": 5.0}
    report.save(job / "run_report.json")
    s = load_summary(job / "run_report.json")
    assert s == {"job": job.name, "status": "ok", "error": None,
                 "warnings": [{"code": "still_fallback", "message": "scene 1 is a still", "detail": {"scene": 1}}],
                 "loudness": {"I": -14.1, "TP": -1.2, "LRA": 5.0}, "platform_safe": None}


def test_load_summary_never_raises(tmp_path):
    from app.cin.report import load_summary
    job = tmp_path / "jobx"
    job.mkdir()
    missing = load_summary(job / "run_report.json")
    assert missing["status"] == "unknown" and missing["warnings"] == [] and missing["job"] == "jobx"
    for bad in (b"{not json", b"\xff\xfe\x00garbage", b"[1, 2]"):
        (job / "run_report.json").write_bytes(bad)
        s = load_summary(job / "run_report.json")
        assert s["status"] == "unknown" and s["warnings"] == [] and s["error"]
    (job / "run_report.json").write_text(json.dumps({"status": "ok", "warnings": ["oops", {"code": "x"}]}))
    s = load_summary(job / "run_report.json")
    assert s["warnings"] == [{"code": "x", "message": "", "detail": {}}] and s["job"] == "jobx"


def test_save_quietly_logs_instead_of_raising(tmp_path, caplog):
    report = RunReport(job="j")
    assert report.save_quietly(tmp_path / "missing_dir" / "run_report.json") is False
    assert "Could not write run report" in caplog.text
    assert report.save_quietly(tmp_path / "run_report.json") is True



def test_script_section_round_trips_and_old_reports_load_empty(tmp_path):
    report = RunReport(job="j")
    report.script = {"preset": "medium", "words": 118, "narration_seconds": 46.2}
    path = tmp_path / "run_report.json"
    report.save(path)
    assert RunReport.load(path).script == {"preset": "medium", "words": 118, "narration_seconds": 46.2}
    path.write_text(json.dumps({"job": "old", "status": "ok"}), encoding="utf-8")
    assert RunReport.load(path).script == {}


def test_script_warning_codes_registered():
    from app.cin.report import WARNING_CODES
    assert {"script_length_off_target", "scene_roles_derived", "hook_headline_fallback"} <= set(WARNING_CODES)


def test_quality_tier_warning_codes_registered_and_never_carried():
    from app.cin.editor import _CARRIED_WARNINGS
    from app.cin.report import WARNING_CODES
    assert {"cost_cap_exceeded", "tier_ignored"} <= set(WARNING_CODES)
    assert not {"cost_cap_exceeded", "tier_ignored"} & set(_CARRIED_WARNINGS)


def test_low_motion_warning_registered_and_carried_by_rerender():
    """A rerender reuses the same clips, so their low-motion verdict still applies."""
    from app.cin.editor import _CARRIED_WARNINGS
    from app.cin.report import WARNING_CODES
    assert "low_motion" in WARNING_CODES and "low_motion" in _CARRIED_WARNINGS
