"""Tests of the retired ``swiss`` theme, moved verbatim from ``tests/test_render_quote.py``. Not collected."""


# --- methods moved out of shared test classes (indented as in their class) ---
# From class TestThemes in tests/test_render_quote.py:
    def test_swiss_theme_uses_austere_monochrome_palette(self):
        """Swiss International is the rotation's modernist exception:
        white ground, black body, single red accent on the matched
        phrase and the small header square. No second chromatic ink
        anywhere — a regression that introduced a blue / yellow /
        green accent would collapse the theme into a generic poster
        composition and lose the "austerity by subtraction" identity."""
        t = rq.THEMES["swiss"]
        assert t["page_bg"] == rq.SPECTRA6["white"]
        assert t["text"] == rq.SPECTRA6["black"]
        assert t["accent"] == rq.SPECTRA6["red"]
        assert t["ornament_dark"] == rq.SPECTRA6["black"]
