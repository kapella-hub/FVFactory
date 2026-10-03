"""Spoken-form normalizer used by speech alignment (spec §5 step 2)."""
import pytest

from app.cin.textnorm import cardinal, normalize_token


@pytest.mark.parametrize("raw, expected", [
    ("1926,", ["nineteen", "twenty", "six"]),
    ("1905", ["nineteen", "oh", "five"]),
    ("1900", ["nineteen", "hundred"]),
    ("2005", ["two", "thousand", "five"]),
    ("2024", ["twenty", "twenty", "four"]),
    ("1000", ["one", "thousand"]),
    ("115", ["one", "hundred", "fifteen"]),
    ("1", ["one"]),
    ("1,000,000", ["one", "million"]),
    ("1,250,000", ["one", "million", "two", "hundred", "fifty", "thousand"]),
    ("$5,000", ["five", "thousand", "dollars"]),
    ("40%", ["forty", "percent"]),
    ("2.5", ["two", "point", "five"]),
    ("21st", ["twenty", "first"]),
    ("3rd", ["third"]),
    ("12th", ["twelfth"]),
    ("40th", ["fortieth"]),
    ("twenty-six", ["twenty", "six"]),
    ("That's", ["thats"]),
    ("Hello,", ["hello"]),
    ("(Rolex)", ["rolex"]),
    ("—", []),
    ("...", []),
])
def test_normalize_token(raw, expected):
    assert normalize_token(raw) == expected


def test_digit_and_word_forms_compare_equal():
    assert normalize_token("1926") == normalize_token("nineteen") + normalize_token("twenty-six")
    assert normalize_token("40%") == normalize_token("40") + normalize_token("percent")


def test_cardinal_zero():
    assert cardinal(0) == ["zero"]
