import os

import pytest

from app.fsutil import atomic_write_text, replace_with_retry


def _no_sleep(monkeypatch):
    monkeypatch.setattr("app.fsutil.time.sleep", lambda s: None)


def test_replace_retries_permission_error_then_succeeds(tmp_path, monkeypatch):
    _no_sleep(monkeypatch)
    real, calls = os.replace, []

    def flaky(a, b):
        calls.append(1)
        if len(calls) <= 2:
            raise PermissionError("locked")
        return real(a, b)

    monkeypatch.setattr("app.fsutil.os.replace", flaky)
    atomic_write_text(tmp_path / "x.json", "hello")
    assert (tmp_path / "x.json").read_text(encoding="utf-8") == "hello" and len(calls) == 3
    assert list(tmp_path.glob("*.tmp")) == []


def test_replace_always_locked_cleans_tmp_and_raises(tmp_path, monkeypatch):
    _no_sleep(monkeypatch)
    (tmp_path / "x.json").write_text("old", encoding="utf-8")

    def locked(a, b):
        raise PermissionError("locked")

    monkeypatch.setattr("app.fsutil.os.replace", locked)
    with pytest.raises(PermissionError):
        atomic_write_text(tmp_path / "x.json", "new")
    assert list(tmp_path.glob("*.tmp")) == []
    assert (tmp_path / "x.json").read_text(encoding="utf-8") == "old"


def test_tmp_name_includes_pid_and_thread_id(tmp_path, monkeypatch):
    import threading
    seen = []
    real = os.replace

    def spy(a, b):
        seen.append(os.path.basename(str(a)))
        return real(a, b)

    monkeypatch.setattr("app.fsutil.os.replace", spy)
    atomic_write_text(tmp_path / "x.json", "v")
    assert seen == [f"x.json.{os.getpid()}.{threading.get_ident()}.tmp"]
