"""Tests for fix_substring_time_matches.py"""
from __future__ import annotations

import json

from idle_hours.fix_substring_time_matches import (
    bucket_for_minute,
    infer_time_from_quote,
    parse_number_word,
)


class TestParseNumberWord:
    def test_simple_single_word(self):
        assert parse_number_word("five") == 5

    def test_all_singles(self):
        cases = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
            "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
            "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
        }
        for word, expected in cases.items():
            assert parse_number_word(word) == expected

    def test_compound_hyphen(self):
        assert parse_number_word("twenty-five") == 25

    def test_compound_space(self):
        assert parse_number_word("thirty five") == 35

    def test_compound_forty_two(self):
        assert parse_number_word("forty-two") == 42

    def test_case_insensitive(self):
        assert parse_number_word("FIVE") == 5
        assert parse_number_word("Twenty-Three") == 23

    def test_unknown_word_returns_none(self):
        assert parse_number_word("banana") is None

    def test_three_part_returns_none(self):
        assert parse_number_word("twenty three four") is None

    def test_empty_string_returns_none(self):
        assert parse_number_word("") is None


class TestBucketForMinute:
    # Full behavior of the underlying primitive is exercised in tests/test_buckets.py.
    # These smoke tests confirm this module still exposes it under the historical
    # ``bucket_for_minute`` name for backward compatibility.
    def test_alias_resolves_to_shared_primitive(self):
        from idle_hours.buckets import minute_bucket as shared
        assert bucket_for_minute is shared

    def test_smoke(self):
        assert bucket_for_minute(0) == "exact"
        assert bucket_for_minute(30) == "half_past"
        assert bucket_for_minute(59) == "exact"


class TestInferTimeFromQuote:
    def test_minutes_past(self):
        result = infer_time_from_quote("It was ten minutes past three in the evening.")
        assert result is not None
        assert result["hour"] == 3
        assert result["minute"] == 10
        assert result["normalized_time"] == "03:10"
        assert result["fuzzy_bucket"] == "h3_ten_past"

    def test_minutes_to(self):
        result = infer_time_from_quote("The clock read twenty minutes to six.")
        assert result is not None
        assert result["hour"] == 5
        assert result["minute"] == 40
        assert result["normalized_time"] == "05:40"
        assert result["fuzzy_bucket"] == "h5_twenty_to"

    def test_compound_minute_word(self):
        result = infer_time_from_quote("It was thirty-five minutes past two.")
        assert result is not None
        assert result["hour"] == 2
        assert result["minute"] == 35
        assert result["normalized_time"] == "02:35"

    def test_minutes_to_one_wraps_to_twelve(self):
        # "X minutes to one" means hour=12, minute=60-X
        result = infer_time_from_quote("It was five minutes to one.")
        assert result is not None
        assert result["hour"] == 12
        assert result["minute"] == 55

    def test_matched_text_returned(self):
        result = infer_time_from_quote("She arrived fifteen minutes past nine.")
        assert result is not None
        assert "fifteen minutes past nine" in result["matched_text"].lower()

    def test_no_time_phrase_returns_none(self):
        assert infer_time_from_quote("She arrived at the station.") is None

    def test_quarter_past_not_matched(self):
        # "quarter past" is not in the pattern (no digit word for 15)
        # but "fifteen minutes past" should match
        result = infer_time_from_quote("It was fifteen minutes past two.")
        assert result is not None
        assert result["minute"] == 15

    def test_normalizes_whitespace(self):
        result = infer_time_from_quote("It was   ten   minutes   past   four.")
        assert result is not None
        assert result["hour"] == 4
        assert result["minute"] == 10

    def test_case_insensitive(self):
        result = infer_time_from_quote("TWENTY MINUTES PAST SIX struck the bell.")
        assert result is not None
        assert result["hour"] == 6
        assert result["minute"] == 20

    def test_compound_minute_with_dash_then_space(self):
        # "forty- seven" arises when Gutenberg line-wraps "forty-\nseven" and
        # clean_display_quotes.py collapses the newline to a single space. The
        # repair regex must treat this as one compound minute_word so the
        # substring-collision (captured "seven minutes past ten") gets fixed
        # back to the full "forty-seven minutes past ten" (= 10:47).
        result = infer_time_from_quote(
            "At forty- seven minutes past ten Murchison fired the spark."
        )
        assert result is not None
        assert result["hour"] == 10
        assert result["minute"] == 47
        assert result["normalized_time"] == "10:47"
        assert result["fuzzy_bucket"] == "h10_quarter_to"


class TestMain:
    def test_fixes_substring_collision(self, tmp_path):
        """A row whose matched_text is a sub-string of the longer phrase gets updated."""
        import sys

        from idle_hours.fix_substring_time_matches import main

        row = {
            "display_quote": "It was thirty-five minutes past two in the afternoon.",
            "matched_text": "five minutes past two",
            "hour": 2,
            "minute": 5,
            "normalized_time": "02:05",
            "fuzzy_bucket": "h2_five_past",
        }
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        input_file.write_text(json.dumps(row) + "\n", encoding="utf-8")

        sys.argv = ["fix_substring_time_matches.py", str(input_file), "--output", str(output_file)]
        main()

        result = json.loads(output_file.read_text(encoding="utf-8").strip())
        assert result["minute"] == 35
        assert result["hour"] == 2
        assert result["fuzzy_bucket"] == "h2_twenty_five_to"

    def test_leaves_non_collision_rows_unchanged(self, tmp_path):
        import sys

        from idle_hours.fix_substring_time_matches import main

        row = {
            "display_quote": "It was ten minutes past three.",
            "matched_text": "ten minutes past three",
            "hour": 3,
            "minute": 10,
            "normalized_time": "03:10",
            "fuzzy_bucket": "h3_ten_past",
        }
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        input_file.write_text(json.dumps(row) + "\n", encoding="utf-8")

        sys.argv = ["fix_substring_time_matches.py", str(input_file), "--output", str(output_file)]
        main()

        result = json.loads(output_file.read_text(encoding="utf-8").strip())
        assert result["minute"] == 10
        assert result["fuzzy_bucket"] == "h3_ten_past"


class TestArchaicReversedCompound:
    """"five-and-twenty minutes past eight" (= 8:25) — the Victorian reversed
    compound that previously slipped through as the bare trailing phrase
    ("twenty minutes past eight" = 8:20)."""

    def test_parse_five_and_twenty(self):
        assert parse_number_word("five and twenty") == 25

    def test_parse_hyphenated_five_and_twenty(self):
        assert parse_number_word("five-and-twenty") == 25

    def test_parse_one_and_twenty(self):
        assert parse_number_word("one and twenty") == 21

    def test_parse_and_with_unknown_word_returns_none(self):
        assert parse_number_word("five and banana") is None

    def test_infer_hyphenated_past(self):
        result = infer_time_from_quote(
            "I shall be passing here at five-and-twenty minutes past seven."
        )
        assert result is not None
        assert result["matched_text"] == "five-and-twenty minutes past seven"
        assert result["normalized_time"] == "07:25"
        assert result["fuzzy_bucket"] == "h7_twenty_five_past"

    def test_infer_spaced_capitalised_past(self):
        result = infer_time_from_quote("Five and twenty minutes past eight, Winnie.")
        assert result is not None
        assert result["normalized_time"] == "08:25"
        assert result["fuzzy_bucket"] == "h8_twenty_five_past"

    def test_infer_hyphenated_to(self):
        result = infer_time_from_quote(
            "At five-and-twenty minutes to three, Captain Nemo appeared in the saloon."
        )
        assert result is not None
        assert result["normalized_time"] == "02:35"
        assert result["fuzzy_bucket"] == "h2_twenty_five_to"

    def test_main_repairs_archaic_substring_collision(self, tmp_path):
        """The exact corpus shape: matched_text captured the bare trailing
        phrase of an archaic compound; the repair rewrites it to the full
        phrase and re-derives the time fields."""
        import sys

        from idle_hours.fix_substring_time_matches import main

        row = {
            "display_quote": "Five and twenty minutes past eight, Winnie.",
            "matched_text": "twenty minutes past eight",
            "hour": 8,
            "minute": 20,
            "normalized_time": "08:20",
            "fuzzy_bucket": "h8_twenty_past",
        }
        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        input_file.write_text(json.dumps(row) + "\n", encoding="utf-8")

        sys.argv = ["fix_substring_time_matches.py", str(input_file), "--output", str(output_file)]
        main()

        fixed = json.loads(output_file.read_text(encoding="utf-8").strip())
        assert fixed["matched_text"] == "Five and twenty minutes past eight"
        assert fixed["normalized_time"] == "08:25"
        assert fixed["fuzzy_bucket"] == "h8_twenty_five_past"
