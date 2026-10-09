"""Tests of the retired ``mucha`` theme, moved verbatim from ``tests/test_render_quote.py``.

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


def test_mucha_border_paints_tip_blossoms():
    """The upleveled mucha border adds a five-petal tangerine blossom at each
    of the two existing vine tips (TL + BR), preserving the deliberate
    diagonal asymmetry (only the already-ornamented corners gain them)."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_mucha_border(img, rq.THEMES["mucha"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    yellow = rq.SPECTRA6["yellow"]

    def tangerine(cx, cy, r0=16):
        rr = sum(1 for x in range(cx - r0, cx + r0) for y in range(cy - r0, cy + r0) if px[x, y] == red)
        yy = sum(1 for x in range(cx - r0, cx + r0) for y in range(cy - r0, cy + r0) if px[x, y] == yellow)
        return rr, yy

    tl_r, tl_y = tangerine(78, 160)
    br_r, br_y = tangerine(760, 330)
    # Both tips carry a tangerine (R+Y) blossom: red AND yellow present.
    assert tl_r > 20 and tl_y > 20, "top-left vine-tip blossom missing"
    assert br_r > 10 and br_y > 20, "bottom-right vine-tip blossom missing"


# --- methods moved out of shared test classes (indented as in their class) ---
# From class TestThemes in tests/test_render_quote.py:
    def test_mucha_theme_uses_red_sentinel_for_synthesised_body(self):
        """Mucha is the only theme whose body fill is a synthesised
        colour (maroon — R+K 1:1) rather than a native ink. The
        ``text`` slot carries the red sentinel that ``_draw_text_body``
        routes through its R+K stipple branch; a regression that
        changed ``text`` to solid black or solid red would collapse
        the body into a flat single ink and lose the Art Nouveau
        oxblood register."""
        t = rq.THEMES["mucha"]
        assert t["page_bg"] == rq.SPECTRA6["white"]
        assert t["text"] == rq.SPECTRA6["red"]
        assert t["accent"] == rq.SPECTRA6["green"]
