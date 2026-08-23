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
import threading

import pytest
from PIL import Image, ImageDraw

from idle_hours import render_quote as rq

from .conftest import make_row
from .pixel_helpers import distinct_inks, pixel_bytes

CUSTOM_THEMES = ("marquee", "tarot", "vinyl", "vitrail", "outrun", "sampler", "lieder", "izakaya", "abyssal", "pride", "pulp")


def _on_palette(image: Image.Image) -> bool:
    palette = set(rq.SPECTRA6.values())
    return distinct_inks(image).issubset(palette)


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
