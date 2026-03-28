"""Scan Brain vault MD files to extract contextual keywords for Whisper prompts."""
from __future__ import annotations

import logging
import os
import re
import time

logger = logging.getLogger("whisper_dictate.brain_keywords")

BRAIN_DIR = os.path.expanduser("~/Work/[00] Brain")

# Cache: refresh at most every 30 minutes
_cache: dict = {"keywords": "", "ts": 0.0}
CACHE_TTL_SEC = 30 * 60


def _extract_names_from_filename(fname: str) -> list[str]:
    """Extract entity/person/company names from Brain file names."""
    names: list[str] = []
    # [People] First Last.md  or  [People] First Last 中文名.md
    m = re.match(r'\[People\]\s*(.+?)\.md$', fname)
    if m:
        raw = m.group(1).strip()
        # Split English and Chinese parts
        parts = re.split(r'\s+', raw)
        # Full name
        names.append(raw)
        # Individual parts (skip single chars)
        for p in parts:
            if len(p) >= 2:
                names.append(p)
        return names

    # [Meetings] Entity - YYYY-MM-DD Description.md
    m = re.match(r'\[(?:Meetings|Memos|Research|Decks)\]\s*(?:\w+\s*-\s*)?(?:\d{4}-\d{2}-\d{2}\s+)?(.+?)\.md$', fname)
    if m:
        desc = m.group(1).strip()
        # Extract capitalized words / proper nouns from description
        for word in re.findall(r'[A-Z][a-zA-Z]{2,}', desc):
            if word not in _COMMON_SKIP:
                names.append(word)
        # Extract Chinese company/person names (2-4 chars)
        for zh in re.findall(r'[\u4e00-\u9fff]{2,6}', desc):
            names.append(zh)

    return names


def _extract_from_frontmatter(content: str) -> list[str]:
    """Extract names, aliases, company names from YAML frontmatter."""
    terms: list[str] = []
    fm_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not fm_match:
        return terms

    fm = fm_match.group(1)

    # name / title field
    for field in ('name', 'title', 'company'):
        m = re.search(rf'^{field}:\s*(.+)$', fm, re.MULTILINE)
        if m:
            val = m.group(1).strip().strip('"\'')
            if val:
                terms.append(val)
                # Also add individual words if multi-word
                for w in re.split(r'\s+', val):
                    if len(w) >= 2 and w not in _COMMON_SKIP:
                        terms.append(w)

    # aliases field: [alias1, alias2, ...]
    m = re.search(r'^aliases:\s*\[([^\]]+)\]', fm, re.MULTILINE)
    if m:
        for alias in m.group(1).split(','):
            alias = alias.strip().strip('"\'')
            if alias and len(alias) >= 2:
                terms.append(alias)

    # relationship field
    m = re.search(r'^relationship:\s*(.+)$', fm, re.MULTILINE)
    if m:
        rel = m.group(1).strip()
        # Extract org names from relationship
        for word in re.findall(r'[A-Z][a-zA-Z]{2,}', rel):
            if word not in _COMMON_SKIP:
                terms.append(word)

    return terms


def _extract_from_body(content: str, max_lines: int = 40) -> list[str]:
    """Extract key terms from the first N lines of People file body.

    Focuses on company names and proper nouns that appear after
    known patterns like "**Company**", "Founder,", etc.
    """
    terms: list[str] = []
    # Skip frontmatter
    body = re.sub(r'^---\s*\n.*?\n---\s*\n', '', content, count=1, flags=re.DOTALL)
    lines = body.split('\n')[:max_lines]
    text = '\n'.join(lines)

    # Multi-word proper nouns (2+ capitalized words together = likely org name)
    for m in re.finditer(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', text):
        candidate = m.group(1).strip()
        words = candidate.split()
        if any(w in _COMMON_SKIP for w in words):
            continue
        if len(candidate) >= 5:
            terms.append(candidate)

    # Single capitalized words that look like brand/company names (not common)
    for m in re.finditer(r'\b([A-Z][a-zA-Z]{3,})\b', text):
        word = m.group(1)
        if word not in _COMMON_SKIP and not word.endswith(('ing', 'tion', 'ment', 'ness', 'able', 'ible')):
            terms.append(word)

    # Chinese org/person names (2-4 chars, more selective)
    for zh in re.findall(r'[\u4e00-\u9fff]{2,4}', text):
        terms.append(zh)

    return terms


_COMMON_SKIP = frozenset({
    'The', 'This', 'That', 'What', 'When', 'Where', 'How', 'Why',
    'Can', 'Could', 'Would', 'Should', 'Are', 'Was', 'Were', 'Have',
    'Has', 'Had', 'Not', 'But', 'And', 'For', 'With', 'From',
    'Just', 'Like', 'Also', 'Very', 'Really', 'Actually', 'Basically',
    'About', 'After', 'Before', 'Then', 'Now', 'Here', 'There',
    'Some', 'Any', 'All', 'More', 'Other', 'Into', 'Over',
    'Role', 'Background', 'Education', 'Location', 'Status',
    'Notes', 'Tags', 'Type', 'Entity', 'Active', 'Draft',
    'Meeting', 'Meetings', 'Research', 'Memos', 'People', 'Decks',
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
    'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
    'Founded', 'Founder', 'Managing', 'Partner', 'Director',
    'Prior', 'Current', 'Previous', 'Recent', 'Last', 'First',
    'Key', 'Main', 'Summary', 'Overview', 'Details', 'Context',
    'Contact', 'Mobile', 'Email', 'Website', 'Address', 'Phone',
    'Claims', 'Claim', 'Giving', 'Called', 'Quoted', 'Start',
    'Invited', 'Opened', 'Bullish', 'Low', 'High',
    'North', 'South', 'East', 'West', 'Asia', 'Europe', 'America',
    'Middle', 'Greater', 'Area', 'Bay', 'San', 'New', 'Los',
    'President', 'Vice', 'CEO', 'CFO', 'CTO', 'COO',
    'Deep', 'Executive', 'Customer', 'Overseas', 'Experience',
    'Exchange', 'Conference', 'Mining', 'Digital',
    'Wikipedia', 'Crunchbase', 'Bloomberg', 'LinkedIn',
    'Through', 'Met', 'Departure', 'Unsubstantiated',
    'Confirmed', 'Title', 'Sept', 'Timeline', 'Ventures',
    'Tech', 'Fund', 'Division', 'Nasdaq', 'SPAC',
    'Company', 'Science', 'University', 'School',
    'Parkway', 'Sunnyvale', 'Oakmead', 'Street',
    'Seed', 'Series', 'Round', 'Stage', 'Focus',
    'Portfolio', 'Includes', 'Previously', 'Based',
    'Reborn', 'Industry', 'Global', 'Capital',
    'Hong', 'Kong', 'Toronto', 'Beijing', 'Shanghai',
    'Chengdu', 'Miami', 'China', 'Canada', 'Shenzhen',
})


def scan_brain_keywords(max_chars: int = 700) -> str:
    """Scan Brain vault and return a keyword prompt string for Whisper.

    Returns a natural-language string of key terms (people, companies,
    entities) that Whisper can use as initial_prompt context.
    """
    now = time.monotonic()
    if _cache["keywords"] and (now - _cache["ts"]) < CACHE_TTL_SEC:
        return _cache["keywords"]

    if not os.path.isdir(BRAIN_DIR):
        logger.warning("Brain dir not found: %s", BRAIN_DIR)
        return ""

    t0 = time.monotonic()
    all_terms: list[str] = []

    # Priority 1: People files (most important for name recognition)
    # Priority 2: Meeting/Memo files (company names, deal names)
    # Priority 3: Other files (research, events)
    priority_files: list[tuple[int, str]] = []

    try:
        for fname in os.listdir(BRAIN_DIR):
            if not fname.endswith('.md'):
                continue
            if fname.startswith('[People]'):
                priority_files.append((0, fname))
            elif fname.startswith(('[Meetings]', '[Memos]')):
                priority_files.append((1, fname))
            elif fname.startswith(('[Research]', '[Events]', '[Decks]')):
                priority_files.append((2, fname))
    except OSError:
        logger.warning("Failed to list Brain dir", exc_info=True)
        return ""

    priority_files.sort(key=lambda x: x[0])

    for _prio, fname in priority_files:
        # Extract from filename
        all_terms.extend(_extract_names_from_filename(fname))

        # Read file content for frontmatter + body extraction
        fpath = os.path.join(BRAIN_DIR, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                content = f.read(4096)  # Only read first 4KB
            all_terms.extend(_extract_from_frontmatter(content))
            if _prio == 0:  # People files: also scan body
                all_terms.extend(_extract_from_body(content))
        except (OSError, UnicodeDecodeError):
            continue

    # Priority 0: Known entity terms Jerry uses constantly (prepend)
    entity_terms = [
        "Synergis Capital", "Synergis", "Current Equities",
        "UUL Global", "UUL", "良仓", "星航", "新航", "美航",
        "Nscale", "Jerry Shi", "Jerry", "Dora", "Owen",
        "Neuron Venture Partners", "Roboforce", "Packsmith",
        "Hankun", "AFLF", "Industry Reborn",
    ]
    all_terms = entity_terms + all_terms

    # Dedupe while preserving order, skip noise
    seen: set[str] = set()
    unique: list[str] = []
    for term in all_terms:
        term = term.strip().strip('()')
        if not term or len(term) < 2:
            continue
        # Skip single common English words
        if re.match(r'^[A-Za-z]+$', term) and term in _COMMON_SKIP:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(term)

    # Build natural language prompt (Whisper works better with sentences)
    result = ", ".join(unique)
    if len(result) > max_chars:
        # Prioritize: keep trimming from the end
        trimmed: list[str] = []
        length = 0
        for term in unique:
            addition = len(term) + 2  # ", "
            if length + addition > max_chars:
                break
            trimmed.append(term)
            length += addition
        result = ", ".join(trimmed)

    elapsed = time.monotonic() - t0
    logger.info(
        "Brain keyword scan: %d terms, %d chars, %.0fms",
        len(unique), len(result), elapsed * 1000,
    )

    _cache["keywords"] = result
    _cache["ts"] = now
    return result
