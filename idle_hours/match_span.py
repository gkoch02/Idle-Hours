"""Where a row's ``matched_text`` sits in its ``display_quote`` (stdlib only).

The renderer bolds the matched time phrase, and only where it stands as whole
words: a phrase joined to a neighbour by a hyphen ("struck three-quarters",
"twenty-three o'clock") is not the time the row was filed under, so it is not
highlighted. The baker, the picker and the coverage report apply the same test
so a row the panel cannot highlight never reaches it (issue #411). This module
lives outside ``render_quote`` because they must not import Pillow.

The same three, and the miner, also share the gate on numeric times a
five-minute clock cannot honour (:func:`states_too_precise_a_time`).
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


# A numeric time is a timetable minute ("the 10.55 from Halford", "at 10.31
# a.m."), more precise than a clock that moves in five-minute steps. Only the
# quarter-hours read as loosely as "half past ten" does; any other minute is
# kept only when the sentence hedges it ("about 10.20", "soon after 4.05",
# "11.13 or thereabouts"). "about the 3.12" is the topic, not a hedge, and a
# second time offered as an alternative ("about 11.37 or 11.38") undoes one.
_NUMERIC_LOOSE_MINUTES = frozenset({0, 15, 30, 45})
_NUMERIC_HEDGE_BEFORE_RE = re.compile(
    r"(?:\b(?:about|around|nearly|almost|approximately|roughly|circa|towards?|getting\s+on\s+for|close\s+(?:on|upon|to))"
    r"\s+(?:at\s+)?"
    r"|\b(?:soon|shortly|just|a\s+little|a\s+few\s+minutes|a\s+minute\s+or\s+two|some\s*time|not\s+long|a\s+bit)"
    r"\s+(?:before|after|past)\s+)$",
    re.IGNORECASE,
)
# What may stand between the number and a qualifier after it: a clock suffix
# and punctuation ("6.35 p.m. or thereabouts", "about 11.37, or 11.38").
_NUMERIC_TAIL = r"(?:\s*[ap]\.?\s?m\.?)?[\s,;]*"
_NUMERIC_HEDGE_AFTER_RE = re.compile(_NUMERIC_TAIL + r"(?:or\s+so|or\s+thereabouts?|-ish)\b", re.IGNORECASE)
_NUMERIC_ALTERNATIVE_RE = re.compile(_NUMERIC_TAIL + r"or\s+(?:the\s+)?\d{1,2}[.:][0-5]\d\b", re.IGNORECASE)


def numeric_time_is_too_precise(text: str, number_start: int, number_end: int, minute: int) -> bool:
    """True when the numeric time at ``text[number_start:number_end]`` ("10.31",
    "11:13") names a minute the five-minute clock cannot honour: off the
    quarter-hours and not hedged by the sentence around it."""
    if minute in _NUMERIC_LOOSE_MINUTES:
        return False
    after = text[number_end : number_end + 40]
    if _NUMERIC_ALTERNATIVE_RE.match(after):
        return True
    before = text[max(0, number_start - 40) : number_start]
    return not (_NUMERIC_HEDGE_BEFORE_RE.search(before) or _NUMERIC_HEDGE_AFTER_RE.match(after))


_NUMERIC_MATCH_TYPES = frozenset({"digital", "dotted_time"})
_NUMERIC_TIME_RE = re.compile(r"\d{1,2}[.:][0-5]\d")


def states_too_precise_a_time(row: dict) -> bool:
    """Whether ``row``'s numeric time reads, as displayed, more precisely than
    the clock can show (:func:`numeric_time_is_too_precise`). Judged on
    ``display_quote``, because a hedge the cleaner cut away is not one the
    reader sees, and on the minute the quote prints. A row whose phrase cannot
    be found is left to :func:`has_display_match`."""
    if row.get("match_type") not in _NUMERIC_MATCH_TYPES:
        return False
    text = row.get("display_quote") or ""
    span = find_display_match(text, row.get("matched_text") or "")
    if span is None:
        return False
    number = _NUMERIC_TIME_RE.search(text, span.start(), span.end())
    if number is None:
        return False
    return numeric_time_is_too_precise(text, number.start(), number.end(), int(number.group(0)[-2:]))
