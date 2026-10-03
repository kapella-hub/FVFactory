from main import parse_args, resolve_voice


def test_default_args():
    args = parse_args([])
    assert args.auto is False
    assert args.batch is None
    assert args.series is None
    assert args.parts == 3
    assert args.niche is None
    assert args.no_motion is False
    assert args.subtitle_style is None          # resolved to settings.subtitle_style when generating
    assert args.no_sfx is False
    assert args.no_music is False
    assert args.voice is None
    assert args.upload is False


def test_auto_mode():
    args = parse_args(["--auto"])
    assert args.auto is True


def test_batch_mode():
    args = parse_args(["--batch", "5"])
    assert args.batch == 5


def test_series_mode():
    args = parse_args(["--series", "History of Money", "--parts", "3"])
    assert args.series == "History of Money"
    assert args.parts == 3


def test_auto_with_niche():
    args = parse_args(["--auto", "--niche", "tech"])
    assert args.auto is True
    assert args.niche == "tech"


def test_style_and_feature_flags():
    args = parse_args(["--auto", "--subtitle-style", "neon_glow", "--no-motion", "--no-sfx"])
    assert args.subtitle_style == "neon_glow"
    assert args.no_motion is True
    assert args.no_sfx is True


def test_voice_preset():
    args = parse_args(["--auto", "--voice", "bill"])
    assert args.voice == "bill"


def test_voice_auto():
    args = parse_args(["--auto", "--niche", "stoicism", "--voice", "auto"])
    assert args.voice == "auto"
    assert args.niche == "stoicism"


def test_upload_flag():
    args = parse_args(["--auto", "--upload"])
    assert args.upload is True


def test_resolve_voice_none():
    assert resolve_voice(None) is None


def test_resolve_voice_preset():
    voice_id = resolve_voice("bill")
    assert voice_id == "pqHfZKP75CvOlQylNhV4"


def test_resolve_voice_auto_stoicism():
    voice_id = resolve_voice("auto", niche="stoicism")
    assert voice_id == "pqHfZKP75CvOlQylNhV4"  # bill


def test_resolve_voice_auto_unknown_niche():
    voice_id = resolve_voice("auto", niche="underwater_basket_weaving")
    assert voice_id is not None  # falls back to george


def test_resolve_voice_raw_id():
    voice_id = resolve_voice("some_custom_id_123")
    assert voice_id == "some_custom_id_123"


def test_pacing_and_strict_flags():
    args = parse_args(["--auto", "--pacing", "fast", "--strict", "--classic"])
    assert args.pacing == "fast" and args.strict is True and args.classic is True


def test_pacing_and_strict_default_to_settings():
    args = parse_args([])
    assert args.pacing is None and args.strict is False and args.classic is False


def test_unknown_pacing_rejected():
    import pytest
    with pytest.raises(SystemExit):
        parse_args(["--pacing", "hyper"])


def test_rerender_flags():
    args = parse_args(["--rerender", "output/20261002_143005_rolex", "--pacing", "fast",
                       "--color-grade", "tech", "--subtitle-style", "neon_glow", "--no-music"])
    assert args.rerender == "output/20261002_143005_rolex"
    assert args.pacing == "fast" and args.color_grade == "tech"
    assert args.subtitle_style == "neon_glow" and args.no_music is True


def test_rerender_defaults_keep_job_options():
    args = parse_args([])
    assert args.rerender is None and args.color_grade is None and args.subtitle_style is None


def test_main_rerender_skips_config_validation(monkeypatch):
    import sys
    import pytest
    import main
    calls = {}

    def fake_rerender(job_dir, **kwargs):
        calls.update(kwargs, job_dir=job_dir)
        return f"{job_dir}/final.mp4"

    def must_not_validate(*args, **kwargs):
        raise AssertionError("validate_config must not run for --rerender")

    monkeypatch.setattr("app.cin.editor.rerender_job", fake_rerender)
    monkeypatch.setattr(main, "validate_config", must_not_validate)
    monkeypatch.setattr(sys, "argv", ["main.py", "--rerender", "output/job", "--pacing", "fast", "--no-sfx"])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == 0
    assert calls == {"job_dir": "output/job", "pacing": "fast", "subtitle_style": None,
                     "no_sfx": True, "no_music": False, "color_grade": None, "music_source": None}


def test_music_source_flag():
    import pytest
    assert parse_args([]).music_source is None
    assert parse_args(["--music-source", "generated"]).music_source == "generated"
    assert parse_args(["--rerender", "output/j", "--music-source", "none"]).music_source == "none"
    with pytest.raises(SystemExit):
        parse_args(["--music-source", "spotify"])
