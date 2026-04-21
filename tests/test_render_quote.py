"""Tests for render_quote.py — layout selection, text helpers, color quantization."""
from __future__ import annotations

import pytest

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not installed")

import render_quote as rq  # noqa: E402

# ---------------------------------------------------------------------------
# choose_layout
# ---------------------------------------------------------------------------

class TestChooseLayout:
    def test_short_text_is_hero(self):
        assert rq.choose_layout("Short quote.") == "hero"

    def test_exactly_90_chars_is_hero(self):
        assert rq.choose_layout("A" * 90) == "hero"

    def test_91_chars_is_standard(self):
        assert rq.choose_layout("A" * 91) == "standard"

    def test_exactly_170_chars_is_standard(self):
        assert rq.choose_layout("A" * 170) == "standard"

    def test_171_chars_is_dense(self):
        assert rq.choose_layout("A" * 171) == "dense"

    def test_empty_string_is_hero(self):
        assert rq.choose_layout("") == "hero"

    def test_none_handled(self):
        assert rq.choose_layout(None) == "hero"


# ---------------------------------------------------------------------------
# strip_underscore_emphasis
# ---------------------------------------------------------------------------

class TestStripUnderscoreEmphasis:
    def test_removes_single_word_emphasis(self):
        assert rq.strip_underscore_emphasis("my _Daily_ chronicle") == "my Daily chronicle"

    def test_removes_multi_word_emphasis(self):
        assert rq.strip_underscore_emphasis("my _Daily Chronicle_.") == "my Daily Chronicle."

    def test_passes_through_plain_text(self):
        assert rq.strip_underscore_emphasis("no markers here") == "no markers here"

    def test_handles_empty_and_none(self):
        assert rq.strip_underscore_emphasis("") == ""
        assert rq.strip_underscore_emphasis(None) == ""

    def test_preserves_intra_word_underscores(self):
        assert rq.strip_underscore_emphasis("var_name stays") == "var_name stays"


# ---------------------------------------------------------------------------
# normalize_dashes
# ---------------------------------------------------------------------------

class TestNormalizeDashes:
    def test_converts_double_dash_to_em_dash(self):
        assert rq.normalize_dashes("a shadowy furtiveness--and recognized") == "a shadowy furtiveness\u2014and recognized"

    def test_leaves_single_dash_alone(self):
        assert rq.normalize_dashes("well-known fact") == "well-known fact"

    def test_leaves_triple_dash_alone(self):
        assert rq.normalize_dashes("mystery of the---") == "mystery of the---"

    def test_passes_through_when_no_dashes(self):
        assert rq.normalize_dashes("plain text") == "plain text"

    def test_handles_empty_and_none(self):
        assert rq.normalize_dashes("") == ""
        assert rq.normalize_dashes(None) == ""


# ---------------------------------------------------------------------------
# resolve_display_match
# ---------------------------------------------------------------------------

class TestResolveDisplayMatch:
    def test_returns_original_when_no_expansion_found(self):
        text = "It was three o'clock in the hall."
        result = rq.resolve_display_match(text, "three o'clock")
        assert result == "three o'clock"

    def test_returns_direct_match_for_short_seed_when_present(self):
        text = "It was five minutes past three when she arrived."
        result = rq.resolve_display_match(text, "five")
        assert result.lower() == "five"

    def test_returns_direct_match_for_quarter_when_present(self):
        text = "Quarter past six the bell rang loudly."
        result = rq.resolve_display_match(text, "quarter")
        assert result.lower() == "quarter"

    def test_returns_direct_match_for_half_when_present(self):
        text = "Half past nine the carriage departed."
        result = rq.resolve_display_match(text, "half")
        assert result.lower() == "half"

    def test_returns_direct_match_when_full_seed_already_present(self):
        text = "It was ten minutes past five o'clock in the evening."
        result = rq.resolve_display_match(text, "ten minutes past")
        assert result.lower() == "ten minutes past"

    def test_does_not_switch_to_unrelated_longer_time_phrase(self):
        text = "It was a quarter past six when we left Baker Street, and it still wanted ten minutes to the hour when we found ourselves in Serpentine Avenue."
        result = rq.resolve_display_match(text, "quarter past six")
        assert result.lower() == "quarter past six"

    def test_empty_match_text(self):
        result = rq.resolve_display_match("Some text.", "")
        assert result == ""

    def test_match_text_with_newline_normalizes_for_lookup(self):
        text = "Do you think I should be standing here at five minutes to nine looking for it?"
        result = rq.resolve_display_match(text, "five\nminutes to nine")
        assert result.lower() == "five minutes to nine"

    def test_display_text_with_underscore_emphasis_still_matches_time_phrase(self):
        text = "I heard of it first about a quarter to nine when I went out to get my _Daily Chronicle_."
        result = rq.resolve_display_match(text, "quarter to nine")
        assert result.lower() == "quarter to nine"

    def test_em_dash_double_hyphen_is_valid_boundary(self):
        text = "Eleven--twelve--one o'clock had struck."
        result = rq.resolve_display_match(text, "one o'clock")
        assert result.lower() == "one o'clock"

    def test_compound_word_hyphen_still_blocks_substring_match(self):
        text = "Towards night-time the lady roused."
        # "night" on its own must not be picked up inside "night-time"
        assert rq.resolve_display_match(text, "Towards night") == "Towards night"
        tokens = rq.tokenize_quote(text, "Towards night")
        assert tokens == [(text, False)]


# ---------------------------------------------------------------------------
# tokenize_quote
# ---------------------------------------------------------------------------

class TestTokenizeQuote:
    def test_no_match_returns_single_plain_segment(self):
        tokens = rq.tokenize_quote("She arrived at noon.", "midnight")
        assert tokens == [("She arrived at noon.", False)]

    def test_match_at_start(self):
        tokens = rq.tokenize_quote("Three o'clock the bell rang.", "three o'clock")
        assert len(tokens) == 3
        assert tokens[0] == ("", False)
        bold_text = tokens[1][0]
        assert "three o'clock" in bold_text.lower()
        assert tokens[1][1] is True

    def test_match_in_middle(self):
        tokens = rq.tokenize_quote("It was three o'clock.", "three o'clock")
        assert len(tokens) == 3
        before, bold, after = tokens
        assert before[1] is False
        assert bold[1] is True
        assert after[1] is False

    def test_match_is_case_insensitive(self):
        tokens = rq.tokenize_quote("It was THREE O'CLOCK.", "three o'clock")
        bold_parts = [t for t in tokens if t[1]]
        assert len(bold_parts) == 1

    def test_prefers_actual_matched_phrase_when_multiple_time_phrases_exist(self):
        tokens = rq.tokenize_quote(
            "It was a quarter past six when we left Baker Street, and it still wanted ten minutes to the hour.",
            "quarter past six",
        )
        bold_parts = [t[0] for t in tokens if t[1]]
        assert bold_parts == ["quarter past six"]

    def test_newline_in_matched_text_does_not_break_highlight(self):
        tokens = rq.tokenize_quote(
            "Do you think I should be standing here at five minutes to nine looking for it if I had it in my pocket all the while?",
            "five\nminutes to nine",
        )
        bold_parts = [t[0] for t in tokens if t[1]]
        assert bold_parts == ["five minutes to nine"]


# ---------------------------------------------------------------------------
# snap_image_to_palette
# ---------------------------------------------------------------------------

class TestSnapImageToPalette:
    def _pixels(self, img):
        return list(img.convert("RGB").getdata())

    def test_pure_white_snaps_to_white(self):
        img = Image.new("RGB", (4, 4), color=(255, 255, 255))
        palette = [(255, 255, 255), (0, 0, 0)]
        result = rq.snap_image_to_palette(img, palette)
        assert all(p == (255, 255, 255) for p in self._pixels(result))

    def test_pure_black_snaps_to_black(self):
        img = Image.new("RGB", (4, 4), color=(0, 0, 0))
        palette = [(255, 255, 255), (0, 0, 0)]
        result = rq.snap_image_to_palette(img, palette)
        assert all(p == (0, 0, 0) for p in self._pixels(result))

    def test_near_red_snaps_to_red(self):
        img = Image.new("RGB", (2, 2), color=(240, 10, 10))
        palette = [(255, 255, 255), (0, 0, 0), (255, 0, 0)]
        result = rq.snap_image_to_palette(img, palette)
        assert all(p == (255, 0, 0) for p in self._pixels(result))

    def test_output_size_matches_input(self):
        img = Image.new("RGB", (10, 8), color=(128, 128, 128))
        palette = [(255, 255, 255), (0, 0, 0)]
        result = rq.snap_image_to_palette(img, palette)
        assert result.size == (10, 8)

    def test_all_spectra6_colors_round_trip(self):
        palette = list(rq.SPECTRA6.values())
        for color in palette:
            img = Image.new("RGB", (2, 2), color=color)
            result = rq.snap_image_to_palette(img, palette)
            assert all(p == color for p in self._pixels(result)), f"Color {color} did not round-trip"


# ---------------------------------------------------------------------------
# render — smoke test (no assertion on pixels, just that it completes)
# ---------------------------------------------------------------------------

class TestDebugQuoteId:
    def test_uses_source_id_when_present(self):
        assert rq.debug_quote_id({"source_id": "1661"}) == "1661"

    def test_uses_source_id_and_line_number_when_present(self):
        assert rq.debug_quote_id({"source_id": "1661", "line_number": 12345}) == "1661:L12345"

    def test_falls_back_to_source_stem(self):
        assert rq.debug_quote_id({"source_path": "data/gutenberg/pg1661.txt"}) == "pg1661"


class TestFallbackTitle:
    def test_prefers_project_gutenberg_label_for_source_id(self):
        assert rq.fallback_title({"source_id": "119"}) == "Project Gutenberg #119"

    def test_falls_back_to_source_stem_without_source_id(self):
        assert rq.fallback_title({"source_path": "data/gutenberg/pg1661.txt"}) == "pg1661"


class TestThemes:
    def test_dark_theme_palette_values(self):
        dark = rq.THEMES["dark"]
        assert dark["page_bg"] == rq.SPECTRA6["black"]
        assert dark["text"] == rq.SPECTRA6["white"]
        assert dark["accent"] == rq.SPECTRA6["yellow"]
        assert dark["ornament_dark"] == rq.SPECTRA6["black"]
        assert dark["ornament_light"] == rq.SPECTRA6["white"]


class TestRender:
    def _quote_row(self, text="It was three o'clock in the afternoon.", matched="three o'clock"):
        return {
            "display_quote": text,
            "matched_text": matched,
            "author": "Jane Austen",
            "title": "Mansfield Park",
            "bucket": "h3_exact",
            "resolved_bucket": "h3_exact",
            "used_fallback": False,
            "quality_score": 80,
            "source_id": "141",
        }

    def test_render_returns_image_of_correct_size(self):
        row = self._quote_row()
        img = rq.render("03:00", row, 800, 480, mode="debug")
        assert img.size == (800, 480)

    def test_render_production_mode(self):
        row = self._quote_row()
        img = rq.render("03:00", row, 800, 480, mode="production")
        assert img.size == (800, 480)

    def test_render_dark_theme(self):
        row = self._quote_row()
        img = rq.render("03:00", row, 800, 480, mode="production", theme="dark")
        assert img.size == (800, 480)

    def test_render_with_fallback_flag(self):
        row = self._quote_row()
        row["used_fallback"] = True
        row["resolved_bucket"] = "h3_just_after"
        img = rq.render("03:00", row, 800, 480, mode="debug")
        assert img.size == (800, 480)

    def test_render_short_quote_uses_hero_layout(self):
        row = self._quote_row(text="Three o'clock.", matched="Three o'clock")
        img = rq.render("03:00", row, 800, 480, mode="debug")
        assert img.size == (800, 480)

    def test_render_long_quote_uses_dense_layout(self):
        long_text = "A" * 180 + " three o'clock " + "B" * 40 + "."
        row = self._quote_row(text=long_text, matched="three o'clock")
        img = rq.render("03:00", row, 800, 480, mode="debug")
        assert img.size == (800, 480)

    def test_render_output_uses_spectra6_palette(self):
        row = self._quote_row()
        img = rq.render("03:00", row, 800, 480, mode="production")
        palette = set(rq.SPECTRA6.values())
        pixels = set(img.convert("RGB").getdata())
        assert pixels.issubset(palette), f"Unexpected colors: {pixels - palette}"

    def test_render_dark_theme_uses_black_background(self):
        row = self._quote_row()
        img = rq.render("03:00", row, 800, 480, mode="production", theme="dark")
        assert img.getpixel((0, 0)) == rq.SPECTRA6["black"]

    def test_render_without_metadata_does_not_need_source_path_attribution(self):
        row = self._quote_row()
        row["author"] = None
        row["title"] = None
        row["source_id"] = "119"
        row["source_path"] = "data/gutenberg/pg119.txt"
        img = rq.render("03:00", row, 800, 480, mode="production")
        assert img.size == (800, 480)

    def test_render_handles_newline_in_matched_text(self):
        row = self._quote_row(
            text="Do you think I should be standing here at five minutes to nine looking for it if I had it in my pocket all the while?",
            matched="five\nminutes to nine",
        )
        img = rq.render("08:55", row, 800, 480, mode="debug")
        assert img.size == (800, 480)

    def test_render_handles_gutenberg_underscore_emphasis_without_crashing(self):
        row = self._quote_row(
            text="I heard of it first from my newspaper boy about a quarter to nine when I went out to get my _Daily Chronicle_.",
            matched="quarter to nine",
        )
        img = rq.render("08:45", row, 800, 480, mode="debug")
        assert img.size == (800, 480)


class TestRenderCard:
    """The button-C source card uses mode='card' to render a centered metadata frame."""

    def _row(self, **overrides):
        row = {
            "display_quote": "It was three o'clock in the afternoon.",
            "matched_text": "three o'clock",
            "author": "Jane Austen",
            "title": "Mansfield Park",
            "source_id": "141",
        }
        row.update(overrides)
        return row

    def test_card_returns_image_of_correct_size(self):
        img = rq.render("03:00", self._row(), 800, 480, mode="card")
        assert img.size == (800, 480)

    def test_card_uses_dark_theme_background(self):
        img = rq.render("03:00", self._row(), 800, 480, mode="card", theme="dark")
        assert img.getpixel((0, 0)) == rq.SPECTRA6["black"]

    def test_card_uses_default_theme_background(self):
        img = rq.render("03:00", self._row(), 800, 480, mode="card", theme="default")
        assert img.getpixel((0, 0)) == rq.SPECTRA6["white"]

    def test_card_palette_is_spectra6(self):
        img = rq.render("03:00", self._row(), 800, 480, mode="card")
        palette = set(rq.SPECTRA6.values())
        pixels = set(img.convert("RGB").getdata())
        assert pixels.issubset(palette), f"Unexpected colors: {pixels - palette}"

    def test_card_without_author_or_title_falls_back_gracefully(self):
        row = self._row(author=None, title=None, source_path="data/gutenberg/pg141.txt")
        img = rq.render("03:00", row, 800, 480, mode="card")
        assert img.size == (800, 480)

    def test_card_without_source_id_does_not_crash(self):
        row = self._row(source_id=None)
        img = rq.render("03:00", row, 800, 480, mode="card")
        assert img.size == (800, 480)

    def test_card_strips_underscore_emphasis_from_matched_text(self):
        row = self._row(matched_text="_three o'clock_")
        img = rq.render("03:00", row, 800, 480, mode="card")
        assert img.size == (800, 480)


class TestMainAtomicSave:
    """``render_quote.main`` must never leave ``output/current.png`` truncated."""

    def _row(self):
        return {
            "display_quote": "It was three o'clock.",
            "matched_text": "three o'clock",
            "source_id": "141",
            "line_number": 482,
            "author": "A. Author",
            "title": "A Title",
            "quality_score": 90,
            "fuzzy_bucket": "h3_exact",
            "resolved_bucket": "h3_exact",
        }

    def test_successful_save_writes_valid_png(self, tmp_path, monkeypatch):
        """End-to-end: main() produces a file Pillow can re-open."""
        monkeypatch.setattr(rq, "pick_quote", lambda *args, **kwargs: self._row())
        output = tmp_path / "current.png"
        monkeypatch.setattr(
            "sys.argv",
            ["render_quote.py", "--time", "03:00", "--output", str(output)],
        )
        assert rq.main() == 0
        # Must be a readable PNG, not a truncated stub.
        with Image.open(output) as img:
            assert img.size == (800, 480)
        # No stray tmp sibling left behind.
        assert list(tmp_path.glob("*.tmp")) == []

    def test_save_failure_preserves_previous_output(self, tmp_path, monkeypatch):
        """A Pillow save failure must not truncate the existing current.png."""
        original_bytes = b"\x89PNG\r\n\x1a\nprior-valid-frame-bytes"
        output = tmp_path / "current.png"
        output.write_bytes(original_bytes)

        monkeypatch.setattr(rq, "pick_quote", lambda *args, **kwargs: self._row())

        # Make image.save raise mid-save by patching PIL.Image.Image.save.
        original_save = Image.Image.save

        def exploding_save(self, fp, format=None, **kwargs):  # noqa: A002
            raise OSError("simulated disk error mid-save")

        monkeypatch.setattr(Image.Image, "save", exploding_save)
        monkeypatch.setattr(
            "sys.argv",
            ["render_quote.py", "--time", "03:00", "--output", str(output)],
        )

        with pytest.raises(OSError):
            rq.main()

        # Crucially, the prior frame is intact; no truncation.
        assert output.read_bytes() == original_bytes
        assert list(tmp_path.glob("*.tmp")) == []

        # Restore so later tests aren't affected.
        monkeypatch.setattr(Image.Image, "save", original_save)
