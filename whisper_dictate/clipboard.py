"""Clipboard snapshot, paste, and restore operations."""
from __future__ import annotations

import logging
import subprocess
import threading

from AppKit import NSPasteboard, NSPasteboardItem
from Foundation import NSData

from whisper_dictate.config import CLIPBOARD_RESTORE_DELAY_SEC

logger = logging.getLogger("whisper_dictate.clipboard")


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


def paste_text(text: str) -> None:
    """Copy text to clipboard, paste via Cmd+V, then restore original clipboard."""
    snapshot = None
    previous_change_count = None
    try:
        previous_change_count, snapshot = _snapshot_clipboard()
    except Exception:
        logger.warning("Clipboard snapshot failed", exc_info=True)

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
        except Exception:
            logger.warning("Clipboard restore failed", exc_info=True)

    timer = threading.Timer(CLIPBOARD_RESTORE_DELAY_SEC, _restore_if_unchanged)
    timer.daemon = True
    timer.start()
