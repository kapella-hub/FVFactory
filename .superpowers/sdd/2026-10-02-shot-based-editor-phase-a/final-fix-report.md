# Final fix wave report

RED command (all new tests written first): `.venv/Scripts/python.exe -m pytest tests/test_cin_editor.py tests/test_rerender.py tests/test_library.py tests/test_motion_gen.py -q --tb=line -p no:cacheprovider -m "not render"`
RED result: `5 failed, 24 passed` - failing: test_locked_final_swap_writes_timestamped_file_and_warns, test_platform_check_failure_is_warned, test_new_warning_codes_registered, test_failed_rerender_keeps_old_plan_and_saves_prev_report (shot_plan.json bytes differed), test_unknown_or_non_fal_model_key_fails_clip (returned a path instead of None). The "abc\n" library test already passed at RED (resolve_video's path handling rejects it), so a direct `_SAFE_ID.fullmatch` test was added; it was not RED-verified.

1. Swap: `_swap_final` in app/cin/editor.py retries 3x0.5s, then writes final.<timestamp>.mp4, report.warn final_swap_failed + logger.warning, returns the path written; loudness/platform checks run on it.
2. rerender_job copies run_report.json to run_report.prev.json first and saves shot_plan.json only after render_job succeeds.
3. .claude/memory.md updated (alignment, -1.38 dBTP, UTF-8).
4. `_SAFE_ID` uses fullmatch; unused json/os removed from api_library.py (py_compile ok).
5. platform_check_failed warning + logger.warning; both new codes in WARNING_CODES.
6. `_generate_fal`: explicit model_key not in CLIP_MODELS or with no fal endpoint -> logger.error, return None (before importing fal_client). No-key legacy path unchanged.

GREEN: same command -> `30 passed, 2 deselected` after fixing a test-assertion bug in the swap test (initially 1 failed: repr-escape comparison).
Full suite: `.venv/Scripts/python.exe -m pytest tests/ -q --tb=short -rf -p no:cacheprovider --ignore=tests/test_scheduler.py --ignore=tests/test_web_api.py` -> 12 failed, 314 passed (the 12 known: 4 uploader, 6 trends, 1 trend_scout, 1 local_image_gen).
