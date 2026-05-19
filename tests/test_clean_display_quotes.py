"""Tests for clean_display_quotes.py — sentence extraction and fragment detection."""
from __future__ import annotations

import json

from idle_hours import clean_display_quotes as cdq
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

    def test_does_not_split_at_mr_abbreviation(self):
        parts = cdq.split_sentences("She went to see Mr. Smith. He was kind.")
        assert parts == ["She went to see Mr. Smith.", "He was kind."]

    def test_does_not_split_at_mrs_abbreviation(self):
        parts = cdq.split_sentences(
            "We left Mrs. Jones at the station. The train departed at noon."
        )
        assert parts == ["We left Mrs. Jones at the station.", "The train departed at noon."]

    def test_does_not_split_at_dr_abbreviation(self):
        parts = cdq.split_sentences("Dr. Watson arrived at two.")
        assert parts == ["Dr. Watson arrived at two."]

    def test_does_not_split_at_st_abbreviation(self):
        parts = cdq.split_sentences("They met at St. James's Park. It was noon.")
        assert parts == ["They met at St. James's Park.", "It was noon."]

    def test_does_not_split_at_single_letter_initials(self):
        # "J. R. R. Tolkien" must stay whole instead of splitting into four.
        parts = cdq.split_sentences("J. R. R. Tolkien wrote novels.")
        assert parts == ["J. R. R. Tolkien wrote novels."]

    def test_trailing_abbreviation_at_true_sentence_end_is_kept(self):
        # If the abbreviation is genuinely at the end (no following sentence),
        # we just return the single part — no merge required.
        parts = cdq.split_sentences("I wrote to Mr.")
        assert parts == ["I wrote to Mr."]

    def test_does_not_split_at_am_pm_abbreviation(self):
        parts = cdq.split_sentences("I left at four P.M. and arrived at six. It was dark.")
        assert parts == ["I left at four P.M. and arrived at six.", "It was dark."]

    def test_does_not_split_at_lowercase_am_pm(self):
        parts = cdq.split_sentences("Meeting at 3 p.m. tomorrow. Be there.")
        assert parts == ["Meeting at 3 p.m. tomorrow.", "Be there."]

    def test_does_not_split_at_multidot_acronym(self):
        parts = cdq.split_sentences("U.S.A. is here. Hello.")
        assert parts == ["U.S.A. is here.", "Hello."]

    def test_preserves_true_boundary_after_etc(self):
        # Review finding (P2): an unconditional merge after every abbreviation
        # also glues real sentence boundaries. "etc." legitimately ends a
        # sentence, so when the next fragment starts with an uppercase letter
        # we must keep the split.
        parts = cdq.split_sentences("We had tea, cakes, etc. Then we left.")
        assert parts == ["We had tea, cakes, etc.", "Then we left."]

    def test_preserves_true_boundary_after_viz(self):
        parts = cdq.split_sentences(
            "The plans were made clear, viz. The first was shelved."
        )
        assert parts == [
            "The plans were made clear, viz.",
            "The first was shelved.",
        ]

    def test_preserves_true_boundary_after_pm_uppercase(self):
        # "I left at four p.m. Then ..." — lowercase p.m. ends a real sentence
        # here (uppercase "Then" signals a new sentence). Don't merge.
        parts = cdq.split_sentences("I left at four p.m. Then I walked home.")
        assert parts == ["I left at four p.m.", "Then I walked home."]


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

    def test_ends_at_title_abbreviation_is_fragment(self):
        # A sentence that terminates at "Mr." / "Mrs." / "Dr." is almost
        # always the miner's context window cut short — the real sentence
        # continues with a proper name. Flag as a fragment so quality_filter
        # penalises it.
        assert cdq.looks_fragment("At three o'clock that afternoon, Mr.") is True
        assert cdq.looks_fragment("She wrote to her friend Mrs.") is True
        assert cdq.looks_fragment("He went to visit Dr.") is True

    def test_ends_at_sentence_ok_abbreviation_is_not_fragment(self):
        # Review finding (P1): "p.m." / "etc." / "U.S.A." can legitimately end
        # a real sentence, so `looks_fragment` must NOT flag them. A display
        # quote that genuinely terminates with one of these is complete and
        # should not be penalised in the quality filter.
        assert cdq.looks_fragment("The meeting starts at three in the afternoon, p.m.") is False
        assert cdq.looks_fragment("Please remember to bring the tent, stove, matches, etc.") is False
        assert cdq.looks_fragment("He had travelled widely across the U.S.A.") is False


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
        # The chosen text must contain the matched phrase and be a non-fragment
        # (either a single complete sentence or an expanded multi-sentence run).
        assert status in {"complete_sentence", "expanded_with_context"}
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
        assert status in {"complete_sentence", "expanded_with_context"}
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


class TestExpandCandidates:
    def test_returns_single_hit_and_neighbour_runs(self):
        text = "She arrived. It was three o'clock. Everyone cheered."
        runs, singles = cdq.expand_candidates(text, "three o'clock")
        # The hit sentence itself must appear as a single-hit candidate.
        assert "It was three o'clock." in singles
        # Multi-sentence runs joining it with its neighbours must be present.
        assert "She arrived. It was three o'clock." in runs
        assert "It was three o'clock. Everyone cheered." in runs
        assert "She arrived. It was three o'clock. Everyone cheered." in runs

    def test_no_match_returns_empty(self):
        runs, singles = cdq.expand_candidates("No match here at all.", "three o'clock")
        assert runs == []
        assert singles == set()

    def test_empty_needle_returns_empty(self):
        runs, singles = cdq.expand_candidates("Some prose. More prose.", "")
        assert runs == []
        assert singles == set()

    def test_caps_runs_at_max_chars(self):
        long_filler = (
            " ".join(["This is a long padding sentence that exists only to stretch the total length."] * 5)
        )
        text = f"{long_filler} It was three o'clock. {long_filler}"
        runs, _ = cdq.expand_candidates(text, "three o'clock")
        # No run produced may exceed the documented 260-char cap.
        for run in runs:
            assert len(run) <= cdq.EXPANSION_MAX_CHARS


class TestExpandedStatusStamping:
    def _row(self, quote_text="", context_text="", matched_text="three o'clock"):
        return {"quote_text": quote_text, "context_text": context_text, "matched_text": matched_text}

    def test_short_hit_expands_to_neighbouring_sentences(self):
        # A bare time-utterance sandwiched between two richer complete sentences
        # should yield a multi-sentence run as the winner (closer to 140 chars).
        context = (
            "The fire burned low and the hour grew late in the little cottage. "
            "It was three o'clock. "
            "Outside, a thin rain drummed against the shutters of the cottage."
        )
        row = self._row(quote_text="It was three o'clock.", context_text=context)
        text, is_frag, status = cdq.best_display_quote(row)
        assert is_frag is False
        assert status == "expanded_with_context"
        # Must include the hit and at least one neighbouring sentence.
        assert "three o'clock" in text
        assert "fire burned low" in text or "thin rain drummed" in text

    def test_standalone_complete_sentence_stays_complete(self):
        # When no neighbours are available, a single complete sentence should
        # still be stamped "complete_sentence", not "expanded_with_context".
        row = self._row(
            quote_text="It was three o'clock in the afternoon of a long and weary day in the hills.",
            context_text="It was three o'clock in the afternoon of a long and weary day in the hills.",
        )
        _, _, status = cdq.best_display_quote(row)
        assert status == "complete_sentence"

    def test_empty_matched_text_stamps_complete_when_blob_is_single_sentence(self):
        # Regression guard: before the single-sentence-blob fallback, an empty
        # matched_text plus a clean one-sentence quote_text got stamped
        # "expanded_with_context" because the blob bypassed the expand path.
        row = self._row(
            quote_text="It was a cold and moonless night on the edge of the western hills.",
            context_text="",
            matched_text="",
        )
        _, is_frag, status = cdq.best_display_quote(row)
        assert is_frag is False
        assert status == "complete_sentence"

    def test_interior_chapter_heading_is_avoided_when_alternative_exists(self):
        # Row where context_text has a clean single-sentence hit but quote_text
        # bleeds a Title-Case chapter marker mid-run. The heading-free candidate
        # must win.
        row = self._row(
            quote_text="Lord, it's one o'clock. Chapter XI Titania Tries Reading in Bed.",
            context_text="He yawned and looked at the clock on the mantel. Lord, it's one o'clock. The fire had burned low and the room was cold.",
            matched_text="one o'clock",
        )
        text, _, _ = cdq.best_display_quote(row)
        assert "Chapter XI" not in text
        assert "one o'clock" in text

    def test_interior_heading_filter_falls_back_when_only_heading_candidates(self):
        # Sparse-bucket safety: if every non-fragment candidate contains an
        # interior heading, we still return something (rather than punting to
        # fragment_fallback) so the panel renders a line. Uses a mid-sentence
        # heading that clean_edges cannot strip (it only strips prefixes), so
        # the filter genuinely has no clean candidate to choose from.
        only_sentence = "When I heard that CHAPTER 5 was coming, at three o'clock sharp, I felt ready."
        row = self._row(
            quote_text=only_sentence,
            context_text=only_sentence,
            matched_text="three o'clock",
        )
        text, is_frag, _ = cdq.best_display_quote(row)
        assert is_frag is False
        assert "three o'clock" in text
        # Fell back to the unfiltered pool — the heading is still there.
        assert "CHAPTER 5" in text

    def test_expansion_preserves_opening_quotes_on_interior_dialogue(self):
        # Regression guard for the P2 review finding: clean_edges' LEADING_JUNK
        # strips leading "/' characters, so naïvely applying it per-sentence
        # destroys opening quotes on interior dialogue when sentences are
        # joined into a run, producing orphan close-quotes like
        # 'He paused. All is ready," she replied.' instead of
        # 'He paused. "All is ready," she replied.'.
        quote_text = (
            'He paused at the door, listening for voices on the stair. '
            '"The carriage leaves at three o’clock," she replied firmly. '
            'Outside the wind rattled the shutters of the old house.'
        )
        row = self._row(quote_text=quote_text, context_text="", matched_text="three o’clock")
        text, _, _ = cdq.best_display_quote(row)
        # If the interior dialogue sentence ended up in the run, its opening
        # quote must still be present.
        if "The carriage leaves at three" in text:
            assert '"The carriage leaves' in text, (
                f"opening quote missing before dialogue: {text!r}"
            )

    def test_picks_run_closest_to_140_over_shorter_and_longer_alternatives(self):
        # Dedicated proximity test: a ~137-char hit sentence must win over a
        # shorter single-sentence sibling and a much-longer joined blob.
        short_sibling = "The door creaked."  # 17 chars
        hit = (
            "It was three o'clock when the long-awaited letter from her family in "
            "a distant city finally arrived at the old country house that evening."
        )  # 139 chars — closest to 140
        filler = (
            "She had waited for it all her life and the postman had come at last "
            "with the envelope clutched tightly in his gloved hand and a wide grin."
        )  # pushes any joined blob comfortably past 260
        assert 130 <= len(hit) <= 150
        row = self._row(
            quote_text=f"{short_sibling} {hit} {filler}",
            context_text="",
        )
        text, _, status = cdq.best_display_quote(row)
        # Winner must be the 140-close hit sentence alone — not the short
        # sibling, not a joined run, not the full blob.
        assert text == hit
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
        assert written[0]["cleanup_status"] in {"complete_sentence", "expanded_with_context"}
        assert written[0]["display_fragment"] is False
        assert written[1]["cleanup_status"] == "empty"
        assert written[1]["display_fragment"] is True
        out = capsys.readouterr().out
        assert "Wrote 2 cleaned" in out
        assert "Fragment fallbacks:" in out
