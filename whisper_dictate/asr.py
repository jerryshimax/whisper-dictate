"""ASR backend: Whisper (MLX) — single model, simple and reliable."""
from __future__ import annotations

import logging
import os
import time

# Models are cached locally — never phone home to HuggingFace on startup.
# Without this, a proxy/network blip crashes the app.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import numpy as np
import soundfile as sf

from whisper_dictate.config import SAMPLE_RATE, WHISPER_MODEL, _secure_tmpfile

logger = logging.getLogger("whisper_dictate.asr")


def warmup_model() -> None:
    """Run a dummy transcription to warm up the model cache."""
    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    tmp = _secure_tmpfile()
    sf.write(tmp, silence, SAMPLE_RATE)
    try:
        import mlx_whisper
        mlx_whisper.transcribe(tmp, path_or_hf_repo=WHISPER_MODEL)
        logger.info("Warmed up model: %s", WHISPER_MODEL)
    except Exception:
        logger.warning("Model warmup failed", exc_info=True)
    os.unlink(tmp)


def transcribe(
    audio_path: str,
    keywords: str = "",
    use_prompt: bool = True,
    duration: float = 0.0,
) -> tuple[str, float]:
    """Run ASR on an audio file. Returns (raw_text, asr_seconds)."""
    t_asr = time.monotonic()

    import mlx_whisper
    kwargs = {
        "path_or_hf_repo": WHISPER_MODEL,
        "condition_on_previous_text": True,
        "word_timestamps": False,
    }
    if use_prompt and keywords:
        kwargs["initial_prompt"] = keywords
    result = mlx_whisper.transcribe(audio_path, **kwargs)
    raw_text = result.get("text", "").strip()

    asr_sec = time.monotonic() - t_asr
    logger.info("ASR [%s] %.2fs audio -> %.2fs inference (RTF=%.2f)",
                WHISPER_MODEL.split("/")[-1], duration, asr_sec,
                asr_sec / max(duration, 0.1))
    return raw_text, asr_sec


def transcribe_array(
    audio: np.ndarray,
    keywords: str = "",
    use_prompt: bool = True,
) -> tuple[str, float]:
    """Transcribe a numpy audio array. Returns (raw_text, asr_seconds)."""
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
