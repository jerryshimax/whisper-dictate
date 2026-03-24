#!/usr/bin/env python3
"""Build WhisperDictate.app — lightweight shell-based .app bundle.

Creates a macOS .app that launches whisper_dictate.py using Python.
Uses WHISPER_PYTHON env var, conda voice env, or system python3.

Usage:
    python setup_whisper_app.py
"""
from __future__ import annotations

import os
import plistlib
import shutil
import stat
import subprocess

APP_NAME = "WhisperDictate"
APP_DIR = os.path.expanduser(f"~/Applications/{APP_NAME}.app")
CONTENTS = os.path.join(APP_DIR, "Contents")
MACOS = os.path.join(CONTENTS, "MacOS")
RESOURCES = os.path.join(CONTENTS, "Resources")

SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whisper_dictate.py")

PLIST = {
    "CFBundleName": APP_NAME,
    "CFBundleDisplayName": "Whisper Dictate",
    "CFBundleIdentifier": "com.user.whisper-dictate",
    "CFBundleVersion": "2.1.0",
    "CFBundleShortVersionString": "2.1",
    "CFBundleExecutable": APP_NAME,
    "CFBundlePackageType": "APPL",
    "LSUIElement": True,
    "NSMicrophoneUsageDescription": "Whisper Dictate needs microphone access for voice input.",
    "LSMinimumSystemVersion": "13.0",
}

LOG_FILE = os.path.expanduser("~/.config/whisper/app.log")


def _find_python() -> str:
    """Find the best Python to use: $WHISPER_PYTHON > conda voice > system."""
    env_python = os.environ.get("WHISPER_PYTHON")
    if env_python and os.path.isfile(env_python):
        return env_python

    conda_python = os.path.expanduser("~/miniconda3/envs/voice/bin/python")
    if os.path.isfile(conda_python):
        return conda_python

    conda_python_alt = os.path.expanduser("~/anaconda3/envs/voice/bin/python")
    if os.path.isfile(conda_python_alt):
        return conda_python_alt

    system = shutil.which("python3")
    if system:
        return system

    return "python3"


def main():
    python_path = _find_python()
    print(f"Using Python: {python_path}")

    if os.path.exists(APP_DIR):
        shutil.rmtree(APP_DIR)
        print(f"Removed existing {APP_DIR}")

    os.makedirs(MACOS, exist_ok=True)
    os.makedirs(RESOURCES, exist_ok=True)

    plist_path = os.path.join(CONTENTS, "Info.plist")
    with open(plist_path, "wb") as f:
        plistlib.dump(PLIST, f)
    print(f"Wrote {plist_path}")

    launcher = f"""#!/bin/bash
export PATH="/opt/homebrew/bin:$PATH"
exec "{python_path}" -u "{SCRIPT_PATH}" >> "{LOG_FILE}" 2>&1
"""
    launcher_path = os.path.join(MACOS, APP_NAME)
    with open(launcher_path, "w") as f:
        f.write(launcher)
    os.chmod(launcher_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    print(f"Wrote {launcher_path}")

    subprocess.run(["codesign", "-s", "-", "--force", "--deep", APP_DIR], check=True)
    print(f"\nBuilt and signed {APP_DIR}")
    print(f"  Launch: open ~/Applications/{APP_NAME}.app")
    print(f"  Add to Login Items: System Settings > General > Login Items")
    print(f"  Grant Accessibility: System Settings > Privacy > Accessibility")


if __name__ == "__main__":
    main()
