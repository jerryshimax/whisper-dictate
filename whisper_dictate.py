#!/usr/bin/env python3
"""Whisper Dictation v2 — macOS app with FN hold-to-talk, post-processing, and history.

Usage:
    python whisper_dictate.py
    Or: open ~/Applications/WhisperDictate.app

This is a thin launcher; all logic lives in the whisper_dictate/ package.
"""
from whisper_dictate.app import main

if __name__ == "__main__":
    main()
