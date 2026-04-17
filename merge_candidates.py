#!/usr/bin/env python3
"""Merge and dedupe harvested author-clock candidates."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
from typing import Iterable


@dataclass
class Record:
    raw: dict
    canonical_quote: str
    canonical_context: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge and dedupe quote candidate JSONL files.")
    parser.add_argument("inputs", nargs="+", help="Input JSONL files.")
    parser.add_argument(
        "--output",
        default="output/candidates-merged.jsonl",
        help="Output JSONL path for deduped records.",
    )
    parser.add_argument(
        "--summary",
        default="output/candidates-merged-summary.json",
        help="Where to write summary stats.",
    )
    return parser.parse_args()


def normalize_text(text: str) -> str:
    text = text.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\s+", " ", text.strip().lower())
    text = re.sub(r"^[\"'“”‘’\(\[]+", "", text)
    text = re.sub(r"[\"'“”‘’\)\]\.,;:!?-]+$", "", text)
    return text


def iter_records(paths: Iterable[str]) -> Iterable[Record]:
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            quote = raw.get("quote_text") or ""
            context = raw.get("context_text") or ""
            yield Record(raw=raw, canonical_quote=normalize_text(quote), canonical_context=normalize_text(context))


def dedupe(records: Iterable[Record]) -> tuple[list[dict], dict]:
    seen: dict[tuple, dict] = {}
    duplicates = 0
    source_counter = Counter()
    match_counter = Counter()
    bucket_counter = Counter()

    for record in records:
        raw = record.raw
        source_counter[raw.get("source_id") or raw.get("source_path")] += 1
        match_counter[raw.get("match_type")] += 1
        if raw.get("fuzzy_bucket"):
            bucket_counter[raw["fuzzy_bucket"]] += 1

        key = (
            raw.get("normalized_time"),
            raw.get("fuzzy_bucket"),
            raw.get("daypart_bucket"),
            record.canonical_quote,
        )
        existing = seen.get(key)
        if existing is None:
            enriched = dict(raw)
            enriched["canonical_quote"] = record.canonical_quote
            enriched["canonical_context"] = record.canonical_context
            seen[key] = enriched
            continue

        duplicates += 1
        existing_len = len(existing.get("context_text") or "")
        challenger_len = len(raw.get("context_text") or "")
        if challenger_len > existing_len:
            enriched = dict(raw)
            enriched["canonical_quote"] = record.canonical_quote
            enriched["canonical_context"] = record.canonical_context
            seen[key] = enriched

    merged = sorted(
        seen.values(),
        key=lambda row: (
            row.get("normalized_time") or "",
            row.get("daypart_bucket") or "",
            row.get("source_id") or row.get("source_path") or "",
            row.get("canonical_quote") or "",
        ),
    )
    summary = {
        "input_rows": sum(source_counter.values()),
        "deduped_rows": len(merged),
        "duplicates_removed": duplicates,
        "sources_seen": len(source_counter),
        "match_type_counts": dict(match_counter.most_common()),
        "top_buckets": dict(bucket_counter.most_common(25)),
        "top_sources": dict(source_counter.most_common(25)),
    }
    return merged, summary


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    args = parse_args()
    merged, summary = dedupe(iter_records(args.inputs))
    output_path = (BASE_DIR / args.output).expanduser() if not Path(args.output).is_absolute() else Path(args.output).expanduser()
    summary_path = (BASE_DIR / args.summary).expanduser() if not Path(args.summary).is_absolute() else Path(args.summary).expanduser()
    write_jsonl(output_path, merged)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {summary['deduped_rows']} deduped candidates to {output_path}")
    print(f"Removed {summary['duplicates_removed']} duplicates from {summary['input_rows']} input rows")
    print(f"Summary written to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
