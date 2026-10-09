"""Where a row's ``matched_text`` sits in its ``display_quote`` (stdlib only).

The renderer bolds the matched time phrase, and only where it stands as whole
words: a phrase joined to a neighbour by a hyphen ("struck three-quarters",
"twenty-three o'clock") is not the time the row was filed under, so it is not
highlighted. The baker, the picker and the coverage report apply the same test
so a row the panel cannot highlight never reaches it (issue #411). This module
lives outside ``render_quote`` because they must not import Pillow.
"""

from __future__ import annotations

import functools
import re

TIME_PHRASE_PREFIXES = [
    "five minutes past",
    "ten minutes past",
    "quarter past",
    "twenty minutes past",
    "twenty-five minutes past",
    "half past",
    "twenty-five minutes to",
    "twenty minutes to",
    "quarter to",
    "ten minutes to",
    "five minutes to",
]

# Pre-compiled longest-first so the first prefix that matches the candidate
# wins ("twenty-five minutes past" beats "minutes past" for the same row).
# Order is load-bearing — keep this list sorted by descending prefix length.
_TIME_PHRASE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        prefix,
        re.compile(
            rf"(?<![A-Za-z0-9])(?<![A-Za-z0-9]-){re.escape(prefix)}"
            rf"(?:[ ,]+[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)?(?![A-Za-z0-9])(?!-[A-Za-z0-9])",
            re.IGNORECASE,
        ),
    )
    for prefix in sorted(TIME_PHRASE_PREFIXES, key=len, reverse=True)
]


@functools.lru_cache(maxsize=4096)
def _direct_match_pattern(normalized_match: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![A-Za-z0-9])(?<![A-Za-z0-9]-){re.escape(normalized_match)}(?![A-Za-z0-9])(?!-[A-Za-z0-9])",
        re.IGNORECASE,
    )


def resolve_display_match(text: str, match_text: str) -> str:
    normalized_match = " ".join((match_text or "").split()).strip()
    if not normalized_match:
        return ""

    direct = _direct_match_pattern(normalized_match).search(text)
    if direct:
        return direct.group(0)

    lower_match = normalized_match.lower()
    for prefix, pattern in _TIME_PHRASE_PATTERNS:
        if not lower_match.startswith(prefix):
            continue
        for m in pattern.finditer(text):
            candidate = m.group(0).strip(" ,.;:!?")
            if candidate.lower().startswith(lower_match):
                return candidate

    return normalized_match


def find_display_match(text: str, match_text: str) -> re.Match[str] | None:
    """The span of ``text`` the renderer highlights for ``match_text``, or None."""
    normalized_match = resolve_display_match(text, match_text)
    if not normalized_match:
        return None
    return _direct_match_pattern(normalized_match).search(text)


def has_display_match(row: dict) -> bool:
    """Whether the panel can highlight ``row``'s matched phrase in its ``display_quote``."""
    return find_display_match(row.get("display_quote") or "", row.get("matched_text") or "") is not None
