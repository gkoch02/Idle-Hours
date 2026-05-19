#!/usr/bin/env python3
"""Repair rows whose ``fuzzy_bucket`` uses legacy 8-state names.

LEGACY MIGRATION TOOL. Both classes of damage this script repairs are now
prevented at the source: the shared ``buckets.py`` module means fresh mines
cannot produce obsolete state names (``just_after``, ``early_past``,
``quarter_pastish``, ``half_pastish``, ``late_past``, ``just_before``,
``quarter_toish``), and ``gutenberg_time_miner.py`` now collapses whitespace
in ``matched_text`` before writing the candidate row. This script is retained
only to repair rows harvested by earlier revisions of the pipeline. New
hand-curated content fixes should go in ``assets/content_overrides.json``
(applied by ``apply_content_overrides.py``) so they survive pipeline re-runs.

For each row with a known ``hour`` and ``minute`` whose ``fuzzy_bucket``
carries a legacy state, recompute the canonical ``h{hour}_{state}`` bucket.
Also normalises ``matched_text`` whitespace so quotes captured across a line
break stay stored as a single clean phrase.

Writes in-place by default (pass ``--output`` to redirect).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from idle_hours.buckets import BUCKET_ORDER, bucket_for_time
from idle_hours.jsonl_io import iter_jsonl

BASE_DIR = Path(__file__).resolve().parent


def canonical_bucket(hour: int, minute: int) -> str:
    """Canonical ``h{hour}_{state}`` bucket for a 24-hour ``(hour, minute)`` pair.

    Delegates to :func:`buckets.bucket_for_time` so the rounding rule lives in
    exactly one place (see the CLAUDE.md note about killing state-table drift).
    """
    return bucket_for_time(f"{hour:02d}:{minute:02d}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair legacy fuzzy_bucket names in JSONL corpus rows.")
    parser.add_argument("input", help="Input JSONL file")
    parser.add_argument("--output", default=None, help="Output path; defaults to in-place overwrite")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = (BASE_DIR / args.input).expanduser() if not Path(args.input).is_absolute() else Path(args.input).expanduser()
    output_path = ((BASE_DIR / args.output).expanduser() if not Path(args.output).is_absolute() else Path(args.output).expanduser()) if args.output else input_path

    rows = []
    bucket_fixes = 0
    matched_text_fixes = 0
    skipped_no_time = 0

    for row in iter_jsonl(input_path):
        fb = row.get("fuzzy_bucket")
        if fb and "_" in fb:
            state = fb.split("_", 1)[1]
            if state not in BUCKET_ORDER:
                hour = row.get("hour")
                minute = row.get("minute")
                if hour is None or minute is None:
                    skipped_no_time += 1
                else:
                    row["fuzzy_bucket"] = canonical_bucket(hour, minute)
                    bucket_fixes += 1

        matched_text = row.get("matched_text")
        if matched_text:
            normalised = " ".join(matched_text.split())
            if normalised != matched_text:
                row["matched_text"] = normalised
                matched_text_fixes += 1

        rows.append(row)

    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Repaired {bucket_fixes} legacy fuzzy_bucket rows")
    print(f"Normalised {matched_text_fixes} matched_text whitespace rows")
    if skipped_no_time:
        print(f"Skipped {skipped_no_time} legacy-bucket rows missing hour/minute")
    print(f"Wrote {len(rows)} rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
