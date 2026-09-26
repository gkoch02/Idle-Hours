"""Tests for quality_filter.py — penalty scoring logic."""
from __future__ import annotations

import json

from idle_hours import quality_filter as qf
from tests.conftest import make_row


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

    def test_expanded_with_context_is_treated_as_clean(self):
        text = "It was three o'clock when she arrived."
        s_clean, _ = score(text, fragment=False, status="complete_sentence")
        s_expanded, flags = score(text, fragment=False, status="expanded_with_context")
        assert s_expanded == s_clean
        assert "expanded_with_context" not in flags


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
    def test_work_schedule_pattern_deducts_45(self):
        for text in (
            "Our working hours ran from nine until three o'clock every day.",
            "She took the night work shift and left at three o'clock every day.",
            "He worked nine to five and was home by six o'clock every evening.",
        ):
            s, flags = score(text)
            assert "contains_work_schedule" in flags, text
            assert s <= 55

    def test_the_verb_work_is_not_a_schedule(self):
        """Issue #296: ``\\bwork\\b`` flagged 70 corpus rows, none a schedule."""
        for text in (
            "The fearful work went on until nearly dawn, and nobody spoke a word.",
            "She would work until three o'clock every day, then walk home slowly.",
            "His custom was to work from four o'clock in the morning until dusk.",
        ):
            _s, flags = score(text)
            assert "contains_work_schedule" not in flags, text

    def test_am_pm_deducts_45(self):
        for text in (
            "She departed at 3 pm after the long meeting ended at last, exhausted.",
            "The train left at 10:30 a.m. and did not stop until it reached the coast.",
            "We shall meet at 7 AM sharp tomorrow, and you had better not be late.",
            "The office opens at nine a.m. on weekdays and closes at five p.m. daily.",
        ):
            s, flags = score(text)
            assert "contains_modern_am_pm" in flags, text

    def test_the_verb_am_is_not_a_clock_suffix(self):
        """Issue #296: every am/pm flag in the shipped corpus was "I am"."""
        for text in (
            "I am sure it was nearly ten o'clock when the letter arrived at the house.",
            "Here I am at last, she said, as the clock struck three in the hall.",
        ):
            _s, flags = score(text)
            assert "contains_modern_am_pm" not in flags, text

    def test_time_range_deducts_55(self):
        text = "Office hours are 9:00-5:00 on weekdays."
        s, flags = score(text)
        assert "contains_time_range" in flags

    def test_structural_label_deducts_35(self):
        for text in (
            "Chapter III begins at this point of the story, near three o'clock.",
            "BOOK 2 opens at this point of the story, near three o'clock at night.",
            "ACT THE SECOND. It was three o'clock when the curtain rose again.",
        ):
            s, flags = score(text)
            assert "contains_structural_label" in flags, text

    def test_prose_book_act_scene_are_not_headings(self):
        for text in (
            "The book I was reading fell shut at three o'clock, and I slept at once.",
            "It was the last act of the play, and the clock had just struck three.",
            "The scene before them at three o'clock was one of perfect stillness.",
        ):
            _s, flags = score(text)
            assert "contains_structural_label" not in flags, text

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
    def test_unbalanced_quotes_deducts_15(self):
        tail = ' he said, looking down at his watch with a frown and shaking his head slowly.'
        s, flags = score('It is five o\'clock,"' + tail)
        assert "unbalanced_quotes" in flags
        assert s == 85
        s, flags = score('"It is five o\'clock,"' + tail)
        assert "unbalanced_quotes" not in flags
        assert s == 100

    def test_score_never_below_zero(self):
        text = "working hours CHAPTER ebook 1:00-2:00 3 am 4 pm"
        s, _ = score(text, fragment=True, status="empty")
        assert s == 0


class TestMainCLI:
    def test_annotates_rows_and_writes_output(self, tmp_path, tmp_jsonl, monkeypatch, capsys):
        input_rows = [
            make_row(
                display_quote="It was exactly three o'clock when the carriage arrived at the door of Mansfield Park.",
                display_fragment=False,
                cleanup_status="complete_sentence",
            ),
            make_row(
                display_quote="bad",  # fragment + too_short + weak_ending
                display_fragment=True,
                cleanup_status="fragment_fallback",
            ),
        ]
        input_path = tmp_jsonl(input_rows)
        output_path = tmp_path / "quality.jsonl"
        monkeypatch.setattr(
            "sys.argv",
            ["quality_filter.py", str(input_path), "--output", str(output_path)],
        )
        exit_code = qf.main()
        assert exit_code == 0
        written = [json.loads(line) for line in output_path.read_text().splitlines()]
        assert len(written) == 2
        assert written[0]["quality_score"] == 100
        assert written[0]["quality_flags"] == []
        assert written[1]["quality_score"] < 50
        assert "fragment" in written[1]["quality_flags"]
        out = capsys.readouterr().out
        assert "Wrote 2 quality-scored" in out

    def test_handles_missing_display_quote_field(self, tmp_path, tmp_jsonl, monkeypatch):
        row = make_row()
        del row["display_quote"]
        input_path = tmp_jsonl([row])
        output_path = tmp_path / "quality.jsonl"
        monkeypatch.setattr(
            "sys.argv",
            ["quality_filter.py", str(input_path), "--output", str(output_path)],
        )
        assert qf.main() == 0
        written = json.loads(output_path.read_text().splitlines()[0])
        assert "quality_score" in written


class TestLeadingHeadingPenalty:
    """Issue #308: a heading still opening the excerpt is pushed under the
    bake floor even when the cleaner missed it."""

    def test_roman_numeral_heading_is_penalised(self):
        s, flags = score("XXXIV. Next morning, accordingly, she rose at five o'clock and went into the street.")
        assert "leading_heading" in flags
        assert s < 70

    def test_caps_chapter_title_is_penalised(self):
        _, flags = score(
            "WITHIN THE POWER-HOUSE At a few moments before six o'clock Byng was shown into Jasmine's sitting-room."
        )
        assert "leading_heading" in flags

    def test_play_speaker_label_is_not_a_heading(self):
        _, flags = score("ROSALIND. How say you now? Is it not past two o'clock? And here much Orlando.")
        assert "leading_heading" not in flags

    def test_pronoun_sentence_is_not_a_heading(self):
        _, flags = score("I. said nothing, but at five o'clock the carriage came round to the door.")
        assert "leading_heading" not in flags
