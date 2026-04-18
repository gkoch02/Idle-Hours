"""Tests for gutenberg_time_miner.py — regex patterns, time parsing, bucket logic."""
from __future__ import annotations

import re

import gutenberg_time_miner as gtm

# ---------------------------------------------------------------------------
# normalize_number_phrase
# ---------------------------------------------------------------------------

class TestNormalizeNumberPhrase:
    def test_single_word(self):
        assert gtm.normalize_number_phrase("five") == 5

    def test_compound_with_space(self):
        assert gtm.normalize_number_phrase("twenty five") == 25

    def test_compound_with_hyphen(self):
        assert gtm.normalize_number_phrase("twenty-five") == 25

    def test_unknown_returns_none(self):
        assert gtm.normalize_number_phrase("eleventy") is None

    def test_zero(self):
        assert gtm.normalize_number_phrase("zero") == 0

    def test_thirty(self):
        assert gtm.normalize_number_phrase("thirty") == 30

    def test_fifty_nine(self):
        assert gtm.normalize_number_phrase("fifty nine") == 59


# ---------------------------------------------------------------------------
# hour_word_to_int
# ---------------------------------------------------------------------------

class TestHourWordToInt:
    def test_valid_words(self):
        assert gtm.hour_word_to_int("one") == 1
        assert gtm.hour_word_to_int("twelve") == 12
        assert gtm.hour_word_to_int("six") == 6

    def test_case_insensitive(self):
        assert gtm.hour_word_to_int("THREE") == 3
        assert gtm.hour_word_to_int("Seven") == 7

    def test_zero_not_valid_hour(self):
        assert gtm.hour_word_to_int("zero") is None

    def test_thirteen_not_valid_hour(self):
        assert gtm.hour_word_to_int("thirteen") is None

    def test_unknown_returns_none(self):
        assert gtm.hour_word_to_int("noon") is None


# ---------------------------------------------------------------------------
# daypart_for_hour
# ---------------------------------------------------------------------------

class TestDaypartForHour:
    def test_midnight(self):
        assert gtm.daypart_for_hour(0) == "midnight"

    def test_dawn(self):
        assert gtm.daypart_for_hour(5) == "dawn"
        assert gtm.daypart_for_hour(6) == "dawn"

    def test_morning(self):
        assert gtm.daypart_for_hour(7) == "morning"
        assert gtm.daypart_for_hour(11) == "morning"

    def test_noon(self):
        assert gtm.daypart_for_hour(12) == "noon"

    def test_afternoon(self):
        assert gtm.daypart_for_hour(13) == "afternoon"
        assert gtm.daypart_for_hour(17) == "afternoon"

    def test_dusk(self):
        assert gtm.daypart_for_hour(18) == "dusk"
        assert gtm.daypart_for_hour(19) == "dusk"

    def test_evening(self):
        assert gtm.daypart_for_hour(20) == "evening"
        assert gtm.daypart_for_hour(22) == "evening"

    def test_night_late(self):
        assert gtm.daypart_for_hour(23) == "night"

    def test_wraps_24(self):
        assert gtm.daypart_for_hour(24) == "midnight"

    def test_none_returns_none(self):
        assert gtm.daypart_for_hour(None) is None


# ---------------------------------------------------------------------------
# build_bucket
# ---------------------------------------------------------------------------

class TestBuildBucket:
    def test_normal_hour_minute(self):
        # hour 3 is 3am → "night"; use hour 9 (9am → "morning") instead
        normalized, fuzzy, daypart = gtm.build_bucket(9, 0)
        assert normalized == "09:00"
        assert fuzzy == "h9_exact"
        assert daypart == "morning"

    def test_hour12_bucket(self):
        normalized, fuzzy, daypart = gtm.build_bucket(12, 30)
        assert normalized == "12:30"
        assert fuzzy == "h12_half_past"
        assert daypart == "noon"

    def test_explicit_daypart_ignores_hour_minute(self):
        normalized, fuzzy, daypart = gtm.build_bucket(None, None, "morning")
        assert normalized is None
        assert fuzzy is None
        assert daypart == "morning"

    def test_none_hour_minute_returns_nones(self):
        normalized, fuzzy, daypart = gtm.build_bucket(None, None)
        assert normalized is None
        assert fuzzy is None
        assert daypart is None

    def test_midnight_hour(self):
        normalized, fuzzy, _ = gtm.build_bucket(0, 0)
        assert normalized == "00:00"
        assert fuzzy == "h12_exact"


# ---------------------------------------------------------------------------
# candidate_from_match — one test per match type
# ---------------------------------------------------------------------------

def _make_match(pattern: re.Pattern, text: str) -> re.Match:
    m = pattern.search(text)
    assert m is not None, f"Pattern did not match: {text!r}"
    return m


def _get_pattern(name: str) -> re.Pattern:
    for match_type, pattern in gtm.TIME_PATTERNS:
        if match_type == name:
            return pattern
    raise KeyError(name)


class TestCandidateFromMatch:
    def _make(self, match_type: str, text: str) -> gtm.Candidate | None:
        pattern = _get_pattern(match_type)
        m = _make_match(pattern, text)
        return gtm.candidate_from_match("test.txt", "1234", text, match_type, m, 220)

    def test_oclock_word(self):
        c = self._make("oclock_word", "It was three o'clock when she left.")
        assert c is not None
        assert c.hour == 3
        assert c.minute == 0
        assert c.fuzzy_bucket == "h3_exact"

    def test_quarter_half_quarter(self):
        c = self._make("quarter_half", "The bell rang at quarter past five.")
        assert c is not None
        assert c.hour == 5
        assert c.minute == 15

    def test_quarter_half_half(self):
        c = self._make("quarter_half", "Half past two in the morning.")
        assert c is not None
        assert c.hour == 2
        assert c.minute == 30

    def test_quarter_to(self):
        c = self._make("quarter_to", "It was quarter to four.")
        assert c is not None
        assert c.hour == 3
        assert c.minute == 45

    def test_quarter_to_wraps_one(self):
        # quarter to one → hour 12, minute 45
        c = self._make("quarter_to", "Quarter to one in the afternoon.")
        assert c is not None
        assert c.hour == 12
        assert c.minute == 45

    def test_minutes_past(self):
        c = self._make("minutes_past_to", "Ten minutes past six she arrived.")
        assert c is not None
        assert c.hour == 6
        assert c.minute == 10

    def test_minutes_to(self):
        c = self._make("minutes_past_to", "Five minutes to eight the train left.")
        assert c is not None
        assert c.hour == 7
        assert c.minute == 55

    def test_minutes_to_wraps_one(self):
        c = self._make("minutes_past_to", "Five minutes to one the bell struck.")
        assert c is not None
        assert c.hour == 12
        assert c.minute == 55

    def test_just_after(self):
        c = self._make("just_after_before", "Just after three o'clock she appeared.")
        assert c is not None
        assert c.hour == 3
        assert c.minute == 3

    def test_just_before(self):
        c = self._make("just_after_before", "Almost five o'clock when he returned.")
        assert c is not None
        assert c.hour == 5
        assert c.minute == 57

    def test_clock_struck(self):
        c = self._make("clock_struck", "The clock struck midnight.")
        assert c is not None
        assert c.hour == 0
        assert c.minute == 0

    def test_clock_struck_noon(self):
        c = self._make("clock_struck", "It struck noon at last.")
        assert c is not None
        assert c.hour == 12
        assert c.minute == 0

    def test_clock_struck_hour(self):
        c = self._make("clock_struck", "The clock struck seven.")
        assert c is not None
        assert c.hour == 7
        assert c.minute == 0

    def test_daypart(self):
        c = self._make("daypart", "He walked out into the morning air.")
        assert c is not None
        assert c.daypart_bucket == "morning"
        assert c.hour is None

    def test_digital_valid(self):
        c = self._make("digital", "The train departs at 14:30.")
        assert c is not None
        assert c.hour == 14
        assert c.minute == 30

    def test_digital_invalid_hour_returns_none(self):
        pattern = _get_pattern("digital")
        text = "Reference 25:00 in the manual."
        m = pattern.search(text)
        if m:
            result = gtm.candidate_from_match("test.txt", "1234", text, "digital", m, 220)
            assert result is None

    def test_digital_chapter_context_returns_none(self):
        text = "See chapter 3:45 for details."
        pattern = _get_pattern("digital")
        m = pattern.search(text)
        if m:
            result = gtm.candidate_from_match("test.txt", "1234", text, "digital", m, 220)
            assert result is None

    def test_twenty_five_minutes_past(self):
        c = self._make("minutes_past_to", "Twenty-five minutes past nine the carriage arrived.")
        assert c is not None
        assert c.hour == 9
        assert c.minute == 25


# ---------------------------------------------------------------------------
# iter_candidates — integration smoke test
# ---------------------------------------------------------------------------

class TestSentenceWindow:
    def test_basic_mid_text(self):
        text = "She arrived early. It was three o'clock. She sat down."
        start = text.index("three")
        end = start + len("three o'clock")
        quote, context, line_no = gtm.sentence_window(text, start, end, context_chars=100)
        assert "three o'clock" in quote
        assert line_no == 1

    def test_quote_starts_after_period(self):
        text = "First sentence. It was noon. Another sentence."
        start = text.index("noon")
        end = start + 4
        quote, _, _ = gtm.sentence_window(text, start, end, context_chars=50)
        assert quote.startswith("It")

    def test_quote_ends_at_sentence_boundary(self):
        text = "Before. It was midnight. After sentence."
        start = text.index("midnight")
        end = start + len("midnight")
        quote, _, _ = gtm.sentence_window(text, start, end, context_chars=50)
        assert quote.endswith(".")
        assert "After" not in quote

    def test_context_respects_context_chars(self):
        text = "A" * 100 + "TARGET" + "B" * 100
        start = 100
        end = 106
        _, context, _ = gtm.sentence_window(text, start, end, context_chars=10)
        assert "TARGET" in context
        # Should not include all 100 A's
        assert len(context) < 50

    def test_line_number_first_line(self):
        text = "It was three o'clock in the morning."
        _, _, line_no = gtm.sentence_window(text, 7, 20, context_chars=50)
        assert line_no == 1

    def test_line_number_multiline(self):
        text = "Line one.\nLine two.\nIt was three o'clock."
        start = text.index("three")
        _, _, line_no = gtm.sentence_window(text, start, start + 5, context_chars=50)
        assert line_no == 3

    def test_no_sentence_boundary_before_match(self):
        text = "It was three o'clock in the morning"
        start = text.index("three")
        quote, context, _ = gtm.sentence_window(text, start, start + 5, context_chars=50)
        # No prior period, but should still return something
        assert "three" in quote or "three" in context

    def test_exclamation_and_question_as_boundaries(self):
        text = "How strange! It was noon! Was it really?"
        start = text.index("noon")
        end = start + 4
        quote, _, _ = gtm.sentence_window(text, start, end, context_chars=50)
        assert "It was noon" in quote


class TestIterCandidates:
    def test_finds_multiple_match_types_in_text(self):
        text = (
            "She woke at seven o'clock. "
            "By half past eight the house was quiet. "
            "Quarter to ten she departed."
        )
        from pathlib import Path
        candidates = list(gtm.iter_candidates(Path("test.txt"), None, text, 220, 0))
        match_types = {c.match_type for c in candidates}
        assert "oclock_word" in match_types
        assert "quarter_half" in match_types
        assert "quarter_to" in match_types

    def test_max_per_file_limits_results(self):
        text = " ".join([f"It was {w} o'clock." for w in ["one", "two", "three", "four", "five"]])
        from pathlib import Path
        candidates = list(gtm.iter_candidates(Path("test.txt"), None, text, 220, max_per_file=2))
        assert len(candidates) == 2
