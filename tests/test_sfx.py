import tempfile
from pathlib import Path
from app.sfx import SFXMixer


def test_sfx_mixer_init():
    mixer = SFXMixer()
    assert mixer.sfx_dir is not None


def test_build_sfx_track_with_no_sfx_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        mixer = SFXMixer(sfx_dir=tmpdir)
        result = mixer.build_sfx_track(
            scene_timestamps=[0.0, 8.0, 16.0, 24.0, 32.0],
            total_duration=40.0,
        )
        assert result is None


def test_get_scene_transition_times():
    mixer = SFXMixer()
    timestamps = [0.0, 8.0, 16.0, 24.0, 32.0]
    transitions = mixer._get_transition_times(timestamps)
    assert transitions == [8.0, 16.0, 24.0, 32.0]
