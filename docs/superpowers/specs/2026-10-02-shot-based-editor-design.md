# Shot-Based Editor — Design Spec

**Date:** 2026-10-02
**Status:** Approved in conversation (parts 1–5); spec self-reviewed at the user's request
**Sub-project:** 1 of 3 in the "top-of-the-line short-form" effort
(2 = script upgrades, 3 = quality tiers + new models + cost cap)

## 1. Goal

Make every FVFactory video look and sound like a professionally edited Short using the
models we already pay for. Success means a default run produces:

- Real motion footage in every shot, cut on phrase boundaries at the selected pacing.
- Pictures that change when the narration's subject changes (timed from speech, not word counts).
- Readable, correctly timed captions from frame one, inside the cross-platform safe zone.
- Music and sound effects on every video, with ducking under the voice.
- −14 LUFS / −1 dBTP audio and an upload-grade H.264 encode at 30 fps.
- No silent quality downgrades: every fallback is recorded in a run report.

## 2. Background (verified in code, 2026-10-02)

| Area | Today | File |
|---|---|---|
| Cuts | `plan_cuts` output is computed but `_render_scene` never reads it; one shot per 4–8 s scene | `app/cinematic.py:72-98, 202` |
| Scene timing | Word-count proportional split, drifts from speech | `app/cinematic.py:194` |
| Motion clips | Speed-scaled to fill the scene (0.75×–1.5×), frozen last frame if short | `app/cinematic.py:211-231` |
| Transitions | 0.6 s blend between two frozen frames at every scene change | `app/cinematic.py:355-391` |
| Hook | 4 s centre title card, captions suppressed for 4 s | `app/cinematic.py:136-156` |
| Captions | Even split inside 3-word chunks; y = 1570 (inside app UI); Whisper `base`; one ImageClip per word | `app/video_editor.py:109, 473-520` |
| Fonts | System font names; on Linux every style falls back to DejaVu Sans Bold | `app/subtitle_styles.py:92` |
| Music | `assets/music/<mood>/` folders are empty; music silently skipped; flat 10 % volume; hard-splice loop | `app/video_editor.py:198` |
| SFX | `assets/sfx/` empty; cinematic path never calls `SFXMixer` | `app/sfx.py` |
| Encode | 24 fps, libx264 preset medium, defaults otherwise; no loudness normalization | `app/cinematic.py:182-189` |
| Fallback | Any renderer exception silently falls back to classic Ken Burns editor | `app/video_editor.py:685` |
| Assets | Temp assets (paid clips included) deleted after every run, even on failure | `main.py:440-452` |
| Concurrency | Narration always written to `assets/temp/audio.mp3` | `app/asset_manager.py:89` |
| Crash | Mismatched `motion_prompts`/`image_prompts` counts raise after images are paid for | `app/motion_gen.py:146` |
| Tests | Suite fails at collection: `.env` has legacy keys and `Settings` forbids extras | `app/config.py:5` |
| Cost tracker | Logs Minimax clips at $0.10; fal list price is ≈ $0.50 per clip | `app/config.py:115` |

User decisions recorded during design:

- **Motion only.** Every shot is AI motion footage. Stills appear only when clip generation fails,
  and are reported as defects.
- **Selectable over hardcoded.** Pacing, music source and strictness are per-video options.
- Commit `52b1360` slowed cutting down because cuts landed on loudness peaks 0.8 s apart with
  random tight crops and zoom jitter. This design cuts on phrase boundaries with a 1.8 s floor
  and removes the audio zoom punch.

## 3. Scope

**In:** pipeline reorder, speech alignment, shot planner, new renderer, captions + bundled fonts,
music/SFX libraries + mixing, voice polish, loudness + encode, per-job sources + `--rerender`,
run report, option plumbing (web form, CLI, scheduler, settings), housekeeping fixes listed in §11.

**Out (later sub-projects):**
- Script structure: hook/open loop/re-hook/loop ending, tone, WPM gate, dedicated
  `hook_headline` field (sub-project 2).
- Quality tiers, new video/image/voice models (Kling v3, MiniMax H3, FLUX.2, Nano Banana 2,
  Eleven v4), pre-spend cost estimate and cap, tier selector (sub-project 3).
- **Open item, not approved:** a ≈ $1.80 paid side-by-side model test (Hailuo 2.3 Pro,
  H3 Max Turbo, Kling v3 Standard, Kling v3 Pro). Do not run without explicit approval.

## 4. Pipeline order

Today: script → TTS → images → motion clips → edit.

New:

```
script ─► TTS ─► align (Whisper words ↔ script tokens) ─► shot plan ─► motion clips ─► render ─► encode
          └────────────► images (in parallel with align) ──────────────┘
```

Clips must come after the shot plan because each clip's requested length is its scene's spoken
length. Images do not depend on timing and run concurrently with alignment.

All intermediates for a run are written under the job folder (§9), never a shared temp path.

## 5. Speech alignment — `app/cin/align.py`

Input: narration audio, `scene_texts` (list of strings), full narration text.
Output: `Alignment` with per-script-token timings and per-scene `[t0, t1]`.

Algorithm:

1. Transcribe with Whisper (`word_timestamps=True`). Model is `settings.whisper_model`,
   default `"small"` (currently hard-coded `"base"`). Configurable because the VPS CPU/RAM
   budget is unverified; `base` remains a valid value.
2. Tokenize both sides and normalize: lowercase, strip punctuation, expand integers, years and
   percentages to words with a small built-in normalizer (no new dependency), split hyphenated words.
3. Align the script token sequence to the Whisper token sequence with `difflib.SequenceMatcher`.
   Matched script tokens take the matched word's `start`/`end`. Unmatched script tokens are
   linearly interpolated between their nearest matched neighbours.
4. Each scene starts at the `start` of its first token; it ends where the next scene starts
   (last scene ends at audio duration).
5. **Fallback:** if fewer than 70 % of script tokens match, or `scene_texts` is missing or does not
   join back to the narration, use the current word-count split and record
   `alignment_fallback` in the run report.

Caption text uses the **script's** tokens (correct spelling of names), with timings from step 3.

## 6. Shot plan — `app/cin/shot_plan.py`

Pure functions: `build_shot_plan(alignment, pacing, clip_specs) -> ShotPlan`. No I/O, no rendering.

### 6.1 Pacing presets

| `pacing` | Target shot length | Min | Max |
|---|---|---|---|
| `calm` | 4.2 s | 3.5 s | 5.0 s |
| `standard` (default) | 2.8 s | 2.2 s | 3.5 s |
| `fast` | 2.1 s | 1.8 s | 2.5 s |

### 6.2 Cut placement

Scene boundaries are fixed by the alignment. Within a scene, candidate cut points are word gaps.
Each candidate scores `gap_seconds + 0.5 if sentence end + 0.25 if comma`. A small dynamic
program picks the cut set that keeps every shot within `[min, max]` and minimizes
`Σ (shot_len − target)² − Σ score`. A scene shorter than `min` is one shot. If a longer segment has
no valid set (word gaps can make strict bounds infeasible), retry with bounds ×(0.8, 1.25), then
(0, ×1.5), before falling back to one shot.

### 6.3 Framing

Consecutive shots from the same clip alternate framing between `1.0` (full frame) and `1.18`
(punch-in, centred, slight upper-third bias). Two adjacent shots never share the same framing
from the same clip (no jump cuts).

### 6.4 Clip sourcing

- Each scene requests one clip of length `scene_len + 0.5 s` handle, snapped up to the motion
  model's supported durations (table in `app/motion_gen.py`, e.g. Minimax video-01: fixed ≈ 6 s;
  Kling v1/1.5: 5 or 10 s).
- If `scene_len + 0.5` exceeds the model's maximum, split the scene into two clip segments at the
  best cut point nearest the middle. The second segment's clip uses the **last frame of the first
  clip** as its start image for continuous motion; if the first clip failed, it uses the scene image.
- Shot `k` in a scene plays clip time `[shot.t0 − segment.t0, shot.t1 − segment.t0]`.
- If footage is short by ≤ 15 %, apply a uniform speed factor ≥ 0.87 to that segment. Beyond that,
  the uncovered tail becomes a still shot (reported).
- Generation runs in parallel with `settings.motion_concurrency` (default 4); chained second
  segments wait for their first segment only.

### 6.5 Transitions

Default is a hard cut. Up to 3 scene boundaries get a styled transition (flash, zoom-through,
whip pan from `app/cin/transitions.py`), 0.3 s, computed from **moving** frames of both shots
(overlap of 0.15 s each side). Boundaries are chosen by the longest preceding pause. Sub-project 2
will replace this heuristic with script beat markers.
*(Amended 2026-10-03: when the script supplies scene_roles, rehook/payoff/loop scenes get the transitions instead; see 2026-10-03-script-upgrades-design.md §8.)*

### 6.6 `shot_plan.json` contract

```json
{
  "version": 1,
  "duration": 40.12,
  "fps": 30,
  "pacing": "standard",
  "alignment": {"method": "whisper+script", "fallback": false, "match_ratio": 0.94},
  "scenes": [
    {"index": 0, "t0": 0.0, "t1": 2.21, "text": "This watch costs more than a car.",
     "segments": [{"t0": 0.0, "t1": 2.21, "clip": "sources/clips/scene00_a.mp4",
                    "requested_len": 6.0, "start_image": "sources/images/scene00.png"}]}
  ],
  "shots": [
    {"index": 0, "scene": 0, "t0": 0.0, "t1": 1.10,
     "source": {"type": "clip", "path": "sources/clips/scene00_a.mp4",
                "clip_t0": 0.0, "clip_t1": 1.10, "speed": 1.0},
     "framing": 1.0, "transition_in": "cut"}
  ],
  "captions": [
    {"t0": 0.0, "t1": 0.62, "words": [{"text": "THIS", "t0": 0.0, "t1": 0.21}]}
  ],
  "sfx": [{"t": 0.0, "kind": "impact", "file": "assets/sfx/generated/impact_1.mp3", "gain_db": -6}],
  "music": {"file": "assets/music/epic/generated/epic_03.mp3", "duck_windows": [[0.0, 2.21]]},
  "hook_headline": {"text": "...", "t0": 0.0, "t1": 2.5}
}
```

A still-sourced shot uses `{"type": "still", "path": ..., "move": "push_in"}`.
Consumers: renderer reads `shots`, `hook_headline`; captions (§7) read `captions`;
audio (§8) reads `sfx`, `music`, and word timings for ducking.

## 7. Captions

- **Fonts:** bundle OFL fonts in `assets/fonts/` (Montserrat ExtraBold, Anton, Bebas Neue).
  Presets reference font files, not system names. A missing font logs a warning and is recorded
  in the run report.
- **Grouping:** 1–3 words per group from aligned script tokens; break at punctuation and gaps
  > 0.25 s; never split a number or capitalized name sequence across groups.
- **Highlight:** active word in the preset's active colour, scaled 1.0 → preset `active_scale`
  over 80 ms.
- **Placement:** `bottom` positions centre the caption block at y ≈ 1325 (range 1250–1400);
  block never extends below y = 1410 or right of x = 990. `center` keeps its current position.
- **From frame one:** no suppression window.
- **Hook headline:** top band y ≈ 250–450 for `[0, 2.5 s]`. Text is the hook's first sentence
  if ≤ 8 words, otherwise omitted (sub-project 2 adds a dedicated field).
  *(Amended 2026-10-03: the script's hook_headline field (≤ 6 words) is used first; see 2026-10-03-script-upgrades-design.md §8.)*
- **Rendering:** each group is rasterized once per highlight state and alpha-composited inside
  the frame function, replacing one `ImageClip` per word.
- Existing presets (`bold_impact`, `clean_minimal`, `neon_glow`, `fire`) keep their colours
  and remain selectable.

## 8. Audio

### 8.1 Music library

- Layout: `assets/music/<mood>/*.mp3|wav` (user tracks) and `assets/music/<mood>/generated/*`.
  Moods: chill, cinematic, dark, epic, upbeat (as resolved by `resolve_music_mood`).
- `music_source`: `mine` | `generated` | `any` (default) | `none`.
- Selection: least-recently-used track in the mood, tracked in `data/music_usage.json`.
- Empty pool for a non-`none` source: warning + `music_missing` in the run report.
- `python main.py --build-music-library [--per-mood 5] [--moods epic,dark]` generates instrumental
  ≈ 60 s loop-friendly tracks via ElevenLabs Music (endpoint and parameters to be verified against
  current API docs during planning). Estimated ≈ $4 for 25 tracks; prints the estimate and asks
  for confirmation unless `--yes`.

### 8.2 Sound effects library

- `python main.py --build-sfx-library` generates whoosh ×3, impact ×2, riser ×2 via ElevenLabs
  `POST /v1/sound-generation` into `assets/sfx/generated/`. User files in `assets/sfx/` are also used.
- Placement from the shot plan: whoosh 0.15 s before each scene boundary (not intra-scene cuts),
  impact at 0.0 s, riser ending at each styled transition. Variants rotate.
- Honour `enable_sfx`.

### 8.3 Mix

- **Voice polish:** ffmpeg `highpass=f=80,acompressor=threshold=-18dB:ratio=3:attack=10:release=150`.
- **Ducking:** music gain envelope from word timings: −22 dB under speech, −14 dB in gaps
  ≥ 0.5 s and over the final 1.0 s; 150 ms attack, 300 ms release; fade in 0.3 s, fade out 1.5 s.
- **Looping:** tracks shorter than the video loop with a 1.0 s equal-power crossfade.
- Mix voice + music + SFX to a 48 kHz WAV in the job folder.

## 9. Encode, sources, re-render

### 9.1 Encode

1. Video-only render via MoviePy at 30 fps with
   `-c:v libx264 -preset slow -crf 18 -profile:v high -pix_fmt yuv420p -colorspace bt709 -color_primaries bt709 -color_trc bt709`.
2. Two-pass `loudnorm=I=-14:TP=-1:LRA=11` on the mixed WAV.
3. Mux with `-c:v copy -c:a aac -b:a 192k -ar 48000 -movflags +faststart`, plus the
   `h264_metadata` bitstream filter to write BT.709 primaries/transfer (MoviePy's writer leaves
   them `unknown`; verified with ffprobe).
4. Port `probe_video`, `get_audio_loudness` and `is_platform_safe` from `src/encoding.py` into
   `app/encoding.py`; record measured loudness and the safety check in the run report.

### 9.2 Job folder

```
output/<job>/
  final.mp4
  run_report.json
  sources/
    narration.mp3   words.json   alignment.json   shot_plan.json
    images/scene00.png …        clips/scene00_a.mp4 …
    mix.wav
```

`cleanup_temp()` no longer deletes paid assets. A prune step at startup removes `sources/` older
than `settings.keep_sources_days` (default 14). Expected size ≈ 30–40 MB per video.

### 9.3 `--rerender <job_dir>`

Rebuilds `final.mp4` from `sources/` with zero API calls. Optional overrides:
`--pacing`, `--subtitle-style`, `--music-source`, `--no-sfx`, `--no-music`, `--color-grade`.
Scene boundaries and clips are fixed, so `--pacing` changes cuts **within** scenes only. Caption
style, music, SFX and colour grade change fully. The previous output is kept as `final.prev.mp4`.

## 10. Reliability and reporting

- Renderer exceptions fail the run with the error (sources kept; fix and `--rerender`); they never
  fall back to the classic editor. The classic editor is used only with `--classic`, for persona runs
  (talking-head hybrid), or when the `cinematic_enabled` setting is off (Settings page "Shot editor"
  toggle). *(Amended 2026-10-03, Phase D, controller ruling.)*
- Clip failure: retry once → fallback model (`settings.fal_video_fallback_model`) → still with a
  slow push-in. `strict=True` fails the run instead of shipping a still.
- `--no-motion` and `--mock` remain as explicit opt-outs; they produce still-sourced shots. `--mock`
  skips image and clip spend but still calls the LLM and TTS (≈ $0.01); `validate_config` must not
  require `FAL_API_KEY` in mock mode. The fully offline check is the patched pytest end-to-end test.
- `motion_prompts`/`image_prompts`/`scene_texts` length mismatch: normalize after the LLM call
  (merge extra `scene_texts` into the last scene so the narration still joins back; truncate extra
  prompts; pad `motion_prompts` with a generic camera move) and log it.
- `run_report.json`: `warnings[]` (each `{code, message, detail}`; codes include
  `still_fallback`, `alignment_fallback`, `font_fallback`, `music_missing`, `sfx_missing`,
  `speed_adjusted`, `prompt_count_normalized`), `loudness` (I, TP, LRA), `platform_safe`,
  `cost` (estimated, actual by item), `durations` per stage.
- `/api/generate` returns the report's `warnings` with the result.

## 11. Options and housekeeping

New per-video options, plumbed like `subtitle_style` (web generate request model + form,
CLI flag, scheduler slot config, `Settings` default):

| Option | Values | Default |
|---|---|---|
| `pacing` | `calm`, `standard`, `fast` | `standard` |
| `music_source` | `mine`, `generated`, `any`, `none` | `any` |
| `strict` | bool | `false` |

New settings: `whisper_model` (`"small"`), `motion_concurrency` (4), `keep_sources_days` (14),
`fal_video_fallback_model` (`""` = none).

Housekeeping:
- `Settings.model_config`: `extra="ignore"` so legacy `.env` keys do not break startup or tests.
- Cost tracker: per-model clip pricing (per clip or per second) replacing the flat
  `cost_minimax_video = 0.10`; Minimax video-01 ≈ $0.50 per clip (fal list price; verify against billing).
- `generator_worker.py` stops hard-coding `enable_sfx=False`.
- `CLAUDE.md`: fix the stale `app/dashboard.py` reference and document the new flags.

## 12. Testing

- **Unit (no media):** normalizer and alignment on saved `words.json` fixtures (including a
  misheard name and a number); fallback threshold; shot planner for each pacing (bounds respected,
  no same-framing adjacency, scene longer than model max splits); caption grouping rules;
  LRU music selection; SFX placement; prompt-count normalization.
- **Render (no APIs):** 8 s fixture with synthetic clips (`ffmpeg testsrc`), a short WAV and saved
  word timings. Assert 1080×1920, 30 fps, duration ±0.05 s, loudness −14 ±1 LU, true peak ≤ −1 dBTP,
  `yuv420p`, faststart atom first, caption pixels only inside the safe zone.
- **Re-render:** run the render fixture, then `--rerender --pacing fast`; assert more shots,
  identical scene boundaries, zero network calls (patched clients raise).
- **End-to-end:** one real run with current models after the user approves the spend (≈ $4.50).

## 13. Delivery phases

Each phase ends with a playable video:

- **A — Picture + encode + sources:** pipeline reorder, alignment, shot planner, clip sourcing,
  renderer, transitions, encode, job folder, `--rerender`. (Existing captions/music paths
  temporarily adapted.)
- **B — Captions + fonts.**
- **C — Music/SFX libraries, ducking, voice polish, loudnorm.**
- **D — Options plumbing (web, CLI, scheduler), run report surfaced in API, housekeeping.**

## 14. Risks

- **Render time:** per-frame crop/resize at 30 fps in Python. Prototype: an 8 s full-size render with
  captions and grade took ≈ 27–86 s on the dev PC, so a 40 s video is roughly 3–6 minutes.
  Mitigation: precompute framing crops per shot, use `cv2.resize` if available; measure on the VPS.
- **Whisper `small` on the VPS:** slower and ≈ 2 GB RAM. Mitigation: `whisper_model` setting.
- **ElevenLabs Music licensing:** commercial use depends on the plan tier; user to confirm their plan
  before building the generated library.
- **Clip chaining latency:** second segments wait on their first; bounded by one extra clip time.
- **Clip cost with fixed-length models:** Minimax video-01 only produces ≈ 6 s clips, so scenes
  longer than ≈ 5.5 s need two clips. With today's average scene of ≈ 4.4 s this adds an
  estimated 1–3 clips per video (≈ $0.50–1.50). The run report shows actual clip count;
  sub-project 3's variable-length models (Kling 3–15 s) remove most of this overhead.

## 15. Implementation notes (deviations made during implementation)

- Loudnorm target true peak is -1.5 dBTP so the measured post-AAC peak stays <= -1.0 dBTP.
- Whisper audio is decoded via ffmpeg; MoviePy's 16 kHz `to_soundarray` is broken.
- The `center` caption preset is centred on the frame.
- Montserrat is a variable font; weight is applied through Pillow.
- The hook headline follows `enable_subtitles`.
- A corrupt cost log is copied to `cost_log.corrupt.json` and never overwritten.
- `--rerender` re-derives `alignment_fallback` from `alignment.json`.
