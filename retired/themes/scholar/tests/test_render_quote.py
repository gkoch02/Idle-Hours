"""Tests of the retired ``scholar`` theme, moved verbatim from ``tests/test_render_quote.py``. Not collected."""


# --- methods moved out of shared test classes (indented as in their class) ---
# From class TestThemes in tests/test_render_quote.py:
    def test_scholar_theme_uses_blue_text(self):
        t = rq.THEMES["scholar"]
        assert t["text"] == rq.SPECTRA6["blue"]
        assert t["page_bg"] == rq.SPECTRA6["white"]
        assert t["accent"] == rq.SPECTRA6["red"]
