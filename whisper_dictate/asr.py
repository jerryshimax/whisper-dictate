"""ASR backends: Whisper (MLX) and Paraformer (FunASR)."""
from __future__ import annotations

import logging
import os
import time

import numpy as np
import soundfile as sf

from whisper_dictate.config import (
    PARAFORMER_MODEL,
    PARAFORMER_PUNC,
    PARAFORMER_VAD,
    SAMPLE_RATE,
    WHISPER_MODEL,
    _secure_tmpfile,
)

logger = logging.getLogger("whisper_dictate.asr")

_funasr_model = None  # lazy-loaded singleton


def _get_funasr_model():
    """Lazy-load and return the FunASR Paraformer model."""
    global _funasr_model
    if _funasr_model is None:
        from funasr import AutoModel
        _funasr_model = AutoModel(
            model=PARAFORMER_MODEL,
            vad_model=PARAFORMER_VAD,
            punc_model=PARAFORMER_PUNC,
        )
        logger.info("FunASR Paraformer loaded (%s)", PARAFORMER_MODEL)
    return _funasr_model


def warmup_model(backend: str = "whisper") -> None:
    """Run a dummy transcription to warm up caches."""
    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    tmp = _secure_tmpfile()
    sf.write(tmp, silence, SAMPLE_RATE)
    try:
        if backend == "paraformer":
            m = _get_funasr_model()
            m.generate(input=tmp)
        else:
            import mlx_whisper
            mlx_whisper.transcribe(tmp, path_or_hf_repo=WHISPER_MODEL)
    except Exception:
        logger.warning("Model warmup failed", exc_info=True)
    os.unlink(tmp)


def transcribe(
    audio_path: str,
    backend: str = "whisper",
    keywords: str = "",
    use_prompt: bool = True,
) -> tuple[str, float]:
    """Run ASR on an audio file.

    Returns (raw_text, asr_seconds).
    """
    t_asr = time.monotonic()

    if backend == "paraformer":
        m = _get_funasr_model()
        res = m.generate(input=audio_path)
        # FunASR returns list of dicts with 'text' key
        if res and isinstance(res, list) and len(res) > 0:
            raw_text_parts = []
            for seg in res:
                t = seg.get("text", "") if isinstance(seg, dict) else str(seg)
                if t:
                    raw_text_parts.append(t)
            raw_text = "".join(raw_text_parts).strip()
        else:
            raw_text = ""
    else:
        import mlx_whisper
        kwargs = {"path_or_hf_repo": WHISPER_MODEL}
        if use_prompt and keywords:
            kwargs["initial_prompt"] = keywords
        result = mlx_whisper.transcribe(audio_path, **kwargs)
        raw_text = result.get("text", "").strip()

    asr_sec = time.monotonic() - t_asr
    return raw_text, asr_sec
