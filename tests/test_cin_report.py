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
