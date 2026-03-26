"""Audio device listing, input resolution, and silence trimming."""
from __future__ import annotations

import logging

import numpy as np
import sounddevice as sd

from whisper_dictate.config import (
    SAMPLE_RATE,
    TRAILING_SILENCE_DB_THRESHOLD,
    TRAILING_SILENCE_HOLD_SEC,
    TRAILING_SILENCE_WINDOW_SEC,
)

logger = logging.getLogger("whisper_dictate.audio")


def _trim_trailing_silence(audio: np.ndarray) -> tuple[np.ndarray, float]:
    """Trim trailing silence from audio array. Returns (trimmed_audio, seconds_trimmed)."""
    if audio.size == 0:
        return audio, 0.0

    frame_size = max(1, int(SAMPLE_RATE * TRAILING_SILENCE_WINDOW_SEC))
    min_tail_run = int(SAMPLE_RATE * TRAILING_SILENCE_HOLD_SEC)
    tail_run = 0
    trim_samples = 0
    total = len(audio)

    for end in range(total, 0, -frame_size):
        start = max(0, end - frame_size)
        frame = audio[start:end]
        rms = float(np.sqrt(np.mean(np.square(frame))))
        db = 20.0 * np.log10(max(rms, 1e-7))
        if db <= TRAILING_SILENCE_DB_THRESHOLD:
            tail_run += len(frame)
            if tail_run >= min_tail_run:
                trim_samples = tail_run
                continue
        break

    if trim_samples <= 0:
        return audio, 0.0

    keep_samples = max(frame_size, total - trim_samples)
    trimmed = audio[:keep_samples]
    return trimmed, (total - len(trimmed)) / SAMPLE_RATE


def _get_input_devices() -> list[dict]:
    """Return list of input devices as [{'index': int, 'name': str}, ...]."""
    devices = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            devices.append({"index": i, "name": d["name"]})
    return devices


def _resolve_input_device() -> int | None:
    """Look up preferred input device from config. Returns device index or None."""
    from whisper_dictate.config import load_user_config

    cfg = load_user_config()
    preferred = cfg.get("input_device")
    if not preferred:
        return None
    for d in _get_input_devices():
        if d["name"] == preferred:
            logger.info("Using preferred input: %s (index %d)", d["name"], d["index"])
            return d["index"]
    logger.warning("Preferred device '%s' not found, using system default", preferred)
    return None
