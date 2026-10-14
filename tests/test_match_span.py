"""Tests for match_span.py — where the renderer finds a row's matched phrase."""
from __future__ import annotations

import pytest

from idle_hours import match_span


class TestFindDisplayMatch:
    @pytest.mark.parametrize(
        ("text", "matched", "span"),
        [
            ("It was three o'clock.", "three o'clock", "three o'clock"),
            ("At THREE O'CLOCK she left.", "three o'clock", "THREE O'CLOCK"),
            ("It was quarter past ten, and raining.", "quarter  past ten", "quarter past ten"),
        ],
    )
    def test_finds_the_span_the_renderer_bolds(self, text, matched, span):
        found = match_span.find_display_match(text, matched)
        assert found is not None and found.group(0) == span

    @pytest.mark.parametrize(
        ("text", "matched"),
        [
            ("accounts for one-quarter to one-third of national output", "quarter to one"),
            ("the Cathedral clock struck three-quarters, when it actually struck but one.", "struck three"),
            ("ten minutes before twenty-three o'clock.", "three o'clock"),
            ("who number nearly eight-ninths of the population", "nearly eight"),
            ("A quote that never names the hour.", "three o'clock"),
            ("It was three o'clock.", ""),
        ],
    )
    def test_rejects_a_phrase_that_is_not_a_whole_word_span(self, text, matched):
        assert match_span.find_display_match(text, matched) is None


class TestHasDisplayMatch:
    def test_reads_the_row_fields(self):
        assert match_span.has_display_match({"display_quote": "It was three o'clock.", "matched_text": "three o'clock"})

    def test_missing_fields_are_not_a_match(self):
        assert not match_span.has_display_match({})


class TestStatesTooPreciseATime:
    @staticmethod
    def _row(display_quote, matched_text, match_type="dotted_time"):
        return {"display_quote": display_quote, "matched_text": matched_text, "match_type": match_type}

    @pytest.mark.parametrize(
        ("text", "matched"),
        [
            ("He examined the safe at 10.31 a.m. that morning.", "at 10.31"),
            ("He went by the 4.05 from Halford.", "the 4.05"),
            ("Don't let's bother about the 3.12, she said.", "the 3.12"),
            ("He reached the rock before about 11.37 or 11.38.", "about 11.37"),
        ],
    )
    def test_an_exact_off_quarter_time_is_too_precise(self, text, matched):
        assert match_span.states_too_precise_a_time(self._row(text, matched))

    @pytest.mark.parametrize(
        ("text", "matched"),
        [
            ("He came by the 10.45 from Halford.", "the 10.45"),
            ("Mr. Felix called about 11.05 to see you.", "about 11.05"),
            ("He had reached home soon after 10.20.", "after 10.20"),
            ("He went to the Grosvenor at 6.35 or thereabouts.", "at 6.35"),
            ("She came round about 7.10 that evening.", "about 7.10"),
        ],
    )
    def test_a_quarter_hour_or_a_hedged_time_is_not(self, text, matched):
        assert not match_span.states_too_precise_a_time(self._row(text, matched))

    def test_judges_the_displayed_text_not_the_mined_context(self):
        """A hedge the cleaner cut away is not one the reader sees."""
        assert match_span.states_too_precise_a_time(self._row("10.20 struck as he came in.", "10.20", "digital"))

    def test_only_numeric_match_types_are_judged(self):
        assert not match_span.states_too_precise_a_time(self._row("At twenty-two minutes past ten.", "twenty-two minutes past ten", "minutes_past_to"))
