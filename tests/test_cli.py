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
    assert args.pacing is None and args.strict is None and args.classic is False


def test_strict_has_an_opt_out():
    assert parse_args(["--no-strict"]).strict is False
    assert parse_args(["--strict"]).strict is True
    assert parse_args([]).strict is None


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


def test_library_builder_flags():
    import pytest
    args = parse_args(["--build-music-library", "--per-mood", "3", "--moods", "epic, dark", "--yes"])
    assert args.build_music_library is True and args.per_mood == 3
    assert args.moods == ["epic", "dark"] and args.yes is True
    d = parse_args([])
    assert d.build_music_library is False and d.build_sfx_library is False
    assert d.per_mood == 5 and d.moods is None and d.yes is False
    for bad in (["--moods", "epic,jazz"], ["--per-mood", "0"], ["--per-mood", "50"]):
        with pytest.raises(SystemExit):
            parse_args(bad)


def test_main_builders_skip_config_validation(monkeypatch):
    import sys
    import pytest
    import main
    calls = []

    def must_not_validate(*a, **k):
        raise AssertionError("validate_config must not run for library builders")

    monkeypatch.setattr(main, "validate_config", must_not_validate)
    monkeypatch.setattr("app.cin.library_builder.build_sfx_library",
                        lambda **kw: calls.append(("sfx", kw)) or 0)
    monkeypatch.setattr("app.cin.library_builder.build_music_library",
                        lambda **kw: calls.append(("music", kw)) or 1)
    monkeypatch.setattr(sys, "argv", ["main.py", "--build-sfx-library", "--build-music-library",
                                      "--moods", "epic", "--per-mood", "2", "--yes"])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == 1                       # worst of the two exit codes
    assert calls == [("sfx", {"yes": True}), ("music", {"per_mood": 2, "moods": ["epic"], "yes": True})]


def test_main_module_has_no_unused_imports_or_dead_helpers():
    """Housekeeping guard (Phase D): every top-level import in main.py is referenced."""
    import ast
    from pathlib import Path
    import main
    tree = ast.parse(Path(main.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            imported |= {a.asname or a.name for a in node.names}
        elif isinstance(node, ast.Import):
            imported |= {(a.asname or a.name).split(".")[0] for a in node.names}
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert imported - used == set()
    assert not hasattr(main, "generate_output_filename")


def test_superseded_cinematic_modules_are_gone():
    import importlib.util
    for name in ("audio_analysis", "depth", "parallax", "kinetic_text"):
        assert importlib.util.find_spec(f"app.cin.{name}") is None, name
