"""AppDelegate (thin orchestrator), main() entry point, and instance lock."""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time

import numpy as np
import objc
import sounddevice as sd
import soundfile as sf
from AppKit import (
    NSApplication,
    NSApp,
    NSButton,
    NSBezelStyleInline,
    NSColor,
    NSFont,
    NSMakeRect,
    NSObject,
    NSPanel,
    NSScreen,
    NSSound,
    NSTextField,
    NSWindowStyleMaskBorderless,
    NSBackingStoreBuffered,
    NSApplicationActivationPolicyAccessory,
)
from Quartz import kCGFloatingWindowLevel
from PyObjCTools import AppHelper

from whisper_dictate.config import (
    ASR_SLOW_RTF_THRESHOLD,
    ASR_SLOW_STREAK_TRIGGER,
    ASR_SLOW_THRESHOLD_SEC,
    ASR_WATCHDOG_SEC,
    COPY_READY_LABEL,
    DONE_LABEL,
    FN_MIN_HOLD_SEC,
    TAP_MAX_HOLD_SEC,
    HISTORY_FILE,
    IDLE_LABEL,
    INDICATOR_BOTTOM_MARGIN,
    INDICATOR_HEIGHT,
    INDICATOR_HEIGHT_COPY,
    INDICATOR_HEIGHT_RECORDING,
    INDICATOR_WIDTH_COPY,
    INDICATOR_WIDTH_NORMAL,
    INDICATOR_WIDTH_RECORDING,
    INDICATOR_WIDTH_RESULT,
    KEYWORDS_FILE,
    KEYWORDS_MAX_CHARS,
    LLM_SKIP_WORD_THRESHOLD,
    LOADING_LABEL,
    LOG_FILE,
    MEMORY_MAINTENANCE_INTERVAL_SEC,
    MEMORY_SOFT_LIMIT_MB,
    METER_EMA_ALPHA,
    METER_MIN_DB,
    METER_UPDATE_INTERVAL_SEC,
    MIN_AUDIO_DURATION_SEC,
    PROMPT_DISABLE_ROUNDS_ON_SLOW,
    RECORDING_TIMEOUT_SEC,
    RESULT_DISPLAY_SECONDS,
    SAMPLE_RATE,
    USE_CTRL_OPT,
    _ensure_private_dir,
    _secure_tmpfile,
    _set_private,
    load_keywords,
    load_user_config,
    save_user_config,
)
from whisper_dictate.logging_setup import setup_logging
from whisper_dictate.postprocessor import postprocess_fast
from whisper_dictate.audio import _trim_trailing_silence, _resolve_input_device
from whisper_dictate.clipboard import paste_text
from whisper_dictate.history import save_history, cleanup_history, ensure_history_file, suggest_keywords
from whisper_dictate.macos import (
    get_frontmost_app_id,
    get_front_window_title,
    get_rss_mb,
    run_memory_maintenance,
    _normalize_window_title,
)
from whisper_dictate.asr import warmup_model, warmup_fast_model, transcribe
from whisper_dictate.llm_polish import warmup_llm, polish_text
from whisper_dictate.event_tap import setup_event_tap, EventTapState
from whisper_dictate.streaming import StreamingTranscriber
from whisper_dictate.context import get_window_context_keywords
from whisper_dictate.ui.indicator import RoundedView
from whisper_dictate.ui.waveform import WaveformView
from whisper_dictate.ui.context_menu import build_context_menu, refresh_mic_submenu

logger = logging.getLogger("whisper_dictate.app")


class AppDelegate(NSObject):
    def init(self):
        self = objc.super(AppDelegate, self).init()
        self.is_recording = False
        self.is_transcribing = False
        self.audio_chunks = []
        self.stream = None
        self.keywords = load_keywords()
        self.indicator = None
        self.label = None
        self.rounded_view = None
        self.copy_btn = None
        self.status_item = None
        self._hide_timer = None
        self._last_text = ""
        self._meter_last_update = 0.0
        self._meter_db_smooth = METER_MIN_DB
        self._recording_front_app = ""
        self._recording_front_window = ""
        self._pending_copy_text = ""
        self._last_memory_maintenance_ts = 0.0
        self._slow_asr_streak = 0
        self._disable_prompt_rounds = 0
        self._fn_press_time = 0.0
        self._toggle_recording = False  # tap-to-toggle mode active
        self._asr_watchdog = None
        self._recording_timeout = None
        self.waveform_view = None
        self._mic_submenu = None
        self._event_tap_state = EventTapState()
        self._streamer = None  # StreamingTranscriber instance during recording
        self._clipboard_snapshot = None  # pre-captured clipboard for parallel paste
        self._clipboard_change_count = None
        return self

    def applicationDidFinishLaunching_(self, notification):
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        self._create_indicator()
        self._setup_right_click_menu()

        cleanup_history()

        threading.Thread(target=self._warmup, daemon=True).start()
        threading.Thread(
            target=setup_event_tap,
            args=(self._event_tap_state, self._on_fn_press, self._on_fn_release),
            daemon=True,
        ).start()

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
        self.label.setFont_(NSFont.systemFontOfSize_weight_(11.0, 0.25))
        self.label.setTextColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.92, 0.92, 0.92, 0.9)
        )
        self.label.setAlignment_(1)  # center
        label_w = INDICATOR_WIDTH_NORMAL - 12
        label_h = 14
        label_x = 6
        label_y = (INDICATOR_HEIGHT - label_h) / 2
        self.label.setFrame_(NSMakeRect(label_x, label_y, label_w, label_h))

        self.copy_btn = NSButton.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 1))
        self.copy_btn.setTitle_("\U0001f4cb")
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

        db_clamped = max(METER_MIN_DB, min(0.0, db))
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
            self.label.setFont_(NSFont.systemFontOfSize_weight_(11.0, 0.25))
            label_w = INDICATOR_WIDTH_RESULT - 12
            label_h = 14
            label_x = 6
            label_y = (INDICATOR_HEIGHT - label_h) / 2
            self.label.setFrame_(NSMakeRect(label_x, label_y, label_w, label_h))
            self.label.setAlignment_(1)  # center
            self.label.setStringValue_(DONE_LABEL)
            self.label.setTextColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.85, 0.45, 1.0)
            )

            self.rounded_view.setBgColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    0.1, 0.1, 0.1, 0.55
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
            self.label.setFont_(NSFont.systemFontOfSize_weight_(11.0, 0.25))
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
                logger.warning("setContentTintColor_ not available", exc_info=True)
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
            self.label.setFont_(NSFont.systemFontOfSize_weight_(11.0, 0.25))
            label_w = INDICATOR_WIDTH_NORMAL - 12
            label_h = 14
            label_x = 6
            label_y = (INDICATOR_HEIGHT - label_h) / 2
            self.label.setFrame_(NSMakeRect(label_x, label_y, label_w, label_h))
            self.label.setAlignment_(1)  # center
            self.label.setStringValue_(IDLE_LABEL)
            self.label.setTextColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.92, 0.92, 0.92, 0.9)
            )
            self.rounded_view.setBgColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    0.1, 0.1, 0.1, 0.55
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

            self.label.setStringValue_("\u2713 Copied")
            if self._hide_timer:
                self._hide_timer.cancel()
            self._hide_timer = threading.Timer(1.5, self._reset_indicator)
            self._hide_timer.daemon = True
            self._hide_timer.start()

    # ── right-click context menu on floating indicator ──
    def _setup_right_click_menu(self):
        menu, mic_submenu = build_context_menu(self)
        self._mic_submenu = mic_submenu
        self.rounded_view._ctx_menu = menu
        self.rounded_view._app_delegate = self

    def _refresh_mic_submenu(self):
        refresh_mic_submenu(self._mic_submenu, self)

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
        cfg = load_user_config()
        if name:
            cfg["input_device"] = name
            logger.info("Input device set to: %s", name)
        else:
            cfg.pop("input_device", None)
            logger.info("Input device set to: system default")
        save_user_config(cfg)

    # ── sound feedback ──
    def _play_sound(self, name: str):
        """Play a system sound by name (e.g. 'Tink', 'Pop')."""
        def play():
            sound = NSSound.soundNamed_(name)
            if sound:
                sound.play()
        AppHelper.callAfter(play)

    # ── model warmup ──
    def _warmup(self):
        self._update_indicator(LOADING_LABEL, 0.1, 0.1, 0.1, 0.55)
        warmup_model()
        warmup_llm()  # pre-load punctuation LLM in background
        # Warm fast model in background (non-blocking)
        threading.Thread(target=warmup_fast_model, daemon=True).start()
        if self._event_tap_state.event_tap_failed:
            logger.warning("Model loaded, but event tap failed — keeping error indicator.")
            self._update_indicator("\u26a0\ufe0f  Need Accessibility", 0.5, 0.2, 0.1)
        else:
            self._update_indicator(IDLE_LABEL, 0.1, 0.1, 0.1, 0.55)
            logger.info("Model loaded, ready.")

    # ── recording ──
    def _on_fn_press(self):
        if self.is_transcribing:
            return
        # Second tap in toggle mode → stop recording
        if self.is_recording and self._toggle_recording:
            self._toggle_recording = False
            self._fn_press_time = time.monotonic()  # reset so release is a no-op
            self._stop_and_transcribe()
            return
        if self.is_recording:
            return
        self.is_recording = True
        self._fn_press_time = time.monotonic()
        self.audio_chunks = []

        # ── FAST PATH: start recording immediately ──
        # Init fields that background thread will populate (safe defaults)
        self._recording_front_window = ""
        self._clipboard_snapshot = None
        self._clipboard_change_count = None
        self.keywords = ""

        # Get app ID via NSWorkspace (instant, no subprocess)
        self._recording_front_app = get_frontmost_app_id()

        # Start streaming transcriber with no keywords (updated by background thread)
        self._streamer = StreamingTranscriber(keywords="", use_prompt=False)
        self._streamer.start()

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
            chunk = indata.copy()
            self.audio_chunks.append(chunk)
            # Feed streaming transcriber for VAD-chunked ASR
            if self._streamer:
                self._streamer.feed(chunk)
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
        self._play_sound("Tink")
        logger.info("Recording...")

        # ── SLOW PATH: gather context in background ──
        # Window title, keywords, clipboard, context all happen in parallel
        # while audio is already being captured.
        def _gather_context():
            t0 = time.monotonic()
            self._recording_front_window = get_front_window_title()

            # Feature 4: Context-aware keywords from active app
            context_kw = get_window_context_keywords(self._recording_front_app)

            # Feature 5: Pre-snapshot clipboard
            self._clipboard_snapshot = None
            self._clipboard_change_count = None
            try:
                from whisper_dictate.clipboard import _snapshot_clipboard
                self._clipboard_change_count, self._clipboard_snapshot = _snapshot_clipboard()
            except Exception:
                logger.debug("Pre-snapshot clipboard failed (non-fatal)", exc_info=True)

            # Prepare keywords for streaming transcriber
            self.keywords = load_keywords()
            kw_len = len(self.keywords)
            if kw_len > KEYWORDS_MAX_CHARS:
                self.keywords = self.keywords[:KEYWORDS_MAX_CHARS]
            # Append context keywords
            if context_kw:
                combined = self.keywords + ", " + context_kw if self.keywords else context_kw
                if len(combined) <= KEYWORDS_MAX_CHARS:
                    self.keywords = combined
                    logger.info("Context keywords appended: %s", context_kw)

            use_prompt = bool(self.keywords) and self._disable_prompt_rounds <= 0

            # Update the already-running streamer with keywords
            if self._streamer and use_prompt:
                self._streamer.update_keywords(self.keywords, use_prompt=True)

            logger.info("Background context gathered in %.0fms", (time.monotonic() - t0) * 1000)

        threading.Thread(target=_gather_context, daemon=True).start()

        if self._recording_timeout:
            self._recording_timeout.cancel()

        def _force_stop_recording():
            if self.is_recording:
                logger.warning(
                    "WATCHDOG: recording timeout (%ss), forcing stop",
                    RECORDING_TIMEOUT_SEC,
                )
                def release_on_main():
                    self._event_tap_state.fn_held = False
                    self._on_fn_release()
                AppHelper.callAfter(release_on_main)

        self._recording_timeout = threading.Timer(RECORDING_TIMEOUT_SEC, _force_stop_recording)
        self._recording_timeout.daemon = True
        self._recording_timeout.start()

    def _stop_and_transcribe(self):
        """Stop recording and kick off transcription (shared by hold and toggle)."""
        self.is_recording = False

        if self._recording_timeout:
            self._recording_timeout.cancel()
            self._recording_timeout = None

        stream_ref = self.stream
        self.stream = None

        self.is_transcribing = True
        self.waveform_view.set_state("transcribing")

        if self._asr_watchdog:
            self._asr_watchdog.cancel()

        def _asr_timeout():
            if self.is_transcribing:
                logger.warning("WATCHDOG: ASR timeout (%ss), resetting", ASR_WATCHDOG_SEC)
                self.is_transcribing = False
                def _reset():
                    self.waveform_view.set_state("idle")
                    self.label.setHidden_(False)
                    self._update_indicator(IDLE_LABEL, 0.1, 0.1, 0.1, 0.55)
                AppHelper.callAfter(_reset)

        self._asr_watchdog = threading.Timer(ASR_WATCHDOG_SEC, _asr_timeout)
        self._asr_watchdog.daemon = True
        self._asr_watchdog.start()

        threading.Thread(target=self._transcribe, args=(stream_ref,), daemon=True).start()

    def _on_fn_release(self):
        if not self.is_recording:
            return
        # In toggle mode, ignore releases (stop happens on next press)
        if self._toggle_recording:
            logger.info("Toggle mode active, ignoring release")
            return
        hold_duration = time.monotonic() - self._fn_press_time
        logger.info("Release: hold=%.3fs (ghost<%.1f, tap<%.1f)",
                     hold_duration, FN_MIN_HOLD_SEC, TAP_MAX_HOLD_SEC)

        if hold_duration < FN_MIN_HOLD_SEC:
            # Ghost press (modifier key re-assertion) — discard silently
            self.is_recording = False
            self.audio_chunks = []
            stream_ref = self.stream
            self.stream = None
            if stream_ref:
                def _close(s):
                    try:
                        s.stop()
                        s.close()
                    except Exception:
                        logger.warning("Stream close error (ghost press)", exc_info=True)
                threading.Thread(target=_close, args=(stream_ref,), daemon=True).start()
            self._update_indicator(IDLE_LABEL, 0.1, 0.1, 0.1, 0.55)
            return

        if hold_duration < TAP_MAX_HOLD_SEC:
            # Short tap → enter toggle mode, keep recording
            self._toggle_recording = True
            self._play_sound("Tink")  # double-Tink confirms toggle
            logger.info("Toggle mode: recording continues (tap again to stop)")
            return

        # Long hold → stop and transcribe (hold-to-talk)
        logger.info("Hold-to-talk: stopping and transcribing")
        self._stop_and_transcribe()

    def _transcribe(self, stream_ref=None):
        # Stop/close audio stream in background thread (not blocking main RunLoop)
        if stream_ref:
            try:
                stream_ref.stop()
                stream_ref.close()
            except Exception:
                logger.error("Stream close error", exc_info=True)

        try:
            t_start = time.monotonic()

            # ── Feature 1: Finalize streaming transcriber ──
            # The streamer has been transcribing speech segments in the background
            # during recording. Now we just need to process the tail.
            streamer = self._streamer
            self._streamer = None

            # Also grab the old-style chunks as fallback
            chunks = self.audio_chunks
            self.audio_chunks = []

            if streamer:
                raw_text, asr_sec, duration = streamer.finalize()

                if duration < MIN_AUDIO_DURATION_SEC:
                    logger.info("Too short (%.2fs), skipping.", duration)
                    return

                # If streaming produced nothing, fall back to batch transcription
                if not raw_text and chunks:
                    logger.info("Streaming produced no text, falling back to batch.")
                    audio = np.concatenate(chunks, axis=0)
                    chunks.clear()
                    audio, trimmed_tail_sec = _trim_trailing_silence(audio)
                    duration = len(audio) / SAMPLE_RATE
                    if duration < MIN_AUDIO_DURATION_SEC:
                        logger.info("Batch fallback too short (%.2fs), skipping.", duration)
                        return
                    tmp = _secure_tmpfile()
                    sf.write(tmp, audio, SAMPLE_RATE)

                    use_prompt = bool(self.keywords) and self._disable_prompt_rounds <= 0
                    if not use_prompt and self._disable_prompt_rounds > 0:
                        self._disable_prompt_rounds -= 1

                    raw_text, asr_sec = transcribe(
                        audio_path=tmp,
                        keywords=self.keywords,
                        use_prompt=use_prompt,
                        duration=duration,
                    )
                    os.unlink(tmp)
            else:
                # No streamer (shouldn't happen, but handle gracefully)
                if not chunks:
                    logger.info("No audio captured.")
                    return
                audio = np.concatenate(chunks, axis=0)
                chunks.clear()
                audio, _ = _trim_trailing_silence(audio)
                duration = len(audio) / SAMPLE_RATE
                if duration < MIN_AUDIO_DURATION_SEC:
                    return
                tmp = _secure_tmpfile()
                sf.write(tmp, audio, SAMPLE_RATE)
                use_prompt = bool(self.keywords) and self._disable_prompt_rounds <= 0
                raw_text, asr_sec = transcribe(
                    audio_path=tmp, keywords=self.keywords,
                    use_prompt=use_prompt, duration=duration,
                )
                os.unlink(tmp)

            # Track slow ASR
            rtf = asr_sec / max(duration, 0.1)
            slow_asr = asr_sec >= ASR_SLOW_THRESHOLD_SEC or rtf >= ASR_SLOW_RTF_THRESHOLD
            if slow_asr:
                self._slow_asr_streak += 1
            else:
                self._slow_asr_streak = 0
            if self._slow_asr_streak >= ASR_SLOW_STREAK_TRIGGER:
                self._disable_prompt_rounds = max(
                    self._disable_prompt_rounds, PROMPT_DISABLE_ROUNDS_ON_SLOW
                )
                logger.info(
                    "Slow ASR streak=%d, disable prompt for next %d rounds. (asr=%.2fs, rtf=%.2f)",
                    self._slow_asr_streak, self._disable_prompt_rounds, asr_sec, rtf,
                )
            elif self._disable_prompt_rounds > 0:
                self._disable_prompt_rounds -= 1

            if raw_text:
                processed = postprocess_fast(raw_text)

                # ── Feature 3: Skip LLM polish on short utterances ──
                import re
                word_count = len(re.findall(r'[A-Za-z]+|[\u4e00-\u9fff]', processed))
                llm_sec = 0.0
                if word_count > LLM_SKIP_WORD_THRESHOLD:
                    polished, llm_sec = polish_text(processed)
                    if polished != processed:
                        logger.info("llm  -> %s (%.2fs)", polished, llm_sec)
                        processed = polished
                else:
                    logger.info("LLM skip: %d words <= threshold %d", word_count, LLM_SKIP_WORD_THRESHOLD)

                t_post = time.monotonic()
                logger.info("raw -> %s", raw_text)
                logger.info("out -> %s", processed)

                self._last_text = processed
                current_front_app = get_frontmost_app_id()
                same_app = (
                    bool(self._recording_front_app)
                    and current_front_app == self._recording_front_app
                )
                current_front_window = ""
                if same_app:
                    current_front_window = get_front_window_title()
                window_title_changed = (
                    bool(self._recording_front_window)
                    and bool(current_front_window)
                    and _normalize_window_title(current_front_window)
                    != _normalize_window_title(self._recording_front_window)
                )

                # ── Feature 5: Use pre-captured clipboard snapshot for faster paste ──
                if same_app and not window_title_changed:
                    self._paste_with_presnapshot(processed)
                    t_end = time.monotonic()
                    self._play_sound("Ping")
                    self._show_result(processed)
                else:
                    t_end = time.monotonic()
                    self._play_sound("Ping")
                    self._show_copy_prompt(processed)
                    logger.info(
                        "Window changed (app: %s -> %s, window: %r -> %r), showing copy prompt.",
                        self._recording_front_app, current_front_app,
                        self._recording_front_window, current_front_window,
                    )

                save_history(raw_text, processed, duration)
                rss_mb_now = get_rss_mb()
                kw_terms = len([x for x in self.keywords.split(",") if x.strip()]) if self.keywords else 0
                logger.info(
                    "[BENCH] audio=%.1fs | asr=%.2fs | llm=%.2fs | rtf=%.2f | "
                    "post=%.2fs | paste=%.2fs | total=%.2fs | rss=%.0fMB | "
                    "kw_chars=%d | kw_terms=%d | prompt=%s | slow_streak=%d | streaming=yes",
                    duration, asr_sec, llm_sec, rtf, t_post - (t_start + asr_sec),
                    t_end - t_post, t_end - t_start, rss_mb_now, len(self.keywords),
                    kw_terms, "on" if bool(self.keywords) else "off", self._slow_asr_streak,
                )

                self.is_transcribing = False
                return
            else:
                logger.info("No speech detected.")
        except Exception:
            logger.error("Transcription error", exc_info=True)
        finally:
            if self._asr_watchdog:
                self._asr_watchdog.cancel()
                self._asr_watchdog = None
            self._streamer = None
            self._clipboard_snapshot = None
            self._clipboard_change_count = None
            self.audio_chunks = []
            restarting = False
            now = time.time()
            if now - self._last_memory_maintenance_ts >= MEMORY_MAINTENANCE_INTERVAL_SEC:
                run_memory_maintenance()
                self._last_memory_maintenance_ts = now
                # Mine history for keyword suggestions
                suggestions = suggest_keywords()
                if suggestions:
                    logger.info("Keyword suggestions from history: %s", ", ".join(suggestions))
                rss_mb = get_rss_mb()
                if rss_mb > 0:
                    logger.info("RSS: %.0f MB (maintenance)", rss_mb)
                    if rss_mb >= MEMORY_SOFT_LIMIT_MB:
                        logger.warning(
                            "RSS %.0f MB > %d MB, auto-restarting...",
                            rss_mb, MEMORY_SOFT_LIMIT_MB,
                        )
                        self.is_transcribing = False
                        restarting = True
            if restarting:
                self._auto_restart()
            else:
                self.is_transcribing = False
                def _reset_all():
                    self.waveform_view.set_state("idle")
                    self.label.setHidden_(False)
                AppHelper.callAfter(_reset_all)
                self._update_indicator(IDLE_LABEL, 0.1, 0.1, 0.1, 0.55)

    def _paste_with_presnapshot(self, text: str) -> None:
        """Paste text using the clipboard snapshot captured at recording start.

        Feature 5: Since we pre-captured the clipboard in _on_fn_press,
        we skip the snapshot step here, saving ~50ms.
        """
        snapshot = self._clipboard_snapshot
        change_count = self._clipboard_change_count
        self._clipboard_snapshot = None
        self._clipboard_change_count = None

        if snapshot is None or change_count is None:
            # No pre-snapshot available, fall back to standard paste
            paste_text(text)
            return

        from whisper_dictate.clipboard import _restore_clipboard

        # Write text to clipboard and paste
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(text.encode("utf-8"))
        subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to keystroke "v" using command down'],
            capture_output=True,
        )

        # Restore original clipboard using pre-captured snapshot
        from whisper_dictate.config import CLIPBOARD_RESTORE_DELAY_SEC

        def _restore():
            try:
                pb = __import__('AppKit', fromlist=['NSPasteboard']).NSPasteboard.generalPasteboard()
                current_count = int(pb.changeCount())
                if current_count == change_count + 1:
                    _restore_clipboard(snapshot)
            except Exception:
                logger.debug("Clipboard restore failed (non-fatal)", exc_info=True)

        timer = threading.Timer(CLIPBOARD_RESTORE_DELAY_SEC, _restore)
        timer.daemon = True
        timer.start()

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


# ── instance lock ──────────────────────────────────────────
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
        return lock_fd  # keep fd alive to hold the lock
    except (IOError, OSError):
        logger.error("Another instance is already running. Exiting.")
        sys.exit(0)


# ── main ───────────────────────────────────────────────────
def main():
    setup_logging()

    _acquire_lock()
    _ensure_private_dir(KEYWORDS_FILE)
    ensure_history_file()
    _set_private(HISTORY_FILE)
    _set_private(LOG_FILE)
    if not os.path.exists(KEYWORDS_FILE):
        with open(KEYWORDS_FILE, "w") as f:
            f.write("NVIDIA, Tesla, S&P 500, Bitcoin, Apple, Microsoft, Google")
    _set_private(KEYWORDS_FILE)

    hotkey_name = "Ctrl+Option" if USE_CTRL_OPT else "FN"
    logger.info("Starting v2... (hold %s to talk)", hotkey_name)
    logger.info("Keywords: %s", KEYWORDS_FILE)
    logger.info("History: %s", HISTORY_FILE)

    app = NSApplication.sharedApplication()
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)

    signal.signal(signal.SIGINT, lambda *_: app.terminate_(None))

    AppHelper.runEventLoop()
