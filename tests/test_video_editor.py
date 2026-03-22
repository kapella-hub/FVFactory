from app.video_editor import VideoEditor


def test_calculate_paced_durations_equal():
    editor = VideoEditor()
    durations = editor._calculate_paced_durations(40.0, 5, pacing_hints=None)
    assert len(durations) == 5
    assert all(abs(d - 8.0) < 0.01 for d in durations)


def test_calculate_paced_durations_weighted():
    editor = VideoEditor()
    hints = ["fast", "normal", "slow", "dramatic_pause", "normal"]
    durations = editor._calculate_paced_durations(40.0, 5, pacing_hints=hints)
    assert len(durations) == 5
    assert abs(sum(durations) - 40.0) < 0.01
    assert durations[0] < durations[1]  # fast < normal
    assert durations[3] > durations[2]  # dramatic_pause > slow


def test_calculate_paced_durations_unknown_hint():
    editor = VideoEditor()
    hints = ["unknown", "normal", "normal", "normal", "normal"]
    durations = editor._calculate_paced_durations(40.0, 5, pacing_hints=hints)
    assert len(durations) == 5
    assert abs(sum(durations) - 40.0) < 0.01


def test_apply_color_grade_returns_same_shape():
    import numpy as np
    editor = VideoEditor()
    frame = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
    result = editor._apply_color_grade(frame, "tech")
    assert result.shape == frame.shape
    assert result.dtype == np.uint8


def test_apply_color_grade_unknown_returns_original():
    import numpy as np
    editor = VideoEditor()
    frame = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
    result = editor._apply_color_grade(frame, "nonexistent")
    assert (result == frame).all()


def test_assemble_video_accepts_v2_params():
    """Verify the v2 signature is accepted (doesn't test full rendering)."""
    import inspect
    editor = VideoEditor()
    sig = inspect.signature(editor.assemble_video)
    params = list(sig.parameters.keys())
    assert "motion_clip_paths" in params
    assert "pacing_hints" in params
    assert "subtitle_style" in params
    assert "color_grade" in params
    assert "enable_sfx" in params
    assert "enable_intro" in params
