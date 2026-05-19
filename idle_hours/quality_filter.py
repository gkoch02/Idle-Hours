#!/usr/bin/env python3
"""Annotate cleaned quote candidates with quality heuristics."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from idle_hours.jsonl_io import iter_jsonl

BASE_DIR = Path(__file__).resolve().parent


BAD_PATTERNS = [
    (re.compile(r"\bwork\b", re.IGNORECASE), "contains_work_schedule", 45),
    (re.compile(r"\b(?:a\.m\.|p\.m\.|am|pm)\b", re.IGNORECASE), "contains_modern_am_pm", 45),
    (re.compile(r"\b\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}\b"), "contains_time_range", 55),
    (re.compile(r"\b(?:chapter|book|act|scene)\b", re.IGNORECASE), "contains_structural_label", 35),
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
    elif length > 260:
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

    uppercase_ratio = sum(ch.isupper() for ch in display_quote) / max(len(display_quote), 1)
    if uppercase_ratio > 0.18:
        score -= 15
        reasons.append("uppercase_heavy")

    for pattern, label, penalty in BAD_PATTERNS:
        if pattern.search(display_quote):
            score -= penalty
            reasons.append(label)

    if not display_quote.endswith((".", "!", "?", '"', "”", "'", "’")):
        score -= 10
        reasons.append("weak_ending")

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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Wrote {len(rows)} quality-scored candidates to {output_path}")
    print(f"Rows below 50 score: {sum(1 for r in rows if r['quality_score'] < 50)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
