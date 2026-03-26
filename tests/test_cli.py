from main import parse_args, resolve_voice


def test_default_args():
    args = parse_args([])
    assert args.auto is False
    assert args.batch is None
    assert args.series is None
    assert args.parts == 3
    assert args.niche is None
    assert args.no_motion is False
    assert args.subtitle_style == "bold_impact"
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
