"""--build-music-library / --build-sfx-library (spec §8.1, §8.2) via the ElevenLabs API.

Endpoints (verified 2026-10-03):
  POST https://api.elevenlabs.io/v1/music             https://elevenlabs.io/docs/api-reference/music/compose
  POST https://api.elevenlabs.io/v1/sound-generation  https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert
Prices: https://elevenlabs.io/pricing/api (Music $0.15/min, Sound Effects $0.12/min).
Never imported by the render path. Tests always inject `post`."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests

from app.cin.music_library import GENERATED_DIR, MOODS, MUSIC_EXTENSIONS
from app.config import settings

API_ROOT = "https://api.elevenlabs.io/v1"
MUSIC_URL = f"{API_ROOT}/music"
SFX_URL = f"{API_ROOT}/sound-generation"
OUTPUT_FORMAT = "mp3_44100_128"        # 192 kbps output is Creator-tier gated
TRACK_SECONDS = 60
SFX_MODEL = "eleven_text_to_sound_v2"
MAX_ATTEMPTS = 3                       # for 429 / 5xx / network errors
MUSIC_TIMEOUT = 300
SFX_TIMEOUT = 120

MOOD_PROMPTS = {
    "chill": "calm lo-fi ambient groove, soft electric piano, warm pads, gentle brushed drums",
    "cinematic": "cinematic documentary underscore, strings and piano, steady pulse, curious and hopeful",
    "dark": "dark suspenseful underscore, low drones, ticking percussion, tense synth pulses",
    "epic": "epic orchestral trailer bed, driving percussion, brass swells, heroic strings",
    "upbeat": "upbeat modern pop instrumental, bright plucks, claps, punchy bass, positive energy",
}
VARIATIONS = (
    "medium tempo around 100 BPM",
    "slightly faster, around 120 BPM",
    "minimal arrangement with more space",
    "fuller arrangement with layered textures",
    "rhythmic and percussive",
)
LOOP_HINT = ("Instrumental background music for a short narrated video. Constant energy from start "
             "to finish, no intro build-up, no ending, no vocals, seamless loop.")

SFX_SPECS = (   # (file stem, prompt, seconds) - spec §8.2: whoosh x3, impact x2, riser x2
    ("whoosh_1", "fast cinematic whoosh transition, air swish, clean", 1.0),
    ("whoosh_2", "short deep whoosh pass-by, smooth, no tail", 0.8),
    ("whoosh_3", "quick bright swish transition sound", 1.2),
    ("impact_1", "deep cinematic impact boom hit with short tail", 1.5),
    ("impact_2", "punchy trailer hit, sub bass thump", 1.2),
    ("riser_1", "tension riser swelling upward, ends abruptly", 2.0),
    ("riser_2", "short synth sweep riser building up, ends on a peak", 2.5),
)


class LibraryAccessError(Exception):
    """401/402/403 from ElevenLabs: key invalid, missing permission, or plan lacks the API."""


@dataclass
class LibraryItem:
    path: Path
    url: str
    payload: dict
    seconds: float
    timeout: int


def _existing_stems(folder: Path) -> set:
    if not folder.is_dir():
        return set()
    return {p.stem for p in folder.iterdir() if p.is_file() and p.suffix.lower() in MUSIC_EXTENSIONS}


def plan_music_items(music_dir, moods, per_mood: int) -> tuple:
    """(todo, skipped): assets/music/<mood>/generated/<mood>_NN.mp3 for NN in 1..per_mood."""
    todo, skipped = [], []
    for mood in moods:
        folder = Path(music_dir) / mood / GENERATED_DIR
        have = _existing_stems(folder)
        for n in range(1, per_mood + 1):
            stem = f"{mood}_{n:02d}"
            path = folder / f"{stem}.mp3"
            if stem in have:
                skipped.append(path)
                continue
            prompt = f"{MOOD_PROMPTS[mood]}, {VARIATIONS[(n - 1) % len(VARIATIONS)]}. {LOOP_HINT}"
            todo.append(LibraryItem(path, MUSIC_URL, {
                "prompt": prompt, "music_length_ms": TRACK_SECONDS * 1000,
                "model_id": settings.elevenlabs_music_model, "force_instrumental": True,
            }, TRACK_SECONDS, MUSIC_TIMEOUT))
    return todo, skipped


def plan_sfx_items(sfx_dir) -> tuple:
    folder = Path(sfx_dir) / GENERATED_DIR
    have = _existing_stems(folder)
    todo, skipped = [], []
    for stem, text, seconds in SFX_SPECS:
        path = folder / f"{stem}.mp3"
        if stem in have:
            skipped.append(path)
            continue
        todo.append(LibraryItem(path, SFX_URL, {
            "text": text, "duration_seconds": seconds, "prompt_influence": 0.5,
            "loop": False, "model_id": SFX_MODEL,
        }, seconds, SFX_TIMEOUT))
    return todo, skipped


def estimate_cost(items) -> float:
    total = 0.0
    for it in items:
        rate = (settings.cost_elevenlabs_music_per_minute if it.url == MUSIC_URL
                else settings.cost_elevenlabs_sfx_per_minute)
        total += it.seconds / 60.0 * rate
    return round(total, 2)


def _detail(resp) -> str:
    """Human-readable error text from an ElevenLabs error body (never contains the request key)."""
    try:
        d = resp.json().get("detail")
    except Exception:  # noqa: BLE001
        d = None
    if isinstance(d, dict):
        d = d.get("message") or d.get("status") or str(d)
    elif isinstance(d, list):
        d = "; ".join(str(x.get("msg", x)) if isinstance(x, dict) else str(x) for x in d)
    text = str(d) if d else (getattr(resp, "text", "") or "")
    return text.strip()[:300]


def _looks_like_audio(resp) -> bool:
    """True if the 200 body is audio: audio/* Content-Type, or an MP3 (ID3 tag / MPEG frame sync)."""
    ctype = ""
    try:
        ctype = str((getattr(resp, "headers", None) or {}).get("Content-Type", "")).lower()
    except Exception:  # noqa: BLE001
        pass
    if ctype.startswith("audio/"):
        return True
    b = resp.content[:2]
    return resp.content[:3] == b"ID3" or (len(b) == 2 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0)


def fetch_item(item: LibraryItem, api_key: str, *, post: Optional[Callable] = None,
               sleep: Optional[Callable] = None) -> None:
    """Download one item to item.path via a .part file. Raises LibraryAccessError on 401/402/403,
    RuntimeError on any other failure after MAX_ATTEMPTS (429/5xx/network are retried)."""
    post = post or requests.post          # resolved per call so patched requests.post is honoured
    sleep = sleep or time.sleep
    headers = {"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    last = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = post(item.url, params={"output_format": OUTPUT_FORMAT}, json=item.payload,
                        headers=headers, timeout=item.timeout)
        except requests.RequestException as e:
            last = f"network error: {type(e).__name__}"
        else:
            if resp.status_code == 200 and resp.content and not _looks_like_audio(resp):
                last = f"HTTP 200 but the body is not audio: {_detail(resp) or 'unexpected content'}"
                break                       # a retry would just be billed again
            if resp.status_code == 200 and resp.content:
                item.path.parent.mkdir(parents=True, exist_ok=True)
                part = item.path.with_name(item.path.name + ".part")
                part.write_bytes(resp.content)
                os.replace(part, item.path)
                return
            if resp.status_code in (401, 402, 403):
                raise LibraryAccessError(
                    f"ElevenLabs refused the request (HTTP {resp.status_code}): {_detail(resp)}. "
                    "Check that ELEVENLABS_API_KEY is valid, that the key has the music / sound-effects "
                    "permission, and that your ElevenLabs plan includes this API (Music needs a paid plan).")
            last = f"HTTP {resp.status_code}: {_detail(resp)}"
            if resp.status_code != 429 and resp.status_code < 500:
                break                       # 400/422 (e.g. a rejected prompt): retrying will not help
        if attempt < MAX_ATTEMPTS:
            sleep(5 * attempt)
    raise RuntimeError(last or "empty response")


def run_library_build(kind: str, todo: list, skipped: list, *, yes: bool = False,
                      input_fn: Callable = input, post: Optional[Callable] = None,
                      sleep: Optional[Callable] = None, out: Callable = print) -> int:
    """estimate -> confirm -> fetch. 0 ok / nothing to do, 1 declined or failures, 2 no key / refused."""
    for p in skipped:
        out(f"  skip (exists): {p.as_posix()}")
    if not todo:
        out(f"{kind}: nothing to generate ({len(skipped)} file(s) already present).")
        return 0
    if not settings.elevenlabs_api_key:
        out("ELEVENLABS_API_KEY is not set in .env; cannot build the library.")
        return 2
    seconds = sum(it.seconds for it in todo)
    out(f"{kind}: {len(todo)} file(s), ~{seconds / 60:.1f} min of audio, estimated ${estimate_cost(todo):.2f} "
        "(ElevenLabs API list price; subscription plans bill credits instead).")
    if not yes:
        try:
            answer = input_fn("Proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in ("y", "yes"):
            out("Cancelled; nothing generated.")
            return 1
    failed = 0
    for i, item in enumerate(todo, 1):
        try:
            fetch_item(item, settings.elevenlabs_api_key, post=post, sleep=sleep)
            out(f"  [{i}/{len(todo)}] wrote {item.path.as_posix()}")
        except LibraryAccessError as e:
            out(str(e))
            return 2
        except Exception as e:  # noqa: BLE001 - one bad prompt must not stop the batch
            failed += 1
            out(f"  [{i}/{len(todo)}] FAILED {item.path.name}: {e}")
    out(f"{kind}: {len(todo) - failed} generated, {failed} failed, {len(skipped)} skipped.")
    return 1 if failed else 0


def build_music_library(*, per_mood: int = 5, moods: Optional[list] = None, **kw) -> int:
    todo, skipped = plan_music_items(settings.music_dir, moods or list(MOODS), per_mood)
    return run_library_build("Music library", todo, skipped, **kw)


def build_sfx_library(**kw) -> int:
    todo, skipped = plan_sfx_items(settings.sfx_dir)
    return run_library_build("SFX library", todo, skipped, **kw)
