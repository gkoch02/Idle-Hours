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

import pytest

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

    @pytest.mark.parametrize(
        "text, hour, minute",
        [
            ("It was half-past ten when we arrived.", 10, 30),
            ("At a quarter-past six the lamps were lit.", 6, 15),
            ("It was half-past-ten by the kitchen clock.", 10, 30),
            ("We dined at a quarter after seven.", 7, 15),
            ("The coach left at half after four.", 4, 30),
        ],
    )
    def test_hyphenated_and_after_forms(self, text, hour, minute):
        """Issue #301: "half-past" / "quarter after" / "half after" used to
        produce no row at all, so every hyphenated period text lost its
        half-hours."""
        c = _first_candidate(text, "quarter_half")
        assert c is not None
        assert (c.hour, c.minute) == (hour, minute)

    def test_half_after_needs_an_hour_word(self):
        assert _first_candidate("Half after dinner he slept.", "quarter_half") is None


class TestQuarterToMatchType:
    def test_quarter_to_eight(self):
        c = _first_candidate("Quarter to eight the bell rang.", "quarter_to")
        assert c is not None
        # "quarter to eight" means 7:45.
        assert c.hour == 7
        assert c.minute == 45

    @pytest.mark.parametrize(
        "text, hour, minute",
        [
            ("It wanted a quarter before ten.", 9, 45),
            ("At a quarter-to-six the lamps were lit.", 5, 45),
            ("It was a quarter\nto seven.", 6, 45),
        ],
    )
    def test_before_hyphen_and_wrapped_forms(self, text, hour, minute):
        c = _first_candidate(text, "quarter_to")
        assert c is not None
        assert (c.hour, c.minute) == (hour, minute)

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


    @pytest.mark.parametrize(
        "text, hour, minute",
        [
            ("It was five-and-twenty minutes past seven.", 7, 25),
            ("At five and twenty minutes to nine she rose.", 8, 35),
            ("Some three-and-thirty minutes past two.", 2, 33),
            # A line break inside the compound: the regex used a literal
            # ``[- ]`` around "and", so the wrapped form fell back to the
            # trailing "twenty minutes past seven" (7:20).
            ("It was five and\ntwenty minutes past seven.", 7, 25),
            ("It was five-and-\ntwenty minutes past seven.", 7, 25),
        ],
    )
    def test_reversed_compound_minutes(self, text, hour, minute):
        """Issue #301: the archaic "five-and-twenty" form was mined as its
        trailing "twenty minutes past seven" — five minutes early."""
        c = _first_candidate(text, "minutes_past_to")
        assert c is not None
        assert (c.hour, c.minute) == (hour, minute)
        assert "and" in c.matched_text

    def test_normalize_reversed_compound(self):
        assert miner.normalize_number_phrase("five-and-twenty") == 25
        assert miner.normalize_number_phrase("five and twenty") == 25
        assert miner.normalize_number_phrase("twenty and five") is None


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

    def test_a_little_before_nine(self):
        # The Moonstone 155:18444 was mined as a bare "nine o'clock" at 09:00
        # because "a little before" was missing from the prefix list.
        c = _first_candidate("A little before nine o’clock, I prevailed on Mr. Blake.", "just_after_before")
        assert c is not None
        assert (c.hour, c.minute) == (8, 57)
        assert c.matched_text.lower().startswith("a little before")

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


class TestOverlappingPatterns:
    """Issue #298: the longer, more specific phrase wins an overlapping span."""

    def _all(self, text):
        return list(miner.iter_candidates(source_path="test.txt", source_id=None, text=text, context_chars=120, max_per_file=0))

    def test_just_after_swallows_the_bare_oclock(self):
        cands = self._all("It was just after nine o'clock when the storm broke.")
        assert [(c.match_type, c.normalized_time) for c in cands] == [("just_after_before", "09:03")]

    def test_nearly_swallows_the_bare_oclock(self):
        cands = self._all("It was nearly one o'clock before the house was quiet.")
        assert [(c.match_type, c.normalized_time) for c in cands] == [("just_after_before", "12:57")]

    def test_minutes_past_swallows_the_bare_oclock(self):
        cands = self._all("At five minutes past five o'clock the coach left the yard.")
        assert [(c.match_type, c.normalized_time) for c in cands] == [("minutes_past_to", "05:05")]

    def test_clock_struck_swallows_the_bare_daypart(self):
        cands = self._all("The clock struck midnight as they left the hall.")
        assert [(c.match_type, c.normalized_time) for c in cands] == [("clock_struck", "00:00")]

    def test_disjoint_matches_are_all_kept_in_text_order(self):
        cands = self._all("She woke at seven o'clock. By half past eight the house was quiet. Quarter to ten she left.")
        assert [c.match_type for c in cands] == ["oclock_word", "quarter_half", "quarter_to"]
        assert [c.match_start for c in cands] == sorted(c.match_start for c in cands)


class TestStruckNeedsAStriker:
    """Issue #298: bare ``struck N`` is the verb unless a clock is in reach."""

    @pytest.mark.parametrize("text", [
        "She struck one of the fish with her rod and hauled it in.",
        "The old lady, she struck one as an uncommonly strong dose.",
        "The lightning struck one of the tallest trees on the ridge.",
        "The book struck one of the other boys full in the face.",
        "He had not known how it really struck one until that moment.",
        "As agreed among themselves about the time, they struck five.",
        # "o'clock" nearby is not a striker: \b sits inside it, before "clock".
        "She struck one of the fish; it was four o'clock by then.",
        "He struck two of them down. At five o’clock the fighting stopped.",
    ])
    def test_the_verb_is_rejected(self, text):
        assert _first_candidate(text, "clock_struck") is None

    @pytest.mark.parametrize("text, hour", [
        ("The clock struck one.", 1),
        ("As the chime struck one, Campbell turned round.", 1),
        ("Coggan's watch struck two.", 2),
        ("As the Cathedral clock struck two in the morning we set out.", 2),
        ("They had cleared the town as the church-bell struck two.", 2),
        ("It struck midnight.", 0),
        ("The distant clock had just struck noon when I heard it.", 12),
        ("It struck six long ago, and still nobody came.", 6),
        ("It had just struck eight when the door opened.", 8),
        ("It had just struck three on the Palace clock.", 3),
        # "struck N o'clock" names a time whoever the subject is — including
        # the impersonal "it struck one", which the idiom guard would reject.
        ("It struck one o'clock as we came in.", 1),
        ("Somewhere far off it struck four o’clock, and she rose to go.", 4),
    ])
    def test_a_striker_within_reach_is_accepted(self, text, hour):
        c = _first_candidate(text, "clock_struck")
        assert c is not None, text
        assert c.hour == hour
