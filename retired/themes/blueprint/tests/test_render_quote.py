"""Tests of the retired ``blueprint`` theme, moved verbatim from ``tests/test_render_quote.py``.

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


class TestBlueprintBorder:
    """The blueprint theme paints a cyanotype drafting sheet.

    Parallels ``TestBauhausBorder`` but locks the blueprint-specific
    primitives: 50/50 white-on-blue dithered ground, thin white outer
    frame, and white crosshair registration marks at each corner. A
    regression that dropped ``draw_blueprint_border`` would pass every
    dict-level palette test silently, so pin the painted pixels here.
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

    def test_blueprint_corner_crosshairs_paint_accent_red(self):
        """Four crosshair "+" marks centred on the frame corners at
        ``(16, 16)`` / ``(783, 16)`` / ``(16, 463)`` / ``(783, 463)``.
        The centre pixel is always on the mark; arm extents are ±8.
        Crosshairs paint in the accent colour (red) so they pop
        against the white body / grid ink, matching the matched
        time phrase highlight."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="blueprint")
        assert img.getpixel((16, 16)) == rq.SPECTRA6["red"], "TL crosshair centre missing"
        assert img.getpixel((783, 16)) == rq.SPECTRA6["red"], "TR crosshair centre missing"
        assert img.getpixel((16, 463)) == rq.SPECTRA6["red"], "BL crosshair centre missing"
        assert img.getpixel((783, 463)) == rq.SPECTRA6["red"], "BR crosshair centre missing"

    def test_blueprint_crosshair_arms_extend_both_directions(self):
        """Each crosshair has four 8px arms (left/right/up/down from
        centre). A regression that drew a single dot instead of a "+"
        would pass the centre-pixel test but fail here."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="blueprint")
        cx, cy = 16, 16
        assert img.getpixel((cx - 6, cy)) == rq.SPECTRA6["red"], "TL left arm missing"
        assert img.getpixel((cx + 6, cy)) == rq.SPECTRA6["red"], "TL right arm missing"
        assert img.getpixel((cx, cy - 6)) == rq.SPECTRA6["red"], "TL up arm missing"
        assert img.getpixel((cx, cy + 6)) == rq.SPECTRA6["red"], "TL down arm missing"

    def test_blueprint_outer_frame_is_painted_in_body_white(self):
        """The outer rectangle outline is the structural anchor for the
        crosshairs. Sample a point on each side well clear of the
        corners, to verify all four sides of the frame rendered. Frame
        is the body-text colour (white, cyanotype ink)."""
        img = rq.render("03:00", self._row(), 800, 480, mode="production", theme="blueprint")
        assert img.getpixel((400, 16)) == rq.SPECTRA6["white"], "top frame line missing"
        assert img.getpixel((400, 463)) == rq.SPECTRA6["white"], "bottom frame line missing"
        assert img.getpixel((16, 240)) == rq.SPECTRA6["white"], "left frame line missing"
        assert img.getpixel((783, 240)) == rq.SPECTRA6["white"], "right frame line missing"

    def test_blueprint_border_is_theme_gated(self):
        """Border is gated on theme == 'blueprint'; no other theme (including
        bauhaus, which uses a different graphic at different coordinates)
        should paint a crosshair arm at (6, 16)."""
        for theme in ("default", "dark", "scholar", "newsprint", "nightvision",
                      "illuminated", "risograph", "comic"):
            img = rq.render("03:00", self._row(), 800, 480, mode="production", theme=theme)
            expected_bg = rq.THEMES[theme]["page_bg"]
            # (6, 16) lands on the blueprint TL crosshair's leftmost arm
            # pixel; other themes must leave it showing page_bg.
            assert img.getpixel((6, 16)) == expected_bg, (
                f"theme {theme} painted something at the blueprint crosshair location"
            )

    def test_blueprint_border_appears_in_debug_and_card_modes_too(self):
        """The border is part of the blueprint theme's visual identity, so
        it must show up regardless of render mode."""
        for mode in ("production", "debug", "card"):
            img = rq.render("03:00", self._row(), 800, 480, mode=mode, theme="blueprint")
            assert img.getpixel((16, 16)) == rq.SPECTRA6["red"], f"blueprint mode={mode} missing TL crosshair"

    def test_blueprint_border_uses_theme_colours_not_hardcoded_rgb(self):
        """``draw_blueprint_border`` must pull its colours from the passed-in
        theme dict (text for the frame, accent for the crosshairs). Call
        the helper with a non-default palette and assert the output
        reflects it."""
        image = Image.new("RGB", (800, 480), color=(255, 255, 255))
        custom = {
            "text": rq.SPECTRA6["green"],
            "accent": rq.SPECTRA6["yellow"],
        }
        rq.draw_blueprint_border(image, custom)
        assert image.getpixel((16, 16)) == rq.SPECTRA6["yellow"], "crosshair should use accent"
        assert image.getpixel((400, 16)) == rq.SPECTRA6["green"], "frame should use text colour"

    def test_blueprint_interior_grid_paints_in_body_text_colour(self):
        """The graph-paper grid inside the frame uses the body-text colour.
        Sample an intersection well clear of the frame and of the quote
        block so no glyph or outer rule is painted on top. At 20px spacing,
        with ``frame_inset=16``, the first interior horizontal rule is at
        y=36 and the first interior vertical rule is at x=36; (36, 56) is
        a clean grid crossing. Direct-call (no ``page_bg`` in palette →
        Layer 0 dither is skipped) so the off-grid pixel stays the
        white canvas the test prepared."""
        image = Image.new("RGB", (800, 480), color=(255, 255, 255))
        rq.draw_blueprint_border(image, {"text": rq.SPECTRA6["green"], "accent": rq.SPECTRA6["red"]})
        assert image.getpixel((36, 56)) == rq.SPECTRA6["green"], "grid intersection should use text colour"
        # Off-grid whitespace between rules stays page_bg (white canvas here).
        assert image.getpixel((45, 45)) == (255, 255, 255), "between-grid pixel should remain unpainted"

    def test_blueprint_grid_is_theme_gated(self):
        """No other theme paints a non-page_bg pixel at the blueprint
        grid-intersection coordinate (36, 56). Newsprint, alchemy, and
        illuminated are all excluded because their Layer 0 grounds
        intentionally paint sparse Bayer flecks across `page_bg`
        (black halftone for newsprint, parchment yellow flecks for
        alchemy, cream yellow flecks for illuminated). Dispatch is
        excluded for the same reason — its Layer 0 1-in-8 cream wash
        also flips white-ground pixels to yellow at this coordinate."""
        row = self._row()
        for theme in ("default", "dark", "scholar", "nightvision",
                      "bauhaus", "risograph", "comic"):
            img = rq.render("03:00", row, 800, 480, mode="production", theme=theme)
            expected_bg = rq.THEMES[theme]["page_bg"]
            assert img.getpixel((36, 56)) == expected_bg, (
                f"theme {theme} painted something at the blueprint grid coordinate"
            )


def test_blueprint_border_paints_top_dimension_line():
    """The upleveled blueprint border adds a top-margin overall-width
    dimension callout. The rule + extension ticks are in the white drafting
    ink; the inward arrowheads and the centred measurement figure are in the
    red registration ink — so both inks appear in the dimension band."""
    img = Image.new("RGB", (800, 480), rq.SPECTRA6["blue"])
    rq.draw_blueprint_border(img, rq.THEMES["blueprint"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    white = rq.SPECTRA6["white"]
    dim_red = sum(1 for x in range(110, 690) for y in range(36, 45) if px[x, y] == red)
    dim_white = sum(1 for x in range(110, 690) for y in range(36, 45) if px[x, y] == white)
    assert dim_red > 30, "dimension arrowheads / figure (red) missing"
    assert dim_white > 100, "dimension rule / extension ticks (white) missing"


def test_blueprint_border_paints_scale_bar():
    """The upleveled blueprint border adds a bottom-right graduated
    SCALE 1:1 legend bar in the drafting-ink (white) colour."""
    img = Image.new("RGB", (800, 480), rq.SPECTRA6["blue"])
    rq.draw_blueprint_border(img, rq.THEMES["blueprint"])
    px = img.load()
    white = rq.SPECTRA6["white"]
    bar_x = 800 - 1 - 16 - 12 - 80
    bar_y = 480 - 1 - 16 - 18
    assert px[bar_x + 2, bar_y + 3] == white, "scale-bar first filled cell missing"


def test_blueprint_callouts_clear_debug_banner_band():
    """The dimension line sits at y=40 — below the y=14-29 debug banner — so
    blueprint still needs no _DEBUG_LABEL_RIGHT_INSET adjustment for them."""
    img = Image.new("RGB", (800, 480), rq.SPECTRA6["blue"])
    rq.draw_blueprint_border(img, rq.THEMES["blueprint"])
    px = img.load()
    red = rq.SPECTRA6["red"]
    banner = sum(1 for x in range(600, 690) for y in range(14, 30) if px[x, y] == red)
    # The TR crosshair is at the frame corner (x~width-16), left of x=600,
    # so the banner sample band should carry no callout red.
    assert banner == 0, "blueprint callout intrudes on the debug-banner band"


# --- methods moved out of shared test classes (indented as in their class) ---
# From class TestThemes in tests/test_render_quote.py:
    def test_blueprint_theme_uses_white_on_blue_cyanotype_palette(self):
        """Cyanotype blueprint: blue ground, white ink for every
        structural mark (body, frame, grid, crosshairs), red accent
        for the matched time phrase (the "annotated dimension" in red
        pencil over an otherwise monochromatic print). Pin the
        inverted palette so a regression that flipped it back to
        white/blue/red would collapse the theme into a Scholar-adjacent
        layout and lose the photochemical-drafting-sheet identity."""
        t = rq.THEMES["blueprint"]
        assert t["page_bg"] == rq.SPECTRA6["blue"]
        assert t["text"] == rq.SPECTRA6["white"]
        assert t["accent"] == rq.SPECTRA6["red"]
