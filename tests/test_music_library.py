"""Music library listing and least-recently-used selection (spec §8.1)."""
import json
import threading
from pathlib import Path

import pytest

from app.cin.music_library import (UsageStore, list_tracks, lru_order, select_track)


def touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return p


def test_list_tracks_by_source(tmp_path):
    a = touch(tmp_path / "epic" / "a.mp3")
    g = touch(tmp_path / "epic" / "generated" / "epic_01.mp3")
    touch(tmp_path / "epic" / "notes.txt")
    touch(tmp_path / "epic" / "generated" / "epic_02.mp3.part")      # interrupted download
    d = touch(tmp_path / "dark" / "d.wav")
    assert list_tracks(tmp_path, "epic", "mine") == [a]
    assert list_tracks(tmp_path, "epic", "generated") == [g]
    assert list_tracks(tmp_path, "epic", "any") == [a, g]
    assert list_tracks(tmp_path, "epic", "none") == []
    assert set(list_tracks(tmp_path, "", "any")) == {a, g, d}      # mood "" = every mood
    assert list_tracks(tmp_path / "missing", "epic", "any") == []


def test_unknown_source_rejected(tmp_path):
    with pytest.raises(ValueError):
        list_tracks(tmp_path, "epic", "spotify")


def test_lru_order_never_used_first_then_oldest():
    a, b, c = Path("m/a.mp3"), Path("m/b.mp3"), Path("m/c.mp3")
    assert lru_order([c, b, a], {}) == [a, b, c]
    usage = {"m/a.mp3": {"last_used": 50.0}, "m/b.mp3": {"last_used": 10.0}}
    assert lru_order([a, b, c], usage) == [c, b, a]
    assert lru_order([a, b], {"m/a.mp3": {"last_used": "garbage"}}) == [a, b]


def test_select_track_rotates_and_records(tmp_path):
    a, b = Path("m/a.mp3"), Path("m/b.mp3")
    store = UsageStore(tmp_path / "u.json")
    assert [select_track([a, b], store, now=t) for t in (1.0, 2.0, 3.0)] == [a, b, a]
    tracks = json.loads((tmp_path / "u.json").read_text(encoding="utf-8"))["tracks"]
    assert tracks["m/a.mp3"] == {"last_used": 3.0, "count": 2}
    assert select_track([], store) is None


def test_select_track_skips_rejected_candidates(tmp_path):
    a, b = Path("m/a.mp3"), Path("m/b.mp3")
    store = UsageStore(tmp_path / "u.json")
    assert select_track([a, b], store, accept=lambda p: p != a, now=1.0) == b
    assert "m/a.mp3" not in store.load()
    assert select_track([a], store, accept=lambda p: False) is None


def test_corrupt_usage_file_is_ignored_and_rewritten(tmp_path):
    usage = tmp_path / "music_usage.json"
    a = Path("m/a.mp3")
    for junk in ("{not json", "[1, 2]", '{"tracks": "nope"}'):
        usage.write_text(junk, encoding="utf-8")
        store = UsageStore(usage)
        assert store.load() == {}
        assert select_track([a], store, now=7.0) == a
        assert json.loads(usage.read_text(encoding="utf-8"))["tracks"]["m/a.mp3"]["count"] == 1


def test_usage_folder_is_created(tmp_path):
    usage = tmp_path / "data" / "nested" / "music_usage.json"
    assert select_track([Path("m/a.mp3")], UsageStore(usage), now=1.0) is not None
    assert usage.exists()


def test_concurrent_selection_picks_distinct_tracks(tmp_path):
    tracks = [Path(f"m/{i}.mp3") for i in range(4)]
    path = tmp_path / "u.json"
    got, barrier = [], threading.Barrier(4)

    def job():
        barrier.wait()
        got.append(select_track(tracks, UsageStore(path)))

    threads = [threading.Thread(target=job) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(got) == sorted(tracks)


def test_default_usage_path_is_isolated_in_tests(tmp_path):
    from app.cin import music_library
    assert "music_usage.json" in str(music_library.default_usage_path())
    assert Path(music_library.default_usage_path()).parent.name == "data"
    assert Path("data/music_usage.json").resolve() != Path(music_library.default_usage_path()).resolve()


def test_settings_music_source_default_and_validation(monkeypatch):
    from pydantic import ValidationError
    from app.config import Settings
    for name in Settings.model_fields:          # .env leaks into os.environ via MoviePy's load_dotenv
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.upper(), raising=False)
    s = Settings(_env_file=None)
    assert s.music_source == "any" and s.elevenlabs_music_model == "music_v1"
    assert s.cost_elevenlabs_music_per_minute == 0.15 and s.cost_elevenlabs_sfx_per_minute == 0.12
    with pytest.raises(ValidationError):
        Settings(_env_file=None, music_source="spotify")


def test_render_options_music_source_roundtrip():
    from app.cin.editor import RenderOptions
    assert RenderOptions().music_source == "any"
    opts = RenderOptions(music_source="generated")
    assert RenderOptions.from_json(opts.to_json()).music_source == "generated"


def test_phase_c_warning_codes_registered():
    from app.cin.report import WARNING_CODES
    assert {"music_missing", "sfx_missing", "music_track_skipped", "sfx_file_skipped"} <= set(WARNING_CODES)


def test_unreadable_usage_file_is_not_overwritten(tmp_path, monkeypatch):
    path = tmp_path / "u.json"
    original = json.dumps({"version": 1, "tracks": {"m/z.mp3": {"last_used": 5.0, "count": 9}}})
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr("app.cin.music_library.time.sleep", lambda s: None)
    real = Path.read_text

    def locked(self, *a, **k):
        if self.name == "u.json":
            raise PermissionError("locked")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", locked)
    assert select_track([Path("m/a.mp3")], UsageStore(path), now=1.0) == Path("m/a.mp3")
    monkeypatch.undo()
    assert path.read_text(encoding="utf-8") == original


def test_save_failure_never_raises_and_leaves_no_tmp(tmp_path, monkeypatch):
    real = Path.write_text

    def boom(self, *a, **k):
        if self.name.endswith(".tmp"):
            real(self, "partial", encoding="utf-8")
            raise OSError("disk full")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", boom)
    assert select_track([Path("m/a.mp3")], UsageStore(tmp_path / "u.json"), now=1.0) == Path("m/a.mp3")
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_retries_replace_on_permission_error(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr("app.cin.music_library.time.sleep", lambda s: None)
    real, calls = os.replace, []

    def flaky(src, dst):
        calls.append(1)
        if len(calls) <= 2:
            raise PermissionError("busy")
        return real(src, dst)

    monkeypatch.setattr("app.cin.music_library.os.replace", flaky)
    path = tmp_path / "u.json"
    assert UsageStore(path).save({"m/a.mp3": {"last_used": 1.0, "count": 1}}) is True
    assert len(calls) == 3 and json.loads(path.read_text(encoding="utf-8"))["tracks"]["m/a.mp3"]["count"] == 1
