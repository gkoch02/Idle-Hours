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
