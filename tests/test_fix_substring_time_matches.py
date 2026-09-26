"""Tests for fix_substring_time_matches.py"""
from __future__ import annotations

import json

import pytest

from idle_hours.fix_substring_time_matches import (
    bucket_for_minute,
    infer_quarter_half_from_quote,
    infer_time_from_quote,
    parse_number_word,
    repair_row,
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


class TestMultiplePhrasesInQuote:
    """Issue #301: with two ``<minutes> past/to <hour>`` phrases in one quote,
    the repair must pick the phrase that contains the row's own matched_text,
    not whichever phrase happens to come first."""

    QUOTE = (
        "It was ten minutes past three when he left, and "
        "thirty-five minutes past four when he returned."
    )

    def test_prefers_phrase_containing_current_match(self):
        result = infer_time_from_quote(self.QUOTE, "five minutes past four")
        assert result is not None
        assert (result["hour"], result["minute"]) == (4, 35)

    def test_without_current_match_first_phrase_wins(self):
        result = infer_time_from_quote(self.QUOTE)
        assert (result["hour"], result["minute"]) == (3, 10)

    def test_main_repairs_the_second_phrase(self, tmp_path):
        import sys

        from idle_hours.fix_substring_time_matches import main

        row = {
            "display_quote": self.QUOTE,
            "matched_text": "five minutes past four",
            "hour": 4,
            "minute": 5,
            "normalized_time": "04:05",
            "fuzzy_bucket": "h4_five_past",
        }
        path = tmp_path / "rows.jsonl"
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        sys.argv = ["fix_substring_time_matches.py", str(path)]
        main()
        result = json.loads(path.read_text(encoding="utf-8").strip())
        assert result["normalized_time"] == "04:35"
        assert result["matched_text"] == "thirty-five minutes past four"


class TestAtomicWriteback:
    """Issue #306: the in-place default must go through atomic_io, so a
    failure mid-write leaves the input byte-identical."""

    def test_failed_replace_leaves_input_intact(self, tmp_path, monkeypatch):
        import os
        import sys

        import pytest

        from idle_hours.fix_substring_time_matches import main

        row = {
            "display_quote": "It was thirty-five minutes past two.",
            "matched_text": "five minutes past two",
            "hour": 2,
            "minute": 5,
            "normalized_time": "02:05",
            "fuzzy_bucket": "h2_five_past",
        }
        path = tmp_path / "rows.jsonl"
        original = json.dumps(row) + "\n"
        path.write_text(original, encoding="utf-8")

        def boom(*_a, **_k):
            raise OSError("simulated crash")

        monkeypatch.setattr(os, "replace", boom)
        sys.argv = ["fix_substring_time_matches.py", str(path)]
        with pytest.raises(OSError):
            main()
        assert path.read_text(encoding="utf-8") == original
        assert [p.name for p in tmp_path.iterdir()] == ["rows.jsonl"]


class TestQuarterHalfSwallowedPhrase:
    """Legacy ``oclock_word`` rows mined on "ten o'clock" inside "half-past
    ten o'clock" sat at :00 with only the bare hour bolded while the quote
    stated a time 15-30 minutes away."""

    @pytest.mark.parametrize(
        "quote, needle, matched, hhmm, bucket, match_type",
        [
            ("It was half-past ten o’clock at night.", "ten o’clock", "half-past ten", "10:30", "h10_half_past", "quarter_half"),
            ("About half after eleven o’clock.", "eleven o’clock", "half after eleven", "11:30", "h11_half_past", "quarter_half"),
            ("From a quarter after eight o’clock on.", "eight o’clock", "quarter after eight", "08:15", "h8_quarter_past", "quarter_half"),
            ("At quarter past two o'clock he rose.", "two o'clock", "quarter past two", "02:15", "h2_quarter_past", "quarter_half"),
            ("It was a quarter to nine o’clock.", "nine o’clock", "quarter to nine", "08:45", "h8_quarter_to", "quarter_to"),
            ("It was a quarter before ten o’clock.", "ten o’clock", "quarter before ten", "09:45", "h9_quarter_to", "quarter_to"),
            ("It was a quarter to one o’clock.", "one o’clock", "quarter to one", "12:45", "h12_quarter_to", "quarter_to"),
            ("At half past twelve o’clock he came.", "twelve o’clock", "half past twelve", "12:30", "h12_half_past", "quarter_half"),
            ("It struck half-past-ten.", "ten", "half-past-ten", "10:30", "h10_half_past", "quarter_half"),
        ],
    )
    def test_infers_the_quarter_half_phrase(self, quote, needle, matched, hhmm, bucket, match_type):
        result = infer_quarter_half_from_quote(quote, needle)
        assert result is not None
        assert result["matched_text"] == matched
        assert result["normalized_time"] == hhmm
        assert result["fuzzy_bucket"] == bucket
        assert result["match_type"] == match_type

    def test_already_the_quarter_half_phrase_is_left_alone(self):
        assert infer_quarter_half_from_quote("At half past ten o’clock.", "half past ten") is None

    def test_standalone_occurrence_blocks_the_repair(self):
        # The row may have been mined on the bare "ten o'clock"; moving it
        # to 10:30 would break a correct row.
        quote = "He left at ten o’clock and came back at half-past ten o’clock."
        assert infer_quarter_half_from_quote(quote, "ten o’clock") is None

    def test_half_to_is_not_a_time(self):
        assert infer_quarter_half_from_quote("It was half to ten o’clock.", "ten o’clock") is None

    def test_different_hour_is_not_swallowed(self):
        assert infer_quarter_half_from_quote("At half-past nine, or ten o’clock.", "ten o’clock") is None


def _run_main(tmp_path, rows):
    import sys

    from idle_hours.fix_substring_time_matches import main

    path = tmp_path / "rows.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    sys.argv = ["fix_substring_time_matches.py", str(path)]
    main()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _oclock_row(**extra):
    row = {
        "source_id": "885",
        "line_number": 3988,
        "match_type": "oclock_word",
        "display_quote": "Who was in a room in your house, at half-past ten o’clock at night?",
        "matched_text": "ten o’clock",
        "hour": 10,
        "minute": 0,
        "normalized_time": "10:00",
        "fuzzy_bucket": "h10_exact",
        "daypart_bucket": "morning",
    }
    row.update(extra)
    return row


class TestMainQuarterHalf:
    def test_repairs_the_row(self, tmp_path):
        (row,) = _run_main(tmp_path, [_oclock_row()])
        assert row["matched_text"] == "half-past ten"
        assert row["match_type"] == "quarter_half"
        assert (row["hour"], row["minute"], row["normalized_time"]) == (10, 30, "10:30")
        assert row["fuzzy_bucket"] == "h10_half_past"

    def test_quarter_to_rolls_the_daypart(self):
        row = _oclock_row(display_quote="It was a quarter to seven o’clock.", matched_text="seven o’clock", hour=7)
        repair = repair_row(row)
        assert repair["normalized_time"] == "06:45"
        assert repair["daypart_bucket"] == "dawn"

    def test_repaired_twin_of_a_correct_row_is_dropped(self, tmp_path):
        twin = _oclock_row(
            match_type="quarter_half", matched_text="half-past ten", minute=30,
            normalized_time="10:30", fuzzy_bucket="h10_half_past",
        )
        rows = _run_main(tmp_path, [_oclock_row(), twin])
        assert rows == [twin]

    def test_row_whose_override_owns_the_time_is_skipped(self):
        row = _oclock_row(override_originals={"matched_text": "ten o’clock"}, override_applied=True)
        assert repair_row(row) is None

    def test_overridden_display_quote_must_agree_with_the_original(self):
        agreeing = _oclock_row(
            override_originals={"display_quote": "CHAPTER X Who was in a room at half-past ten o’clock?"},
        )
        assert repair_row(agreeing)["normalized_time"] == "10:30"
        # The original text had the bare phrase only: deleting the override
        # later would restore a quote the repaired matched_text is not in.
        disagreeing = _oclock_row(override_originals={"display_quote": "Who was there at ten o’clock?"})
        assert repair_row(disagreeing) is None
