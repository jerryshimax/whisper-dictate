"""NSPanel floating indicator and RoundedView background."""
from __future__ import annotations

import logging

import objc
from AppKit import (
    NSBezierPath,
    NSColor,
    NSMakeRect,
    NSMenu,
    NSPanel,
    NSScreen,
    NSView,
    NSWindowStyleMaskBorderless,
    NSBackingStoreBuffered,
)
from Quartz import kCGFloatingWindowLevel

from whisper_dictate.config import INDICATOR_CORNER_RADIUS

logger = logging.getLogger("whisper_dictate.ui.indicator")


class RoundedView(NSView):
    """NSView subclass with rounded corners and background color."""

    _bg_color = None

    def initWithFrame_(self, frame):
        self = objc.super(RoundedView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._bg_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.1, 0.1, 0.1, 0.85
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
