"""Pick-equivalence between the raw corpus and the baked database.

The whole point of the bake stage is that it replaces a runtime computation
with a pre-computed artifact *without* changing which quote ends up on the
display. This test module pins that property: for a representative sweep of
times and seeds, picking via the baked database produces the same
``(source_id, line_number)`` as picking via the raw corpus.

A failure here means the baker either filtered out a row the raw picker would
have chosen, dropped a score component, or picked an inconsistent tuple
layout — all of which silently shift what the clock displays.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from idle_hours import bake_quote_database as bq
from idle_hours import pick_quote
from idle_hours.buckets import BUCKET_ORDER, DEFAULT_BUCKET_MINUTES


def _bake_to(tmp_path, raw_rows):
    """Write raw_rows to a JSONL, bake it, and return (raw_path, baked_path)."""
    raw_path = tmp_path / "raw.jsonl"
    baked_path = tmp_path / "baked.jsonl"
    with raw_path.open("w", encoding="utf-8") as f:
        for row in raw_rows:
            f.write(json.dumps(row) + "\n")
    # Use the real main() via monkeypatched argv so we exercise the same
    # filtering + atomic-write path the pipeline uses in production.
    import sys
    old_argv = sys.argv
    try:
        sys.argv = ["bake_quote_database.py", str(raw_path), "--output", str(baked_path)]
        bq.main()
    finally:
        sys.argv = old_argv
    return raw_path, baked_path


def _pick_key(time_str: str, *, database_path: str | None, input_path: str, seed: int = 0):
    """Return (source_id, line_number) for the picked quote."""
    result = pick_quote.select_quote(
        time_str=time_str,
        seed=seed,
        database_path=database_path,
        input_path=input_path,
    )
    return (result.get("source_id"), result.get("line_number"))


def _iter_canonical_times():
    """Yield one canonical HH:MM per (hour, state) — 144 combinations."""
    for hour in range(1, 13):
        for state in BUCKET_ORDER:
            minute = DEFAULT_BUCKET_MINUTES.get(state, 0)
            hh = hour % 12  # h12_* maps to the 00:MM hour
            yield f"{hh:02d}:{minute:02d}", f"h{hour}_{state}"


# Running the full corpus through the baker for every test would make the
# suite slow; scope a "bake once per module" fixture that uses the shipped
# corpus so the 144-bucket sweep runs against real data.
CORPUS_PATH = Path(__file__).resolve().parent.parent / "assets" / "candidates-attributed.jsonl"

pytestmark = pytest.mark.skipif(not CORPUS_PATH.exists(), reason="shipped corpus missing")


@pytest.fixture(scope="module")
def baked_against_shipped(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("bake_equiv")
    baked_path = tmp_dir / "quote_database.jsonl"
    import sys
    old_argv = sys.argv
    try:
        sys.argv = [
            "bake_quote_database.py",
            str(CORPUS_PATH),
            "--output", str(baked_path),
        ]
        assert bq.main() == 0
    finally:
        sys.argv = old_argv
    return str(CORPUS_PATH), str(baked_path)


class TestPickEquivalenceShippedCorpus:
    def test_all_144_buckets_agree(self, baked_against_shipped):
        raw_path, baked_path = baked_against_shipped
        mismatches = []
        for time_str, bucket in _iter_canonical_times():
            try:
                raw_key = _pick_key(time_str, database_path="", input_path=raw_path)
                baked_key = _pick_key(time_str, database_path=baked_path, input_path=raw_path)
            except SystemExit:
                # Bucket has no candidates even after fallback — acceptable as
                # long as both paths agree on the non-pick.
                try:
                    pick_quote.select_quote(time_str=time_str, database_path="", input_path=raw_path)
                    raw_has = True
                except SystemExit:
                    raw_has = False
                try:
                    pick_quote.select_quote(time_str=time_str, database_path=baked_path, input_path=raw_path)
                    baked_has = True
                except SystemExit:
                    baked_has = False
                if raw_has != baked_has:
                    mismatches.append((time_str, bucket, "one path empty"))
                continue
            if raw_key != baked_key:
                mismatches.append((time_str, bucket, raw_key, baked_key))
        assert not mismatches, f"diverged picks: {mismatches[:10]}"

    @pytest.mark.parametrize("seed", [1, 7, 42, 1234])
    def test_tie_break_seed_stability(self, baked_against_shipped, seed):
        """Seeded tie-break must produce the same pick on both paths."""
        raw_path, baked_path = baked_against_shipped
        # Pick a dense bucket likely to have ties.
        for time_str in ("10:00", "03:00", "06:00"):
            raw_key = _pick_key(time_str, database_path="", input_path=raw_path, seed=seed)
            baked_key = _pick_key(time_str, database_path=baked_path, input_path=raw_path, seed=seed)
            assert raw_key == baked_key, f"seed={seed} time={time_str} raw={raw_key} baked={baked_key}"


class TestComposeBakedScoreKey:
    def test_full_tuple_matches_score_row_on_same_row(self, sample_row):
        from tests.conftest import make_row
        raw = make_row(quality_score=80, normalized_time="03:00", fuzzy_bucket="h3_exact")
        source_counts = pick_quote.count_sources([raw])
        expected = pick_quote.score_row(
            raw, bucket="h3_exact", overrides={},
            requested_time="03:00", source_counts=source_counts,
        )
        # Bake that one row and re-score it via the baked path.
        baked_rows, _ = bq.bake_rows([dict(raw)], min_quality=60)
        baked_row = baked_rows[0]
        actual = pick_quote.compose_baked_score_key(
            baked_row, bucket="h3_exact", overrides={}, requested_time="03:00",
        )
        assert actual == expected

    def test_score_row_short_circuits_on_baked(self):
        """score_row on a baked row routes to compose_baked_score_key."""
        from tests.conftest import make_row
        raw = make_row(quality_score=80, fuzzy_bucket="h3_exact")
        baked_rows, _ = bq.bake_rows([dict(raw)], min_quality=60)
        baked_row = baked_rows[0]
        via_score_row = pick_quote.score_row(
            baked_row, bucket="h3_exact", overrides={},
            requested_time="03:00", source_counts=None,
        )
        via_compose = pick_quote.compose_baked_score_key(
            baked_row, bucket="h3_exact", overrides={}, requested_time="03:00",
        )
        assert via_score_row == via_compose
