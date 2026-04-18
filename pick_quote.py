#!/usr/bin/env python3
"""Pick the best cleaned quote for a given time or fuzzy bucket."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from buckets import DEFAULT_BUCKET_MINUTES, bucket_for_time, neighbor_buckets

EXACT_MINUTE_PATTERNS = {
    "zero": ["o’clock", "oclock", "struck"],
    5: ["five minutes past", "five minutes after", "five past"],
    10: ["ten minutes past", "ten minutes after", "ten past"],
    15: ["quarter past"],
    20: ["twenty minutes past", "twenty past"],
    25: ["twenty-five minutes past", "twenty five minutes past", "twenty-five past", "twenty five past"],
    30: ["half past", "half-past", "11:30", "12:30"],
    35: ["thirty-five minutes past", "thirty five minutes past", "twenty-five minutes to", "twenty five minutes to", "twenty-five to", "twenty five to"],
    40: ["twenty minutes to", "twenty to"],
    45: ["quarter to"],
    50: ["ten minutes to", "ten to"],
    55: ["five minutes to", "five to"],
}

BASE_DIR = Path(__file__).resolve().parent

DIALOGUE_FILLER_PATTERNS = [
    "he said",
    "she said",
    "they said",
    "i said",
    "replied ",
    "asked ",
    "cried ",
    "answered ",
    "returned ",
]
WEAK_OPENING_PATTERNS = [
    "and ",
    "but ",
    "for ",
    "then ",
    "so ",
    "yet ",
    "or ",
]
PRONOUN_HEAVY_OPENINGS = [
    "he ",
    "she ",
    "they ",
    "it ",
    "his ",
    "her ",
    "their ",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pick the best LitClock quote for a time.")
    parser.add_argument(
        "--input",
        default="output/candidates-attributed.jsonl",
        help="Attributed and quality-scored candidate JSONL file.",
    )
    parser.add_argument(
        "--time",
        help="Time in HH:MM 24-hour format, for example 22:54.",
    )
    parser.add_argument(
        "--bucket",
        help="Explicit bucket like h10_just_before.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Optional random seed for stable picks among similarly scored quotes.",
    )
    parser.add_argument(
        "--min-quality",
        type=int,
        default=60,
        help="Minimum acceptable quality score before falling back to nearby buckets.",
    )
    parser.add_argument(
        "--overrides",
        default="selection_overrides.json",
        help="JSON overrides for manual boosts/bans/preferred bucket picks.",
    )
    return parser.parse_args()


def resolve_path(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def load_rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        normalized = row.get("normalized_time")
        if isinstance(normalized, str) and ":" in normalized:
            row["fuzzy_bucket"] = bucket_for_time(normalized)
        rows.append(row)
    return rows


def load_overrides(path: Path) -> dict:
    if not path.exists():
        return {"ban_source_ids": [], "boost_source_ids": [], "preferred_buckets": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def metadata_bonus(row: dict) -> int:
    has_author = bool(row.get("author"))
    has_title = bool(row.get("title"))
    if has_author and has_title:
        return -3
    if has_author or has_title:
        return -1
    return 2


def dialogue_penalty(row: dict) -> int:
    text = (row.get("display_quote") or "").lower()
    return 2 if any(pattern in text for pattern in DIALOGUE_FILLER_PATTERNS) else 0


def opening_penalty(row: dict) -> int:
    text = (row.get("display_quote") or "").strip().lower()
    if any(text.startswith(pattern) for pattern in WEAK_OPENING_PATTERNS):
        return 2
    if any(text.startswith(pattern) for pattern in PRONOUN_HEAVY_OPENINGS):
        return 1
    return 0


def override_bonus(row: dict, overrides: dict, bucket: str) -> int:
    source_id = str(row.get("source_id") or "")
    preferred = overrides.get("preferred_buckets", {}).get(bucket)
    if preferred and source_id == str(preferred):
        return -5
    if source_id in {str(x) for x in overrides.get("boost_source_ids", [])}:
        return -3
    return 0


def is_banned(row: dict, overrides: dict) -> bool:
    source_id = str(row.get("source_id") or "")
    return source_id in {str(x) for x in overrides.get("ban_source_ids", [])}


def parse_requested_minute(bucket: str, requested_time: str | None) -> int | None:
    if requested_time:
        minute = int(requested_time.split(":", 1)[1])
        rounded_minute = ((minute + 2) // 5) * 5
        return 0 if rounded_minute == 60 else rounded_minute
    state = bucket.split("_", 1)[1]
    return DEFAULT_BUCKET_MINUTES.get(state)


def infer_quote_minute(row: dict) -> int | None:
    normalized = row.get("normalized_time")
    if isinstance(normalized, str) and ":" in normalized:
        try:
            return int(normalized.split(":", 1)[1])
        except ValueError:
            pass

    lowered = (row.get("matched_text") or "").lower().replace("\n", " ")
    for minute, patterns in EXACT_MINUTE_PATTERNS.items():
        if any(pattern in lowered for pattern in patterns):
            return 0 if minute == "zero" else minute
    return None


def minute_distance_penalty(row: dict, bucket: str, requested_time: str | None) -> int:
    requested_minute = parse_requested_minute(bucket, requested_time)
    quote_minute = infer_quote_minute(row)
    if requested_minute is None or quote_minute is None:
        return 99
    return abs(requested_minute - quote_minute)


def score_row(row: dict, bucket: str, overrides: dict, requested_time: str | None = None) -> tuple:
    display = row.get("display_quote") or ""
    fragment_penalty = 1 if row.get("display_fragment") else 0
    cleanup_penalty = 0 if row.get("cleanup_status") == "complete_sentence" else 1
    matched = row.get("matched_text") or ""
    length_penalty = abs(len(display) - 140)
    exactness_bonus = 0
    lowered = matched.lower().replace("\n", " ")
    if "five minutes to" in lowered or "ten minutes to" in lowered or "fifty-five minutes past" in lowered:
        exactness_bonus = -2
    elif "quarter" in lowered or "half" in lowered:
        exactness_bonus = -1
    source_bonus = 0 if row.get("source_id") else 1
    quality_component = -(row.get("quality_score") or 0)
    minute_penalty = minute_distance_penalty(row, bucket, requested_time)
    return (
        fragment_penalty,
        cleanup_penalty,
        minute_penalty,
        metadata_bonus(row),
        dialogue_penalty(row),
        opening_penalty(row),
        source_bonus,
        override_bonus(row, overrides, bucket),
        quality_component,
        length_penalty + exactness_bonus,
        len(display),
    )


def pick_best(rows: list[dict], bucket: str, seed: int, min_quality: int, overrides: dict, requested_time: str | None = None) -> tuple[dict, str]:
    for candidate_bucket in neighbor_buckets(bucket):
        candidates = [
            row for row in rows
            if row.get("fuzzy_bucket") == candidate_bucket
            and row.get("display_quote")
            and not is_banned(row, overrides)
            and (row.get("quality_score") is None or row.get("quality_score", 0) >= min_quality)
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda row: score_row(row, candidate_bucket, overrides, requested_time))
        top_score = score_row(candidates[0], candidate_bucket, overrides, requested_time)
        top = [row for row in candidates if score_row(row, candidate_bucket, overrides, requested_time) == top_score]
        rng = random.Random(seed)
        return rng.choice(top), candidate_bucket
    raise SystemExit(f"No candidates found for bucket {bucket} or nearby buckets above quality {min_quality}")


def main() -> int:
    args = parse_args()
    if not args.time and not args.bucket:
        raise SystemExit("Provide --time or --bucket")
    bucket = args.bucket or bucket_for_time(args.time)
    rows = load_rows(resolve_path(args.input))
    overrides = load_overrides(resolve_path(args.overrides))
    best, resolved_bucket = pick_best(rows, bucket, args.seed, args.min_quality, overrides, args.time)
    output = {
        "requested_time": args.time,
        "bucket": bucket,
        "resolved_bucket": resolved_bucket,
        "used_fallback": resolved_bucket != bucket,
        "display_quote": best.get("display_quote"),
        "matched_text": best.get("matched_text"),
        "source_id": best.get("source_id"),
        "source_path": best.get("source_path"),
        "author": best.get("author"),
        "title": best.get("title"),
        "display_fragment": best.get("display_fragment"),
        "cleanup_status": best.get("cleanup_status"),
        "normalized_time": best.get("normalized_time"),
        "quality_score": best.get("quality_score"),
        "quality_flags": best.get("quality_flags"),
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
