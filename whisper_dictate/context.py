"""Context-aware transcription: read active app to improve ASR accuracy."""
from __future__ import annotations

import logging
import re
import subprocess

from whisper_dictate.config import CONTEXT_APPS

logger = logging.getLogger("whisper_dictate.context")


def get_app_type(bundle_id: str) -> str:
    """Map bundle ID to app category."""
    return CONTEXT_APPS.get(bundle_id, "general")


def get_window_context_keywords(bundle_id: str) -> str:
    """Extract contextual keywords from the active window.

    Reads the window title and, for supported apps, extracts names and
    terms that could help ASR accuracy (e.g., email recipient names,
    Slack channel names, document titles).
    """
    app_type = get_app_type(bundle_id)

    # Get the window title
    try:
        script = (
            'tell application "System Events"\n'
            '  try\n'
            '    set frontProc to first process whose frontmost is true\n'
            '    set wt to ""\n'
            '    try\n'
            '      set wt to name of front window of frontProc\n'
            '    end try\n'
            '    return wt\n'
            '  on error\n'
            '    return ""\n'
            '  end try\n'
            'end tell'
        )
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=0.3,
        )
        title = out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        title = ""

    if not title:
        return ""

    # Extract useful terms from the window title
    terms: list[str] = []

    if app_type == "email":
        # Email subjects often contain names and topics
        # Strip common prefixes
        cleaned = re.sub(r'^(?:Re:|Fwd?:|FW:)\s*', '', title, flags=re.IGNORECASE)
        # Extract multi-word proper nouns
        for m in re.finditer(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*', cleaned):
            terms.append(m.group())
        # Chinese names
        for zh in re.findall(r'[\u4e00-\u9fff]{2,4}', cleaned):
            terms.append(zh)

    elif app_type == "chat":
        # Slack/Telegram/iMessage — channel or contact name
        # Telegram: "Chat Name — Telegram"
        # Slack: "#channel-name | Workspace" or "Person Name | Workspace"
        cleaned = re.split(r'\s*[—|]\s*', title)[0].strip()
        if cleaned.startswith('#'):
            cleaned = cleaned[1:]  # strip Slack channel hash
        # Convert kebab-case to words
        cleaned = cleaned.replace('-', ' ')
        for word in cleaned.split():
            if len(word) >= 2:
                terms.append(word)

    elif app_type in ("code", "terminal"):
        # File names, project names from title
        for m in re.finditer(r'[A-Za-z_][A-Za-z0-9_]{2,}', title):
            word = m.group()
            if len(word) >= 3 and word not in _SKIP_CODE_TERMS:
                terms.append(word)

    else:
        # General: extract proper nouns
        for m in re.finditer(r'[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*', title):
            terms.append(m.group())

    if not terms:
        return ""

    # Dedupe
    seen: set[str] = set()
    unique: list[str] = []
    for t in terms:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            unique.append(t)

    result = ", ".join(unique[:15])  # cap at 15 terms
    if result:
        logger.debug("Context keywords from %s [%s]: %s", app_type, bundle_id, result)
    return result


_SKIP_CODE_TERMS = frozenset({
    'usr', 'bin', 'src', 'lib', 'var', 'tmp', 'etc', 'opt',
    'index', 'main', 'test', 'spec', 'dist', 'build', 'node_modules',
    'Untitled', 'undefined', 'null', 'true', 'false',
})
