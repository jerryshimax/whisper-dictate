# WhisperDictate

macOS voice dictation app — FN hold-to-talk, local Whisper ASR, LLM post-processing.

## Architecture
Python + PyObjC native macOS app. `app.py` is the AppDelegate orchestrator managing a floating NSPanel indicator. `event_tap.py` captures FN key via CGEventTap. `audio.py` records via sounddevice. `asr.py` runs Whisper MLX locally. `postprocessor.py` and `llm_polish.py` handle text cleanup. `clipboard.py` pastes results. Packaged as `.app` via `setup_whisper_app.py`.

## Review Focus
- PyObjC thread safety: ASR and audio run on background threads but UI updates must be on main thread — verify all `performSelectorOnMainThread` or `AppHelper.callAfter` usage
- Audio buffer management: `sounddevice` callback writes to numpy arrays — check for buffer overflow on long recordings (RECORDING_TIMEOUT_SEC)
- MLX model memory: Whisper model stays resident — verify `MEMORY_SOFT_LIMIT_MB` enforcement and `MEMORY_MAINTENANCE_INTERVAL_SEC` cleanup
- CGEventTap permissions: tap fails silently without Accessibility permissions — check error handling path
- FN key detection: `FN_MIN_HOLD_SEC` vs `TAP_MAX_HOLD_SEC` — verify no dead zone between tap and hold
- `_trim_trailing_silence` edge case: all-silence audio should not crash ASR

## Known Risks
- CGEventTap can be killed by macOS if the app becomes unresponsive (main thread blocked)
- Instance lock mechanism — check for stale lock file after crash
- `_secure_tmpfile` cleanup on abnormal exit

## Test Commands
```bash
cd ~/Ship/dictation && python -m pytest tests/ 2>/dev/null || echo "No test suite"
```
