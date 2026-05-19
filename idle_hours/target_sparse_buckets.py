#!/usr/bin/env python3
"""Target sparse fuzzy-clock buckets with bucket-specific phrase searches."""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


HOUR_WORDS = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
}

STATE_TEMPLATES = {
    "five_past": [
        ("five past {hour}", "five_past"),
        ("five minutes past {hour}", "five_past"),
        ("five minutes after {hour}", "five_past"),
    ],
    "ten_past": [
        ("ten past {hour}", "ten_past"),
        ("ten minutes past {hour}", "ten_past"),
        ("ten minutes after {hour}", "ten_past"),
    ],
    "quarter_past": [
        ("quarter past {hour}", "quarter_past"),
        ("fifteen minutes past {hour}", "quarter_past"),
    ],
    "twenty_past": [
        ("twenty past {hour}", "twenty_past"),
        ("twenty minutes past {hour}", "twenty_past"),
    ],
    "twenty_five_past": [
        ("twenty-five past {hour}", "twenty_five_past"),
        ("twenty five past {hour}", "twenty_five_past"),
        ("twenty-five minutes past {hour}", "twenty_five_past"),
        ("twenty five minutes past {hour}", "twenty_five_past"),
    ],
    "half_past": [
        ("half past {hour}", "half_past"),
        ("half-past {hour}", "half_past"),
        ("thirty minutes past {hour}", "half_past"),
    ],
    "twenty_five_to": [
        ("twenty-five to {next_hour}", "twenty_five_to"),
        ("twenty five to {next_hour}", "twenty_five_to"),
        ("twenty-five minutes to {next_hour}", "twenty_five_to"),
        ("twenty five minutes to {next_hour}", "twenty_five_to"),
        ("thirty-five minutes past {hour}", "twenty_five_to"),
        ("thirty five minutes past {hour}", "twenty_five_to"),
    ],
    "twenty_to": [
        ("twenty to {next_hour}", "twenty_to"),
        ("twenty minutes to {next_hour}", "twenty_to"),
        ("forty minutes past {hour}", "twenty_to"),
    ],
    "quarter_to": [
        ("quarter to {next_hour}", "quarter_to"),
        ("fifteen minutes to {next_hour}", "quarter_to"),
    ],
    "ten_to": [
        ("ten to {next_hour}", "ten_to"),
        ("ten minutes to {next_hour}", "ten_to"),
        ("fifty minutes past {hour}", "ten_to"),
    ],
    "five_to": [
        ("five to {next_hour}", "five_to"),
        ("five minutes to {next_hour}", "five_to"),
        ("fifty-five minutes past {hour}", "five_to"),
        ("almost {next_hour}", "five_to"),
        ("nearly {next_hour}", "five_to"),
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search cached Gutenberg texts for sparse-bucket phrases.")
    parser.add_argument("coverage_json", help="Path to bucket coverage JSON output.")
    parser.add_argument("--search-dir", default="data/gutenberg", help="Directory of cached Gutenberg .txt files.")
    parser.add_argument("--max-buckets", type=int, default=24, help="How many sparse/empty buckets to target.")
    parser.add_argument(
        "--output",
        default="output/targeted-candidates.jsonl",
        help="Output JSONL for targeted candidate matches.",
    )
    return parser.parse_args()


def expected_targets(coverage: dict, max_buckets: int) -> list[str]:
    empties = coverage.get("empty_buckets", [])
    sparse = [item["bucket"] for item in coverage.get("sparse_buckets", [])]
    ordered = empties + sparse
    deduped = []
    seen = set()
    for bucket in ordered:
        if bucket not in seen:
            deduped.append(bucket)
            seen.add(bucket)
        if len(deduped) >= max_buckets:
            break
    return deduped


def templates_for_bucket(bucket: str) -> list[tuple[str, str]]:
    hour_part, state = bucket.split("_", 1)
    hour = int(hour_part[1:])
    next_hour = 1 if hour == 12 else hour + 1
    hour_word = HOUR_WORDS[hour]
    next_hour_word = HOUR_WORDS[next_hour]
    templates = STATE_TEMPLATES.get(state, [])
    return [
        (template.format(hour=hour_word, next_hour=next_hour_word), implied_state)
        for template, implied_state in templates
    ]


def sentence_window(text: str, start: int, end: int, context_chars: int = 180) -> tuple[str, str, int]:
    left = max(0, start - context_chars)
    right = min(len(text), end + context_chars)
    context = " ".join(text[left:right].split())
    sentence_start = max(text.rfind(".", 0, start), text.rfind("\n", 0, start), text.rfind("!", 0, start), text.rfind("?", 0, start))
    sentence_end_candidates = [text.find(tok, end) for tok in (".", "\n", "!", "?") if text.find(tok, end) != -1]
    sentence_end = min(sentence_end_candidates) if sentence_end_candidates else len(text)
    quote = " ".join(text[sentence_start + 1 : sentence_end + 1].split())
    line_number = text.count("\n", 0, start) + 1
    return quote, context, line_number


def search_bucket(bucket: str, search_dir: Path) -> list[dict]:
    parts = bucket.split("_", 1)
    hour = int(parts[0][1:])
    templates = templates_for_bucket(bucket)
    if not templates:
        return []
    patterns = [
        (re.compile(r"\b" + re.escape(phrase).replace(r"\ ", r"\s+") + r"\b", re.IGNORECASE), phrase, implied_state)
        for phrase, implied_state in templates
    ]
    results = []
    for path in sorted(search_dir.rglob("*.txt")):
        text = path.read_text(encoding="utf-8", errors="replace")
        seen_positions = set()
        for pattern, phrase, implied_state in patterns:
            for match in pattern.finditer(text):
                pos = (match.start(), match.end(), implied_state)
                if pos in seen_positions:
                    continue
                seen_positions.add(pos)
                quote, context, line_number = sentence_window(text, match.start(), match.end())
                results.append(
                    {
                        "source_path": str(path),
                        "source_id": path.stem.removeprefix("pg") if path.stem.startswith("pg") else None,
                        "target_bucket": bucket,
                        "resolved_bucket": f"h{hour}_{implied_state}",
                        "search_phrase": phrase,
                        "matched_text": match.group(0),
                        "quote_text": quote,
                        "context_text": context,
                        "line_number": line_number,
                        "match_start": match.start(),
                        "match_end": match.end(),
                    }
                )
    return results


def main() -> int:
    args = parse_args()
    coverage_path = Path(args.coverage_json).expanduser()
    if not coverage_path.is_absolute():
        coverage_path = BASE_DIR / coverage_path
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    targets = expected_targets(coverage, args.max_buckets)
    search_dir = Path(args.search_dir).expanduser()

    all_results = []
    per_bucket = defaultdict(int)
    resolved_counts = defaultdict(int)
    for bucket in targets:
        bucket_results = search_bucket(bucket, search_dir)
        all_results.extend(bucket_results)
        per_bucket[bucket] = len(bucket_results)
        for row in bucket_results:
            resolved_counts[row["resolved_bucket"]] += 1

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in all_results:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Targeted buckets searched: {len(targets)}")
    print(f"Targeted candidates found: {len(all_results)}")
    for bucket in targets:
        print(f"{bucket}: {per_bucket[bucket]}")
    print("Resolved buckets:")
    for bucket in sorted(resolved_counts):
        print(f"  {bucket}: {resolved_counts[bucket]}")
    print(f"Output: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
