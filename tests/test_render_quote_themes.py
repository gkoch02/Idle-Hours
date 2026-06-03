"""Smoke tests for the custom-render themes that bypass the standard literary layout.

These themes (``astrarium``, ``diags``, ``marquee``, ``tarot``, ``vinyl``,
``vitrail``, ``outrun``, ``sampler``) each dispatch out of ``render()`` into
their own frame function and own their composition top to bottom. The contracts
every custom-render frame must keep:

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

CUSTOM_THEMES = ("marquee", "tarot", "vinyl", "vitrail", "outrun", "sampler")


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


class TestVitrailFrame:
    """Gothic stained-glass cathedral window — leaded jewel-tone panes,
    rose-window Roman numeral, and a clear white-glass quote cartouche."""

    def test_uses_full_spectra6_palette(self):
        """The leaded glass deliberately exercises every native ink (the
        whole point — "take full advantage of the hardware"). A real
        render should surface all six Spectra-6 colours via the solid
        panes + jewel-tone stipples."""
        img = rq.render("14:30", make_row(), 800, 480, theme="vitrail")
        used = set(img.getdata())
        assert used == set(rq.SPECTRA6.values()), f"expected all six inks, got {used}"

    def test_quote_cartouche_is_clear_white(self):
        """The quote sits on a solid white-glass knockout so the body text
        stays legible over the colored field. The top-left interior corner
        of the cartouche (just inside the came frame, above the centred
        text block) should be bare white."""
        img = rq.render("14:30", make_row(), 800, 480, theme="vitrail")
        x0, y0, _, _ = rq._VITRAIL_CARTOUCHE
        # A few px inside the frame, near the top edge where the centred
        # quote block does not reach.
        assert img.getpixel((x0 + 8, y0 + 6)) == rq.SPECTRA6["white"]

    def test_rose_window_carries_numeral(self):
        """The rose-window hub paints the Roman-numeral hour in black on a
        clear white hub. Sample the hub region and assert both the white
        hub ground and black numeral ink are present."""
        img = rq.render("03:00", make_row(), 800, 480, theme="vitrail")
        # Rose centre x is always width//2; y is the 800×480 reference constant.
        cx, cy = 800 // 2, rq._VITRAIL_ROSE_CY
        hub_pixels = {
            img.getpixel((x, y))
            for x in range(cx - 24, cx + 24, 2)
            for y in range(cy - 14, cy + 14, 2)
        }
        assert rq.SPECTRA6["white"] in hub_pixels, "rose hub should be clear white glass"
        assert rq.SPECTRA6["black"] in hub_pixels, "rose hub should carry a black numeral"

    def test_no_digital_time_chrome(self):
        """Like the other custom frames, vitrail never surfaces the digital
        HH:MM — the matched phrase and the rose-window Roman numeral carry
        the time. Soft check: a quote that can't mention the time still
        renders cleanly and on-palette for an arbitrary minute."""
        row = make_row(display_quote="A quiet hour with no clock in it.", matched_text="")
        img = rq.render("14:37", row, 800, 480, theme="vitrail")
        assert img.size == (800, 480)
        assert set(img.getdata()).issubset(set(rq.SPECTRA6.values()))

    def test_composes_at_non_native_resolution(self):
        """The rose / arch / cartouche geometry is derived from the canvas
        size (the module constants are the 800×480 reference), so the frame
        must compose cleanly and stay on-palette at an arbitrary size rather
        than spilling off a hardcoded layout."""
        for w, h in ((1024, 600), (640, 384)):
            img = rq.render("08:00", make_row(), w, h, theme="vitrail")
            assert img.size == (w, h)
            assert set(img.getdata()).issubset(set(rq.SPECTRA6.values()))

    def test_render_is_deterministic(self):
        """The seeded tessellation + pure-function geometry must produce a
        byte-identical frame on re-render (panel-dedup / golden contract)."""
        import io

        def png(_):
            img = rq.render("08:00", make_row(), 800, 480, theme="vitrail", mode="production")
            buf = io.BytesIO()
            img.save(buf, "PNG")
            return buf.getvalue()

        assert png(1) == png(2)

    def test_every_hour_renders_on_palette(self):
        """All twelve numeral mappings (and the 00→XII rollover) render
        without raising and stay on-palette."""
        palette = set(rq.SPECTRA6.values())
        for hh in range(24):
            img = rq.render(f"{hh:02d}:15", make_row(), 800, 480, theme="vitrail")
            assert img.size == (800, 480)
            assert set(img.getdata()).issubset(palette), f"off-palette at hour {hh}"

    def test_is_deterministic(self):
        """No RNG in the vitrail path — re-rendering the same time must be
        byte-identical (golden tests + panel dedup depend on this)."""
        row = make_row()
        a = list(rq.render("14:30", row, 800, 480, theme="vitrail").getdata())
        b = list(rq.render("14:30", row, 800, 480, theme="vitrail").getdata())
        assert a == b


class TestOutrunFrame:
    """Synthwave / Outrun — dusk gradient sky, sliced neon sun, perspective grid."""

    def _palette(self):
        return set(rq.SPECTRA6.values())

    def test_is_deterministic(self):
        """The star field is seeded and the rest of the composition is pure
        geometry, so re-rendering the same time must be byte-identical (panel
        dedup + any future golden fixture depend on it)."""
        row = make_row()
        a = list(rq.render("14:30", row, 800, 480, theme="outrun").getdata())
        b = list(rq.render("14:30", row, 800, 480, theme="outrun").getdata())
        assert a == b

    def test_neon_grid_below_horizon(self):
        """The perspective grid lays magenta (red/blue) verticals and cyan
        (green/blue) horizontals over the dark ground, so both red and green
        ink must appear below the horizon."""
        img = rq.render("14:30", make_row(), 800, 480, theme="outrun")
        px = img.load()
        below = [px[x, y] for y in range(rq._OUTRUN_HORIZON + 2, 480) for x in range(0, 800, 3)]
        assert rq.SPECTRA6["red"] in below, "missing magenta grid verticals"
        assert rq.SPECTRA6["green"] in below, "missing cyan grid horizontals"

    def test_sun_has_warm_crown(self):
        """The sliced sun's crown carries a yellow→tangerine gradient, so
        yellow ink must appear in the disc cap above the horizon."""
        img = rq.render("14:30", make_row(), 800, 480, theme="outrun")
        px = img.load()
        cx = rq._OUTRUN_SUN_CENTER[0]
        top = rq._OUTRUN_SUN_CENTER[1] - rq._OUTRUN_SUN_RADIUS
        crown = [px[x, y] for y in range(top + 4, top + 34) for x in range(cx - 50, cx + 50)]
        assert rq.SPECTRA6["yellow"] in crown, "sun crown should carry warm yellow ink"

    def test_matched_phrase_is_cyan(self):
        """The matched time-phrase is painted as a green+blue (cyan) stipple in
        the upper sky, where no other element introduces green ink — so green
        in the quote band is a positive signal the accent rendered."""
        row = make_row(display_quote="It struck three o'clock sharp.", matched_text="three o'clock")
        img = rq.render("03:00", row, 800, 480, theme="outrun")
        px = img.load()
        upper = [px[x, y] for y in range(38, 150) for x in range(0, 800, 2)]
        assert rq.SPECTRA6["green"] in upper, "matched-phrase cyan stipple not found in the sky band"

    def test_no_digital_time_chrome(self):
        """Like the other custom frames, outrun never surfaces the digital
        HH:MM — the matched phrase carries the time. Soft check: a quote with
        no matched phrase still renders cleanly and on-palette for an
        arbitrary minute."""
        row = make_row(display_quote="A quiet hour with no clock in it.", matched_text="")
        img = rq.render("14:37", row, 800, 480, theme="outrun")
        assert img.size == (800, 480)
        assert set(img.getdata()).issubset(self._palette())

    def test_composes_at_non_native_resolution(self):
        """The composition is anchored on the 800×480 reference constants but
        every raw pixel write is bounds-clipped, so a shorter/larger canvas
        must crop cleanly and stay on-palette rather than raising."""
        for w, h in ((1024, 600), (320, 192)):
            img = rq.render("08:00", make_row(), w, h, theme="outrun")
            assert img.size == (w, h)
            assert set(img.getdata()).issubset(self._palette()), f"off-palette at {w}x{h}"
