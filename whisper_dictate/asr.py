"""ASR backend: Whisper (MLX)."""
from __future__ import annotations

import logging
import os
import time

import numpy as np
import soundfile as sf

from whisper_dictate.config import (
    SAMPLE_RATE,
    WHISPER_MODEL,
    _secure_tmpfile,
)

logger = logging.getLogger("whisper_dictate.asr")


def warmup_model() -> None:
    """Run a dummy transcription to warm up caches."""
    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    tmp = _secure_tmpfile()
    sf.write(tmp, silence, SAMPLE_RATE)
    try:
        import mlx_whisper
        mlx_whisper.transcribe(tmp, path_or_hf_repo=WHISPER_MODEL)
    except Exception:
        logger.warning("Model warmup failed", exc_info=True)
    os.unlink(tmp)


def transcribe(
    audio_path: str,
    keywords: str = "",
    use_prompt: bool = True,
) -> tuple[str, float]:
    """Run ASR on an audio file.

    Returns (raw_text, asr_seconds).
    """
    t_asr = time.monotonic()

    import mlx_whisper
    kwargs = {
        "path_or_hf_repo": WHISPER_MODEL,
        "condition_on_previous_text": False,  # faster: no cross-segment context
        "word_timestamps": False,             # faster: skip alignment pass
    }
    if use_prompt and keywords:
        kwargs["initial_prompt"] = keywords
    result = mlx_whisper.transcribe(audio_path, **kwargs)
    raw_text = result.get("text", "").strip()

    asr_sec = time.monotonic() - t_asr
    return raw_text, asr_sec
