"""Tests of the retired ``illuminated`` theme, moved verbatim from ``tests/test_render_quote.py``.

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


class TestIlluminatedBorder:
    """The illuminated theme paints a manuscript-style border.

    Double rubricated (red) rule — outer and inner concentric rectangles
    — plus a small blue "jewel" (filled circle) centred on each outer
    corner, evoking the lapis cabochons inset into medieval
    illuminated pages. Regression tests here pin the painted pixels,
    complementing the golden-image suite.
    """

    def _row(self):
        return {
            "display_quote": "It was three o'clock in the afternoon.",
            "matched_text": "three o'clock",
            "author": "Jane Austen",
            "title": "Mansfield Park",
            "bucket": "h3_exact",
            "resolved_bucket": "h3_exact",
            "used_fallback": False,
            "quality_score": 80,
            "source_id": "141",
        }

    def test_illuminated_double_rule_paints_both_rules_in_body_red(self):
        """Outer rule at y=14, inner rule at y=22, page_bg gap between."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="illuminated")
        assert img.getpixel((400, 14)) == rq.SPECTRA6["red"], "outer rule missing"
        assert img.getpixel((400, 22)) == rq.SPECTRA6["red"], "inner rule missing"
        # White gap between the two — the defining "doubled" effect.
        assert img.getpixel((400, 18)) == rq.SPECTRA6["white"], "rules merged into single band"

    def test_illuminated_corner_jewels_paint_plum_three_way_bayer(self):
        """Plum cabochons at the four outer-rule corners — radius 5
        filled circles painted in a sentinel ink and then bbox-post-
        passed through a 3-way 4×4 Bayer partition (cells 0-4 → red,
        cells 5-9 → blue, cells 10-15 → black; ~1/3 each, the
        documented R+B+K plum recipe). Pin the centre pixel of each
        jewel against the deterministic Bayer assignment so a
        regression that dropped the post-pass would surface; the
        centre's exact ink depends on the `BAYER_4x4[y%4][x%4]` value
        at that coordinate.

        Centre pixels:
          (14, 14)   → BAYER[2][2]=1  → red
          (785, 14)  → BAYER[2][1]=11 → black
          (14, 465)  → BAYER[1][2]=14 → black
          (785, 465) → BAYER[1][1]=4  → red

        At least one corner-region sample lands on a cell in the blue
        partition (cells 5-9) — verify the post-pass painted blue
        somewhere too so all three plum inks are present."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="illuminated")
        assert img.getpixel((14, 14)) == rq.SPECTRA6["red"], "TL jewel centre missing"
        assert img.getpixel((785, 14)) == rq.SPECTRA6["black"], "TR jewel centre missing"
        assert img.getpixel((14, 465)) == rq.SPECTRA6["black"], "BL jewel centre missing"
        assert img.getpixel((785, 465)) == rq.SPECTRA6["red"], "BR jewel centre missing"
        # Probe the TL jewel's bbox for at least one painted blue pixel
        # to confirm the 3-way partition's blue arm fires.
        found_blue = False
        for py in range(9, 20):
            for px in range(9, 20):
                if img.getpixel((px, py)) == rq.SPECTRA6["blue"]:
                    found_blue = True
                    break
            if found_blue:
                break
        assert found_blue, "TL jewel bbox produced no blue pixels — 3-way Bayer regressed"

    def test_illuminated_border_paints_all_four_sides(self):
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="illuminated")
        # Outer rule, mid-side samples (away from the jewels).
        assert img.getpixel((400, 14)) == rq.SPECTRA6["red"], "top outer rule missing"
        assert img.getpixel((400, 465)) == rq.SPECTRA6["red"], "bottom outer rule missing"
        assert img.getpixel((14, 240)) == rq.SPECTRA6["red"], "left outer rule missing"
        assert img.getpixel((785, 240)) == rq.SPECTRA6["red"], "right outer rule missing"

    def test_illuminated_border_is_theme_gated(self):
        """Sample (400, 22) — inner rule pixel — which is unique to
        illuminated; no other border theme places a rule at inset 22."""
        for theme in ("default", "dark", "scholar", "newsprint", "nightvision",
                      "blueprint", "bauhaus", "risograph", "comic"):
            img = rq.render("03:00", self._row(), 800, 480, mode="production", theme=theme)
            expected_bg = rq.THEMES[theme]["page_bg"]
            assert img.getpixel((400, 22)) == expected_bg, (
                f"theme {theme} painted at inner-rule y=22; expected page_bg={expected_bg}"
            )

    def test_illuminated_border_appears_in_debug_and_card_modes_too(self):
        for mode in ("production", "debug", "card"):
            img = rq.render("03:00", self._row(), 800, 480, mode=mode, theme="illuminated")
            # (14, 14) lands on the TL jewel's centre — with the 3-way
            # plum post-pass the centre is the red arm of the partition
            # at this coordinate (BAYER[2][2]=1 < 5). Different from
            # both the body's rubricated red text (which doesn't reach
            # this corner) and the canvas page_bg, so a regression that
            # dropped the border in any render mode would still fail
            # here.
            assert img.getpixel((14, 14)) == rq.SPECTRA6["red"], f"illuminated mode={mode} missing TL jewel"

    def test_illuminated_border_uses_theme_colours_not_hardcoded_rgb(self):
        image = Image.new("RGB", (800, 480), color=(255, 255, 255))
        custom = {"text": rq.SPECTRA6["green"], "accent": rq.SPECTRA6["yellow"]}
        rq.draw_illuminated_border(image, custom)
        assert image.getpixel((14, 14)) == rq.SPECTRA6["yellow"], "jewel should use accent"
        assert image.getpixel((400, 14)) == rq.SPECTRA6["green"], "outer rule should use text"
        assert image.getpixel((400, 22)) == rq.SPECTRA6["green"], "inner rule should use text"


def test_illuminated_border_paints_head_asterism():
    """The upleveled illuminated border adds a rubricated head asterism
    (red lozenges) centred in the top margin."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_illuminated_border(img, rq.THEMES["illuminated"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    head_red = sum(1 for x in range(385, 416) for y in range(33, 52) if px[x, y] == red)
    assert head_red > 40, "head asterism lozenges missing"


def test_illuminated_border_paints_foot_line_filler():
    """The upleveled illuminated border adds a foot line-filler — a red
    rule + central red lozenge flanked by blue lozenges."""
    img = Image.new("RGB", (800, 480), (255, 255, 255))
    rq.draw_illuminated_border(img, rq.THEMES["illuminated"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    blue = rq.SPECTRA6["blue"]
    foot_red = sum(1 for x in range(355, 446) for y in range(445, 458) if px[x, y] == red)
    foot_blue = sum(1 for x in range(345, 456) for y in range(445, 458) if px[x, y] == blue)
    assert foot_red > 40, "foot line-filler rule / centre lozenge missing"
    assert foot_blue > 10, "foot line-filler flanking blue lozenges missing"


# --- methods moved out of shared test classes (indented as in their class) ---
# From class TestThemes in tests/test_render_quote.py:
    def test_illuminated_theme_uses_rubricated_red_body(self):
        """Red body text is unique to ``illuminated`` across the rotation;
        a regression that flipped ``text`` to black would collapse the
        theme into a slightly-fancier ``default`` and lose the whole
        manuscript motif."""
        t = rq.THEMES["illuminated"]
        assert t["page_bg"] == rq.SPECTRA6["white"]
        assert t["text"] == rq.SPECTRA6["red"]
        assert t["accent"] == rq.SPECTRA6["blue"]
