"""Clipboard snapshot, paste, and restore operations.

Uses native macOS APIs (NSPasteboard + CGEvent) instead of subprocess
calls (pbcopy/osascript) for dramatically lower latency.
"""
from __future__ import annotations

import logging
import threading
import time

from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString
from Foundation import NSData
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventSetFlags,
    CGEventPost,
    kCGHIDEventTap,
    kCGEventFlagMaskCommand,
)

from whisper_dictate.config import CLIPBOARD_RESTORE_DELAY_SEC

logger = logging.getLogger("whisper_dictate.clipboard")

# macOS keycode for 'v'
_V_KEYCODE = 9


def _snapshot_clipboard() -> tuple[int, list[dict[str, bytes]]]:
    """Capture current clipboard contents. Returns (changeCount, items)."""
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
                logger.warning("Failed to snapshot paste type %s", paste_type, exc_info=True)
                continue
        if item_data:
            snapshot.append(item_data)
    return int(pb.changeCount()), snapshot


def _restore_clipboard(snapshot: list[dict[str, bytes]]) -> None:
    """Restore clipboard to a previously captured snapshot."""
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


def _set_clipboard_text(text: str) -> None:
    """Write text to clipboard via NSPasteboard (no subprocess)."""
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)


def _simulate_cmd_v() -> None:
    """Simulate Cmd+V keystroke via CGEvent (no osascript subprocess)."""
    event_down = CGEventCreateKeyboardEvent(None, _V_KEYCODE, True)
    CGEventSetFlags(event_down, kCGEventFlagMaskCommand)
    event_up = CGEventCreateKeyboardEvent(None, _V_KEYCODE, False)
    CGEventSetFlags(event_up, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, event_down)
    CGEventPost(kCGHIDEventTap, event_up)


def paste_text(text: str) -> None:
    """Copy text to clipboard, paste via Cmd+V, then restore original clipboard."""
    snapshot = None
    previous_change_count = None
    try:
        previous_change_count, snapshot = _snapshot_clipboard()
    except Exception:
        logger.warning("Clipboard snapshot failed", exc_info=True)

    t0 = time.monotonic()
    _set_clipboard_text(text)
    _simulate_cmd_v()
    logger.debug("Native paste: %.1fms", (time.monotonic() - t0) * 1000)

    if snapshot is None or previous_change_count is None:
        return

    def _restore_if_unchanged():
        try:
            pb = NSPasteboard.generalPasteboard()
            expected = previous_change_count + 1
            if pb.changeCount() != expected:
                return
            _restore_clipboard(snapshot)
        except Exception:
            logger.warning("Clipboard restore failed", exc_info=True)

    timer = threading.Timer(CLIPBOARD_RESTORE_DELAY_SEC, _restore_if_unchanged)
    timer.daemon = True
    timer.start()
