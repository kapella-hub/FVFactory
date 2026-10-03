"""Small text normalizer for speech alignment (spec §5 step 2). No third-party dependencies.

normalize_token() turns one whitespace-separated token into the lowercase words a speaker says,
so script text and Whisper text compare equal:
"1926," -> ["nineteen", "twenty", "six"], "40%" -> ["forty", "percent"], "twenty-six" -> ["twenty", "six"].
"""
import re

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_SCALES = [(1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand")]
_IRREGULAR_ORDINALS = {"one": "first", "two": "second", "three": "third", "five": "fifth",
                       "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}
_EDGE = ".,!?;:\"'()[]{}…“”‘’"
_ORDINAL_RE = re.compile(r"^(\d+)(st|nd|rd|th)$")
_INT_RE = re.compile(r"^\d+$")
_DEC_RE = re.compile(r"^\d+\.\d+$")


def _under_1000(n: int) -> list:
    words = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        words += [_ONES[hundreds], "hundred"]
    if rest >= 20:
        tens, ones = divmod(rest, 10)
        words.append(_TENS[tens])
        if ones:
            words.append(_ONES[ones])
    elif rest:
        words.append(_ONES[rest])
    return words


def cardinal(n: int) -> list:
    if n == 0:
        return ["zero"]
    words = []
    for value, name in _SCALES:
        if n >= value:
            words += cardinal(n // value) + [name]
            n %= value
    return words + _under_1000(n)


def year_words(n: int) -> list:
    """1100-1999 and 2010-2099 are read in pairs; 2000-2009 as cardinals."""
    if 2000 <= n <= 2009:
        return cardinal(n)
    hi, lo = divmod(n, 100)
    if lo == 0:
        return _under_1000(hi) + ["hundred"]
    if lo < 10:
        return _under_1000(hi) + ["oh", _ONES[lo]]
    return _under_1000(hi) + _under_1000(lo)


def _ordinal(words: list) -> list:
    last = words[-1]
    if last in _IRREGULAR_ORDINALS:
        last = _IRREGULAR_ORDINALS[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last += "th"
    return words[:-1] + [last]


def _normalize_part(part: str) -> list:
    p = part.strip(_EDGE)
    if not p:
        return []
    dollars = p.startswith("$")
    percent = p.endswith("%")
    p = p.strip("$%")
    m = _ORDINAL_RE.match(p)
    if m:
        return _ordinal(cardinal(int(m.group(1))))
    num = p.replace(",", "")
    if _INT_RE.match(num):
        n = int(num)
        is_year = len(p) == 4 and (1100 <= n <= 1999 or 2000 <= n <= 2099)
        words = year_words(n) if is_year else cardinal(n)
    elif _DEC_RE.match(num):
        whole, frac = num.split(".")
        words = cardinal(int(whole)) + ["point"] + [_ONES[int(d)] for d in frac]
    else:
        word = re.sub(r"[^a-z0-9]", "", p)  # drops apostrophes: "that's" -> "thats" on both sides
        words = [word] if word else []
    if dollars:
        words.append("dollars")
    if percent:
        words.append("percent")
    return words


def normalize_token(raw: str) -> list:
    """Normalize one whitespace token into spoken lowercase words ([] for pure punctuation)."""
    t = raw.lower().replace("’", "'").strip()
    out = []
    for part in re.split("[-–—/]", t):
        out += _normalize_part(part)
    return out
