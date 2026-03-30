"""LLM-based text polisher using Llama 3.2-3B via MLX (Wispr Flow style)."""
from __future__ import annotations

import logging
import os
import threading
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")

logger = logging.getLogger("whisper_dictate.llm_polish")

LLM_MODEL = "mlx-community/Qwen2.5-3B-Instruct-4bit"
LLM_TIMEOUT_SEC = 8.0
LLM_MAX_TOKENS = 1024

_model_cache: dict = {"model": None, "tokenizer": None, "loaded": False, "loading": False}

SYSTEM_PROMPT = (
    "Clean up this dictated text. Output ONLY the cleaned text.\n"
    "- Add punctuation: ，。？！\n"
    "- Remove fillers: 嗯 呃 um uh 就是说 那个\n"
    "- Fix repetitions and false starts\n"
    "- NEVER translate between languages. If user said English words, keep them in English. If Chinese, keep Chinese.\n"
    "- Fix capitalization: proper nouns capitalized (US Bank, GitHub), normal words lowercase\n"
    "- Keep all meaningful words, technical terms, and proper nouns exactly as spoken\n"
    "- Do NOT add explanations, comments, or labels\n"
    "- Do NOT wrap in quotes"
)


def warmup_llm() -> None:
    """Pre-load the LLM model in background."""
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
            logger.info("LLM loaded: %s (%.1fs)", LLM_MODEL, time.monotonic() - t0)
        except Exception:
            logger.warning("LLM warmup failed", exc_info=True)
        finally:
            _model_cache["loading"] = False

    threading.Thread(target=_load, daemon=True).start()


def polish_text(text: str) -> tuple[str, float]:
    """Polish dictated text using local LLM. Returns (polished_text, seconds)."""
    if not _model_cache["loaded"]:
        return text, 0.0

    if not text or len(text) < 5:
        return text, 0.0

    t0 = time.monotonic()
    result = [text]

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
            # Basic sanity: not empty, not wildly different length
            if not cleaned or len(cleaned) < len(text) * 0.3:
                logger.debug("LLM output too short, rejecting")
                return
            if len(cleaned) > len(text) * 3.0:
                logger.debug("LLM output too long, rejecting")
                return
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
