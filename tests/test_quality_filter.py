"""Tests for quality_filter.py — penalty scoring logic."""
from __future__ import annotations

import quality_filter as qf


def score(text, fragment=False, status="complete_sentence"):
    return qf.score_quote(text, fragment, status)


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

class TestBaseline:
    def test_perfect_quote_scores_100(self):
        # A ~140-char complete sentence with no bad patterns
        text = "It was exactly three o'clock when the carriage arrived at the door of Mansfield Park."
        s, flags = score(text)
        assert s == 100
        assert flags == []


# ---------------------------------------------------------------------------
# Fragment and cleanup penalties
# ---------------------------------------------------------------------------

class TestFragmentPenalty:
    def test_fragment_deducts_30(self):
        text = "It was three o'clock when she arrived."
        s_clean, _ = score(text, fragment=False, status="complete_sentence")
        s_frag, flags = score(text, fragment=True, status="complete_sentence")
        assert s_frag == s_clean - 30
        assert "fragment" in flags

    def test_non_complete_sentence_deducts_20(self):
        text = "It was three o'clock when she arrived."
        s_clean, _ = score(text, fragment=False, status="complete_sentence")
        s_bad, flags = score(text, fragment=False, status="fragment_fallback")
        assert s_bad == s_clean - 20
        assert "fragment_fallback" in flags


# ---------------------------------------------------------------------------
# Length penalties
# ---------------------------------------------------------------------------

class TestLengthPenalties:
    def test_too_short_deducts_20(self):
        text = "Three o'clock."
        s, flags = score(text)
        assert "too_short" in flags
        assert s <= 80

    def test_short_deducts_8(self):
        text = "It struck three in the hall and the room fell quiet."
        assert 50 <= len(text) < 80
        s, flags = score(text)
        assert "short" in flags

    def test_ideal_length_no_penalty(self):
        # ~140 chars
        text = "It was exactly three o'clock when the carriage arrived at the door of Mansfield Park."
        assert 80 <= len(text) <= 200
        s, flags = score(text)
        assert "too_short" not in flags
        assert "short" not in flags
        assert "too_long" not in flags
        assert "long" not in flags

    def test_long_deducts_8(self):
        text = "A" * 201 + "."
        s, flags = score(text)
        assert "long" in flags

    def test_too_long_deducts_20(self):
        text = "A" * 261 + "."
        s, flags = score(text)
        assert "too_long" in flags


# ---------------------------------------------------------------------------
# Digit penalties
# ---------------------------------------------------------------------------

class TestDigitPenalties:
    def test_digit_heavy_deducts_25(self):
        text = "Reference numbers: 1, 2, 3, 4, 5, 6 in the document."
        s, flags = score(text)
        assert "digit_heavy" in flags

    def test_some_digits_deducts_10(self):
        text = "At 3:00 on the 15th she left."
        s, flags = score(text)
        assert "some_digits" in flags

    def test_no_digits_no_penalty(self):
        text = "It was three o'clock when she arrived at last."
        _, flags = score(text)
        assert "digit_heavy" not in flags
        assert "some_digits" not in flags


# ---------------------------------------------------------------------------
# Uppercase ratio
# ---------------------------------------------------------------------------

class TestUppercasePenalty:
    def test_uppercase_heavy_deducts_15(self):
        # >18% uppercase: use all-caps words
        text = "THE CLOCK STRUCK THREE at the MANSION."
        _, flags = score(text)
        assert "uppercase_heavy" in flags

    def test_normal_case_no_penalty(self):
        text = "It was three o'clock in the afternoon."
        _, flags = score(text)
        assert "uppercase_heavy" not in flags


# ---------------------------------------------------------------------------
# Bad patterns
# ---------------------------------------------------------------------------

class TestBadPatterns:
    def test_work_pattern_deducts_45(self):
        text = "She would work until three o'clock every day."
        s, flags = score(text)
        assert "contains_work_schedule" in flags
        assert s <= 55

    def test_am_pm_deducts_45(self):
        # \bpm\b requires a space before pm; "3pm" has no word boundary between digit and p
        text = "She departed at three pm after the long meeting ended at last."
        s, flags = score(text)
        assert "contains_modern_am_pm" in flags

    def test_time_range_deducts_55(self):
        text = "Office hours are 9:00-5:00 on weekdays."
        s, flags = score(text)
        assert "contains_time_range" in flags

    def test_structural_label_deducts_35(self):
        text = "Chapter three begins at this point."
        s, flags = score(text)
        assert "contains_structural_label" in flags

    def test_metadata_deducts_55(self):
        text = "This ebook is provided by Project Gutenberg for free."
        s, flags = score(text)
        assert "contains_metadata" in flags


# ---------------------------------------------------------------------------
# Weak ending
# ---------------------------------------------------------------------------

class TestWeakEnding:
    def test_no_terminal_punct_deducts_10(self):
        text = "She arrived at three o'clock in the afternoon"
        s, flags = score(text)
        assert "weak_ending" in flags

    def test_period_ending_no_penalty(self):
        text = "She arrived at three o'clock."
        _, flags = score(text)
        assert "weak_ending" not in flags

    def test_closing_quote_ending_no_penalty(self):
        text = 'She said "it is three o\u2019clock."'
        _, flags = score(text)
        assert "weak_ending" not in flags


# ---------------------------------------------------------------------------
# Score floor
# ---------------------------------------------------------------------------

class TestScoreFloor:
    def test_score_never_below_zero(self):
        text = "work chapter ebook 1:00-2:00 am pm"
        s, _ = score(text, fragment=True, status="empty")
        assert s == 0
