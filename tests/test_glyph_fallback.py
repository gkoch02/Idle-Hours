"""Missing-glyph fallback: characters a theme's text faces lack become ASCII.

PIL falls back per font *file*, not per glyph, so a face without "…" draws its
``.notdef`` box. ``render`` rewrites such characters — and only those the
theme's body / matched-phrase faces actually lack — before layout.
"""

from __future__ import annotations

import pytest

from idle_hours import render_quote as rq
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
DOTS_ROW = _row("It was half past two... and the house was very still at last.", "half past two")


class TestFontHasGlyph:
    def test_iceland_lacks_ellipsis(self):
        font = _font("glacier")
        assert "Iceland" in font.path
        assert not rq.font_has_glyph(font, "…")

    def test_iceland_has_ordinary_characters(self):
        font = _font("glacier")
        for ch in "a.'’—":
            assert rq.font_has_glyph(font, ch), ch

    def test_playfair_has_ellipsis(self):
        font = _font("default")
        assert "Playfair" in font.path
        assert rq.font_has_glyph(font, "…")

    def test_result_is_size_independent_and_memoised(self):
        rq._GLYPH_PRESENT_CACHE.clear()
        small = rq.load_font(rq.theme_font_candidates("glacier", "quote_regular"), size=12)
        big = rq.load_font(rq.theme_font_candidates("glacier", "quote_regular"), size=48)
        assert rq.font_has_glyph(small, "…") is False
        assert len(rq._GLYPH_PRESENT_CACHE) == 1
        assert rq.font_has_glyph(big, "…") is False
        assert len(rq._GLYPH_PRESENT_CACHE) == 1


class TestApplyFallbacks:
    def test_unchanged_row_is_returned_as_is(self):
        # Playfair carries the glyph, so the row object itself comes back.
        assert rq.apply_theme_glyph_fallbacks(ELLIPSIS_ROW, "default") is ELLIPSIS_ROW

    def test_glacier_rewrites_ellipsis(self):
        out = rq.apply_theme_glyph_fallbacks(ELLIPSIS_ROW, "glacier")
        assert out["display_quote"] == DOTS_ROW["display_quote"]
        assert ELLIPSIS_ROW["display_quote"].endswith("at last.")  # input not mutated
        assert "…" in ELLIPSIS_ROW["display_quote"]

    def test_present_glyphs_are_left_alone(self):
        # Iceland has curly quotes and dashes: only the ellipsis is touched.
        row = _row("“Half past two…” she said — twice.", "Half past two")
        out = rq.apply_theme_glyph_fallbacks(row, "glacier")
        assert out["display_quote"] == "“Half past two...” she said — twice."

    def test_matched_text_substituted_consistently(self):
        row = _row("At half past two… exactly, he left.", "half past two…")
        out = rq.apply_theme_glyph_fallbacks(row, "glacier")
        assert out["matched_text"] == "half past two..."
        assert rq.resolve_display_match(out["display_quote"], out["matched_text"]) == "half past two..."
        segments = rq.tokenize_quote(out["display_quote"], out["matched_text"])
        assert ("half past two...", True) in segments

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
    monkeypatch.setattr(rq, "apply_theme_glyph_fallbacks", lambda row, theme: row)


class TestRender:
    def test_glacier_ellipsis_renders_as_three_dots(self):
        with_ellipsis = rq.render("02:30", ELLIPSIS_ROW, 800, 480, mode="production", theme="glacier")
        with_dots = rq.render("02:30", DOTS_ROW, 800, 480, mode="production", theme="glacier")
        assert pixel_bytes(with_ellipsis) == pixel_bytes(with_dots)

    def test_glacier_without_fix_draws_notdef(self, monkeypatch):
        fixed = rq.render("02:30", ELLIPSIS_ROW, 800, 480, mode="production", theme="glacier")
        _disable(monkeypatch)
        tofu = rq.render("02:30", ELLIPSIS_ROW, 800, 480, mode="production", theme="glacier")
        assert pixel_bytes(fixed) != pixel_bytes(tofu)

    @pytest.mark.parametrize("theme", ["default", "dark", "scholar", "questline"])
    def test_themes_with_the_glyph_are_unchanged(self, theme, monkeypatch):
        row = _row("The clock— at half past two… “yes”, it’s time.", "half past two")
        with_feature = rq.render("02:30", row, 800, 480, mode="production", theme=theme)
        _disable(monkeypatch)
        without = rq.render("02:30", row, 800, 480, mode="production", theme=theme)
        assert pixel_bytes(with_feature) == pixel_bytes(without)

    def test_matched_phrase_still_highlighted_after_substitution(self):
        row = _row("It was half past two… and all was still.", "half past two…")
        img = rq.render("02:30", row, 800, 480, mode="production", theme="glacier")
        plain = _row("It was half past two and all was still.", "zzz-no-match")
        img_plain = rq.render("02:30", plain, 800, 480, mode="production", theme="glacier")
        green = rq.SPECTRA6["green"]
        # glacier paints the matched phrase as a green+blue teal stipple; an
        # unmatched render has far less green (only the frost border).
        assert ink_counts(img).get(green, 0) > ink_counts(img_plain).get(green, 0) + 500
