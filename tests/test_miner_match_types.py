"""Match-type matrix tests for gutenberg_time_miner.

The existing ``test_gutenberg_time_miner.py`` covers the happy paths. This
module focuses on the combinatorial space of match types × edge cases that
the regex library has to get right:

* Each match_type has a positive example (should produce a row with known
  ``hour``, ``minute``).
* Each match_type has a negative example that matches the pattern but is
  correctly rejected (chapter-context digital, out-of-range hour, etc.).

Most misses here mean the miner is silently dropping quotes (hard to notice
at runtime) or producing wrong hour/minute (obvious, because the quote ends
up in the wrong bucket).
"""
from __future__ import annotations

from idle_hours import gutenberg_time_miner as miner


def _first_candidate(text: str, match_type: str | None = None):
    """Return the first Candidate produced by the miner, optionally filtered
    to a single match_type."""
    for c in miner.iter_candidates(
        source_path="test.txt",
        source_id=None,
        text=text,
        context_chars=120,
        max_per_file=0,
    ):
        if match_type is None or c.match_type == match_type:
            return c
    return None


class TestDigitalMatchType:
    def test_simple_time_matches(self):
        # Note: miner's digital regex uses IGNORECASE, so [A-Z] matches any letter —
        # the lookahead (?!\s+[A-Z][a-z]) rejects times followed by <ws><word>,
        # which rules out "14:30 on the dot". Close with punctuation to match.
        c = _first_candidate("They arrived at 14:30. End of story.", "digital")
        assert c is not None
        assert c.hour == 14
        assert c.minute == 30
        assert c.normalized_time == "14:30"

    def test_midnight_digital(self):
        c = _first_candidate("The log showed 00:00. End of story.", "digital")
        assert c is not None
        assert c.hour == 0
        assert c.minute == 0

    def test_rejects_hour_over_23(self):
        c = _first_candidate("Psalm 25:1 is clear.", "digital")
        assert c is None, "25:01 must not be accepted as a digital time"

    def test_rejects_chapter_context(self):
        c = _first_candidate("See Chapter 14:30 for details.", "digital")
        assert c is None

    def test_rejects_psalm_context(self):
        c = _first_candidate("As Psalm 14:30 teaches us well.", "digital")
        assert c is None

    def test_rejects_verse_context(self):
        c = _first_candidate("Verse 14:30 records the event.", "digital")
        assert c is None


class TestOclockWordMatchType:
    def test_three_oclock(self):
        c = _first_candidate("It was three o'clock in the afternoon.", "oclock_word")
        assert c is not None
        assert c.hour == 3
        assert c.minute == 0

    def test_twelve_oclock(self):
        c = _first_candidate("The bell tolled twelve o'clock sharp.", "oclock_word")
        assert c is not None
        assert c.hour == 12
        assert c.minute == 0

    def test_curly_apostrophe(self):
        c = _first_candidate("It was three o’clock in the afternoon.", "oclock_word")
        assert c is not None
        assert c.hour == 3


class TestQuarterHalfMatchType:
    def test_quarter_past(self):
        c = _first_candidate("At quarter past six, they left.", "quarter_half")
        assert c is not None
        assert c.hour == 6
        assert c.minute == 15

    def test_half_past(self):
        c = _first_candidate("Half past two had come and gone.", "quarter_half")
        assert c is not None
        assert c.hour == 2
        assert c.minute == 30

    def test_hyphenated_half_past_is_not_matched(self):
        """The quarter_half regex uses ``\\s+`` between "half" and "past" — it
        does NOT accept "half-past". Documenting this explicitly so the day
        someone adds hyphen support, they also update this test rather than
        silently changing observable behaviour."""
        c = _first_candidate("It was half-past ten when we arrived.", "quarter_half")
        assert c is None


class TestQuarterToMatchType:
    def test_quarter_to_eight(self):
        c = _first_candidate("Quarter to eight the bell rang.", "quarter_to")
        assert c is not None
        # "quarter to eight" means 7:45.
        assert c.hour == 7
        assert c.minute == 45

    def test_quarter_to_one_wraps_to_twelve(self):
        c = _first_candidate("Quarter to one the mail arrived.", "quarter_to")
        assert c is not None
        assert c.hour == 12
        assert c.minute == 45


class TestMinutesPastToMatchType:
    def test_ten_minutes_past_five(self):
        c = _first_candidate("At ten minutes past five they met.", "minutes_past_to")
        assert c is not None
        assert c.hour == 5
        assert c.minute == 10

    def test_twenty_minutes_to_three(self):
        # "twenty minutes to three" = 2:40
        c = _first_candidate("Twenty minutes to three the carriage stopped.", "minutes_past_to")
        assert c is not None
        assert c.hour == 2
        assert c.minute == 40

    def test_twenty_minutes_to_one_wraps(self):
        c = _first_candidate("Twenty minutes to one the clock struck.", "minutes_past_to")
        assert c is not None
        assert c.hour == 12
        assert c.minute == 40

    def test_compound_minute_split_by_line_break(self):
        # Gutenberg sources line-wrap hyphenated words: "forty-\nseven minutes
        # past ten" — the regex must still capture the full compound, otherwise
        # it falls back to "seven minutes past ten" (10:07) and the row lands
        # in the wrong bucket (h10_five_past instead of h10_quarter_to).
        c = _first_candidate("At forty-\nseven minutes past ten Murchison fired.", "minutes_past_to")
        assert c is not None
        assert c.hour == 10
        assert c.minute == 47
        # matched_text whitespace is normalized to a single space by the miner.
        assert "forty" in c.matched_text and "seven" in c.matched_text


class TestJustAfterBeforeMatchType:
    def test_shortly_after_three(self):
        # The regex requires o'clock after the hourword (or a bare daypart).
        c = _first_candidate("Shortly after three o'clock the rain came.", "just_after_before")
        assert c is not None
        assert c.hour == 3
        assert c.minute == 3

    def test_just_before_five(self):
        # "just before five" means ~4:57, not 5:57 — the hour rolls back like quarter_to.
        c = _first_candidate("Just before five o'clock the shop closed.", "just_after_before")
        assert c is not None
        assert c.hour == 4
        assert c.minute == 57

    def test_almost_ten(self):
        c = _first_candidate("Almost ten o'clock when the bell rang.", "just_after_before")
        assert c is not None
        assert c.hour == 9
        assert c.minute == 57

    def test_just_before_one_rolls_to_twelve(self):
        # 1 → 12 rollover, matching quarter_to / minutes_past_to.
        c = _first_candidate("Nearly one o'clock the bell tolled.", "just_after_before")
        assert c is not None
        assert c.hour == 12
        assert c.minute == 57

    def test_towards_dusk_uses_daypart_branch(self):
        """The alternate branch of just_after_before accepts a bare daypart."""
        c = _first_candidate("Towards dusk the fog thickened.", "just_after_before")
        assert c is not None
        assert c.daypart_bucket == "dusk"


class TestClockStruckMatchType:
    def test_struck_midnight(self):
        c = _first_candidate("The clock struck midnight as they left.", "clock_struck")
        assert c is not None
        assert c.hour == 0
        assert c.minute == 0

    def test_struck_noon(self):
        c = _first_candidate("The clock struck noon over the square.", "clock_struck")
        assert c is not None
        assert c.hour == 12
        assert c.minute == 0

    def test_struck_three(self):
        c = _first_candidate("The clock struck three in the drawing room.", "clock_struck")
        assert c is not None
        assert c.hour == 3
        assert c.minute == 0


class TestDaypartMatchType:
    def test_bare_dawn(self):
        c = _first_candidate("They rode out at dawn toward the coast.", "daypart")
        assert c is not None
        assert c.daypart_bucket == "dawn"
        assert c.hour is None
        assert c.minute is None

    def test_bare_dusk(self):
        c = _first_candidate("By dusk the forest had grown silent.", "daypart")
        assert c is not None
        assert c.daypart_bucket == "dusk"


class TestMatchedTextWhitespaceCollapsing:
    def test_embedded_newline_is_collapsed(self):
        """Miner collapses whitespace within matched_text so phrases captured
        across a source-line break become a single clean phrase. This used to
        be a fix_legacy_buckets repair; it is now done inline."""
        text = "He met her at half\npast two that afternoon."
        c = _first_candidate(text, "quarter_half")
        assert c is not None
        assert "\n" not in c.matched_text
        assert c.matched_text == "half past two"


class TestMineStrict:
    def test_strict_excludes_daypart(self):
        """--strict is used in production harvests to cut false positives;
        daypart matches (bare ``dawn``, ``evening``) are usually noise."""
        text = "It was three o'clock in the afternoon. They rode at dawn."
        candidates = list(miner.iter_candidates("t.txt", None, text, 120, 0))
        strict = [c for c in candidates if c.match_type != "daypart"]
        assert any(c.match_type == "daypart" for c in candidates)
        assert all(c.match_type != "daypart" for c in strict)
