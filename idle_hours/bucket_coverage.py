#!/usr/bin/env python3
"""Report fuzzy bucket coverage for harvested Idle Hours candidates."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from idle_hours.buckets import BUCKET_ORDER, rederive_buckets
from idle_hours.jsonl_io import iter_jsonl
from idle_hours.pick_quote import (
    DEFAULT_OVERRIDES_PATH,
    _twin_texts,
    is_banned,
    load_overrides,
    normalize_display_text,
)

BASE_DIR = Path(__file__).resolve().parent


HOURS = list(range(1, 13))
STATES = BUCKET_ORDER

# The baker's quality floor (``bake_quote_database --min-quality``). Coverage
# counts what the panel can *display*, so it applies the same gate (issue
# #300): a bucket whose only row scores 55 is empty at runtime, and reporting
# it as covered hid five such buckets from the gap finder and the snapshot.
DEFAULT_MIN_QUALITY = 60
SPARSE_THRESHOLD = 3
THIN_THRESHOLD = 2


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
    parser.add_argument(
        "--min-quality",
        type=int,
        default=DEFAULT_MIN_QUALITY,
        help="Quality floor a row must clear to count as displayable (the baker's --min-quality).",
    )
    parser.add_argument(
        "--overrides",
        default=DEFAULT_OVERRIDES_PATH,
        help="selection_overrides.json whose bans exclude rows from the displayable counts.",
    )
    return parser.parse_args()


def load_rows(path: Path) -> list[dict]:
    return rederive_buckets(list(iter_jsonl(path)))


def expected_buckets() -> list[str]:
    return [f"h{hour}_{state}" for hour in HOURS for state in STATES]


def banned_twin_texts(rows: list[dict], overrides: dict | None) -> frozenset[str]:
    """Display texts the picker's per-row bans reach, twins included.

    ``ban_quote_keys`` names one ``source:line``, but the picker drops every
    row that shows the same text (issue #294) — the corpus carries one
    passage under several keys. Coverage has to follow the same rule or a
    bucket whose only quote was banned through a twin still reads as covered.
    """
    ban_keys = {str(k) for k in (overrides or {}).get("ban_quote_keys", [])}
    return _twin_texts(rows, ban_keys, set())[0]


def _banned(row: dict, overrides: dict | None, banned_texts: frozenset[str]) -> bool:
    if overrides and is_banned(row, overrides):
        return True
    return bool(banned_texts) and normalize_display_text(row.get("display_quote")) in banned_texts


def is_displayable(
    row: dict,
    min_quality: int,
    overrides: dict | None,
    banned_texts: frozenset[str] = frozenset(),
) -> bool:
    """Would the runtime picker ever be able to show ``row``?

    Mirrors the gates between the raw corpus and the panel: the baker's
    ``filter_rows`` (a bucket, a non-blank ``display_quote`` once the cleaner
    has set one, and the quality floor — a row with no score passes, as it
    does there) and the picker's
    bans, including the twins a per-row ban reaches (``banned_texts``, from
    :func:`banned_twin_texts`).
    """
    if not row.get("fuzzy_bucket"):
        return False
    # Gated only once the cleaner has run. Coverage is also run on merged,
    # pre-clean candidates to choose which sparse buckets to target, and
    # there no row has a ``display_quote`` yet — gating those would read
    # every bucket as empty. Same shape as the quality rule below: a row
    # with no score passes.
    if "display_quote" in row:
        display = row["display_quote"]
        if not isinstance(display, str) or not display.strip():
            return False
    quality = row.get("quality_score")
    if quality is not None and quality < min_quality:
        return False
    return not _banned(row, overrides, banned_texts)


def build_summary(rows: list[dict], *, min_quality: int = DEFAULT_MIN_QUALITY, overrides: dict | None = None) -> dict:
    """Summarise bucket coverage, classified by what the panel can display.

    ``bucket_counts`` (and everything derived from it: populated / empty /
    sparse / dense / ``coverage_percent``) count *displayable* rows — those
    that clear ``min_quality`` and are not banned — because a coverage
    number should describe what the clock can show (issue #300). The raw
    counts are kept alongside as ``raw_bucket_counts`` so the curator can
    still see that a bucket has material the baker dropped.
    """
    raw_rows: dict[str, list[dict]] = defaultdict(list)
    bucket_rows: dict[str, list[dict]] = defaultdict(list)
    daypart_counter = Counter()
    banned = 0
    banned_texts = banned_twin_texts(rows, overrides)
    for row in rows:
        bucket = row.get("fuzzy_bucket")
        if bucket:
            raw_rows[bucket].append(row)
            if is_displayable(row, min_quality, overrides, banned_texts):
                bucket_rows[bucket].append(row)
            elif _banned(row, overrides, banned_texts):
                banned += 1
        if row.get("daypart_bucket"):
            daypart_counter[row["daypart_bucket"]] += 1

    raw_counts = {bucket: len(raw_rows.get(bucket, [])) for bucket in expected_buckets()}
    counts = {bucket: len(bucket_rows.get(bucket, [])) for bucket in expected_buckets()}
    populated = {bucket: count for bucket, count in counts.items() if count > 0}
    empty = [bucket for bucket, count in counts.items() if count == 0]
    sparse = sorted(
        ((bucket, count) for bucket, count in populated.items() if count <= SPARSE_THRESHOLD),
        key=lambda item: (item[1], item[0]),
    )
    # ``thin``: populated but too small for the anti-repeat ledger to do
    # anything (it falls back to the full list) — the tier the gap finder
    # should also be targeting.
    thin = [(bucket, count) for bucket, count in sparse if count <= THIN_THRESHOLD]
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
        "displayable_rows": sum(counts.values()),
        "banned_rows": banned,
        "min_quality": min_quality,
        "total_expected_buckets": len(counts),
        "populated_bucket_count": len(populated),
        "raw_populated_bucket_count": sum(1 for count in raw_counts.values() if count > 0),
        "empty_bucket_count": len(empty),
        "coverage_percent": round((len(populated) / len(counts)) * 100, 2),
        "bucket_counts": counts,
        "raw_bucket_counts": raw_counts,
        "empty_buckets": empty,
        "sparse_buckets": [{"bucket": bucket, "count": count} for bucket, count in sparse],
        "thin_buckets": [{"bucket": bucket, "count": count} for bucket, count in thin],
        "dense_buckets": [{"bucket": bucket, "count": count} for bucket, count in dense[:25]],
        "daypart_counts": dict(daypart_counter.most_common()),
        "sample_quotes": sample_quotes,
    }


def render_markdown(summary: dict) -> str:
    lines = []
    lines.append("# Bucket Coverage Report")
    lines.append("")
    lines.append(f"- Total rows: **{summary['total_rows']}**")
    if "displayable_rows" in summary:
        lines.append(
            f"- Displayable rows (quality ≥ {summary['min_quality']}, not banned): "
            f"**{summary['displayable_rows']}**"
        )
    lines.append(f"- Expected buckets: **{summary['total_expected_buckets']}**")
    lines.append(f"- Populated buckets: **{summary['populated_bucket_count']}**")
    if "raw_populated_bucket_count" in summary:
        lines.append(f"- Populated before the quality floor / bans: **{summary['raw_populated_bucket_count']}**")
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
    overrides = load_overrides(Path(args.overrides).expanduser().resolve()) if args.overrides else None
    summary = build_summary(rows, min_quality=args.min_quality, overrides=overrides)

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
