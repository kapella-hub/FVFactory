"""Speech alignment: Whisper word timings mapped onto the script's own tokens (spec §5).

Pure core: align_words(). I/O wrapper: align() (runs Whisper). Captions use the script's
spelling with Whisper's timings; scene boundaries come from the first token of each scene.
"""
from __future__ import annotations

import difflib
import logging
import threading
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np

from app.cin.textnorm import normalize_token

logger = logging.getLogger(__name__)

MATCH_THRESHOLD = 0.70          # spec §5 step 5
MIN_SCENE = 1.0 / 30            # a scene is never shorter than one frame at 30 fps
_EDGE_PUNCT = ".,!?;:\"'()[]{}…—–“”‘’"
_SENTENCE_END = (".", "!", "?", "…")
_CLAUSE_END = (",", ";", ":", "—", "–")


@dataclass
class AlignedToken:
    text: str            # script spelling, edge punctuation stripped ("Wilsdorf", "That's")
    t0: float
    t1: float
    matched: bool        # False = timing interpolated (or a fallback token)
    sentence_end: bool = False
    comma: bool = False


@dataclass
class SceneSpan:
    index: int
    t0: float
    t1: float
    text: str
    first_token: int     # index into Alignment.tokens
    last_token: int      # exclusive


@dataclass
class Alignment:
    method: str                      # "whisper+script" | "word_count"
    fallback: bool
    match_ratio: float
    duration: float
    tokens: list = field(default_factory=list)
    scenes: list = field(default_factory=list)
    reason: str = ""                 # why the fallback was used ("" when it was not)

    def to_json(self) -> dict:
        return {
            "method": self.method,
            "fallback": self.fallback,
            "match_ratio": round(self.match_ratio, 4),
            "duration": round(self.duration, 4),
            "reason": self.reason,
            "tokens": [asdict(t) for t in self.tokens],
            "scenes": [asdict(s) for s in self.scenes],
        }

    @classmethod
    def from_json(cls, d: dict) -> "Alignment":
        return cls(
            method=d["method"], fallback=d["fallback"], match_ratio=d["match_ratio"],
            duration=d["duration"], reason=d.get("reason", ""),
            tokens=[AlignedToken(**t) for t in d["tokens"]],
            scenes=[SceneSpan(**s) for s in d["scenes"]],
        )


def _token_info(raw: str):
    """(display, normalized_words, sentence_end, comma) for one whitespace token; None if empty."""
    norm = normalize_token(raw)
    if not norm:
        return None
    tail = raw.rstrip("\"'”’)]")
    display = raw.strip(_EDGE_PUNCT) or raw
    return display, norm, tail.endswith(_SENTENCE_END), tail.endswith(_CLAUSE_END)


def script_tokens(text: str) -> list:
    return [info for info in (_token_info(r) for r in text.split()) if info]


def _whisper_subwords(words: list):
    subwords, times = [], []
    for wd in words:
        if "start" not in wd or "end" not in wd:
            continue
        for w in normalize_token(wd.get("word", "")):
            subwords.append(w)
            times.append((float(wd["start"]), float(wd["end"])))
    return subwords, times


def _interpolate(t0: list, t1: list, duration: float) -> None:
    """Fill unmatched runs evenly between matched neighbours (0.0 / duration at the edges)."""
    n = len(t0)
    i = 0
    while i < n:
        if t0[i] is not None:
            i += 1
            continue
        j = i
        while j < n and t0[j] is None:
            j += 1
        left = t1[i - 1] if i > 0 else 0.0
        right = max(t0[j] if j < n else duration, left)
        step = (right - left) / (j - i)
        for k in range(i, j):
            t0[k] = left + step * (k - i)
            t1[k] = left + step * (k - i + 1)
        i = j
    for k in range(1, n):
        t0[k] = max(t0[k], t0[k - 1])
        t1[k] = max(t1[k], t0[k])


def _enforce_min_gaps(starts: list, duration: float) -> list:
    """Strictly increasing scene starts, every scene >= MIN_SCENE, first scene starts at 0."""
    n = len(starts)
    if n == 0:
        return []
    if duration < n * MIN_SCENE:
        return [duration * k / n for k in range(n)]
    out = list(starts)
    out[0] = 0.0
    for k in range(1, n):
        out[k] = max(out[k], out[k - 1] + MIN_SCENE)
    for k in range(n - 1, 0, -1):
        upper = duration if k == n - 1 else out[k + 1]
        out[k] = min(out[k], upper - MIN_SCENE)
    return out


def _spans(starts: list, duration: float) -> list:
    return [(starts[k], starts[k + 1] if k + 1 < len(starts) else duration) for k in range(len(starts))]


def _fallback_tokens(words: list, narration: str, duration: float) -> list:
    tokens = []
    for wd in words:
        info = _token_info(wd.get("word", "").strip())
        if info and "start" in wd and "end" in wd:
            tokens.append(AlignedToken(info[0], round(float(wd["start"]), 3), round(float(wd["end"]), 3),
                                       False, info[2], info[3]))
    if tokens:
        return tokens
    infos = script_tokens(narration)
    weights = [len(i[0]) + 1 for i in infos]
    total = sum(weights) or 1
    acc = 0.0
    for info, w in zip(infos, weights):
        a = duration * acc / total
        acc += w
        tokens.append(AlignedToken(info[0], round(a, 3), round(duration * acc / total, 3), False, info[2], info[3]))
    return tokens


def word_count_alignment(words: list, scene_texts: list, narration: str, duration: float,
                         num_scenes: int, reason: str, match_ratio: float = 0.0) -> Alignment:
    """Spec §5 step 5 fallback: scene lengths proportional to scene word counts."""
    n = max(num_scenes, 1)
    if scene_texts and len(scene_texts) == n:
        weights = [max(len(t.split()), 1) for t in scene_texts]
        texts = list(scene_texts)
    else:
        weights = [1] * n
        texts = [""] * n
    total = sum(weights)
    starts, acc = [], 0
    for w in weights:
        starts.append(duration * acc / total)
        acc += w
    starts = _enforce_min_gaps(starts, duration)
    tokens = _fallback_tokens(words, narration, duration)
    scenes = []
    for si, (s0, s1) in enumerate(_spans(starts, duration)):
        idx = [i for i, t in enumerate(tokens)
               if s0 <= (t.t0 + t.t1) / 2 < s1 or (si == n - 1 and (t.t0 + t.t1) / 2 >= s1)]
        first = idx[0] if idx else (scenes[-1].last_token if scenes else 0)
        last = idx[-1] + 1 if idx else first
        scenes.append(SceneSpan(si, round(s0, 4), round(s1, 4), texts[si], first, last))
    return Alignment("word_count", True, match_ratio, duration, tokens, scenes, reason)


def align_words(words: list, scene_texts: list, narration: str, duration: float,
                num_scenes: Optional[int] = None) -> Alignment:
    """Pure alignment of Whisper words (whisper's dict format) to the script's scene_texts."""
    n = num_scenes or len(scene_texts) or 1
    if not scene_texts:
        return word_count_alignment(words, [], narration, duration, n, reason="scene_texts_missing")
    if len(scene_texts) != n:
        return word_count_alignment(words, scene_texts, narration, duration, n, reason="scene_count_mismatch")
    per_scene = [script_tokens(t) for t in scene_texts]
    joined = [w for toks in per_scene for tok in toks for w in tok[1]]
    narr = [w for tok in script_tokens(narration) for w in tok[1]]
    if not joined or joined != narr:
        return word_count_alignment(words, scene_texts, narration, duration, n, reason="scene_texts_do_not_join")

    flat = [(si, tok) for si, toks in enumerate(per_scene) for tok in toks]
    s_words, s_owner = [], []
    for ti, (_, tok) in enumerate(flat):
        for w in tok[1]:
            s_words.append(w)
            s_owner.append(ti)
    w_words, w_times = _whisper_subwords(words)

    # autojunk=False: with autojunk on, words like "the" are ignored once a sequence has 200+ items.
    sm = difflib.SequenceMatcher(None, s_words, w_words, autojunk=False)
    t0 = [None] * len(flat)
    t1 = [None] * len(flat)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            ti = s_owner[a + k]
            st, en = w_times[b + k]
            t0[ti] = st if t0[ti] is None else min(t0[ti], st)
            t1[ti] = en if t1[ti] is None else max(t1[ti], en)
    matched = [x is not None for x in t0]
    ratio = sum(matched) / len(flat)
    if ratio < MATCH_THRESHOLD:
        return word_count_alignment(words, scene_texts, narration, duration, n,
                                    reason="low_match_ratio", match_ratio=ratio)

    _interpolate(t0, t1, duration)
    tokens = [AlignedToken(tok[0], round(t0[i], 3), round(t1[i], 3), matched[i], tok[2], tok[3])
              for i, (_, tok) in enumerate(flat)]
    owners = [si for si, _ in flat]

    starts, ranges, cursor = [], [], 0
    for si in range(n):
        idx = [i for i, o in enumerate(owners) if o == si]
        if idx:
            starts.append(tokens[idx[0]].t0)
            ranges.append((idx[0], idx[-1] + 1))
            cursor = idx[-1] + 1
        else:  # empty scene text: zero length here, widened by _enforce_min_gaps
            starts.append(tokens[cursor - 1].t1 if cursor else 0.0)
            ranges.append((cursor, cursor))
    starts = _enforce_min_gaps(starts, duration)
    scenes = [SceneSpan(si, round(s0, 4), round(s1, 4), scene_texts[si], ranges[si][0], ranges[si][1])
              for si, (s0, s1) in enumerate(_spans(starts, duration))]
    return Alignment("whisper+script", False, ratio, duration, tokens, scenes)


# ---------------------------------------------------------------- Whisper I/O

_MODELS: dict = {}
_MODEL_LOCK = threading.Lock()
_TRANSCRIBE_LOCK = threading.Lock()


def _load_whisper(name: str):
    with _MODEL_LOCK:
        if name not in _MODELS:
            import whisper
            logger.info("Loading Whisper '%s' model...", name)
            _MODELS[name] = whisper.load_model(name)
        return _MODELS[name]


def _audio_16k(audio_path) -> np.ndarray:
    """Decode to mono 16 kHz float32 with ffmpeg directly (find_ffmpeg falls back to imageio-ffmpeg,
    so Whisper does not need ffmpeg on PATH). MoviePy 2.1.2's to_soundarray(fps=16000) returned a
    constant array, which Whisper heard as silence."""
    import subprocess
    from app.encoding import find_ffmpeg
    proc = subprocess.run([find_ffmpeg(), "-nostdin", "-i", str(audio_path), "-f", "f32le",
                           "-ac", "1", "-ar", "16000", "-"], capture_output=True)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace")[-500:]
        raise RuntimeError(f"ffmpeg audio decode failed (exit {proc.returncode}): {tail}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def transcribe_words(audio_path, model_name: str) -> list:
    """Whisper word timings as [{"word", "start", "end"}] (whisper's own word-dict keys)."""
    model = _load_whisper(model_name)
    audio = _audio_16k(audio_path)
    with _TRANSCRIBE_LOCK:  # whisper models are not thread-safe; concurrent jobs take turns
        result = model.transcribe(audio, word_timestamps=True, language="en", fp16=False)
    return [{"word": w["word"], "start": float(w["start"]), "end": float(w["end"])}
            for seg in result.get("segments", []) for w in seg.get("words", [])]


def align(audio_path, scene_texts: list, narration: str, duration: float, *,
          num_scenes: Optional[int] = None, model_name: Optional[str] = None):
    """Transcribe + align. Returns (Alignment, whisper_words). Never raises for Whisper failures."""
    from app.config import settings
    n = num_scenes or len(scene_texts) or 1
    try:
        words = transcribe_words(audio_path, model_name or settings.whisper_model)
    except Exception as e:  # noqa: BLE001 - any Whisper failure becomes a reported fallback
        logger.warning("Whisper transcription failed, using word-count split: %s", e)
        return word_count_alignment([], scene_texts, narration, duration, n,
                                    reason=f"transcription_failed: {e}"), []
    return align_words(words, scene_texts, narration, duration, num_scenes=n), words
