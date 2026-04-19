#!/usr/bin/env python3
"""Enrich corpus rows with title/author metadata parsed from Gutenberg headers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonl_io import iter_jsonl

BASE_DIR = Path(__file__).resolve().parent


HEADER_SCAN_LINES = 120


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add source metadata to corpus rows.")
    parser.add_argument("input", help="Input JSONL corpus file")
    parser.add_argument(
        "--output",
        default="assets/candidates-attributed.jsonl",
        help="Output JSONL path for the packaged runtime dataset",
    )
    parser.add_argument(
        "--gutenberg-dir",
        default="data/gutenberg",
        help="Directory containing cached Gutenberg texts",
    )
    return parser.parse_args()


def parse_header(path: Path) -> tuple[str | None, str | None]:
    title = None
    author = None
    if not path.exists():
        return title, author
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:HEADER_SCAN_LINES]:
        stripped = line.strip()
        if stripped.startswith("Title: ") and not title:
            title = stripped.replace("Title: ", "", 1).strip()
        elif stripped.startswith("Author: ") and not author:
            author = stripped.replace("Author: ", "", 1).strip()
        if title and author:
            break
    return title, author


def main() -> int:
    args = parse_args()
    input_path = (BASE_DIR / args.input).expanduser() if not Path(args.input).is_absolute() else Path(args.input).expanduser()
    output_path = (BASE_DIR / args.output).expanduser() if not Path(args.output).is_absolute() else Path(args.output).expanduser()
    gutenberg_dir = Path(args.gutenberg_dir).expanduser()

    rows = []
    metadata_cache: dict[str, tuple[str | None, str | None]] = {}
    for row in iter_jsonl(input_path):
        source_id = row.get("source_id")
        title = row.get("title")
        author = row.get("author")
        if source_id and (not title or not author):
            if source_id not in metadata_cache:
                metadata_cache[source_id] = parse_header(gutenberg_dir / f"pg{source_id}.txt")
            parsed_title, parsed_author = metadata_cache[source_id]
            title = title or parsed_title
            author = author or parsed_author
        row["title"] = title
        row["author"] = author
        rows.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    enriched = sum(1 for row in rows if row.get("title") or row.get("author"))
    print(f"Wrote {len(rows)} attributed rows to {output_path}")
    print(f"Rows with attribution metadata: {enriched}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
