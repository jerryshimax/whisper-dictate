"""Constants, config.json load/save/validate, and file-permission helpers."""
from __future__ import annotations

import json
import logging
import os
import tempfile

logger = logging.getLogger("whisper_dictate.config")

# ── paths ──────────────────────────────────────────────────
KEYWORDS_FILE = os.path.expanduser("~/.config/whisper/keywords.txt")
HISTORY_FILE = os.path.expanduser("~/.config/whisper/history.jsonl")
CONFIG_FILE = os.path.expanduser("~/.config/whisper/config.json")
LOG_FILE = os.path.expanduser("~/.config/whisper/app.log")

# ── ASR models ─────────────────────────────────────────────
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"

# ── audio ──────────────────────────────────────────────────
SAMPLE_RATE = 16000

# ── hotkey flags ───────────────────────────────────────────
FN_FLAG = 1 << 23        # NSEventModifierFlagFunction
CTRL_FLAG = 1 << 18      # NSEventModifierFlagControl
OPT_FLAG = 1 << 19       # NSEventModifierFlagOption
USE_CTRL_OPT = True      # Set False to revert to FN-only

# ── timing / thresholds ───────────────────────────────────
HISTORY_RETENTION_DAYS = 7
CLIPBOARD_RESTORE_DELAY_SEC = 0.15
MEMORY_SOFT_LIMIT_MB = 2500
MEMORY_MAINTENANCE_INTERVAL_SEC = 2 * 60 * 60  # 2 h
FN_MIN_HOLD_SEC = 0.2
ASR_SLOW_THRESHOLD_SEC = 10.0
ASR_SLOW_RTF_THRESHOLD = 1.8
ASR_WATCHDOG_SEC = 30.0
RECORDING_TIMEOUT_SEC = 120.0
ASR_SLOW_STREAK_TRIGGER = 1
PROMPT_DISABLE_ROUNDS_ON_SLOW = 6
KEYWORDS_MAX_CHARS = 800  # ~200 words ≈ ~220 Whisper tokens (224 token limit)
MIN_AUDIO_DURATION_SEC = 0.6
TRAILING_SILENCE_WINDOW_SEC = 0.05
TRAILING_SILENCE_HOLD_SEC = 0.28
TRAILING_SILENCE_DB_THRESHOLD = -42.0

# ── indicator appearance ───────────────────────────────────
INDICATOR_WIDTH_NORMAL = 120
INDICATOR_WIDTH_RECORDING = 200
INDICATOR_WIDTH_RESULT = 120
INDICATOR_WIDTH_COPY = 220
INDICATOR_HEIGHT = 24
INDICATOR_HEIGHT_RECORDING = 28
INDICATOR_HEIGHT_COPY = 28
INDICATOR_BOTTOM_MARGIN = 65
INDICATOR_CORNER_RADIUS = 12
RESULT_DISPLAY_SECONDS = 5
METER_UPDATE_INTERVAL_SEC = 0.06  # ~16 fps
METER_MIN_DB = -55.0
METER_MAX_DB = 0.0
METER_EMA_ALPHA = 0.22
IDLE_LABEL = "●  ready"
TRANSCRIBING_LABEL = "◌  thinking"
LOADING_LABEL = "◌  loading"
DONE_LABEL = "✓  pasted"
COPY_READY_LABEL = "✓  copied"

# ── waveform bars ──────────────────────────────────────────
WAVEFORM_NUM_BARS = 28
WAVEFORM_BAR_WIDTH = 3.0
WAVEFORM_BAR_GAP = 1.5
WAVEFORM_BAR_MIN_H = 2.0
WAVEFORM_BAR_MAX_H = 18.0
WAVEFORM_BAR_RADIUS = 1.5

# ── logging ────────────────────────────────────────────────
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT = 1


# ── file-permission helpers ────────────────────────────────
def _ensure_private_dir(path: str) -> None:
    """Create directory with 0o700 permissions if it doesn't exist."""
    d = os.path.dirname(path)
    if not os.path.exists(d):
        os.makedirs(d, mode=0o700, exist_ok=True)
    else:
        os.chmod(d, 0o700)


def _set_private(path: str) -> None:
    """Set file to owner-only read/write (0o600)."""
    if os.path.exists(path):
        os.chmod(path, 0o600)


def _secure_tmpfile(suffix: str = ".wav") -> str:
    """Create a temp file with restrictive permissions, return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return path


# ── config load / save ─────────────────────────────────────
_CONFIG_DEFAULTS: dict = {
    "input_device": None,
    "whisper_model": WHISPER_MODEL,
    "history_retention_days": HISTORY_RETENTION_DAYS,
}


def load_user_config() -> dict:
    """Load config.json with defaults for missing keys."""
    cfg = dict(_CONFIG_DEFAULTS)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg.update(json.load(f))
        except Exception:
            logger.warning("Failed to load config.json, using defaults", exc_info=True)
    return cfg


def save_user_config(cfg: dict) -> None:
    """Write config dict to config.json with private permissions."""
    _ensure_private_dir(CONFIG_FILE)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    _set_private(CONFIG_FILE)


# ── keywords ───────────────────────────────────────────────
def load_keywords() -> str:
    """Read keywords.txt as natural-language prompt text.

    Sentences are joined with spaces (not commas) to preserve natural
    language structure, which Whisper's decoder uses more effectively
    than bare keyword lists.
    """
    if os.path.exists(KEYWORDS_FILE):
        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
            return " ".join(lines)
    return ""
