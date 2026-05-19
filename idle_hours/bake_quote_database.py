#!/usr/bin/env python3
"""Bake the runtime quote database from the attributed corpus.

Final pipeline stage. Reads ``assets/candidates-attributed.jsonl`` (the output
of ``apply_content_overrides.py``) and produces ``assets/quote_database.jsonl``:
a *display-ready* corpus with scoring pre-computed.

At runtime the picker no longer has to filter quality / drop daypart-only rows
/ compute the nine row-intrinsic score components on every tick. Instead it
reads this file and only recomputes the two request-time components
(``minute_penalty``, ``override_bonus``); the remaining ten components live in
``baked_score`` on each row.

Baking drops rows that the runtime picker would have filtered anyway:

* missing / empty ``fuzzy_bucket`` — daypart-only harvests that never match an
  ``h{1..12}_{state}`` bucket, so ``pick_best`` can never surface them;
* missing / empty ``display_quote`` — same filter ``pick_best`` applies today;
* ``quality_score < --min-quality`` — same gate the picker applies on every
  tick, paid once at bake time instead of per-render.

Each kept row gets:

* ``baked_score``: list of the ten row-intrinsic score components in the same
  order the runtime picker expects when it interleaves the request-time
  components back in (see ``pick_quote.compose_baked_score_key``);
* ``inferred_quote_minute``: what minute this row *claims* (for the runtime
  ``minute_penalty``) — cached once so the picker skips regex work per tick;
* ``baked_rank``: 0-based ordinal within the row's bucket after sorting by
  ``baked_score`` ascending. Purely for curator-UI readability; the runtime
  picker sorts again once the request-time components are known.

The baker never applies ``selection_overrides.json`` (bans / boosts /
preferred buckets) — those are edited live via the web UI and stay runtime
concerns. ``content_overrides.json`` is already applied by
``apply_content_overrides.py`` immediately upstream.

Example:

    python3 bake_quote_database.py \\
        assets/candidates-attributed.jsonl \\
        --output assets/quote_database.jsonl \\
        --min-quality 60

Writes atomically via ``atomic_io.atomic_write_lines``.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from idle_hours import atomic_io, pick_quote
from idle_hours.buckets import bucket_for_time
from idle_hours.jsonl_io import iter_jsonl

BASE_DIR = Path(__file__).resolve().parent


# Positions inside the tuple returned by ``pick_quote.score_row`` that depend
# only on the row's own content. ``minute_penalty`` (position 2),
# ``override_bonus`` (position 7), and ``source_rarity_penalty`` (position 10)
# are handled separately: rarity is computed from the full raw corpus and
# baked in; minute/override are deferred to the runtime picker.
_STATIC_SCORE_INDICES: tuple[int, ...] = (0, 1, 3, 4, 5, 6, 8, 9, 10, 11)

# Schema version stamped on every baked row. Bump whenever
# ``BAKED_SCORE_COMPONENTS`` changes (order, length, or semantics) so the
# runtime picker can detect a mismatch between a freshly ``git pull``-ed
# ``pick_quote.py`` and a stale ``assets/quote_database.jsonl`` that was baked
# under an older schema, instead of silently scoring against a mis-aligned
# tuple. The runtime picker in :mod:`pick_quote` compares against
# ``pick_quote.BAKED_SCORE_SCHEMA_VERSION``; when they disagree it warns and
# falls back to the raw corpus.
BAKED_SCORE_SCHEMA_VERSION: int = 1

# Human-readable labels for the baked_score tuple, in the order they appear.
# The runtime picker uses this same order when it reconstructs the full 12-
# component sort key; changing it breaks pick equivalence, so keep it in sync
# with ``pick_quote.compose_baked_score_key``.
BAKED_SCORE_COMPONENTS: tuple[str, ...] = (
    "fragment_penalty",
    "cleanup_penalty",
    "metadata_bonus",
    "dialogue_penalty",
    "opening_penalty",
    "source_bonus",
    "quality_component",
    "length_exactness",
    "source_rarity_penalty",
    "length_tiebreak",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bake the runtime quote database from the attributed corpus.")
    parser.add_argument(
        "input",
        nargs="?",
        default="assets/candidates-attributed.jsonl",
        help="Input JSONL (typically assets/candidates-attributed.jsonl).",
    )
    parser.add_argument(
        "--output",
        default="assets/quote_database.jsonl",
        help="Output JSONL path (the baked database).",
    )
    parser.add_argument(
        "--min-quality",
        type=int,
        default=60,
        help="Drop rows whose quality_score is below this threshold. Mirrors the runtime picker default.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=0,
        help=(
            "Keep only the top-N rows per bucket after sorting by the baked score. "
            "0 (default) keeps all rows, preserving exact pick-equivalence with the "
            "raw-corpus picker."
        ),
    )
    return parser.parse_args()


def _resolve(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


_BAKED_ONLY_FIELDS: frozenset[str] = frozenset(
    {"baked_score", "inferred_quote_minute", "baked_rank", "schema_version"}
)


def _static_score(row: dict, source_counts: Counter) -> list[int]:
    """Compute the ten row-intrinsic score components for ``row``.

    Calls ``pick_quote.score_row`` with empty overrides and ``requested_time=None``
    so ``override_bonus`` reduces to 0 and ``minute_penalty`` falls out of the
    tuple positions we actually keep. The values ``score_row`` returns for the
    two dropped positions (2 and 7) are discarded by the index projection below,
    so it doesn't matter what they happen to compute to.

    Rarity (position 10) is kept and is computed against ``source_counts`` —
    the counter must be built from the **full raw corpus**, not the filtered
    subset, to preserve pick-equivalence with the live picker.
    """
    bucket = row.get("fuzzy_bucket") or ""
    tup = pick_quote.score_row(
        row,
        bucket=bucket,
        overrides={},
        requested_time=None,
        source_counts=source_counts,
    )
    return [tup[i] for i in _STATIC_SCORE_INDICES]


def filter_rows(rows: list[dict], min_quality: int) -> tuple[list[dict], dict[str, int]]:
    """Return ``(kept, drop_counts)`` after applying the runtime filters at bake time.

    Drop reasons are mutually exclusive; a row is only counted under the first
    reason that applies, in the order checked: no/invalid bucket → no
    display_quote → low quality.

    ``fuzzy_bucket`` is validated against :func:`pick_quote.valid_bucket_names`
    rather than just truthy-checked: the raw-corpus picker silently ignores
    rows whose bucket is not a canonical ``h{1..12}_{state}`` (e.g. legacy
    daypart strings like ``"morning"`` that pre-date ``buckets.py``), but the
    baker would otherwise call ``parse_requested_minute`` on them and crash
    with ``IndexError`` on ``"morning".split("_", 1)[1]``.
    """
    valid = pick_quote.valid_bucket_names()
    kept: list[dict] = []
    drops = {"no_bucket": 0, "no_display_quote": 0, "low_quality": 0}
    for row in rows:
        bucket = row.get("fuzzy_bucket")
        if not bucket or bucket not in valid:
            drops["no_bucket"] += 1
            continue
        display = row.get("display_quote")
        if not isinstance(display, str) or not display.strip():
            drops["no_display_quote"] += 1
            continue
        quality = row.get("quality_score")
        if quality is not None and quality < min_quality:
            drops["low_quality"] += 1
            continue
        kept.append(row)
    return kept, drops


def bake_rows(rows: list[dict], min_quality: int, *, top_n: int = 0) -> tuple[list[dict], dict]:
    """Bake ``rows`` into display-ready form. Returns ``(baked_rows, stats)``.

    ``stats`` is a dict with ``input``, ``kept``, drop counters, and
    ``per_bucket`` (min / max / total populated buckets) — useful for the CLI
    summary and the bake-stage unit tests.

    Input rows are not mutated: we deep-copy survivors before stamping
    ``baked_score`` / ``inferred_quote_minute`` / ``baked_rank``. Any of those
    fields already present on an input row are stripped first, so re-running
    the baker on its own output refreshes (rather than carries forward) the
    cached rarity + rank. Without the strip, ``score_row`` would short-circuit
    on the existing ``baked_score`` and reuse the stale values from the
    previous bake.
    """
    kept, drops = filter_rows(rows, min_quality)

    # Defensive copy + strip: protects callers from surprise mutation, and
    # guarantees ``score_row`` takes the full recomputation path below even
    # when handed an already-baked input.
    kept = [{k: v for k, v in row.items() if k not in _BAKED_ONLY_FIELDS} for row in kept]

    # Rarity must be computed against the input corpus (not the kept subset)
    # so picks are bit-for-bit equivalent to what the live picker does with
    # the raw file. ``score_row`` only counts rows that *have* a source_id, so
    # including filtered-out rows changes the counts only for sources that
    # still have surviving rows.
    source_counts = pick_quote.count_sources(rows)

    for row in kept:
        row["baked_score"] = _static_score(row, source_counts)
        row["inferred_quote_minute"] = pick_quote.infer_quote_minute(row)
        row["schema_version"] = BAKED_SCORE_SCHEMA_VERSION

    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for row in kept:
        by_bucket[row["fuzzy_bucket"]].append(row)

    baked: list[dict] = []
    per_bucket_sizes: list[int] = []
    for bucket in sorted(by_bucket):
        group = by_bucket[bucket]
        group.sort(key=lambda r: tuple(r["baked_score"]))
        if top_n > 0:
            group = group[:top_n]
        for rank, row in enumerate(group):
            row["baked_rank"] = rank
            baked.append(row)
        per_bucket_sizes.append(len(group))

    stats = {
        "input": len(rows),
        "kept": len(baked),
        "drops": drops,
        "per_bucket": {
            "populated": len(per_bucket_sizes),
            "max": max(per_bucket_sizes) if per_bucket_sizes else 0,
            "min": min(per_bucket_sizes) if per_bucket_sizes else 0,
        },
    }
    return baked, stats


def _load_rows(path: Path) -> list[dict]:
    """Load the attributed corpus and re-derive ``fuzzy_bucket`` from ``normalized_time``.

    Mirrors ``pick_quote.load_rows`` so the bake stage and the runtime picker
    agree on which bucket each row belongs to; otherwise a stale
    ``fuzzy_bucket`` value in the input would land the row in a different
    bucket at bake vs. at runtime.
    """
    rows: list[dict] = []
    for row in iter_jsonl(path):
        normalized = row.get("normalized_time")
        if isinstance(normalized, str) and ":" in normalized:
            try:
                row["fuzzy_bucket"] = bucket_for_time(normalized)
            except (ValueError, KeyError):
                pass
        rows.append(row)
    return rows


def main() -> int:
    args = parse_args()
    input_path = _resolve(args.input)
    output_path = _resolve(args.output)

    rows = _load_rows(input_path)
    baked, stats = bake_rows(rows, args.min_quality, top_n=args.top_n)

    atomic_io.atomic_write_lines(
        output_path,
        (json.dumps(row, ensure_ascii=False) for row in baked),
    )

    drops = stats["drops"]
    per_bucket = stats["per_bucket"]
    print(
        f"Baked {stats['kept']} rows from {stats['input']} "
        f"(dropped {drops['no_bucket']} no-bucket, "
        f"{drops['no_display_quote']} no-display-quote, "
        f"{drops['low_quality']} below quality {args.min_quality})",
        file=sys.stdout,
    )
    print(
        f"Populated {per_bucket['populated']} buckets "
        f"(min {per_bucket['min']}, max {per_bucket['max']} rows/bucket)",
        file=sys.stdout,
    )
    print(f"Wrote {output_path}", file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
