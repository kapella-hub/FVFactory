from main import parse_args


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
