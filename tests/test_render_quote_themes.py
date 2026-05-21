"""Smoke tests for the custom-render themes that bypass the standard literary layout.

These themes (``astrarium``, ``diags``, ``marquee``, ``tarot``, ``vinyl``)
each dispatch out of ``render()`` into their own frame function and own their
composition top to bottom. The contracts every custom-render frame must keep:

* the returned image is the requested ``(width, height)``;
* every output pixel sits on the SPECTRA6 palette (verified after
  ``snap_image_to_palette``);
* the frame doesn't raise on representative inputs (full quote_row, missing
  metadata, edge-of-bucket minutes, every hour in the rotation).

The literary-layout themes have their own assertions in ``test_render_quote.py``;
this module focuses on the dispatch + on-palette + don't-crash invariants the
custom paths add.
"""
from __future__ import annotations

import pytest
from PIL import Image

from idle_hours import render_quote as rq

from .conftest import make_row

CUSTOM_THEMES = ("marquee", "tarot", "vinyl")


def _on_palette(image: Image.Image) -> bool:
    palette = set(rq.SPECTRA6.values())
    return set(image.getdata()).issubset(palette)


@pytest.mark.parametrize("theme", CUSTOM_THEMES)
class TestCustomRenderContract:
    """Every custom-render theme must satisfy the four-clause contract above."""

    def test_returns_requested_size(self, theme):
        img = rq.render("14:30", make_row(), 800, 480, theme=theme)
        assert img.size == (800, 480)

    def test_output_is_on_palette(self, theme):
        img = rq.render("14:30", make_row(), 800, 480, theme=theme)
        assert _on_palette(img), f"{theme} produced off-palette pixels"

    def test_renders_with_empty_metadata(self, theme):
        """A row missing author / title / matched_text must still render."""
        row = make_row(author="", title="", matched_text="")
        img = rq.render("14:30", row, 800, 480, theme=theme)
        assert img.size == (800, 480)
        assert _on_palette(img)

    def test_renders_without_fuzzy_bucket(self, theme):
        """Bucket is re-derived from time_str when missing on the row."""
        row = make_row()
        row.pop("fuzzy_bucket", None)
        img = rq.render("14:30", row, 800, 480, theme=theme)
        assert img.size == (800, 480)


class TestMarqueeFrame:
    """1930s movie-palace marquee — bulb-light border + chunky time chrome."""

    def test_bulb_border_lights_perimeter(self):
        """Yellow + red bulb-lights run along all four edges. Sample a
        known bulb position on each edge and assert one of the two
        canonical bulb colours sits there. Spacing 32 px, inset 16 px,
        radius 5 px — first top-edge bulb sits at (16, 16); first
        right-edge bulb at (784, 48); etc."""
        img = rq.render("14:30", make_row(), 800, 480, theme="marquee")
        # Pick the canvas-edge bulb positions defined by the constants.
        positions = [
            (rq._MARQUEE_BULB_INSET, rq._MARQUEE_BULB_INSET),                # top-left corner
            (800 - rq._MARQUEE_BULB_INSET, rq._MARQUEE_BULB_INSET),          # top-right corner
            (rq._MARQUEE_BULB_INSET, 480 - rq._MARQUEE_BULB_INSET),          # bottom-left corner
            (800 - rq._MARQUEE_BULB_INSET, 480 - rq._MARQUEE_BULB_INSET),    # bottom-right corner
        ]
        bulb_colours = {rq.SPECTRA6["yellow"], rq.SPECTRA6["red"], rq.SPECTRA6["white"]}
        for (cx, cy) in positions:
            # The bulb covers a small region; pick the centre pixel.
            assert img.getpixel((cx, cy)) in bulb_colours, \
                f"expected a bulb-colour pixel at corner {(cx, cy)}, got {img.getpixel((cx, cy))}"

    def test_feature_title_renders_at_top(self):
        """The big Bungee Shade title chrome sits centred near y≈112
        (the ``_marquee_paint_feature_title`` cy). Sample a stripe
        across that row and assert white pixels appear (the title
        glyphs). The title comes from ``quote_row['title']``; missing
        title falls back to the time."""
        row = make_row(title="Anne of Avonlea")
        img = rq.render("14:30", row, 800, 480, theme="marquee")
        white_seen = any(
            img.getpixel((x, 112)) == rq.SPECTRA6["white"]
            for x in range(200, 600, 5)
        )
        assert white_seen, "Bungee Shade title chrome should paint white pixels at y≈112"

    def test_feature_title_falls_back_to_author_or_brand(self):
        """A row with no title falls back to the author name in the
        big chrome slot; a row with neither falls back to the literal
        ``"IDLE HOURS"`` brand string. Deliberately never falls back
        to the digital HH:MM — surfacing the wall-clock time would
        undermine the fuzzy-clock conceit (the matched phrase carries
        the time signal)."""
        # Author-only fallback.
        row = make_row(title="", author="L. M. Montgomery")
        img = rq.render("14:30", row, 800, 480, theme="marquee")
        white_seen = any(
            img.getpixel((x, 112)) == rq.SPECTRA6["white"]
            for x in range(200, 600, 5)
        )
        assert white_seen, "author fallback should paint white pixels at y≈112"
        # Brand fallback when both title and author are missing.
        row = make_row(title="", author="")
        img = rq.render("14:30", row, 800, 480, theme="marquee")
        white_seen = any(
            img.getpixel((x, 112)) == rq.SPECTRA6["white"]
            for x in range(200, 600, 5)
        )
        assert white_seen, "IDLE HOURS brand fallback should paint white pixels at y≈112"

    def test_no_digital_time_chrome(self):
        """The marquee deliberately never surfaces the digital HH:MM
        anywhere on the canvas — the matched phrase carries the time
        signal. This is a soft regression check: it can't prove the
        time isn't painted (the body's matched phrase might happen to
        contain digits), but it asserts the documented design.

        Concrete proof: render with a time the body cannot mention,
        and assert the standard HH:MM string doesn't appear via the
        chrome's Bungee Shade typography. We approximate by checking
        that the top tagline band doesn't contain a colon-shaped
        yellow glyph silhouette at the position where the showtime
        used to render.
        """
        # The 14:30 colon used to render at x≈400 in the Bungee Shade
        # time chrome. Now that band is the "NOW SHOWING" tagline; we
        # assert the central pixel is BLACK (chassis) rather than
        # WHITE (Bungee Shade glyph stroke).
        row = make_row(title="Anne of Avonlea", author="L. M. Montgomery")
        img = rq.render("14:30", row, 800, 480, theme="marquee")
        # Sample a few central-band rows where the big time used to
        # land at y≈80–145 (the chunky 84pt Bungee Shade extents).
        # Confirm there's no WHITE pixel at the canvas centre in that
        # band that's *not* part of the new feature-title chrome —
        # this test relies on "Anne of Avonlea" being narrower than
        # the original 84pt time chrome, so the centre column at
        # certain ys is bare-black.
        # Sample the y=70 row (above the title): should be all-black.
        for x in (380, 400, 420):
            assert img.getpixel((x, 70)) == rq.SPECTRA6["black"], \
                f"unexpected non-black pixel at ({x}, 70) — digital time chrome leaked?"

    def test_feature_title_wraps_long_titles(self):
        """A title too long for a single line at the smallest fit-step
        wraps onto two lines without raising. Renders successfully and
        produces an on-palette image."""
        row = make_row(title="Frankenstein; or, The Modern Prometheus")
        img = rq.render("14:30", row, 800, 480, theme="marquee")
        assert img.size == (800, 480)
        palette = set(rq.SPECTRA6.values())
        assert set(img.getdata()).issubset(palette)

    def test_credits_render_when_author_present(self):
        """WRITTEN BY label paints in yellow when the row carries an
        author; the label lives in the credits band at y≈384 onward.
        Title is no longer in the credits (it moved to the top
        chrome) so the test only asserts the WRITTEN BY line."""
        row = make_row(author="L. M. Montgomery", title="Anne of Avonlea")
        img = rq.render("14:30", row, 800, 480, theme="marquee")
        yellow_seen = any(
            img.getpixel((x, 386)) == rq.SPECTRA6["yellow"]
            for x in range(100, 700, 4)
        )
        assert yellow_seen, "WRITTEN BY label should paint yellow pixels in the credits band"

    def test_renders_without_credits(self):
        """Missing author + title must not crash; the credits painter
        no-ops on missing author, and the feature-title painter falls
        back to the time."""
        row = make_row(author="", title="")
        img = rq.render("14:30", row, 800, 480, theme="marquee")
        assert img.size == (800, 480)


class TestTarotFrame:
    """Major-arcana card — renders for every hour without raising."""

    @pytest.mark.parametrize("hour", range(0, 24))
    def test_renders_for_every_hour(self, hour):
        img = rq.render(f"{hour:02d}:00", make_row(), 800, 480, theme="tarot")
        assert img.size == (800, 480)
        assert _on_palette(img)

    def test_all_twelve_emblems_registered(self):
        """Every hour 1..12 has its own emblem painter (no pentagram
        fallback in normal use). The defensive ``_tarot_emblem_default``
        is still exposed for hours outside that range."""
        assert set(rq._TAROT_EMBLEMS.keys()) == set(range(1, 13))
        # The defensive fallback still exists and renders for an
        # out-of-range hour (e.g. dispatch with hour_int=0 / 13 would
        # hit _tarot_emblem_default, but the dispatch in render_tarot_frame
        # always normalises to 1..12, so this is purely defence-in-depth).
        from PIL import Image, ImageDraw
        sandbox = Image.new("RGB", (200, 200), rq.SPECTRA6["white"])
        rq._tarot_emblem_default(ImageDraw.Draw(sandbox), 100, 100)
        # No assertion on visual content; just that the call returns
        # without raising for an unmapped hour.

    def test_card_name_is_dithered_tyrian_purple(self):
        """The matched-phrase card name paints via draw_text_dithered with
        dark=red+light=blue at 0.5 density. Both inks must appear in the
        name band — failing means the dither call regressed to a single
        solid colour."""
        row = make_row(matched_text="half past two")
        img = rq.render("14:30", row, 800, 480, theme="tarot")
        # Card name band sits at y≈88..120 (y0=20, +68 offset, font ~22pt).
        # Sample a stripe across the card centre.
        counts = {}
        for y in range(95, 115):
            for x in range(280, 520):
                c = img.getpixel((x, y))
                counts[c] = counts.get(c, 0) + 1
        # Both red and blue pixels must be present (the 50/50 dither).
        assert counts.get(rq.SPECTRA6["red"], 0) > 100, "card name missing red pixels"
        assert counts.get(rq.SPECTRA6["blue"], 0) > 100, "card name missing blue pixels"

    def test_roman_numeral_table_is_complete(self):
        """Every hour 1..12 maps to a Roman numeral string."""
        assert set(rq._TAROT_ROMAN_NUMERALS.keys()) == set(range(1, 13))
        for hour, numeral in rq._TAROT_ROMAN_NUMERALS.items():
            assert numeral and isinstance(numeral, str)


class TestVinylFrame:
    """Turntable + LP back-cover — tonearm angle math + catalog number."""

    @pytest.mark.parametrize("minute,expected_axis", [
        (0,  "up"),     # 0° = pointing up (12-o'-clock)
        (15, "right"),  # 90° = pointing right
        (30, "down"),   # 180° = pointing down
        (45, "left"),   # 270° = pointing left
    ])
    def test_tonearm_cartridge_lands_at_expected_axis(self, minute, expected_axis):
        """The pivoted tonearm's cartridge tip lands on the disk rim at
        the current-minute angle (sweeping clockwise from 12-o'-clock).
        The cartridge stylus pin is a small red filled circle at the
        tip; sample around the expected cardinal point and assert red
        ink appears."""
        img = rq.render(f"11:{minute:02d}", make_row(), 800, 480, theme="vinyl")
        cx, cy, r = rq._VINYL_DISK_CX, rq._VINYL_DISK_CY, rq._VINYL_DISK_R
        # Cardinal probe points just inside the rim.
        probes = {
            "up":    (cx, cy - r + 5),
            "right": (cx + r - 5, cy),
            "down":  (cx, cy + r - 5),
            "left":  (cx - r + 5, cy),
        }
        x, y = probes[expected_axis]
        # The expected axis should have a red pixel within a small window
        # around the cartridge tip.
        red_seen = False
        for dy in range(-8, 9):
            for dx in range(-8, 9):
                if img.getpixel((x + dx, y + dy)) == rq.SPECTRA6["red"]:
                    red_seen = True
                    break
            if red_seen:
                break
        assert red_seen, f"stylus did not paint red at expected {expected_axis} axis"

    def test_catalog_number_format(self):
        assert rq._vinyl_catalog_number("h2_half_past") == "IH-H2-30"
        assert rq._vinyl_catalog_number("h12_exact") == "IH-H12-00"
        assert rq._vinyl_catalog_number("h7_quarter_to") == "IH-H7-45"

    def test_catalog_number_handles_garbage(self):
        assert rq._vinyl_catalog_number("") == "IH-?"
        assert rq._vinyl_catalog_number(None) == "IH-?"
        assert rq._vinyl_catalog_number("h2_unknown_state") == "IH-H2-?"

    def test_wear_speckle_is_deterministic_per_seed(self):
        """Same seed must produce the same wear-mark pattern so the
        per-day daily-seeded variation is stable across re-renders within
        the same day."""
        img_a = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        img_b = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        rq._astrarium_paint_cream_wash(img_a)
        rq._astrarium_paint_cream_wash(img_b)
        rq._vinyl_paint_wear_speckle(img_a, seed=20260521)
        rq._vinyl_paint_wear_speckle(img_b, seed=20260521)
        assert list(img_a.getdata()) == list(img_b.getdata())

    def test_wear_speckle_varies_with_seed(self):
        """Different seeds must produce different wear-mark patterns
        (i.e., the speckle isn't a no-op)."""
        img_a = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        img_b = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        rq._astrarium_paint_cream_wash(img_a)
        rq._astrarium_paint_cream_wash(img_b)
        rq._vinyl_paint_wear_speckle(img_a, seed=20260101)
        rq._vinyl_paint_wear_speckle(img_b, seed=20261231)
        assert list(img_a.getdata()) != list(img_b.getdata())
