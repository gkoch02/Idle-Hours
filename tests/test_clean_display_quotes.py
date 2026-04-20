"""Tests for clean_display_quotes.py — sentence extraction and fragment detection."""
from __future__ import annotations

import json

import clean_display_quotes as cdq
from tests.conftest import make_row

# ---------------------------------------------------------------------------
# split_sentences
# ---------------------------------------------------------------------------

class TestSplitSentences:
    def test_single_sentence(self):
        assert cdq.split_sentences("Hello world.") == ["Hello world."]

    def test_multiple_sentences(self):
        parts = cdq.split_sentences("She left. He stayed. They wept.")
        assert len(parts) == 3

    def test_exclamation_and_question(self):
        parts = cdq.split_sentences("What time is it? Three o'clock! Good.")
        assert len(parts) == 3

    def test_empty_string(self):
        assert cdq.split_sentences("") == []

    def test_collapses_whitespace(self):
        parts = cdq.split_sentences("Hello   world.")
        assert parts == ["Hello world."]

    def test_strips_individual_parts(self):
        parts = cdq.split_sentences("  First sentence.  Second sentence.  ")
        assert all(p == p.strip() for p in parts)

    def test_no_split_on_abbreviation_mid_sentence(self):
        # Sentences separated by newlines in context
        parts = cdq.split_sentences("It was 3 o'clock. She left.")
        assert len(parts) == 2


# ---------------------------------------------------------------------------
# clean_edges
# ---------------------------------------------------------------------------

class TestCleanEdges:
    def test_removes_leading_dash(self):
        # LEADING_JUNK strips hyphens (-) not em-dashes (—); use a hyphen
        assert cdq.clean_edges("-Hello world.") == "Hello world."

    def test_removes_trailing_comma(self):
        assert cdq.clean_edges("Hello world,") == "Hello world"

    def test_removes_leading_quote(self):
        assert cdq.clean_edges('"She said hello."') == "She said hello."

    def test_keeps_interior_punct(self):
        result = cdq.clean_edges("Hello, world.")
        assert "," in result

    def test_empty_string(self):
        assert cdq.clean_edges("") == ""

    def test_collapses_internal_whitespace(self):
        assert cdq.clean_edges("Hello   world.") == "Hello world."

    def test_strips_narrative_heading_prefix(self):
        text = "MR. WHYMPER'S NARRATIVE We started from Zermatt at half past five."
        assert cdq.clean_edges(text) == "We started from Zermatt at half past five."

    def test_strips_chapter_heading_and_all_caps_section_title(self):
        text = "CHAPTER IV. IN WHICH PHILEAS FOGG ASTOUNDS PASSEPARTOUT, HIS SERVANT Having won twenty guineas at whist."
        assert cdq.clean_edges(text) == "Having won twenty guineas at whist."

    def test_strips_bare_in_which_section_title(self):
        text = "IN WHICH PHILEAS FOGG ASTOUNDS PASSEPARTOUT, HIS SERVANT Having won twenty guineas at whist."
        assert cdq.clean_edges(text) == "Having won twenty guineas at whist."


# ---------------------------------------------------------------------------
# looks_fragment
# ---------------------------------------------------------------------------

class TestLooksFragment:
    def test_empty_is_fragment(self):
        assert cdq.looks_fragment("") is True

    def test_too_short_is_fragment(self):
        assert cdq.looks_fragment("Hi.") is True

    def test_no_terminal_punct_is_fragment(self):
        assert cdq.looks_fragment("She walked to the door") is True

    def test_lowercase_start_is_fragment(self):
        assert cdq.looks_fragment("and then she left.") is True

    def test_complete_sentence_not_fragment(self):
        assert cdq.looks_fragment("She walked to the door.") is False

    def test_ends_with_question_mark(self):
        assert cdq.looks_fragment("What time is it now?") is False

    def test_ends_with_exclamation(self):
        assert cdq.looks_fragment("Three o'clock at last!") is False

    def test_ends_with_closing_quote(self):
        assert cdq.looks_fragment('She said "three o\'clock."') is False


# ---------------------------------------------------------------------------
# best_display_quote
# ---------------------------------------------------------------------------

class TestBestDisplayQuote:
    def _row(self, quote_text="", context_text="", matched_text="three o'clock"):
        return {"quote_text": quote_text, "context_text": context_text, "matched_text": matched_text}

    def test_returns_complete_sentence_when_available(self):
        row = self._row(
            quote_text="It was three o'clock in the afternoon.",
            context_text="It was three o'clock in the afternoon when she left.",
        )
        text, is_frag, status = cdq.best_display_quote(row)
        assert status == "complete_sentence"
        assert is_frag is False
        assert "three o'clock" in text

    def test_prefers_sentence_containing_matched_text(self):
        row = self._row(
            quote_text="Some preamble. It was three o'clock. Some postamble.",
            context_text="",
        )
        text, _, status = cdq.best_display_quote(row)
        assert status == "complete_sentence"
        assert "three o'clock" in text

    def test_falls_back_to_fragment(self):
        row = self._row(
            quote_text="three o'clock",
            context_text="three o'clock",
        )
        text, is_frag, status = cdq.best_display_quote(row)
        assert is_frag is True
        assert status == "fragment_fallback"

    def test_empty_row_returns_empty(self):
        row = self._row(quote_text="", context_text="", matched_text="")
        text, is_frag, status = cdq.best_display_quote(row)
        assert status == "empty"
        assert text == ""

    def test_picks_length_closest_to_140(self):
        short = "It was three o'clock."
        ideal = "It was three o'clock when the long-awaited letter finally arrived at the house."
        very_long = "It was three o'clock when the long-awaited letter finally arrived at the house and she read it."
        # Build a quote_text that has all three as separate sentences
        full = f"{short} {ideal} {very_long}"
        row = self._row(quote_text=full, context_text="")
        text, _, status = cdq.best_display_quote(row)
        assert status == "complete_sentence"
        assert abs(len(text) - 140) <= abs(len(short) - 140)

    def test_strips_heading_from_context_sentence(self):
        row = self._row(
            quote_text="half past five, on a brilliant and perfectly cloudless morning.",
            context_text="MR. WHYMPER'S NARRATIVE We started from Zermatt on the 13th of July, at half past five, on a brilliant and perfectly cloudless morning.",
            matched_text="half past five",
        )
        text, is_frag, status = cdq.best_display_quote(row)
        assert text.startswith("We started from Zermatt")
        assert "WHYMPER'S NARRATIVE" not in text
        assert is_frag is False
        assert status == "complete_sentence"

    def test_strips_chapter_heading_from_context_sentence(self):
        row = self._row(
            quote_text="Phileas Fogg, at twenty-five minutes past seven, left the Reform Club.",
            context_text="CHAPTER IV. IN WHICH PHILEAS FOGG ASTOUNDS PASSEPARTOUT, HIS SERVANT Having won twenty guineas at whist, and taken leave of his friends, Phileas Fogg, at twenty-five minutes past seven, left the Reform Club.",
            matched_text="twenty-five minutes past seven",
        )
        text, is_frag, status = cdq.best_display_quote(row)
        assert text.startswith("Having won twenty guineas")
        assert "CHAPTER IV" not in text
        assert "IN WHICH PHILEAS FOGG ASTOUNDS PASSEPARTOUT" not in text
        assert is_frag is False
        assert status == "complete_sentence"


class TestMainCLI:
    def test_writes_cleaned_rows(self, tmp_path, tmp_jsonl, monkeypatch, capsys):
        rows = [
            make_row(
                quote_text="It was three o'clock.",
                context_text="She arrived. It was three o'clock. Everyone cheered.",
                matched_text="three o'clock",
            ),
            make_row(
                quote_text="",
                context_text="",
                matched_text="noon",
            ),
        ]
        input_path = tmp_jsonl(rows)
        output_path = tmp_path / "cleaned.jsonl"
        monkeypatch.setattr(
            "sys.argv",
            ["clean_display_quotes.py", str(input_path), "--output", str(output_path)],
        )
        assert cdq.main() == 0
        written = [json.loads(line) for line in output_path.read_text().splitlines()]
        assert len(written) == 2
        assert written[0]["cleanup_status"] == "complete_sentence"
        assert written[0]["display_fragment"] is False
        assert written[1]["cleanup_status"] == "empty"
        assert written[1]["display_fragment"] is True
        out = capsys.readouterr().out
        assert "Wrote 2 cleaned" in out
        assert "Fragment fallbacks:" in out
