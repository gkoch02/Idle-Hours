"""Tests of the retired ``herbarium`` theme, moved verbatim from ``tests/test_render_quote.py``.

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


def test_herbarium_border_paints_second_fern_specimen():
    """The upleveled herbarium border mounts a second pressed-fern specimen
    in the top-left margin (olive = green/yellow stipple)."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_herbarium_border(img, rq.THEMES["herbarium"])
    px = img.load()
    green = rq.SPECTRA6["green"]
    yellow = rq.SPECTRA6["yellow"]
    fern = {px[x, y] for x in range(42, 67) for y in range(34, 109)}
    assert green in fern and yellow in fern, "TL fern specimen olive stipple missing"


def test_herbarium_border_paints_leaf_mounting_tape():
    """Off-white gummed mounting-tape strips pin the main BR leaf's midrib."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_herbarium_border(img, rq.THEMES["herbarium"])
    px = img.load()
    white = rq.SPECTRA6["white"]
    leaf_cx = 800 - 1 - 38 - 84 // 2
    leaf_cy = 480 - 1 - 38 - 42 // 2
    assert px[leaf_cx, leaf_cy - 18] == white
    assert px[leaf_cx, leaf_cy + 16] == white


# --- methods moved out of shared test classes (indented as in their class) ---
# From class TestThemes in tests/test_render_quote.py:
    def test_herbarium_theme_routes_matched_phrase_to_forest_green(self):
        """Herbarium uses the green sentinel ink in the ``accent`` slot
        so ``_draw_text_body`` can route the matched phrase through a
        G+K → forest-green stipple. Pinning the sentinel slot here
        catches a regression that drops the matched phrase back to
        solid black (eliminating the green colour story that
        defines the theme on the green axis)."""
        t = rq.THEMES["herbarium"]
        assert t["page_bg"] == rq.SPECTRA6["white"]
        assert t["text"] == rq.SPECTRA6["black"]
        assert t["accent"] == rq.SPECTRA6["green"]
