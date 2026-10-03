"""--build-music-library / --build-sfx-library (spec §8.1-8.2). HTTP is always a fake `post`."""
import pytest
import requests

from app.cin import library_builder as lb
from app.config import settings

FAKE_KEY = "test-key-not-real"


class Resp:
    def __init__(self, status, content=b"", js=None, text=""):
        self.status_code, self.content, self._js, self.text = status, content, js, text

    def json(self):
        if self._js is None:
            raise ValueError("no json")
        return self._js


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "music_dir", str(tmp_path / "music"))
    monkeypatch.setattr(settings, "sfx_dir", str(tmp_path / "sfx"))
    monkeypatch.setattr(settings, "elevenlabs_api_key", FAKE_KEY)
    monkeypatch.setattr(settings, "elevenlabs_music_model", "music_v1")

    def no_network(*a, **k):
        raise AssertionError("real network call")

    monkeypatch.setattr(requests, "post", no_network)
    monkeypatch.setattr(requests, "get", no_network)
    return tmp_path


def recorder(responses=None):
    responses = list(responses or [])
    calls = []

    def post(url, **kw):
        calls.append((url, kw))
        return responses.pop(0) if responses else Resp(200, b"ID3fake-audio")
    return post, calls


def test_music_build_requests_estimate_and_files(env):
    post, calls = recorder()
    lines = []
    code = lb.build_music_library(per_mood=5, yes=True, post=post, sleep=lambda s: None, out=lines.append)
    assert code == 0 and len(calls) == 25
    assert any("$3.75" in line for line in lines)                      # 25 x 60 s x $0.15/min
    url, kw = calls[0]
    assert url == "https://api.elevenlabs.io/v1/music"
    assert kw["params"] == {"output_format": "mp3_44100_128"}
    body = kw["json"]
    assert body["music_length_ms"] == 60000 and body["force_instrumental"] is True
    assert body["model_id"] == "music_v1" and "no vocals" in body["prompt"]
    assert kw["headers"]["xi-api-key"] == FAKE_KEY
    assert calls[0][1]["timeout"] == 300
    assert (env / "music" / "epic" / "generated" / "epic_05.mp3").read_bytes() == b"ID3fake-audio"
    assert not list((env / "music").rglob("*.part"))
    assert all(FAKE_KEY not in line for line in lines)


def test_existing_files_are_skipped(env):
    post, calls = recorder()
    lb.build_music_library(per_mood=2, moods=["dark"], yes=True, post=post, out=lambda s: None)
    post2, calls2 = recorder()
    lines = []
    assert lb.build_music_library(per_mood=3, moods=["dark"], yes=True, post=post2, out=lines.append) == 0
    assert len(calls2) == 1 and calls2[0][1]["json"]["prompt"]                 # only dark_03
    assert sum("skip (exists)" in line for line in lines) == 2


def test_confirmation_declined_or_no_tty(env):
    post, calls = recorder()
    assert lb.build_sfx_library(input_fn=lambda prompt: "n", post=post, out=lambda s: None) == 1

    def eof(prompt):
        raise EOFError

    assert lb.build_sfx_library(input_fn=eof, post=post, out=lambda s: None) == 1
    assert calls == []
    assert lb.build_sfx_library(input_fn=lambda prompt: "y", post=post, out=lambda s: None) == 0
    assert len(calls) == 7


def test_plan_or_permission_refusal_stops_with_clear_message(env):
    for status in (401, 402, 403):
        post, calls = recorder([Resp(status, js={"detail": {"status": "missing_permissions",
                                                            "message": "Music requires a paid plan"}})])
        lines = []
        code = lb.build_music_library(per_mood=2, moods=["epic"], yes=True, post=post,
                                      sleep=lambda s: None, out=lines.append)
        assert code == 2 and len(calls) == 1
        msg = " ".join(lines)
        assert f"HTTP {status}" in msg and "paid plan" in msg and "plan" in msg and FAKE_KEY not in msg
    assert not list((env / "music").rglob("*.mp3"))


def test_rate_limit_retries_and_bad_prompt_continues(env):
    post, calls = recorder([Resp(429, text="busy"), Resp(200, b"ID3ok"),
                            Resp(422, js={"detail": [{"msg": "prompt rejected"}]})])
    sleeps, lines = [], []
    code = lb.build_music_library(per_mood=3, moods=["chill"], yes=True, post=post,
                                  sleep=sleeps.append, out=lines.append)
    assert code == 1 and len(calls) == 4 and sleeps == [5]       # 429 retried; 422 not retried
    assert any("prompt rejected" in line for line in lines)
    assert sorted(p.name for p in (env / "music" / "chill" / "generated").iterdir()) == ["chill_01.mp3", "chill_03.mp3"]


def test_network_errors_retry_then_fail(env):
    def flaky(url, **kw):
        raise requests.ConnectionError("down")
    lines = []
    code = lb.build_sfx_library(yes=True, post=flaky, sleep=lambda s: None, out=lines.append)
    assert code == 1 and any("network error" in line for line in lines)


def test_sfx_build_requests(env):
    post, calls = recorder()
    assert lb.build_sfx_library(yes=True, post=post, sleep=lambda s: None, out=lambda s: None) == 0
    assert len(calls) == 7 and calls[0][0] == "https://api.elevenlabs.io/v1/sound-generation"
    body = calls[0][1]["json"]
    assert body["model_id"] == "eleven_text_to_sound_v2" and 0.5 <= body["duration_seconds"] <= 30
    assert body["loop"] is False and "text" in body
    names = sorted(p.name for p in (env / "sfx" / "generated").iterdir())
    assert names == ["impact_1.mp3", "impact_2.mp3", "riser_1.mp3", "riser_2.mp3",
                     "whoosh_1.mp3", "whoosh_2.mp3", "whoosh_3.mp3"]


def test_missing_key_never_calls_api(env, monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    post, calls = recorder()
    lines = []
    assert lb.build_music_library(per_mood=1, moods=["epic"], yes=True, post=post, out=lines.append) == 2
    assert calls == [] and any("ELEVENLABS_API_KEY" in line for line in lines)


def test_default_post_resolves_requests_at_call_time(env):
    """The env fixture patched requests.post; a builder call without `post` must hit the patch."""
    with pytest.raises(AssertionError, match="real network call"):
        lb.fetch_item(lb.plan_sfx_items(settings.sfx_dir)[0][0], FAKE_KEY, sleep=lambda s: None)


def test_non_audio_200_is_not_saved(env):
    bad = Resp(200, b'{"detail":"x"}', js={"detail": "quota exceeded"})
    bad.headers = {"Content-Type": "application/json"}
    post, calls = recorder([bad])
    lines = []
    code = lb.build_music_library(per_mood=1, moods=["epic"], yes=True, post=post,
                                  sleep=lambda s: None, out=lines.append)
    assert code == 1 and len(calls) == 1
    assert any("not audio" in line and "quota exceeded" in line for line in lines)
    assert not list((env / "music").rglob("*.mp3")) and not list((env / "music").rglob("*.part"))


def test_audio_detection_by_header_or_magic(env):
    ok_hdr = Resp(200, bytes([0, 1]) + b"raw")
    ok_hdr.headers = {"Content-Type": "audio/mpeg"}
    sync = Resp(200, bytes([0xFF, 0xFB]) + b"data")
    post, _ = recorder([ok_hdr, sync])
    assert lb.build_music_library(per_mood=2, moods=["dark"], yes=True, post=post,
                                  sleep=lambda s: None, out=lambda s: None) == 0
