"""Tests for bake_quote_database.py — the display-ready-database bake stage."""
from __future__ import annotations

import json

import pytest

import bake_quote_database as bq
import pick_quote
from tests.conftest import make_row


class TestFilterRows:
    def test_drops_daypart_only_rows(self, sample_row):
        daypart = make_row(
            fuzzy_bucket=None,
            normalized_time=None,
            daypart_bucket="dawn",
            display_quote="a morning scene",
        )
        kept, drops = bq.filter_rows([sample_row, daypart], min_quality=60)
        assert kept == [sample_row]
        assert drops["no_bucket"] == 1
        assert drops["no_display_quote"] == 0
        assert drops["low_quality"] == 0

    def test_drops_empty_display_quote(self, sample_row):
        empty = make_row(display_quote="   ")
        kept, drops = bq.filter_rows([sample_row, empty], min_quality=60)
        assert kept == [sample_row]
        assert drops["no_display_quote"] == 1

    def test_drops_low_quality(self, sample_row):
        low = make_row(quality_score=40)
        kept, drops = bq.filter_rows([sample_row, low], min_quality=60)
        assert kept == [sample_row]
        assert drops["low_quality"] == 1

    def test_drops_legacy_nonstandard_bucket_name(self):
        """Rows with a truthy but malformed ``fuzzy_bucket`` (legacy
        8-state names like ``"just_after"`` or daypart strings like
        ``"morning"``) must be dropped, not scored — ``parse_requested_minute``
        would otherwise crash with IndexError on ``"morning".split("_", 1)[1]``.
        The raw-corpus picker silently ignores such rows because they never
        match a canonical bucket, so dropping at bake time is the safe
        equivalent."""
        legacy = make_row(fuzzy_bucket="morning", normalized_time=None, hour=None, minute=None)
        just_after = make_row(fuzzy_bucket="just_after", normalized_time=None, hour=None, minute=None)
        valid = make_row(fuzzy_bucket="h3_exact")
        kept, drops = bq.filter_rows([legacy, just_after, valid], min_quality=60)
        assert kept == [valid]
        assert drops["no_bucket"] == 2  # both legacy rows counted under no_bucket

    def test_bake_rows_survives_legacy_bucket_input(self):
        """Full bake_rows pipeline: legacy rows are filtered out before scoring,
        so the baker completes successfully instead of crashing."""
        legacy = make_row(fuzzy_bucket="morning", normalized_time=None, hour=None, minute=None)
        valid = make_row(fuzzy_bucket="h3_exact")
        baked, stats = bq.bake_rows([legacy, valid], min_quality=60)
        assert len(baked) == 1
        assert baked[0]["fuzzy_bucket"] == "h3_exact"
        assert stats["drops"]["no_bucket"] == 1

    def test_threshold_is_inclusive(self, sample_row):
        at_threshold = make_row(quality_score=60)
        just_below = make_row(quality_score=59)
        kept, drops = bq.filter_rows([at_threshold, just_below], min_quality=60)
        assert len(kept) == 1
        assert kept[0]["quality_score"] == 60
        assert drops["low_quality"] == 1

    def test_missing_quality_score_is_kept(self, sample_row):
        # score_row treats missing quality as 0 penalty; the bake filter matches
        # that by only dropping rows with a present score below the threshold.
        sample_row.pop("quality_score", None)
        kept, drops = bq.filter_rows([sample_row], min_quality=60)
        assert len(kept) == 1
        assert drops["low_quality"] == 0

    def test_drop_reasons_are_mutually_exclusive(self):
        # A row that fails multiple checks is counted under the first failure
        # in check order (bucket → display → quality), so drop counts sum to
        # exactly the number of dropped rows — not double-counted.
        bad = make_row(fuzzy_bucket=None, display_quote="", quality_score=10)
        kept, drops = bq.filter_rows([bad], min_quality=60)
        assert kept == []
        assert sum(drops.values()) == 1


class TestBakeRows:
    def test_each_kept_row_has_baked_score_tuple(self, sample_row):
        baked, _stats = bq.bake_rows([sample_row], min_quality=60)
        assert len(baked) == 1
        row = baked[0]
        assert "baked_score" in row
        assert isinstance(row["baked_score"], list)
        assert len(row["baked_score"]) == len(bq.BAKED_SCORE_COMPONENTS)
        assert all(isinstance(v, int) for v in row["baked_score"])

    def test_baked_score_matches_live_static_components(self, sample_row):
        """The baked ten-tuple equals the row-intrinsic positions of score_row."""
        baked, _ = bq.bake_rows([sample_row], min_quality=60)
        row = baked[0]
        # Reproduce the live score (empty overrides, no requested_time ⇒
        # minute_penalty = 99, override_bonus = 0) so we can strip the two
        # request-time positions out.
        source_counts = pick_quote.count_sources([sample_row])
        live = pick_quote.score_row(
            dict(sample_row),  # unbaked copy; baked_score present would short-circuit
            bucket=sample_row["fuzzy_bucket"],
            overrides={},
            requested_time=None,
            source_counts=source_counts,
        )
        expected = [live[i] for i in (0, 1, 3, 4, 5, 6, 8, 9, 10, 11)]
        assert row["baked_score"] == expected

    def test_inferred_quote_minute_cached(self, sample_row):
        baked, _ = bq.bake_rows([sample_row], min_quality=60)
        assert baked[0]["inferred_quote_minute"] == 0  # "three o'clock" → minute 0

    def test_baked_rank_is_per_bucket_dense_ordering(self):
        rows = [
            make_row(source_id="a", line_number=1, quality_score=90),
            make_row(source_id="b", line_number=2, quality_score=80),
            make_row(source_id="c", line_number=3, quality_score=70, fuzzy_bucket="h4_exact"),
        ]
        baked, _ = bq.bake_rows(rows, min_quality=60)
        ranks_by_bucket = {}
        for row in baked:
            ranks_by_bucket.setdefault(row["fuzzy_bucket"], []).append(row["baked_rank"])
        # Each bucket's ranks start at 0 and are dense.
        for bucket_ranks in ranks_by_bucket.values():
            assert bucket_ranks == list(range(len(bucket_ranks)))

    def test_per_bucket_sorted_by_baked_score(self):
        # Higher-quality rows should end up at lower baked_rank within a bucket.
        rows = [
            make_row(source_id="low", line_number=1, quality_score=70),
            make_row(source_id="high", line_number=2, quality_score=95),
        ]
        baked, _ = bq.bake_rows(rows, min_quality=60)
        by_rank = {r["baked_rank"]: r for r in baked}
        assert by_rank[0]["source_id"] == "high"
        assert by_rank[1]["source_id"] == "low"

    def test_top_n_caps_per_bucket(self):
        rows = [make_row(source_id=str(i), line_number=i, quality_score=80 + (i % 5)) for i in range(10)]
        baked, stats = bq.bake_rows(rows, min_quality=60, top_n=3)
        assert len(baked) == 3
        assert stats["per_bucket"]["max"] == 3

    def test_top_n_zero_means_keep_all(self):
        rows = [make_row(source_id=str(i), line_number=i) for i in range(5)]
        baked, _ = bq.bake_rows(rows, min_quality=60, top_n=0)
        assert len(baked) == 5

    def test_rarity_uses_full_input_corpus(self):
        """source_rarity_penalty must be computed against the full raw input,
        not the post-filter kept subset — otherwise baked and raw picks diverge
        for sources whose low-quality rows get dropped at bake time."""
        rows = [
            # One kept row for source "A"
            make_row(source_id="A", line_number=1, quality_score=80),
            # Three low-quality rows for source "A" that the baker drops
            make_row(source_id="A", line_number=2, quality_score=30),
            make_row(source_id="A", line_number=3, quality_score=30),
            make_row(source_id="A", line_number=4, quality_score=30),
            # One kept row for source "B"
            make_row(source_id="B", line_number=5, quality_score=80, fuzzy_bucket="h4_exact"),
        ]
        baked, _ = bq.bake_rows(rows, min_quality=60)
        by_source = {r["source_id"]: r for r in baked}
        rarity_idx = bq.BAKED_SCORE_COMPONENTS.index("source_rarity_penalty")
        # A had four rows total in the raw input, B had one.
        assert by_source["A"]["baked_score"][rarity_idx] == 4
        assert by_source["B"]["baked_score"][rarity_idx] == 1

    def test_stats_report_structure(self, sample_row):
        low = make_row(source_id="x", line_number=99, quality_score=40)
        daypart = make_row(source_id="y", line_number=100, fuzzy_bucket=None)
        _, stats = bq.bake_rows([sample_row, low, daypart], min_quality=60)
        assert stats == {
            "input": 3,
            "kept": 1,
            "drops": {"no_bucket": 1, "no_display_quote": 0, "low_quality": 1},
            "per_bucket": {"populated": 1, "max": 1, "min": 1},
        }


class TestMain:
    def test_writes_baked_jsonl(self, sample_row, tmp_jsonl, tmp_path, monkeypatch, capsys):
        input_path = tmp_jsonl([sample_row])
        output_path = tmp_path / "quote_database.jsonl"
        monkeypatch.setattr("sys.argv", [
            "bake_quote_database.py",
            str(input_path),
            "--output", str(output_path),
        ])
        assert bq.main() == 0
        lines = output_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert "baked_score" in row
        assert "inferred_quote_minute" in row
        assert row["baked_rank"] == 0
        summary = capsys.readouterr().out
        assert "Baked 1 rows from 1" in summary

    def test_atomic_write_leaves_existing_file_on_crash(self, sample_row, tmp_jsonl, tmp_path, monkeypatch):
        """If os.replace fails mid-write, the previous baked file must stay intact."""
        input_path = tmp_jsonl([sample_row])
        output_path = tmp_path / "quote_database.jsonl"
        output_path.write_text('{"sentinel": true}\n', encoding="utf-8")

        import atomic_io

        def boom(*args, **kwargs):
            raise OSError("simulated disk full")

        monkeypatch.setattr(atomic_io.os, "replace", boom)
        monkeypatch.setattr("sys.argv", [
            "bake_quote_database.py",
            str(input_path),
            "--output", str(output_path),
        ])
        with pytest.raises(OSError):
            bq.main()
        # The original file is untouched.
        assert json.loads(output_path.read_text(encoding="utf-8").splitlines()[0]) == {"sentinel": True}
        # And no .tmp sibling leaks.
        assert not (tmp_path / "quote_database.jsonl.tmp").exists()


class TestBakeIdempotence:
    """Re-baking an already-baked file must refresh rarity + rank, not carry
    forward the stale values cached in ``baked_score``. Without the strip in
    ``bake_rows``, ``score_row`` would short-circuit on the existing
    ``baked_score`` and reuse the previous bake's rarity."""

    def test_rarity_refreshes_when_rebaking(self):
        rarity_idx = bq.BAKED_SCORE_COMPONENTS.index("source_rarity_penalty")
        initial = [make_row(source_id="A", line_number=i, quality_score=80) for i in range(1, 4)]
        baked_first, _ = bq.bake_rows(initial, min_quality=60)
        assert baked_first[0]["baked_score"][rarity_idx] == 3

        # Simulate the corpus shrinking: one row survives from source A.
        shrunk_input = [dict(baked_first[0])]  # already carries baked_score
        baked_second, _ = bq.bake_rows(shrunk_input, min_quality=60)
        assert baked_second[0]["baked_score"][rarity_idx] == 1, (
            "rarity stayed stale — baker short-circuited on the existing "
            "baked_score instead of recomputing"
        )

    def test_does_not_mutate_input_rows(self, sample_row):
        """bake_rows must not stamp baked fields onto the caller's dicts."""
        before = dict(sample_row)
        bq.bake_rows([sample_row], min_quality=60)
        assert sample_row == before, (
            f"input row was mutated: new keys {set(sample_row) - set(before)}"
        )


class TestPipelinePosition:
    def test_load_rows_re_derives_fuzzy_bucket(self, tmp_path):
        """Mirrors pick_quote.load_rows: a stale fuzzy_bucket in the input is
        recomputed from normalized_time so bake and runtime agree on placement."""
        row = make_row(normalized_time="03:00", fuzzy_bucket="h9_half_past")  # stale
        path = tmp_path / "in.jsonl"
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        loaded = bq._load_rows(path)
        assert loaded[0]["fuzzy_bucket"] == "h3_exact"


class TestBakedScoreComponents:
    def test_component_list_matches_pick_quote(self):
        """bake_quote_database and pick_quote must describe baked_score
        identically — drift means the runtime picker reads components from the
        wrong tuple positions."""
        assert bq.BAKED_SCORE_COMPONENTS == pick_quote.BAKED_SCORE_COMPONENTS

    def test_component_count_matches_indices(self):
        assert len(bq.BAKED_SCORE_COMPONENTS) == len(bq._STATIC_SCORE_INDICES)
