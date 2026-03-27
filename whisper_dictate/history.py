"""JSONL history: save, cleanup, file initialization, and keyword mining."""
from __future__ import annotations

import collections
import datetime
import json
import logging
import os
import re

from whisper_dictate.config import (
    HISTORY_FILE,
    HISTORY_RETENTION_DAYS,
    KEYWORDS_FILE,
    _ensure_private_dir,
    _set_private,
)

logger = logging.getLogger("whisper_dictate.history")


def save_history(raw: str, processed: str, duration: float) -> None:
    """Append a transcription record to history.jsonl."""
    _ensure_private_dir(HISTORY_FILE)
    entry = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "raw": raw,
        "processed": processed,
        "duration": round(duration, 1),
    }
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _set_private(HISTORY_FILE)


def cleanup_history() -> None:
    """Remove entries older than HISTORY_RETENTION_DAYS."""
    if not os.path.exists(HISTORY_FILE):
        return
    cutoff = datetime.datetime.now() - datetime.timedelta(days=HISTORY_RETENTION_DAYS)
    kept: list[str] = []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.datetime.fromisoformat(entry["ts"])
                    if ts >= cutoff:
                        kept.append(line)
                except (json.JSONDecodeError, KeyError, ValueError):
                    pass
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(kept) + "\n" if kept else "")
    except Exception:
        logger.error("History cleanup error", exc_info=True)


def ensure_history_file() -> None:
    """Create history file if it doesn't exist."""
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    if not os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "w", encoding="utf-8"):
            pass


# ── keyword mining ────────────────────────────────────────
_PROPER_NOUN_RE = re.compile(r'\b[A-Z][a-zA-Z]{2,}\b')
_ENGLISH_IN_CHINESE_RE = re.compile(r'(?<=[\u4e00-\u9fff])\s*([A-Za-z][A-Za-z0-9 ]{1,30})\s*(?=[\u4e00-\u9fff])')
_COMMON_WORDS = frozenset({
    "The", "This", "That", "What", "When", "Where", "How", "Why",
    "Can", "Could", "Would", "Should", "Are", "Was", "Were", "Have",
    "Has", "Had", "Not", "But", "And", "For", "With", "From",
    "Just", "Like", "Also", "Very", "Really", "Actually", "Basically",
    "About", "After", "Before", "Then", "Now", "Here", "There",
    "Some", "Any", "All", "More", "Other", "Into", "Over",
})


def suggest_keywords(min_count: int = 3) -> list[str]:
    """Mine transcription history for frequently-used terms not in keywords.txt.

    Returns a list of suggested terms that appear >= min_count times
    in recent transcriptions but aren't already in the keywords file.
    """
    if not os.path.exists(HISTORY_FILE):
        return []

    # Load existing keywords to avoid duplicates
    existing = set()
    if os.path.exists(KEYWORDS_FILE):
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            text = f.read().lower()
            existing = set(re.findall(r'[a-z]{3,}', text))

    # Count terms from recent transcriptions
    term_counts: dict[str, int] = collections.Counter()
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    raw = entry.get("raw", "")
                    # Extract proper nouns (capitalized English words)
                    for match in _PROPER_NOUN_RE.findall(raw):
                        if match not in _COMMON_WORDS:
                            term_counts[match] += 1
                    # Extract English embedded in Chinese text
                    for match in _ENGLISH_IN_CHINESE_RE.findall(raw):
                        term = match.strip()
                        if len(term) >= 3:
                            term_counts[term] += 1
                except (json.JSONDecodeError, KeyError):
                    continue
    except Exception:
        logger.debug("Keyword mining failed", exc_info=True)
        return []

    # Filter: frequent terms not already in keywords
    suggestions = [
        term for term, count in term_counts.most_common(20)
        if count >= min_count and term.lower() not in existing
    ]
    return suggestions
