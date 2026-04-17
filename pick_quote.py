#!/usr/bin/env python3
"""Pick the best cleaned quote for a given time or fuzzy bucket."""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

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


def minute_bucket(minute: int) -> str:
    if minute == 0:
        return "exact"
    if 1 <= minute <= 5:
        return "just_after"
    if 6 <= minute <= 14:
        return "early_past"
    if 15 <= minute <= 19:
        return "quarter_pastish"
    if 20 <= minute <= 39:
        return "half_pastish"
    if 40 <= minute <= 44:
        return "late_past"
    if 45 <= minute <= 49:
        return "quarter_toish"
    if 50 <= minute <= 59:
        return "just_before"
    raise ValueError(f"Unexpected minute: {minute}")


def bucket_for_time(time_str: str) -> str:
    hour24, minute = [int(part) for part in time_str.split(":", 1)]
    hour12 = hour24 % 12
    if hour12 == 0:
        hour12 = 12
    return f"h{hour12}_{minute_bucket(minute)}"


def resolve_path(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def load_rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
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


def score_row(row: dict, bucket: str, overrides: dict) -> tuple:
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
    return (
        fragment_penalty,
        cleanup_penalty,
        metadata_bonus(row),
        dialogue_penalty(row),
        opening_penalty(row),
        source_bonus,
        override_bonus(row, overrides, bucket),
        quality_component,
        length_penalty + exactness_bonus,
        len(display),
    )


def neighbor_buckets(bucket: str) -> list[str]:
    hour_part, state = bucket.split("_", 1)
    order = [
        "exact",
        "just_after",
        "early_past",
        "quarter_pastish",
        "half_pastish",
        "late_past",
        "quarter_toish",
        "just_before",
    ]
    idx = order.index(state)
    neighbors = [bucket]
    for distance in range(1, len(order)):
        if idx - distance >= 0:
            neighbors.append(f"{hour_part}_{order[idx - distance]}")
        if idx + distance < len(order):
            neighbors.append(f"{hour_part}_{order[idx + distance]}")
    return neighbors


def pick_best(rows: list[dict], bucket: str, seed: int, min_quality: int, overrides: dict) -> tuple[dict, str]:
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
        candidates.sort(key=lambda row: score_row(row, candidate_bucket, overrides))
        top_score = score_row(candidates[0], candidate_bucket, overrides)
        top = [row for row in candidates if score_row(row, candidate_bucket, overrides) == top_score]
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
    best, resolved_bucket = pick_best(rows, bucket, args.seed, args.min_quality, overrides)
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
