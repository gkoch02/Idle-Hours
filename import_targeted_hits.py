#!/usr/bin/env python3
"""Convert targeted sparse-bucket hits into mergeable candidate rows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


STATE_TO_MINUTE = {
    "exact": 0,
    "just_after": 3,
    "early_past": 8,
    "quarter_pastish": 15,
    "half_pastish": 30,
    "late_past": 25,
    "quarter_toish": 45,
    "just_before": 57,
}

DAYPARTS = {
    0: "midnight",
    1: "night",
    2: "night",
    3: "night",
    4: "night",
    5: "dawn",
    6: "dawn",
    7: "morning",
    8: "morning",
    9: "morning",
    10: "morning",
    11: "morning",
    12: "noon",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert targeted sparse-bucket hits into candidate rows.")
    parser.add_argument("input", help="targeted-candidates.jsonl path")
    parser.add_argument(
        "--output",
        default="projects/author-clock/output/targeted-candidates-importable.jsonl",
        help="Output JSONL path",
    )
    return parser.parse_args()


def minute_for_bucket(bucket: str) -> tuple[int, int, str]:
    hour_part, state = bucket.split("_", 1)
    hour12 = int(hour_part[1:])
    minute = STATE_TO_MINUTE[state]
    return hour12, minute, state


def row_from_targeted(raw: dict) -> dict:
    resolved_bucket = raw["resolved_bucket"]
    hour12, minute, _state = minute_for_bucket(resolved_bucket)
    normalized_time = f"{hour12:02d}:{minute:02d}"
    daypart = DAYPARTS.get(hour12, "night")
    return {
        "source_path": raw.get("source_path"),
        "source_id": raw.get("source_id"),
        "match_type": "targeted_phrase",
        "matched_text": raw.get("matched_text"),
        "quote_text": raw.get("quote_text"),
        "context_text": raw.get("context_text"),
        "hour": hour12,
        "minute": minute,
        "normalized_time": normalized_time,
        "fuzzy_bucket": resolved_bucket,
        "daypart_bucket": daypart,
        "line_number": raw.get("line_number"),
        "match_start": raw.get("match_start"),
        "match_end": raw.get("match_end"),
        "search_phrase": raw.get("search_phrase"),
        "target_bucket": raw.get("target_bucket"),
        "resolved_bucket": resolved_bucket,
    }


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser()
    output_path = Path(args.output).expanduser()
    rows = []
    for line in input_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(row_from_targeted(json.loads(line)))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} importable targeted hits to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
