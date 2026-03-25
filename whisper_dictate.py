#!/usr/bin/env python3
"""Whisper Dictation v2 — macOS app with FN hold-to-talk, post-processing, and history.

Usage:
    conda activate voice && python whisper_dictate.py
    Or: open ~/Applications/WhisperDictate.app

Requirements:
    - System Settings > Keyboard > "Press 🌐 key to" → "Do Nothing"
    - System Settings > Privacy > Accessibility → allow the app
    - conda env: voice (python 3.10, mlx-whisper, pyobjc)

Keywords:
    Edit ~/.config/whisper/keywords.txt (comma-separated terms).
    Changes are picked up automatically on each transcription.
"""
from __future__ import annotations

import datetime
import gc
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import signal
import sys

import numpy as np
import sounddevice as sd
import soundfile as sf

# PyObjC
import objc
from AppKit import (
    NSApplication,
    NSApp,
    NSObject,
    NSWindow,
    NSPanel,
    NSScreen,
    NSColor,
    NSFont,
    NSTextField,
    NSView,
    NSButton,
    NSMakeRect,
    NSWindowStyleMaskBorderless,
    NSBackingStoreBuffered,
    NSApplicationActivationPolicyAccessory,
    NSStatusBar,
    NSMenu,
    NSMenuItem,
    NSImage,
    NSBezierPath,
    NSBezelStyleInline,
    NSPasteboard,
    NSPasteboardItem,
    NSWorkspace,
)
from AppKit import NSEvent, NSFlagsChangedMask
from Foundation import NSData
from Quartz import (
    CGEventGetFlags,
    CGEventSourceFlagsState,
    kCGEventFlagsChanged,
    kCGEventSourceStateHIDSystemState,
    kCGEventTapDisabledByTimeout,
    kCGEventTapDisabledByUserInput,
    kCGEventTapOptionListenOnly,
    kCGHeadInsertEventTap,
    kCGSessionEventTap,
    CGEventTapCreate,
    CGEventTapEnable,
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    kCFRunLoopCommonModes,
    kCGFloatingWindowLevel,
    kCGScreenSaverWindowLevel,
)
from CoreFoundation import CFRunLoopGetMain
from PyObjCTools import AppHelper

# Core Animation (for waveform visualization)
import ctypes as _ctypes
_ca_lib = _ctypes.cdll.LoadLibrary('/System/Library/Frameworks/QuartzCore.framework/QuartzCore')
_ca_lib.CACurrentMediaTime.restype = _ctypes.c_double

import objc as _objc_loader
_QuartzCore = _objc_loader.loadBundle(
    'QuartzCore', globals(),
    '/System/Library/Frameworks/QuartzCore.framework',
)
# Now CALayer, CATransaction, CABasicAnimation are in global scope
from Quartz import CGColorCreateGenericRGB

# ── constants ──────────────────────────────────────────────
KEYWORDS_FILE = os.path.expanduser("~/.config/whisper/keywords.txt")
HISTORY_FILE = os.path.expanduser("~/.config/whisper/history.jsonl")
CONFIG_FILE = os.path.expanduser("~/.config/whisper/config.json")
LOG_FILE = os.path.expanduser("~/.config/whisper/app.log")
WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
ASR_BACKEND = "whisper"  # "whisper" or "paraformer" (togglable via right-click menu)
PARAFORMER_MODEL = "paraformer-zh"
PARAFORMER_VAD = "fsmn-vad"
PARAFORMER_PUNC = "ct-punc"
_funasr_model = None  # lazy-loaded singleton
SAMPLE_RATE = 16000
FN_FLAG = 1 << 23  # NSEventModifierFlagFunction
# Custom hotkey: Control + Option (both must be held)
CTRL_FLAG = 1 << 18   # NSEventModifierFlagControl
OPT_FLAG  = 1 << 19   # NSEventModifierFlagOption
USE_CTRL_OPT = True   # Set False to revert to FN-only
HISTORY_RETENTION_DAYS = 7
CLIPBOARD_RESTORE_DELAY_SEC = 0.15
MEMORY_SOFT_LIMIT_MB = 2500
MEMORY_MAINTENANCE_INTERVAL_SEC = 2 * 60 * 60  # 2h (was 24h)
FN_MIN_HOLD_SEC = 0.2  # minimum FN hold to filter ghost events
ASR_SLOW_THRESHOLD_SEC = 10.0
ASR_SLOW_RTF_THRESHOLD = 1.8
ASR_WATCHDOG_SEC = 30.0           # max time for transcription before watchdog resets
RECORDING_TIMEOUT_SEC = 120.0     # max recording duration (auto-stop if FN release missed)
ASR_SLOW_STREAK_TRIGGER = 1
PROMPT_DISABLE_ROUNDS_ON_SLOW = 6
KEYWORDS_MAX_CHARS = 900
MIN_AUDIO_DURATION_SEC = 0.6
TRAILING_SILENCE_WINDOW_SEC = 0.05
TRAILING_SILENCE_HOLD_SEC = 0.28
TRAILING_SILENCE_DB_THRESHOLD = -42.0

# indicator appearance
INDICATOR_WIDTH_NORMAL = 170
INDICATOR_WIDTH_RECORDING = 200
INDICATOR_WIDTH_RESULT = 170
INDICATOR_WIDTH_COPY = 240
INDICATOR_HEIGHT = 20
INDICATOR_HEIGHT_RECORDING = 26
INDICATOR_HEIGHT_COPY = 26
INDICATOR_BOTTOM_MARGIN = 65
INDICATOR_CORNER_RADIUS = 12
RESULT_DISPLAY_SECONDS = 5
METER_UPDATE_INTERVAL_SEC = 0.06  # ~16fps for smooth waveform
METER_MIN_DB = -55.0
METER_MAX_DB = 0.0
METER_EMA_ALPHA = 0.22
IDLE_LABEL = "◦  dictate"
TRANSCRIBING_LABEL = "✎  ···"
LOADING_LABEL = "◦  loading"
DONE_LABEL = "✓  done"
COPY_READY_LABEL = "✓ Ready to Copy"

# waveform bars
WAVEFORM_NUM_BARS = 28
WAVEFORM_BAR_WIDTH = 3.0
WAVEFORM_BAR_GAP = 1.5
WAVEFORM_BAR_MIN_H = 2.0
WAVEFORM_BAR_MAX_H = 18.0
WAVEFORM_BAR_RADIUS = 1.5


# ── post-processing ───────────────────────────────────────
_FILLER_ZH = re.compile(
    r'(?<![一-龥])(?:嗯+|啊+|呃+|那个|就是说|就是|然后嘛)(?![一-龥])'
)
_FILLER_EN = re.compile(
    r'\b(?:um+|uh+|like|you know|I mean|basically|actually|so+)\b',
    re.IGNORECASE,
)

_HALLUCINATION_RE = re.compile(
    r'(?:字幕志愿者|字幕由|请不要|谢谢大家|感谢收看|订阅|小铃铛|'
    r'(?:\$i\s*){3,}|(.{2,6})\1{4,})',
)
_TAIL_NOISE_RE = re.compile(
    r'[\s，,。.!?！？；;:：、\-]*(?:sperdy|seperti)[\s，,。.!?！？；;:：、\-]*$',
    re.IGNORECASE,
)


def _strip_hallucinations(text: str) -> str:
    text = _HALLUCINATION_RE.sub('', text)
    return text.strip()


def _strip_tail_noise(text: str) -> str:
    """Drop known recurring tail-noise token from ASR output."""
    return _TAIL_NOISE_RE.sub('', text).strip()


_TERMINAL_VOLATILE_RE_DIM = re.compile(r'\s+—\s+\d+×\d+$')
_TERMINAL_VOLATILE_RE_PROC = re.compile(r'\s+—\s+\S+\s+◂\s+\S+$')


def _normalize_window_title(title: str) -> str:
    """Strip volatile terminal title parts (subprocess name, dimensions) for stable comparison."""
    if not title:
        return title
    title = _TERMINAL_VOLATILE_RE_DIM.sub('', title)
    title = _TERMINAL_VOLATILE_RE_PROC.sub('', title)
    return title


def _trim_trailing_silence(audio: np.ndarray) -> tuple[np.ndarray, float]:
    if audio.size == 0:
        return audio, 0.0

    frame_size = max(1, int(SAMPLE_RATE * TRAILING_SILENCE_WINDOW_SEC))
    min_tail_run = int(SAMPLE_RATE * TRAILING_SILENCE_HOLD_SEC)
    tail_run = 0
    trim_samples = 0
    total = len(audio)

    for end in range(total, 0, -frame_size):
        start = max(0, end - frame_size)
        frame = audio[start:end]
        rms = float(np.sqrt(np.mean(np.square(frame))))
        db = 20.0 * np.log10(max(rms, 1e-7))
        if db <= TRAILING_SILENCE_DB_THRESHOLD:
            tail_run += len(frame)
            if tail_run >= min_tail_run:
                trim_samples = tail_run
                continue
        break

    if trim_samples <= 0:
        return audio, 0.0

    keep_samples = max(frame_size, total - trim_samples)
    trimmed = audio[:keep_samples]
    return trimmed, (total - len(trimmed)) / SAMPLE_RATE


_REPEATED_BLOCK_RE = re.compile(r'(.{8,120}?)\1{1,}')


def _collapse_repeated_blocks(text: str) -> str:
    """Collapse exact repeated long chunks: AAA -> A."""
    prev = None
    while prev != text:
        prev = text
        text = _REPEATED_BLOCK_RE.sub(r'\1', text)
    return text


def _norm_clause_for_dedupe(text: str) -> str:
    text = text.lower()
    text = re.sub(r'[\s，,。.!?！？；;:：、"\'`“”‘’\-\(\)\[\]{}]+', '', text)
    return text


def _dedupe_adjacent_clauses(text: str) -> str:
    """Remove adjacent duplicated clauses split by punctuation/comma."""
    parts = re.split(r'([，,。.!?！？；;:\n])', text)
    if len(parts) <= 1:
        return text

    out: list[str] = []
    prev_norm = ""
    i = 0
    while i < len(parts):
        clause = parts[i].strip()
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        i += 2

        if not clause:
            continue

        norm = _norm_clause_for_dedupe(clause)
        # Keep very short acknowledgements to avoid over-deletion.
        if norm and norm == prev_norm and len(norm) >= 6:
            continue

        out.append(clause)
        if sep:
            out.append(sep)
        prev_norm = norm

    return ''.join(out).strip()


def _dedupe_repeated_tail_phrase(text: str) -> str:
    """Collapse repeated suffix phrase like 'X X X' -> 'X'."""
    s = text.strip()
    if len(s) < 12:
        return s

    # Try multiple tail lengths; prioritize longer phrases.
    max_len = min(36, len(s) // 2)
    for phrase_len in range(max_len, 3, -1):
        phrase = s[-phrase_len:]
        if not phrase.strip():
            continue
        # Avoid pure punctuation/noise phrase.
        if not re.search(r'[A-Za-z0-9\u4e00-\u9fff]', phrase):
            continue

        count = 0
        cursor = len(s)
        while cursor >= phrase_len and s[cursor - phrase_len:cursor] == phrase:
            count += 1
            cursor -= phrase_len

        if count >= 2:
            s = s[:cursor] + phrase
            break

    return s


def _dedupe_tail_by_char_stream(text: str) -> str:
    """More aggressive tail-loop dedupe that ignores spaces/punctuation."""
    s = text.strip()
    if len(s) < 16:
        return s

    # Keep only semantic chars; map back to original index.
    stream_chars: list[str] = []
    stream_to_orig: list[int] = []
    for i, ch in enumerate(s):
        if re.match(r'[A-Za-z0-9\u4e00-\u9fff]', ch):
            stream_chars.append(ch)
            stream_to_orig.append(i)

    n = len(stream_chars)
    if n < 16:
        return s

    max_unit = min(24, n // 2)
    for unit_len in range(max_unit, 3, -1):
        unit = stream_chars[n - unit_len:n]
        if len(set(unit)) < 3:
            continue

        count = 1
        cursor = n - unit_len
        while cursor - unit_len >= 0 and stream_chars[cursor - unit_len:cursor] == unit:
            count += 1
            cursor -= unit_len

        if count < 2:
            continue

        remove_start_stream = n - unit_len * count
        remove_end_stream = n - unit_len
        if remove_start_stream < 0 or remove_end_stream <= remove_start_stream:
            continue

        remove_start_orig = stream_to_orig[remove_start_stream]
        keep_start_orig = stream_to_orig[remove_end_stream]
        if keep_start_orig <= remove_start_orig:
            continue

        s = s[:remove_start_orig] + s[keep_start_orig:]
        break

    return s


def _remove_fillers(text: str) -> str:
    text = _FILLER_ZH.sub('', text)
    text = _FILLER_EN.sub('', text)
    return text


def _clean_whitespace(text: str) -> str:
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'([，,。.！!？?])\1+', r'\1', text)
    text = re.sub(r'\s*([，,。.！!？?])', r'\1', text)
    return text.strip()


def _postprocess_regex(text: str) -> str:
    text = _strip_hallucinations(text)
    text = _collapse_repeated_blocks(text)
    text = _dedupe_adjacent_clauses(text)
    text = _dedupe_repeated_tail_phrase(text)
    text = _dedupe_tail_by_char_stream(text)
    text = _remove_fillers(text)
    text = _strip_tail_noise(text)
    text = _clean_whitespace(text)
    return text


def postprocess_fast(text: str) -> str:
    """Immediate path: hallucination strip + regex. Always returns quickly."""
    text = _strip_hallucinations(text)
    if not text:
        return text
    return _postprocess_regex(text)


# ── history ────────────────────────────────────────────────
def save_history(raw: str, processed: str, duration: float) -> None:
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
    if not os.path.exists(HISTORY_FILE):
        return
    cutoff = datetime.datetime.now() - datetime.timedelta(days=HISTORY_RETENTION_DAYS)
    kept = []
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
    except Exception as e:
        print(f"[whisper_dictate] History cleanup error: {e}")


def ensure_history_file() -> None:
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    if not os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "w", encoding="utf-8"):
            pass


# ── helpers ────────────────────────────────────────────────
def load_keywords() -> str:
    if os.path.exists(KEYWORDS_FILE):
        with open(KEYWORDS_FILE, "r") as f:
            lines = [l.strip() for l in f if l.strip() and not l.strip().startswith('#')]
            return ', '.join(lines)
    return ""


def _load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_config(cfg: dict) -> None:
    _ensure_private_dir(CONFIG_FILE)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    _set_private(CONFIG_FILE)


def _get_input_devices() -> list[dict]:
    devices = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            devices.append({"index": i, "name": d["name"]})
    return devices


def _resolve_input_device() -> int | None:
    cfg = _load_config()
    preferred = cfg.get("input_device")
    if not preferred:
        return None
    for d in _get_input_devices():
        if d["name"] == preferred:
            print(f"[whisper_dictate] Using preferred input: {d['name']} (index {d['index']})")
            return d["index"]
    print(f"[whisper_dictate] Preferred device '{preferred}' not found, using system default")
    return None


def _snapshot_clipboard() -> tuple[int, list[dict[str, bytes]]]:
    pb = NSPasteboard.generalPasteboard()
    snapshot: list[dict[str, bytes]] = []
    items = pb.pasteboardItems() or []
    for item in items:
        item_data: dict[str, bytes] = {}
        for paste_type in (item.types() or []):
            data = item.dataForType_(paste_type)
            if data is None:
                continue
            try:
                item_data[str(paste_type)] = bytes(data)
            except Exception:
                continue
        if item_data:
            snapshot.append(item_data)
    return int(pb.changeCount()), snapshot


def _restore_clipboard(snapshot: list[dict[str, bytes]]) -> None:
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    if not snapshot:
        return
    restored_items = []
    for item_data in snapshot:
        pb_item = NSPasteboardItem.alloc().init()
        for paste_type, raw in item_data.items():
            ns_data = NSData.dataWithBytes_length_(raw, len(raw))
            pb_item.setData_forType_(ns_data, paste_type)
        restored_items.append(pb_item)
    pb.writeObjects_(restored_items)


def paste_text(text: str) -> None:
    snapshot = None
    previous_change_count = None
    try:
        previous_change_count, snapshot = _snapshot_clipboard()
    except Exception as e:
        print(f"[whisper_dictate] Clipboard snapshot failed: {e}")

    proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
    proc.communicate(text.encode("utf-8"))
    subprocess.run(
        ["osascript", "-e",
         'tell application "System Events" to keystroke "v" using command down'],
        capture_output=True,
    )

    if snapshot is None or previous_change_count is None:
        return

    def _restore_if_unchanged():
        try:
            pb = NSPasteboard.generalPasteboard()
            expected = previous_change_count + 1
            if pb.changeCount() != expected:
                # User/app changed clipboard after paste; do not overwrite.
                return
            _restore_clipboard(snapshot)
        except Exception as e:
            print(f"[whisper_dictate] Clipboard restore failed: {e}")

    timer = threading.Timer(CLIPBOARD_RESTORE_DELAY_SEC, _restore_if_unchanged)
    timer.daemon = True
    timer.start()


def get_frontmost_app_id() -> str:
    try:
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return ""
        bundle_id = app.bundleIdentifier()
        return str(bundle_id) if bundle_id else ""
    except Exception:
        return ""


def get_front_window_title() -> str:
    """Get front window title via System Events (heavier than app-id check)."""
    # Query focused window title via System Events.
    script = (
        'tell application "System Events"\n'
        '  try\n'
        '    set frontProc to first process whose frontmost is true\n'
        '    set wt to ""\n'
        '    try\n'
        '      set wt to name of front window of frontProc\n'
        '    end try\n'
        '    return wt\n'
        '  on error\n'
        '    return ""\n'
        '  end try\n'
        'end tell'
    )
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=0.45,
        )
        if out.returncode == 0:
            return out.stdout.strip().replace("\n", " ")
    except Exception:
        pass

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
        return 0.0


def run_memory_maintenance() -> None:
    """Best-effort memory cleanup for long-running tray app."""
    gc.collect()
    try:
        import mlx.core as mx  # type: ignore
        if hasattr(mx, "clear_cache"):
            mx.clear_cache()
    except Exception:
        pass


LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
LOG_BACKUP_COUNT = 1


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


def _rotate_log_if_needed() -> None:
    """Simple log rotation: if log exceeds max size, rotate to .1 and truncate."""
    if not os.path.exists(LOG_FILE):
        return
    try:
        if os.path.getsize(LOG_FILE) > LOG_MAX_BYTES:
            backup = LOG_FILE + ".1"
            if os.path.exists(backup):
                os.unlink(backup)
            os.rename(LOG_FILE, backup)
            _set_private(backup)
    except Exception:
        pass


def _secure_tmpfile(suffix=".wav") -> str:
    """Create a temp file with restrictive permissions, return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return path


def _get_funasr_model():
    global _funasr_model
    if _funasr_model is None:
        from funasr import AutoModel
        _funasr_model = AutoModel(
            model=PARAFORMER_MODEL,
            vad_model=PARAFORMER_VAD,
            punc_model=PARAFORMER_PUNC,
        )
        print(f"[whisper_dictate] FunASR Paraformer loaded ({PARAFORMER_MODEL})")
    return _funasr_model


def warmup_model() -> None:
    silence = np.zeros(SAMPLE_RATE, dtype=np.float32)
    tmp = _secure_tmpfile()
    sf.write(tmp, silence, SAMPLE_RATE)
    try:
        if ASR_BACKEND == "paraformer":
            m = _get_funasr_model()
            m.generate(input=tmp)
        else:
            import mlx_whisper
            mlx_whisper.transcribe(tmp, path_or_hf_repo=WHISPER_MODEL)
    except Exception:
        pass
    os.unlink(tmp)


# ── waveform view ─────────────────────────────────────────
class WaveformView(NSView):
    """Layer-backed view with animated waveform bars using Core Animation."""

    _bars = None
    _levels = None
    _state = "idle"
    _shimmer_timer = None

    def initWithFrame_(self, frame):
        self = objc.super(WaveformView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.setWantsLayer_(True)
        self.layer().setMasksToBounds_(True)
        self._bars = []
        self._levels = [0.0] * WAVEFORM_NUM_BARS
        self._state = "idle"
        self._create_bars()
        self.setHidden_(True)
        return self

    def _create_bars(self):
        total_w = WAVEFORM_NUM_BARS * (WAVEFORM_BAR_WIDTH + WAVEFORM_BAR_GAP) - WAVEFORM_BAR_GAP
        bounds = self.bounds()
        start_x = (bounds.size.width - total_w) / 2.0
        center_y = bounds.size.height / 2.0

        for i in range(WAVEFORM_NUM_BARS):
            bar = CALayer.alloc().init()
            x = start_x + i * (WAVEFORM_BAR_WIDTH + WAVEFORM_BAR_GAP)
            h = WAVEFORM_BAR_MIN_H
            y = center_y - h / 2.0
            bar.setFrame_(((x, y), (WAVEFORM_BAR_WIDTH, h)))
            bar.setCornerRadius_(WAVEFORM_BAR_RADIUS)
            bar.setBackgroundColor_(CGColorCreateGenericRGB(1.0, 1.0, 1.0, 0.15))
            self.layer().addSublayer_(bar)
            self._bars.append(bar)

    def relayout(self):
        """Recalculate bar positions after resize."""
        total_w = WAVEFORM_NUM_BARS * (WAVEFORM_BAR_WIDTH + WAVEFORM_BAR_GAP) - WAVEFORM_BAR_GAP
        bounds = self.bounds()
        start_x = (bounds.size.width - total_w) / 2.0
        center_y = bounds.size.height / 2.0
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        for i, bar in enumerate(self._bars):
            x = start_x + i * (WAVEFORM_BAR_WIDTH + WAVEFORM_BAR_GAP)
            h = WAVEFORM_BAR_MIN_H
            y = center_y - h / 2.0
            bar.setFrame_(((x, y), (WAVEFORM_BAR_WIDTH, h)))
        CATransaction.commit()

    def set_state(self, state):
        """Transition to: 'idle', 'recording', 'transcribing', 'done'."""
        old = self._state
        self._state = state
        if self._shimmer_timer:
            self._shimmer_timer.cancel()
            self._shimmer_timer = None

        if state == "recording":
            self.setHidden_(False)
            self._levels = [0.0] * WAVEFORM_NUM_BARS
            self._stop_animations()
            self._set_all_bars_idle()
        elif state == "transcribing":
            self.setHidden_(False)
            self._start_shimmer()
        elif state == "done":
            self._flash_done()
        else:
            self._stop_animations()
            self._set_all_bars_idle()
            self.setHidden_(True)

    def update_level(self, db):
        """Feed new audio level (dB). Called on main thread during recording."""
        if self._state != "recording":
            return
        ratio = max(0.0, min(1.0, (db - METER_MIN_DB) / (METER_MAX_DB - METER_MIN_DB)))
        self._levels.pop(0)
        self._levels.append(ratio)
        self._render_levels()

    def _render_levels(self):
        bounds = self.bounds()
        center_y = bounds.size.height / 2.0
        total_w = WAVEFORM_NUM_BARS * (WAVEFORM_BAR_WIDTH + WAVEFORM_BAR_GAP) - WAVEFORM_BAR_GAP
        start_x = (bounds.size.width - total_w) / 2.0

        CATransaction.begin()
        CATransaction.setAnimationDuration_(0.06)
        for i, bar in enumerate(self._bars):
            ratio = self._levels[i]
            h = WAVEFORM_BAR_MIN_H + ratio * (WAVEFORM_BAR_MAX_H - WAVEFORM_BAR_MIN_H)
            x = start_x + i * (WAVEFORM_BAR_WIDTH + WAVEFORM_BAR_GAP)
            y = center_y - h / 2.0
            bar.setFrame_(((x, y), (WAVEFORM_BAR_WIDTH, h)))
            # Color gradient: left=cyan, right=blue, intensity by level
            t = i / max(1, WAVEFORM_NUM_BARS - 1)  # 0..1 across bars
            r = 0.2 + 0.15 * t
            g = 0.75 - 0.25 * t + 0.25 * ratio
            b = 0.9 + 0.1 * ratio
            a = 0.25 + 0.7 * ratio
            bar.setBackgroundColor_(CGColorCreateGenericRGB(r, g, b, a))
        CATransaction.commit()

    def _set_all_bars_idle(self):
        bounds = self.bounds()
        center_y = bounds.size.height / 2.0
        total_w = WAVEFORM_NUM_BARS * (WAVEFORM_BAR_WIDTH + WAVEFORM_BAR_GAP) - WAVEFORM_BAR_GAP
        start_x = (bounds.size.width - total_w) / 2.0
        CATransaction.begin()
        CATransaction.setAnimationDuration_(0.3)
        for i, bar in enumerate(self._bars):
            x = start_x + i * (WAVEFORM_BAR_WIDTH + WAVEFORM_BAR_GAP)
            h = WAVEFORM_BAR_MIN_H
            y = center_y - h / 2.0
            bar.setFrame_(((x, y), (WAVEFORM_BAR_WIDTH, h)))
            bar.setBackgroundColor_(CGColorCreateGenericRGB(1.0, 1.0, 1.0, 0.15))
            bar.setOpacity_(1.0)
        CATransaction.commit()

    def _start_shimmer(self):
        """Traveling wave shimmer for transcribing state."""
        self._stop_animations()
        bounds = self.bounds()
        center_y = bounds.size.height / 2.0
        total_w = WAVEFORM_NUM_BARS * (WAVEFORM_BAR_WIDTH + WAVEFORM_BAR_GAP) - WAVEFORM_BAR_GAP
        start_x = (bounds.size.width - total_w) / 2.0

        # Set bars to a base state
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        for i, bar in enumerate(self._bars):
            x = start_x + i * (WAVEFORM_BAR_WIDTH + WAVEFORM_BAR_GAP)
            bar.setFrame_(((x, center_y - 3), (WAVEFORM_BAR_WIDTH, 6)))
            bar.setBackgroundColor_(CGColorCreateGenericRGB(0.5, 0.8, 1.0, 0.5))
            bar.setOpacity_(0.3)
        CATransaction.commit()

        # Add shimmer animation to each bar with phase offset
        for i, bar in enumerate(self._bars):
            anim = CABasicAnimation.animationWithKeyPath_("opacity")
            anim.setFromValue_(0.15)
            anim.setToValue_(0.8)
            anim.setDuration_(0.8)
            anim.setAutoreverses_(True)
            anim.setRepeatCount_(1e6)
            # Stagger: each bar starts slightly after the previous
            begin = _ca_lib.CACurrentMediaTime() + i * 0.04
            anim.setBeginTime_(begin)
            bar.addAnimation_forKey_(anim, "shimmer")

            # Also animate height for a wave effect
            h_anim = CABasicAnimation.animationWithKeyPath_("bounds.size.height")
            h_anim.setFromValue_(4.0)
            h_anim.setToValue_(12.0)
            h_anim.setDuration_(0.8)
            h_anim.setAutoreverses_(True)
            h_anim.setRepeatCount_(1e6)
            h_anim.setBeginTime_(begin)
            bar.addAnimation_forKey_(h_anim, "wave")

        self._levels = [0.0] * WAVEFORM_NUM_BARS

    def _flash_done(self):
        """Brief green flash then fade to idle."""
        CATransaction.begin()
        CATransaction.setAnimationDuration_(0.15)
        for bar in self._bars:
            bar.removeAllAnimations()
            bar.setBackgroundColor_(CGColorCreateGenericRGB(0.2, 0.9, 0.4, 0.9))
            bar.setOpacity_(1.0)
        CATransaction.commit()

        def _fade_out():
            def _do():
                if self._state == "done":
                    self._set_all_bars_idle()
                    self.setHidden_(True)
            AppHelper.callAfter(_do)
        t = threading.Timer(0.6, _fade_out)
        t.daemon = True
        t.start()

    def _stop_animations(self):
        for bar in self._bars:
            bar.removeAllAnimations()


# ── rounded view ───────────────────────────────────────────
class RoundedView(NSView):
    """NSView subclass with rounded corners and background color."""

    _bg_color = None

    def initWithFrame_(self, frame):
        self = objc.super(RoundedView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._bg_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.15, 0.15, 0.15, 0.92
        )
        return self

    def drawRect_(self, rect):
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            self.bounds(), INDICATOR_CORNER_RADIUS, INDICATOR_CORNER_RADIUS
        )
        if self._bg_color:
            self._bg_color.setFill()
        path.fill()

    def setBgColor_(self, color):
        self._bg_color = color
        self.setNeedsDisplay_(True)

    _ctx_menu = None
    _app_delegate = None

    def rightMouseDown_(self, event):
        if self._ctx_menu:
            if self._app_delegate and hasattr(self._app_delegate, '_refresh_mic_submenu'):
                self._app_delegate._refresh_mic_submenu()
            NSMenu.popUpContextMenu_withEvent_forView_(
                self._ctx_menu, event, self
            )

    def mouseDown_(self, event):
        pass  # consume left clicks (170x20 at screen bottom — negligible)


# ── app delegate ───────────────────────────────────────────
class AppDelegate(NSObject):
    def init(self):
        self = objc.super(AppDelegate, self).init()
        self.is_recording = False
        self.is_transcribing = False
        self.audio_chunks = []
        self.stream = None
        self.keywords = load_keywords()
        self._fn_held = False
        self.indicator = None
        self.label = None
        self.rounded_view = None
        self.copy_btn = None
        self.status_item = None
        self._hide_timer = None
        self._last_text = ""
        self._event_tap_failed = False
        self._meter_last_update = 0.0
        self._meter_db_smooth = METER_MIN_DB
        self._recording_front_app = ""
        self._recording_front_window = ""
        self._pending_copy_text = ""
        self._last_memory_maintenance_ts = 0.0
        self._slow_asr_streak = 0
        self._disable_prompt_rounds = 0
        self._fn_press_time = 0.0
        self._asr_watchdog = None
        self._recording_timeout = None
        self.waveform_view = None
        return self

    def applicationDidFinishLaunching_(self, notification):
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        self._create_indicator()
        self._setup_right_click_menu()

        cleanup_history()

        threading.Thread(target=self._warmup, daemon=True).start()
        threading.Thread(target=self._start_event_tap, daemon=True).start()

    # ── floating indicator at bottom center ──
    def _create_indicator(self):
        screen = NSScreen.mainScreen().frame()
        x = (screen.size.width - INDICATOR_WIDTH_NORMAL) / 2
        y = INDICATOR_BOTTOM_MARGIN

        frame = NSMakeRect(x, y, INDICATOR_WIDTH_NORMAL, INDICATOR_HEIGHT)

        self.indicator = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        self.indicator.setLevel_(kCGFloatingWindowLevel)
        self.indicator.setHidesOnDeactivate_(False)
        self.indicator.setCanHide_(False)
        self.indicator.setOpaque_(False)
        self.indicator.setBackgroundColor_(NSColor.clearColor())
        self.indicator.setHasShadow_(True)
        self.indicator.setIgnoresMouseEvents_(False)
        self.indicator.setCollectionBehavior_(
            1 << 0 | 1 << 4  # canJoinAllSpaces | fullScreenAuxiliary
        )

        self.rounded_view = RoundedView.alloc().initWithFrame_(
            NSMakeRect(0, 0, INDICATOR_WIDTH_NORMAL, INDICATOR_HEIGHT)
        )

        self.label = NSTextField.labelWithString_(IDLE_LABEL)
        self.label.setFont_(NSFont.systemFontOfSize_weight_(10.5, 0.3))
        self.label.setTextColor_(NSColor.whiteColor())
        self.label.setAlignment_(1)  # center
        label_w = INDICATOR_WIDTH_NORMAL - 12
        label_h = 14
        label_x = 6
        label_y = (INDICATOR_HEIGHT - label_h) / 2
        self.label.setFrame_(NSMakeRect(label_x, label_y, label_w, label_h))

        self.copy_btn = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 1))
        self.copy_btn.setTitle_("📋")
        self.copy_btn.setBezelStyle_(NSBezelStyleInline)
        self.copy_btn.setBordered_(False)
        self.copy_btn.setFont_(NSFont.systemFontOfSize_(16))
        self.copy_btn.setTarget_(self)
        self.copy_btn.setAction_(objc.selector(self.copyClicked_, signature=b"v@:@"))
        self.copy_btn.setHidden_(True)

        # Waveform visualization (hidden by default, shown during recording/transcribing)
        self.waveform_view = WaveformView.alloc().initWithFrame_(
            NSMakeRect(0, 0, INDICATOR_WIDTH_RECORDING, INDICATOR_HEIGHT_RECORDING)
        )

        self.rounded_view.addSubview_(self.label)
        self.rounded_view.addSubview_(self.copy_btn)
        self.rounded_view.addSubview_(self.waveform_view)
        self.indicator.contentView().addSubview_(self.rounded_view)
        self._order_indicator_front()

    def _order_indicator_front(self):
        if hasattr(self.indicator, "orderFrontRegardless"):
            self.indicator.orderFrontRegardless()
        else:
            self.indicator.orderFront_(None)

    def _resize_indicator(self, width, height=INDICATOR_HEIGHT):
        screen = NSScreen.mainScreen().frame()
        x = (screen.size.width - width) / 2
        y = INDICATOR_BOTTOM_MARGIN
        self.indicator.setFrame_display_(
            NSMakeRect(x, y, width, height), True
        )
        self.rounded_view.setFrame_(NSMakeRect(0, 0, width, height))

    def _update_indicator(self, text, bg_r, bg_g, bg_b, bg_a=0.92):
        def update():
            self.label.setHidden_(False)
            self.label.setStringValue_(text)
            self.rounded_view.setBgColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    bg_r, bg_g, bg_b, bg_a
                )
            )
        AppHelper.callAfter(update)

    def _update_recording_meter(self, db: float):
        now = time.monotonic()
        if now - self._meter_last_update < METER_UPDATE_INTERVAL_SEC:
            return
        self._meter_last_update = now

        db_clamped = max(METER_MIN_DB, min(METER_MAX_DB, db))
        self._meter_db_smooth = (
            (1.0 - METER_EMA_ALPHA) * self._meter_db_smooth
            + METER_EMA_ALPHA * db_clamped
        )

        smooth_db = self._meter_db_smooth

        def update():
            if not self.is_recording:
                return
            self.waveform_view.update_level(smooth_db)
            self._order_indicator_front()

        AppHelper.callAfter(update)

    def _show_result(self, text):
        def update():
            if self._hide_timer:
                self._hide_timer.cancel()

            # Flash waveform green then hide it
            self.waveform_view.set_state("done")

            self._resize_indicator(INDICATOR_WIDTH_RESULT)
            self.indicator.setIgnoresMouseEvents_(False)
            self.copy_btn.setHidden_(True)
            self.label.setHidden_(False)
            self.label.setFont_(NSFont.systemFontOfSize_weight_(10.5, 0.3))
            label_w = INDICATOR_WIDTH_RESULT - 12
            label_h = 14
            label_x = 6
            label_y = (INDICATOR_HEIGHT - label_h) / 2
            self.label.setFrame_(NSMakeRect(label_x, label_y, label_w, label_h))
            self.label.setAlignment_(1)  # center
            self.label.setStringValue_(DONE_LABEL)

            self.rounded_view.setBgColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    0.17, 0.17, 0.17, 0.52
                )
            )

            self._order_indicator_front()

            self._hide_timer = threading.Timer(
                RESULT_DISPLAY_SECONDS, self._reset_indicator
            )
            self._hide_timer.daemon = True
            self._hide_timer.start()
        AppHelper.callAfter(update)

    def _show_copy_prompt(self, text):
        def update():
            if self._hide_timer:
                self._hide_timer.cancel()
                self._hide_timer = None

            self.waveform_view.set_state("done")

            self._pending_copy_text = text
            self._resize_indicator(INDICATOR_WIDTH_COPY, INDICATOR_HEIGHT_COPY)
            self.indicator.setIgnoresMouseEvents_(False)

            self.label.setHidden_(False)
            self.label.setFont_(NSFont.systemFontOfSize_weight_(10.5, 0.3))
            label_w = INDICATOR_WIDTH_COPY - 74
            label_h = 14
            label_x = 8
            label_y = (INDICATOR_HEIGHT_COPY - label_h) / 2
            self.label.setFrame_(NSMakeRect(label_x, label_y, label_w, label_h))
            self.label.setAlignment_(1)
            self.label.setStringValue_(COPY_READY_LABEL)

            self.copy_btn.setTitle_("Copy")
            self.copy_btn.setBordered_(False)
            self.copy_btn.setFont_(NSFont.monospacedSystemFontOfSize_weight_(10, 0.25))
            self.copy_btn.setFrame_(NSMakeRect(INDICATOR_WIDTH_COPY - 58, 4, 50, 18))
            try:
                self.copy_btn.setContentTintColor_(NSColor.whiteColor())
            except Exception:
                pass
            self.copy_btn.setHidden_(False)

            self.rounded_view.setBgColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.17, 0.17, 0.17, 0.62)
            )
            self._order_indicator_front()

        AppHelper.callAfter(update)

    def _reset_indicator(self):
        def update():
            self._pending_copy_text = ""
            self.waveform_view.set_state("idle")
            self._resize_indicator(INDICATOR_WIDTH_NORMAL)
            self.indicator.setIgnoresMouseEvents_(False)
            self.copy_btn.setHidden_(True)
            self.label.setHidden_(False)
            self.label.setFont_(NSFont.systemFontOfSize_weight_(10.5, 0.3))
            label_w = INDICATOR_WIDTH_NORMAL - 12
            label_h = 14
            label_x = 6
            label_y = (INDICATOR_HEIGHT - label_h) / 2
            self.label.setFrame_(NSMakeRect(label_x, label_y, label_w, label_h))
            self.label.setAlignment_(1)  # center
            self.label.setStringValue_(IDLE_LABEL)
            self.rounded_view.setBgColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    0.17, 0.17, 0.17, 0.52
                )
            )
            self._order_indicator_front()
        AppHelper.callAfter(update)

    @objc.typedSelector(b"v@:@")
    def copyClicked_(self, sender):
        to_copy = self._pending_copy_text or self._last_text
        if to_copy:
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            proc.communicate(to_copy.encode("utf-8"))
            self._pending_copy_text = ""

            self.label.setStringValue_("✓ Copied")
            if self._hide_timer:
                self._hide_timer.cancel()
            self._hide_timer = threading.Timer(1.5, self._reset_indicator)
            self._hide_timer.daemon = True
            self._hide_timer.start()

    # ── right-click context menu on floating indicator ──
    def _setup_right_click_menu(self):
        menu = NSMenu.alloc().init()
        for title, action in [
            ("Edit Keywords", "ctxKeywords:"),
            ("Open History", "ctxHistory:"),
            ("Open Log", "ctxLog:"),
        ]:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title, action, ""
            )
            item.setTarget_(self)
            menu.addItem_(item)

        menu.addItem_(NSMenuItem.separatorItem())

        # Input Device submenu
        mic_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Input Device", "", ""
        )
        mic_submenu = NSMenu.alloc().init()
        mic_item.setSubmenu_(mic_submenu)
        menu.addItem_(mic_item)
        self._mic_submenu = mic_submenu

        # ASR Backend submenu
        asr_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "ASR Backend", "", ""
        )
        asr_submenu = NSMenu.alloc().init()
        for backend_label, backend_val in [("Whisper (MLX)", "whisper"), ("Paraformer (FunASR)", "paraformer")]:
            bi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                backend_label, "ctxSelectBackend:", ""
            )
            bi.setTarget_(self)
            bi.setRepresentedObject_(backend_val)
            if backend_val == ASR_BACKEND:
                bi.setState_(1)
            asr_submenu.addItem_(bi)
        asr_item.setSubmenu_(asr_submenu)
        menu.addItem_(asr_item)
        self._asr_submenu = asr_submenu

        menu.addItem_(NSMenuItem.separatorItem())
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "terminate:", ""
        )
        menu.addItem_(quit_item)
        self.rounded_view._ctx_menu = menu
        self.rounded_view._app_delegate = self

    def _refresh_mic_submenu(self):
        self._mic_submenu.removeAllItems()
        cfg = _load_config()
        preferred = cfg.get("input_device", "")
        devices = _get_input_devices()
        sys_default_idx = sd.default.device[0]

        # "System Default" option
        default_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "System Default", "ctxSelectMic:", ""
        )
        default_item.setTarget_(self)
        default_item.setRepresentedObject_("")
        if not preferred:
            default_item.setState_(1)  # checkmark
        self._mic_submenu.addItem_(default_item)
        self._mic_submenu.addItem_(NSMenuItem.separatorItem())

        for d in devices:
            label = d["name"]
            if d["index"] == sys_default_idx:
                label += " (default)"
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                label, "ctxSelectMic:", ""
            )
            item.setTarget_(self)
            item.setRepresentedObject_(d["name"])
            if preferred and d["name"] == preferred:
                item.setState_(1)
            self._mic_submenu.addItem_(item)

    @objc.typedSelector(b"v@:@")
    def ctxKeywords_(self, sender):
        subprocess.Popen(["open", KEYWORDS_FILE])

    @objc.typedSelector(b"v@:@")
    def ctxHistory_(self, sender):
        ensure_history_file()
        try:
            subprocess.run(["open", "-a", "TextEdit", HISTORY_FILE], check=True)
        except subprocess.CalledProcessError:
            subprocess.Popen(["open", HISTORY_FILE])

    @objc.typedSelector(b"v@:@")
    def ctxLog_(self, sender):
        subprocess.Popen(["open", "-a", "TextEdit", LOG_FILE])

    @objc.typedSelector(b"v@:@")
    def ctxSelectMic_(self, sender):
        name = sender.representedObject()
        cfg = _load_config()
        if name:
            cfg["input_device"] = name
            print(f"[whisper_dictate] Input device set to: {name}")
        else:
            cfg.pop("input_device", None)
            print("[whisper_dictate] Input device set to: system default")
        _save_config(cfg)

    @objc.typedSelector(b"v@:@")
    def ctxSelectBackend_(self, sender):
        global ASR_BACKEND, _funasr_model
        new_backend = sender.representedObject()
        if new_backend == ASR_BACKEND:
            return
        ASR_BACKEND = new_backend
        # Update checkmarks
        for i in range(self._asr_submenu.numberOfItems()):
            mi = self._asr_submenu.itemAtIndex_(i)
            mi.setState_(1 if mi.representedObject() == new_backend else 0)
        print(f"[whisper_dictate] ASR backend switched to: {ASR_BACKEND}")
        self._update_indicator(LOADING_LABEL, 0.17, 0.17, 0.17, 0.52)
        # Warm up the new backend in background
        def _switch_warmup():
            if new_backend == "paraformer":
                _get_funasr_model()
            warmup_model()
            self._update_indicator(IDLE_LABEL, 0.17, 0.17, 0.17, 0.52)
            print(f"[whisper_dictate] {ASR_BACKEND} backend ready.")
        threading.Thread(target=_switch_warmup, daemon=True).start()

    # ── model warmup ──
    def _warmup(self):
        self._update_indicator(LOADING_LABEL, 0.17, 0.17, 0.17, 0.52)
        warmup_model()
        if self._event_tap_failed:
            print("[whisper_dictate] Model loaded, but event tap failed — keeping error indicator.")
        else:
            self._update_indicator(IDLE_LABEL, 0.17, 0.17, 0.17, 0.52)
            print("[whisper_dictate] Model loaded, ready.")

    # ── FN key monitoring ──
    def _start_event_tap(self):
        def callback(proxy, event_type, event, refcon):
            if event_type in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
                CGEventTapEnable(proxy, True)
                print("[whisper_dictate] Event tap re-enabled.")
                try:
                    cur = CGEventSourceFlagsState(kCGEventSourceStateHIDSystemState)
                    if USE_CTRL_OPT:
                        fn_actual = bool((cur & CTRL_FLAG) and (cur & OPT_FLAG))
                    else:
                        fn_actual = bool(cur & FN_FLAG)
                    if self._fn_held and not fn_actual:
                        print("[whisper_dictate] FN sync: was held but now released, triggering release")
                        self._fn_held = False
                        AppHelper.callAfter(self._on_fn_release)
                    elif not self._fn_held and fn_actual:
                        print("[whisper_dictate] FN sync: now held, triggering press")
                        self._fn_held = True
                        AppHelper.callAfter(self._on_fn_press)
                except Exception as e:
                    print(f"[whisper_dictate] FN sync error: {e}")
                return event

            flags = CGEventGetFlags(event)
            if USE_CTRL_OPT:
                fn_now = bool((flags & CTRL_FLAG) and (flags & OPT_FLAG))
                # For Ctrl+Option: only stop when BOTH are released
                either_held = bool((flags & CTRL_FLAG) or (flags & OPT_FLAG))
                if fn_now and not self._fn_held:
                    self._fn_held = True
                    self._on_fn_press()
                elif not either_held and self._fn_held:
                    # Only trigger release when neither Ctrl nor Option is held
                    self._fn_held = False
                    self._on_fn_release()
            else:
                fn_now = bool(flags & FN_FLAG)
                if fn_now and not self._fn_held:
                    self._fn_held = True
                    self._on_fn_press()
                elif not fn_now and self._fn_held:
                    self._fn_held = False
                    self._on_fn_release()

            return event

        tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            1 << kCGEventFlagsChanged,
            callback,
            None,
        )
        if tap is None:
            print("[whisper_dictate] CGEventTap failed, trying NSEvent fallback...")
            self._setup_nsevent_fallback()
            return

        source = CFMachPortCreateRunLoopSource(None, tap, 0)

        def add_to_main_loop():
            main_loop = CFRunLoopGetMain()
            CFRunLoopAddSource(main_loop, source, kCFRunLoopCommonModes)
            CGEventTapEnable(tap, True)
            print("[whisper_dictate] Event tap active on main run loop.")
        AppHelper.callAfter(add_to_main_loop)

    def _setup_nsevent_fallback(self):
        def add_monitor():
            def handler(event):
                flags = event.modifierFlags()
                if USE_CTRL_OPT:
                    fn_now = bool((flags & CTRL_FLAG) and (flags & OPT_FLAG))
                    either_held = bool((flags & CTRL_FLAG) or (flags & OPT_FLAG))
                    if fn_now and not self._fn_held:
                        self._fn_held = True
                        self._on_fn_press()
                    elif not either_held and self._fn_held:
                        self._fn_held = False
                        self._on_fn_release()
                else:
                    fn_now = bool(flags & (1 << 23))
                    if fn_now and not self._fn_held:
                        self._fn_held = True
                        self._on_fn_press()
                    elif not fn_now and self._fn_held:
                        self._fn_held = False
                        self._on_fn_release()

            monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSFlagsChangedMask, handler
            )
            if monitor is None:
                self._event_tap_failed = True
                print("[whisper_dictate] ERROR: NSEvent fallback also failed.")
                print("  → Grant Accessibility permission to this app.")
                self._update_indicator("⚠️  Need Accessibility", 0.5, 0.2, 0.1)
            else:
                print("[whisper_dictate] NSEvent fallback active.")
        AppHelper.callAfter(add_monitor)

    # ── recording ──
    def _on_fn_press(self):
        if self.is_recording or self.is_transcribing:
            return
        self.is_recording = True
        self._fn_press_time = time.monotonic()
        self.audio_chunks = []
        self._recording_front_app = get_frontmost_app_id()
        self._recording_front_window = get_front_window_title()

        if self._hide_timer:
            self._hide_timer.cancel()
            self._hide_timer = None

        def reset_and_record():
            self._resize_indicator(INDICATOR_WIDTH_RECORDING, INDICATOR_HEIGHT_RECORDING)
            self.indicator.setIgnoresMouseEvents_(False)
            self.copy_btn.setHidden_(True)
            self.label.setHidden_(True)
            self._meter_db_smooth = METER_MIN_DB
            # Show waveform and resize it to match
            self.waveform_view.setFrame_(
                NSMakeRect(0, 0, INDICATOR_WIDTH_RECORDING, INDICATOR_HEIGHT_RECORDING)
            )
            self.waveform_view.relayout()
            self.waveform_view.set_state("recording")
            self.rounded_view.setBgColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.12, 0.12, 0.12, 0.88)
            )
            self._order_indicator_front()
        AppHelper.callAfter(reset_and_record)

        def audio_callback(indata, frames, time_info, status):
            self.audio_chunks.append(indata.copy())
            mono = indata[:, 0]
            rms = float(np.sqrt(np.mean(np.square(mono))))
            db = 20.0 * np.log10(max(rms, 1e-7))
            self._update_recording_meter(db)

        dev_idx = _resolve_input_device()
        self.stream = sd.InputStream(
            device=dev_idx,
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=audio_callback,
        )
        self.stream.start()
        print("[whisper_dictate] Recording...")

        if self._recording_timeout:
            self._recording_timeout.cancel()

        def _force_stop_recording():
            if self.is_recording:
                print(f"[whisper_dictate] WATCHDOG: recording timeout ({RECORDING_TIMEOUT_SEC}s), forcing stop")
                def release_on_main():
                    self._fn_held = False
                    self._on_fn_release()
                AppHelper.callAfter(release_on_main)

        self._recording_timeout = threading.Timer(RECORDING_TIMEOUT_SEC, _force_stop_recording)
        self._recording_timeout.daemon = True
        self._recording_timeout.start()

    def _on_fn_release(self):
        if not self.is_recording:
            return
        self.is_recording = False
        hold_duration = time.monotonic() - self._fn_press_time

        if self._recording_timeout:
            self._recording_timeout.cancel()
            self._recording_timeout = None

        # Move stream ref off self — background thread will stop/close it
        stream_ref = self.stream
        self.stream = None

        if hold_duration < FN_MIN_HOLD_SEC:
            # Ghost press (modifier key re-assertion) — discard silently
            self.audio_chunks = []
            if stream_ref:
                def _close(s):
                    try:
                        s.stop()
                        s.close()
                    except Exception:
                        pass
                threading.Thread(target=_close, args=(stream_ref,), daemon=True).start()
            self._update_indicator(IDLE_LABEL, 0.17, 0.17, 0.17, 0.52)
            return

        # Normal release — stream stop + transcription all in background thread
        self.is_transcribing = True
        # Switch waveform to shimmer animation for transcribing
        self.waveform_view.set_state("transcribing")

        if self._asr_watchdog:
            self._asr_watchdog.cancel()

        def _asr_timeout():
            if self.is_transcribing:
                print(f"[whisper_dictate] WATCHDOG: ASR timeout ({ASR_WATCHDOG_SEC}s), resetting")
                self.is_transcribing = False
                def _reset():
                    self.waveform_view.set_state("idle")
                    self.label.setHidden_(False)
                    self._update_indicator(IDLE_LABEL, 0.17, 0.17, 0.17, 0.52)
                AppHelper.callAfter(_reset)

        self._asr_watchdog = threading.Timer(ASR_WATCHDOG_SEC, _asr_timeout)
        self._asr_watchdog.daemon = True
        self._asr_watchdog.start()

        threading.Thread(target=self._transcribe, args=(stream_ref,), daemon=True).start()

    def _transcribe(self, stream_ref=None):
        # Stop/close audio stream in background thread (not blocking main RunLoop)
        if stream_ref:
            try:
                stream_ref.stop()
                stream_ref.close()
            except Exception as e:
                print(f"[whisper_dictate] Stream close error: {e}")

        tmp = None
        try:
            t_start = time.monotonic()
            # Detach and clear shared buffer early to release memory pressure.
            chunks = self.audio_chunks
            self.audio_chunks = []
            if not chunks:
                print("[whisper_dictate] No audio captured.")
                return
            audio = np.concatenate(chunks, axis=0)
            chunks.clear()
            raw_duration = len(audio) / SAMPLE_RATE
            audio, trimmed_tail_sec = _trim_trailing_silence(audio)
            duration = len(audio) / SAMPLE_RATE
            print(
                f"[whisper_dictate] Transcribing {duration:.1f}s audio "
                f"(raw={raw_duration:.1f}s, tail_trim={trimmed_tail_sec:.2f}s) "
                f"[backend={ASR_BACKEND}]..."
            )

            if duration < MIN_AUDIO_DURATION_SEC:
                print(
                    "[whisper_dictate] Too short after trim, skipping. "
                    f"(effective={duration:.2f}s, raw={raw_duration:.2f}s)"
                )
                return

            tmp = _secure_tmpfile()
            sf.write(tmp, audio, SAMPLE_RATE)

            self.keywords = load_keywords()
            kw_len = len(self.keywords)
            if kw_len > KEYWORDS_MAX_CHARS:
                self.keywords = self.keywords[:KEYWORDS_MAX_CHARS]
                print(
                    f"[whisper_dictate] Keywords trimmed: "
                    f"{kw_len} -> {len(self.keywords)} chars"
                )

            t_asr = time.monotonic()

            if ASR_BACKEND == "paraformer":
                use_prompt = False
                m = _get_funasr_model()
                res = m.generate(input=tmp)
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
                use_prompt = bool(self.keywords) and self._disable_prompt_rounds <= 0
                if use_prompt:
                    kwargs["initial_prompt"] = self.keywords
                elif self._disable_prompt_rounds > 0:
                    self._disable_prompt_rounds -= 1
                    print(
                        f"[whisper_dictate] Prompt temporarily disabled, "
                        f"rounds left={self._disable_prompt_rounds}"
                    )
                result = mlx_whisper.transcribe(tmp, **kwargs)
                raw_text = result.get("text", "").strip()

            t_asr_done = time.monotonic()
            asr_sec = t_asr_done - t_asr
            rtf = asr_sec / max(duration, 0.1)
            slow_asr = (
                asr_sec >= ASR_SLOW_THRESHOLD_SEC or rtf >= ASR_SLOW_RTF_THRESHOLD
            )
            if slow_asr:
                self._slow_asr_streak += 1
            else:
                self._slow_asr_streak = 0
            if self._slow_asr_streak >= ASR_SLOW_STREAK_TRIGGER:
                self._disable_prompt_rounds = max(
                    self._disable_prompt_rounds, PROMPT_DISABLE_ROUNDS_ON_SLOW
                )
                print(
                    f"[whisper_dictate] Slow ASR streak={self._slow_asr_streak}, "
                    f"disable prompt for next {self._disable_prompt_rounds} rounds. "
                    f"(asr={asr_sec:.2f}s, rtf={rtf:.2f})"
                )
            os.unlink(tmp)
            tmp = None

            if raw_text:
                processed = postprocess_fast(raw_text)
                t_post = time.monotonic()
                print(f"[whisper_dictate] raw → {raw_text}")
                print(f"[whisper_dictate] out → {processed}")

                self._last_text = processed
                current_front_app = get_frontmost_app_id()
                same_app = (
                    bool(self._recording_front_app)
                    and current_front_app == self._recording_front_app
                )
                current_front_window = ""
                if same_app:
                    # Only do expensive window-title lookup when app is unchanged.
                    current_front_window = get_front_window_title()
                window_title_changed = (
                    bool(self._recording_front_window)
                    and bool(current_front_window)
                    and _normalize_window_title(current_front_window)
                    != _normalize_window_title(self._recording_front_window)
                )

                if same_app and not window_title_changed:
                    paste_text(processed)
                    t_end = time.monotonic()
                    self._show_result(processed)
                else:
                    t_end = time.monotonic()
                    self._show_copy_prompt(processed)
                    print(
                        "[whisper_dictate] Window changed "
                        f"(app: {self._recording_front_app} -> {current_front_app}, "
                        f"window: {self._recording_front_window!r} -> {current_front_window!r}), "
                        "showing copy prompt."
                    )

                save_history(raw_text, processed, duration)
                rss_mb_now = get_rss_mb()
                kw_terms = len([x for x in self.keywords.split(",") if x.strip()]) if self.keywords else 0
                print(
                    f"[BENCH] audio={duration:.1f}s | asr={asr_sec:.2f}s | "
                    f"rtf={rtf:.2f} | post={t_post-t_asr_done:.2f}s | "
                    f"paste={t_end-t_post:.2f}s | total={t_end-t_start:.2f}s | "
                    f"rss={rss_mb_now:.0f}MB | kw_chars={len(self.keywords)} | "
                    f"kw_terms={kw_terms} | prompt={'on' if use_prompt else 'off'} | "
                    f"slow_streak={self._slow_asr_streak}"
                )

                self.is_transcribing = False
                return
            else:
                print("[whisper_dictate] No speech detected.")
        except Exception as e:
            print(f"[whisper_dictate] Error: {e}")
        finally:
            if self._asr_watchdog:
                self._asr_watchdog.cancel()
                self._asr_watchdog = None
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
            self.audio_chunks = []
            now = time.time()
            if now - self._last_memory_maintenance_ts >= MEMORY_MAINTENANCE_INTERVAL_SEC:
                run_memory_maintenance()
                self._last_memory_maintenance_ts = now
                rss_mb = get_rss_mb()
                if rss_mb > 0:
                    print(f"[whisper_dictate] RSS: {rss_mb:.0f} MB (maintenance)")
                    if rss_mb >= MEMORY_SOFT_LIMIT_MB:
                        print(
                            f"[whisper_dictate] RSS {rss_mb:.0f} MB > "
                            f"{MEMORY_SOFT_LIMIT_MB} MB, auto-restarting..."
                        )
                        self.is_transcribing = False
                        self._auto_restart()
                        return
            self.is_transcribing = False
            if not self._last_text or self.label.stringValue().startswith("✎"):
                self._update_indicator(IDLE_LABEL, 0.17, 0.17, 0.17, 0.52)

    def _auto_restart(self):
        """Relaunch to reclaim memory."""
        app_path = os.path.expanduser("~/Applications/WhisperDictate.app")
        if os.path.exists(app_path):
            subprocess.Popen(
                ["bash", "-c", "sleep 1 && open \"$1\"", "_", app_path],
                start_new_session=True,
            )
            os._exit(0)
        else:
            python = sys.executable
            os.execv(python, [python, "-u"] + sys.argv)


# ── main ───────────────────────────────────────────────────
def _acquire_lock():
    """Ensure only one instance runs. Exit if another is already active."""
    lock_path = os.path.expanduser("~/.config/whisper/whisper_dictate.lock")
    try:
        import fcntl
        _ensure_private_dir(lock_path)
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        lock_fd = os.fdopen(fd, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        return lock_fd          # keep fd alive to hold the lock
    except (IOError, OSError):
        print("[whisper_dictate] Another instance is already running. Exiting.")
        sys.exit(0)


def main():
    _acquire_lock()
    _ensure_private_dir(KEYWORDS_FILE)
    _rotate_log_if_needed()
    ensure_history_file()
    _set_private(HISTORY_FILE)
    _set_private(LOG_FILE)
    if not os.path.exists(KEYWORDS_FILE):
        with open(KEYWORDS_FILE, "w") as f:
            f.write("NVIDIA, Tesla, S&P 500, Bitcoin, Apple, Microsoft, Google")
    _set_private(KEYWORDS_FILE)

    hotkey_name = "Ctrl+Option" if USE_CTRL_OPT else "FN"
    print(f"[whisper_dictate] Starting v2... (hold {hotkey_name} to talk)")
    print(f"[whisper_dictate] Keywords: {KEYWORDS_FILE}")
    print(f"[whisper_dictate] History: {HISTORY_FILE}")

    app = NSApplication.sharedApplication()
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)

    signal.signal(signal.SIGINT, lambda *_: app.terminate_(None))

    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
