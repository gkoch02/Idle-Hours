"""Smoke tests for the custom-render themes that bypass the standard literary layout.

These themes (``astrarium``, ``diags``, ``marquee``, ``tarot``, ``vinyl``,
``vitrail``, ``outrun``, ``sampler``, ``lieder``, ``izakaya``) each dispatch out of ``render()`` into
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

CUSTOM_THEMES = ("marquee", "tarot", "vinyl", "vitrail", "outrun", "sampler", "lieder", "izakaya", "pride")


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
        buckets = [{} for _ in depths]
        for y in range(0, height, 3):
            for x in range(0, int(depths[-1]) + 1):
                displacement, _ = rq._pride_wave(x, y)
                reach = x + abs((y - displacement) - centre)
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
        layout_stub = {"quote_h": 60, "credits_h": 20, "credits": [("x", None, (0, 0, 10, 10))], "block_w": 200}
        rect = rq._pride_card_rect(layout_stub, 800, 480)
        assert rect[0] >= rq._pride_chevron_tip(800), (
            f"card starts at x={rect[0]}, chevron point is at "
            f"x={rq._pride_chevron_tip(800)} — the card is covering the arrow"
        )
