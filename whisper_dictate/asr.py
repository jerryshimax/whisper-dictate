"""ASR backend: Whisper (MLX) with adaptive model selection and streaming support."""
from __future__ import annotations

import logging
import os
import time

import numpy as np
import soundfile as sf

from whisper_dictate.config import (
    FAST_MODEL_DURATION_THRESHOLD_SEC,
    SAMPLE_RATE,
    WHISPER_MODEL,
    WHISPER_MODEL_FAST,
    _secure_tmpfile,
)

logger = logging.getLogger("whisper_dictate.asr")

# Track which models are warmed up
_warmed: set[str] = set()


def warmup_model() -> None:
    """Run a dummy transcription to warm up the primary model cache."""
    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    tmp = _secure_tmpfile()
    sf.write(tmp, silence, SAMPLE_RATE)
    try:
        import mlx_whisper
        mlx_whisper.transcribe(tmp, path_or_hf_repo=WHISPER_MODEL)
        _warmed.add(WHISPER_MODEL)
        logger.info("Warmed up primary model: %s", WHISPER_MODEL)
    except Exception:
        logger.warning("Model warmup failed", exc_info=True)
    os.unlink(tmp)


def warmup_fast_model() -> None:
    """Warm up the fast model in background (called after primary warmup)."""
    if WHISPER_MODEL_FAST == WHISPER_MODEL:
        return
    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    tmp = _secure_tmpfile()
    sf.write(tmp, silence, SAMPLE_RATE)
    try:
        import mlx_whisper
        mlx_whisper.transcribe(tmp, path_or_hf_repo=WHISPER_MODEL_FAST)
        _warmed.add(WHISPER_MODEL_FAST)
        logger.info("Warmed up fast model: %s", WHISPER_MODEL_FAST)
    except Exception:
        logger.warning("Fast model warmup failed (non-fatal)", exc_info=True)
    os.unlink(tmp)


def _select_model(duration: float) -> str:
    """Pick model based on audio duration.

    Always use the primary (multilingual) model — distil-whisper is
    English-optimised and degrades Chinese recognition.
    """
    return WHISPER_MODEL


def transcribe(
    audio_path: str,
    keywords: str = "",
    use_prompt: bool = True,
    duration: float = 0.0,
) -> tuple[str, float]:
    """Run ASR on an audio file.

    Returns (raw_text, asr_seconds).
    """
    model = _select_model(duration) if duration > 0 else WHISPER_MODEL
    t_asr = time.monotonic()

    import mlx_whisper
    kwargs = {
        "path_or_hf_repo": model,
        "condition_on_previous_text": False,  # faster: no cross-segment context
        "word_timestamps": False,             # faster: skip alignment pass
    }
    if use_prompt and keywords:
        kwargs["initial_prompt"] = keywords
    result = mlx_whisper.transcribe(audio_path, **kwargs)
    raw_text = result.get("text", "").strip()

    asr_sec = time.monotonic() - t_asr
    logger.info("ASR [%s] %.2fs audio -> %.2fs inference (RTF=%.2f)",
                model.split("/")[-1], duration, asr_sec,
                asr_sec / max(duration, 0.1))
    return raw_text, asr_sec


def transcribe_array(
    audio: np.ndarray,
    keywords: str = "",
    use_prompt: bool = True,
) -> tuple[str, float]:
    """Transcribe a numpy audio array directly (avoids extra file write in hot path).

    Returns (raw_text, asr_seconds).
    """
    duration = len(audio) / SAMPLE_RATE
    tmp = _secure_tmpfile()
    sf.write(tmp, audio, SAMPLE_RATE)
    try:
        text, asr_sec = transcribe(
            audio_path=tmp,
            keywords=keywords,
            use_prompt=use_prompt,
            duration=duration,
        )
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return text, asr_sec
