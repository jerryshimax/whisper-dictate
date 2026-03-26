"""JSONL history: save, cleanup, and file initialization."""
from __future__ import annotations

import datetime
import json
import logging
import os

from whisper_dictate.config import (
    HISTORY_FILE,
    HISTORY_RETENTION_DAYS,
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
