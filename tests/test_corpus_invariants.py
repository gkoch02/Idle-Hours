"""Invariants over the shipped runtime corpus.

These tests read ``assets/candidates-attributed.jsonl`` (the picker's default
input) and assert schema / bucket / metadata invariants that the pipeline is
supposed to guarantee. A break here typically means a miner or cleanup stage
regressed and a rebuild is needed.

The checks are *schema* and *cross-field consistency* — not statistical checks
like "every bucket must have >= N quotes" (that's ``bucket_coverage.py``'s job).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from buckets import BUCKET_ORDER, bucket_for_time, minute_bucket

CORPUS_PATH = Path(__file__).resolve().parent.parent / "assets" / "candidates-attributed.jsonl"

pytestmark = pytest.mark.skipif(not CORPUS_PATH.exists(), reason="shipped corpus missing")


@pytest.fixture(scope="module")
def corpus_rows() -> list[dict]:
    rows = []
    with CORPUS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


class TestCorpusSchema:
    def test_corpus_is_nonempty(self, corpus_rows):
        assert len(corpus_rows) > 100, "corpus looks suspiciously small"

    def test_required_fields_present(self, corpus_rows):
        required = {
            "source_id",
            "match_type",
            "matched_text",
            "display_quote",
            "display_fragment",
            "cleanup_status",
            "quality_score",
            "quality_flags",
        }
        for row in corpus_rows:
            missing = required - set(row.keys())
            assert not missing, f"row missing fields {missing}: {row.get('source_id')}:{row.get('line_number')}"

    def test_quality_score_range(self, corpus_rows):
        for row in corpus_rows:
            score = row["quality_score"]
            assert isinstance(score, int), f"quality_score must be int, got {type(score).__name__}"
            assert 0 <= score <= 100, f"quality_score {score} out of [0, 100]"

    def test_quality_flags_is_list_of_str(self, corpus_rows):
        for row in corpus_rows:
            flags = row["quality_flags"]
            assert isinstance(flags, list)
            assert all(isinstance(f, str) for f in flags)

    def test_display_fragment_is_bool(self, corpus_rows):
        for row in corpus_rows:
            assert isinstance(row["display_fragment"], bool)

    def test_cleanup_status_is_known(self, corpus_rows):
        allowed = {"complete_sentence", "expanded_with_context", "fragment_fallback", "empty"}
        for row in corpus_rows:
            assert row["cleanup_status"] in allowed, f"unknown cleanup_status {row['cleanup_status']!r}"

    def test_display_quote_is_nonempty_string(self, corpus_rows):
        for row in corpus_rows:
            dq = row["display_quote"]
            assert isinstance(dq, str)
            assert dq.strip(), f"empty display_quote at {row.get('source_id')}:{row.get('line_number')}"


VALID_FUZZY_BUCKETS = {f"h{h}_{state}" for h in range(1, 13) for state in BUCKET_ORDER}
VALID_DAYPART_BUCKETS = {
    "midnight", "small_hours", "dawn", "morning", "noon", "afternoon",
    "dusk", "evening", "night",
}


class TestBucketConsistency:
    def test_fuzzy_bucket_is_known_or_null(self, corpus_rows):
        valid = VALID_FUZZY_BUCKETS | {None}
        for row in corpus_rows:
            bucket = row.get("fuzzy_bucket")
            assert bucket in valid, f"unknown fuzzy_bucket {bucket!r}"

    def test_daypart_bucket_is_known_or_null(self, corpus_rows):
        valid = VALID_DAYPART_BUCKETS | {None}
        for row in corpus_rows:
            bucket = row.get("daypart_bucket")
            assert bucket in valid, f"unknown daypart_bucket {bucket!r}"

    def test_fuzzy_bucket_matches_hour_minute(self, corpus_rows):
        """When hour/minute are set, fuzzy_bucket must match what buckets.py computes.

        This catches legacy 8-state bucket names (``just_after``, ``half_pastish``)
        that should have been purged by ``fix_legacy_buckets.py``.
        """
        mismatches = []
        for row in corpus_rows:
            hour = row.get("hour")
            minute = row.get("minute")
            bucket = row.get("fuzzy_bucket")
            if hour is None or minute is None or bucket is None:
                continue
            expected = bucket_for_time(f"{int(hour):02d}:{int(minute):02d}")
            if bucket != expected:
                mismatches.append((row.get("source_id"), row.get("line_number"), hour, minute, bucket, expected))
        assert not mismatches, (
            f"fuzzy_bucket disagrees with buckets.bucket_for_time for {len(mismatches)} rows; "
            f"first offender: {mismatches[0]}"
        )

    def test_normalized_time_parses_when_hour_minute_set(self, corpus_rows):
        for row in corpus_rows:
            hour = row.get("hour")
            minute = row.get("minute")
            norm = row.get("normalized_time")
            if hour is None and minute is None:
                continue
            assert norm, "normalized_time must be set when hour/minute are set"
            parts = norm.split(":")
            assert len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit()
            h, m = int(parts[0]), int(parts[1])
            assert 0 <= h <= 23
            assert 0 <= m <= 59

    def test_hour_minute_in_valid_range(self, corpus_rows):
        for row in corpus_rows:
            hour = row.get("hour")
            minute = row.get("minute")
            if hour is not None:
                assert 0 <= int(hour) <= 23
            if minute is not None:
                assert 0 <= int(minute) <= 59

    def test_time_or_daypart_always_present(self, corpus_rows):
        """Every row must have at least one of fuzzy_bucket or daypart_bucket —
        otherwise it's unroutable by the picker."""
        for row in corpus_rows:
            assert row.get("fuzzy_bucket") or row.get("daypart_bucket"), (
                f"row {row.get('source_id')}:{row.get('line_number')} has no bucket of any kind"
            )


class TestDeduplication:
    # Current corpus has a small number of duplicate-position rows arising from
    # the merge stage intentionally NOT dedup-ing across match_type (a
    # `minutes_past_to` regex hit and a `targeted_phrase` hit at the same
    # offset both survive). This test locks in that count as a ceiling so a
    # merge-stage regression that silently doubles the corpus fires loudly.
    MAX_POSITION_DUPLICATES = 40

    def test_duplicate_position_rows_below_ceiling(self, corpus_rows):
        seen = set()
        dupes = []
        for row in corpus_rows:
            sid = row.get("source_id")
            ln = row.get("line_number")
            if sid is None or ln is None:
                continue
            key = (sid, ln, row.get("match_start"), row.get("match_end"))
            if key in seen:
                dupes.append(key)
            seen.add(key)
        assert len(dupes) <= self.MAX_POSITION_DUPLICATES, (
            f"{len(dupes)} duplicate (source_id, line_number, match_start, match_end) rows "
            f"exceeds ceiling {self.MAX_POSITION_DUPLICATES} — merge stage regression?"
        )

    def test_canonical_quote_dedup_within_bucket(self, corpus_rows):
        """Within a (fuzzy_bucket, canonical_quote) pair, rows should be unique —
        that's the merge_candidates dedup key. Violations mean merge silently dropped.
        """
        seen = set()
        dupes = 0
        for row in corpus_rows:
            bucket = row.get("fuzzy_bucket")
            canonical = row.get("canonical_quote")
            normalized = row.get("normalized_time")
            daypart = row.get("daypart_bucket")
            if not canonical:
                continue
            key = (normalized, bucket, daypart, canonical)
            if key in seen:
                dupes += 1
            seen.add(key)
        # Lock current count as the ceiling. A clean corpus would be 0, but
        # targeted_phrase vs original-regex collisions leave a known residue.
        assert dupes <= 40, f"{dupes} rows violate the merge_candidates dedup key (ceiling 40)"


class TestMetadataCoverage:
    def test_author_title_present_on_gutenberg_rows(self, corpus_rows):
        """Rows with a numeric source_id come from cached Gutenberg downloads, so
        enrich_metadata should have attached author+title to the overwhelming
        majority. Allow a small slop (some Gutenberg texts have unparseable
        headers) but flag regressions."""
        gutenberg_rows = [r for r in corpus_rows if str(r.get("source_id", "")).isdigit()]
        if not gutenberg_rows:
            pytest.skip("no gutenberg-sourced rows in corpus")
        with_metadata = sum(1 for r in gutenberg_rows if r.get("author") and r.get("title"))
        ratio = with_metadata / len(gutenberg_rows)
        assert ratio >= 0.90, f"metadata coverage dropped to {ratio:.1%} of gutenberg rows — did enrich_metadata break?"


DATABASE_PATH = Path(__file__).resolve().parent.parent / "assets" / "quote_database.jsonl"


@pytest.fixture(scope="module")
def baked_rows() -> list[dict]:
    rows = []
    with DATABASE_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


@pytest.mark.skipif(not DATABASE_PATH.exists(), reason="shipped baked database missing")
class TestBakedDatabaseInvariants:
    """Schema checks on ``assets/quote_database.jsonl`` — the committed baked DB.

    The raw corpus and the baked DB are both committed; CI must catch a
    regression in the baker (wrong tuple layout, missing required field,
    rank drift) before a deploy, not after.
    """

    def test_database_is_nonempty(self, baked_rows):
        assert len(baked_rows) > 100, "baked database looks suspiciously small"

    def test_every_row_has_baked_score(self, baked_rows):
        for row in baked_rows:
            score = row.get("baked_score")
            assert isinstance(score, list), f"missing baked_score: {row.get('source_id')}:{row.get('line_number')}"
            assert len(score) == 10, f"baked_score must have 10 components, got {len(score)}"
            assert all(isinstance(v, int) for v in score), "baked_score components must be int"

    def test_every_row_has_inferred_quote_minute(self, baked_rows):
        for row in baked_rows:
            assert "inferred_quote_minute" in row
            value = row["inferred_quote_minute"]
            assert value is None or (isinstance(value, int) and 0 <= value <= 59)

    def test_every_row_has_valid_bucket(self, baked_rows):
        """Baking drops all daypart-only rows; every kept row routes to a
        concrete h{1..12}_{state} bucket."""
        from pick_quote import valid_bucket_names
        valid = valid_bucket_names()
        for row in baked_rows:
            bucket = row.get("fuzzy_bucket")
            assert bucket in valid, f"unknown fuzzy_bucket {bucket!r} at {row.get('source_id')}:{row.get('line_number')}"

    def test_quality_floor_applied(self, baked_rows):
        """Default bake threshold is 60 — every row must clear it (or have no
        score at all, which score_row treats as 0 penalty)."""
        for row in baked_rows:
            quality = row.get("quality_score")
            if quality is not None:
                assert quality >= 60, f"row below quality floor: {row.get('source_id')}:{row.get('line_number')} = {quality}"

    def test_display_quote_nonempty(self, baked_rows):
        for row in baked_rows:
            display = row.get("display_quote")
            assert isinstance(display, str) and display.strip()

    def test_ranks_are_per_bucket_dense(self, baked_rows):
        """Within each bucket, baked_rank should be 0, 1, 2, ... with no gaps —
        confirms the baker's per-bucket sort+enumerate contract."""
        from collections import defaultdict
        by_bucket = defaultdict(list)
        for row in baked_rows:
            by_bucket[row["fuzzy_bucket"]].append(row["baked_rank"])
        for bucket, ranks in by_bucket.items():
            ranks.sort()
            assert ranks == list(range(len(ranks))), f"bucket {bucket} has non-dense ranks {ranks}"

    def test_rows_sorted_by_bucket_then_rank(self, baked_rows):
        """File order is (bucket, rank) ascending so a human diff of the
        committed DB is readable."""
        seen_buckets: set[str] = set()
        current_bucket = None
        prev_rank = -1
        for row in baked_rows:
            bucket = row["fuzzy_bucket"]
            rank = row["baked_rank"]
            if bucket != current_bucket:
                assert bucket not in seen_buckets, f"bucket {bucket} rows are not contiguous"
                seen_buckets.add(bucket)
                current_bucket = bucket
                prev_rank = rank
                continue
            assert rank >= prev_rank, f"rank regression within bucket {bucket}: {prev_rank} → {rank}"
            prev_rank = rank


class TestBucketsHelpers:
    """Paranoid sanity checks on the primitives the invariants depend on."""

    def test_bucket_order_is_twelve_states(self):
        # 12 rounded-minute states; paired with 12 hours that's the 144 full buckets.
        assert len(BUCKET_ORDER) == 12

    def test_bucket_for_time_suffix_matches_minute_bucket(self):
        for h in range(24):
            for m in range(60):
                suffix = minute_bucket(m)
                # minute 58–59 rolls the hour forward to "exact", so for those minutes
                # the bucket for the CURRENT hour may end in a different state from
                # minute_bucket(m) when the time string is recomputed below — skip.
                if m >= 58:
                    continue
                bucket = bucket_for_time(f"{h:02d}:{m:02d}")
                assert bucket.endswith(f"_{suffix}"), f"{h:02d}:{m:02d} → {bucket} but state {suffix!r}"
