#!/usr/bin/env python3
"""Report fuzzy bucket coverage for harvested Idle Hours candidates."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from idle_hours.buckets import BUCKET_ORDER, bucket_for_time
from idle_hours.jsonl_io import iter_jsonl

BASE_DIR = Path(__file__).resolve().parent


HOURS = list(range(1, 13))
STATES = BUCKET_ORDER


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize fuzzy bucket coverage.")
    parser.add_argument(
        "input",
        help="Merged candidate JSONL file.",
    )
    parser.add_argument(
        "--output-json",
        default="output/bucket-coverage.json",
        help="Coverage summary JSON output path.",
    )
    parser.add_argument(
        "--output-md",
        default="output/bucket-coverage.md",
        help="Coverage markdown output path.",
    )
    return parser.parse_args()


def load_rows(path: Path) -> list[dict]:
    rows = []
    for row in iter_jsonl(path):
        normalized = row.get("normalized_time")
        if isinstance(normalized, str) and ":" in normalized:
            try:
                row["fuzzy_bucket"] = bucket_for_time(normalized)
            except (ValueError, KeyError):
                pass
        rows.append(row)
    return rows


def expected_buckets() -> list[str]:
    return [f"h{hour}_{state}" for hour in HOURS for state in STATES]


def build_summary(rows: list[dict]) -> dict:
    bucket_rows: dict[str, list[dict]] = defaultdict(list)
    daypart_counter = Counter()
    for row in rows:
        bucket = row.get("fuzzy_bucket")
        if bucket:
            bucket_rows[bucket].append(row)
        if row.get("daypart_bucket"):
            daypart_counter[row["daypart_bucket"]] += 1

    counts = {bucket: len(bucket_rows.get(bucket, [])) for bucket in expected_buckets()}
    populated = {bucket: count for bucket, count in counts.items() if count > 0}
    empty = [bucket for bucket, count in counts.items() if count == 0]
    sparse = sorted(((bucket, count) for bucket, count in populated.items() if count <= 3), key=lambda item: (item[1], item[0]))
    dense = sorted(populated.items(), key=lambda item: (-item[1], item[0]))

    sample_quotes = {}
    for bucket, bucket_list in bucket_rows.items():
        sample_quotes[bucket] = [
            {
                "quote_text": row.get("quote_text"),
                "matched_text": row.get("matched_text"),
                "source_id": row.get("source_id"),
            }
            for row in bucket_list[:3]
        ]

    return {
        "total_rows": len(rows),
        "total_expected_buckets": len(counts),
        "populated_bucket_count": len(populated),
        "empty_bucket_count": len(empty),
        "coverage_percent": round((len(populated) / len(counts)) * 100, 2),
        "bucket_counts": counts,
        "empty_buckets": empty,
        "sparse_buckets": [{"bucket": bucket, "count": count} for bucket, count in sparse],
        "dense_buckets": [{"bucket": bucket, "count": count} for bucket, count in dense[:25]],
        "daypart_counts": dict(daypart_counter.most_common()),
        "sample_quotes": sample_quotes,
    }


def render_markdown(summary: dict) -> str:
    lines = []
    lines.append("# Bucket Coverage Report")
    lines.append("")
    lines.append(f"- Total rows: **{summary['total_rows']}**")
    lines.append(f"- Expected buckets: **{summary['total_expected_buckets']}**")
    lines.append(f"- Populated buckets: **{summary['populated_bucket_count']}**")
    lines.append(f"- Empty buckets: **{summary['empty_bucket_count']}**")
    lines.append(f"- Coverage: **{summary['coverage_percent']}%**")
    lines.append("")

    lines.append("## Strongest buckets")
    lines.append("")
    for item in summary["dense_buckets"][:15]:
        lines.append(f"- `{item['bucket']}`: {item['count']}")
    lines.append("")

    lines.append("## Sparse buckets (<=3 quotes)")
    lines.append("")
    for item in summary["sparse_buckets"][:40]:
        lines.append(f"- `{item['bucket']}`: {item['count']}")
    lines.append("")

    lines.append("## Empty buckets")
    lines.append("")
    chunk = []
    for bucket in summary["empty_buckets"]:
        chunk.append(f"`{bucket}`")
        if len(chunk) == 8:
            lines.append("- " + ", ".join(chunk))
            chunk = []
    if chunk:
        lines.append("- " + ", ".join(chunk))
    lines.append("")

    lines.append("## Daypart counts")
    lines.append("")
    for key, value in summary["daypart_counts"].items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    rows = load_rows(Path(args.input).expanduser().resolve())
    summary = build_summary(rows)

    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    output_md.write_text(render_markdown(summary), encoding="utf-8")

    print(f"Coverage: {summary['populated_bucket_count']}/{summary['total_expected_buckets']} buckets populated ({summary['coverage_percent']}%)")
    print(f"Empty buckets: {summary['empty_bucket_count']}")
    print(f"Sparse buckets: {len(summary['sparse_buckets'])}")
    print(f"JSON: {output_json}")
    print(f"Markdown: {output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
