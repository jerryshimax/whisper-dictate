"""Regex-based text cleaning pipeline for ASR output. Pure functions, no state."""
from __future__ import annotations

import re

# ── regex patterns ─────────────────────────────────────────
_FILLER_ZH = re.compile(
    r'(?<![一-龥])(?:嗯+|啊+|呃+|那个|就是说|就是|然后嘛)(?![一-龥])'
)
_FILLER_EN = re.compile(
    r'\b(?:um+|uh+|like|you know|I mean|basically|actually|so+)\b',
    re.IGNORECASE,
)

_HALLUCINATION_RE = re.compile(
    r'(?:字幕志愿者|字幕由|请不要|谢谢大家|感谢收看|订阅|小铃铛|'
    r'(?:\$i\s*){3,}|(.{2,6})\1{4,})',
)
_TAIL_NOISE_RE = re.compile(
    r'[\s，,。.!?！？；;:：、\-]*(?:sperdy|seperti)[\s，,。.!?！？；;:：、\-]*$',
    re.IGNORECASE,
)

_REPEATED_BLOCK_RE = re.compile(r'(.{8,120}?)\1{1,}')


# ── cleaning functions ─────────────────────────────────────
def _strip_hallucinations(text: str) -> str:
    text = _HALLUCINATION_RE.sub('', text)
    return text.strip()


def _strip_tail_noise(text: str) -> str:
    """Drop known recurring tail-noise token from ASR output."""
    return _TAIL_NOISE_RE.sub('', text).strip()


def _collapse_repeated_blocks(text: str) -> str:
    """Collapse exact repeated long chunks: AAA -> A."""
    prev = None
    while prev != text:
        prev = text
        text = _REPEATED_BLOCK_RE.sub(r'\1', text)
    return text


def _norm_clause_for_dedupe(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[\s，,。.!?！？；;:：、\"'`\u201c\u201d\u2018\u2019()\[\]{}-]+", '', text)
    return text


def _dedupe_adjacent_clauses(text: str) -> str:
    """Remove adjacent duplicated clauses split by punctuation/comma."""
    parts = re.split(r'([，,。.!?！？；;:\n])', text)
    if len(parts) <= 1:
        return text

    out: list[str] = []
    prev_norm = ""
    i = 0
    while i < len(parts):
        clause = parts[i].strip()
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        i += 2

        if not clause:
            continue

        norm = _norm_clause_for_dedupe(clause)
        # Keep very short acknowledgements to avoid over-deletion.
        if norm and norm == prev_norm and len(norm) >= 6:
            continue

        out.append(clause)
        if sep:
            out.append(sep)
        prev_norm = norm

    return ''.join(out).strip()


def _dedupe_repeated_tail_phrase(text: str) -> str:
    """Collapse repeated suffix phrase like 'X X X' -> 'X'."""
    s = text.strip()
    if len(s) < 12:
        return s

    # Try multiple tail lengths; prioritize longer phrases.
    max_len = min(36, len(s) // 2)
    for phrase_len in range(max_len, 3, -1):
        phrase = s[-phrase_len:]
        if not phrase.strip():
            continue
        # Avoid pure punctuation/noise phrase.
        if not re.search(r'[A-Za-z0-9\u4e00-\u9fff]', phrase):
            continue

        count = 0
        cursor = len(s)
        while cursor >= phrase_len and s[cursor - phrase_len:cursor] == phrase:
            count += 1
            cursor -= phrase_len

        if count >= 2:
            s = s[:cursor] + phrase
            break

    return s


def _dedupe_tail_by_char_stream(text: str) -> str:
    """More aggressive tail-loop dedupe that ignores spaces/punctuation."""
    s = text.strip()
    if len(s) < 16:
        return s

    # Keep only semantic chars; map back to original index.
    stream_chars: list[str] = []
    stream_to_orig: list[int] = []
    for i, ch in enumerate(s):
        if re.match(r'[A-Za-z0-9\u4e00-\u9fff]', ch):
            stream_chars.append(ch)
            stream_to_orig.append(i)

    n = len(stream_chars)
    if n < 16:
        return s

    max_unit = min(24, n // 2)
    for unit_len in range(max_unit, 3, -1):
        unit = stream_chars[n - unit_len:n]
        if len(set(unit)) < 3:
            continue

        count = 1
        cursor = n - unit_len
        while cursor - unit_len >= 0 and stream_chars[cursor - unit_len:cursor] == unit:
            count += 1
            cursor -= unit_len

        if count < 2:
            continue

        remove_start_stream = n - unit_len * count
        remove_end_stream = n - unit_len
        if remove_start_stream < 0 or remove_end_stream <= remove_start_stream:
            continue

        remove_start_orig = stream_to_orig[remove_start_stream]
        keep_start_orig = stream_to_orig[remove_end_stream]
        if keep_start_orig <= remove_start_orig:
            continue

        s = s[:remove_start_orig] + s[keep_start_orig:]
        break

    return s


def _remove_fillers(text: str) -> str:
    text = _FILLER_ZH.sub('', text)
    text = _FILLER_EN.sub('', text)
    return text


def _clean_whitespace(text: str) -> str:
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'([，,。.！!？?])\1+', r'\1', text)
    text = re.sub(r'\s*([，,。.！!？?])', r'\1', text)
    return text.strip()


def _postprocess_regex(text: str) -> str:
    text = _strip_hallucinations(text)
    text = _collapse_repeated_blocks(text)
    text = _dedupe_adjacent_clauses(text)
    text = _dedupe_repeated_tail_phrase(text)
    text = _dedupe_tail_by_char_stream(text)
    text = _remove_fillers(text)
    text = _strip_tail_noise(text)
    text = _clean_whitespace(text)
    return text


def postprocess_fast(text: str) -> str:
    """Immediate path: hallucination strip + regex. Always returns quickly."""
    text = _strip_hallucinations(text)
    if not text:
        return text
    return _postprocess_regex(text)
