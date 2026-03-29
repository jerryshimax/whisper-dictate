"""macOS system helpers: window/app detection, RSS, memory maintenance."""
from __future__ import annotations

import gc
import logging
import os
import re
import subprocess

from AppKit import NSWorkspace

logger = logging.getLogger("whisper_dictate.macos")

# ── window-title normalization ─────────────────────────────
_TERMINAL_VOLATILE_RE_DIM = re.compile(r'\s+—\s+\d+×\d+$')
_TERMINAL_VOLATILE_RE_PROC = re.compile(r'\s+—\s+\S+\s+◂\s+\S+$')


def _normalize_window_title(title: str) -> str:
    """Strip volatile terminal title parts (subprocess name, dimensions) for stable comparison."""
    if not title:
        return title
    title = _TERMINAL_VOLATILE_RE_DIM.sub('', title)
    title = _TERMINAL_VOLATILE_RE_PROC.sub('', title)
    return title


def get_frontmost_app_id() -> str:
    """Return the bundle identifier of the frontmost app."""
    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return ""
        bundle_id = app.bundleIdentifier()
        return str(bundle_id) if bundle_id else ""
    except Exception:
        logger.warning("Failed to get frontmost app id", exc_info=True)
        return ""


def get_front_window_title() -> str:
    """Get front window title via CGWindowList (fast, no subprocess).

    Uses Quartz CGWindowListCopyWindowInfo instead of osascript,
    reducing latency from ~450ms to ~10ms.
    """
    try:
        from Quartz import (
            CGWindowListCopyWindowInfo,
            kCGWindowListOptionOnScreenOnly,
            kCGWindowListExcludeDesktopElements,
            kCGNullWindowID,
        )
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if not app:
            return ""
        pid = app.processIdentifier()
        windows = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
            kCGNullWindowID,
        )
        if not windows:
            return ""
        for w in windows:
            d = dict(w)
            if d.get("kCGWindowOwnerPID") == pid and d.get("kCGWindowName"):
                return str(d["kCGWindowName"]).replace("\n", " ")
        return ""
    except Exception:
        logger.warning("Failed to get front window title", exc_info=True)
        return ""


def get_rss_mb() -> float:
    """Return current process RSS in MB (macOS via ps)."""
    try:
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(os.getpid())],
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        if out.returncode != 0:
            return 0.0
        rss_kb = int(out.stdout.strip() or "0")
        return rss_kb / 1024.0
    except Exception:
        logger.warning("Failed to get RSS", exc_info=True)
        return 0.0


def run_memory_maintenance() -> None:
    """Best-effort memory cleanup for long-running tray app.

    Feature 6: More surgical — only run gc.collect(), do NOT clear MLX metal
    cache. Clearing the cache forces model re-compilation on next inference,
    adding 200-500ms latency. The RSS limit auto-restart handles true OOM.
    """
    gc.collect()
    # Intentionally NOT clearing MLX cache here — keeping the metal cache hot
    # means the next transcription starts instantly instead of recompiling.
    # The auto-restart at MEMORY_SOFT_LIMIT_MB handles true memory pressure.
