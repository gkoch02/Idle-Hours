"""Missing-glyph fallback: characters a theme's text faces lack become ASCII.

PIL falls back per font *file*, not per glyph, so a face without "“" draws its
``.notdef`` box. ``render`` rewrites such characters — and only those the
theme's body / matched-phrase faces actually lack — before layout.
"""

from __future__ import annotations

import pytest

from idle_hours import render_quote as rq
from idle_hours.render_quote import core as rq_core
from idle_hours.render_quote import theme_tables
from tests.pixel_helpers import ink_counts, pixel_bytes


def _font(theme: str, role: str = "quote_regular"):
    return rq.load_font(rq.theme_font_candidates(theme, role), size=32)


def _row(quote: str, matched: str, **extra) -> dict:
    row = {
        "display_quote": quote,
        "matched_text": matched,
        "author": "Test Author",
        "title": "A Test Title",
        "source_id": "1",
        "line_number": 1,
        "fuzzy_bucket": "h2_half_past",
        "quality_score": 90,
    }
    row.update(extra)
    return row


ELLIPSIS_ROW = _row("It was half past two… and the house was very still at last.", "half past two")
# Lumen (``gantry``, ``platform``) carries "…" but no curly quote or dash.
CURLY_ROW = _row("It was “half past two” — and the house was very still at last.", "half past two")
STRAIGHT_ROW = _row('It was "half past two" - and the house was very still at last.', "half past two")


class TestFontHasGlyph:
    def test_lumen_lacks_curly_quotes_and_dashes(self):
        font = _font("gantry")
        assert "Lumen" in font.path
        for ch in "“”‘’—–":
            assert not rq.font_has_glyph(font, ch), ch

    def test_lumen_has_ordinary_characters(self):
        font = _font("gantry")
        for ch in "a.'\"…":
            assert rq.font_has_glyph(font, ch), ch

    def test_playfair_has_ellipsis(self):
        font = _font("default")
        assert "Playfair" in font.path
        assert rq.font_has_glyph(font, "…")

    def test_result_is_size_independent_and_memoised(self):
        rq._GLYPH_PRESENT_CACHE.clear()
        small = rq.load_font(rq.theme_font_candidates("gantry", "quote_regular"), size=12)
        big = rq.load_font(rq.theme_font_candidates("gantry", "quote_regular"), size=48)
        assert rq.font_has_glyph(small, "“") is False
        assert len(rq._GLYPH_PRESENT_CACHE) == 1
        assert rq.font_has_glyph(big, "“") is False
        assert len(rq._GLYPH_PRESENT_CACHE) == 1


class TestApplyFallbacks:
    def test_unchanged_row_is_returned_as_is(self):
        # Playfair carries the glyph, so the row object itself comes back.
        assert rq.apply_theme_glyph_fallbacks(ELLIPSIS_ROW, "default") is ELLIPSIS_ROW

    def test_gantry_rewrites_curly_quotes_and_dashes(self):
        out = rq.apply_theme_glyph_fallbacks(CURLY_ROW, "gantry")
        assert out["display_quote"] == STRAIGHT_ROW["display_quote"]
        assert "“" in CURLY_ROW["display_quote"]  # input not mutated

    def test_present_glyphs_are_left_alone(self):
        # Lumen has the ellipsis: only the quotes are touched.
        row = _row("“Half past two…” she said.", "Half past two")
        out = rq.apply_theme_glyph_fallbacks(row, "gantry")
        assert out["display_quote"] == '"Half past two…" she said.'

    def test_matched_text_substituted_consistently(self):
        row = _row("By two o’clock exactly, he left.", "two o’clock")
        out = rq.apply_theme_glyph_fallbacks(row, "gantry")
        assert out["matched_text"] == "two o'clock"
        assert rq.resolve_display_match(out["display_quote"], out["matched_text"]) == "two o'clock"
        segments = rq.tokenize_quote(out["display_quote"], out["matched_text"])
        assert ("two o'clock", True) in segments

    def test_em_dash_fallback_spacing(self):
        missing = {"—"}
        assert rq._apply_glyph_fallbacks("a—b", missing) == "a - b"
        assert rq._apply_glyph_fallbacks("a — b", missing) == "a - b"
        # ``--`` would be turned back into an em dash by normalize_dashes, so
        # it is normalised first and then substituted too.
        assert rq._apply_glyph_fallbacks("a--b", missing) == "a - b"
        assert rq._apply_glyph_fallbacks("and then—", missing) == "and then-"

    @pytest.mark.parametrize("ch", sorted(rq.GLYPH_FALLBACKS))
    def test_fallbacks_are_ascii(self, ch):
        assert rq.GLYPH_FALLBACKS[ch].isascii()


def _disable(monkeypatch):
    monkeypatch.setattr(rq_core, "apply_theme_glyph_fallbacks", lambda row, theme: row)


@pytest.fixture
def lumen_default(monkeypatch):
    """Set ``default``'s text faces to Lumen, so the standard layout meets a
    face without curly quotes or dashes (``gantry`` and ``platform`` draw
    their own frames and map those characters themselves)."""
    lumen = [(rq.LUMEN_VARIABLE, "Bold")]
    monkeypatch.setitem(theme_tables.THEME_FONTS, "default",
                        {**theme_tables.THEME_FONTS["default"], "quote_regular": lumen, "quote_bold": lumen})


class TestRender:
    def test_curly_quotes_render_as_straight_ones(self, lumen_default):
        with_curly = rq.render("02:30", CURLY_ROW, 800, 480, mode="production", theme="default")
        with_straight = rq.render("02:30", STRAIGHT_ROW, 800, 480, mode="production", theme="default")
        assert pixel_bytes(with_curly) == pixel_bytes(with_straight)

    def test_without_fix_draws_notdef(self, lumen_default, monkeypatch):
        fixed = rq.render("02:30", CURLY_ROW, 800, 480, mode="production", theme="default")
        _disable(monkeypatch)
        tofu = rq.render("02:30", CURLY_ROW, 800, 480, mode="production", theme="default")
        assert pixel_bytes(fixed) != pixel_bytes(tofu)

    @pytest.mark.parametrize("theme", ["default", "dark", "roman", "questline"])
    def test_themes_with_the_glyph_are_unchanged(self, theme, monkeypatch):
        row = _row("The clock— at half past two… “yes”, it’s time.", "half past two")
        with_feature = rq.render("02:30", row, 800, 480, mode="production", theme=theme)
        _disable(monkeypatch)
        without = rq.render("02:30", row, 800, 480, mode="production", theme=theme)
        assert pixel_bytes(with_feature) == pixel_bytes(without)

    def test_matched_phrase_still_highlighted_after_substitution(self, lumen_default):
        row = _row("It was two o’clock and all was still.", "two o’clock")
        img = rq.render("02:30", row, 800, 480, mode="production", theme="default")
        plain = _row("It was two o'clock and all was still.", "zzz-no-match")
        img_plain = rq.render("02:30", plain, 800, 480, mode="production", theme="default")
        red = rq.SPECTRA6["red"]
        # ``default`` paints the matched phrase red; an unmatched render has
        # red only in its quote marks.
        assert ink_counts(img).get(red, 0) > ink_counts(img_plain).get(red, 0) + 200
