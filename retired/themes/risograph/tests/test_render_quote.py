"""Tests of the retired ``risograph`` theme, moved verbatim from ``tests/test_render_quote.py``.

Not collected (pytest only collects ``tests/``); restore them with the theme.
"""
# Original module header, kept so the tests read as they did:
"""Tests for render_quote.py — layout selection, text helpers, color quantization."""
from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from unittest.mock import patch

import pytest

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not installed")

from idle_hours import render_quote as rq  # noqa: E402
from idle_hours.render_quote import core as rq_core  # noqa: E402
from idle_hours.render_quote import fonts as rq_fonts  # noqa: E402
from idle_hours.render_quote import palette as rq_palette  # noqa: E402
from idle_hours.render_quote import text as rq_text  # noqa: E402

from .pixel_helpers import distinct_inks, ink_counts  # noqa: E402


@pytest.fixture(autouse=True)


def test_risograph_border_paints_registration_colour_bar():
    """The upleveled risograph border adds a top-centre colour-registration
    bar of red / blue / lavender-overprint / red / blue swatches — no black
    ink (the riso theme's invariant)."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_risograph_border(img, rq.THEMES["risograph"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    blue = rq.SPECTRA6["blue"]
    bar_red = sum(1 for x in range(337, 360) for y in range(24, 33) if px[x, y] == red)
    bar_blue = sum(1 for x in range(363, 386) for y in range(24, 33) if px[x, y] == blue)
    assert bar_red > 100, "registration-bar red swatch missing"
    assert bar_blue > 100, "registration-bar blue swatch missing"
    # The bar must clear y=22, the coordinate the illuminated cross-gating
    # test samples to prove no other theme paints centre-top there.
    assert px[400, 22] == (255, 255, 255), "registration bar must clear y=22"


def test_risograph_registration_bar_lavender_swatch_is_red_and_blue():
    """The middle overprint swatch is the R+B+W lavender 3-way recipe, so it
    carries both red and blue pixels (and no black, per the riso invariant)."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_risograph_border(img, rq.THEMES["risograph"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    blue = rq.SPECTRA6["blue"]
    black = rq.SPECTRA6["black"]
    lav_x0 = 337 + 2 * 26
    region = [px[x, y] for x in range(lav_x0, lav_x0 + 23) for y in range(24, 33)]
    assert region.count(red) > 30, "lavender swatch red component missing"
    assert region.count(blue) > 30, "lavender swatch blue component missing"
    assert black not in region, "lavender swatch must not introduce black ink"


class TestRisographKnockout:
    def test_clear_rect_is_knocked_back_to_paper_and_framed(self):
        img = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        colors = rq.THEMES["risograph"]
        rect = (60, 80, 740, 400)
        rq.draw_risograph_border(img, colors, clear_rect=rect)
        # Inside the pad (past both the red rule and the offset blue rule)
        # the paper is clean white.
        for x in range(rect[0] + 10, rect[2] - 10, 23):
            for y in range(rect[1] + 10, rect[3] - 10, 17):
                assert img.getpixel((x, y)) == rq.SPECTRA6["white"], (x, y)
        # The two misregistered rules are present in the theme's inks.
        assert img.getpixel((rect[0], (rect[1] + rect[3]) // 2)) == colors["text"]
        assert img.getpixel((rect[0] + 5, (rect[1] + rect[3]) // 2)) == colors["accent"]

    def test_render_threads_the_clear_rect(self):
        row = {
            "display_quote": "But I must consider. Come to me to-morrow at the office, at nine o\u2019clock.",
            "matched_text": "nine o\u2019clock",
            "author": "George Eliot",
            "title": "Middlemarch",
        }
        img = rq.render("09:00", row, 800, 480, mode="production", theme="risograph")
        # The chunky left bar (x 42-74, y 54-170) used to run solid under
        # the first word. Inside the label its box is now paper, apart from
        # the hanging quote mark's 50/50 blue stipple that deliberately
        # overlaps it -- so well under half the box may be blue, where the
        # bare border paints all of it.
        blue = rq.SPECTRA6["blue"]
        box = [(x, y) for x in range(62, 73) for y in range(120, 166)]
        assert sum(img.getpixel(p) == blue for p in box) / len(box) < 0.5


# --- methods moved out of shared test classes (indented as in their class) ---
# From class TestThemes in tests/test_render_quote.py:
    def test_risograph_theme_uses_no_black_ink(self):
        """The defining constraint of the risograph aesthetic is
        two-colour printing with NO black plate. Pin "no black anywhere"
        as an explicit invariant so a well-meaning refactor (e.g. making
        the source credit more legible by darkening it) doesn't silently
        re-introduce black and collapse the theme into a tinted
        ``default``."""
        t = rq.THEMES["risograph"]
        assert t["page_bg"] == rq.SPECTRA6["white"]
        assert t["text"] == rq.SPECTRA6["red"]
        assert t["accent"] == rq.SPECTRA6["blue"]
        # Every colour field must avoid black — this is the theme's
        # whole point.
        for field, value in t.items():
            assert value != rq.SPECTRA6["black"], f"risograph.{field} is black"

# From class TestKnockoutCoversByline in tests/test_render_quote.py:
    def test_long_title_stays_inside_the_risograph_label(self):
        """A short quote with a long title: the label's right edge used to
        follow the quote lines alone, so the byline ran out of the panel
        into the lower-right print bar (Codex review on #328)."""
        row = {
            "display_quote": "The clock struck nine as he came in.",
            "matched_text": "struck nine",
            "author": "Christopher Morley",
            "title": "The Haunted Bookshop, Being a Further Account of Roger Mifflin and His Parnassus at Home",
        }
        img = rq.render("09:00", row, 800, 480, mode="production", theme="risograph")
        red = rq.SPECTRA6["red"]
        # The title paints red on paper; follow its row and check that every
        # red pixel at the far right of the byline band is text-sized ink on
        # white neighbours, not the solid print bar (x 712-744).
        bar_columns = range(714, 742)
        solid_rows = 0
        for y in range(296, 412):
            if all(img.getpixel((x, y)) == red for x in bar_columns):
                solid_rows += 1
        # The bar is 116 rows tall when untouched; the knockout must have
        # removed the rows the byline band overlaps.
        assert solid_rows < 116
