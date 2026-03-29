"""Streaming VAD-chunked transcription engine.

Runs ASR on speech segments while the user is still recording, so that by the
time they release the hotkey most of the audio is already transcribed.

Architecture:
  - Audio callback pushes frames into a thread-safe queue
  - A background thread runs energy-based VAD on the frames
  - When a speech segment boundary is detected (silence gap), the segment
    is sent to ASR immediately
  - On finalize (hotkey release), only the remaining tail needs transcription
  - Results are concatenated in order
"""
from __future__ import annotations

import logging
import queue
import threading
import time

import numpy as np

from whisper_dictate.config import (
    SAMPLE_RATE,
    VAD_ENERGY_THRESHOLD_DB,
    VAD_FRAME_SEC,
    VAD_MAX_SEGMENT_SEC,
    VAD_MIN_SEGMENT_SEC,
    VAD_SILENCE_TRIGGER_SEC,
)

logger = logging.getLogger("whisper_dictate.streaming")


class StreamingTranscriber:
    """Accumulates audio, detects speech segments via VAD, transcribes them
    in the background as they arrive."""

    def __init__(self, keywords: str = "", use_prompt: bool = True):
        self._keywords = keywords
        self._use_prompt = use_prompt
        self._kw_lock = threading.Lock()

        # Audio accumulation
        self._frame_queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self._all_audio: list[np.ndarray] = []  # all frames in order
        self._segment_start: int = 0  # sample index where current segment starts
        self._total_samples: int = 0

        # VAD state
        self._speech_active = False
        self._silence_samples: int = 0
        self._silence_trigger = int(SAMPLE_RATE * VAD_SILENCE_TRIGGER_SEC)
        self._min_segment_samples = int(SAMPLE_RATE * VAD_MIN_SEGMENT_SEC)
        self._max_segment_samples = int(SAMPLE_RATE * VAD_MAX_SEGMENT_SEC)
        self._vad_frame_size = int(SAMPLE_RATE * VAD_FRAME_SEC)

        # Results
        self._results: list[tuple[int, str]] = []  # (segment_index, text)
        self._result_lock = threading.Lock()
        self._segment_count = 0
        self._asr_threads: list[threading.Thread] = []

        # Control
        self._running = False
        self._vad_thread: threading.Thread | None = None

    def update_keywords(self, keywords: str, use_prompt: bool = True) -> None:
        """Update keywords after construction (called when background context is ready)."""
        with self._kw_lock:
            self._keywords = keywords
            self._use_prompt = use_prompt

    def start(self) -> None:
        """Start the VAD processing thread."""
        self._running = True
        self._vad_thread = threading.Thread(target=self._vad_loop, daemon=True)
        self._vad_thread.start()
        logger.info("StreamingTranscriber started (running=%s)", self._running)

    def feed(self, audio_chunk: np.ndarray) -> None:
        """Called from the audio callback with each chunk of samples."""
        if self._running:
            self._frame_queue.put(audio_chunk.copy())
        else:
            logger.debug("feed() called but streamer not running (samples=%d)", len(audio_chunk))

    def finalize(self) -> tuple[str, float, float]:
        """Stop streaming, transcribe any remaining audio, return full result.

        Returns (full_text, total_asr_seconds, audio_duration).
        """
        t0 = time.monotonic()
        qsize = self._frame_queue.qsize()
        logger.info("finalize() called: queue_size=%d, total_samples_so_far=%d", qsize, self._total_samples)
        self._running = False
        self._frame_queue.put(None)  # sentinel

        # Wait for VAD thread to finish processing
        if self._vad_thread:
            self._vad_thread.join(timeout=2.0)

        # Wait for in-flight ASR threads BEFORE transcribing the tail —
        # MLX Metal can't run concurrent Whisper inference without deadlocking.
        for t in self._asr_threads:
            t.join(timeout=10.0)

        # Transcribe any remaining audio that didn't hit a silence boundary
        remaining = self._get_remaining_audio()
        remaining_asr_sec = 0.0
        if remaining is not None and len(remaining) >= self._min_segment_samples:
            seg_idx = self._segment_count
            self._segment_count += 1
            text, asr_sec = self._transcribe_segment(remaining)
            remaining_asr_sec = asr_sec
            if text:
                with self._result_lock:
                    self._results.append((seg_idx, text))

        # Assemble final text in segment order
        with self._result_lock:
            self._results.sort(key=lambda x: x[0])
            texts = [r[1] for r in self._results if r[1]]

        full_text = " ".join(texts)
        total_duration = self._total_samples / SAMPLE_RATE
        total_time = time.monotonic() - t0

        pre_transcribed = len(self._results) - (1 if remaining is not None and len(remaining) >= self._min_segment_samples else 0)
        logger.info(
            "Streaming finalize: %d segments pre-transcribed, tail=%.1fs, "
            "finalize_time=%.2fs, total_audio=%.1fs",
            pre_transcribed,
            len(remaining) / SAMPLE_RATE if remaining is not None else 0,
            total_time,
            total_duration,
        )

        return full_text, remaining_asr_sec, total_duration

    def get_all_audio(self) -> np.ndarray | None:
        """Return all accumulated audio as a single array (for fallback)."""
        if not self._all_audio:
            return None
        return np.concatenate(self._all_audio, axis=0).flatten()

    def _vad_loop(self) -> None:
        """Background thread: process audio frames, detect speech segments."""
        pending_frames: list[np.ndarray] = []

        while True:
            try:
                frame = self._frame_queue.get(timeout=0.1)
            except queue.Empty:
                if not self._running:
                    break
                continue

            if frame is None:  # sentinel
                break

            flat = frame.flatten()
            self._all_audio.append(flat)
            self._total_samples += len(flat)
            pending_frames.append(flat)

            # Process in VAD frame-sized chunks
            combined = np.concatenate(pending_frames)
            processed = 0

            while processed + self._vad_frame_size <= len(combined):
                vad_frame = combined[processed:processed + self._vad_frame_size]
                processed += self._vad_frame_size
                self._process_vad_frame(vad_frame)

            # Keep unprocessed remainder
            if processed < len(combined):
                pending_frames = [combined[processed:]]
            else:
                pending_frames = []

    def _process_vad_frame(self, frame: np.ndarray) -> None:
        """Process a single VAD frame, detect speech/silence transitions."""
        rms = float(np.sqrt(np.mean(np.square(frame))))
        db = 20.0 * np.log10(max(rms, 1e-7))

        is_speech = db > VAD_ENERGY_THRESHOLD_DB

        if is_speech:
            self._speech_active = True
            self._silence_samples = 0
        else:
            if self._speech_active:
                self._silence_samples += len(frame)

                if self._silence_samples >= self._silence_trigger:
                    # Silence boundary detected — extract and transcribe segment
                    segment_end = self._total_samples - self._silence_samples
                    segment_samples = segment_end - self._segment_start

                    if segment_samples >= self._min_segment_samples:
                        segment_audio = self._extract_segment(
                            self._segment_start, segment_end
                        )
                        if segment_audio is not None:
                            seg_idx = self._segment_count
                            self._segment_count += 1
                            t = threading.Thread(
                                target=self._transcribe_and_store,
                                args=(segment_audio, seg_idx),
                                daemon=True,
                            )
                            self._asr_threads.append(t)
                            t.start()

                    self._segment_start = segment_end
                    self._speech_active = False
                    self._silence_samples = 0

    def _extract_segment(self, start: int, end: int) -> np.ndarray | None:
        """Extract audio samples from the accumulated buffer."""
        all_audio = np.concatenate(self._all_audio, axis=0).flatten()
        start = max(0, min(start, len(all_audio)))
        end = max(start, min(end, len(all_audio)))
        if end <= start:
            return None
        return all_audio[start:end]

    def _get_remaining_audio(self) -> np.ndarray | None:
        """Get audio from the last segment boundary to the end."""
        if not self._all_audio:
            return None
        all_audio = np.concatenate(self._all_audio, axis=0).flatten()
        if self._segment_start >= len(all_audio):
            return None
        return all_audio[self._segment_start:]

    def _transcribe_segment(self, audio: np.ndarray) -> tuple[str, float]:
        """Transcribe a segment of audio."""
        from whisper_dictate.asr import transcribe_array
        with self._kw_lock:
            kw = self._keywords
            use = self._use_prompt
        return transcribe_array(
            audio,
            keywords=kw,
            use_prompt=use,
        )

    def _transcribe_and_store(self, audio: np.ndarray, seg_idx: int) -> None:
        """Transcribe and store result (runs in background thread)."""
        try:
            text, asr_sec = self._transcribe_segment(audio)
            dur = len(audio) / SAMPLE_RATE
            logger.info(
                "Streaming segment #%d: %.1fs audio -> %.2fs ASR, text=%r",
                seg_idx, dur, asr_sec, text[:60] if text else "",
            )
            if text:
                with self._result_lock:
                    self._results.append((seg_idx, text))
        except Exception:
            logger.error("Streaming segment #%d failed", seg_idx, exc_info=True)
