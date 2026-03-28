"""LLM-based punctuation and capitalization polisher using local MLX models."""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger("whisper_dictate.llm_polish")

# Small, fast model for punctuation fixing
LLM_MODEL = "mlx-community/Qwen2.5-0.5B-Instruct-4bit"
LLM_TIMEOUT_SEC = 3.0
LLM_MAX_TOKENS = 512

_model_cache: dict = {"model": None, "tokenizer": None, "loaded": False, "loading": False}
_lock = threading.Lock()

SYSTEM_PROMPT = (
    "You are a punctuation fixer for speech-to-text output. "
    "Fix ONLY: punctuation, capitalization, and sentence boundaries. "
    "NEVER change, replace, correct, add, or remove any words. "
    "NEVER paraphrase or rephrase. Keep every word exactly as-is. "
    "NEVER add quotes around the output. "
    "Proper nouns to preserve exactly: Synergis, Nscale, UUL, Packsmith, Roboforce, Hankun, AFLF. "
    "Output ONLY the corrected text."
)


def warmup_llm() -> None:
    """Pre-load the LLM model in background. Call after Whisper warmup."""
    if _model_cache["loaded"] or _model_cache["loading"]:
        return
    _model_cache["loading"] = True

    def _load():
        try:
            import mlx_lm
            t0 = time.monotonic()
            model, tokenizer = mlx_lm.load(LLM_MODEL)
            _model_cache["model"] = model
            _model_cache["tokenizer"] = tokenizer
            _model_cache["loaded"] = True
            elapsed = time.monotonic() - t0
            logger.info("LLM loaded: %s (%.1fs)", LLM_MODEL, elapsed)
        except Exception:
            logger.warning("LLM warmup failed", exc_info=True)
        finally:
            _model_cache["loading"] = False

    threading.Thread(target=_load, daemon=True).start()


def polish_text(text: str) -> tuple[str, float]:
    """Fix punctuation/capitalization using local LLM.

    Returns (polished_text, llm_seconds).
    If LLM is not loaded or times out, returns original text.
    """
    if not _model_cache["loaded"]:
        return text, 0.0

    if not text or len(text) < 5:
        return text, 0.0

    t0 = time.monotonic()
    result = [text]  # default to original

    def _run():
        try:
            import mlx_lm
            model = _model_cache["model"]
            tokenizer = _model_cache["tokenizer"]

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ]

            prompt = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )

            response = mlx_lm.generate(
                model,
                tokenizer,
                prompt=prompt,
                max_tokens=LLM_MAX_TOKENS,
                verbose=False,
            )

            cleaned = response.strip().strip('"\'')
            if not cleaned or len(cleaned) < len(text) * 0.5:
                return  # LLM output too short, reject
            if len(cleaned) > len(text) * 2.0:
                return  # LLM added too much, reject
            # Verify words weren't changed: compare alphanumeric content
            import re
            orig_words = re.findall(r'[a-zA-Z]+|[\u4e00-\u9fff]', text.lower())
            new_words = re.findall(r'[a-zA-Z]+|[\u4e00-\u9fff]', cleaned.lower())
            if orig_words == new_words or len(new_words) >= len(orig_words) * 0.85:
                result[0] = cleaned
        except Exception:
            logger.debug("LLM polish failed", exc_info=True)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=LLM_TIMEOUT_SEC)

    elapsed = time.monotonic() - t0
    if thread.is_alive():
        logger.warning("LLM polish timed out (%.1fs), using raw text", elapsed)
        return text, elapsed

    return result[0], elapsed
