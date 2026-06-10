#!/usr/bin/env python3
"""Fix substring-collision time metadata like 'five minutes' inside 'thirty-five minutes'.

MIGRATION / REPAIR TOOL. The current ``gutenberg_time_miner.py`` regex
captures the longest *standard* time phrase (regex alternation tries compound
number forms like ``thirty-five`` before the bare ``five``), so fresh harvests
mostly do not produce substring-collision rows — but the archaic reversed
compound ("five-and-twenty minutes past eight" = 8:25) still slips through as
the bare trailing phrase ("twenty minutes past eight" = 8:20), so this script
stays in the pipeline to repair that class. New hand-curated content fixes
should go in ``assets/content_overrides.json`` (applied by
``apply_content_overrides.py``) so they survive pipeline re-runs.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from idle_hours.buckets import minute_bucket as bucket_for_minute
from idle_hours.jsonl_io import iter_jsonl

BASE_DIR = Path(__file__).resolve().parent


NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}

TIME_PATTERN = re.compile(
    r"\b(?P<minute_word>"
    # Archaic reversed compound first: "five-and-twenty minutes past seven"
    # (= 25). Victorian-era texts use this form heavily; capturing only the
    # trailing "twenty minutes past seven" mis-tags the row by five minutes.
    r"(?:one|two|three|four|five|six|seven|eight|nine)[- ]and[- ](?:twenty|thirty|forty|fifty)"
    r"|(?:twenty|thirty|forty|fifty)(?:[- ]\s*(?:one|two|three|four|five|six|seven|eight|nine))?"
    r"|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen"
    r"|sixteen|seventeen|eighteen|nineteen"
    r")\s+minutes?\s+(?P<relation>past|to)\s+(?P<hour_word>one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b",
    re.IGNORECASE,
)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fix substring-collision time matches in JSONL corpus rows.")
    parser.add_argument("input", help="Input JSONL file")
    parser.add_argument("--output", default=None, help="Output path; defaults to in-place overwrite")
    return parser.parse_args()


def parse_number_word(text: str) -> int | None:
    text = text.lower().replace('-', ' ').strip()
    if text in NUMBER_WORDS:
        return NUMBER_WORDS[text]
    parts = text.split()
    if len(parts) == 2 and parts[0] in NUMBER_WORDS and parts[1] in NUMBER_WORDS:
        return NUMBER_WORDS[parts[0]] + NUMBER_WORDS[parts[1]]
    # Archaic reversed compound: "five and twenty" = 25.
    if (
        len(parts) == 3
        and parts[1] == 'and'
        and parts[0] in NUMBER_WORDS
        and parts[2] in NUMBER_WORDS
    ):
        return NUMBER_WORDS[parts[0]] + NUMBER_WORDS[parts[2]]
    return None


def infer_time_from_quote(display_quote: str):
    match = TIME_PATTERN.search(' '.join(display_quote.split()))
    if not match:
        return None
    minute_word = match.group('minute_word')
    relation = match.group('relation').lower()
    hour_word = match.group('hour_word').lower()
    minute_value = parse_number_word(minute_word)
    hour_value = parse_number_word(hour_word)
    if minute_value is None or hour_value is None:
        return None
    if relation == 'past':
        hour = hour_value
        minute = minute_value
    else:
        hour = 12 if hour_value == 1 else hour_value - 1
        minute = 60 - minute_value
    bucket_hour = hour
    if ((minute + 2) // 5) * 5 == 60:
        bucket_hour = (hour % 12) + 1
    return {
        'matched_text': match.group(0),
        'hour': hour,
        'minute': minute,
        'normalized_time': f"{hour:02d}:{minute:02d}",
        'fuzzy_bucket': f"h{bucket_hour}_{bucket_for_minute(minute)}",
    }


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = (Path(args.output).expanduser().resolve()) if args.output else input_path
    rows = []
    fixed = 0
    for row in iter_jsonl(input_path):
        display_quote = row.get('display_quote') or ''
        inferred = infer_time_from_quote(display_quote)
        if inferred:
            current_matched = ' '.join((row.get('matched_text') or '').split()).lower()
            inferred_matched = inferred['matched_text'].lower()
            if current_matched and current_matched in inferred_matched and current_matched != inferred_matched:
                row.update(inferred)
                fixed += 1
        rows.append(row)
    with output_path.open('w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(f'Fixed {fixed} substring-collision rows')
    print(f'Wrote {len(rows)} rows to {output_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
