"""Right-click context menu for the floating indicator."""
from __future__ import annotations

import logging

import sounddevice as sd
from AppKit import NSMenu, NSMenuItem

from whisper_dictate.audio import _get_input_devices
from whisper_dictate.config import load_user_config

logger = logging.getLogger("whisper_dictate.ui.context_menu")


def build_context_menu(delegate) -> tuple[NSMenu, NSMenu]:
    """Build the right-click context menu.

    Returns (menu, mic_submenu) so the delegate can store references.
    """
    menu = NSMenu.alloc().init()
    for title, action in [
        ("Edit Keywords", "ctxKeywords:"),
        ("Open History", "ctxHistory:"),
        ("Open Log", "ctxLog:"),
    ]:
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            title, action, ""
        )
        item.setTarget_(delegate)
        menu.addItem_(item)

    menu.addItem_(NSMenuItem.separatorItem())

    # Input Device submenu
    mic_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Input Device", "", ""
    )
    mic_submenu = NSMenu.alloc().init()
    mic_item.setSubmenu_(mic_submenu)
    menu.addItem_(mic_item)

    menu.addItem_(NSMenuItem.separatorItem())
    quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "Quit", "terminate:", ""
    )
    menu.addItem_(quit_item)

    return menu, mic_submenu


def refresh_mic_submenu(submenu: NSMenu, delegate) -> None:
    """Rebuild the Input Device submenu with current devices."""
    submenu.removeAllItems()
    cfg = load_user_config()
    preferred = cfg.get("input_device", "")
    devices = _get_input_devices()
    sys_default_idx = sd.default.device[0]

    # "System Default" option
    default_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        "System Default", "ctxSelectMic:", ""
    )
    default_item.setTarget_(delegate)
    default_item.setRepresentedObject_("")
    if not preferred:
        default_item.setState_(1)  # checkmark
    submenu.addItem_(default_item)
    submenu.addItem_(NSMenuItem.separatorItem())

    for d in devices:
        label = d["name"]
        if d["index"] == sys_default_idx:
            label += " (default)"
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            label, "ctxSelectMic:", ""
        )
        item.setTarget_(delegate)
        item.setRepresentedObject_(d["name"])
        if preferred and d["name"] == preferred:
            item.setState_(1)
        submenu.addItem_(item)
