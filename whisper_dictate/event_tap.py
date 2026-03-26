"""CGEventTap + NSEvent fallback for hotkey monitoring."""
from __future__ import annotations

import logging
from typing import Callable

from AppKit import NSEvent, NSFlagsChangedMask
from Quartz import (
    CGEventGetFlags,
    CGEventSourceFlagsState,
    CGEventTapCreate,
    CGEventTapEnable,
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    kCFRunLoopCommonModes,
    kCGEventFlagsChanged,
    kCGEventSourceStateHIDSystemState,
    kCGEventTapDisabledByTimeout,
    kCGEventTapDisabledByUserInput,
    kCGEventTapOptionListenOnly,
    kCGHeadInsertEventTap,
    kCGSessionEventTap,
)
from CoreFoundation import CFRunLoopGetMain
from PyObjCTools import AppHelper

from whisper_dictate.config import CTRL_FLAG, FN_FLAG, OPT_FLAG, USE_CTRL_OPT

logger = logging.getLogger("whisper_dictate.event_tap")

OnPress = Callable[[], None]
OnRelease = Callable[[], None]


class EventTapState:
    """Mutable state shared between the event tap callback and the app."""

    def __init__(self) -> None:
        self.fn_held = False
        self.event_tap_failed = False


def setup_event_tap(
    state: EventTapState,
    on_press: OnPress,
    on_release: OnRelease,
) -> None:
    """Install a CGEventTap (with NSEvent fallback) for hotkey detection.

    Runs the tap setup on a background thread; the actual tap lives on the main run loop.
    """

    def callback(proxy, event_type, event, refcon):
        if event_type in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
            CGEventTapEnable(proxy, True)
            logger.info("Event tap re-enabled.")
            try:
                cur = CGEventSourceFlagsState(kCGEventSourceStateHIDSystemState)
                if USE_CTRL_OPT:
                    fn_actual = bool((cur & CTRL_FLAG) and (cur & OPT_FLAG))
                else:
                    fn_actual = bool(cur & FN_FLAG)
                if state.fn_held and not fn_actual:
                    logger.info("FN sync: was held but now released, triggering release")
                    state.fn_held = False
                    AppHelper.callAfter(on_release)
                elif not state.fn_held and fn_actual:
                    logger.info("FN sync: now held, triggering press")
                    state.fn_held = True
                    AppHelper.callAfter(on_press)
            except Exception:
                logger.error("FN sync error", exc_info=True)
            return event

        flags = CGEventGetFlags(event)
        if USE_CTRL_OPT:
            fn_now = bool((flags & CTRL_FLAG) and (flags & OPT_FLAG))
            either_held = bool((flags & CTRL_FLAG) or (flags & OPT_FLAG))
            if fn_now and not state.fn_held:
                state.fn_held = True
                on_press()
            elif not either_held and state.fn_held:
                state.fn_held = False
                on_release()
        else:
            fn_now = bool(flags & FN_FLAG)
            if fn_now and not state.fn_held:
                state.fn_held = True
                on_press()
            elif not fn_now and state.fn_held:
                state.fn_held = False
                on_release()

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
        logger.warning("CGEventTap failed, trying NSEvent fallback...")
        _setup_nsevent_fallback(state, on_press, on_release)
        return

    source = CFMachPortCreateRunLoopSource(None, tap, 0)

    def add_to_main_loop():
        main_loop = CFRunLoopGetMain()
        CFRunLoopAddSource(main_loop, source, kCFRunLoopCommonModes)
        CGEventTapEnable(tap, True)
        logger.info("Event tap active on main run loop.")

    AppHelper.callAfter(add_to_main_loop)


def _setup_nsevent_fallback(
    state: EventTapState,
    on_press: OnPress,
    on_release: OnRelease,
) -> None:
    """Fallback using NSEvent global monitor when CGEventTap fails."""

    def add_monitor():
        def handler(event):
            flags = event.modifierFlags()
            if USE_CTRL_OPT:
                fn_now = bool((flags & CTRL_FLAG) and (flags & OPT_FLAG))
                either_held = bool((flags & CTRL_FLAG) or (flags & OPT_FLAG))
                if fn_now and not state.fn_held:
                    state.fn_held = True
                    on_press()
                elif not either_held and state.fn_held:
                    state.fn_held = False
                    on_release()
            else:
                fn_now = bool(flags & (1 << 23))
                if fn_now and not state.fn_held:
                    state.fn_held = True
                    on_press()
                elif not fn_now and state.fn_held:
                    state.fn_held = False
                    on_release()

        monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSFlagsChangedMask, handler
        )
        if monitor is None:
            state.event_tap_failed = True
            logger.error("NSEvent fallback also failed. Grant Accessibility permission to this app.")
        else:
            logger.info("NSEvent fallback active.")

    AppHelper.callAfter(add_monitor)
