#!/usr/bin/env python3
"""Apply per-row content overrides on top of the enriched corpus.

Final pipeline stage. Reads ``assets/content_overrides.json`` — a sidecar
keyed by ``"<source_id>:<line_number>"`` — and patches matching rows from the
input JSONL. This is how hand-curated fixes (a miscaptured time phrase, a bad
display excerpt, a broken attribution) are kept *durable* across pipeline
re-runs: the fix lives in the sidecar and re-applies every time, instead of
being written into a derivable artifact and silently overwritten by the next
miner run.

The sidecar format is a flat dict:

    {
      "141:482":  {"display_quote": "..."},
      "1342:99":  {"matched_text": "half past two", "normalized_time": "02:30"}
    }

Allowed override fields: ``display_quote``, ``matched_text``, ``author``,
``title``, ``quality_score``, ``hour``, ``minute``, ``normalized_time``. Any
other key in the sidecar is ignored with a stderr warning. After applying,
``fuzzy_bucket`` is re-derived from the post-override ``normalized_time`` so
time-affecting overrides can't drift the bucket. Patched rows are stamped
``override_applied: true`` so downstream debugging can tell which rows came
from the sidecar.

Keys that don't match any row in the input are logged to stderr so typos and
overrides for rows that later got dedup-dropped surface loudly rather than
silently no-op'ing.

Writes in-place by default (pass ``--output`` to redirect).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from buckets import bucket_for_time
from jsonl_io import iter_jsonl

BASE_DIR = Path(__file__).resolve().parent

ALLOWED_FIELDS: frozenset[str] = frozenset({
    "display_quote",
    "matched_text",
    "author",
    "title",
    "quality_score",
    "hour",
    "minute",
    "normalized_time",
})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply per-row content overrides to corpus rows.")
    parser.add_argument("input", help="Input JSONL file (typically assets/candidates-attributed.jsonl)")
    parser.add_argument(
        "--overrides",
        default="assets/content_overrides.json",
        help="Path to the content overrides sidecar JSON",
    )
    parser.add_argument("--output", default=None, help="Output path; defaults to in-place overwrite")
    return parser.parse_args()


def _resolve(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def row_key(row: dict) -> str | None:
    source_id = row.get("source_id")
    line_number = row.get("line_number")
    if source_id is None or line_number is None:
        return None
    return f"{source_id}:{line_number}"


def load_overrides(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: overrides root must be a JSON object")
    return raw


def _warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr, flush=True)


def apply_overrides(rows: list[dict], overrides: dict[str, dict], *, overrides_path: str = "content_overrides.json") -> tuple[list[dict], int]:
    """Return ``(patched_rows, applied_count)`` after layering ``overrides`` onto ``rows``.

    Mutates row copies, not the inputs. Warns on stderr for unknown fields and
    dangling keys (overrides that didn't match any row).
    """
    patched_rows = [dict(row) for row in rows]
    unseen_keys = set(overrides.keys())
    applied = 0

    for row in patched_rows:
        key = row_key(row)
        if key is None or key not in overrides:
            continue
        unseen_keys.discard(key)
        patch = overrides[key]
        if not isinstance(patch, dict):
            _warn(f"{overrides_path}: override for {key} is not an object; skipped")
            continue

        unknown = sorted(f for f in patch if f not in ALLOWED_FIELDS)
        if unknown:
            _warn(f"{overrides_path}: override for {key} has unsupported fields: {', '.join(unknown)}")

        time_touched = False
        for field, value in patch.items():
            if field not in ALLOWED_FIELDS:
                continue
            row[field] = value
            if field in {"hour", "minute", "normalized_time"}:
                time_touched = True

        if time_touched:
            hour = row.get("hour")
            minute = row.get("minute")
            # If hour/minute were touched but normalized_time wasn't, keep them in sync.
            if isinstance(hour, int) and isinstance(minute, int) and "normalized_time" not in patch:
                row["normalized_time"] = f"{hour:02d}:{minute:02d}"

        normalized = row.get("normalized_time")
        if isinstance(normalized, str) and ":" in normalized:
            try:
                row["fuzzy_bucket"] = bucket_for_time(normalized)
            except (ValueError, KeyError):
                pass

        row["override_applied"] = True
        applied += 1

    if unseen_keys:
        dangling = ", ".join(sorted(unseen_keys))
        _warn(
            f"{overrides_path}: {len(unseen_keys)} override key(s) did not match any row "
            f"(dropped row or typo?): {dangling}"
        )

    return patched_rows, applied


def main() -> int:
    args = parse_args()
    input_path = _resolve(args.input)
    overrides_path = _resolve(args.overrides)
    output_path = _resolve(args.output) if args.output else input_path

    rows = list(iter_jsonl(input_path))
    overrides = load_overrides(overrides_path)
    patched, applied = apply_overrides(rows, overrides, overrides_path=str(overrides_path))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in patched:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Applied {applied} override(s) across {len(overrides)} sidecar entries")
    print(f"Wrote {len(patched)} rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
