"""CALayer animated waveform bars (WaveformView class)."""
from __future__ import annotations

import ctypes as _ctypes
import threading

import objc
from AppKit import NSView
from PyObjCTools import AppHelper

from whisper_dictate.config import (
    METER_MAX_DB,
    METER_MIN_DB,
    WAVEFORM_BAR_GAP,
    WAVEFORM_BAR_MAX_H,
    WAVEFORM_BAR_MIN_H,
    WAVEFORM_BAR_RADIUS,
    WAVEFORM_BAR_WIDTH,
    WAVEFORM_NUM_BARS,
)

# Core Animation loader
_ca_lib = _ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/QuartzCore.framework/QuartzCore"
)
_ca_lib.CACurrentMediaTime.restype = _ctypes.c_double

import objc as _objc_loader  # noqa: E402

_QuartzCore = _objc_loader.loadBundle(
    "QuartzCore",
    globals(),
    "/System/Library/Frameworks/QuartzCore.framework",
)
# Now CALayer, CATransaction, CABasicAnimation are in module scope
from Quartz import CGColorCreateGenericRGB  # noqa: E402


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
            bar.setBackgroundColor_(CGColorCreateGenericRGB(1.0, 0.15, 0.1, 0.4))
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
        CATransaction.setAnimationDuration_(0.05)
        for i, bar in enumerate(self._bars):
            ratio = self._levels[i]
            h = WAVEFORM_BAR_MIN_H + ratio * (WAVEFORM_BAR_MAX_H - WAVEFORM_BAR_MIN_H)
            x = start_x + i * (WAVEFORM_BAR_WIDTH + WAVEFORM_BAR_GAP)
            y = center_y - h / 2.0
            bar.setFrame_(((x, y), (WAVEFORM_BAR_WIDTH, h)))
            # Red bars — vivid, brightness responds to volume
            a = 0.5 + 0.5 * ratio
            r = 1.0
            g = 0.15 * (1.0 - ratio)
            b = 0.1 * (1.0 - ratio)
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
            bar.setBackgroundColor_(CGColorCreateGenericRGB(1.0, 0.15, 0.1, 0.4))
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
            bar.setBackgroundColor_(CGColorCreateGenericRGB(1.0, 0.15, 0.1, 0.5))
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
            bar.setBackgroundColor_(CGColorCreateGenericRGB(0.3, 0.85, 0.45, 0.9))
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
