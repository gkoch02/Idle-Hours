"""Smoke tests for the custom-render themes that bypass the standard literary layout.

These themes (``astrarium``, ``diags``, ``marquee``, ``tarot``, ``vinyl``,
``vitrail``, ``outrun``, ``sampler``, ``lieder``, ``izakaya``, ``abyssal``) each dispatch out of ``render()`` into
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

import bisect
import json
import math
import threading

import pytest
from PIL import Image, ImageDraw

from idle_hours import render_quote as rq

from .conftest import make_row
from .pixel_helpers import distinct_inks, ink_counts, pixel_bytes

CUSTOM_THEMES = ("marquee", "tarot", "vinyl", "vitrail", "outrun", "sampler", "lieder", "izakaya",
                 "abyssal", "pride", "pulp", "vhs", "cardcatalog", "metro", "bakelite", "intaglio",
                 "nocturne", "plaque", "daguerreotype")


def _on_palette(image: Image.Image) -> bool:
    palette = set(rq.SPECTRA6.values())
    return distinct_inks(image).issubset(palette)


# Perceived luminance of each ink as the panel actually reflects it, from the
# epdoptimize calibration in docs/spectra6_color_recipes.md. Assertions about
# how bright something *reads* have to use these: the saturated palette IDs are
# addresses, not colours, and predicting tone from them is the mistake the
# pride brown documents. Panels drift unit to unit, so this is a guide — the
# thresholds it feeds are loose bands, not measurements.
_PANEL_INK = {
    "white": (0xB9, 0xC7, 0xC9), "black": (0x1F, 0x22, 0x26),
    "red": (0x62, 0x20, 0x1E), "yellow": (0xC1, 0xBB, 0x1E),
    "blue": (0x23, 0x3F, 0x8E), "green": (0x35, 0x56, 0x3A),
}
_PANEL_LUM = {
    rq.SPECTRA6[name]: 0.2126 * r + 0.7152 * g + 0.0722 * b
    for name, (r, g, b) in _PANEL_INK.items()
}
_PANEL_INK_BY_RGB = {rq.SPECTRA6[name]: ink for name, ink in _PANEL_INK.items()}


def _panel_mix(shares: dict) -> tuple:
    """Blend calibrated inks by share — what a stipple averages to by eye."""
    total = sum(shares.values())
    return tuple(sum(_PANEL_INK[n][i] * w for n, w in shares.items()) / total
                 for i in range(3))


def _wcag_contrast(a: tuple, b: tuple) -> float:
    """WCAG 2.x contrast ratio between two panel colours.

    Defined for sRGB emissive displays rather than reflective e-ink, so treat
    it as a calibrated relative yardstick, not an absolute. It is still the
    right yardstick: it is the only one that puts a *number* on the quantity
    two builds of this theme failed on while every other assertion passed.
    """
    def rel_lum(rgb):
        chan = []
        for v in rgb:
            v /= 255.0
            chan.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2]
    la, lb = rel_lum(a), rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


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


class TestMetroFrame:
    def test_long_metadata_labels_do_not_overlap(self):
        """Shipped Shelley metadata must retain the Metro row's 12 px gutter."""
        draw = ImageDraw.Draw(Image.new("RGB", (800, 480)))
        author_font = rq.load_font(rq.theme_font_candidates("metro", "quote_bold"), 16)
        title_font = rq.load_font(rq.theme_font_candidates("metro", "quote_regular"), 16)
        author, title = rq._metro_fit_metadata(
            draw,
            "MARY WOLLSTONECRAFT SHELLEY",
            "Frankenstein; or, the modern prometheus",
            author_font,
            title_font,
        )
        author_right = 174 + draw.textlength(author, font=author_font)
        title_left = 658 - draw.textlength(title, font=title_font)
        assert author_right + 12 <= title_left
        assert author.endswith("…") or title.endswith("…")


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
        assert distinct_inks(img).issubset(palette)

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
        assert pixel_bytes(img_a) == pixel_bytes(img_b)

    def test_wear_speckle_varies_with_seed(self):
        """Different seeds must produce different wear-mark patterns
        (i.e., the speckle isn't a no-op)."""
        img_a = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        img_b = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        rq._astrarium_paint_cream_wash(img_a)
        rq._astrarium_paint_cream_wash(img_b)
        rq._vinyl_paint_wear_speckle(img_a, seed=20260101)
        rq._vinyl_paint_wear_speckle(img_b, seed=20261231)
        assert pixel_bytes(img_a) != pixel_bytes(img_b)


class TestVitrailFrame:
    """Gothic stained-glass cathedral window — leaded jewel-tone panes,
    rose-window Roman numeral, and a clear white-glass quote cartouche."""

    def test_uses_full_spectra6_palette(self):
        """The leaded glass deliberately exercises every native ink (the
        whole point — "take full advantage of the hardware"). A real
        render should surface all six Spectra-6 colours via the solid
        panes + jewel-tone stipples."""
        img = rq.render("14:30", make_row(), 800, 480, theme="vitrail")
        used = distinct_inks(img)
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
        assert distinct_inks(img).issubset(set(rq.SPECTRA6.values()))

    def test_composes_at_non_native_resolution(self):
        """The rose / arch / cartouche geometry is derived from the canvas
        size (the module constants are the 800×480 reference), so the frame
        must compose cleanly and stay on-palette at an arbitrary size rather
        than spilling off a hardcoded layout."""
        for w, h in ((1024, 600), (640, 384)):
            img = rq.render("08:00", make_row(), w, h, theme="vitrail")
            assert img.size == (w, h)
            assert distinct_inks(img).issubset(set(rq.SPECTRA6.values()))

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
            assert distinct_inks(img).issubset(palette), f"off-palette at hour {hh}"

    def test_is_deterministic(self):
        """No RNG in the vitrail path — re-rendering the same time must be
        byte-identical (golden tests + panel dedup depend on this)."""
        row = make_row()
        a = pixel_bytes(rq.render("14:30", row, 800, 480, theme="vitrail"))
        b = pixel_bytes(rq.render("14:30", row, 800, 480, theme="vitrail"))
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
        a = pixel_bytes(rq.render("14:30", row, 800, 480, theme="outrun"))
        b = pixel_bytes(rq.render("14:30", row, 800, 480, theme="outrun"))
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

    def test_matched_phrase_is_magenta(self):
        """The matched time-phrase is painted as a red-biased red+blue (magenta)
        stipple in the navy upper sky. The sky gradient only starts mixing red
        in below frac 0.42 of the horizon (y >= 126 for the 300px horizon), so
        sampling the navy band above that (y < 120) isolates the accent — red
        there is a positive signal the magenta phrase rendered. Biased toward
        red (not 50/50 violet) so it stays legible against the navy/blue sky
        instead of melting into the blue ground, and ties to the magenta grid."""
        row = make_row(display_quote="It struck three o'clock sharp.", matched_text="three o'clock")
        img = rq.render("03:00", row, 800, 480, theme="outrun")
        px = img.load()
        navy_band = [px[x, y] for y in range(38, 120) for x in range(0, 800, 2)]
        assert rq.SPECTRA6["red"] in navy_band, "matched-phrase magenta stipple not found in the navy sky band"

    def test_no_digital_time_chrome(self):
        """Like the other custom frames, outrun never surfaces the digital
        HH:MM — the matched phrase carries the time. Soft check: a quote with
        no matched phrase still renders cleanly and on-palette for an
        arbitrary minute."""
        row = make_row(display_quote="A quiet hour with no clock in it.", matched_text="")
        img = rq.render("14:37", row, 800, 480, theme="outrun")
        assert img.size == (800, 480)
        assert distinct_inks(img).issubset(self._palette())

    def test_composes_at_non_native_resolution(self):
        """The composition is anchored on the 800×480 reference constants but
        every raw pixel write is bounds-clipped, so a shorter/larger canvas
        must crop cleanly and stay on-palette rather than raising."""
        for w, h in ((1024, 600), (320, 192)):
            img = rq.render("08:00", make_row(), w, h, theme="outrun")
            assert img.size == (w, h)
            assert distinct_inks(img).issubset(self._palette()), f"off-palette at {w}x{h}"


class TestLiederRhythm:
    """Bar-filling invariants for the ``lieder`` engraver.

    The theme's defining claim is that every bar holds exactly ``numerator``
    beats. Two ways that can break, both silent in a rendered PNG unless you
    count: a note can straddle a barline (which real notation would have to
    write as a tie), and the final bar can be left short.

    The second shipped broken once. The original final-bar fill only grew the
    last note when the remainder happened to be one of four notated durations
    and gave up otherwise, which left the last bar incomplete on 51% of
    (row, meter) pairs across the committed corpus — 83% at 12/4 — while the
    docs claimed bars always fill exactly. It is now padded with rests. This
    sweeps real corpus rows against every meter the clock can produce, because
    the meter *is* the hour and all twelve are reachable in normal operation.
    """

    METERS = tuple(range(1, 13))

    @staticmethod
    def _corpus_rows(limit):
        path = rq.BASE_DIR / "assets" / "quote_database.jsonl"
        rows = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if len(rows) >= limit:
                    break
                row = json.loads(line)
                if row.get("display_quote"):
                    rows.append(row)
        return rows

    @pytest.mark.parametrize("meter", METERS)
    def test_every_bar_holds_exactly_the_meter(self, meter):
        for row in self._corpus_rows(60):
            notes = rq._lieder_notes(row)
            if not notes:
                continue
            rq._lieder_rhythm(notes, meter)
            total = sum(n["beats"] for n in notes)
            assert abs(total % meter) < 1e-9, (
                f"meter {meter}/4, row {row.get('source_id')}:{row.get('line_number')}: "
                f"{total} beats leaves a final bar of {total % meter}, not {meter}"
            )

    @pytest.mark.parametrize("meter", METERS)
    def test_no_note_straddles_a_barline(self, meter):
        for row in self._corpus_rows(60):
            notes = rq._lieder_notes(row)
            if not notes:
                continue
            rq._lieder_rhythm(notes, meter)
            elapsed = 0.0
            for note in notes:
                start = elapsed // meter
                end = (elapsed + note["beats"] - 1e-9) // meter
                assert start == end, (
                    f"meter {meter}/4, row {row.get('source_id')}:{row.get('line_number')}: "
                    f"a {note['beats']}-beat note starting at {elapsed} crosses a barline; "
                    "notation would need a tie"
                )
                elapsed += note["beats"]

    def test_rests_only_ever_pad_the_tail(self):
        """Rests exist to complete the final bar, so none may precede a sung note."""
        for row in self._corpus_rows(40):
            for meter in (3, 7, 12):
                notes = rq._lieder_notes(row)
                if not notes:
                    continue
                rq._lieder_rhythm(notes, meter)
                kinds = [bool(n.get("rest")) for n in notes]
                assert kinds == sorted(kinds), (
                    f"meter {meter}/4: a rest appears before a sung syllable in "
                    f"{row.get('source_id')}:{row.get('line_number')}"
                )

    def test_cadence_lands_on_the_last_sung_note_not_a_rest(self):
        """Trailing rests must not steal the cadence from the final syllable."""
        for row in self._corpus_rows(40):
            for meter in (4, 12):
                notes = rq._lieder_notes(row)
                if len(notes) < 2:
                    continue
                rq._lieder_rhythm(notes, meter)
                rq._lieder_contour(rq._lieder_seed(row), notes)
                sung = [n for n in notes if not n.get("rest")]
                # Tonic degrees of C major on this staff: positions -2 and 5.
                assert (sung[-1]["pitch"] + 2) % 7 == 0, (
                    f"meter {meter}/4: final sung note is not the tonic "
                    f"({sung[-1]['pitch']}) in {row.get('source_id')}:{row.get('line_number')}"
                )


class TestFooterTruncationTerminates:
    """Text-shrinking loops must terminate however small the width budget is.

    ``_questline_paint_footer`` and ``_chrono_paint_footer`` were written from
    the same template and carried the same defect: the loop shrank ``title``
    but guarded on ``text``, which is rebuilt as ``f"— from {title}… —"`` every
    pass and therefore stays truthy after the title is exhausted. Once the
    budget was too small to fit the bare ``"— from … —"``, the loop was a fixed
    point and spun forever.

    That is a hard hang of the render path, not a cosmetic bug: fatal in-process
    on the curator UI's ``/api/preview`` thread, and a render_timeout plus
    backoff on the appliance. Both were latent rather than live — the budget is
    a fixed constant that happens to be generous — so nothing caught them, and
    a golden fixture never would: a hang produces no pixels to compare.

    These run the painter with the budget squeezed to nothing, on a worker
    thread with a timeout, so a reintroduced hang fails in seconds instead of
    burning the job's whole ``timeout-minutes``.
    """

    LONG_TITLE = "A Considerably Overlong Book Title That Cannot Possibly Fit" * 3

    @staticmethod
    def _run_with_timeout(fn, seconds=10):
        done = threading.Event()
        error: list[BaseException] = []

        def target():
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001 - re-raised on the main thread
                error.append(exc)
            finally:
                done.set()

        threading.Thread(target=target, daemon=True).start()
        finished = done.wait(seconds)
        if error:
            raise error[0]
        return finished

    @pytest.mark.parametrize(
        "painter_name, box_name",
        [
            ("_questline_paint_footer", "_QUESTLINE_BOX"),
            ("_chrono_paint_footer", "_CHRONO_WINDOW"),
        ],
    )
    def test_terminates_with_no_width_budget(self, painter_name, box_name, monkeypatch):
        # Squeeze the box until the width budget cannot fit even the ellipsis
        # stub, which is the exact condition that used to spin.
        box = getattr(rq, box_name)
        monkeypatch.setattr(rq, box_name, (box[0], box[1], box[0] + 1, box[3]))
        painter = getattr(rq, painter_name)
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["black"])
        draw = ImageDraw.Draw(image)
        row = {"display_quote": "It was half past two.", "matched_text": "half past two",
               "title": self.LONG_TITLE, "author": "Edith Wharton"}
        assert self._run_with_timeout(lambda: painter(image, draw, row)), (
            f"{painter_name} did not terminate with an exhausted width budget — "
            "the truncation loop is a fixed point again"
        )

    @pytest.mark.parametrize("theme", ("questline", "chrono"))
    def test_frame_still_renders_with_an_absurd_title(self, theme):
        """The normal path must survive a title no sane budget can fit."""
        row = {"display_quote": "It was half past two when the clock struck.",
               "matched_text": "half past two", "title": self.LONG_TITLE,
               "author": "Edith Wharton"}
        assert self._run_with_timeout(
            lambda: rq.render("02:30", row, 800, 480, mode="production", theme=theme)
        ), f"{theme} frame did not terminate with an absurd title"


class TestAbyssalSeafoamMix:
    """The surface band must actually be the seafoam recipe it claims.

    ``abyssal`` is built around claiming G+B+W @ 40/30/30 — the recipe
    ``spectra6_color_recipes.md`` had held open as a forward reference since the
    catalogue was written — and the README, CLAUDE.md and the catalogue itself
    all say so. The first revision allocated 5 white / 4 green cells and left
    the remaining 7 to blue, which is G25/B44/W31: a substantially bluer surface
    that did not implement the recipe. Nothing caught it, because the only
    seafoam test in the suite checks the *diags swatch list's* names rather than
    any theme's implementation.

    The target is read out of ``_DIAGS_TRIPLE_SWATCHES`` rather than hardcoded,
    so the recipe and its one consumer cannot drift apart independently.
    """

    # The quantisation floor for a 4x4 tile is 0.025 (16 cells split 6/5/5
    # against 0.40/0.30/0.30). The defect this fences was 0.150, so a tolerance
    # anywhere between leaves the test meaningful; 0.06 is comfortably clear of
    # the floor without approaching the bug.
    TOLERANCE = 0.06

    @staticmethod
    def _target() -> dict[str, float]:
        entry = next(e for e in rq._DIAGS_TRIPLE_SWATCHES if e[0] == "seafoam")
        _, first, second, third, w_first, w_second, _ = entry
        assert (first, second, third) == (rq.SPECTRA6["green"], rq.SPECTRA6["blue"], rq.SPECTRA6["white"])
        return {"G": w_first, "B": w_second, "W": round(1.0 - w_first - w_second, 6)}

    @staticmethod
    def _measure(y0: int, rows: int = 4) -> dict[str, float]:
        """Ink shares in the bare water layer, over whole Bayer tiles.

        Measures ``_abyssal_paint_water`` on its own rather than the finished
        frame: the caustic net, marine snow and jellyfish all paint over the
        water, and a sample that included them would be measuring the wrong
        thing. ``rows`` must be a multiple of 4 — a single row of a 4x4 tile is
        not representative (row 2 of the matrix alone reads W50/G25/B25).
        """
        assert rows % 4 == 0
        image = rq.Image.new("RGB", (800, 480), rq.SPECTRA6["blue"])
        rq._abyssal_paint_water(image)
        px = image.load()
        names = {rq.SPECTRA6["white"]: "W", rq.SPECTRA6["green"]: "G", rq.SPECTRA6["blue"]: "B"}
        counts = {"W": 0, "G": 0, "B": 0}
        for y in range(y0, y0 + rows):
            for x in range(800):
                counts[names[px[x, y]]] += 1
        total = sum(counts.values())
        return {k: v / total for k, v in counts.items()}

    def test_surface_matches_the_documented_recipe(self):
        target = self._target()
        got = self._measure(0)
        for ink in ("G", "B", "W"):
            assert abs(got[ink] - target[ink]) <= self.TOLERANCE, (
                f"seafoam surface {ink} is {got[ink]:.3f}, recipe says {target[ink]:.3f} — "
                f"the band is not the mix abyssal is built around (full mix: {got})"
            )

    def test_green_leads_the_surface_mix(self):
        """Green is the *dominant* ink at 40%; the bug made it the smallest."""
        got = self._measure(0)
        assert got["G"] > got["B"] and got["G"] > got["W"], (
            f"green is not the leading ink at the surface ({got}) — seafoam is "
            "green-dominant, and a blue-led mix is just water"
        )

    def test_band_fades_to_plain_blue_with_depth(self):
        """The mix is animated by depth: both light inks recede, blue takes over."""
        samples = [self._measure(y) for y in (0, 24, 48, 72, 92)]
        for earlier, later in zip(samples, samples[1:]):
            assert later["B"] >= earlier["B"], f"blue share did not rise with depth: {samples}"
            assert later["G"] <= earlier["G"], f"green share did not fall with depth: {samples}"
            assert later["W"] <= earlier["W"], f"white share did not fall with depth: {samples}"
        assert samples[-1]["B"] > 0.9, f"surface band had not resolved to plain blue by its bottom: {samples[-1]}"


class TestPrideStripeInkRatios:
    """The flag's fold lighting must not shift the stripe hues.

    ``pride`` paints two of its six stripes as two-ink mixes — orange as the
    R+Y 5/8:3/8 tangerine, violet as the R+B 1:1 — and lights the whole flag by
    dithering white or black in at a density that tracks the cloth's tilt. The
    obvious way to combine those is to pick the stripe ink by one Bayer read and
    then overwrite some of those pixels by a second read, and it is wrong: a
    Bayer tile has a fixed number of cells, so *any* two reads of it are
    perfectly correlated and no phase shift decorrelates them. Measured across
    all sixteen 4x4 shifts, the lit face of the violet stripe came out at 0.27
    or 0.73 red against a target of 0.50 — the hue sliding toward blue on one
    face of every fold and toward red on the other, a colour shift wearing the
    costume of shading.

    ``_pride_paint_flag`` therefore resolves each pixel with a *single* read
    that partitions the tile three ways. These tests measure the surviving mix
    directly off the rendered canvas across the lighting range, so they fail if
    the two-read form is ever reintroduced — including by someone "simplifying"
    the partition back into an overlay.
    """

    # Generous, because the mix can only be quantised to whole tile cells: at
    # peak lighting the violet stripe has 51 of 64 cells left to split evenly,
    # which is 0.5098 rather than 0.5. Anything approaching the 0.23 error the
    # two-read form produced is a different phenomenon entirely.
    TOLERANCE = 0.06

    @staticmethod
    def _mix(level: float, light_density: float) -> float:
        """Replay the painter's partition and return the surviving light share."""
        tile = len(rq.BAYER_8x8)
        scale = tile * tile
        peak = rq._PRIDE_LIGHT_PEAK if level >= 0 else rq._PRIDE_SHADE_PEAK
        cells = round(abs(level) * peak * scale)
        split = cells + round(light_density * (scale - cells))
        dark = light = 0
        for y in range(tile):
            for x in range(tile):
                cell = rq.BAYER_8x8[y][x]
                if cell < cells:
                    continue
                if cell < split:
                    light += 1
                else:
                    dark += 1
        return light / (light + dark)

    @pytest.mark.parametrize("light_density", (0.375, 0.5))
    @pytest.mark.parametrize("level", (0.0, 0.25, 0.5, 0.75, 1.0, -0.25, -0.5, -1.0))
    def test_mix_survives_every_lighting_level(self, level, light_density):
        drift = abs(self._mix(level, light_density) - light_density)
        assert drift <= self.TOLERANCE, (
            f"stripe mix {light_density} drifted to {self._mix(level, light_density):.3f} "
            f"at lighting level {level:+.2f} (drift {drift:.3f}) — the fold is shifting "
            "the hue, not the brightness"
        )

    def test_two_read_overlay_would_fail_this_test(self):
        """The guard above is only meaningful if it rejects the broken form.

        Replays the overlay implementation this frame started life with, at
        every phase shift, and asserts that at least one lighting level drifts
        past the tolerance for *every* shift. If this ever passes trivially the
        test above has stopped fencing anything.
        """
        tile = len(rq.BAYER_8x8)
        scale = tile * tile

        def overlay_mix(level, light_density, shift):
            sx, sy = shift
            peak = rq._PRIDE_LIGHT_PEAK if level >= 0 else rq._PRIDE_SHADE_PEAK
            cells = round(abs(level) * peak * scale)
            dark = light = 0
            for y in range(tile):
                for x in range(tile):
                    if rq.BAYER_8x8[(y + sy) % tile][(x + sx) % tile] < cells:
                        continue  # overwritten by the lighting ink
                    if rq.BAYER_8x8[y][x] < round(light_density * scale):
                        light += 1
                    else:
                        dark += 1
            return light / (light + dark) if (light + dark) else 0.0

        for shift in [(sx, sy) for sx in range(tile) for sy in range(tile)]:
            worst = max(
                abs(overlay_mix(level, 0.5, shift) - 0.5)
                for level in (0.5, 1.0, -0.5, -1.0)
            )
            assert worst > self.TOLERANCE, (
                f"the two-read overlay at shift {shift} stayed within tolerance "
                f"(worst drift {worst:.3f}) — this test no longer proves the "
                "partition is load-bearing"
            )

    def test_rendered_violet_stripe_is_balanced_at_the_fold_extremes(self):
        """End-to-end: measure the real canvas, not just the partition maths.

        The sample bands are the *extremes* of the wave, derived from
        ``_pride_wave`` so they follow a future retune, and they are narrow.
        Both details are load-bearing. An earlier version of this test averaged
        a wide band spanning many folds and passed cleanly against a
        deliberately reintroduced two-read overlay: the drift is equal and
        opposite on the lit and shadowed faces, so a wide average cancels it to
        nothing. Measured at the extremes the same broken build reads 0.617
        blue against 0.506 for the partition, which is the signal this test
        exists to see.
        """
        max_tilt = sum(amp * freq for amp, freq, _, _ in rq._PRIDE_WAVE)
        sample_y = 460
        # Only the rainbow field: left of the chevron's point this row is the
        # black band, which has no violet in it to measure.
        field_left = rq._pride_chevron_tip(800) + 30
        levels = {x: rq._pride_wave(x, sample_y)[1] / max_tilt for x in range(field_left, 780)}
        peaks = {
            "lit": max(levels, key=lambda x: levels[x]),
            "shadow": min(levels, key=lambda x: levels[x]),
        }
        row = make_row(display_quote="Nine.", matched_text="Nine", author="", title="")
        image = rq.render("09:00", row, 800, 480, mode="production", theme="pride")
        px = image.load()
        red = rq.SPECTRA6["red"]
        blue = rq.SPECTRA6["blue"]
        for face, peak_x in peaks.items():
            x0 = max(field_left, peak_x - 20)
            reds = blues = 0
            for x in range(x0, min(800, x0 + 40)):
                for y in range(445, 475):
                    ink = px[x, y]
                    if ink == red:
                        reds += 1
                    elif ink == blue:
                        blues += 1
            total = reds + blues
            assert total > 400, f"{face} band had too little violet to measure ({total} px)"
            share = blues / total
            assert abs(share - 0.5) <= self.TOLERANCE, (
                f"violet stripe on the {face} face (x~{peak_x}, level "
                f"{levels[peak_x]:+.2f}) is {share:.3f} blue — the fold lighting is "
                "pulling the hue off violet instead of only its brightness"
            )


class TestPrideChevronBands:
    """The Progress chevron's band order and inks, measured off the canvas.

    This is the part of the flag that could not be implemented from memory. Two
    web searches returned two *different* orders — one putting white between
    pink and brown, the other light blue innermost — and neither matched the
    reference image, whose bands measure (as fractions of flag width) white to
    0.148, pink to 0.223, light blue to 0.303, brown to 0.383, black to 0.465.
    Since the flag belongs to real communities, a wrong order is worse than no
    implementation, so this fences the order rather than trusting the constant
    table to stay in sync with the docs.

    Each band is identified by its own geometry — ``reach = x + |y - centre|``
    against the displaced row, the same term the painter uses — rather than by
    guessing at pixel coordinates, so the assertions survive a wave retune.
    """

    # Expected (minority ink, minority share) per band, innermost outward.
    # A share of 0.0 with a None ink means the band is a single native ink.
    EXPECTED = (
        ("white", None, 0.0),
        ("white", "red", 0.375),
        ("white", "blue", 0.5),
        ("red", "green", 0.5),
        ("black", None, 0.0),
    )
    TOLERANCE = 0.06

    @staticmethod
    def _bands(width: int = 800, height: int = 480) -> list[dict]:
        """Ink histograms per chevron band, bucketed by the painter's own term."""
        image = rq.Image.new("RGB", (width, height), rq.SPECTRA6["white"])
        rq._pride_paint_flag(image)
        px = image.load()
        names = {v: k for k, v in rq.SPECTRA6.items()}
        depths = [d * width for d in rq._PRIDE_CHEVRON_DEPTHS]
        centre = height / 2.0
        slope = rq._pride_arm_slope(width, height)
        buckets = [{} for _ in depths]
        for y in range(0, height, 3):
            for x in range(0, int(depths[-1]) + 1):
                displacement, _ = rq._pride_wave(x, y)
                reach = x + abs((y - displacement) - centre) * slope
                band = bisect.bisect_left(depths, reach)
                if band >= len(depths):
                    continue
                # Skip a margin either side of each boundary: a pixel one cell
                # from a band edge is genuinely ambiguous under rounding, and
                # including it would smear neighbouring inks into the histogram.
                lo = depths[band - 1] if band else 0.0
                if reach - lo < 4 or depths[band] - reach < 4:
                    continue
                ink = names[px[x, y]]
                buckets[band][ink] = buckets[band].get(ink, 0) + 1
        return buckets

    def test_band_inks_and_order(self):
        buckets = self._bands()
        for index, (base, minority, share) in enumerate(self.EXPECTED):
            counts = dict(buckets[index])
            total = sum(counts.values())
            assert total > 500, f"band {index} too small to measure ({total} px)"
            # The lighting inks are white and black, so they are only separable
            # from a band's own inks when the band does not itself use them.
            if minority is None:
                dominant = max(counts, key=counts.get)
                assert dominant == base, (
                    f"band {index} should be solid {base}, reads mostly {dominant} "
                    f"(full histogram {counts}) — the chevron order has drifted"
                )
                continue
            chromatic = {k: v for k, v in counts.items() if k not in ("white", "black")}
            assert chromatic, f"band {index} has no chromatic ink at all: {counts}"
            expected_chromatic = {i for i in (base, minority) if i not in ("white", "black")}
            assert set(chromatic) == expected_chromatic, (
                f"band {index} paints {set(chromatic)}, expected {expected_chromatic} "
                f"(full histogram {counts}) — bands are out of order or a recipe changed"
            )

    def test_pink_and_light_blue_are_not_swapped(self):
        """The specific confusion both web sources got wrong, pinned directly."""
        buckets = self._bands()
        pink, light_blue = buckets[1], buckets[2]
        assert pink.get("red", 0) > 0 and pink.get("blue", 0) == 0, (
            f"the second band should be pink (white+red), reads {dict(pink)}"
        )
        assert light_blue.get("blue", 0) > 0 and light_blue.get("red", 0) == 0, (
            f"the third band should be light blue (white+blue), reads {dict(light_blue)}"
        )

    def test_brown_is_the_documented_red_green_sepia(self):
        """Brown must stay R+G — and must NOT be muted further with black.

        The catalogue offers black as an optional mute for this recipe. It is
        deliberately declined here: this band sits directly against the black
        band, and a darker brown stops being distinguishable from it on a
        six-ink panel. Note the mix looks olive in an RGB preview and reads as a
        real brown on the panel, whose inks are muted (measured red ~#62201E and
        green ~#35563A average to ~#4C3B2C against the flag's #613915) — so do
        not "correct" this from a screenshot.
        """
        brown = dict(self._bands()[3])
        assert brown.get("red", 0) > 0 and brown.get("green", 0) > 0, (
            f"brown band is not the R+G sepia: {brown}"
        )
        ratio = brown["green"] / (brown["red"] + brown["green"])
        assert abs(ratio - 0.5) <= self.TOLERANCE, (
            f"brown band is {ratio:.3f} green, expected the documented 1:1 sepia"
        )

    def test_chevron_clears_the_quote_card(self):
        """The card must sit in the rainbow field, or the arrow loses its point."""
        row = make_row(display_quote="It was half past two.", matched_text="half past two",
                       author="Virginia Woolf", title="Mrs Dalloway")
        draw = ImageDraw.Draw(rq.Image.new("RGB", (800, 480)))
        rect = rq._pride_card_rect(rq._pride_layout(draw, row, 800, 480), 800, 480)
        assert rect[0] >= rq._pride_chevron_tip(800), (
            f"card starts at x={rect[0]}, chevron point is at "
            f"x={rq._pride_chevron_tip(800)} — the card is covering the arrow"
        )

    @pytest.mark.parametrize("width,height", [(800, 480), (1008, 658), (400, 240), (320, 192), (240, 144)])
    def test_corner_band_is_aspect_correct(self, width, height):
        """The hoist corner must land in the same band at every aspect ratio.

        The depths are fractions of WIDTH but an arm's travel is vertical, so a
        literal 45-degree arm puts the corner in a different band on a canvas
        whose aspect differs from the reference's 1008x658. Measured off the
        reference image, the top-left corner is BROWN (its reach is 0.3264 of
        the width, between light blue at 0.303 and brown at 0.383). Rendered at
        the panel's 800x480 with an unscaled 45 degrees it fell at 0.300 —
        inside light blue — so the flag simply had the wrong bands meeting the
        hoist. ``_pride_arm_slope`` restores the reference proportion.
        """
        reach = (height / 2.0) * rq._pride_arm_slope(width, height) / width
        ref_w, ref_h = rq._PRIDE_REFERENCE_SIZE
        expected = (ref_h / 2.0) / ref_w
        assert reach == pytest.approx(expected, abs=1e-6), (
            f"at {width}x{height} the hoist corner sits at {reach:.4f} of the width, "
            f"but the reference flag puts it at {expected:.4f}"
        )
        depths = rq._PRIDE_CHEVRON_DEPTHS
        band = next((i for i, d in enumerate(depths) if reach < d), len(depths))
        assert band == 3, (
            f"the hoist corner falls in band {band}, but the reference flag's corner is "
            "brown (band 3) — the chevron no longer meets the hoist as the flag does"
        )


class TestPrideLayoutFitsEveryCanvas:
    """The card's contents must fit the card at every supported canvas size.

    This is the class of defect the existing preview sweep cannot see: it renders
    each theme at 80x60 and 240x144 and asserts only ``img.size`` and
    palette-subset, so a frame whose text overflows its own card, spills past the
    canvas and clips off the bottom of the image passes it cleanly. ``pride``
    did exactly that — every metric in the frame was a native-panel constant, so
    at 320x192 the text block measured 320x316 against a 244x176 card.

    Measuring the layout directly is what catches it. The 60 px-tall canvases are
    excluded from the height assertion on purpose: no legible layout of a
    literary quote exists in 60 px, and clipping there is the documented
    trade-off (a readable quote beats an intact graphic at thumbnail sizes).
    Width has no such excuse and is asserted everywhere.
    """

    SIZES = ((800, 480), (400, 240), (320, 192), (240, 144), (120, 90), (80, 480), (80, 60), (800, 60))
    LONG = ("The clock had struck half past two some while before, and still nobody in "
            "that long cold house had thought to answer the door, nor to light a lamp.")

    @staticmethod
    def _measure(width, height, row):
        draw = ImageDraw.Draw(rq.Image.new("RGB", (width, height)))
        layout = rq._pride_layout(draw, row, width, height)
        metrics = layout["metrics"]
        rect = rq._pride_card_rect(layout, width, height)
        content = layout["quote_h"] + (
            metrics["gap"] + layout["credits_h"] if layout["credits"] else 0
        )
        return {
            "inner_w": (rect[2] - rect[0]) - 2 * metrics["pad_x"],
            "card_h": rect[3] - rect[1],
            "block_w": layout["block_w"],
            "content_h": content,
            "rect": rect,
        }

    @pytest.mark.parametrize("width,height", SIZES)
    def test_text_never_exceeds_the_card_width(self, width, height):
        row = make_row(display_quote=self.LONG, matched_text="half past two",
                       author="Elizabeth Gaskell", title="North and South")
        m = self._measure(width, height, row)
        assert m["block_w"] <= m["inner_w"], (
            f"at {width}x{height} the text block is {m['block_w']} px wide inside a "
            f"{m['inner_w']} px card — it will spill over the card edge onto the flag"
        )

    @pytest.mark.parametrize("width,height", [s for s in SIZES if s[1] >= 90])
    def test_text_never_exceeds_the_card_height(self, width, height):
        row = make_row(display_quote=self.LONG, matched_text="half past two",
                       author="Elizabeth Gaskell", title="North and South")
        m = self._measure(width, height, row)
        assert m["content_h"] <= m["card_h"], (
            f"at {width}x{height} the content is {m['content_h']} px tall inside a "
            f"{m['card_h']} px card — the bottom will be clipped"
        )

    @pytest.mark.parametrize("width,height", SIZES)
    def test_card_stays_inside_the_canvas(self, width, height):
        row = make_row(display_quote=self.LONG, matched_text="half past two",
                       author="Elizabeth Gaskell", title="North and South")
        x0, y0, x1, y1 = self._measure(width, height, row)["rect"]
        assert 0 <= x0 < x1 <= width, f"card x-range {x0}..{x1} escapes a {width}px canvas"
        assert 0 <= y0 < y1 <= height, f"card y-range {y0}..{y1} escapes a {height}px canvas"

    def test_native_metrics_are_the_declared_constants(self):
        """At 800x480 nothing scales, so the native render is untouched by this.

        Pins the scale-1 identity: if a future edit changes the derivation, the
        native frame moves and the golden fixtures churn for no visible reason.
        """
        m = rq._pride_metrics(800, 480)
        assert m["scale"] == 1.0
        assert (m["pad_x"], m["pad_top"], m["pad_bottom"]) == (
            rq._PRIDE_PAD_X, rq._PRIDE_PAD_TOP, rq._PRIDE_PAD_BOTTOM)
        assert m["gap"] == rq._PRIDE_CREDIT_GAP
        assert m["shadow"] == rq._PRIDE_SHADOW_OFFSET
        assert m["radius"] == rq._PRIDE_CARTOUCHE_RADIUS
        assert m["text_max"] == rq._PRIDE_TEXT_MAX
        assert m["show_credits"] is True

    def test_credits_are_dropped_only_when_illegible(self):
        """Below the floor the byline is a smudge, so it is omitted entirely."""
        assert rq._pride_metrics(800, 480)["show_credits"] is True
        assert rq._pride_metrics(400, 240)["show_credits"] is True
        assert rq._pride_metrics(320, 192)["show_credits"] is False
        row = make_row(display_quote="Nine.", matched_text="Nine",
                       author="Elizabeth Gaskell", title="Cranford")
        draw = ImageDraw.Draw(rq.Image.new("RGB", (320, 192)))
        assert rq._pride_layout(draw, row, 320, 192)["credits"] == []


class TestSynopticValidityStamp:
    """The chart's validity stamp must not claim a timezone it does not have.

    ``run_clock.current_time_str`` is ``datetime.now().strftime("%H:%M")`` —
    naive local wall time — and that value reaches the painter unchanged. An
    earlier revision stamped it ``VALID HHMM UTC`` because that is what a real
    surface analysis carries, which made the label *false* on every appliance
    outside UTC: a device in UTC-4 showing 12:30 claimed to be an analysis valid
    at 12:30 UTC, a moment four hours away.

    The label is now LT (local time). Converting the value to UTC instead would
    be wrong for a different reason — this stamp *is* the theme's time carrier,
    so a number disagreeing with the quote and the wall clock defeats it — and
    reading the host's real zone abbreviation would make the frame depend on the
    machine's timezone, which is the hazard ``CLOCK_DEPENDENT_THEMES`` exists
    for in the golden suite.
    """

    @staticmethod
    def _stamp_text(time_str: str) -> str:
        captured = {}
        image = rq.Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        draw = ImageDraw.Draw(image)
        real_text = draw.text

        def spy(xy, text="", *args, **kwargs):
            if "VALID" in str(text):
                captured["text"] = text
            return real_text(xy, text, *args, **kwargs)

        draw.text = spy
        rq._synoptic_paint_stamp(draw, 800, 480, time_str)
        return captured.get("text", "")

    @pytest.mark.parametrize("time_str,digits", [
        ("16:30", "1630"), ("00:00", "0000"), ("09:05", "0905"), ("23:59", "2359"),
    ])
    def test_stamp_carries_the_wall_clock_digits(self, time_str, digits):
        assert self._stamp_text(time_str) == f"VALID {digits} LT"

    def test_stamp_never_claims_utc(self):
        """The regression this class exists for."""
        for hour in range(24):
            text = self._stamp_text(f"{hour:02d}:30")
            assert "UTC" not in text, (
                f"the validity stamp reads {text!r} — the clock renders naive LOCAL "
                "time, so a UTC label is false on every appliance outside UTC"
            )

    def test_stamp_is_not_machine_dependent(self):
        """Two renders under different host timezones must be byte-identical.

        The stamp must come from ``time_str`` alone. If it ever reads the host
        clock or zone, this theme's golden fixtures become machine-dependent.
        """
        import os
        import time as _time
        row = make_row(display_quote="It was half past two.", matched_text="half past two",
                       author="Joseph Conrad", title="Typhoon")
        original = os.environ.get("TZ")
        try:
            renders = []
            for zone in ("UTC", "America/New_York", "Asia/Tokyo"):
                os.environ["TZ"] = zone
                if hasattr(_time, "tzset"):
                    _time.tzset()
                renders.append(pixel_bytes(
                    rq.render("16:30", row, 800, 480, mode="production", theme="synoptic")
                ))
            assert renders[0] == renders[1] == renders[2], (
                "the synoptic frame differs between host timezones — something in it "
                "is reading the machine clock instead of the passed time_str"
            )
        finally:
            if original is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = original
            if hasattr(_time, "tzset"):
                _time.tzset()


class TestCardcatalogManila:
    """The manila ground must actually carry both halves of the sepia recipe.

    The first implementation sampled foxing positions on a lattice that aliased
    with the 4-pixel Bayer period of the cream wash painted just above it: every
    candidate position forced ``x % 4 == y % 4``, both surviving diagonal cells
    of the tile sit below the cream threshold, and so all 8000 candidates had
    already been claimed and the foxing pass painted exactly nothing. Nothing
    caught it — the frame still rendered, still snapped on-palette, and still
    passed the preview sweep. Only the eye did.
    """

    def _manila(self):
        image = rq.Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        rq._cardcatalog_paint_manila(image)
        return ink_counts(image)

    def test_cream_wash_is_present_and_stays_a_wash(self):
        counts = self._manila()
        yellow = counts.get(rq.SPECTRA6["yellow"], 0) / 384000.0
        assert 0.08 < yellow < 0.20, (
            f"cream wash covers {yellow:.1%} of the card; the Y+W recipe wants "
            "roughly an eighth — much more reads as a yellow card, much less as white"
        )

    def test_foxing_paints_both_sepia_inks(self):
        counts = self._manila()
        red = counts.get(rq.SPECTRA6["red"], 0)
        green = counts.get(rq.SPECTRA6["green"], 0)
        assert red > 0 and green > 0, (
            f"foxing painted red={red} green={green}; sepia is R+G averaged at "
            "panel distance, so a pass that emits only one ink (or neither) is "
            "not painting sepia at all"
        )

    def test_foxing_stays_sparse(self):
        counts = self._manila()
        sepia = (counts.get(rq.SPECTRA6["red"], 0) + counts.get(rq.SPECTRA6["green"], 0)) / 384000.0
        assert sepia < 0.05, (
            f"foxing covers {sepia:.1%} of the card — a handled catalogue card, "
            "not centuries-old vellum"
        )


class TestCardcatalogDueStamp:
    """The freshest stamp is the theme's time carrier."""

    @pytest.mark.parametrize("time_str,expected", [
        ("00:00", (12, "AM")), ("00:30", (12, "AM")), ("01:00", (1, "AM")),
        ("11:59", (11, "AM")), ("12:00", (12, "PM")), ("12:45", (12, "PM")),
        ("13:00", (1, "PM")), ("14:30", (2, "PM")), ("23:59", (11, "PM")),
    ])
    def test_due_hour_maps_to_twelve_hour_clock(self, time_str, expected):
        assert rq._cardcatalog_due_hour(time_str) == expected

    @pytest.mark.parametrize("bad", ["", "  ", "nonsense", ":", "ab:cd", None])
    def test_due_hour_survives_junk(self, bad):
        hour, meridiem = rq._cardcatalog_due_hour(bad)
        assert 1 <= hour <= 12 and meridiem in ("AM", "PM")

    def test_no_minute_reaches_the_card(self):
        """Only the hour is stamped — a stamped minute would be a digital clock.

        Every minute of an hour must produce the same card, or the stamp has
        started carrying more of the time than a reserve-desk due stamp can.
        """
        row = make_row(display_quote="It was half past two.", matched_text="half past two",
                       author="Joseph Conrad", title="Typhoon")
        frames = {
            pixel_bytes(rq.render(f"14:{minute:02d}", row, 800, 480,
                                  mode="production", theme="cardcatalog"))
            for minute in (0, 15, 30, 45, 59)
        }
        assert len(frames) == 1, (
            "the cardcatalog frame changes with the minute — the due stamp is "
            "meant to carry the hour only, with the minute left to the quote"
        )

    def test_history_always_leaves_room_for_the_due_stamp(self):
        """The current impression must never be pushed off the card.

        The history length is drawn from the row digest, so a bad bound would
        only show up on whichever corpus rows happened to hash high.
        """
        top = rq._CARDCATALOG_STAMP_TOP
        step = rq._CARDCATALOG_STAMP_STEP
        for history in range(3, 2 * (rq._CARDCATALOG_STAMP_ROWS - 1) - 2 + 3):
            row_index = (history + 1) // 2
            bottom = top + row_index * step + rq._CARDCATALOG_STAMP_SIZE[1] + 20
            assert bottom <= 480, (
                f"a {history}-stamp history puts the DUE impression at y={bottom}, "
                "off an 800x480 card"
            )


class TestVhsTapeDate:
    """The burn-in date must come from the quote, never from the machine clock.

    ``synoptic`` shipped a validity stamp labelled UTC while the clock renders
    naive local time; the same class of mistake here — reading ``datetime.now()``
    for the "recorded on" date — would make every vhs golden fixture expire
    overnight and differ between appliances. It is also the wrong reading: the
    date on a camcorder burn-in is when the tape was recorded, not when it is
    being played, so a different quote is a different tape.
    """

    def _row(self, **kwargs):
        return make_row(display_quote="It was half past two.", matched_text="half past two",
                        author="Joseph Conrad", title="Typhoon", **kwargs)

    def test_date_is_a_pure_function_of_the_row(self):
        row = self._row()
        assert rq._vhs_tape_date(row) == rq._vhs_tape_date(dict(row))

    def test_different_quotes_get_different_tapes(self):
        dates = {
            rq._vhs_tape_date(make_row(display_quote=f"It was {word} o'clock.",
                                       matched_text=f"{word} o'clock",
                                       source_id=str(index), line_number=index))
            for index, word in enumerate(
                ("one", "two", "three", "four", "five", "six",
                 "seven", "eight", "nine", "ten", "eleven", "twelve"))
        }
        assert len(dates) > 6, (
            f"twelve distinct quotes produced only {len(dates)} tape dates — the "
            "date is barely varying with the row"
        )

    def test_frame_ignores_the_system_date(self):
        """The regression this class exists for."""
        import datetime as _dt

        row = self._row()
        before = pixel_bytes(rq.render("14:30", row, 800, 480,
                                       mode="production", theme="vhs"))

        class FrozenFuture(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2031, 12, 25, 3, 4, 5)

            @classmethod
            def today(cls):
                return cls(2031, 12, 25)

        original = rq.datetime
        try:
            rq.datetime = FrozenFuture
            after = pixel_bytes(rq.render("14:30", row, 800, 480,
                                          mode="production", theme="vhs"))
        finally:
            rq.datetime = original
        assert before == after, (
            "the vhs frame changed when the system date moved — something in it "
            "is reading the machine clock, which would expire its golden fixture "
            "overnight and make the frame differ between appliances"
        )


class TestVhsChromaBleed:
    """Both chroma records must actually separate, and the tears must spare the text."""

    def _row(self):
        return make_row(display_quote="At half past two Mr. and Mrs. Irving left the house.",
                        matched_text="half past two", author="L. M. Montgomery",
                        title="Anne of Avonlea")

    def test_both_ghosts_reach_the_page(self):
        """Compared against a baseline with the shift disabled, not an absolute count.

        An absolute "is there red / blue on the page" threshold is useless here:
        the tape ground is itself a blue-and-white noise field, so blue clears
        any fixed bar whether or not a single glyph bled. The measurement has to
        be differential.
        """
        row = self._row()
        real = ink_counts(rq.render("14:30", row, 800, 480,
                                    mode="production", theme="vhs"))

        def flat(image, xy, text, font, *, core=None, left=None, right=None,
                 offset=2, ground=None):
            ImageDraw.Draw(image).text(xy, text, font=font, fill=core)

        original = rq.draw_text_chroma_shift
        try:
            rq.draw_text_chroma_shift = flat
            base = ink_counts(rq.render("14:30", row, 800, 480,
                                        mode="production", theme="vhs"))
        finally:
            rq.draw_text_chroma_shift = original

        for ink, side in ((rq.SPECTRA6["red"], "left"), (rq.SPECTRA6["blue"], "right")):
            gained = real.get(ink, 0) - base.get(ink, 0)
            assert gained > 400, (
                f"the {side} chroma ghost added only {gained} pixels over a frame "
                "rendered with the shift disabled — the text is not bleeding, "
                "which is the entire effect"
            )

    def test_core_survives_the_tears(self):
        """A tear must look like the picture slipping, not like the quote deleting.

        Measured as the fraction of scanlines the tears disturb, not as ink lost:
        a tear *shifts* a row rather than erasing it, so pixel counts barely move
        however violent it is — the first version of this test compared white ink
        against an untorn baseline and sat green through a tear pool fourteen
        times too strong.
        """
        row = self._row()
        torn = rq.render("14:30", row, 800, 480, mode="production", theme="vhs")
        original = rq._vhs_apply_tears
        try:
            rq._vhs_apply_tears = lambda image: None
            clean = rq.render("14:30", row, 800, 480, mode="production", theme="vhs")
        finally:
            rq._vhs_apply_tears = original

        top, bottom = 96, 372
        torn_px, clean_px = torn.load(), clean.load()
        disturbed = sum(
            1
            for y in range(top, bottom)
            if any(torn_px[x, y] != clean_px[x, y] for x in range(0, 800, 4))
        )
        fraction = disturbed / (bottom - top)
        assert fraction < 0.2, (
            f"tears disturb {fraction:.0%} of the scanlines crossing the quote; "
            "past a fifth the picture stops reading as slipping and starts "
            "reading as shredded"
        )

    def test_no_chunk_ghost_eats_a_neighbours_core(self):
        """The clean-letterform-centre invariant must hold ACROSS chunk seams.

        A matched phrase splits a line into adjacent styled chunks. Painting
        ghost-then-core per chunk only holds the invariant *within* a chunk: the
        next chunk's left ghost lands on the previous chunk's tail, and the
        ``ground`` guard cannot reject it, because ``ground`` necessarily lists
        every ink the frame paints — the white core included.

        Drives the real ``_vhs_paint_quote`` and compares its cores against the
        same call with the ghosts suppressed; anything the ghost pass ate shows
        up as a core pixel present in the baseline and missing from the render.
        Reimplementing the pass order inside the test would make it a tautology
        that passes against the very bug it guards.

        Swept across offsets rather than pinned at the shipped 2/3, because at
        those the glyph side bearings absorb the reach and the bug is invisible.
        It starts eating cores around 5, so a future "make the bleed stronger"
        tweak is exactly what this guards.
        """
        white = rq.SPECTRA6["white"]
        row = make_row(
            display_quote="At half past two the mm ll bell rang and everybody left.",
            matched_text="half past two", author="L. M. Montgomery", title="Anne of Avonlea")

        def paint(offset, ghosts):
            image = rq.Image.new("RGB", (800, 480), rq.SPECTRA6["black"])
            draw = ImageDraw.Draw(image)
            real = rq.draw_text_chroma_shift

            def maybe_ghostless(img, xy, text, font, *, core=None, left=None,
                                right=None, offset=2, ground=None):
                if not ghosts:
                    left = right = None
                return real(img, xy, text, font, core=core, left=left, right=right,
                            offset=offset, ground=ground)

            original_offset = rq._VHS_CHROMA_OFFSET
            try:
                rq._VHS_CHROMA_OFFSET = offset
                rq.draw_text_chroma_shift = maybe_ghostless
                rq._vhs_paint_quote(image, draw, row)
            finally:
                rq.draw_text_chroma_shift = real
                rq._VHS_CHROMA_OFFSET = original_offset
            return image.load()

        for offset in (2, 3, 5, 8, 12):
            got = paint(offset, ghosts=True)
            want = paint(offset, ghosts=False)
            eaten = sum(
                1
                for y in range(480)
                for x in range(800)
                if want[x, y] == white and got[x, y] != white
            )
            assert eaten == 0, (
                f"at offset={offset}, {eaten} core pixels were overwritten by a "
                "neighbouring chunk's chroma ghost — every ghost on a line must "
                "be laid down before any core, or the letterform centres are "
                "not clean"
            )


class TestFixedGeometryFramesDownscale:
    """Frames built on fixed panel coordinates must downscale, not crop.

    The curator theme grid and the setup wizard both request every theme from
    ``/api/preview`` at 320x192. A frame whose composition is written in
    absolute 800x480 coordinates renders a cropped top-left fragment at that
    size — for ``cardcatalog`` that put the entire stamp column (x=582..770,
    and the theme's time carrier) off the canvas, so the thumbnail could not
    represent the theme at all. ``metro`` established the fix: compose at the
    canonical size, then resample.

    The pre-existing preview sweep cannot see this — it asserts only ``img.size``
    and palette-subset, both of which a cropped fragment satisfies.
    """

    FIXED_GEOMETRY_FRAMES = ("vhs", "cardcatalog", "metro", "bakelite", "intaglio", "nocturne",
                             "plaque", "daguerreotype")

    @pytest.mark.parametrize("theme", FIXED_GEOMETRY_FRAMES)
    @pytest.mark.parametrize("size", [(320, 192), (240, 144), (400, 240)])
    def test_thumbnail_is_a_downscale_of_the_canonical_frame(self, theme, size):
        row = make_row(display_quote="At half past two Mr. and Mrs. Irving left the house.",
                       matched_text="half past two", author="L. M. Montgomery",
                       title="Anne of Avonlea")
        canonical = rq.render("14:30", row, 800, 480, mode="production", theme=theme)
        expected = canonical.resize(size, Image.Resampling.NEAREST)
        actual = rq.render("14:30", row, *size, mode="production", theme=theme)
        assert pixel_bytes(actual) == pixel_bytes(expected), (
            f"{theme} at {size[0]}x{size[1]} is not a downscale of its 800x480 "
            "composition — a frame written in absolute panel coordinates must "
            "compose at the canonical size and resample, or the curator "
            "thumbnail is a cropped fragment"
        )

    @pytest.mark.parametrize("theme", FIXED_GEOMETRY_FRAMES)
    def test_resampling_keeps_the_thumbnail_on_palette(self, theme):
        """NEAREST specifically: an interpolating filter averages adjacent inks.

        Every one of these frames is built from per-pixel stipples, so BILINEAR
        or LANCZOS would invent colours the panel cannot print — and the final
        ``snap_image_to_palette`` runs before the resize, not after.
        """
        row = make_row(display_quote="It was nine o'clock.", matched_text="nine o'clock",
                       author="E. Nesbit", title="The Railway Children")
        thumb = rq.render("09:00", row, 320, 192, mode="production", theme=theme)
        off_palette = distinct_inks(thumb) - set(rq.SPECTRA6.values())
        assert not off_palette, (
            f"{theme} thumbnail carries off-palette colours {sorted(off_palette)} — "
            "the resample filter is blending inks instead of picking them"
        )


class TestBakeliteHourIndex:
    """The console's ``HOUR n/12`` readout carries the hour and only the hour.

    ``bakelite`` surfaces a number, which the rotation's default posture forbids
    — the matched phrase is supposed to be the time carrier. It earns the
    exception the way ``cardcatalog``'s due stamp and ``abyssal``'s depth gauge
    do, by showing a *setting index* rather than a clock reading, and the way to
    keep that honest is mechanical: if a minute could reach the frame, the
    readout would be a clock. So every minute of an hour must render identically
    for a fixed row, and the twelve hours must all differ.
    """

    ROW = make_row(display_quote="At half past two the bell rang and nobody moved.",
                   matched_text="half past two", author="L. M. Montgomery",
                   title="Anne of Avonlea")

    def _frame(self, time_str):
        return pixel_bytes(rq.render(time_str, self.ROW, 800, 480, mode="production", theme="bakelite"))

    def test_no_minute_reaches_the_console(self):
        frames = {self._frame(f"09:{minute:02d}") for minute in range(60)}
        assert len(frames) == 1, (
            "the minute is reaching the bakelite frame — the console shows an hour "
            "index, not a clock reading, and the matched phrase is the time carrier"
        )

    def test_every_hour_renders_differently(self):
        frames = {self._frame(f"{hour:02d}:30") for hour in range(1, 13)}
        assert len(frames) == 12, "two hours render the same console"

    @pytest.mark.parametrize("time_str, expected", [
        ("00:30", 12), ("12:05", 12), ("13:00", 1), ("09:45", 9), ("23:59", 11),
    ])
    def test_hour_index_is_twelve_hour(self, time_str, expected):
        assert rq._bakelite_hour(time_str) == expected

    @pytest.mark.parametrize("value", ["", "nonsense", "::", None])
    def test_a_malformed_time_falls_back_rather_than_raising(self, value):
        assert rq._bakelite_hour(value) == 12


class TestBakelitePhosphorHalo:
    """The glow must hold one hue while its density falls.

    This is the invariant the theme exists to demonstrate and the one that broke
    twice while it was being built: an amber halo is a *synthesised* colour, so
    the ratio between its two inks has to stay put across the whole falloff. Key
    the ratio off anything the density is also keyed off and it collapses — the
    tail goes one colour and the bright ring the other, so the glow changes hue
    as it fades rather than dimming.

    Measured in annular bands out from the stroke, because that is exactly the
    axis the bug runs along; a single figure over the whole halo averages the
    two ends together and comes out at the target while looking wrong.
    """

    YELLOW_SHARE = rq._BAKELITE_HALO_YELLOW

    def _halo_bands(self):
        """Bloom a disc on a black field; return per-annulus (yellow, red) counts.

        A *disc* in *circular* annuli, and both halves of that matter. Blooming
        a rectangle and binning by distance from its edge — the first version of
        this test — samples each band along a straight run at one fixed
        ``y % 8``, so the measurement aliases against the Bayer tile: it reported
        alternating empty bands and shares swinging between 0.14 and 1.00 for a
        halo that was in fact fine. A curved edge crosses every phase of the
        tile, and a 5 px band is wide enough to contain whole tiles.
        """
        image = Image.new("RGB", (200, 200), rq.SPECTRA6["black"])
        mask = Image.new("L", image.size, 0)
        ImageDraw.Draw(mask).ellipse((70, 70, 130, 130), fill=255)
        rq._bakelite_paint_phosphor(image, mask, rq.SPECTRA6["white"], radius=14, cap=0.85)
        pixels = image.load()
        bands: dict[int, list[int]] = {}
        for y in range(200):
            for x in range(200):
                distance = math.hypot(x - 100, y - 100)
                if distance < 32:                     # inside the disc and its rim
                    continue
                band = bands.setdefault(int(distance) // 5, [0, 0])
                if pixels[x, y] == rq.SPECTRA6["yellow"]:
                    band[0] += 1
                elif pixels[x, y] == rq.SPECTRA6["red"]:
                    band[1] += 1
        return bands

    # Wide enough to permit the documented drift in the faintest annulus, where
    # the lit run is too short to hold the fraction exactly (measured 0.47),
    # and still narrow enough to discriminate: the two rejected one-read rules
    # reach 0.51 and 0.33 in this same geometry, and the original two-read bug
    # ran the tail to 1.00.
    TOLERANCE = 0.11

    def test_the_ratio_holds_at_every_distance(self):
        measured = [(d, y, r) for d, (y, r) in sorted(self._halo_bands().items()) if y + r >= 80]
        assert len(measured) >= 3, "too few populated annuli to say anything about drift"
        for distance, yellow, red in measured:
            total = yellow + red
            share = yellow / total
            assert abs(share - self.YELLOW_SHARE) < self.TOLERANCE, (
                f"in annulus {distance} the halo is {share:.2f} yellow "
                f"against a target of {self.YELLOW_SHARE:.3f} — the ink ratio is "
                "tracking the density instead of holding steady, so the glow "
                "changes hue as it fades"
            )

    def test_the_halo_actually_falls_off(self):
        """A ratio test alone passes against a halo that is a solid slab."""
        bands = self._halo_bands()
        populated = sorted(d for d, counts in bands.items() if sum(counts))
        near, far = sum(bands[populated[0]]), sum(bands[populated[-1]])
        assert far < near, f"halo is not fading: {near} px at the stroke, {far} px at the rim"

    def test_the_default_core_is_a_warmer_amber_than_the_halo(self):
        """Core and halo must differ, or a character is just a fat halo."""
        image = Image.new("RGB", (120, 80), rq.SPECTRA6["black"])
        mask = Image.new("L", image.size, 0)
        ImageDraw.Draw(mask).rectangle((40, 30, 80, 50), fill=255)
        rq._bakelite_paint_phosphor(image, mask, radius=6)
        pixels = image.load()
        core = [pixels[x, y] for y in range(31, 50) for x in range(41, 80)]
        share = core.count(rq.SPECTRA6["yellow"]) / len(core)
        assert 0.55 < share < 0.70, (
            f"the amber core is {share:.2f} yellow, expected ~5/8 — solid yellow "
            "reads as pale citrus on this panel and pure halo reads as unlit"
        )


class TestBakeliteTube:
    """The CRT face has to be brown, and brown here is made of scanlines."""

    ROW = make_row(display_quote="At half past two the bell rang.", matched_text="half past two")

    def _tube(self):
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        rq._bakelite_paint_tube(image, rq._bakelite_screen_mask())
        return image

    # Bright centre and vignetted rim. Sampling only the centre is what let the
    # first version of this test pass against a deliberately reintroduced
    # zero-green bug: the tube runs at full density there, so a position-keyed
    # ratio still emits both inks. The defect lives wherever the density is
    # *partial*, which is the whole rim, so a ratio test has to sample it.
    REGIONS = {"centre": (340, 210, 460, 270),
               "lower rim": (60, 380, 190, 435),
               "upper rim": (600, 50, 740, 110)}

    @pytest.mark.parametrize("region", sorted(REGIONS))
    def test_the_field_carries_both_sepia_inks(self, region):
        """The zero-green build rendered maroon under a comment saying brown.

        Keying the green on ``x & 3`` selected the Bayer column the density
        threshold had already rejected, so the two conditions were rarely true
        together and the mix lost most of its second ink wherever the vignette
        bit. Nothing else could see it — the frame still rendered and still
        snapped on-palette.
        """
        counts = ink_counts(self._tube().crop(self.REGIONS[region]))
        red = counts.get(rq.SPECTRA6["red"], 0)
        green = counts.get(rq.SPECTRA6["green"], 0)
        assert green > 0, f"{region}: the tube paints no green at all — maroon, not brown"
        assert 2.0 < red / green < 4.2, (
            f"{region}: tube red:green is {red / green:.1f}:1, expected about 3:1 — "
            "the ratio is tracking the Bayer density instead of holding"
        )

    def test_the_tube_is_scanned_and_not_washed(self):
        """The line structure is the theme's name; a solid brown wash is not it.

        The spacing is asserted as a literal 3 rather than against
        ``_BAKELITE_PITCH``. Deriving it from the constant is what the first
        version did, and that test passes cleanly with the pitch set to 1 — the
        tube fully washed, every row lit, no scanlines at all — because the
        assertion is then vacuously true. A test that reads the value it is
        fencing is not fencing it.
        """
        pixels = self._tube().load()
        lit = sorted(y for y in range(200, 260)
                     if any(pixels[x, y] != rq.SPECTRA6["black"] for x in range(360, 440)))
        assert lit, "no scanlines at all in the middle of the tube"
        assert set(y - x for x, y in zip(lit, lit[1:])) == {3}, (
            f"lit rows {lit} are not on a 3-row pitch — the tube is washed, not scanned"
        )

    def test_the_vignette_darkens_the_rim(self):
        pixels = self._tube().load()
        def lit_share(x0, y0):
            cells = [pixels[x, y] for y in range(y0, y0 + 40) for x in range(x0, x0 + 60)]
            return 1 - cells.count(rq.SPECTRA6["black"]) / len(cells)
        assert lit_share(370, 220) > lit_share(52, 42) * 1.4, (
            "the tube's centre is not meaningfully brighter than its corner"
        )

    def test_every_masked_pixel_is_tube_ink(self):
        """The mask is authoritative: whatever it calls screen must be painted.

        PIL's ``rounded_rectangle`` fills *both* endpoints of its bounding box,
        but the paint loop ran ``range(x0, x1)`` — so the mask's last column and
        row were classified as screen and never painted. The bevel pass then
        skipped them for exactly the same reason, and every render carried a
        1 px line of moulding *inside* the CRT along its right and bottom edges.

        The complement test below could not see it: it checks that nothing
        paints outside the screen, and this is the opposite mistake. Nor could
        the eye at panel distance — the stray line sits precisely where the
        recess bevel puts its white highlight, so it read as part of the
        moulding. Found by review on #225; fenced here in the strongest form,
        over the whole mask rather than at sampled points.
        """
        image = self._tube()
        pixels = image.load()
        mask = rq._bakelite_screen_mask().load()
        tube_inks = {rq.SPECTRA6[name] for name in ("black", "red", "green")}
        stray = [
            (x, y)
            for y in range(480)
            for x in range(800)
            if mask[x, y] >= 128 and pixels[x, y] not in tube_inks
        ]
        assert not stray, (
            f"{len(stray)} pixels inside the screen mask were never painted "
            f"(first at {stray[0]}) — they keep the moulding underneath, which "
            "draws a line of slab colour inside the CRT"
        )

    def test_nothing_paints_outside_the_rounded_screen(self):
        pixels = self._tube().load()
        for x, y in ((0, 0), (799, 0), (0, 479), (799, 479), (48, 38), (400, 20)):
            assert pixels[x, y] == rq.SPECTRA6["white"], (
                f"the tube painted over the moulding at ({x}, {y})"
            )


class TestBakeliteMoulding:
    """The slab is a jittered ordered dither, not a plain Bayer lattice."""

    def _slab(self):
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["black"])
        rq._bakelite_paint_moulding(image)
        return image

    def test_the_jitter_is_actually_applied(self):
        """Without it each Bayer residue maps to exactly one ink — the lattice.

        Dropping the hash term is an easy 'simplification' to make while reading
        this painter, and the result still renders, still snaps on-palette and
        still averages to the right tan; it only reveals itself as a visible
        screen-door texture on the finished panel. So the fence is structural:
        under a plain ordered partition every pixel sharing a residue class
        carries essentially one ink, and under a jittered one most classes carry
        more than one.

        The floor is calibrated against a measured baseline rather than guessed:
        over this window the marbling alone mixes 4 of the 16 classes (a slow
        threshold sweep does cross a boundary here and there), and the shipped
        jitter mixes 11. The classes that stay pure are the extreme ranks, which
        no jitter of this amplitude can carry across a threshold — so the fence
        sits at 8, comfortably above the swirl-only case and below the real one.
        """
        pixels = self._slab().load()
        classes = {}
        for y in range(120, 380):
            for x in range(0, 40):
                classes.setdefault((x % 4, y % 4), set()).add(pixels[x, y])
        mixed = sum(1 for inks in classes.values() if len(inks) > 1)
        assert mixed >= 8, (
            f"only {mixed} of {len(classes)} Bayer residue classes carry more than one "
            "ink — the moulding has fallen back to a plain ordered lattice, which "
            "reads as a screen door on the panel"
        )

    def test_the_slab_is_a_warm_three_ink_tan(self):
        counts = ink_counts(self._slab().crop((0, 100, 40, 400)))
        total = sum(counts.values())
        share = {ink: counts.get(rq.SPECTRA6[ink], 0) / total for ink in ("white", "yellow", "red")}
        assert share["white"] > share["yellow"] > share["red"] > 0.05, (
            f"moulding mix is {share} — white must lead (or the slab reads as a flat "
            "lemon) and red must be present (or it lands on khaki, because the "
            "panel's yellow is a green one)"
        )
        assert counts.get(rq.SPECTRA6["black"], 0) == 0, "the slab is painting black"


class TestIntaglioEngraving:
    """The line-work tone mechanism and the banknote's time-carrier contract.

    ``paint_hatched_tone`` is the theme's reason to exist — tone carried by
    line *weight* at constant pitch — so the fences here are on the mechanism
    (weight tracks the tone field, the darkest passage never saturates, the
    ground guard holds) plus the two premise rules: the denomination carries
    the hour and only the hour, and the serial never derives from the clock.
    """

    ROW = make_row(display_quote="At half past two the bell rang and nobody moved.",
                   matched_text="half past two", author="L. M. Montgomery",
                   title="Anne of Avonlea")

    def _frame(self, time_str):
        return pixel_bytes(rq.render(time_str, self.ROW, 800, 480, mode="production", theme="intaglio"))

    def test_hatch_weight_tracks_tone(self):
        img = Image.new("RGB", (300, 100), rq.SPECTRA6["white"])
        rq.paint_hatched_tone(img, (0, 0, 300, 100), lambda x, y: x / 300.0,
                              33.0, 5.0, rq.SPECTRA6["black"])
        px = img.load()
        thirds = [0, 0, 0]
        for y in range(100):
            for x in range(300):
                if px[x, y] == rq.SPECTRA6["black"]:
                    thirds[x // 100] += 1
        assert thirds[0] < thirds[1] < thirds[2], (
            f"hatch ink per tone third is {thirds} — line weight is not tracking the tone field"
        )
        # The mean tones of the outer thirds are 1/6 and 5/6; the painted-ink
        # ratio should sit in that neighbourhood, not merely be ordered.
        assert thirds[2] > 3 * thirds[0], f"tone contrast collapsed: {thirds}"

    def test_hatch_never_saturates(self):
        img = Image.new("RGB", (120, 120), rq.SPECTRA6["white"])
        rq.paint_hatched_tone(img, (0, 0, 120, 120), lambda x, y: 1.0,
                              33.0, 5.0, rq.SPECTRA6["black"])
        black = ink_counts(img).get(rq.SPECTRA6["black"], 0)
        assert black / (120 * 120) <= 0.85 + 0.05, (
            "a full-tone hatch filled past max_duty — paper must survive between the "
            "lines or the mechanism collapses to flat ink"
        )
        assert ink_counts(img).get(rq.SPECTRA6["white"], 0) > 0

    def test_hatch_respects_ground(self):
        img = Image.new("RGB", (60, 60), rq.SPECTRA6["white"])
        ImageDraw.Draw(img).rectangle((20, 20, 39, 39), fill=rq.SPECTRA6["red"])
        rq.paint_hatched_tone(img, (0, 0, 60, 60), lambda x, y: 1.0,
                              33.0, 5.0, rq.SPECTRA6["black"],
                              ground=frozenset({rq.SPECTRA6["white"]}))
        counts = ink_counts(img.crop((20, 20, 40, 40)))
        assert counts == {rq.SPECTRA6["red"]: 400}, "hatch painted over a non-ground ink"

    def test_roulette_curve_closes_and_stays_dense(self):
        pts = rq._intaglio_roulette_points(0.0, 0.0, 34, 10, 8.0)
        assert abs(pts[0][0] - pts[-1][0]) < 0.01 and abs(pts[0][1] - pts[-1][1]) < 0.01, (
            "the hypotrochoid did not close — the lcm-derived revolution count is wrong"
        )
        reach = (34 - 10) + 8.0 + 0.01
        assert all(x * x + y * y <= reach * reach for x, y in pts), "curve escaped its bound"
        worst = max(math.dist(a, b) for a, b in zip(pts, pts[1:]))
        assert worst <= 1.6, (
            f"max polyline segment is {worst:.2f} px — a coarse roulette leaves dotted "
            "gaps on shallow arcs at width 1"
        )

    def test_denomination_tracks_hour_only(self):
        frames = {self._frame(f"09:{minute:02d}") for minute in (0, 7, 15, 29, 30, 44, 55, 59)}
        assert len(frames) == 1, (
            "two minutes of the same hour rendered differently — a minute is reaching "
            "the intaglio frame, whose only time carrier is the hour denomination"
        )
        hours = {self._frame(f"{hour:02d}:15") for hour in range(1, 13)}
        assert len(hours) == 12, "two different hours produced the same note face"

    def test_serial_is_row_stable_and_never_time_derived(self):
        import re as _re
        serial = rq._intaglio_serial(self.ROW)
        assert _re.fullmatch(r"[A-Z] \d{7} [A-Z]", serial), serial
        assert serial == rq._intaglio_serial(dict(self.ROW)), "serial is not row-stable"
        other = make_row(display_quote="Different row entirely.", matched_text="",
                         source_id="999", line_number=123)
        assert rq._intaglio_serial(other) != serial, "two rows share a serial"


class TestNocturneBrushwork:
    """The flow-field stroke mechanism and the frame's suspended-moment contract.

    Strokes must actually follow the field (or the pass is an expensive
    stipple), the pass must be deterministic (the golden fixture and run_clock's
    dedup depend on it), the gold must stay confined to the lit elements, and —
    the premise rule — no part of ``time_str`` may reach the canvas.
    """

    ROW = make_row(display_quote="At half past two the bell rang and nobody moved.",
                   matched_text="half past two", author="L. M. Montgomery",
                   title="Anne of Avonlea")

    def _render(self, time_str="21:30"):
        return rq.render(time_str, self.ROW, 800, 480, mode="production", theme="nocturne")

    @staticmethod
    def _mean_run(img, ink, axis):
        """Mean length of consecutive painted runs along rows (axis=0) or columns."""
        px = img.load()
        w, h = img.size
        runs, total = 0, 0
        outer, inner = (h, w) if axis == 0 else (w, h)
        for o in range(outer):
            run = 0
            for i in range(inner):
                x, y = (i, o) if axis == 0 else (o, i)
                if px[x, y] == ink:
                    run += 1
                elif run:
                    runs += 1
                    total += run
                    run = 0
            if run:
                runs += 1
                total += run
        return (total / runs) if runs else 0.0

    def test_strokes_follow_the_field(self):
        blue = rq.SPECTRA6["blue"]
        horizontal = Image.new("RGB", (240, 240), rq.SPECTRA6["black"])
        rq.paint_flow_strokes(horizontal, (0, 0, 240, 240), lambda x, y: 0.0,
                              lambda x, y, r: blue if r < 0.5 else None,
                              cell=10, length=20, width=1)
        assert self._mean_run(horizontal, blue, axis=0) >= 3.0 * self._mean_run(horizontal, blue, axis=1), (
            "strokes under a horizontal field are not elongated along it"
        )
        vertical = Image.new("RGB", (240, 240), rq.SPECTRA6["black"])
        rq.paint_flow_strokes(vertical, (0, 0, 240, 240), lambda x, y: math.pi / 2,
                              lambda x, y, r: blue if r < 0.5 else None,
                              cell=10, length=20, width=1)
        assert self._mean_run(vertical, blue, axis=1) >= 3.0 * self._mean_run(vertical, blue, axis=0), (
            "strokes under a vertical field are not elongated along it"
        )

    def test_stroke_pass_is_deterministic_and_salt_decorrelates(self):
        def paint(salt):
            img = Image.new("RGB", (200, 200), rq.SPECTRA6["black"])
            rq.paint_flow_strokes(img, (0, 0, 200, 200), lambda x, y: 0.0,
                                  lambda x, y, r: rq.SPECTRA6["blue"] if r < 0.5 else None,
                                  cell=10, length=20, width=2, salt=salt)
            return pixel_bytes(img)
        assert paint(1) == paint(1), "the stroke pass is not byte-deterministic"
        assert paint(1) != paint(2), "salt does not decorrelate passes"

    def test_water_carries_the_brushwork(self):
        img = Image.new("RGB", (800, 480), rq.SPECTRA6["black"])
        rq._nocturne_paint_strokes(img)
        counts = ink_counts(img.crop((0, rq._NOCTURNE_SHORE[1], 800, 480)))
        painted = counts.get(rq.SPECTRA6["blue"], 0) + counts.get(rq.SPECTRA6["green"], 0)
        assert painted >= 20_000, f"the water pass painted only {painted} px — it has gone sparse"
        sky = ink_counts(img.crop((0, 0, 800, 120))).get(rq.SPECTRA6["blue"], 0) / (800 * 120)
        water = counts.get(rq.SPECTRA6["blue"], 0) / (800 * (480 - rq._NOCTURNE_SHORE[1]))
        assert water > sky, "the water is no denser than the upper sky"

    def test_gold_stays_confined_to_the_lit_elements(self):
        img = self._render()
        px = img.load()
        qx0, qy0, qx1, qy1 = rq._NOCTURNE_QUOTE_RECT
        strays = []
        for y in range(480):
            for x in range(800):
                if px[x, y] not in (rq.SPECTRA6["yellow"], rq.SPECTRA6["red"]):
                    continue
                in_quote = qx0 - 16 <= x <= qx1 + 16 and qy0 - 16 <= y <= qy1 + 16
                in_rocket = 520 <= x <= 800 and 0 <= y <= 262
                in_water = y >= rq._NOCTURNE_SHORE[0] - 6
                in_butterfly = 728 <= x <= 780 and 408 <= y <= 452
                if not (in_quote or in_rocket or in_water or in_butterfly):
                    strays.append((x, y))
        assert not strays, f"gold ink leaked outside the lit elements: {strays[:10]}"

    def test_time_never_reaches_the_canvas(self):
        frames = {pixel_bytes(self._render(t)) for t in ("03:07", "03:52", "09:30", "23:59")}
        assert len(frames) == 1, (
            "two clock times rendered differently — nocturne del-asserts time_str and "
            "the matched phrase alone carries the time"
        )

    def test_quote_bloom_cannot_eat_the_rocket(self, monkeypatch):
        lit = self._render()
        monkeypatch.setattr(rq, "_nocturne_paint_quote", lambda *a, **k: None)
        bare = self._render()
        box = (580, 4, 792, 258)
        assert pixel_bytes(lit.crop(box)) == pixel_bytes(bare.crop(box)), (
            "painting the quote changed the rocket's sparks — the ground fence on the "
            "gold blooms is broken"
        )


class TestPlaqueRelief:
    """The relief-lighting mechanism and the tablet's contracts.

    ``paint_relief_mask`` is the theme's reason to exist — the #226 kill
    criterion was "letters must read as lit metal, not outlined" — so the
    fences are on the lighting geometry (highlight on the lit side, shadow on
    the far side, one light for the whole object), on the ``shade_face``
    lesson, on the claimed forest-teal patina mix, and on the hour-only
    dedication.
    """

    ROW = make_row(display_quote="At half past two the bell rang and nobody moved.",
                   matched_text="half past two", author="L. M. Montgomery",
                   title="Anne of Avonlea")

    def _frame(self, time_str):
        return pixel_bytes(rq.render(time_str, self.ROW, 800, 480, mode="production", theme="plaque"))

    def test_relief_lights_the_correct_sides(self):
        img = Image.new("RGB", (120, 120), rq.SPECTRA6["green"])
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rectangle((40, 40, 79, 79), fill=255)
        rq.paint_relief_mask(img, mask, highlight=rq.SPECTRA6["white"], shadow=rq.SPECTRA6["black"],
                             face=rq.SPECTRA6["yellow"], radius=3, strength=4.0)
        px = img.load()
        white_tl = black_tl = white_br = black_br = 0
        for y in range(120):
            for x in range(120):
                if px[x, y] == rq.SPECTRA6["white"]:
                    if x + y < 120:
                        white_tl += 1
                    else:
                        white_br += 1
                elif px[x, y] == rq.SPECTRA6["black"]:
                    if x + y < 120:
                        black_tl += 1
                    else:
                        black_br += 1
        assert white_tl > 4 * max(1, white_br), (white_tl, white_br)
        assert black_br > 4 * max(1, black_tl), (black_br, black_tl)

    def test_shade_face_false_keeps_the_face_solid(self):
        def interior_inks(shade_face):
            img = Image.new("RGB", (80, 80), rq.SPECTRA6["green"])
            mask = Image.new("L", img.size, 0)
            ImageDraw.Draw(mask).rectangle((30, 10, 49, 69), fill=255)
            rq.paint_relief_mask(img, mask, highlight=rq.SPECTRA6["white"], shadow=rq.SPECTRA6["black"],
                                 face=rq.SPECTRA6["yellow"], radius=2, strength=5.0,
                                 shade_face=shade_face)
            return distinct_inks(img.crop((32, 30, 48, 50)))
        assert interior_inks(False) == {rq.SPECTRA6["yellow"]}, (
            "shade_face=False must leave a thin stroke's interior pure face ink — "
            "shading it is what decayed the first plaque build into grey ghosts"
        )
        assert len(interior_inks(True)) > 1, "shade_face=True should bevel the face"

    def test_relief_respects_ground(self):
        img = Image.new("RGB", (80, 80), rq.SPECTRA6["green"])
        ImageDraw.Draw(img).rectangle((0, 0, 79, 20), fill=rq.SPECTRA6["red"])
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rectangle((20, 24, 59, 59), fill=255)
        rq.paint_relief_mask(img, mask, highlight=rq.SPECTRA6["white"], shadow=rq.SPECTRA6["black"],
                             face=rq.SPECTRA6["yellow"], radius=3, strength=5.0,
                             ground=frozenset({rq.SPECTRA6["green"]}))
        counts = ink_counts(img.crop((0, 0, 80, 21)))
        assert counts == {rq.SPECTRA6["red"]: 80 * 21}, "exterior relief painted over a non-ground ink"

    def test_patina_is_dark_verdigris(self):
        """Half black, the rest green-led blue — verdigris over dark bronze.

        The ground was the catalogue's forest-teal (G+B+Y 40/40/20) for two
        builds. It is dark now because *no* lighter ground can carry text on
        six inks — see ``test_inscription_clears_the_contrast_floor``, which
        is the fence that matters; this one just pins the recipe.
        """
        img = Image.new("RGB", (800, 480), rq.SPECTRA6["green"])
        rq._plaque_paint_patina(img)
        counts = ink_counts(img)
        total = sum(counts.values())
        share = {ink: counts.get(rq.SPECTRA6[ink], 0) / total
                 for ink in ("green", "blue", "yellow", "black")}
        assert 0.45 < share["black"] < 0.55, f"the field is no longer half dark: {share}"
        assert share["green"] > share["blue"], (
            f"blue overtook green: {share} — an even split reads navy rather than "
            "verdigris, because the panel's blue is far more chromatic than its green"
        )
        assert 0.25 < share["green"] < 0.42, share
        assert 0.08 < share["blue"] < 0.25, share
        assert share["yellow"] == 0.0, (
            "yellow is the inscription's ink on this theme; putting it in the ground "
            "is what made the first two builds illegible"
        )

    def test_inscription_clears_the_contrast_floor(self):
        """The fence that matters: the quote must actually be readable.

        Both earlier builds passed every assertion in this class and were still
        hard to read across a room, because nothing measured the one quantity
        legibility is made of. Shipped, the inscription sat at 3.33:1 against
        its ground where WCAG asks 4.5:1 for body text and 3:1 even for large —
        and the ceiling is what makes it decisive: against the old mid-tone
        forest-teal ground, *pure white* reaches only 3.85:1, so no ink and no
        stipple could have rescued it. The ground had to go dark.

        Measured by diffing the frame against a text-free render of the same
        composition, because the inks cannot classify themselves: the old
        ground contained yellow, the same ink as the face, so an ink-based
        split counts ground as text and reports a flattering number. Of the
        differing pixels, the bright ones are the glyph face and the dark ones
        are its relief boundary — crease and core shadow, which aid legibility
        rather than cost it, so the ratio is face against ground.
        """
        row = make_row(display_quote="At half past two the bell rang and nobody moved.",
                       matched_text="half past two", author="L. M. Montgomery",
                       title="Anne of Avonlea")
        full = rq.render("02:30", row, 800, 480, mode="production", theme="plaque")

        bare = Image.new("RGB", (800, 480), rq.SPECTRA6["green"])
        rq._plaque_paint_patina(bare)
        rq._plaque_paint_rim(bare)
        rq._plaque_paint_bolts(bare)
        bare = rq.snap_image_to_palette(bare, rq.SPECTRA6_PALETTE)

        fs, bs = full.load(), bare.load()
        bright = {rq.SPECTRA6["yellow"], rq.SPECTRA6["white"]}
        face, ground = [], []
        x0, y0, x1, y1 = rq._PLAQUE_QUOTE_RECT
        for y in range(y0, y1):
            for x in range(x0, x1):
                if fs[x, y] != bs[x, y]:
                    if fs[x, y] in bright:
                        face.append(_PANEL_INK_BY_RGB[fs[x, y]])
                elif True:
                    ground.append(_PANEL_INK_BY_RGB[bs[x, y]])
        assert len(face) > 5000, f"only {len(face)} face pixels — the quote did not render"

        def mean(px):
            return tuple(sum(q[i] for q in px) / len(px) for i in range(3))

        got = _wcag_contrast(mean(face), mean(ground))
        assert got >= 4.5, (
            f"the inscription reads at {got:.2f}:1 against its ground; WCAG asks 4.5:1 "
            "for body text and this panel is read across a room. Raising the face will "
            "not save a light ground — check the ground's own luminance first."
        )

    def test_no_ink_can_rescue_a_mid_tone_ground(self):
        """Pins *why* the ground is dark, so nobody lightens it back.

        Against the forest-teal this theme used to stand on, the brightest ink
        the panel has still lands under the 4.5:1 floor. The lesson generalises
        past this theme: on six inks a mid-tone ground cannot hold text, and no
        amount of work on the letters changes that.
        """
        teal = _panel_mix({"green": 0.40, "blue": 0.40, "yellow": 0.20})
        best = max(_wcag_contrast(_PANEL_INK[ink], teal) for ink in _PANEL_INK)
        assert best < 4.5, (
            f"the old forest-teal ground now supports {best:.2f}:1 — if the calibration "
            "moved this much, revisit the whole plaque palette rather than trusting it"
        )

    def test_contact_crease_closes_the_glyph_contour(self):
        """Lambert alone leaves the edges *along* the light unshaded.

        A raised form's upper-right and lower-left arcs run parallel to an
        upper-left light, so their gradient is ~0 and the directional pass
        paints nothing there — the form touches the ground with no boundary
        between them. On a mottled ground that is where a letter bleeds into
        the plate. The contact crease is the occlusion line a real relief
        carries all the way round, and this asserts it reaches the corners the
        raking light cannot.
        """
        cx = cy = 45
        radius = 20

        def bare_arc_fraction(contact):
            """How much of the ring just outside a disc keeps the bare ground."""
            img = Image.new("RGB", (90, 90), rq.SPECTRA6["green"])
            mask = Image.new("L", img.size, 0)
            ImageDraw.Draw(mask).ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                                         fill=255)
            rq.paint_relief_mask(img, mask, highlight=rq.SPECTRA6["white"],
                                 shadow=rq.SPECTRA6["black"], face=rq.SPECTRA6["yellow"],
                                 radius=2, strength=3.4, cap=0.6, shade_face=False,
                                 contact=contact, contact_cut=rq._PLAQUE_CONTACT_CUT)
            px = img.load()
            bare = 0
            steps = 360
            for i in range(steps):
                theta = 2 * math.pi * i / steps
                # Walk outward along the ray rather than sampling one rounded
                # radius: the question is whether the contour is closed in this
                # direction, and a single sample answers where the rasteriser
                # put a pixel instead.
                closed = False
                for d in (1.0, 1.5, 2.0, 2.5):
                    x = int(round(cx + (radius + d) * math.cos(theta)))
                    y = int(round(cy + (radius + d) * math.sin(theta)))
                    if px[x, y] != rq.SPECTRA6["green"]:
                        closed = True
                        break
                if not closed:
                    bare += 1
            return bare / steps

        lambert_only = bare_arc_fraction(None)
        creased = bare_arc_fraction(rq.SPECTRA6["black"])
        assert lambert_only > 0.15, (
            f"premise moved: Lambert alone left only {lambert_only:.0%} of the contour open, "
            "so the null arcs this crease exists to close are no longer there"
        )
        assert creased < 0.02, (
            f"the crease left {creased:.0%} of the contour open (Lambert alone: "
            f"{lambert_only:.0%}) — the form still touches the ground somewhere"
        )

    def test_contact_is_off_by_default(self):
        """``contact=None`` must be a byte-level no-op.

        ``paint_relief_mask`` is shared with ``daguerreotype``'s pressed mat
        rings, which want pure Lambert; the crease is a plaque opt-in.
        """
        def render(**kwargs):
            img = Image.new("RGB", (90, 90), rq.SPECTRA6["green"])
            mask = Image.new("L", img.size, 0)
            ImageDraw.Draw(mask).ellipse((25, 25, 64, 64), fill=255)
            rq.paint_relief_mask(img, mask, highlight=rq.SPECTRA6["white"],
                                 shadow=rq.SPECTRA6["black"], face=rq.SPECTRA6["yellow"],
                                 radius=3, strength=4.0, **kwargs)
            return pixel_bytes(img)
        assert render() == render(contact=None), "the default grew a side effect"

    def test_dedication_tracks_hour_only(self):
        frames = {self._frame(f"04:{minute:02d}") for minute in (0, 9, 17, 30, 48, 59)}
        assert len(frames) == 1, (
            "two minutes of the same hour rendered differently — a minute is reaching "
            "the plaque, whose only time device is the ERECTED year's Roman hour"
        )
        hours = {self._frame(f"{hour:02d}:30") for hour in range(1, 13)}
        assert len(hours) == 12, "two different hours produced the same tablet"


class TestDaguerreotypePlate:
    """The Atkinson mechanism (the #227 kill criterion) and the case's rules.

    Atkinson must be *measurably* different from Floyd-Steinberg on the 2-ink
    sub-palette — blown highlights, crushed shadows — or the dithering half of
    the theme's pitch collapses. The case rules: the silver stays achromatic,
    the tarnish stays in its rim annulus, no clock reaches the canvas, and a
    stripped install still gets a photograph-shaped fallback.
    """

    ROW = make_row(display_quote="At half past two the bell rang and nobody moved.",
                   matched_text="half past two", author="L. M. Montgomery",
                   title="Anne of Avonlea")

    def _render(self, time_str="14:15"):
        return rq.render(time_str, self.ROW, 800, 480, mode="production", theme="daguerreotype")

    @staticmethod
    def _ramp():
        img = Image.new("RGB", (256, 64))
        px = img.load()
        for y in range(64):
            for x in range(256):
                px[x, y] = (x, x, x)
        return img

    def _white_frac(self, img, x0, x1):
        counts = ink_counts(img.crop((x0, 0, x1, 64)))
        return counts.get(rq.SPECTRA6["white"], 0) / (64 * (x1 - x0))

    def test_atkinson_blows_highlights_and_crushes_shadows_vs_fs(self):
        ramp = self._ramp()
        pal = [rq.SPECTRA6["white"], rq.SPECTRA6["black"]]
        atk = rq.dither_image_to_palette(ramp, pal, method="atkinson")
        fs = rq.dither_image_to_palette(ramp, pal, method="floyd-steinberg")
        assert self._white_frac(atk, 192, 240) > self._white_frac(fs, 192, 240) + 0.03, (
            "Atkinson's bright end is no whiter than Floyd-Steinberg's — the "
            "discarded-error signature is missing and the theme's pitch collapses"
        )
        assert self._white_frac(atk, 16, 64) < self._white_frac(fs, 16, 64) - 0.03, (
            "Atkinson's dark end is no blacker than Floyd-Steinberg's"
        )

    def test_atkinson_is_deterministic_and_on_palette(self):
        ramp = self._ramp()
        pal = [rq.SPECTRA6["white"], rq.SPECTRA6["black"]]
        a = rq.dither_image_to_palette(ramp, pal, method="atkinson")
        b = rq.dither_image_to_palette(ramp, pal, method="atkinson")
        assert pixel_bytes(a) == pixel_bytes(b)
        assert distinct_inks(a) <= set(pal)

    def test_the_silver_stays_achromatic(self):
        px = self._render().load()
        x0, y0, x1, y1 = rq._DAG_OVAL
        allowed = {rq.SPECTRA6["white"], rq.SPECTRA6["black"]}
        for y in range(y0, y1, 3):
            for x in range(x0, x1, 3):
                if rq._daguerreotype_oval_radial(x, y) < rq._DAG_TARNISH_START - 0.02:
                    assert px[x, y] in allowed, (
                        f"chroma at ({x}, {y}) inside the silver — dithering must run "
                        "against white+black only"
                    )

    def test_tarnish_stays_in_its_annulus(self):
        px = self._render().load()
        for y in range(480):
            for x in range(800):
                if px[x, y] == rq.SPECTRA6["green"]:
                    radial = rq._daguerreotype_oval_radial(x, y)
                    assert rq._DAG_TARNISH_START - 0.02 <= radial <= 1.02, (
                        f"tarnish green at ({x}, {y}), radial {radial:.2f} — outside the rim annulus"
                    )

    def test_time_never_reaches_the_canvas(self):
        frames = {pixel_bytes(self._render(t)) for t in ("03:07", "03:52", "12:00", "23:59")}
        assert len(frames) == 1, (
            "two clock times rendered differently — daguerreotype del-asserts time_str"
        )

    def test_missing_plate_falls_back_gracefully(self, monkeypatch):
        monkeypatch.setattr(rq, "DAGUERREOTYPE_PLATE", rq.BASE_DIR / "assets" / "no_such_plate.png")
        img = self._render()
        counts = ink_counts(img.crop((200, 100, 340, 380)))
        assert counts.get(rq.SPECTRA6["white"], 0) > 0 and counts.get(rq.SPECTRA6["black"], 0) > 0, (
            "the fallback did not paint a photograph-shaped silver image"
        )
