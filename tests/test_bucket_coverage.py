"""Tests for bucket_coverage.py"""
from __future__ import annotations

from bucket_coverage import build_summary, expected_buckets, render_markdown


class TestExpectedBuckets:
    def test_count(self):
        buckets = expected_buckets()
        assert len(buckets) == 96  # 12 hours × 8 states

    def test_format(self):
        buckets = expected_buckets()
        assert "h1_exact" in buckets
        assert "h12_just_before" in buckets

    def test_all_hours_present(self):
        buckets = expected_buckets()
        for h in range(1, 13):
            assert f"h{h}_exact" in buckets

    def test_all_states_present(self):
        states = [
            "exact", "just_after", "early_past", "quarter_pastish",
            "half_pastish", "late_past", "quarter_toish", "just_before",
        ]
        buckets = expected_buckets()
        for state in states:
            assert f"h1_{state}" in buckets

    def test_no_h0(self):
        buckets = expected_buckets()
        assert not any(b.startswith("h0_") for b in buckets)


class TestBuildSummary:
    def _make_row(self, bucket, daypart=None, **kwargs):
        row = {"fuzzy_bucket": bucket, "quote_text": "Some quote.", "matched_text": "time", "source_id": "1"}
        if daypart:
            row["daypart_bucket"] = daypart
        row.update(kwargs)
        return row

    def test_empty_corpus(self):
        summary = build_summary([])
        assert summary["total_rows"] == 0
        assert summary["populated_bucket_count"] == 0
        assert summary["empty_bucket_count"] == 96
        assert summary["coverage_percent"] == 0.0

    def test_single_row(self):
        rows = [self._make_row("h3_exact")]
        summary = build_summary(rows)
        assert summary["total_rows"] == 1
        assert summary["populated_bucket_count"] == 1
        assert summary["bucket_counts"]["h3_exact"] == 1
        assert summary["bucket_counts"]["h3_just_after"] == 0

    def test_coverage_percent(self):
        rows = [self._make_row(f"h{h}_exact") for h in range(1, 13)]
        summary = build_summary(rows)
        # 12 populated out of 96 = 12.5%
        assert summary["coverage_percent"] == 12.5

    def test_empty_buckets_listed(self):
        rows = [self._make_row("h3_exact")]
        summary = build_summary(rows)
        assert "h3_exact" not in summary["empty_buckets"]
        assert "h3_just_after" in summary["empty_buckets"]

    def test_sparse_buckets(self):
        rows = [self._make_row("h5_half_pastish")] * 2
        summary = build_summary(rows)
        sparse_names = [item["bucket"] for item in summary["sparse_buckets"]]
        assert "h5_half_pastish" in sparse_names

    def test_sparse_threshold_is_three(self):
        rows = [self._make_row("h5_half_pastish")] * 4
        summary = build_summary(rows)
        sparse_names = [item["bucket"] for item in summary["sparse_buckets"]]
        assert "h5_half_pastish" not in sparse_names

    def test_dense_buckets_sorted_descending(self):
        rows = (
            [self._make_row("h1_exact")] * 10
            + [self._make_row("h2_exact")] * 5
        )
        summary = build_summary(rows)
        counts = [item["count"] for item in summary["dense_buckets"]]
        assert counts == sorted(counts, reverse=True)

    def test_daypart_counts(self):
        rows = [
            self._make_row("h3_exact", daypart="morning"),
            self._make_row("h3_exact", daypart="morning"),
            self._make_row("h9_exact", daypart="afternoon"),
        ]
        summary = build_summary(rows)
        assert summary["daypart_counts"]["morning"] == 2
        assert summary["daypart_counts"]["afternoon"] == 1

    def test_sample_quotes_capped_at_three(self):
        rows = [self._make_row("h1_exact")] * 10
        summary = build_summary(rows)
        assert len(summary["sample_quotes"]["h1_exact"]) == 3

    def test_total_expected_buckets(self):
        summary = build_summary([])
        assert summary["total_expected_buckets"] == 96


class TestRenderMarkdown:
    def _summary(self, **overrides):
        base = {
            "total_rows": 100,
            "total_expected_buckets": 96,
            "populated_bucket_count": 80,
            "empty_bucket_count": 16,
            "coverage_percent": 83.33,
            "dense_buckets": [{"bucket": "h3_exact", "count": 20}],
            "sparse_buckets": [{"bucket": "h1_just_after", "count": 1}],
            "empty_buckets": ["h2_late_past"],
            "daypart_counts": {"morning": 30, "afternoon": 20},
        }
        base.update(overrides)
        return base

    def test_contains_header(self):
        md = render_markdown(self._summary())
        assert "# Bucket Coverage Report" in md

    def test_contains_stats(self):
        md = render_markdown(self._summary())
        assert "100" in md  # total_rows
        assert "83.33" in md  # coverage_percent

    def test_contains_dense_bucket(self):
        md = render_markdown(self._summary())
        assert "h3_exact" in md

    def test_contains_sparse_bucket(self):
        md = render_markdown(self._summary())
        assert "h1_just_after" in md

    def test_contains_empty_bucket(self):
        md = render_markdown(self._summary())
        assert "h2_late_past" in md

    def test_contains_daypart_section(self):
        md = render_markdown(self._summary())
        assert "morning" in md
        assert "afternoon" in md

    def test_empty_buckets_chunked_to_eight(self):
        many_empty = [f"h{h}_exact" for h in range(1, 13)]
        # Use a summary with no dense buckets to isolate the empty-bucket section
        md = render_markdown(self._summary(empty_buckets=many_empty, dense_buckets=[]))
        # 12 buckets → 2 lines (8 + 4)
        empty_section_lines = [
            line for line in md.splitlines()
            if line.startswith("- `h") and "_exact`" in line
        ]
        assert len(empty_section_lines) == 2
