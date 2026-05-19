"""Tests for bucket_coverage.py"""
from __future__ import annotations

import json

from idle_hours import bucket_coverage as bc
from idle_hours.bucket_coverage import build_summary, expected_buckets, render_markdown
from tests.conftest import make_row


class TestExpectedBuckets:
    def test_count(self):
        buckets = expected_buckets()
        assert len(buckets) == 144  # 12 hours × 12 states

    def test_format(self):
        buckets = expected_buckets()
        assert "h1_exact" in buckets
        assert "h12_five_to" in buckets

    def test_all_hours_present(self):
        buckets = expected_buckets()
        for h in range(1, 13):
            assert f"h{h}_exact" in buckets

    def test_all_states_present(self):
        states = [
            "exact", "five_past", "ten_past", "quarter_past",
            "twenty_past", "twenty_five_past", "half_past", "twenty_five_to",
            "twenty_to", "quarter_to", "ten_to", "five_to",
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
        assert summary["empty_bucket_count"] == 144
        assert summary["coverage_percent"] == 0.0

    def test_single_row(self):
        rows = [self._make_row("h3_exact")]
        summary = build_summary(rows)
        assert summary["total_rows"] == 1
        assert summary["populated_bucket_count"] == 1
        assert summary["bucket_counts"]["h3_exact"] == 1
        assert summary["bucket_counts"]["h3_five_past"] == 0

    def test_coverage_percent(self):
        rows = [self._make_row(f"h{h}_exact") for h in range(1, 13)]
        summary = build_summary(rows)
        # 12 populated out of 144 = 8.33%
        assert summary["coverage_percent"] == 8.33

    def test_empty_buckets_listed(self):
        rows = [self._make_row("h3_exact")]
        summary = build_summary(rows)
        assert "h3_exact" not in summary["empty_buckets"]
        assert "h3_five_past" in summary["empty_buckets"]

    def test_sparse_buckets(self):
        rows = [self._make_row("h5_half_past")] * 2
        summary = build_summary(rows)
        sparse_names = [item["bucket"] for item in summary["sparse_buckets"]]
        assert "h5_half_past" in sparse_names

    def test_sparse_threshold_is_three(self):
        rows = [self._make_row("h5_half_past")] * 4
        summary = build_summary(rows)
        sparse_names = [item["bucket"] for item in summary["sparse_buckets"]]
        assert "h5_half_past" not in sparse_names

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
        assert summary["total_expected_buckets"] == 144


class TestRenderMarkdown:
    def _summary(self, **overrides):
        base = {
            "total_rows": 100,
            "total_expected_buckets": 144,
            "populated_bucket_count": 80,
            "empty_bucket_count": 64,
            "coverage_percent": 83.33,
            "dense_buckets": [{"bucket": "h3_exact", "count": 20}],
            "sparse_buckets": [{"bucket": "h1_five_past", "count": 1}],
            "empty_buckets": ["h2_twenty_five_to"],
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
        assert "h1_five_past" in md

    def test_contains_empty_bucket(self):
        md = render_markdown(self._summary())
        assert "h2_twenty_five_to" in md

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


class TestLoadRows:
    def test_rebuckets_from_normalized_time(self, tmp_jsonl):
        row = make_row(normalized_time="03:32", fuzzy_bucket="bogus")
        path = tmp_jsonl([row])
        rows = bc.load_rows(path)
        assert rows[0]["fuzzy_bucket"] == "h3_half_past"

    def test_invalid_normalized_time_preserves_existing_bucket(self, tmp_jsonl):
        row = make_row(normalized_time="not-a-time", fuzzy_bucket="h3_exact")
        path = tmp_jsonl([row])
        rows = bc.load_rows(path)
        assert rows[0]["fuzzy_bucket"] == "h3_exact"

    def test_unparseable_normalized_time_preserves_existing_bucket(self, tmp_jsonl):
        # Has a colon (so we enter the try block) but the parts are not ints —
        # exercises the ``except (ValueError, KeyError)`` branch in load_rows.
        row = make_row(normalized_time="ab:cd", fuzzy_bucket="h3_exact")
        path = tmp_jsonl([row])
        rows = bc.load_rows(path)
        assert rows[0]["fuzzy_bucket"] == "h3_exact"


class TestMainCLI:
    def test_writes_json_and_markdown(self, tmp_path, tmp_jsonl, monkeypatch, capsys):
        input_path = tmp_jsonl([
            make_row(fuzzy_bucket="h3_exact", normalized_time="03:00", daypart_bucket="morning"),
            make_row(fuzzy_bucket="h3_exact", normalized_time="03:00", daypart_bucket="morning"),
            make_row(fuzzy_bucket="h7_half_past", normalized_time="07:30", daypart_bucket="morning"),
        ])
        out_json = tmp_path / "coverage.json"
        out_md = tmp_path / "coverage.md"
        monkeypatch.setattr(
            "sys.argv",
            ["bucket_coverage.py", str(input_path), "--output-json", str(out_json), "--output-md", str(out_md)],
        )
        exit_code = bc.main()
        assert exit_code == 0
        summary = json.loads(out_json.read_text())
        assert summary["total_rows"] == 3
        assert summary["populated_bucket_count"] == 2
        assert summary["total_expected_buckets"] == 144
        md = out_md.read_text()
        assert "# Bucket Coverage Report" in md
        out = capsys.readouterr().out
        assert "Coverage:" in out
        assert "Empty buckets:" in out
