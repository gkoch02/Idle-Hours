"""Tests for fix_legacy_buckets.py"""
from __future__ import annotations

import json
import sys

from idle_hours.fix_legacy_buckets import canonical_bucket, main


class TestCanonicalBucket:
    def test_exact(self):
        assert canonical_bucket(3, 0) == "h3_exact"

    def test_five_past(self):
        assert canonical_bucket(3, 3) == "h3_five_past"

    def test_rolls_over_top_of_hour(self):
        # 2:58 rounds to 3:00.
        assert canonical_bucket(2, 58) == "h3_exact"

    def test_wraps_midnight(self):
        # 23:58 rounds to 00:00 → h12_exact.
        assert canonical_bucket(23, 58) == "h12_exact"

    def test_hour_24_normalises_to_12(self):
        assert canonical_bucket(12, 0) == "h12_exact"
        assert canonical_bucket(0, 0) == "h12_exact"

    def test_quarter_past(self):
        assert canonical_bucket(7, 15) == "h7_quarter_past"


class TestMain:
    def _run(self, tmp_path, row):
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        input_file.write_text(json.dumps(row) + "\n", encoding="utf-8")
        sys.argv = ["fix_legacy_buckets.py", str(input_file), "--output", str(output_file)]
        main()
        return json.loads(output_file.read_text(encoding="utf-8").strip())

    def test_repairs_legacy_state_name(self, tmp_path):
        row = {
            "hour": 1,
            "minute": 10,
            "normalized_time": "01:10",
            "fuzzy_bucket": "h1_early_past",
            "matched_text": "ten minutes past one",
            "display_quote": "It was ten minutes past one.",
        }
        result = self._run(tmp_path, row)
        assert result["fuzzy_bucket"] == "h1_ten_past"

    def test_repairs_half_pastish(self, tmp_path):
        row = {
            "hour": 4,
            "minute": 30,
            "normalized_time": "04:30",
            "fuzzy_bucket": "h4_half_pastish",
            "matched_text": "half past four",
            "display_quote": "It was half past four.",
        }
        result = self._run(tmp_path, row)
        assert result["fuzzy_bucket"] == "h4_half_past"

    def test_leaves_valid_bucket_alone(self, tmp_path):
        row = {
            "hour": 2,
            "minute": 15,
            "normalized_time": "02:15",
            "fuzzy_bucket": "h2_quarter_past",
            "matched_text": "quarter past two",
            "display_quote": "It was quarter past two.",
        }
        result = self._run(tmp_path, row)
        assert result["fuzzy_bucket"] == "h2_quarter_past"

    def test_skips_legacy_row_without_time(self, tmp_path):
        row = {
            "hour": None,
            "minute": None,
            "fuzzy_bucket": "daypart_dawn",
            "matched_text": "towards dawn",
            "display_quote": "Towards dawn she rose.",
        }
        result = self._run(tmp_path, row)
        # Invalid state but no hour/minute to recompute from — left as-is.
        assert result["fuzzy_bucket"] == "daypart_dawn"

    def test_normalises_matched_text_whitespace(self, tmp_path):
        row = {
            "hour": 3,
            "minute": 0,
            "normalized_time": "03:00",
            "fuzzy_bucket": "h3_exact",
            "matched_text": "three\no'clock",
            "display_quote": "It was three o'clock.",
        }
        result = self._run(tmp_path, row)
        assert result["matched_text"] == "three o'clock"

    def test_collapses_internal_tabs_and_multispace(self, tmp_path):
        row = {
            "hour": 5,
            "minute": 0,
            "normalized_time": "05:00",
            "fuzzy_bucket": "h5_exact",
            "matched_text": "five\t o'clock",
            "display_quote": "five o'clock",
        }
        result = self._run(tmp_path, row)
        assert result["matched_text"] == "five o'clock"

    def test_rollover_case(self, tmp_path):
        # minute=58 rounds up into the next hour.
        row = {
            "hour": 2,
            "minute": 58,
            "normalized_time": "02:58",
            "fuzzy_bucket": "h2_just_before",
            "matched_text": "nearly three",
            "display_quote": "It was nearly three.",
        }
        result = self._run(tmp_path, row)
        assert result["fuzzy_bucket"] == "h3_exact"
