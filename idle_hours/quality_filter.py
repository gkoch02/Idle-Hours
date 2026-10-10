#!/usr/bin/env python3
"""Annotate cleaned quote candidates with quality heuristics."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from idle_hours import atomic_io
from idle_hours.clean_display_quotes import (
    BROKEN_HYPHENATION,
    EXPANSION_MAX_CHARS,
    HEADING_PREFIX,
    LEADING_BRACKET_TAIL,
    LEADING_CAPS_HEADING,
    LEADING_CHAPTER_HEADING,
    SECTION_BREAK,
    TRAILING_SPEAKER_CUE,
    unbalanced_quotes,
)
from idle_hours.jsonl_io import iter_jsonl

BASE_DIR = Path(__file__).resolve().parent


# Each pattern names a *modern / non-prose* register the panel should never
# show, and must match only that register (issue #296): not the verb in "the
# fearful work went on until nearly dawn", nor the "am" in "I am sure it was
# nearly ten o'clock".
BAD_PATTERNS = [
    # Schedule text ("working hours", "work shift", "nine to five"), not the
    # verb or noun "work" that any novel uses.
    (
        re.compile(
            r"\b(?:work(?:ing)?\s+(?:hours|schedules?|shifts?|weeks?|days?)|(?:nine|9)\s*(?:-|–|to)\s*(?:five|5))\b",
            re.IGNORECASE,
        ),
        "contains_work_schedule",
        45,
    ),
    # The modern clock suffix: bare ``am`` / ``pm`` after a number ("3 pm",
    # "10:30 am"). Never the verb ("I am"), which was every am/pm flag in the
    # shipped corpus before issue #296.
    (
        re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", re.IGNORECASE),
        "contains_modern_am_pm",
        45,
    ),
    # The dotted forms are period: "the 7.47 p.m. boat train" is how a 1920
    # timetable mystery states a time, and those sentences are most of the
    # off-minute corpus. A mild penalty ranks them below a clean alternative
    # in the same bucket without dropping them under the bake floor, which
    # the old 45-point penalty did to a fifth of the dotted-time rows.
    (
        re.compile(r"\b[ap]\.\s?m\.", re.IGNORECASE),
        "contains_dotted_am_pm",
        15,
    ),
    (re.compile(r"\b\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}\b"), "contains_time_range", 55),
    # A heading, not the words: "Chapter IV", "BOOK 2", "ACT", "Scene 3" —
    # never "the book I read" or "the last act of the play". Case-sensitive,
    # and a lone "I" only counts as a numeral when punctuation or the end of
    # the text follows it, because "the book I was reading" is the pronoun.
    (
        re.compile(
            r"\b(?:[Cc]hapter|[Bb]ook|[Aa]ct|[Ss]cene|CHAPTER|BOOK|ACT|SCENE)\s+"
            r"(?:(?:[IVXLCDM]{2,}|\d+)\b|I(?=[.:;,]|\s*$))"
            r"|\b(?:CHAPTER|BOOK|ACT|SCENE)\b",
        ),
        "contains_structural_label",
        35,
    ),
    (re.compile(r"\b(?:copyright|project gutenberg|ebook)\b", re.IGNORECASE), "contains_metadata", 55),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add quality annotations to cleaned quote candidates.")
    parser.add_argument("input", help="Cleaned candidate JSONL input")
    parser.add_argument(
        "--output",
        default="output/candidates-quality.jsonl",
        help="Output JSONL path",
    )
    return parser.parse_args()


def score_quote(display_quote: str, display_fragment: bool, cleanup_status: str) -> tuple[int, list[str]]:
    score = 100
    reasons: list[str] = []

    if display_fragment:
        score -= 30
        reasons.append("fragment")
    if cleanup_status not in ("complete_sentence", "expanded_with_context"):
        score -= 20
        reasons.append(cleanup_status)

    length = len(display_quote)
    if length < 50:
        score -= 20
        reasons.append("too_short")
    elif length < 80:
        score -= 8
        reasons.append("short")
    elif length > EXPANSION_MAX_CHARS:
        score -= 20
        reasons.append("too_long")
    elif length > 200:
        score -= 8
        reasons.append("long")

    digit_count = sum(ch.isdigit() for ch in display_quote)
    if digit_count >= 6:
        score -= 25
        reasons.append("digit_heavy")
    elif digit_count >= 3:
        score -= 10
        reasons.append("some_digits")

    # Deliberately mild: the rows this flags that survive the cleaner are
    # mostly plays, where speaker labels ("ROSALIND. How say you now?") are
    # part of the text. The chapter-title case it used to be the only guard
    # against is now stripped by the cleaner and penalised below.
    uppercase_ratio = sum(ch.isupper() for ch in display_quote) / max(len(display_quote), 1)
    if uppercase_ratio > 0.18:
        score -= 15
        reasons.append("uppercase_heavy")

    # Defence in depth behind the cleaner (issue #308): a chapter title or a
    # bare Roman-numeral heading still opening the excerpt ("XXXIV. Next
    # morning…", "—CONTINUATION OF THE ENIGMA The night wind…") is not prose,
    # and the same weight as a structural label puts it under the floor.
    if HEADING_PREFIX.match(display_quote) or LEADING_CAPS_HEADING.match(display_quote):
        score -= 35
        reasons.append("leading_heading")
    # The tail of a cut-off bracketed aside ("Looks at his watch] It's about…"): the
    # same structural residue, the same weight.
    if LEADING_BRACKET_TAIL.match(display_quote):
        score -= 35
        reasons.append("leading_bracket_tail")
    # A play's next speaker left at the end ("…the name of Ernest. JACK.").
    if TRAILING_SPEAKER_CUE.search(display_quote):
        score -= 35
        reasons.append("trailing_speaker_cue")
    # A chapter heading in ordinary case, which the cleaner cannot cut cleanly.
    if LEADING_CHAPTER_HEADING.match(display_quote):
        score -= 35
        reasons.append("leading_chapter_heading")
    # An excerpt that runs across a section break ("* * * * *").
    if SECTION_BREAK.search(display_quote):
        score -= 35
        reasons.append("section_break")
    # A word the source broke across a line ("forty- seven").
    if BROKEN_HYPHENATION.search(display_quote):
        score -= 20
        reasons.append("broken_hyphenation")

    for pattern, label, penalty in BAD_PATTERNS:
        if pattern.search(display_quote):
            score -= penalty
            reasons.append(label)

    if not display_quote.endswith((".", "!", "?", '"', "”", "'", "’")):
        score -= 10
        reasons.append("weak_ending")

    # Defence in depth behind the cleaner's balanced-run preference (issue
    # #297): a quotation mark with no partner is a visible flaw on the panel,
    # so a row that could not be cleaned ranks below a clean alternative.
    if unbalanced_quotes(display_quote):
        score -= 15
        reasons.append("unbalanced_quotes")

    return max(score, 0), reasons


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    rows = []
    for row in iter_jsonl(input_path):
        display_quote = row.get("display_quote") or ""
        quality_score, quality_flags = score_quote(
            display_quote,
            bool(row.get("display_fragment")),
            row.get("cleanup_status") or "unknown",
        )
        row["quality_score"] = quality_score
        row["quality_flags"] = quality_flags
        rows.append(row)

    atomic_io.atomic_write_lines(
        output_path, (json.dumps(row, ensure_ascii=False) for row in rows)
    )

    print(f"Wrote {len(rows)} quality-scored candidates to {output_path}")
    print(f"Rows below 50 score: {sum(1 for r in rows if r['quality_score'] < 50)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
