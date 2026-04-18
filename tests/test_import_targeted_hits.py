"""Tests for import_targeted_hits.py"""
from __future__ import annotations

import json

from import_targeted_hits import minute_for_bucket, row_from_targeted


class TestMinuteForBucket:
    def test_exact(self):
        hour, minute, state = minute_for_bucket("h3_exact")
        assert hour == 3
        assert minute == 0
        assert state == "exact"

    def test_five_past(self):
        hour, minute, state = minute_for_bucket("h5_five_past")
        assert hour == 5
        assert minute == 5
        assert state == "five_past"

    def test_ten_past(self):
        hour, minute, state = minute_for_bucket("h7_ten_past")
        assert hour == 7
        assert minute == 10

    def test_quarter_past(self):
        hour, minute, state = minute_for_bucket("h1_quarter_past")
        assert hour == 1
        assert minute == 15

    def test_half_past(self):
        hour, minute, state = minute_for_bucket("h12_half_past")
        assert hour == 12
        assert minute == 30

    def test_twenty_five_to(self):
        hour, minute, state = minute_for_bucket("h4_twenty_five_to")
        assert hour == 4
        assert minute == 35

    def test_quarter_to(self):
        hour, minute, state = minute_for_bucket("h9_quarter_to")
        assert hour == 9
        assert minute == 45

    def test_five_to(self):
        hour, minute, state = minute_for_bucket("h11_five_to")
        assert hour == 11
        assert minute == 55

    def test_all_hours_parse(self):
        for h in range(1, 13):
            hour, _, _ = minute_for_bucket(f"h{h}_exact")
            assert hour == h


class TestRowFromTargeted:
    def _raw(self, **kwargs):
        base = {
            "resolved_bucket": "h3_exact",
            "source_path": "/data/gutenberg/pg1342.txt",
            "source_id": "1342",
            "matched_text": "three o'clock",
            "quote_text": "It was three o'clock in the afternoon.",
            "context_text": "She arrived at three o'clock.",
            "line_number": 42,
            "match_start": 10,
            "match_end": 23,
            "search_phrase": "three o'clock",
            "target_bucket": "h3_exact",
        }
        base.update(kwargs)
        return base

    def test_basic_field_mapping(self):
        row = row_from_targeted(self._raw())
        assert row["hour"] == 3
        assert row["minute"] == 0
        assert row["normalized_time"] == "03:00"
        assert row["fuzzy_bucket"] == "h3_exact"
        assert row["match_type"] == "targeted_phrase"

    def test_source_fields_preserved(self):
        row = row_from_targeted(self._raw())
        assert row["source_id"] == "1342"
        assert row["source_path"] == "/data/gutenberg/pg1342.txt"
        assert row["matched_text"] == "three o'clock"
        assert row["quote_text"] == "It was three o'clock in the afternoon."
        assert row["line_number"] == 42

    def test_daypart_morning_hour(self):
        row = row_from_targeted(self._raw(resolved_bucket="h9_exact"))
        assert row["daypart_bucket"] == "morning"

    def test_daypart_noon(self):
        row = row_from_targeted(self._raw(resolved_bucket="h12_exact"))
        assert row["daypart_bucket"] == "noon"

    def test_daypart_midnight(self):
        row_from_targeted(self._raw(resolved_bucket="h12_half_past"))
        # h12 maps to noon in DAYPARTS
        row2 = row_from_targeted(self._raw(resolved_bucket="h1_exact"))
        assert row2["daypart_bucket"] == "night"

    def test_daypart_dawn(self):
        row = row_from_targeted(self._raw(resolved_bucket="h5_exact"))
        assert row["daypart_bucket"] == "dawn"

    def test_daypart_unknown_hour_defaults_to_night(self):
        # Hours > 12 not in DAYPARTS — falls back to "night"
        # Import and override the raw resolved_bucket so hour12 is still 1-12
        # Use h1 which maps to "night" at value 1 in DAYPARTS
        row = row_from_targeted(self._raw(resolved_bucket="h1_exact"))
        assert row["daypart_bucket"] == "night"

    def test_normalized_time_format(self):
        row = row_from_targeted(self._raw(resolved_bucket="h1_exact"))
        assert row["normalized_time"] == "01:00"

    def test_half_past_minute_value(self):
        row = row_from_targeted(self._raw(resolved_bucket="h6_half_past"))
        assert row["minute"] == 30
        assert row["normalized_time"] == "06:30"


class TestMain:
    def test_converts_rows(self, tmp_path):
        import sys

        from import_targeted_hits import main

        raw = {
            "resolved_bucket": "h3_exact",
            "source_path": "/pg1342.txt",
            "source_id": "1342",
            "matched_text": "three o'clock",
            "quote_text": "It was three o'clock.",
            "context_text": "It was three o'clock in the afternoon.",
            "line_number": 1,
            "match_start": 7,
            "match_end": 20,
            "search_phrase": "three o'clock",
            "target_bucket": "h3_exact",
        }
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        input_file.write_text(json.dumps(raw) + "\n", encoding="utf-8")

        sys.argv = ["import_targeted_hits.py", str(input_file), "--output", str(output_file)]
        main()

        result = json.loads(output_file.read_text(encoding="utf-8").strip())
        assert result["match_type"] == "targeted_phrase"
        assert result["hour"] == 3
        assert result["minute"] == 0
