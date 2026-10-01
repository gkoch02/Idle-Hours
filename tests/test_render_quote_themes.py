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
import pathlib
import threading

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from idle_hours import pick_quote as pq
from idle_hours import render_quote as rq
from idle_hours.jsonl_io import iter_jsonl

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


class TestTarotAttributionFitsThePanel:
    """The byline is truncated against the reading panel, not the old card.

    ``_tarot_paint_attribution`` truncated against a literal 470 px, which
    was the inner width of the 520 px card the reading used to sit on. The
    reading is a 444 px panel now, so nine distinct shipped-corpus
    attributions — "Arthur Conan Doyle · The Adventures of Sherlock Holmes"
    among them — fell in the band the old limit left alone and painted
    across the cartouche's red rule onto the cloth. Anything past 470 was
    truncated *to* 470 and overflowed anyway, so the target was wrong and
    not only the threshold.

    Measured on the corpus rather than on invented strings: the failure was
    a real-data one, and a synthetic byline could be picked to miss it.
    """

    @staticmethod
    def _widest_corpus_attributions(limit=6):
        img = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        draw = ImageDraw.Draw(img)
        font = rq.load_font(rq.theme_font_candidates("tarot", "ornament"), size=12)
        scored = []
        for row in iter_jsonl(pathlib.Path(pq.DEFAULT_INPUT_PATH)):
            parts = [p for p in (row.get("author") or "", row.get("title") or "") if p]
            if not parts:
                continue
            text = " · ".join(parts)
            bbox = draw.textbbox((0, 0), text, font=font)
            scored.append((bbox[2] - bbox[0], row))
        scored.sort(key=lambda kv: -kv[0])
        return [row for _, row in scored[:limit]]

    def test_widest_corpus_bylines_stay_inside_the_panel(self):
        rx0, _, rx1, ry1 = rq._TAROT_READING_RECT
        red = rq.SPECTRA6["red"]
        for row in self._widest_corpus_attributions():
            img = rq.render("14:30", dict(row), 800, 480, mode="production", theme="tarot")
            # The panel's own red rule is the boundary. Sample the byline
            # band just inside each vertical rule: only card stock belongs
            # there, so any non-ground ink is the byline having overrun.
            for x in (rx0 + 1, rx0 + 2, rx1 - 2, rx1 - 1):
                for y in range(ry1 - 34, ry1 - 8):
                    px = img.getpixel((x, y))
                    assert px != rq.SPECTRA6["black"], (
                        f"byline ink at ({x}, {y}) is on the panel rule for "
                        f"{row.get('author')} / {row.get('title')}"
                    )
            # And the rule itself is still intact rather than overpainted.
            assert any(
                img.getpixel((rx0, y)) == red for y in range(ry1 - 34, ry1 - 8)
            ), "the panel's left rule was overpainted by the byline"


class TestTarotEmblems:
    """All twelve trumps draw, and draw something different from each other.

    The golden suite pins exactly *one* tarot frame, at ``THEME_SWEEP_TIME``
    (08:55), so eleven of the twelve hours are outside it — a rewrite of
    seven emblems once left every golden fixture byte-identical, because
    hour 8 happened to be one of the four left alone. Twelve more PNG
    fixtures would fence this, but the failures actually worth catching
    are structural: an emblem that stops painting, and two hours that
    resolve to the same figure (a mis-indexed sprite-sheet crop, or a typo
    in the ``_TAROT_EMBLEMS`` dispatch, either of which no smoke test
    notices because both hours still render).

    These run against whichever source is live — the committed Dodal sprite
    sheet when it is present, the polygon painters when it is not — so the
    same three assertions fence both. ``TestTarotPlateFallback`` pins the
    painter path explicitly so it cannot rot behind the plates.
    """

    @staticmethod
    def _panel(hour):
        """The illustration panel's ink, cropped from a rendered card."""
        img = rq.render(f"{hour:02d}:30", make_row(), 800, 480, theme="tarot")
        x0, y0, x1, y1 = rq._TAROT_CARD_RECT
        return img.crop((x0 + 20, y0 + 68, x1 - 20, y1 - 74))

    def test_every_hour_paints_an_emblem(self):
        panels = {hour: self._panel(hour) for hour in range(1, 13)}
        for hour, panel in panels.items():
            counts = ink_counts(panel)
            drawn = counts.get(rq.SPECTRA6["black"], 0) + counts.get(rq.SPECTRA6["red"], 0)
            assert drawn > 600, f"hour {hour}: emblem painted only {drawn} px"

    def test_every_hour_paints_a_distinct_emblem(self):
        seen = {}
        for hour in range(1, 13):
            data = pixel_bytes(self._panel(hour))
            assert data not in seen, f"hour {hour} renders the same emblem as hour {seen[data]}"
            seen[data] = hour

    def test_emblems_stay_inside_the_keyline(self):
        """The clip is what keeps a widened figure off its own frame.

        Six of the twelve reach past the panel once ``_TAROT_EMBLEM_SCALE``
        enlarges them — the Wheel's rim by ~1770 px, as far as the card's
        own border — and a figure crossing its rule reads as a layout
        fault. The stamp is clipped rather than scaled down, so this pins
        the clip and not any emblem's extent.

        The sample band matters and was got wrong first: an earlier
        version looked *below* the panel and only for red, where the
        overflow is overwhelmingly black and sideways, so deleting the
        clip left it green — a test passing against the exact bug it
        guards. The side gutters between the card's inner rule and the
        panel keyline are where the overflow actually lands, and nothing
        else on the card paints there.
        """
        x0, y0, x1, y1 = rq._TAROT_CARD_RECT
        px0, py0, px1, py1 = x0 + 20, y0 + 68, x1 - 20, y1 - 74
        ink = {rq.SPECTRA6["black"], rq.SPECTRA6["red"]}
        for hour in range(1, 13):
            img = rq.render(f"{hour:02d}:30", make_row(), 800, 480, theme="tarot")
            for band in (range(x0 + 8, px0 - 1), range(px1 + 2, x1 - 7)):
                for x in band:
                    for y in range(py0 + 4, py1 - 4):
                        assert img.getpixel((x, y)) not in ink, (
                            f"hour {hour}: emblem ink at ({x}, {y}) is outside the keyline"
                        )


class TestTarotPlateFallback:
    """With no sprite sheet on disk, the polygon painters still draw all twelve.

    Two things need fencing here. The degradation contract: a stripped
    install, or one where the plates were never built, must still render a
    card rather than an empty panel — the same graceful-fallback shape
    ``_load_dithered_plate`` keeps for the dithered themes. And coverage:
    once the plates are committed, every other tarot test exercises the
    sheet, so ~740 lines of emblem painters would be reachable only through
    a code path nothing runs. That is exactly how a fallback quietly stops
    working before anyone needs it.
    """

    @staticmethod
    def _panel(hour, monkeypatch):
        monkeypatch.setattr(rq, "TAROT_PLATES", pathlib.Path("/nonexistent/tarot_plates.png"))
        img = rq.render(f"{hour:02d}:30", make_row(), 800, 480, theme="tarot")
        x0, y0, x1, y1 = rq._TAROT_CARD_RECT
        return img.crop((x0 + 20, y0 + 68, x1 - 20, y1 - 74))

    def test_every_hour_still_paints_without_plates(self, monkeypatch):
        for hour in range(1, 13):
            counts = ink_counts(self._panel(hour, monkeypatch))
            drawn = counts.get(rq.SPECTRA6["black"], 0) + counts.get(rq.SPECTRA6["red"], 0)
            assert drawn > 600, f"hour {hour}: fallback painted only {drawn} px"

    def test_fallback_hours_stay_distinct(self, monkeypatch):
        seen = {}
        for hour in range(1, 13):
            data = pixel_bytes(self._panel(hour, monkeypatch))
            assert data not in seen, f"hour {hour} falls back to the same figure as {seen[data]}"
            seen[data] = hour

    def test_fallback_differs_from_the_plates(self, monkeypatch):
        """If these matched, the fallback would not be under test at all."""
        plated = TestTarotEmblems._panel(9)
        painted = self._panel(9, monkeypatch)
        assert pixel_bytes(plated) != pixel_bytes(painted)


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
        """The card name paints via draw_text_dithered with dark=red +
        light=blue at 0.5 density. Both inks must appear in the name band
        — failing means the dither call regressed to a single solid
        colour."""
        row = make_row(matched_text="half past two")
        img = rq.render("14:30", row, 800, 480, theme="tarot")
        # Derive the name band from the card geometry rather than
        # hardcoding it: the name moved from the head to the foot when
        # the card became portrait, and a literal y-range silently
        # sampled bare card stock afterwards.
        x0, _, x1, y1 = rq._TAROT_CARD_RECT
        counts = {}
        for y in range(y1 - 62, y1 - 34):
            for x in range(x0 + 6, x1 - 6):
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

    def test_trump_name_tables_are_complete(self):
        """Both name tables cover every hour with a non-empty string.

        Two tables because the emblem sources number the deck
        differently — Marseille (the plates) against the Waite-ish
        numbering the polygon painters were drawn to — and a missing
        entry would title a card with the empty string, which paints
        nothing and looks like a rendering fault rather than a bug.
        """
        for table in (rq._TAROT_TRUMP_NAMES, rq._TAROT_PAINTER_TRUMP_NAMES):
            assert set(table) == set(range(1, 13))
            for hour, name in table.items():
                assert isinstance(name, str) and name.strip(), f"hour {hour}"

    def test_the_two_tables_disagree_only_where_the_sources_do(self):
        """Marseille numbers Justice VIII and La Force XI; Waite swaps
        them, and the painters' hour 12 is the World where the plates
        reach only Le Pendu. Those three hours are the whole difference —
        if a fourth appears, one of the tables has drifted rather than
        recording a real numbering difference."""
        differ = {h for h in range(1, 13)
                  if rq._TAROT_TRUMP_NAMES[h] != rq._TAROT_PAINTER_TRUMP_NAMES[h]}
        assert differ == {8, 11, 12}

    @pytest.mark.parametrize("hour", range(1, 13))
    def test_the_emblem_call_names_the_figure_it_drew(self, hour, monkeypatch):
        """``_tarot_paint_emblem`` returns the name of whichever source it
        actually used, so the foot of the card cannot title a Marseille
        plate with a Waite name (or the reverse). Both branches are
        driven — the plate path as shipped, the painter path with the
        sheet pointed at nothing."""
        canvas = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        draw = ImageDraw.Draw(canvas)
        assert rq._tarot_paint_emblem(canvas, draw, hour, 160, 240) == rq._TAROT_TRUMP_NAMES[hour]

        # The sheet is memoised on a module-level dict, but the existence
        # check runs first, so pointing TAROT_PLATES at nothing takes the
        # fallback branch without touching that cache.
        monkeypatch.setattr(rq, "TAROT_PLATES", pathlib.Path("/nonexistent/tarot_plates.png"))
        canvas = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        draw = ImageDraw.Draw(canvas)
        assert (rq._tarot_paint_emblem(canvas, draw, hour, 160, 240)
                == rq._TAROT_PAINTER_TRUMP_NAMES[hour])

    @pytest.mark.parametrize("hour", range(1, 13))
    def test_the_foot_carries_the_emblems_own_name(self, hour, monkeypatch):
        """The frame titles the card with whatever the emblem call
        returned — not with a name it looked up for itself. Asserting the
        wiring rather than the pixels is the point: a second lookup in the
        frame would pass every visual check while being exactly the drift
        the return value exists to prevent."""
        seen = []
        monkeypatch.setattr(
            rq, "_tarot_paint_card_name",
            lambda image, draw, name, rect, y_top: seen.append(name),
        )
        rq.render(f"{hour:02d}:20", make_row(), 800, 480, theme="tarot")
        assert seen == [rq._TAROT_TRUMP_NAMES[hour]]

    @pytest.mark.parametrize("hour", range(1, 13))
    def test_no_trump_name_overruns_the_card(self, hour):
        """Every name stays inside the card's inner rule.

        The band held ``matched_text`` before this, and the longest time
        phrases ran off the card entirely — "TWENTY MINUTES PAST ONE" was
        the reported failure. The names are shorter but not short: "THE
        WHEEL OF FORTUNE" is 300 px at the top size against a 260 px
        card, so it is the fit loop and not the content that keeps this
        true, and a widened size range would break it silently.

        Measured in *blue* only. The vellum's foxing scatters red across
        the whole cloth, so a red-inclusive sample reports the canvas
        width for every hour and passes whatever the name does.
        """
        img = rq.render(f"{hour:02d}:20", make_row(), 800, 480, theme="tarot")
        x0, _, x1, y1 = rq._TAROT_CARD_RECT
        px = img.load()
        xs = [x for x in range(0, x1 + 30)
              for y in range(y1 - 66, y1 - 28)
              if px[x, y] == rq.SPECTRA6["blue"]]
        assert xs, f"hour {hour}: no card name painted"
        assert min(xs) >= x0 + 6 and max(xs) <= x1 - 6, (
            f"hour {hour}: name spans {min(xs)}..{max(xs)}, "
            f"outside the card's {x0 + 6}..{x1 - 6}"
        )

    def test_nothing_from_the_quote_row_reaches_the_card(self):
        """The card is a function of the hour alone.

        This is the regression itself: the foot used to be painted from
        ``matched_text``, so the card announced the time under a picture
        of the Magician — a thing no trump does, and a second copy of
        what the reading beside it already says. Comparing the whole card
        region across two unrelated rows at the same hour fences the
        principle rather than the one field, so a future "put the author
        on the card" would fail here too.
        """
        a = make_row(matched_text="half past two", display_quote="One quote entirely.",
                     author="A", title="B")
        b = make_row(matched_text="twenty minutes past one",
                     display_quote="A different quote entirely.", author="C", title="D")
        x0, y0, x1, y1 = rq._TAROT_CARD_RECT
        crops = [
            rq.render("14:30", row, 800, 480, theme="tarot").crop((x0, y0, x1 + 1, y1 + 1))
            for row in (a, b)
        ]
        assert pixel_bytes(crops[0]) == pixel_bytes(crops[1])


class TestVinylFrame:
    """Turntable + LP back-cover — tonearm angle math + catalog number."""

    @staticmethod
    def _stylus_centroid(img):
        """Centroid of the red stylus pin, in disc-centre coordinates.

        The only red inside the programme band is the cartridge's stylus
        pin: the label is red but sits inside ``_VINYL_LABEL_R``, and the
        counterweight ring is outside the disc entirely.
        """
        cx, cy = rq._VINYL_DISK_CX, rq._VINYL_DISK_CY
        r_outer, r_label = rq._VINYL_DISK_R, rq._VINYL_LABEL_R
        red = rq.SPECTRA6["red"]
        xs, ys = [], []
        for y in range(cy - r_outer, cy + r_outer + 1):
            for x in range(cx - r_outer, cx + r_outer + 1):
                r = math.hypot(x - cx, y - cy)
                if not r_label + 4 < r <= r_outer:
                    continue
                if img.getpixel((x, y)) == red:
                    xs.append(x)
                    ys.append(y)
        assert xs, "no stylus pin found on the programme band"
        return sum(xs) / len(xs), sum(ys) / len(ys)

    def test_stylus_tracks_inward_across_the_hour(self):
        """The minute drives the stylus *radius*, outside-in.

        A record plays from the outer edge toward the run-out, so the
        stylus creeps inward over the hour. An earlier revision swept the
        cartridge a full 360 degrees around the *rim* at the minute's
        clock angle, which no tonearm does — it read as a scratch across
        the record rather than as an arm — so this pins the direction of
        travel, not a set of cardinal positions.
        """
        cx, cy = rq._VINYL_DISK_CX, rq._VINYL_DISK_CY
        radii = []
        for minute in (0, 15, 30, 45, 59):
            img = rq.render(f"11:{minute:02d}", make_row(), 800, 480, theme="vinyl")
            sx, sy = self._stylus_centroid(img)
            radii.append(math.hypot(sx - cx, sy - cy))
        # Strictly decreasing, not merely non-increasing: a stylus pinned
        # to the rim gives a constant radius, which "sorted(reverse=True)"
        # accepts — and a rim-pinned stylus is precisely the bug here.
        assert all(b < a for a, b in zip(radii, radii[1:])), f"stylus did not track inward: {radii}"
        assert radii[0] - radii[-1] > 20, "stylus barely moved across the hour"

    def test_stylus_stays_on_the_programme_band(self):
        """Never off the edge of the record, never onto the label."""
        cx, cy = rq._VINYL_DISK_CX, rq._VINYL_DISK_CY
        for minute in range(0, 60, 7):
            img = rq.render(f"11:{minute:02d}", make_row(), 800, 480, theme="vinyl")
            sx, sy = self._stylus_centroid(img)
            r = math.hypot(sx - cx, sy - cy)
            assert rq._VINYL_LABEL_R < r <= rq._VINYL_DISK_R, f"minute {minute}: r={r:.1f}"

    def test_arm_length_is_constant(self):
        """The stylus stays one arm's length from the bearing.

        This is the invariant that separates a pivoted arm from a point
        placed at an angle: the tip may swing, but its distance from the
        pivot cannot change. Reading the two ratios off the module is
        reading constants, not reimplementing the two-circle solve the
        painter runs.
        """
        cx, cy, r_outer = rq._VINYL_DISK_CX, rq._VINYL_DISK_CY, rq._VINYL_DISK_R
        pivot_x, pivot_y = rq._vinyl_tonearm_pivot(cx, cy, r_outer)
        expected = r_outer * rq._VINYL_ARM_LENGTH_RATIO
        for minute in (0, 20, 40, 59):
            img = rq.render(f"11:{minute:02d}", make_row(), 800, 480, theme="vinyl")
            sx, sy = self._stylus_centroid(img)
            reach = math.hypot(sx - pivot_x, sy - pivot_y)
            assert abs(reach - expected) < 6, f"minute {minute}: reach={reach:.1f} vs {expected:.1f}"

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
                             "plaque", "daguerreotype", "autochrome", "photo", "tarot", "vinyl",
                             "control", "observation", "trisolaris", "biomech", "codex",
                             "culture", "orbital", "furies", "bosch", "saros")

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


class TestBetweenUs:
    """``betweenus`` / ``betweenus_dark`` — the Between Us app's paper card.

    The two variants share one painter and differ only in ground, ink and
    the recipes the legend and outline take, so most assertions run for both.
    What is pinned here: the registration checklist, the ornament-skip, the
    day-progress bar as the sole time carrier (fills with the clock, empty on
    the registry path, never a digit), the daypart pill's vocabulary, the
    card being the one clean surface on a stippled page, the shadow on each
    ground, the legend's five tiers, the dark variant's amber reroute, and
    the Fraunces instance pin — the file's default axis instance is Black, so
    an unpinned load is a real regression, not a cosmetic one.
    """

    THEMES = ("betweenus", "betweenus_dark")

    @staticmethod
    def _row():
        return make_row(
            display_quote="Do you think I should be standing here at five minutes to nine "
                          "looking for it if I had it in my pocket all the while?",
            matched_text="five minutes to nine",
            author="Arthur Conan Doyle",
            title="The Adventures of Sherlock Holmes",
            quality_score=90,
            bucket="h9_five_to",
            resolved_bucket="h9_five_to",
        )

    @pytest.mark.parametrize("theme", THEMES)
    def test_registered_everywhere(self, theme):
        from idle_hours import display_inky
        assert theme in rq.THEMES
        assert theme in rq.THEME_ORDER
        assert theme in rq.THEME_FONTS
        assert rq._BORDER_PAINTERS.get(theme) is rq.draw_betweenus_border
        assert theme in display_inky.THEME_SATURATION
        assert theme in rq._DEBUG_LABEL_RIGHT_INSET
        assert theme in rq._THEMES_WITHOUT_ORNAMENT_MARKS

    def test_palette_shapes(self):
        light = rq.THEMES["betweenus"]
        dark = rq.THEMES["betweenus_dark"]
        assert light["page_bg"] == rq.SPECTRA6["white"]
        assert light["text"] == rq.SPECTRA6["black"]
        assert light["accent"] == rq.SPECTRA6["red"], "light paints the italic phrase in solid terracotta red"
        assert dark["page_bg"] == rq.SPECTRA6["black"]
        assert dark["text"] == rq.SPECTRA6["white"]
        assert dark["accent"] == rq.SPECTRA6["yellow"], "dark's accent is the amber sentinel"
        from idle_hours import display_inky
        assert display_inky.THEME_SATURATION["betweenus"] == 0.5
        assert display_inky.THEME_SATURATION["betweenus_dark"] == 0.7

    @pytest.mark.parametrize("theme", THEMES)
    def test_no_ornament_marks_are_painted(self, theme, monkeypatch):
        """The app has no quotation-mark ornaments; the marks are skipped, not
        painted invisibly (a page_bg glyph would ghost the paper wash)."""
        def boom(*args, **kwargs):
            raise AssertionError("an ornament mark was painted")
        monkeypatch.setattr(rq, "draw_faux_gray_text", boom)
        monkeypatch.setattr(rq, "draw_faux_3way_text", boom)
        rq.render("08:55", self._row(), 800, 480, mode="production", theme=theme)

    @pytest.mark.parametrize("theme", THEMES)
    def test_render_is_deterministic(self, theme):
        a = pixel_bytes(rq.render("08:55", self._row(), 800, 480, mode="production", theme=theme))
        b = pixel_bytes(rq.render("08:55", self._row(), 800, 480, mode="production", theme=theme))
        assert a == b

    @pytest.mark.parametrize("theme", THEMES)
    def test_frame_stays_on_palette_at_every_size(self, theme):
        allowed = set(rq.SPECTRA6.values())
        for size in ((80, 60), (240, 144), (320, 192), (800, 480)):
            for mode in ("production", "debug", "card"):
                img = rq.render("08:55", self._row(), *size, mode=mode, theme=theme)
                assert img.size == size
                assert distinct_inks(img) <= allowed, (theme, size, mode)

    # -- the day-progress bar ------------------------------------------------

    @pytest.mark.parametrize("time_str,expected", [
        ("00:00", 0.0), ("06:00", 0.25), ("12:00", 0.5), ("18:00", 0.75), ("23:59", 1439 / 1440),
    ])
    def test_day_fraction(self, time_str, expected):
        assert rq._betweenus_day_fraction(time_str) == pytest.approx(expected)

    def test_day_fraction_is_defensive(self):
        assert rq._betweenus_day_fraction(None) == 0.0
        assert rq._betweenus_day_fraction("") == 0.0
        assert rq._betweenus_day_fraction("nonsense") == 0.0

    @staticmethod
    def _bar_fill_width(image) -> int:
        """Count columns of the track carrying fill ink (red / yellow).

        Restricted to the track's own span, inset past its rounded ends — the
        paper outside it carries yellow wash specks that are not fill."""
        px = image.load()
        y = rq._BETWEENUS_BAR_TOP + rq._BETWEENUS_BAR_HEIGHT // 2
        fill = {rq.SPECTRA6["red"], rq.SPECTRA6["yellow"]}
        x0 = rq._BETWEENUS_MARGIN + 3
        x1 = image.width - rq._BETWEENUS_MARGIN - 3
        return sum(1 for x in range(x0, x1) if px[x, y] in fill)

    @pytest.mark.parametrize("theme", THEMES)
    def test_bar_fills_with_the_clock(self, theme):
        """The fill length is the fraction of the day elapsed — the one thing
        on the page that moves with ``time_str``."""
        widths = [
            self._bar_fill_width(rq.render(t, self._row(), 800, 480, mode="production", theme=theme))
            for t in ("00:05", "06:00", "12:00", "18:00", "23:55")
        ]
        assert widths == sorted(widths) and widths[0] < widths[-1], widths
        track = 800 - 2 * rq._BETWEENUS_MARGIN
        assert abs(widths[2] - track / 2) < 12, f"noon should fill about half the track: {widths[2]} of {track}"

    @pytest.mark.parametrize("theme", THEMES)
    def test_registry_path_draws_an_empty_track(self, theme):
        """The ``_BORDER_PAINTERS`` contract carries no clock, so the source
        card / goodnight frame get the track with no fill and no pill."""
        image = Image.new("RGB", (800, 480), rq.THEMES[theme]["page_bg"])
        rq._BORDER_PAINTERS[theme](image, rq.THEMES[theme])
        assert self._bar_fill_width(image) == 0

    def test_fill_is_gold_at_the_left_and_tangerine_at_the_leading_edge(self):
        """The app's ``curious → want`` gradient: the yellow share of the fill
        falls from the left end to the leading edge."""
        image = rq.render("23:55", self._row(), 800, 480, mode="production", theme="betweenus")
        px = image.load()
        x0 = rq._BETWEENUS_MARGIN
        x1 = 800 - rq._BETWEENUS_MARGIN
        ys = range(rq._BETWEENUS_BAR_TOP, rq._BETWEENUS_BAR_TOP + rq._BETWEENUS_BAR_HEIGHT)

        def yellow_share(xa, xb):
            inks = [px[x, y] for x in range(xa, xb) for y in ys]
            inks = [c for c in inks if c in (rq.SPECTRA6["red"], rq.SPECTRA6["yellow"])]
            return sum(1 for c in inks if c == rq.SPECTRA6["yellow"]) / len(inks)

        assert yellow_share(x0 + 8, x0 + 88) > yellow_share(x1 - 88, x1 - 8) + 0.12

    # -- the daypart pill -----------------------------------------------------

    @pytest.mark.parametrize("time_str,label", [
        ("00:10", "Midnight"), ("02:00", "Night"), ("05:30", "Dawn"), ("09:00", "Morning"),
        ("12:00", "Noon"), ("15:00", "Afternoon"), ("18:30", "Dusk"), ("21:00", "Evening"),
        ("23:30", "Night"), (None, None), ("", None), ("bad", None),
    ])
    def test_daypart_label_uses_the_corpus_vocabulary(self, time_str, label):
        assert rq._betweenus_daypart_label(time_str) == label

    def test_pill_carries_the_daypart(self):
        captured = []
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        draw = ImageDraw.Draw(image)
        real_text = draw.text

        def spy(xy, text="", *args, **kwargs):
            captured.append(str(text))
            return real_text(xy, text, *args, **kwargs)

        draw.text = spy
        rq._betweenus_paint_brand_row(image, draw, rq.THEMES["betweenus"], False, "Afternoon")
        assert captured == ["Between ", "Us", "Afternoon"]

    def test_debug_label_clears_the_pill(self):
        """The pill sits in the y=14..38 band top-right, so the DEBUG MODE
        banner is pushed inward past it. Pin the inset against the widest
        label the pill can carry."""
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        draw = ImageDraw.Draw(image)
        widest = max(rq._BETWEENUS_DAYPART_LABELS.values(), key=lambda s: draw.textlength(
            s, font=rq.load_font([(rq.INTER_VARIABLE, "Medium"), *rq.META_FONT_CANDIDATES], size=13)))
        rq._betweenus_paint_brand_row(image, draw, rq.THEMES["betweenus"], False, widest)
        px = image.load()
        pill_left = min(x for x in range(400, 800) for y in range(14, 39) if px[x, y] != rq.SPECTRA6["white"])
        assert 800 - rq._DEBUG_LABEL_RIGHT_INSET["betweenus"] <= pill_left, (
            f"pill starts at x={pill_left} but the debug label may run to "
            f"x={800 - rq._DEBUG_LABEL_RIGHT_INSET['betweenus']}"
        )

    # -- card, shadow, paper --------------------------------------------------

    @pytest.mark.parametrize("theme", THEMES)
    def test_card_is_the_one_clean_surface(self, theme):
        """Inside the body knockout the ground is flat page_bg (no wash
        specks); outside it the paper carries its wash."""
        ground = rq.THEMES[theme]["page_bg"]
        image = Image.new("RGB", (800, 480), ground)
        rq.draw_betweenus_border(image, rq.THEMES[theme], clear_rect=(100, 120, 700, 400), time_str="10:00")
        px = image.load()
        inside = {px[x, y] for x in range(140, 660, 3) for y in range(160, 360, 3)}
        assert inside == {ground}, f"{theme}: card interior is not flat page_bg: {inside}"
        margin = {px[x, y] for x in range(30, 770, 2) for y in range(60, 100, 2)}
        assert margin - {ground}, f"{theme}: the paper above the card carries no wash"

    def test_light_card_casts_a_soft_shadow_down_and_right(self):
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        rq.draw_betweenus_border(image, rq.THEMES["betweenus"], clear_rect=(100, 120, 700, 400))
        px = image.load()
        black = rq.SPECTRA6["black"]

        def black_share(xa, xb, ya, yb):
            cells = [(x, y) for x in range(xa, xb) for y in range(ya, yb)]
            return sum(1 for x, y in cells if px[x, y] == black) / len(cells)

        # The card's edge outline is R+G sepia, never black, so any black here is the shadow.
        below = black_share(300, 500, 402, 409)
        right = black_share(702, 709, 200, 300)
        far = black_share(300, 500, 430, 440)
        assert below > 0.12 and right > 0.12, (below, right)
        assert far < below / 3, "the shadow should fall off within a few pixels"

    def test_dark_card_sits_in_a_clean_halo(self):
        """Dark cannot cast black on near-black, so the wash is cleared around
        the card instead: the ring just outside the edge carries no specks."""
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["black"])
        rq.draw_betweenus_border(image, rq.THEMES["betweenus_dark"], clear_rect=(100, 120, 700, 400))
        px = image.load()
        ring = {px[x, y] for x in range(300, 500) for y in range(402, 406)}
        assert ring == {rq.SPECTRA6["black"]}, ring
        far = {px[x, y] for x in range(300, 500) for y in range(440, 470)}
        assert far - {rq.SPECTRA6["black"]}, "the wash should return past the halo"

    def test_light_paper_warms_toward_the_foot(self):
        """The app's paper → paper2 gradient: more cream at the bottom."""
        paper = rq._betweenus_paper(800, 480, dark=False)
        counts_top = ink_counts(paper.crop((0, 0, 800, 60)))
        counts_bottom = ink_counts(paper.crop((0, 420, 800, 480)))
        yellow = rq.SPECTRA6["yellow"]
        assert counts_bottom.get(yellow, 0) > 2 * counts_top.get(yellow, 0)
        assert set(counts_top) | set(counts_bottom) <= {rq.SPECTRA6["white"], yellow}

    def test_dark_paper_is_warm_and_sparse(self):
        paper = rq._betweenus_paper(800, 480, dark=True)
        counts = ink_counts(paper)
        total = 800 * 480
        assert 0.02 < counts.get(rq.SPECTRA6["red"], 0) / total < 0.08
        assert 0 < counts.get(rq.SPECTRA6["white"], 0) / total < 0.02
        assert set(counts) <= {rq.SPECTRA6["black"], rq.SPECTRA6["red"], rq.SPECTRA6["white"]}

    def test_paper_is_cached_per_geometry(self):
        rq._BETWEENUS_PAPER_CACHE.clear()
        a = rq._betweenus_paper(240, 144, dark=False)
        b = rq._betweenus_paper(240, 144, dark=False)
        assert a is not b, "callers get a copy, never the cached surface"
        assert pixel_bytes(a) == pixel_bytes(b)
        assert (240, 144, False) in rq._BETWEENUS_PAPER_CACHE

    def test_paper_cache_is_bounded_lru(self):
        """The geometry is caller-controlled — ``/api/preview`` is ungated and
        takes any size up to 800x480 — so an unbounded cache is a memory sink
        an unauthenticated client can fill at ~1.1 MB per distinct size. The
        cache holds a few entries and evicts the least recently used."""
        rq._BETWEENUS_PAPER_CACHE.clear()
        limit = rq._BETWEENUS_PAPER_CACHE_MAX
        native = (800, 480, False)
        rq._betweenus_paper(*native)
        for i in range(limit * 3):
            rq._betweenus_paper(*native)               # keep the panel size hot
            rq._betweenus_paper(80 + i, 60 + i, True)  # a stream of one-off sizes
            assert len(rq._BETWEENUS_PAPER_CACHE) <= limit
        assert native in rq._BETWEENUS_PAPER_CACHE, "a reused geometry must survive the churn"
        assert (80, 60, True) not in rq._BETWEENUS_PAPER_CACHE, "the oldest one-off must be evicted"

    # -- legend ---------------------------------------------------------------

    def test_legend_surfaces_every_tier_ink(self):
        """Five tiers: light = red, R+Y tangerine, K+W stone, Y+R gold, black."""
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        rq._betweenus_paint_legend(image, ImageDraw.Draw(image), rq.THEMES["betweenus"], False)
        foot = image.crop((0, 480 - rq._BETWEENUS_LEGEND_RISE - 8, 800, 480 - rq._BETWEENUS_LEGEND_RISE + 8))
        inks = distinct_inks(foot)
        for name in ("red", "yellow", "black", "white"):
            assert rq.SPECTRA6[name] in inks, f"legend is missing {name}"

    def test_no_tier_paints_the_green_ink(self):
        """``limit`` is a near-neutral slate, not a green (#257).

        ``Theme.swift`` names it "slate green" but measures #5D6B66 — chroma
        0.055 — where the panel's green ink is fully saturated, so painting
        the name rather than the measurement put an unmistakably green chip
        on the plate. Asserted on the recipes AND on the canvas, because the
        dots are the only thing on this page that could reach for green and
        a table-only check would miss a hardcoded fill.
        """
        for label, light, dark in rq._BETWEENUS_LEGEND:
            assert "green" not in light, (label, light)
            assert "green" not in dark, (label, dark)
        for variant, dark_flag in (("betweenus", False), ("betweenus_dark", True)):
            image = Image.new("RGB", (800, 480), rq.SPECTRA6["black" if dark_flag else "white"])
            rq._betweenus_paint_legend(image, ImageDraw.Draw(image), rq.THEMES[variant], dark_flag)
            assert rq.SPECTRA6["green"] not in distinct_inks(image), variant

    def test_hard_no_sits_at_the_achromatic_extreme_stone_does_not(self):
        """Both tiers are neutral, so they must differ by lightness or merge."""
        recipes = dict((label, (light, dark)) for label, light, dark in rq._BETWEENUS_LEGEND)
        assert recipes["Hard No"][0] == ("black", None, 0.0)
        assert recipes["Hard No"][1] == ("white", None, 0.0)
        assert recipes["Neutral"] == (("black", "white", 0.5), ("black", "white", 0.5))

    def test_legend_labels_are_the_apps_five_answers(self):
        assert [label for label, _, _ in rq._BETWEENUS_LEGEND] == [
            "Love it", "Like it", "Neutral", "Curious", "Hard No",
        ]

    def test_dark_legend_lifts_every_tint_with_white_or_yellow(self):
        """The app's dark set lightens its accents rather than inverting them.

        A tier may satisfy this either by mixing white or yellow into its
        light ink at half share or more, or — as ``limit`` does — by landing
        on solid white outright, which is the same lightening taken all the
        way rather than an exception to it.
        """
        for label, _light, dark in rq._BETWEENUS_LEGEND:
            lifted = dark[0] == "white" or (dark[1] in ("white", "yellow") and dark[2] >= 0.5)
            assert lifted, (label, dark)

    # -- text -----------------------------------------------------------------

    def test_dark_matched_phrase_is_amber(self):
        """The yellow sentinel reroutes to R+Y 1:1 — roughly half red, half yellow."""
        image = Image.new("RGB", (400, 100), rq.SPECTRA6["black"])
        draw = ImageDraw.Draw(image)
        font = rq.load_font(rq.theme_font_candidates("betweenus_dark", "quote_bold"), size=40)
        rq._draw_text_body(image, draw, (10, 20), "five minutes to nine", font=font, fill=rq.SPECTRA6["yellow"], theme="betweenus_dark")
        counts = ink_counts(image)
        red = counts.get(rq.SPECTRA6["red"], 0)
        yellow = counts.get(rq.SPECTRA6["yellow"], 0)
        assert red and yellow
        assert 0.35 < red / (red + yellow) < 0.65

    def test_light_matched_phrase_is_solid_red(self, monkeypatch):
        """Light paints the italic phrase solid — no stipple seam fires."""
        def boom(*args, **kwargs):
            raise AssertionError("light betweenus must not stipple its matched phrase")
        monkeypatch.setattr(rq, "draw_text_dithered", boom)
        image = Image.new("RGB", (400, 100), rq.SPECTRA6["white"])
        draw = ImageDraw.Draw(image)
        font = rq.load_font(rq.theme_font_candidates("betweenus", "quote_bold"), size=40)
        rq._draw_text_body(image, draw, (10, 20), "five minutes to nine", font=font, fill=rq.SPECTRA6["red"], theme="betweenus")
        snapped = rq.snap_image_to_palette(image, rq.SPECTRA6_PALETTE)
        assert ink_counts(snapped).get(rq.SPECTRA6["red"], 0) > 500

    def test_matched_phrase_is_the_italic_cut(self):
        """"say *what you want.*" — the app's accent is italic, not bold."""
        for theme, instance in (("betweenus", "Italic"), ("betweenus_dark", "SemiBold Italic")):
            entry = rq.THEME_FONTS[theme]["quote_bold"][0]
            assert entry == (rq.FRAUNCES_ITALIC_VARIABLE, instance)
            assert rq.THEME_FONTS[theme]["quote_regular"][0] == (rq.FRAUNCES_VARIABLE, "Regular")

    def test_fraunces_instances_are_pinned_off_the_black_default(self):
        """Fraunces' default axis instance is wght 900. An unpinned load renders
        the body as a display black, so measure the Regular against the raw
        default and require it to be visibly lighter."""
        from PIL import ImageFont
        rq._FONT_CACHE.clear()
        pinned = rq.load_font([(rq.FRAUNCES_VARIABLE, "Regular")], size=48)
        raw = ImageFont.truetype(rq.FRAUNCES_VARIABLE, size=48)

        def coverage(font):
            img = Image.new("L", (600, 80), 0)
            ImageDraw.Draw(img).text((5, 5), "Between Us", font=font, fill=255)
            return sum(img.histogram()[128:])

        assert coverage(pinned) < 0.75 * coverage(raw), "Regular instance was not applied"
        assert pinned.getname()[0].startswith("Fraunces")

    def test_fraunces_files_and_licence_ship(self):
        from pathlib import Path
        for path in (rq.FRAUNCES_VARIABLE, rq.FRAUNCES_ITALIC_VARIABLE):
            assert Path(path).exists(), path
        assert (Path(rq.FRAUNCES_VARIABLE).parent / "OFL.txt").exists()


class TestGrimoireMatchedPhrase:
    """``grimoire``'s matched phrase is sky blue (B+W 1:1), matching its ornaments.

    History worth keeping, because this seam has now moved twice. It began as
    the "candlelit" 3/4-red mix, which read as dim rather than warm at panel
    distance against the black ground. The fix at the time was solid white —
    which cured the dimness but left the phrase as the only *untinted* text on
    a plate where the border and the oversized quote marks are all coloured,
    so on the panel it stopped reading as a highlight at all. It is now the
    same B+W 1:1 sky blue the theme's own ornament marks use, which is neither
    of the previous failure modes: half white rather than three-quarters red,
    and already proven at ornament scale on this exact ground.
    """

    ROW = {
        "display_quote": "It was a quarter past three in the morning when the candle guttered out.",
        "matched_text": "a quarter past three",
        "author": "M. R. James",
        "title": "Ghost Stories of an Antiquary",
    }

    def _phrase_only(self, size=40):
        """Draw just the phrase on a bare ground, so no body text contaminates.

        Measuring a rect off the full frame is what makes this kind of ratio
        assertion wrong: the phrase shares its lines with white body words, and
        including any of them drags the measured blue share toward zero.
        """
        image = Image.new("RGB", (520, 90), rq.SPECTRA6["black"])
        draw = ImageDraw.Draw(image)
        font = rq.load_font(rq.theme_font_candidates("grimoire", "quote_bold"), size=size)
        rq._draw_text_body(
            image, draw, (10, 15), "a quarter past three",
            font=font, fill=rq.SPECTRA6["red"], theme="grimoire",
        )
        return ink_counts(image)

    def test_phrase_is_a_one_to_one_blue_white_stipple(self):
        counts = self._phrase_only()
        blue = counts.get(rq.SPECTRA6["blue"], 0)
        white = counts.get(rq.SPECTRA6["white"], 0)
        assert blue and white, "phrase painted in a single ink — the stipple seam did not fire"
        assert 0.4 < blue / (blue + white) < 0.6

    def test_phrase_carries_no_red(self):
        """The red ``accent`` slot is a sentinel, never painted.

        The border's pentagrams, rules and planetary sigils own the red on this
        plate; a phrase sharing that ink would stop reading as separate from
        them. ``_draw_text_body`` is therefore passed red and must emit none.
        """
        assert self._phrase_only().get(rq.SPECTRA6["red"], 0) == 0

    def test_phrase_shares_the_ornament_marks_recipe(self):
        """Greg's ask: the phrase should match the large quote marks.

        Reads the recipe out of ``THEMES`` rather than restating it, so the two
        cannot drift apart — recolouring the ornaments without the phrase (or
        vice versa) fails here.
        """
        theme = rq.THEMES["grimoire"]
        assert {theme["ornament_dark"], theme["ornament_light"]} == {
            rq.SPECTRA6["blue"], rq.SPECTRA6["white"],
        }
        counts = self._phrase_only()
        assert set(counts) - {rq.SPECTRA6["black"]} == {
            theme["ornament_dark"], theme["ornament_light"],
        }

    def test_phrase_is_visibly_distinct_from_the_body(self):
        """The regression that prompted this: solid white made the phrase and
        the body the same ink, leaving face and weight to carry it alone."""
        image = Image.new("RGB", (520, 90), rq.SPECTRA6["black"])
        draw = ImageDraw.Draw(image)
        font = rq.load_font(rq.theme_font_candidates("grimoire", "quote_regular"), size=40)
        rq._draw_text_body(
            image, draw, (10, 15), "a quarter past three",
            font=font, fill=rq.THEMES["grimoire"]["text"], theme="grimoire",
        )
        body = ink_counts(image)
        assert body.get(rq.SPECTRA6["blue"], 0) == 0, "body text must stay solid white"
        assert self._phrase_only().get(rq.SPECTRA6["blue"], 0) > 0

    def test_full_frame_still_snaps_on_palette(self):
        image = rq.render("03:15", dict(self.ROW), 800, 480, mode="production", theme="grimoire")
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())


class TestAutochromePlate:
    """The full-palette dither is the theme's entire pitch, so it is measured.

    ``autochrome`` is the first plate dithered against all six inks rather than
    a restricted sub-palette, and the argument for it is that a soft, high-key,
    desaturated source breaks into a fine grain the eye integrates — the way a
    real autochrome's dyed starch grains do — where a saturated one quantises
    into a chunky mosaic that reads as colour bars. Both halves of that are
    properties of the committed plate, so both are fenced here: if someone
    regenerates the art with punchier colour, or quietly narrows the palette
    the way every other plate theme does, these fail.

    The case rules follow: the caption card stays clean so a dense quote is
    legible over a photograph, no clock reaches the canvas, and a stripped
    install still gets a colour picture.
    """

    ROW = make_row(display_quote="At half past two the bell rang and nobody moved.",
                   matched_text="half past two", author="L. M. Montgomery",
                   title="Anne of Avonlea")

    def _render(self, time_str="14:15"):
        return rq.render(time_str, self.ROW, 800, 480, mode="production", theme="autochrome")

    @staticmethod
    def _plate():
        rq._DITHER_CACHE.clear()
        plate = rq._load_dithered_plate(rq.AUTOCHROME_PLATE, 800, 480,
                                        palette=rq._AUTOCHROME_PALETTE)
        assert plate is not None, "the committed autochrome plate is missing"
        return plate

    @staticmethod
    def _shares(image):
        total = image.width * image.height
        counts = ink_counts(image)
        return {name: counts.get(ink, 0) / total for name, ink in rq.SPECTRA6.items()}

    # -- the full-palette claim ---------------------------------------------

    def test_the_palette_is_not_restricted(self):
        """Every other plate narrows the candidate set; this one must not.

        A sub-palette here would not fail any other test — the frame would
        still render and still snap on-palette — it would just quietly stop
        being the thing the theme exists to be.
        """
        assert set(rq._AUTOCHROME_PALETTE) == set(rq.SPECTRA6.values()), (
            "the autochrome plate is being dithered against a sub-palette — the "
            "theme's whole claim is that the chroma IS the subject, so all six "
            "inks must be candidates"
        )

    def test_the_plate_puts_every_ink_on_the_page(self):
        shares = self._shares(self._plate())
        thin = {name: round(share, 4) for name, share in shares.items() if share < 0.02}
        assert not thin, (
            f"inks barely present in the plate: {thin} — the subject is a garden "
            "specifically so that sky, foliage, poppies, blooms, path and shadow "
            "each claim an ink; one dropping out means the art no longer "
            "demonstrates the full-palette dither"
        )

    def test_white_carries_the_tone_and_no_chroma_dominates(self):
        """The 'colour bars' guard, and the reason the source is muted.

        Measured against the real primitive, a saturated source quantises to a
        chunky blue/red/green mosaic; a soft high-key one leaves white carrying
        the luminance with the chroma dispersed as grain. That is a property of
        the *art*, invisible to every other test, and it is what separates a
        photograph from a test card.
        """
        shares = self._shares(self._plate())
        assert shares["white"] > 0.30, (
            f"white is only {shares['white']:.0%} of the plate — the source has "
            "lost its high key, and a dithered photograph without a dominant "
            "paper tone reads as a colour mosaic rather than as a picture"
        )
        loud = {name: round(share, 3) for name, share in shares.items()
                if name != "white" and share > 0.28}
        assert not loud, (
            f"chromatic inks dominating the plate: {loud} — the source has been "
            "saturated past what a six-ink dither can hold as grain"
        )

    def test_the_plate_is_a_photograph_not_a_texture(self):
        """The composition has to survive the dither, not just the palette.

        A first cut of this assertion counted how often adjacent pixels shared
        an ink, on the theory that blocks mean a posterised source. That is
        vacuous: Floyd-Steinberg disperses by construction, so it passes for
        any source at all, flat fields included. What actually distinguishes a
        photograph from a texture is that different parts of it differ - sky is
        not beds - so the fence measures the distance between two bands' ink
        distributions, and their sense.
        """
        plate = self._plate()
        sky = self._shares(plate.crop((0, 0, 800, 170)))
        beds = self._shares(plate.crop((0, 310, 800, 480)))
        distance = sum(abs(sky[ink] - beds[ink]) for ink in rq.SPECTRA6) / 2
        assert distance > 0.25, (
            f"sky and beds differ by only {distance:.0%} of their ink mix - the "
            "plate has flattened into a uniform texture, which dithers to noise "
            "rather than to a picture"
        )
        assert sky["white"] > beds["white"] + 0.20, (
            f"the sky ({sky['white']:.0%} white) is not meaningfully lighter than "
            f"the beds ({beds['white']:.0%}) - the plate has lost the tonal "
            "structure that reads as depth"
        )

    # -- the case ------------------------------------------------------------

    def test_the_caption_card_stays_clean(self):
        """A dense literary quote sits on this card over a photograph, so the
        knockout has to be complete: only card stock, rule and ink inside it."""
        px = self._render().load()
        x0, y0, x1, y1 = rq._AUTOCHROME_CARD
        allowed = {rq.SPECTRA6[c] for c in ("white", "yellow", "black", "red")}
        for y in range(y0 + 2, y1 - 1, 3):
            for x in range(x0 + 2, x1 - 1, 3):
                assert px[x, y] in allowed, (
                    f"photograph bleeding through the caption card at ({x}, {y}) — "
                    "the card must be knocked out of the plate, not laid over it"
                )

    def test_the_card_is_lifted_off_the_plate(self):
        """The shadow ledge, without which the card reads as a hole cut in the
        photograph rather than as paper resting on it."""
        px = self._render().load()
        _, _, x1, y1 = rq._AUTOCHROME_CARD
        ledge = rq._AUTOCHROME_LEDGE
        for offset in range(1, ledge + 1):
            assert px[x1 + offset, y1] == rq.SPECTRA6["black"], (
                "the caption card's drop-shadow ledge is missing"
            )

    def test_no_clock_reaches_the_canvas(self):
        """A photograph carries no clock — ``daguerreotype``'s rule, for the
        same class of object. Every minute must render byte-identically."""
        reference = pixel_bytes(self._render("03:00"))
        for time_str in ("03:05", "07:41", "11:59", "19:20", "23:58"):
            assert pixel_bytes(self._render(time_str)) == reference, (
                f"{time_str} renders differently — something is surfacing the clock"
            )

    def test_a_stripped_install_still_renders_a_colour_garden(self, monkeypatch, tmp_path):
        """The house graceful-fallback convention. The synthesised garden is
        coarser than the plate by design, but it must still be a colour picture
        — degrading to a blank ground would leave nothing of the theme."""
        monkeypatch.setattr(rq, "AUTOCHROME_PLATE", tmp_path / "absent.png")
        rq._DITHER_CACHE.clear()
        image = self._render()
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        shares = self._shares(image)
        for ink in ("blue", "green", "yellow"):
            assert shares[ink] > 0.01, (
                f"the fallback garden has almost no {ink} — sky, foliage and "
                f"blooms are what make it read as a colour photograph at all"
            )
        rq._DITHER_CACHE.clear()

    def test_the_tape_binds_all_four_edges(self):
        """The passe-partout: a bound plate is taped on every edge, and the
        tape is also what stops the photograph running off the panel."""
        px = self._render().load()
        black = rq.SPECTRA6["black"]
        mid = rq._AUTOCHROME_TAPE // 2
        for x, y in ((400, mid), (400, 479 - mid), (mid, 240), (799 - mid, 240)):
            assert px[x, y] == black, f"binding tape missing at ({x}, {y})"


class TestPhotoTheme:
    """The open-ended theme: the art is a file the operator chooses.

    Three things this theme has to do that no committed-plate theme does, and
    each was a real bug before it was a test:

    * **Condition an unknown photograph** into the band that dithers to grain,
      measuring in the space the correction knob works in, and applying the two
      corrections in an order where neither undoes the other.
    * **Place the caption card from the picture's own content**, measured on the
      continuous-tone image — a dither inverts the answer.
    * **Survive anything an operator can point it at**, degrading to the bundled
      plate rather than raising into the per-tick render path.
    """

    ROW = make_row(display_quote="At half past two the bell rang and nobody moved.",
                   matched_text="half past two", author="L. M. Montgomery",
                   title="Anne of Avonlea")

    @staticmethod
    def _photo(path, size=(900, 600), bands=None, chroma_boost=1.0, mean=0.5):
        """A synthetic photograph with controllable character."""
        w, h = size
        img = Image.new("RGB", size)
        px = img.load()
        base = int(mean * 255)
        for y in range(h):
            for x in range(w):
                if bands == "left_busy":
                    px[x, y] = ((60 + (x * 37 + y * 61) % 120, 120, 80) if x < w // 2
                               else (base, base - 6, base - 18))
                elif bands == "bright_blob":
                    # Textured left half, and a SOFT radial glow on the right.
                    # Both halves are load-bearing. The glow must be soft
                    # because a hard rim carries edge energy that detail alone
                    # already avoids, and the left must be textured so that
                    # detail alone actively *prefers* the glow's half — with a
                    # smooth left the cost map is near-uniform, the choice is
                    # decided by noise, and the assertion passes against a
                    # build with the salience term switched off. This models
                    # the real case: a sun or a lit face, soft after the
                    # conditioning blur, beside foliage.
                    if x < w // 2:
                        n = (x * 53 + y * 97) % 96
                        px[x, y] = (60 + n, 90 + n // 2, 70 + n // 3)
                    else:
                        d2 = (x - int(w * 0.76)) ** 2 + (y - int(h * 0.3)) ** 2
                        t = max(0.0, 1.0 - d2 / float((w // 5) ** 2))
                        v = int(48 + 200 * t * t)
                        px[x, y] = (v, v - 4, v - 12)
                else:
                    # ``mean`` names the BRIGHTEST channel, because that is what
                    # ``_photo_measure`` reports as luminance — a fixture whose
                    # chroma boost silently lifted its own mean made the
                    # "gentle photograph is left alone" test assert against a
                    # correction that was doing exactly the right thing.
                    px[x, y] = (
                        max(0, min(255, base)),
                        max(0, min(255, int(base - 130 * chroma_boost))),
                        max(0, min(255, int(base - 160 * chroma_boost))),
                    )
        img.save(path)
        return path

    def _render(self, time_str="14:15", size=(800, 480)):
        return rq.render(time_str, self.ROW, *size, mode="production", theme="photo")

    # -- conditioning --------------------------------------------------------

    def test_a_lurid_photograph_is_pulled_into_the_band(self, tmp_path):
        """Both corrections must land, which needs each measured in the space
        its own knob works in and applied in an order that does not undo the
        other. Two earlier versions failed this: one measured HSV saturation and
        drove ``ImageEnhance.Color`` with the ratio (undershooting 0.86 to 0.67
        against a 0.30 target), and one corrected levels before chroma, so
        blending toward grey then dragged the corrected mean back down.
        """
        path = self._photo(tmp_path / "lurid.png", chroma_boost=1.9, mean=0.85)
        with Image.open(path) as raw:
            source = rq._photo_cover_crop(raw.convert("RGB"), 800, 480)
        before = rq._photo_measure(source)
        chroma, mean, _ = rq._photo_measure(rq._photo_condition(source))
        assert before[0] > rq._PHOTO_TARGET_CHROMA * 1.5, "fixture is not lurid enough to test"
        assert chroma <= rq._PHOTO_TARGET_CHROMA + 0.02, (
            f"chroma landed at {chroma:.2f} against a {rq._PHOTO_TARGET_CHROMA} target — "
            "the correction is being computed in a different space from the one "
            "ImageEnhance.Color actually scales"
        )
        assert abs(mean - rq._PHOTO_TARGET_MEAN) <= rq._PHOTO_MEAN_TOLERANCE + 0.02, (
            f"luminance landed at {mean:.2f} against a {rq._PHOTO_TARGET_MEAN} target — "
            "a later correction is undoing an earlier one; levels must run last"
        )

    def test_a_gentle_photograph_is_left_alone(self, tmp_path):
        """The reason the corrections are measured rather than fixed. A blanket
        pastel pass would damage material that never needed it."""
        path = self._photo(tmp_path / "gentle.png", chroma_boost=0.25,
                           mean=rq._PHOTO_TARGET_MEAN)
        with Image.open(path) as raw:
            source = rq._photo_cover_crop(raw.convert("RGB"), 800, 480)
        before = rq._photo_measure(source)
        assert before[0] < rq._PHOTO_TARGET_CHROMA, "fixture is not gentle enough to test"
        after = rq._photo_measure(rq._photo_condition(source))
        assert abs(after[0] - before[0]) < 0.03 and abs(after[1] - before[1]) < 0.05, (
            f"an in-band photograph was altered: {before} -> {after}"
        )

    def test_a_dark_photograph_is_lifted_into_view(self, tmp_path):
        """The panel's ink range is narrow; an unlifted night photograph
        dithers to near-solid black and shows nothing across a room."""
        path = self._photo(tmp_path / "dark.png", chroma_boost=0.3, mean=0.12)
        with Image.open(path) as raw:
            source = rq._photo_cover_crop(raw.convert("RGB"), 800, 480)
        assert rq._photo_measure(source)[1] < 0.25
        assert rq._photo_measure(rq._photo_condition(source))[1] > 0.45

    # -- card placement ------------------------------------------------------

    def _card_side(self, path, monkeypatch):
        monkeypatch.setenv(rq.PHOTO_PATH_ENV, str(path))
        rq.clear_photo_cache()
        _, rect = rq._photo_frame_for(self.ROW, 800, 480)
        return "left" if rect[0] < 400 else "right"

    def test_the_card_avoids_the_busy_side(self, tmp_path, monkeypatch):
        """And it must follow the content when the content moves — otherwise
        the assertion is satisfied by the tie-break default alone."""
        busy_left = self._photo(tmp_path / "bl.png", bands="left_busy")
        assert self._card_side(busy_left, monkeypatch) == "right"
        with Image.open(busy_left) as im:
            im.transpose(Image.FLIP_LEFT_RIGHT).save(tmp_path / "br.png")
        assert self._card_side(tmp_path / "br.png", monkeypatch) == "left", (
            "mirroring the photograph did not move the card — placement is not "
            "actually reading the image"
        )

    def test_placement_is_measured_before_dithering(self, tmp_path, monkeypatch):
        """The inversion this theme shipped with once. A dither turns a smooth
        region into a stipple where every pixel differs from its neighbour, so
        measured on the plate a flat wall scores *higher* edge energy than dark
        foliage and the card lands on the subject.
        """
        photo = self._photo(tmp_path / "bl.png", bands="left_busy")
        monkeypatch.setenv(rq.PHOTO_PATH_ENV, str(photo))
        rq.clear_photo_cache()
        plate, _ = rq._photo_frame_for(self.ROW, 800, 480)
        with Image.open(photo) as raw:
            conditioned = rq._photo_condition(rq._photo_cover_crop(raw.convert("RGB"), 800, 480))

        def busy_half(image):
            cost = rq._photo_cost_map(image)
            cols = len(cost[0])
            left = sum(sum(r[:cols // 2]) for r in cost)
            return "left" if left > sum(sum(r[cols // 2:]) for r in cost) else "right"

        assert busy_half(conditioned) == "left", "fixture's busy half moved"
        assert busy_half(plate) == "right", (
            "the dithered plate no longer inverts the busy-half measurement, so "
            "this test can no longer prove the pre-dither measurement matters"
        )

    def test_the_card_avoids_a_smooth_bright_subject(self, tmp_path, monkeypatch):
        """Detail alone rates a sun or a lit face as quiet — no edge energy
        inside it — and puts the card squarely on the subject. The salience
        term is what fixes that."""
        photo = self._photo(tmp_path / "blob.png", bands="bright_blob")
        monkeypatch.setenv(rq.PHOTO_PATH_ENV, str(photo))
        rq.clear_photo_cache()
        _, (x0, y0, x1, y1) = rq._photo_frame_for(self.ROW, 800, 480)
        blob_cx, blob_cy = int(800 * 0.76), int(480 * 0.3)
        assert not (x0 <= blob_cx <= x1 and y0 <= blob_cy <= y1), (
            f"the card at {(x0, y0, x1, y1)} covers the bright subject at "
            f"{(blob_cx, blob_cy)} — the salience term is not being applied"
        )

    # -- the source ----------------------------------------------------------

    def test_a_directory_rotates_with_the_quote(self, tmp_path, monkeypatch):
        """A picture frame that shows one photograph forever is a poster. The
        pick is driven by the row digest, not the clock, so it is stable for a
        given quote — which run_clock's 'quote unchanged, skip the redraw'
        dedup depends on."""
        for i in range(6):
            self._photo(tmp_path / f"{i}.png", chroma_boost=0.2, mean=0.3 + i * 0.09)
        monkeypatch.setenv(rq.PHOTO_PATH_ENV, str(tmp_path))
        chosen = set()
        for i in range(24):
            row = make_row(display_quote=f"At half past two, take {i}.",
                           matched_text="half past two", line_number=i)
            picked = rq._photo_for_row(row)
            assert rq._photo_for_row(row) == picked, "the pick is not stable for a row"
            chosen.add(picked)
        assert len(chosen) > 1, "every quote chose the same photograph"

    def test_a_directory_pick_does_not_depend_on_listing_order(self, tmp_path, monkeypatch):
        """Directory order is filesystem-defined and not stable, so the
        candidate list is sorted before the digest indexes into it."""
        paths = [self._photo(tmp_path / f"{c}.png", chroma_boost=0.2) for c in "bdac"]
        monkeypatch.setenv(rq.PHOTO_PATH_ENV, str(tmp_path))
        assert rq._photo_candidates(str(tmp_path)) == sorted(paths)

    def test_non_image_entries_in_a_directory_are_skipped(self, tmp_path, monkeypatch):
        (tmp_path / "notes.txt").write_text("not a photograph")
        (tmp_path / "clip.mp4").write_bytes(b"\x00\x01")
        keep = self._photo(tmp_path / "real.png", chroma_boost=0.2)
        monkeypatch.setenv(rq.PHOTO_PATH_ENV, str(tmp_path))
        assert rq._photo_candidates(str(tmp_path)) == [keep]

    # -- robustness ----------------------------------------------------------

    @pytest.mark.parametrize("kind", ["missing", "empty_dir", "truncated", "not_an_image", "zero_byte"])
    def test_every_bad_source_degrades_to_the_bundled_plate(self, kind, tmp_path, monkeypatch, capsys):
        """A theme that can crash the render loop because someone deleted a
        file is not shippable on an appliance. Every failure must land on the
        bundled plate, which is also what the unconfigured render produces."""
        if kind == "missing":
            source = tmp_path / "gone.jpg"
        elif kind == "empty_dir":
            source = tmp_path / "empty"
            source.mkdir()
        else:
            source = tmp_path / "bad.jpg"
            if kind == "truncated":
                real = self._photo(tmp_path / "real.png", chroma_boost=0.4)
                source.write_bytes(real.read_bytes()[:40])
            elif kind == "not_an_image":
                source.write_text("the operator dropped a text file in here")
            else:
                source.write_bytes(b"")
        rq.clear_photo_cache()
        unconfigured = pixel_bytes(self._render())
        monkeypatch.setenv(rq.PHOTO_PATH_ENV, str(source))
        rq.clear_photo_cache()
        assert pixel_bytes(self._render()) == unconfigured, (
            f"a {kind} source did not fall back to the bundled plate"
        )
        assert "photo theme" in capsys.readouterr().err, "the degradation was silent"

    @pytest.mark.parametrize("mode,size", [("CMYK", (900, 600)), ("L", (700, 500)),
                                           ("P", (640, 480)), ("RGBA", (800, 600)),
                                           ("RGB", (13, 9)), ("RGB", (4000, 60))])
    def test_awkward_but_valid_images_render(self, mode, size, tmp_path, monkeypatch):
        """Colour modes and aspect ratios an operator's library really holds:
        a CMYK scan, a greyscale, a palette PNG, a transparency, a thumbnail
        and a panorama."""
        # CMYK has no PNG encoding, so that leg round-trips through JPEG.
        path = tmp_path / ("odd.jpg" if mode == "CMYK" else "odd.png")
        fill = None if mode == "P" else 120 if mode == "L" else (120, 90, 60, 40)[:len(mode)]
        Image.new(mode, size, fill).save(path)
        monkeypatch.setenv(rq.PHOTO_PATH_ENV, str(path))
        rq.clear_photo_cache()
        image = self._render()
        assert image.size == (800, 480)
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())

    def test_an_exif_rotation_is_honoured(self, tmp_path, monkeypatch):
        """A phone stores a portrait photograph landscape with a rotate tag.

        Asserted on the rendered content, not by calling ``exif_transpose`` in
        the test — an earlier version did exactly that and so tested Pillow
        rather than the renderer, passing cheerfully against a build with the
        orientation handling deleted.

        The fixture is a 600x900 portrait whose top third is black. Rotated 90
        CW as the tag asks, that band lands on the RIGHT of a landscape frame;
        ignored, it stays at the TOP. The two are trivially distinguishable.
        """
        portrait = Image.new("RGB", (600, 900), (170, 175, 180))
        ImageDraw.Draw(portrait).rectangle((0, 0, 599, 299), fill=(20, 20, 24))
        exif = portrait.getexif()
        exif[274] = 6  # orientation: rotate 90 CW
        path = tmp_path / "phone.jpg"
        portrait.save(path, exif=exif)

        monkeypatch.setenv(rq.PHOTO_PATH_ENV, str(path))
        rq.clear_photo_cache()
        conditioned = rq._photo_open(path, 800, 480)
        assert conditioned is not None
        grey = conditioned.convert("L")
        left = sum(grey.crop((0, 0, 200, 480)).histogram()[i] * i for i in range(256))
        right = sum(grey.crop((600, 0, 800, 480)).histogram()[i] * i for i in range(256))
        top = sum(grey.crop((0, 0, 800, 120)).histogram()[i] * i for i in range(256))
        bottom = sum(grey.crop((0, 360, 800, 480)).histogram()[i] * i for i in range(256))
        assert right < left * 0.75, (
            "the dark band is not on the right — the EXIF rotation was ignored, "
            "so the photograph is being cropped on the wrong axis"
        )
        assert abs(top - bottom) < max(top, bottom) * 0.25, (
            "the dark band is running across the top, which is the unrotated "
            "interpretation"
        )

    # -- decode bounds -------------------------------------------------------

    def test_a_huge_undraftable_image_is_refused_not_decoded(self, tmp_path, monkeypatch):
        """Pillow's own bomb guard does not cover this range (a Codex finding).

        It raises only above ``MAX_IMAGE_PIXELS * 2`` (179 MP) and merely warns
        between there and 89.5 MP, so an image well inside its limits still
        decodes eagerly — a 56 MP PNG measures 212 MiB of RSS, enough to OOM
        the render child on a 512 MB Pi. An OOM kill is not the graceful
        fallback this theme advertises, so the cap turns it away instead.

        Asserted by refusing to let the decoder run at all: ``load`` raising
        would be caught and reported as an unreadable file, which is a
        different (and much later) code path than the one under test.
        """
        photo = tmp_path / "huge.png"
        Image.new("RGB", (16, 16), (10, 20, 30)).save(photo)
        monkeypatch.setattr(rq, "_PHOTO_MAX_PIXELS", 100)  # 16x16 = 256 px, over it

        def refuse(self, *a, **kw):
            raise AssertionError("the decoder ran on an image over the cap")

        monkeypatch.setattr(Image.Image, "load", refuse)
        rq.clear_photo_cache()
        assert rq._photo_open(photo, 800, 480) is None

    def test_the_cap_is_checked_after_drafting_not_before(self, tmp_path, monkeypatch):
        """Otherwise the cap rejects real cameras.

        A 48 MP phone JPEG is over any Pi-safe limit as declared and
        comfortably under it once the JPEG decoder has scaled it down during
        the DCT pass, so drafting first is what keeps the cap aimed at
        genuinely undecodable material rather than at ordinary photographs.
        """
        photo = tmp_path / "big.jpg"
        Image.new("RGB", (4800, 3200), (150, 140, 120)).save(photo, quality=60)
        declared = 4800 * 3200
        monkeypatch.setattr(rq, "_PHOTO_MAX_PIXELS", declared // 4)
        rq.clear_photo_cache()
        assert rq._photo_open(photo, 800, 480) is not None, (
            "a JPEG that drafts well under the cap was refused — the cap is "
            "being checked against the declared size instead of the drafted one"
        )

    def test_drafting_shrinks_the_decode_for_a_large_jpeg(self, tmp_path):
        """The mechanism itself: draft must reduce the size Pillow decodes,
        before any pixels are materialised."""
        photo = tmp_path / "pano.jpg"
        Image.new("RGB", (6000, 4000), (120, 130, 140)).save(photo, quality=60)
        with Image.open(photo) as raw:
            assert raw.size == (6000, 4000)
            raw.draft("RGB", (1600, 960))
            assert raw.width * raw.height < 6000 * 4000 / 3, (
                f"draft left the image at {raw.size} — a large JPEG would be "
                "decoded at full resolution"
            )

    def test_an_oversized_source_degrades_to_the_bundled_plate(self, tmp_path, monkeypatch):
        """End to end: the refusal reaches the same fallback every other bad
        source does, rather than raising into the per-tick render path."""
        rq.clear_photo_cache()
        unconfigured = pixel_bytes(self._render())
        photo = tmp_path / "huge.png"
        Image.new("RGB", (64, 64), (10, 20, 30)).save(photo)
        monkeypatch.setattr(rq, "_PHOTO_MAX_PIXELS", 100)
        monkeypatch.setenv(rq.PHOTO_PATH_ENV, str(photo))
        rq.clear_photo_cache()
        assert pixel_bytes(self._render()) == unconfigured

    # -- the preview stamp ----------------------------------------------------

    def test_the_source_stamp_moves_when_the_file_changes(self, tmp_path, monkeypatch):
        """What the curator UI's preview cache keys on."""
        photo = self._photo(tmp_path / "p.png", chroma_boost=0.3)
        monkeypatch.setenv(rq.PHOTO_PATH_ENV, str(photo))
        rq.clear_photo_cache()
        first = rq.photo_source_stamp(self.ROW)
        assert first is not None and rq.photo_source_stamp(self.ROW) == first
        self._photo(photo, bands="bright_blob")
        assert rq.photo_source_stamp(self.ROW) != first

    def test_the_source_stamp_is_none_when_unconfigured(self):
        rq.clear_photo_cache()
        assert rq.photo_source_stamp(self.ROW) is None

    def test_the_source_stamp_survives_an_unstattable_file(self, tmp_path, monkeypatch):
        """A stamp is a cache key, so it must not raise on a file that has
        gone away between listing and stat."""
        photo = self._photo(tmp_path / "p.png", chroma_boost=0.3)
        monkeypatch.setattr(rq, "_photo_for_row", lambda row: photo)
        real_stat = pathlib.Path.stat

        def vanish(self, *a, **kw):
            if self == photo:
                raise FileNotFoundError(2, "No such file or directory")
            return real_stat(self, *a, **kw)

        monkeypatch.setattr(pathlib.Path, "stat", vanish)
        assert rq.photo_source_stamp(self.ROW) == (str(photo), None, None)

    # -- caching -------------------------------------------------------------

    def test_the_cache_is_bounded(self, tmp_path, monkeypatch):
        """A directory can hold thousands of files and each decoded frame is
        ~1.1 MB — the ``betweenus`` paper-cache lesson."""
        # Each source is pointed at directly rather than left to the digest to
        # discover: with a directory, several rows can hash onto the same file,
        # so the cache may never reach its bound and the assertion passes
        # against an unbounded dict.
        rq.clear_photo_cache()
        total = rq._PHOTO_CACHE_MAX + 4
        for i in range(total):
            path = self._photo(tmp_path / f"{i}.png", chroma_boost=0.2, mean=0.25 + i * 0.05)
            monkeypatch.setenv(rq.PHOTO_PATH_ENV, str(path))
            rq._photo_frame_for(self.ROW, 800, 480)
            assert len(rq._PHOTO_CACHE) <= rq._PHOTO_CACHE_MAX, (
                f"cache holds {len(rq._PHOTO_CACHE)} frames after {i + 1} distinct "
                f"sources, over the {rq._PHOTO_CACHE_MAX} bound"
            )
        assert len(rq._PHOTO_CACHE) == rq._PHOTO_CACHE_MAX, (
            "the cache never filled, so the bound was never actually exercised"
        )

    def test_editing_the_file_invalidates_the_cache(self, tmp_path, monkeypatch):
        """The cache key carries mtime and size, so replacing the photograph at
        a configured path shows the new one rather than the old one forever."""
        path = self._photo(tmp_path / "p.png", chroma_boost=0.2, mean=0.35)
        monkeypatch.setenv(rq.PHOTO_PATH_ENV, str(path))
        rq.clear_photo_cache()
        first = pixel_bytes(self._render())
        self._photo(path, bands="bright_blob")
        assert pixel_bytes(self._render()) != first, (
            "replacing the file at the configured path did not change the render"
        )

    def test_an_unreadable_directory_degrades(self, tmp_path, monkeypatch):
        """A directory the appliance user cannot list — the wrong owner on a
        mounted share is the ordinary way this happens."""
        source = tmp_path / "locked"
        source.mkdir()

        def deny(self):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(pathlib.Path, "iterdir", deny)
        monkeypatch.setenv(rq.PHOTO_PATH_ENV, str(source))
        rq.clear_photo_cache()
        assert rq._photo_candidates(str(source)) == []
        assert self._render().size == (800, 480)

    def test_a_file_that_vanishes_after_listing_degrades(self, tmp_path, monkeypatch):
        """The cache key is built from a ``stat`` taken after the candidate is
        chosen, so a file removed in between must not raise — a rotating
        directory an operator is actively editing hits this.

        ``_photo_for_row`` is stubbed rather than letting the real listing run:
        ``Path.is_file`` swallows ``OSError`` and returns False, so a globally
        failing ``stat`` makes the candidate list come back empty and the
        render never reaches the branch under test. An earlier version of this
        test did exactly that and left the branch uncovered while passing.
        """
        photo = self._photo(tmp_path / "p.png", chroma_boost=0.4)
        monkeypatch.setattr(rq, "_photo_for_row", lambda row: photo)
        real_stat = pathlib.Path.stat

        def vanish(self, *args, **kwargs):
            if self == photo:
                raise FileNotFoundError(2, "No such file or directory")
            return real_stat(self, *args, **kwargs)

        monkeypatch.setattr(pathlib.Path, "stat", vanish)
        rq.clear_photo_cache()
        image = self._render()
        assert image.size == (800, 480)
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        assert not rq._PHOTO_CACHE, (
            "an un-stattable source was cached — the key would be wrong and "
            "could never be invalidated"
        )

    def test_a_stripped_install_still_renders(self, tmp_path, monkeypatch):
        """Fallback of the fallback: nothing configured *and* the bundled plate
        gone. The synthesised garden keeps the theme a colour picture."""
        monkeypatch.setattr(rq, "AUTOCHROME_PLATE", tmp_path / "absent.png")
        rq.clear_photo_cache()
        rq._DITHER_CACHE.clear()
        image = self._render()
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        counts = ink_counts(image)
        total = 800 * 480
        for ink in ("blue", "green"):
            assert counts.get(rq.SPECTRA6[ink], 0) / total > 0.01, (
                f"the synthesised fallback has almost no {ink}"
            )
        rq._DITHER_CACHE.clear()

    # -- frame contracts -----------------------------------------------------

    def test_no_clock_reaches_the_canvas(self, tmp_path, monkeypatch):
        photo = self._photo(tmp_path / "p.png", chroma_boost=0.5, mean=0.4)
        monkeypatch.setenv(rq.PHOTO_PATH_ENV, str(photo))
        rq.clear_photo_cache()
        reference = pixel_bytes(self._render("03:00"))
        for time_str in ("07:41", "11:59", "23:58"):
            assert pixel_bytes(self._render(time_str)) == reference

    def test_the_caption_card_stays_clean(self, tmp_path, monkeypatch):
        """A dense quote sits on this card over an unknown picture, so the
        knockout has to be complete."""
        photo = self._photo(tmp_path / "p.png", chroma_boost=1.4, mean=0.4)
        monkeypatch.setenv(rq.PHOTO_PATH_ENV, str(photo))
        rq.clear_photo_cache()
        _, (x0, y0, x1, y1) = rq._photo_frame_for(self.ROW, 800, 480)
        px = self._render().load()
        allowed = {rq.SPECTRA6[c] for c in ("white", "yellow", "black", "red")}
        for y in range(y0 + 3, y1 - 2, 3):
            for x in range(x0 + 3, x1 - 2, 3):
                assert px[x, y] in allowed, f"the photograph shows through the card at {(x, y)}"


def ImageOps_exif_size(image):
    """The size an EXIF-aware open would produce, for the rotation fixture."""
    from PIL import ImageOps
    transposed = ImageOps.exif_transpose(image)
    return (transposed or image).size


class TestControlFrame:
    """``control`` — the Astral Plane, after Remedy's *Control*.

    A white void with isometric stone blocks, the Board's inverted pyramid, a
    concrete plinth carrying a black wayfinding sign, and the matched phrase in
    Hiss red blooming a coral stipple into the white around it.
    """

    ROW = dict(
        display_quote="It was about half past two when the clock struck and the "
                      "afternoon light came slanting through the tall windows.",
        matched_text="half past two",
        author="Jane Austen",
        title="Emma",
        source_id="158",
        line_number=482,
    )

    @staticmethod
    def _render(row=None, time_str="14:30"):
        return rq.render(time_str, make_row(**(row or TestControlFrame.ROW)),
                         800, 480, mode="production", theme="control")

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert "control" in rq.THEMES
        assert "control" in rq.THEME_ORDER
        assert "control" not in rq.CYCLE_EXCLUDED_THEMES
        assert display_inky.THEME_SATURATION["control"] == 0.5
        # The title-card face: Jost pinned to Bold for the body as well as
        # the phrase (the game's title cards are Avant Garde Gothic Bold) —
        # the phrase earns its step from the Hiss red, not weight. The sign
        # chrome is Archivo, the Akzidenz-descended grotesque of the game's UI.
        for role in ("quote_regular", "quote_bold"):
            assert rq.theme_font_candidates("control", role)[0] == (rq.JOST_VARIABLE, "Bold")
        assert rq.theme_font_candidates("control", "ornament")[0] == rq.ARCHIVO_BOLD
        for path in (rq.JOST_VARIABLE, rq.ARCHIVO_BOLD):
            assert pathlib.Path(path).exists()
            assert (pathlib.Path(path).parent / "OFL.txt").exists()

    def test_time_never_reaches_the_frame(self):
        """The Astral Plane has no clock: the matched phrase carries the time,
        so every time string must render byte-identically for one row."""
        first = pixel_bytes(self._render(time_str="00:00"))
        for time_str in ("03:15", "14:30", "23:59"):
            assert pixel_bytes(self._render(time_str=time_str)) == first

    def test_frame_is_on_palette_and_deterministic(self):
        image = self._render()
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_only_the_hiss_is_chromatic(self):
        """Everything but the matched phrase — void, blocks, Board, plinth,
        sign — is achromatic: red appears only inside the quote rect (grown by
        the bloom's reach and the resonance shift, which can spill past a rect
        edge the phrase sits against), and a row with no matched phrase paints
        no red at all."""
        red = rq.SPECTRA6["red"]
        image = self._render()
        assert ink_counts(image).get(red, 0) > 0
        x0, y0, x1, y1 = rq._CONTROL_QUOTE_RECT
        reach = 3 * rq._CONTROL_HISS_RADIUS + max(abs(s) for _, _, s in rq._CONTROL_RESONANCE)
        x0, y0, x1, y1 = x0 - reach, y0 - reach, x1 + reach, y1 + reach
        for band in ((0, 0, 800, y0), (0, y1, 800, 480), (0, y0, x0, y1), (x1, y0, 800, y1)):
            assert red not in distinct_inks(image.crop(band)), f"red outside the quote rect in {band}"
        assert distinct_inks(image) <= {red, rq.SPECTRA6["black"], rq.SPECTRA6["white"]}
        plain = self._render({**self.ROW, "matched_text": ""})
        assert ink_counts(plain).get(red, 0) == 0

    def test_hiss_halo_survives_panel_distance(self, monkeypatch):
        """The bloom is not a token: the halo carries a substantial fraction of
        the phrase's own red, which is what keeps it visible once the panel is
        box-averaged by viewing distance (the ``izakaya`` lesson — parameters
        tuned at 1:1 produce a bloom that vanishes at 1-3 m)."""
        red = rq.SPECTRA6["red"]
        full = ink_counts(self._render()).get(red, 0)
        original = rq.paint_neon_mask

        def core_only(image, mask, core, glow, **kwargs):
            kwargs["cap"] = 0.0
            return original(image, mask, core, glow, **kwargs)

        monkeypatch.setattr(rq, "paint_neon_mask", core_only)
        core = ink_counts(self._render()).get(red, 0)
        assert core > 0
        assert full - core >= 0.2 * core, (
            f"halo carries {full - core} red px against a {core} px core"
        )

    def test_halo_never_eats_the_prose(self, monkeypatch):
        """``ground`` pins the bloom to white: the black prose beside the phrase
        must be identical with and without the halo."""
        black = rq.SPECTRA6["black"]
        with_halo = self._render()
        original = rq.paint_neon_mask

        def core_only(image, mask, core, glow, **kwargs):
            kwargs["cap"] = 0.0
            return original(image, mask, core, glow, **kwargs)

        monkeypatch.setattr(rq, "paint_neon_mask", core_only)
        without = self._render()
        # Every black pixel of the halo-less render must still be black with
        # the halo: mask the halo-less black, and require the halo render to
        # be black everywhere under that mask (a C-speed compare, not a walk).
        black_mask = without.convert("L").point(lambda v: 255 if v == 0 else 0)
        under = Image.composite(with_halo, Image.new("RGB", (800, 480), black), black_mask)
        assert distinct_inks(under) == {black}, "halo overwrote prose"

    def test_blocks_are_shaded_solids(self):
        """A block is three faces under one light: its lit face carries a
        sparser black stipple than its shadow face, and both are K+W only."""
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        draw = ImageDraw.Draw(image)
        rq._control_paint_blocks(image, draw)
        assert distinct_inks(image) <= {rq.SPECTRA6["black"], rq.SPECTRA6["white"]}
        top_x, top_y, side, height = rq._CONTROL_BLOCKS[0]
        _, left_face, right_face = rq._control_block_faces(top_x, top_y, side, height)

        def black_share(face):
            mask = Image.new("1", image.size, 0)
            ImageDraw.Draw(mask).polygon([(int(x), int(y)) for x, y in face], fill=1)
            # Shrink away from the outline stroke so the edge does not count.
            mp, px = mask.load(), image.load()
            hits = total = 0
            bx0, by0, bx1, by1 = mask.getbbox()
            for y in range(by0 + 3, by1 - 3):
                for x in range(bx0 + 3, bx1 - 3):
                    if mp[x, y]:
                        total += 1
                        hits += px[x, y] == rq.SPECTRA6["black"]
            return hits / max(1, total)

        lit, shade = black_share(left_face), black_share(right_face)
        assert 0.15 < lit < 0.45
        assert 0.45 < shade < 0.8
        assert lit < shade

    def test_board_lines_are_labels_over_the_rows_own_values(self):
        """The Board's paired diction supplies the labels; the values are the
        row's author and title, uppercased and never invented."""
        assert rq._control_board_lines(make_row(**self.ROW)) == [
            "AUTHOR/ORIGIN: JANE AUSTEN",
            "WORK/VESSEL: EMMA",
        ]
        bare = make_row(**{**self.ROW, "author": "", "title": ""})
        assert rq._control_board_lines(bare) == ["WORK/VESSEL: PROJECT GUTENBERG #158"]
        nothing = make_row(**{**self.ROW, "author": "", "title": "", "source_id": "", "source_path": ""})
        assert rq._control_board_lines(nothing) == []

    def test_sign_and_plinth_are_confined_to_the_foot(self):
        """The plinth owns the band below ``_CONTROL_PLINTH_Y`` and nothing
        above it — a row rendered with an empty quote leaves the void white
        between the Board and the plinth, save for the blocks in the margins."""
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        draw = ImageDraw.Draw(image)
        rq._control_paint_plinth(image, draw)
        rq._control_paint_sign(image, draw, make_row(**self.ROW))
        px = image.load()
        top = rq._CONTROL_PLINTH_Y
        assert all(px[x, y] == rq.SPECTRA6["white"] for y in range(0, top - 1, 7) for x in range(0, 800, 7))
        band = sum(px[x, y] == rq.SPECTRA6["black"] for y in range(top, 480) for x in range(800))
        assert band > 0.3 * (480 - top) * 800

    def test_resonance_echoes_the_phrase_without_cutting_it(self, monkeypatch):
        """The Hiss tearing is an echo, never a displacement: with the
        resonance bands disabled the frame loses red only, and every red
        pixel the bands add sits on what was white — no glyph of the phrase,
        no prose and no bloom pixel is moved or overwritten."""
        red = rq.SPECTRA6["red"]
        with_bands = self._render()
        monkeypatch.setattr(rq, "_CONTROL_RESONANCE", ())
        without = self._render()
        changed = ImageChops.difference(with_bands, without).convert("L").point(lambda v: 255 if v else 0)
        assert changed.getbbox() is not None, "the resonance bands painted nothing"
        # Under the changed mask: the band-less render was all white, and the
        # banded render is all red — an echo laid onto the void and nothing else.
        white = rq.SPECTRA6["white"]
        before = Image.composite(without, Image.new("RGB", (800, 480), white), changed)
        after = Image.composite(with_bands, Image.new("RGB", (800, 480), red), changed)
        assert distinct_inks(before) == {white}, "resonance displaced a non-white pixel"
        assert distinct_inks(after) == {red}

    def test_plinth_prefers_the_concrete_plate_and_falls_back(self, tmp_path, monkeypatch):
        """The plinth is the committed board-formed plate dithered to K+W;
        with the asset missing it degrades to the jittered stipple, and both
        paint an achromatic band of comparable darkness."""
        assert rq.CONTROL_PLATE.exists()
        with Image.open(rq.CONTROL_PLATE) as plate:
            assert plate.size == (800, 480 - rq._CONTROL_PLINTH_Y)

        def band_share(image):
            px = image.load()
            top = rq._CONTROL_PLINTH_Y
            black = sum(px[x, y] == rq.SPECTRA6["black"] for y in range(top + 3, 480) for x in range(800))
            assert distinct_inks(image.crop((0, top, 800, 480))) <= {rq.SPECTRA6["black"], rq.SPECTRA6["white"]}
            return black / ((480 - top - 3) * 800)

        def plinth_only():
            image = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
            rq._control_paint_plinth(image, ImageDraw.Draw(image))
            return image

        plated = band_share(plinth_only())
        monkeypatch.setattr(rq, "CONTROL_PLATE", tmp_path / "missing.png")
        fallback = band_share(plinth_only())
        assert 0.25 < plated < 0.6
        assert 0.25 < fallback < 0.6

    def test_long_credits_never_overprint_the_bureau_name(self):
        """The credit column's budget is measured off the painted name run, so
        a shipped-corpus title wide enough to reach it is shrunk and ellipsised
        rather than laid over FEDERAL BUREAU OF CONTROL. Fenced by comparing
        the name column between a short title and the longest one in the
        corpus: it must not change by a pixel."""
        long_title = "The Importance of Being Earnest: A Trivial Comedy for Serious People"

        def sign(title):
            image = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
            draw = ImageDraw.Draw(image)
            rq._control_paint_sign(image, draw, make_row(**{**self.ROW, "title": title}))
            return image

        x0, y0, x1, y1 = rq._CONTROL_SIGN_RECT
        short, long = sign("Emma"), sign(long_title)
        # The name column is bounded by the run actually painted, measured the
        # way the sign measures it, plus half the gap the sign keeps clear.
        name_font = rq.load_font([(rq.OSWALD_VARIABLE, "Bold")], size=17)
        text_x = rq._CONTROL_SEAL_CENTRE[0] + rq._CONTROL_SEAL_RADIUS + 12
        name_w = rq.tracked_width(ImageDraw.Draw(short), "FEDERAL BUREAU OF CONTROL", name_font,
                                  tracking=rq._CONTROL_TRACKING)
        column = (x0, y0, int(text_x + name_w + rq._CONTROL_SIGN_GAP // 2), y1)
        assert ImageChops.difference(short.crop(column), long.crop(column)).getbbox() is None, (
            "a long title overprinted the Bureau name column"
        )
        # And the long title still carries a legible, ellipsised credit rather
        # than a bare mid-word fragment.
        draw = ImageDraw.Draw(long)
        font, text = rq.fit_text_to_width(
            draw, f"WORK/VESSEL: {long_title.upper()}",
            [(rq.OSWALD_VARIABLE, "Medium")], rq._CONTROL_CREDIT_SIZE, 300,
            floor=rq._CONTROL_CREDIT_FLOOR, tracking=1,
        )
        assert text.endswith("…") and len(text) > 20
        assert rq.tracked_width(draw, text, font, tracking=1) <= 300


class TestObservationFrame:
    """``observation`` — S.A.M.'s camera feed, after No Code's *Observation*.

    Black space, a banded Saturn with its polar hexagon and rings, a glowing
    hexagonal anomaly under a tracking reticle, and the quote as an audio-log
    transcript in a HUD panel. The camera number is the hour.
    """

    ROW = dict(
        display_quote="It was about half past two when the clock struck and the "
                      "afternoon light came slanting through the tall windows.",
        matched_text="half past two",
        author="Jane Austen",
        title="Emma",
        source_id="158",
        line_number=482,
    )

    @staticmethod
    def _render(row=None, time_str="14:30", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or TestObservationFrame.ROW)),
                         *size, mode="production", theme="observation")

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert "observation" in rq.THEMES
        assert "observation" in rq.THEME_ORDER
        assert "observation" not in rq.CYCLE_EXCLUDED_THEMES
        assert display_inky.THEME_SATURATION["observation"] == 0.7
        assert rq.theme_font_candidates("observation", "quote_regular")[0] == rq.PLEXMONO_MEDIUM
        assert rq.theme_font_candidates("observation", "quote_bold")[0] == rq.PLEXMONO_BOLD
        for path in (rq.PLEXMONO_REGULAR, rq.PLEXMONO_MEDIUM, rq.PLEXMONO_SEMIBOLD, rq.PLEXMONO_BOLD):
            assert pathlib.Path(path).exists(), path
        assert (pathlib.Path(rq.PLEXMONO_BOLD).parent / "OFL.txt").exists()

    @pytest.mark.parametrize("time_str,camera", [
        ("00:30", 12), ("12:00", 12), ("13:05", 1), ("01:59", 1), ("09:15", 9), ("bogus", 12),
    ])
    def test_camera_is_the_twelve_hour_clock_hour(self, time_str, camera):
        assert rq._observation_camera(time_str) == camera

    def test_two_cameras_per_module(self):
        lit = [rq._observation_module_index(c) for c in range(1, 13)]
        assert lit == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5]

    def test_minute_never_reaches_the_frame(self):
        """Hour only: the camera designation carries the hour and the matched
        phrase carries the minute, so every minute of an hour renders
        byte-identically for one row."""
        first = pixel_bytes(self._render(time_str="14:00"))
        for time_str in ("14:07", "14:30", "14:59", "02:45"):
            assert pixel_bytes(self._render(time_str=time_str)) == first

    def test_hour_changes_the_camera(self):
        assert pixel_bytes(self._render(time_str="14:30")) != pixel_bytes(self._render(time_str="15:30"))

    def test_on_palette_deterministic_and_all_six_inks(self):
        image = self._render()
        inks = distinct_inks(image)
        assert inks == set(rq.SPECTRA6.values()), "the feed should surface every ink the panel has"
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_log_number_follows_the_row_not_the_clock(self):
        other = {**self.ROW, "source_id": "159"}
        a = self._render()
        b = self._render(other)
        x0, y0, x1, _ = rq._OBSERVATION_PANEL
        header = (x0, y0, x1, y0 + rq._OBSERVATION_HEADER_H)
        assert pixel_bytes(a.crop(header)) != pixel_bytes(b.crop(header))

    def test_band_mix_is_one_read_partitioned_three_ways(self):
        """Over a whole tile, shade takes exactly its share of cells and the
        band's minor ink takes its share of the remainder — no second read."""
        black, major, minor = rq.SPECTRA6["black"], rq.SPECTRA6["yellow"], rq.SPECTRA6["red"]
        counts = {black: 0, major: 0, minor: 0}
        for rank in range(64):
            counts[rq._observation_mix(rank, 0.25, major, minor, 0.375)] += 1
        assert counts[black] == 16
        assert counts[minor] == 18
        assert counts[major] == 30

    def test_far_rings_pass_behind_the_planet(self):
        """Painting the rings over the planet may change the disc only on the
        near half of the ring plane (v > 0); the far half is occluded."""
        base = Image.new("RGB", (800, 480), rq.SPECTRA6["black"])
        rq._observation_paint_saturn(base)
        ringed = base.copy()
        rq._observation_paint_rings(ringed)
        cx, cy, r = rq._OBSERVATION_SATURN
        a, b = base.load(), ringed.load()
        near_changed = 0
        for y in range(cy - r, cy + r + 1):
            for x in range(cx - r, cx + r + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 > r * r or a[x, y] == b[x, y]:
                    continue
                _, v = rq._observation_ring_frame(x - cx, y - cy)
                assert v >= 0, f"far-side ring painted over the planet at {(x, y)}"
                near_changed += 1
        assert near_changed > 500, "the near rings should cross in front of the disc"

    def test_saturn_is_banded_and_shaded(self):
        """The disc carries the warm band inks, the blue polar cap, and a
        terminator: its lower-right quadrant is darker than its upper-left."""
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["black"])
        rq._observation_paint_saturn(image)
        cx, cy, r = rq._OBSERVATION_SATURN
        disc = distinct_inks(image.crop((cx - r, cy - r, cx + r + 1, cy + r + 1)))
        assert {rq.SPECTRA6[n] for n in ("yellow", "red", "blue", "white")} <= disc
        black = rq.SPECTRA6["black"]

        def black_share(box):
            counts = ink_counts(image.crop(box))
            return counts.get(black, 0) / sum(counts.values())

        h = r // 2
        lit = black_share((cx - h - 10, cy - h - 10, cx - h + 10, cy - h + 10))
        dark = black_share((cx + h - 10, cy + h - 10, cx + h + 10, cy + h + 10))
        assert dark > lit + 0.2

    def test_tears_never_cut_the_transcript(self, monkeypatch):
        """Tracking tears shear the feed only — the panel is painted after
        them, so neutering the tears leaves the panel byte-identical."""
        torn = self._render()
        monkeypatch.setattr(rq, "_observation_paint_tears", lambda image: None)
        clean = self._render()
        assert pixel_bytes(torn.crop(rq._OBSERVATION_PANEL)) == pixel_bytes(clean.crop(rq._OBSERVATION_PANEL))
        assert pixel_bytes(torn) != pixel_bytes(clean)

    def test_phrase_is_yellow_with_a_tangerine_halo(self, monkeypatch):
        """The matched phrase is a yellow core in a red+yellow halo that only
        ever lands on black — the white prose is never overwritten."""
        red, yellow, white = rq.SPECTRA6["red"], rq.SPECTRA6["yellow"], rq.SPECTRA6["white"]
        qbox = rq._OBSERVATION_QUOTE_RECT
        with_halo = self._render().crop(qbox)
        original = rq.paint_neon_mask

        def core_only(image, mask, core, glow, **kwargs):
            kwargs["cap"] = 0.0
            return original(image, mask, core, glow, **kwargs)

        monkeypatch.setattr(rq, "paint_neon_mask", core_only)
        without = self._render().crop(qbox)
        assert ink_counts(without).get(red, 0) == 0
        assert ink_counts(with_halo).get(red, 0) > 0
        assert ink_counts(with_halo).get(yellow, 0) > ink_counts(without).get(yellow, 0)
        white_mask = without.convert("L").point(lambda v: 255 if v == 255 else 0)
        under = Image.composite(with_halo, Image.new("RGB", with_halo.size, white), white_mask)
        assert distinct_inks(under) == {white}, "halo overwrote prose"

    def test_lit_module_matches_the_camera(self):
        """The station schematic lights exactly one module — the camera's."""
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["black"])
        rq._observation_paint_map(ImageDraw.Draw(image), 7)
        x0, y0, x1, y1 = rq._OBSERVATION_MAP_RECT
        n = len(rq._OBSERVATION_MODULES)
        step = (x1 - x0 - 12) / (n - 1)
        yellow = rq.SPECTRA6["yellow"]
        lit = [i for i in range(n)
               if yellow in distinct_inks(image.crop((round(x0 + 6 + i * step) - 8, y0 - 2,
                                                      round(x0 + 6 + i * step) + 8, y1 + 2)))]
        assert lit == [rq._observation_module_index(7)]

    def test_unattributed_log_and_missing_title(self):
        row = {**self.ROW, "author": "", "title": ""}
        assert rq._observation_log_header(make_row(**row)) == "AUDIO LOG — UNATTRIBUTED"
        assert rq._observation_log_header(make_row(**self.ROW)) == "AUDIO LOG — JANE AUSTEN"
        image = self._render(row)
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())


class TestTrisolarisFrame:
    """``trisolaris`` — Liu Cixin's *The Three-Body Problem*.

    Three suns and a planet integrated under Newtonian gravity from committed
    initial conditions, advanced by the clock; the era and the civilization
    count are read off the integration; the Red Coast dish on Radar Peak; the
    quote in the dark sky with the matched phrase lit as sunlight.
    """

    ROW = dict(
        display_quote="The clock was striking ten when he came back, and the whole "
                      "house seemed asleep; only the stars were awake over the river.",
        matched_text="striking ten",
        author="H. G. Wells",
        title="The Time Machine",
        source_id="35",
        line_number=646,
    )

    @staticmethod
    def _render(row=None, time_str="10:00"):
        return rq.render(time_str, make_row(**(row or TestTrisolarisFrame.ROW)),
                         800, 480, mode="production", theme="trisolaris")

    @staticmethod
    def _dial_indices():
        return [rq._trisolaris_index(f"{h:02d}:{m:02d}") for h in range(12) for m in range(60)]

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert "trisolaris" in rq.THEMES
        assert "trisolaris" in rq.THEME_ORDER
        assert "trisolaris" not in rq.CYCLE_EXCLUDED_THEMES
        assert display_inky.THEME_SATURATION["trisolaris"] == 0.7
        assert rq.theme_font_candidates("trisolaris", "quote_regular")[0] == rq.TITILLIUM_REGULAR
        assert rq.theme_font_candidates("trisolaris", "quote_bold")[0] == rq.TITILLIUM_SEMIBOLD
        for path in (rq.TITILLIUM_REGULAR, rq.TITILLIUM_SEMIBOLD, rq.TITILLIUM_BOLD, rq.TITILLIUM_ITALIC):
            assert pathlib.Path(path).exists()
        assert (pathlib.Path(rq.TITILLIUM_REGULAR).parent / "OFL.txt").exists()

    def test_frame_is_on_palette_and_deterministic(self):
        image = self._render()
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_the_clock_drives_the_sky(self):
        """Noon and midnight both start the dial, so the same minute past
        either renders identically; a different minute moves the suns."""
        assert pixel_bytes(self._render(time_str="00:30")) == pixel_bytes(self._render(time_str="12:30"))
        orrery = (0, 0, 446, 380)
        a = self._render(time_str="09:00").crop(orrery)
        b = self._render(time_str="09:05").crop(orrery)
        assert pixel_bytes(a) != pixel_bytes(b)

    def test_the_suns_stay_in_the_system_all_day(self):
        """The committed initial conditions were searched for a dance that
        stays bound across the whole dial. A generic three-body start ejects
        a sun within a few dozen crossing times, so any change to the
        constants, masses or step that lets one escape fails here — and the
        projection, which fits the suns' whole-day paths, would otherwise
        shrink the remaining two to a speck."""
        for sample in rq._trisolaris_ephemeris():
            for x, y in sample[0]:
                assert x * x + y * y < 2.5 * 2.5

    def test_barycentre_is_fixed_at_the_origin(self):
        """Zero total momentum is conserved exactly by pairwise-symmetric
        forces under leapfrog, so the mass-weighted centre stays at the
        origin — the point the dish's transmission is aimed at. Drift here
        means the integrator or the initial conditions were mangled."""
        masses = rq._TRISOLARIS_MASSES
        total = sum(masses)
        for sample in rq._trisolaris_ephemeris():
            cx = sum(m * s[0] for m, s in zip(masses, sample[0])) / total
            cy = sum(m * s[1] for m, s in zip(masses, sample[0])) / total
            assert abs(cx) < 1e-9 and abs(cy) < 1e-9

    def test_both_eras_occur_and_neither_dominates(self):
        """The era is physics, not decoration — so the day must actually
        contain both, each for a real share of the dial's buckets."""
        stable = [rq._trisolaris_era(f"{h:02d}:{m:02d}")[0] for h in range(12) for m in range(0, 60, 5)]
        share = sum(stable) / len(stable)
        assert 0.3 <= share <= 0.8, share
        switches = sum(1 for a, b in zip(stable, stable[1:]) if a != b)
        assert switches >= 6

    def test_civilizations_are_lost_across_the_day(self):
        """The counter starts at ``_TRISOLARIS_FIRST_CIVILIZATION`` at the
        start of the preroll, never goes backwards within the dial, and a
        handful of civilizations are destroyed between noon and midnight."""
        ephemeris = rq._trisolaris_ephemeris()
        assert ephemeris[0][3] == 0
        counts = [ephemeris[i][3] for i in self._dial_indices()]
        assert counts == sorted(counts)
        assert 3 <= counts[-1] - counts[0] <= 25
        assert rq._trisolaris_era("00:00")[1] == rq._TRISOLARIS_FIRST_CIVILIZATION + counts[0]

    def test_the_planet_never_leaves_the_system(self):
        """A lost planet is reborn on the very next sample, so every stored
        planet position is within the loss radius plus one sample's travel."""
        for sample in rq._trisolaris_ephemeris():
            px_, py_ = sample[1]
            assert px_ * px_ + py_ * py_ < rq._TRISOLARIS_LOST_RADIUS2 * 1.5

    def test_the_planet_trail_breaks_at_a_rebirth(self):
        """A new civilization begins in a new orbit; the jump between the two
        is not a path the planet travelled and must not be drawn. The planet's
        trail is the only white the orbit painter lays down, so the dead
        planet's last position must stay dark just after a rebirth."""
        ephemeris = rq._trisolaris_ephemeris()
        clip = rq._TRISOLARIS_ORRERY_CLIP
        checked = 0
        for k in range(1, len(ephemeris) - 3):
            if ephemeris[k][3] == ephemeris[k - 1][3]:
                continue
            old = rq._trisolaris_project(ephemeris[k - 1][1])
            new = rq._trisolaris_project(ephemeris[k][1])
            inside = clip[0] + 4 <= old[0] < clip[2] - 4 and clip[1] + 4 <= old[1] < clip[3] - 4
            if not inside or math.dist(old, new) < 40:
                continue
            image = Image.new("RGB", (800, 480), rq.SPECTRA6["black"])
            rq._trisolaris_paint_orbits(image, k + 2)
            window = image.crop((int(old[0]) - 3, int(old[1]) - 3, int(old[0]) + 4, int(old[1]) + 4))
            assert rq.SPECTRA6["white"] not in distinct_inks(window), f"trail crosses rebirth at sample {k}"
            checked += 1
        assert checked >= 1, "no rebirth landed far enough from its predecessor to test"

    def test_integration_is_identical_in_a_fresh_process(self):
        """The ephemeris uses only correctly rounded operations, so a fresh
        interpreter (with a different hash seed) must reproduce it bit for bit
        — the property the golden fixture and run_clock's dedup depend on."""
        import os
        import subprocess
        import sys
        code = ("from idle_hours import render_quote as rq; e = rq._trisolaris_ephemeris(); "
                "print(repr(e[-1]), len(e))")
        env = dict(os.environ, PYTHONHASHSEED="12345")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             env=env, check=True).stdout.strip()
        ephemeris = rq._trisolaris_ephemeris()
        assert out == f"{ephemeris[-1]!r} {len(ephemeris)}"

    def test_the_matched_phrase_is_the_only_sunlight_in_the_column(self):
        """Yellow in the quote rect comes from the matched phrase and nothing
        else: stars are kept out of it, and a row with no phrase paints none."""
        yellow = rq.SPECTRA6["yellow"]
        rect = rq._TRISOLARIS_QUOTE_RECT
        assert yellow in distinct_inks(self._render().crop(rect))
        plain = self._render({**self.ROW, "matched_text": ""})
        assert yellow not in distinct_inks(plain.crop(rect))

    def test_era_header_follows_the_physics(self):
        """A stable and a chaotic minute paint different headers, and the
        header's text comes from ``_trisolaris_era``."""
        eras = {}
        for h in range(12):
            for m in range(0, 60, 5):
                t = f"{h:02d}:{m:02d}"
                eras.setdefault(rq._trisolaris_era(t)[0], t)
        assert set(eras) == {True, False}
        header = (rq._TRISOLARIS_COLUMN[0], 0, 800, 108)
        stable = self._render(time_str=eras[True]).crop(header)
        chaotic = self._render(time_str=eras[False]).crop(header)
        assert pixel_bytes(stable) != pixel_bytes(chaotic)

    def test_stars_stay_out_of_the_text_column(self):
        """A star beside a letterform reads as a stroke of it, so the whole
        column — masthead, header chrome, quote, byline, warning — is starless.
        Excluding only the quote block left 26 stars inside the header and
        footer text on the committed seed."""
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["black"])
        rq._trisolaris_paint_sky(image)
        column = image.crop((rq._TRISOLARIS_COLUMN[0] - 10, 0, 800, 480))
        assert distinct_inks(column) == {rq.SPECTRA6["black"]}
        assert rq.SPECTRA6["white"] in distinct_inks(image), "the star field painted nothing"

    def test_the_dish_aims_at_the_barycentre(self):
        """The transmission is aimed where the suns dance: the dish axis from
        its pivot passes through the projected origin of the integration."""
        ridge = rq._trisolaris_ridge_y(rq._TRISOLARIS_DISH_X)
        _, _, _, pivot, _, (ux, uy) = rq._trisolaris_dish_geometry(ridge)
        tx, ty = rq._trisolaris_project((0.0, 0.0))
        bearing = math.atan2(ty - pivot[1], tx - pivot[0])
        assert abs(math.atan2(uy, ux) - bearing) < 1e-9

    def test_rebirth_is_circular_under_the_softened_force(self):
        """The reborn planet's speed relative to its home sun is the circular
        speed of the force law it actually feels: v^2 / r equals the softened
        pull. The Keplerian sqrt(m / r) is ~5% fast and starts an eccentric
        orbit."""
        pos = [[0.0, 0.0], [40.0, 0.0], [41.0, 0.0]]       # sun 0 is the most isolated
        vel = [[0.1, -0.2], [0.0, 0.0], [0.0, 0.0]]
        p, pv = rq._trisolaris_rebirth(pos, vel)
        r = math.dist(p, pos[0])
        v = math.dist(pv, vel[0])
        assert abs(r - rq._TRISOLARIS_REBIRTH_RADIUS) < 1e-12
        softened_pull = rq._TRISOLARIS_MASSES[0] * r / (r * r + rq._TRISOLARIS_PLANET_SOFTENING2) ** 1.5
        assert abs(v * v / r - softened_pull) < 1e-9
        assert v < math.sqrt(rq._TRISOLARIS_MASSES[0] / r) * 0.97

    def test_no_planet_survives_a_pass_inside_a_sun(self, monkeypatch):
        """The death check runs on every leapfrog step, not every sample.

        Stored samples cannot show this — they are taken after the check under
        either scheme — so watch the integrator itself: every force evaluation
        that finds the planet inside a sun's burn radius must be followed
        immediately by a rebirth. A sample-boundary check let one planet per
        day pass through a sun and out again between samples.
        """
        events = []
        accel, rebirth = rq._trisolaris_planet_accel, rq._trisolaris_rebirth

        def watched_accel(p, pos):
            inside = any((p[0] - x) ** 2 + (p[1] - y) ** 2 < rq._TRISOLARIS_BURN_RADIUS2 for x, y in pos)
            events.append(inside)
            return accel(p, pos)

        def watched_rebirth(pos, vel):
            events.append("rebirth")
            return rebirth(pos, vel)

        monkeypatch.setattr(rq, "_trisolaris_planet_accel", watched_accel)
        monkeypatch.setattr(rq, "_trisolaris_rebirth", watched_rebirth)
        monkeypatch.setattr(rq, "_TRISOLARIS_EPHEMERIS", None)
        rq._trisolaris_ephemeris()
        burns = [k for k, e in enumerate(events) if e is True]
        assert burns, "no planet ever came inside a sun — the fence proves nothing"
        for k in burns:
            assert events[k + 1] == "rebirth", f"planet survived a pass inside a sun at evaluation {k}"

    def test_malformed_time_falls_back_to_the_start_of_the_dial(self):
        assert rq._trisolaris_index("garbage") == rq._trisolaris_index("00:00")
        image = rq.render("garbage", make_row(**self.ROW), 800, 480, mode="production", theme="trisolaris")
        assert image.size == (800, 480)
class TestShadeHeightField:
    """``shade_height_field`` — a procedural height field lit Blinn-Phong.

    The failure worth fencing is silent: a flipped Sobel sign still renders a
    plausible-looking relief, just lit from the wrong corner, and nothing else
    in the suite would notice.
    """

    @staticmethod
    def _ramp(axis: str) -> Image.Image:
        image = Image.new("L", (9, 9))
        image.putdata([(x if axis == "x" else y) * 10 for y in range(9) for x in range(9)])
        return image

    def test_sobel_kernels_read_as_positive_slopes(self):
        """Measured against ramps: ``ImageFilter.Kernel`` reverses its rows but
        not its columns, so the Y weights look upside down on purpose."""
        x_ramp, y_ramp = self._ramp("x"), self._ramp("y")
        assert x_ramp.filter(rq._SOBEL_X).getpixel((4, 4)) == 128 + 40
        assert x_ramp.filter(rq._SOBEL_Y).getpixel((4, 4)) == 128
        assert y_ramp.filter(rq._SOBEL_Y).getpixel((4, 4)) == 128 + 40
        assert y_ramp.filter(rq._SOBEL_X).getpixel((4, 4)) == 128

    def test_flat_field_shades_to_ambient_plus_diffuse_lz(self):
        light = (-0.55, -0.62, 0.56)
        norm = math.sqrt(sum(c * c for c in light))
        tone = rq.shade_height_field(Image.new("L", (16, 16), 90), light=light,
                                     ambient=0.1, diffuse=0.8, specular=0.0)
        expected = round((0.1 + 0.8 * light[2] / norm) * 255)
        assert abs(tone.getpixel((8, 8)) - expected) <= 1

    def test_dome_is_lit_from_the_upper_left(self):
        from PIL import ImageFilter
        field = Image.new("L", (120, 120), 0)
        ImageDraw.Draw(field).ellipse((20, 20, 100, 100), fill=255)
        tone = rq.shade_height_field(field.filter(ImageFilter.GaussianBlur(10)), specular=0.0)
        upper_left = tone.crop((28, 28, 44, 44))
        lower_right = tone.crop((76, 76, 92, 92))
        def mean(im):
            hist = im.histogram()
            return sum(i * c for i, c in enumerate(hist)) / sum(hist)

        assert mean(upper_left) > mean(lower_right) + 60

    def test_specular_glint_is_brighter_than_diffuse_alone(self):
        from PIL import ImageFilter
        field = Image.new("L", (120, 120), 0)
        ImageDraw.Draw(field).ellipse((20, 20, 100, 100), fill=255)
        field = field.filter(ImageFilter.GaussianBlur(10))
        matte = rq.shade_height_field(field, specular=0.0)
        glossy = rq.shade_height_field(field, specular=0.9)
        assert glossy.getextrema()[1] > matte.getextrema()[1]
        assert glossy.getextrema()[1] == 255

    def test_lookup_table_is_memoised_per_parameter_set(self):
        a = rq._height_field_lut((-0.5, -0.5, 0.7), 0.02, 0.1, 0.8, 0.5, 20.0)
        assert rq._height_field_lut((-0.5, -0.5, 0.7), 0.02, 0.1, 0.8, 0.5, 20.0) is a
        assert len(a) == 65536


class TestBiomechFrame:
    """``biomech`` — H. R. Giger's wall round a Zdzisław Beksiński dusk.

    A lit, K+W-dithered biomechanical height field frames a pointed arch; a
    procedurally painted dusk and ruin are dithered to K/R/Y/W behind it. The
    hour is the Roman numeral on the sill plate.
    """

    ROW = dict(
        display_quote="It was about half past two when the clock struck and the "
                      "afternoon light came slanting through the tall windows.",
        matched_text="half past two",
        author="Jane Austen",
        title="Emma",
        source_id="158",
        line_number=482,
    )

    @staticmethod
    def _render(row=None, time_str="14:30", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or TestBiomechFrame.ROW)),
                         *size, mode="production", theme="biomech")

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert "biomech" in rq.THEMES
        assert "biomech" in rq.THEME_ORDER
        assert "biomech" not in rq.CYCLE_EXCLUDED_THEMES
        assert display_inky.THEME_SATURATION["biomech"] == 0.7
        assert rq.theme_font_candidates("biomech", "quote_regular")[0] == rq.SPECTRAL_MEDIUM
        assert rq.theme_font_candidates("biomech", "quote_bold")[0] == rq.SPECTRAL_SEMIBOLD
        for path in (rq.SPECTRAL_MEDIUM, rq.SPECTRAL_SEMIBOLD, rq.SPECTRAL_MEDIUM_ITALIC,
                     rq.GRENZE_GOTISCH_VARIABLE):
            assert pathlib.Path(path).exists(), path
            assert (pathlib.Path(path).parent / "OFL.txt").exists()

    @pytest.mark.parametrize("time_str,hour", [
        ("00:30", 12), ("12:00", 12), ("13:05", 1), ("01:59", 1), ("21:15", 9), ("bogus", 12),
    ])
    def test_hour_is_the_twelve_hour_clock_hour(self, time_str, hour):
        assert rq._biomech_hour(time_str) == hour

    def test_minute_never_reaches_the_frame(self):
        """Hour only: the plate's numeral carries the hour and the matched
        phrase the minute, so every minute of an hour renders byte-identically."""
        first = pixel_bytes(self._render(time_str="14:00"))
        for time_str in ("14:07", "14:30", "14:59", "02:45"):
            assert pixel_bytes(self._render(time_str=time_str)) == first

    def test_hour_changes_only_the_plate(self):
        a, b = self._render(time_str="14:30"), self._render(time_str="15:30")
        assert pixel_bytes(a) != pixel_bytes(b)
        diff = ImageChops.difference(a, b).getbbox()
        x0, y0, x1, y1 = rq._BIOMECH_PLATE
        assert diff[0] >= x0 and diff[1] >= y0 and diff[2] <= x1 + 1 and diff[3] <= y1 + 1

    def test_on_palette_deterministic_and_the_fire_never_cools(self):
        """Black, white, red and yellow only: blue or green anywhere would mean
        error diffusion cooled the dusk or chroma leaked into the bone."""
        image = self._render()
        assert distinct_inks(image) == {rq.SPECTRA6[n] for n in ("black", "white", "red", "yellow")}
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_wall_is_monochrome_bone_with_a_red_rim(self):
        """The wall dithers to K+W; red appears only as rim light, sparse, and
        concentrated on the side facing the portal."""
        image = self._render()
        left = rq._BIOMECH_ARCH[0]
        pier = image.crop((0, 120, left, 440))
        counts = ink_counts(pier)
        assert set(counts) <= {rq.SPECTRA6[n] for n in ("black", "white", "red")}
        red = rq.SPECTRA6["red"]
        total = sum(counts.values())
        assert 0 < counts.get(red, 0) < 0.12 * total
        outer = ink_counts(image.crop((0, 120, 30, 440))).get(red, 0)
        inner = ink_counts(image.crop((left - 30, 120, left, 440))).get(red, 0)
        assert inner > 3 * outer

    def test_quote_rect_lies_inside_the_opening(self):
        x0, y0, x1, y1 = rq._BIOMECH_QUOTE_RECT
        left, right, *_ = rq._BIOMECH_ARCH
        cx = (left + right) / 2
        for y in (y0 + 14, (y0 + y1) / 2, y1):
            assert cx - rq._biomech_arch_halfwidth(y) <= x0
            assert cx + rq._biomech_arch_halfwidth(y) >= x1

    def test_sun_and_cloud_stay_above_the_horizon(self):
        """The ground below the horizon is only the ground gradient: the sun is
        half set, not a disc lying on the plain."""
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["black"])
        rq._biomech_paint_sky(image)
        ground = image.crop((0, rq._BIOMECH_HORIZON + 1, 800, 480))
        ceiling = max(rq._BIOMECH_GROUND_STOPS[0][1])
        assert max(band_max for _, band_max in ground.getextrema()) <= ceiling
        sx, sy, sr = rq._BIOMECH_SUN
        assert image.getpixel((sx, sy - sr // 2)) == (255, 244, 206)

    def test_zenith_is_black_behind_the_quote(self):
        """The top of the sky dithers to solid black, so the halo'd prose sits
        on night rather than on a speckle."""
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["black"])
        rq._biomech_paint_sky(image)
        top = rq.dither_image_to_palette(image, rq._BIOMECH_SCENE_PALETTE).crop((200, 0, 600, 160))
        assert distinct_inks(top) == {rq.SPECTRA6["black"]}

    def test_phrase_is_an_ember_that_never_overwrites_prose(self, monkeypatch):
        """Yellow core, red bloom landing only on black."""
        red, yellow, white = rq.SPECTRA6["red"], rq.SPECTRA6["yellow"], rq.SPECTRA6["white"]
        qbox = rq._BIOMECH_QUOTE_RECT
        with_halo = self._render().crop(qbox)
        original = rq.paint_neon_mask

        def core_only(image, mask, core, glow, **kwargs):
            kwargs["cap"] = 0.0
            return original(image, mask, core, glow, **kwargs)

        monkeypatch.setattr(rq, "paint_neon_mask", core_only)
        without = self._render().crop(qbox)
        assert ink_counts(with_halo).get(red, 0) > ink_counts(without).get(red, 0)
        assert ink_counts(with_halo).get(yellow, 0) > 0
        white_mask = without.convert("L").point(lambda v: 255 if v == 255 else 0)
        under = Image.composite(with_halo, Image.new("RGB", with_halo.size, white), white_mask)
        assert distinct_inks(under) == {white}, "bloom overwrote prose"

    def test_background_cache_respects_a_patched_painter(self, monkeypatch):
        """The painted background is cached, but a neutered painter must still
        change the frame — otherwise the decoration fences measure the cache."""
        painted = pixel_bytes(self._render())
        monkeypatch.setattr(rq, "_biomech_paint_wall", lambda image, opening: None)
        assert pixel_bytes(self._render()) != painted
        monkeypatch.undo()
        assert pixel_bytes(self._render()) == painted

    def test_bare_row_renders(self):
        row = {**self.ROW, "author": "", "title": "", "source_id": None}
        image = self._render(row)
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())


class TestCodexFrame:
    """``codex`` — a page of Luigi Serafini's *Codex Seraphinianus*.

    A chimerical plant plate, columns of generated asemic script, the quote as
    the page's one deciphered passage, and the time as a base-21 page number in
    invented numerals.
    """

    ROW = dict(
        display_quote="It was about half past two when the clock struck and the "
                      "afternoon light came slanting through the tall windows.",
        matched_text="half past two",
        author="Jane Austen",
        title="Emma",
        source_id="158",
        line_number=482,
    )
    # Bottom-right page-number corner: the only region the clock may reach.
    FOLIO_BOX = (640, 436, 800, 480)

    @staticmethod
    def _render(row=None, time_str="14:30", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or TestCodexFrame.ROW)),
                         *size, mode="production", theme="codex")

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert "codex" in rq.THEMES
        assert "codex" in rq.THEME_ORDER
        assert "codex" not in rq.CYCLE_EXCLUDED_THEMES
        assert display_inky.THEME_SATURATION["codex"] == 0.5
        # Pen hand for the body, its italic for the phrase: no bold cut exists.
        assert rq.theme_font_candidates("codex", "quote_regular")[0] == rq.FONDAMENTO_REGULAR
        assert rq.theme_font_candidates("codex", "quote_bold")[0] == rq.FONDAMENTO_ITALIC
        for path in (rq.FONDAMENTO_REGULAR, rq.FONDAMENTO_ITALIC):
            assert pathlib.Path(path).exists()
        assert (pathlib.Path(rq.FONDAMENTO_REGULAR).parent / "OFL.txt").exists()

    def test_on_palette_and_deterministic(self):
        first = self._render()
        assert distinct_inks(first) <= set(rq.SPECTRA6_PALETTE)
        assert pixel_bytes(first) == pixel_bytes(self._render())

    def test_plate_surfaces_every_native_ink(self):
        """The vibrancy is the plate's job, so the check is scoped to the plate.

        Measured across the whole page this passed with the plate deleted
        outright — the rainbow, the cream wash and the text already put all six
        inks on the page. Inside the plate's crop the page alone contributes
        only white and yellow.
        """
        plate = self._render().crop(rq._CODEX_PLATE)
        assert distinct_inks(plate) == set(rq.SPECTRA6_PALETTE)

    def test_script_stays_inside_its_reach(self):
        """Every letter and diacritic lies within the documented reach of its
        baseline; the page's line pitch is computed from these bounds."""
        import random as _random
        above, below = rq._CODEX_REACH_ABOVE, rq._CODEX_REACH_BELOW
        img = Image.new("L", (420, 120), 0)
        draw = ImageDraw.Draw(img)
        base = 60
        for seed in range(400):
            draw.rectangle((0, 0, 420, 120), fill=0)
            xh = 5 if seed % 2 else 8
            width = 1 if xh == 5 else 2
            rq._codex_script(draw, 8, base, 400, xh=xh, rng=_random.Random(seed),
                             fill=255, width=width)
            bbox = img.getbbox()
            slack = width
            assert bbox[1] >= base - above * xh - slack, (seed, bbox)
            assert bbox[3] <= base + below * xh + slack + 1, (seed, bbox)

    def test_stacked_script_lines_cannot_collide(self):
        """An ascender on one line must not be able to reach the descender of
        the line above: pitch >= below*xh_upper + above*xh_lower."""
        above, below = rq._CODEX_REACH_ABOVE, rq._CODEX_REACH_BELOW
        xh = rq._CODEX_BODY_XH
        heading_base, heading_xh = rq._CODEX_HEADING
        stacks = [
            [(heading_base, heading_xh)] + [(b, xh) for b in rq._CODEX_UPPER_LINES],
            [(b, xh) for b in rq._CODEX_LOWER_LINES],
        ]
        for stack in stacks:
            for (upper, uxh), (lower, lxh) in zip(stack, stack[1:]):
                assert lower - upper >= below * uxh + above * lxh, (upper, lower)
        # And the text blocks clear the quote rect above and below.
        top, bottom = rq._CODEX_QUOTE_RECT[1], rq._CODEX_QUOTE_RECT[3]
        assert rq._CODEX_UPPER_LINES[-1] + below * xh < top
        assert rq._CODEX_LOWER_LINES[0] - above * xh > bottom

    def test_plate_caption_clears_the_roots(self):
        """The caption was once written straight through the root spirals."""
        import random as _random
        top_of_caption = rq._CODEX_CAPTION_BASE - rq._CODEX_REACH_ABOVE * rq._CODEX_BODY_XH - 1
        for seed in range(50):
            img = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
            bbox = rq._codex_paint_roots(img, ImageDraw.Draw(img), _random.Random(seed))
            assert bbox[3] < top_of_caption, (seed, bbox, top_of_caption)
        # Caption's own reach stays on the canvas.
        assert rq._CODEX_CAPTION_BASE + rq._CODEX_REACH_BELOW * rq._CODEX_BODY_XH < 480

    def test_roots_carry_the_sepia_recipe(self):
        """Filled through a mask with the R+G recipe, not a red post-pass: the
        roots are a checkerboard of the two inks and nothing else."""
        import random as _random
        img = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        bbox = rq._codex_paint_roots(img, ImageDraw.Draw(img), _random.Random(7))
        below_ground = img.crop((0, rq._CODEX_STEM_BASE[1] + 4, 800, bbox[3]))
        counts = ink_counts(below_ground)
        red, green = counts.get(rq.SPECTRA6["red"], 0), counts.get(rq.SPECTRA6["green"], 0)
        assert red and green and 0.8 < red / green < 1.25, counts
        assert set(counts) <= {rq.SPECTRA6["red"], rq.SPECTRA6["green"], rq.SPECTRA6["white"]}

    def test_fish_leaf_reports_its_nose(self):
        """The dotted leaders point at the returned nose, so it must be on the
        fish's own contour."""
        img = Image.new("RGB", (400, 300), rq.SPECTRA6["white"])
        nx, ny = rq._codex_paint_fish_leaf(img, ImageDraw.Draw(img), 120, 200, 1,
                                           rq._CODEX_LEAF_FILLS[0], 30)
        near = img.crop((int(nx) - 2, int(ny) - 2, int(nx) + 3, int(ny) + 3))
        assert rq.SPECTRA6["black"] in distinct_inks(near)
        assert nx > 120 and ny < 200          # up and out from the stem

    @pytest.mark.parametrize("time_str", ["00:00", "00:21", "07:21", "19:47", "23:59"])
    def test_folio_is_right_aligned_whatever_the_digits(self, time_str):
        """The folio is laid out from the digits' real advances. Zero's ring is
        narrower than the other glyphs, so assuming one fixed advance let the
        page number's right margin drift with how many zeros the minute had."""
        img = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        end = rq._codex_paint_folio(ImageDraw.Draw(img), time_str)
        assert end == pytest.approx(rq._CODEX_COLUMN[1])

    @pytest.mark.parametrize("time_str, digits", [
        ("00:00", [0]),
        ("00:20", [20]),
        ("00:21", [1, 0]),
        ("07:21", [1, 0, 0]),          # 441 minutes = 21 squared
        ("23:59", [3, 5, 11]),         # 1439 = 3*441 + 5*21 + 11
    ])
    def test_page_digits_are_base_21(self, time_str, digits):
        assert rq.codex_page_digits(time_str) == digits

    def test_page_number_round_trips_every_minute(self):
        """A determined reader can decode the folio back to the time."""
        for minute in range(24 * 60):
            time_str = f"{minute // 60:02d}:{minute % 60:02d}"
            digits = rq.codex_page_digits(time_str)
            assert 1 <= len(digits) <= 3
            assert all(0 <= d < 21 for d in digits)
            value = 0
            for d in digits:
                value = value * 21 + d
            assert value == minute

    def test_numerals_are_twenty_one_distinct_glyphs(self):
        """A numeral system needs every digit to be its own glyph, and the same
        digit always drawn the same way."""
        glyphs = []
        for digit in range(21):
            img = Image.new("L", (40, 40), 0)
            rq._codex_numeral(ImageDraw.Draw(img), 10, 30, digit, size=20, fill=255)
            glyphs.append(img.tobytes())
            again = Image.new("L", (40, 40), 0)
            rq._codex_numeral(ImageDraw.Draw(again), 10, 30, digit, size=20, fill=255)
            assert again.tobytes() == glyphs[-1]
            assert img.getbbox() is not None, f"digit {digit} draws nothing"
        assert len(set(glyphs)) == 21

    def test_time_reaches_only_the_folio(self):
        """The page number is the time carrier; nothing else on the page may
        move with the clock, or the frame would be a clock face rather than an
        encyclopedia page."""
        a = self._render(time_str="02:30")
        b = self._render(time_str="19:47")
        bbox = ImageChops.difference(a, b).getbbox()
        assert bbox is not None, "the page number must change with the time"
        x0, y0, x1, y1 = self.FOLIO_BOX
        assert bbox[0] >= x0 and bbox[1] >= y0 and bbox[2] <= x1 and bbox[3] <= y1, bbox

    def test_each_quote_gets_its_own_page_of_script(self):
        other = dict(self.ROW, source_id="1342", line_number=99)
        a = self._render()
        b = self._render(row=other)
        column = (344, 40, 660, 140)          # the script paragraph above the quote
        assert pixel_bytes(a.crop(column)) != pixel_bytes(b.crop(column))

    def test_script_never_overruns_its_line(self):
        """The word budget is the worst case, so the ink provably stops at
        ``x_end`` — a script line must not run into the rainbow vignette or off
        the column."""
        import random as _random
        # Many short lines rather than a few long ones: an overrun is a
        # worst-case event (every letter in the last word drawn at its widest),
        # so the fence needs many line ends to sample it. Verified to fail with
        # the word overhead zeroed.
        img = Image.new("L", (160, 60), 0)
        draw = ImageDraw.Draw(img)
        for seed in range(1500):
            draw.rectangle((0, 0, 160, 60), fill=0)
            x_end = 40 + seed % 90
            rq._codex_script(draw, 8, 36, x_end, xh=4 + seed % 5,
                             rng=_random.Random(seed), fill=255)
            bbox = img.getbbox()
            assert bbox is None or bbox[2] <= x_end + 2, (seed, x_end, bbox)

    def test_matched_phrase_is_red(self):
        with_phrase = self._render()
        without = self._render(row=dict(self.ROW, matched_text=""))
        rect = rq._CODEX_QUOTE_RECT
        red = rq.SPECTRA6["red"]
        count = ink_counts(with_phrase.crop(rect)).get(red, 0)
        base = ink_counts(without.crop(rect)).get(red, 0)
        assert count > base + 150

    def test_bare_row_renders(self):
        """No author, no title, no source: the byline is simply omitted."""
        img = rq.render_codex_frame("02:30", {"display_quote": "At half past two the moon rose.",
                                              "matched_text": "half past two"}, 800, 480)
        assert distinct_inks(img) <= set(rq.SPECTRA6_PALETTE)


class TestCultureFrame:
    """``culture`` — a Mind's signal beside the Orbital it concerns.

    Black space; the signal header, body and relay line on the left; a tilted
    Orbital on the right whose marked plate keeps the local time; and the
    matched phrase again in Marain-idiom glyphs.
    """

    ROW = dict(
        display_quote="It was about half past two when the clock struck and the "
                      "afternoon light came slanting through the tall windows.",
        matched_text="half past two",
        author="Jane Austen",
        title="Emma",
        source_id="158",
        line_number=482,
    )

    @staticmethod
    def _render(row=None, time_str="14:30", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or TestCultureFrame.ROW)),
                         *size, mode="production", theme="culture")

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert "culture" in rq.THEMES
        assert "culture" in rq.THEME_ORDER
        assert "culture" not in rq.CYCLE_EXCLUDED_THEMES
        assert display_inky.THEME_SATURATION["culture"] == 0.7
        assert rq.theme_font_candidates("culture", "quote_regular")[0] == rq.JURA_MEDIUM
        assert rq.theme_font_candidates("culture", "quote_bold")[0] == rq.JURA_BOLD
        for path in (rq.JURA_REGULAR, rq.JURA_MEDIUM, rq.JURA_SEMIBOLD, rq.JURA_BOLD,
                     rq.SHARETECHMONO_REGULAR):
            assert pathlib.Path(path).exists(), path
            assert (pathlib.Path(path).parent / "OFL.txt").exists(), path

    @pytest.mark.parametrize("time_str,clock", [
        ("00:00", 0.0), ("12:00", 0.5), ("06:00", 0.25), ("18:30", 18.5 / 24), ("bogus", 0.5),
    ])
    def test_clock_is_the_full_day(self, time_str, clock):
        assert rq._culture_clock(time_str) == pytest.approx(clock)

    def test_noon_plate_faces_the_sun_and_midnight_plate_faces_away(self):
        """The marked plate's own sun angle equals the local clock: overhead at
        noon (on the lit far arc), opposite at midnight (round on the hull)."""
        noon = rq._culture_plate_theta(0.5)
        midnight = rq._culture_plate_theta(0.0)
        assert math.cos(noon - rq._CULTURE_NOON) == pytest.approx(1.0)
        assert math.cos(midnight - rq._CULTURE_NOON) == pytest.approx(-1.0)
        assert math.sin(noon) < 0, "the noon plate should be on the far arc, facing us"
        assert math.sin(midnight) > 0, "the midnight plate should be on the near arc"

    @pytest.mark.parametrize("hour", range(24))
    def test_marker_is_on_the_lit_face_by_day_and_the_hull_by_night(self, hour):
        """The far arc (sin < 0) shows the inner face; it must hold exactly the
        plates in daylight, or the afternoon marker lands on a black hull."""
        side = math.sin(rq._culture_plate_theta((hour + 0.5) / 24))
        if 6 <= hour < 18:
            assert side < 0, f"{hour}:30 is daytime but the marker is on the hull"
        else:
            assert side > 0, f"{hour}:30 is night but the marker is on the lit face"

    def test_marker_goes_round_once_a_day(self):
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["black"])
        draw = ImageDraw.Draw(image)
        spots = {rq._culture_paint_marker(image, draw, h / 24, "HERE") for h in range(24)}
        assert len(spots) == 24, "every hour should put the plate somewhere new"
        assert rq._culture_plate_theta(0.0) == pytest.approx(rq._culture_plate_theta(1.0) - 2 * math.pi)

    def test_time_reaches_only_the_orbital(self):
        """The signal column is the row's; only the ring side moves with the clock."""
        a, b = self._render(time_str="03:00"), self._render(time_str="15:45")
        column = (0, 0, rq._CULTURE_TEXT_X[1] + 4, 480)
        assert pixel_bytes(a.crop(column)) == pixel_bytes(b.crop(column))
        assert pixel_bytes(a) != pixel_bytes(b)

    def test_signal_follows_the_row_and_names_two_ships(self):
        sig = rq._culture_signal(make_row(**self.ROW))
        assert sig == rq._culture_signal(make_row(**self.ROW))
        assert sig["from"].split(" ", 1)[1] != sig["to"].split(" ", 1)[1]
        other = rq._culture_signal(make_row(**{**self.ROW, "source_id": "159"}))
        assert other != sig
        for n in range(200):
            s = rq._culture_signal(make_row(**{**self.ROW, "line_number": n}))
            assert s["from"].split(" ", 1)[1] != s["to"].split(" ", 1)[1]

    def test_marain_table_is_distinct_connected_glyphs(self):
        codes = [rq._marain_code(ch) for ch in rq._MARAIN_ALPHABET]
        assert len(set(codes)) == len(codes)
        for code in codes:
            assert 4 <= bin(code).count("1") <= 6
            assert rq._marain_connected(code)
        assert rq._marain_code("A") == rq._marain_code("a")
        assert rq._marain_code("'") is None

    def test_marain_wraps_only_at_word_gaps(self):
        rows = rq._marain_layout("half past two", 6)
        assert rows == [
            [rq._marain_code(c) for c in "half"],
            [rq._marain_code(c) for c in "past"],
            [rq._marain_code(c) for c in "two"],
        ]
        assert rq._marain_layout("o'clock", 20) == [[rq._marain_code(c) for c in "oclock"]]
        assert rq._marain_layout("", 5) == []

    def test_hyphens_break_marain_words(self):
        rows = rq._marain_layout("five-and-twenty", 20)
        assert rows == [[rq._marain_code(c) for c in "five"] + [None]
                        + [rq._marain_code(c) for c in "and"] + [None]
                        + [rq._marain_code(c) for c in "twenty"]]

    def test_long_phrase_shrinks_rather_than_dropping_the_hour(self):
        """The Codex finding on #268: at full size this phrase wraps to four
        rows and only three fit, so the last row — the hour — was sliced off."""
        phrase = "Five and twenty minutes past eight"
        pitch, _, _, rows = rq._culture_marain_fit(phrase)
        assert pitch < rq._CULTURE_MARAIN_PITCH
        assert rows[-1][-5:] == [rq._marain_code(c) for c in "eight"]

    def test_no_corpus_phrase_loses_a_glyph(self):
        """Every matched phrase in both committed corpora transcribes whole."""
        phrases = {
            (row.get("matched_text") or "").strip()
            for path in (pq.DEFAULT_DATABASE_PATH, pq.DEFAULT_INPUT_PATH)
            for row in iter_jsonl(pathlib.Path(path))
        } - {""}
        assert len(phrases) > 100
        for phrase in phrases:
            _, _, _, rows = rq._culture_marain_fit(phrase)
            want = sum(rq._marain_code(c) is not None for c in phrase)
            assert rq._marain_glyph_count(rows) == want, phrase

    def test_night_face_is_dark_but_for_its_cities(self):
        inks = {rq._culture_face_ink(r, x, y, x * 1.3, (y % 10) / 10, -0.4)
                for r in range(64) for x in range(0, 300, 7) for y in range(0, 60, 3)}
        assert inks == {rq.SPECTRA6["black"], rq.SPECTRA6["yellow"]}

    def test_aura_never_eats_the_prose(self, monkeypatch):
        """The matched phrase's green aura lands only on black — the white
        prose is never overwritten."""
        green, white = rq.SPECTRA6["green"], rq.SPECTRA6["white"]
        qbox = rq._CULTURE_QUOTE_RECT
        with_aura = self._render().crop(qbox)
        original = rq.paint_neon_mask

        def core_only(image, mask, core, glow, **kwargs):
            kwargs["cap"] = 0.0
            return original(image, mask, core, glow, **kwargs)

        monkeypatch.setattr(rq, "paint_neon_mask", core_only)
        without = self._render().crop(qbox)
        assert ink_counts(without).get(green, 0) == 0
        assert ink_counts(with_aura).get(green, 0) > 0
        white_mask = without.convert("L").point(lambda v: 255 if v == 255 else 0)
        under = Image.composite(with_aura, Image.new("RGB", with_aura.size, white), white_mask)
        assert distinct_inks(under) == {white}, "aura overwrote prose"

    def test_on_palette_and_deterministic(self):
        image = self._render()
        inks = distinct_inks(image)
        assert inks <= set(rq.SPECTRA6.values())
        assert {rq.SPECTRA6[n] for n in ("white", "yellow", "green", "blue", "black")} <= inks
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_unattributed_row_still_renders(self):
        image = self._render({**self.ROW, "author": "", "title": "", "matched_text": ""})
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())


class TestOrbitalFrame:
    """``orbital`` — the Arch seen from one of the Orbital's plates.

    The far side of the ring rises from both horizons; each part of it is lit
    by its own local time, so the Arch is a 24-hour dial. The sky, the sun and
    the quote card follow the hour.
    """

    ROW = TestCultureFrame.ROW
    # The Arch's apex band, clear of the card below it.
    APEX = (360, 12, 440, 32)

    @staticmethod
    def _render(time_str="14:30", row=None, size=(800, 480)):
        return rq.render(time_str, make_row(**(row or TestOrbitalFrame.ROW)),
                         *size, mode="production", theme="orbital")

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert "orbital" in rq.THEMES
        assert "orbital" in rq.THEME_ORDER
        assert "orbital" not in rq.CYCLE_EXCLUDED_THEMES
        assert display_inky.THEME_SATURATION["orbital"] == 0.5
        assert rq.theme_font_candidates("orbital", "quote_regular")[0] == rq.JURA_SEMIBOLD
        assert rq.theme_font_candidates("orbital", "quote_bold")[0] == rq.JURA_BOLD

    @pytest.mark.parametrize("time_str,period", [
        ("12:00", "day"), ("09:00", "day"), ("00:00", "night"), ("03:30", "night"),
        ("06:00", "twilight"), ("18:00", "twilight"),
    ])
    def test_sky_follows_the_hour(self, time_str, period):
        assert rq._orbital_period(rq._culture_clock(time_str)) == period

    def test_zenith_is_twelve_hours_away(self):
        """The plate overhead is halfway round the ring: dark at our noon,
        in full daylight at our midnight. The feet share our time."""
        assert rq._orbital_arch_day(0.5, math.pi) == pytest.approx(-1.0)
        assert rq._orbital_arch_day(0.0, math.pi) == pytest.approx(1.0)
        assert rq._orbital_arch_day(0.5, 0.0) == pytest.approx(1.0)

    def test_the_arch_narrows_as_it_recedes(self):
        widths = [rq._orbital_arch_width(rq._orbital_arch_phi(a))
                  for a in (math.pi, 0.75 * math.pi, 0.5 * math.pi)]
        assert widths[0] > widths[1] > widths[2]
        assert rq._orbital_arch_phi(0.0) == pytest.approx(2 * math.pi - rq._ORBITAL_ARCH_PHI0)

    def test_the_apex_is_lit_at_midnight_and_dark_at_noon(self):
        green, yellow = rq.SPECTRA6["green"], rq.SPECTRA6["yellow"]
        midnight = distinct_inks(self._render("00:00").crop(self.APEX))
        noon = distinct_inks(self._render("12:00").crop(self.APEX))
        assert green in midnight, "the zenith is at local noon at our midnight — land should show"
        assert green not in noon and yellow not in noon, "the zenith is at midnight at our noon"

    def test_card_is_inked_for_the_hour(self):
        white, black = rq.SPECTRA6["white"], rq.SPECTRA6["black"]
        x0, y0, x1, y1 = rq._ORBITAL_CARD
        inner = (x0 + 16, y0 + 40, x1 - 16, y1 - 40)
        day = ink_counts(self._render("12:00").crop(inner))
        night = ink_counts(self._render("00:00").crop(inner))
        assert day.get(white, 0) > day.get(black, 0)
        assert night.get(black, 0) > night.get(white, 0)

    def test_sun_is_up_only_by_day_and_clear_of_the_arch(self):
        assert rq._orbital_sun_xy(0.0) is None
        x, y = rq._orbital_sun_xy(0.5)
        cx, a, b = rq._ORBITAL_ARCH
        rho = math.hypot((x - cx) / a, (rq._ORBITAL_HORIZON - y) / b)
        assert rho < 1 - rq._orbital_arch_width(math.pi) - 0.02, "noon sun should stand below the Arch"

    def test_sun_is_never_behind_the_card(self):
        """Every daylight minute, the sun's disc stands clear of the quote card
        (with a small gap), so the sky always shows it."""
        x0, y0, x1, y1 = rq._ORBITAL_CARD
        up = 0
        for minute in range(1440):
            pos = rq._orbital_sun_xy(minute / 1440)
            if pos is None:
                continue
            up += 1
            dx = max(x0 - pos[0], 0, pos[0] - x1)
            dy = max(y0 - pos[1], 0, pos[1] - y1)
            assert dx * dx + dy * dy >= 13 * 13, f"sun behind the card at minute {minute}: {pos}"
        assert up > 600, "the sun should be up for most of the day"

    def test_on_palette_deterministic_and_hour_dependent(self):
        image = self._render()
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        assert pixel_bytes(image) == pixel_bytes(self._render())
        assert pixel_bytes(self._render("12:00")) != pixel_bytes(self._render("00:00"))

    @pytest.mark.parametrize("time_str", ["00:00", "05:50", "06:15", "12:00", "18:40", "21:00"])
    def test_every_part_of_the_day_renders(self, time_str):
        row = {**self.ROW, "author": "", "title": ""}
        assert distinct_inks(self._render(time_str, row)) <= set(rq.SPECTRA6.values())


class TestFuriesFrame:
    """``furies`` — Bacon's *Three Studies for Figures at the Base of a
    Crucifixion* (1944), under glass in gilt, the quote as wall text beneath.

    The triptych is painted procedurally as continuous-tone layers, each
    separated against its own inks and stacked through a dithered alpha.
    """

    ROW = dict(
        display_quote="It was about half past two when the clock struck and the "
                      "afternoon slipped quietly away from them.",
        matched_text="half past two",
        author="Edith Wharton",
        title="The House of Mirth",
        source_id="141",
        line_number=482,
    )

    @staticmethod
    def _render(row=None, time_str="14:30", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or TestFuriesFrame.ROW)),
                         *size, mode="production", theme="furies")

    @staticmethod
    def _panel_box(i):
        x = rq._FURIES_PANEL_XS[i]
        return (x, rq._FURIES_PANEL_Y, x + rq._FURIES_PANEL_W, rq._FURIES_PANEL_Y + rq._FURIES_PANEL_H)

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert "furies" in rq.THEMES
        assert "furies" in rq.THEME_ORDER
        assert "furies" not in rq.CYCLE_EXCLUDED_THEMES
        assert display_inky.THEME_SATURATION["furies"] == 0.7
        assert rq.theme_font_candidates("furies", "quote_regular")[0] == (rq.LIBREFRANKLIN_VARIABLE, "Medium")
        assert rq.theme_font_candidates("furies", "quote_bold")[0] == (rq.LIBREFRANKLIN_VARIABLE, "ExtraBold")
        for path in (rq.LIBREFRANKLIN_VARIABLE, rq.LIBREFRANKLIN_ITALIC_VARIABLE):
            assert pathlib.Path(path).exists(), path
        assert (pathlib.Path(rq.LIBREFRANKLIN_VARIABLE).parent / "OFL.txt").exists()

    def test_body_instance_is_pinned_off_the_axis_default(self):
        """A variable font renders its default instance unless an instance is
        named; the pinned Medium must differ from what a bare load gives."""
        from PIL import ImageFont
        pinned = rq.load_font([(rq.LIBREFRANKLIN_VARIABLE, "Medium")], size=40)
        bare = ImageFont.truetype(rq.LIBREFRANKLIN_VARIABLE, 40)
        glyph = "Hamburgefonts"

        def ink(font):
            img = Image.new("L", (400, 60), 0)
            ImageDraw.Draw(img).text((0, 0), glyph, font=font, fill=255)
            return sum(img.point(lambda v: 1 if v > 127 else 0).histogram()[1:])

        assert ink(pinned) != ink(bare)

    def test_a_painting_carries_no_clock(self):
        first = pixel_bytes(self._render(time_str="14:30"))
        for time_str in ("00:00", "03:05", "09:59", "23:45", "bogus"):
            assert pixel_bytes(self._render(time_str=time_str)) == first

    def test_on_palette_deterministic_and_no_blue(self):
        """Every ink but blue: the 1944 triptych has none, and the per-layer
        separation gives error diffusion no route to it."""
        image = self._render()
        inks = distinct_inks(image)
        assert inks == set(rq.SPECTRA6.values()) - {rq.SPECTRA6["blue"]}
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_triptych_is_quote_independent(self):
        other = {**self.ROW, "display_quote": "Something else entirely at noon.",
                 "matched_text": "noon", "author": "Anon", "title": "Other"}
        a, b = self._render(), self._render(other)
        for i in range(3):
            box = self._panel_box(i)
            assert pixel_bytes(a.crop(box)) == pixel_bytes(b.crop(box))

    def test_grass_is_only_in_the_right_panel(self):
        image = self._render()
        green = rq.SPECTRA6["green"]
        assert green not in distinct_inks(image.crop(self._panel_box(0)))
        assert green not in distinct_inks(image.crop(self._panel_box(1)))
        assert green in distinct_inks(image.crop(self._panel_box(2)))

    def test_each_layer_is_separated_against_its_own_inks(self):
        """Wherever the flesh layer lands, the panel carries only flesh inks —
        and a single pass over the flattened panel would not have held that:
        grey flesh sits between R+G and W+K, so error diffusion would leak
        green (the grass's ink) into it. That leak is why the layers separate."""
        layers = rq._furies_right_panel()
        composed = rq._furies_compose_panel(layers)
        flesh_rgb, flesh_alpha, flesh_inks = layers[-1]
        mask = rq._furies_dithered_alpha(flesh_alpha)
        under = Image.composite(composed, Image.new("RGB", composed.size, flesh_inks[0]), mask)
        assert distinct_inks(under) <= set(flesh_inks)

        flat = layers[0][0].copy()
        for rgb, alpha, _ in layers[1:]:
            flat = Image.composite(rgb, flat, alpha)
        palette = [c for n, c in rq.SPECTRA6.items() if n != "blue"]
        naive = rq.dither_image_to_palette(flat, palette)
        naive_under = Image.composite(naive, Image.new("RGB", naive.size, flesh_inks[0]), mask)
        leaked = set(distinct_inks(naive_under)) - set(flesh_inks)
        assert leaked, "the naive single pass should leak non-flesh inks into the figure"

    def test_ground_holds_red_and_yellow_only(self):
        ground = rq.dither_image_to_palette(rq._furies_ground(11), rq._FURIES_GROUND_INKS)
        inks = ink_counts(ground)
        assert set(inks) == {rq.SPECTRA6["red"], rq.SPECTRA6["yellow"]}
        share = inks[rq.SPECTRA6["yellow"]] / sum(inks.values())
        assert 0.3 < share < 0.6, f"cadmium orange should be a near-even R+Y mix, got yellow {share:.2f}"

    def test_dithered_alpha_is_a_true_ordered_threshold(self):
        """Half alpha takes exactly half the cells of the 8x8 tile, zero takes
        none and full takes all — so a smear's falling alpha becomes a falling
        stipple, not a hard edge at 50%."""
        for level, expected in ((0, 0), (128, 32), (255, 64)):
            out = rq._furies_dithered_alpha(Image.new("L", (8, 8), level))
            assert out.histogram()[255] == expected, level

    def test_drag_trails_along_its_vector_unevenly(self):
        """The drag leaves paint only downstream of the shape, and the bristle
        striations make the trail uneven across rows rather than a flat blur."""
        size = (120, 80)
        alpha = Image.new("L", size, 0)
        ImageDraw.Draw(alpha).rectangle((20, 20, 50, 60), fill=255)
        rgb = Image.new("RGB", size, (200, 200, 200))
        _, dragged = rq._furies_drag(rgb, alpha, 30, 0, steps=10, decay=0.9, seed=5)
        assert dragged.crop((0, 0, 19, 80)).getbbox() is None, "paint moved upstream"
        trail = dragged.crop((60, 20, 80, 61))
        assert trail.getbbox() is not None, "no trail downstream"
        column = [trail.getpixel((5, y)) for y in range(trail.height)]
        assert len(set(column)) > 3, "trail is uniform — striations missing"
        # The shape itself is carried at ``keep`` strength, not erased.
        assert dragged.getpixel((35, 40)) >= int(255 * 0.9)

    def test_smear_never_touches_the_prose_or_the_phrase(self, monkeypatch):
        """Neutering the smear may only remove red pixels from the black wall
        outside the phrase's berth: the prose and the phrase core are untouched."""
        smeared = self._render()
        monkeypatch.setattr(rq, "_FURIES_SMEAR_STRENGTH", 0.0)
        clean = self._render()
        diff = ImageChops.difference(smeared, clean)
        assert diff.getbbox() is not None, "the phrase should carry a smear"
        red, black = rq.SPECTRA6["red"], rq.SPECTRA6["black"]
        a, b = smeared.load(), clean.load()
        x0, y0, x1, y1 = diff.getbbox()
        for y in range(y0, y1):
            for x in range(x0, x1):
                if a[x, y] != b[x, y]:
                    assert a[x, y] == red and b[x, y] == black, (x, y, a[x, y], b[x, y])

    def test_phrase_core_is_yellow_major_orange(self, monkeypatch):
        monkeypatch.setattr(rq, "_FURIES_SMEAR_STRENGTH", 0.0)
        counts = ink_counts(self._render().crop(rq._FURIES_QUOTE_RECT))
        red, yellow = counts.get(rq.SPECTRA6["red"], 0), counts.get(rq.SPECTRA6["yellow"], 0)
        assert red and yellow
        assert abs(red / (red + yellow) - rq._FURIES_PHRASE_RED_RANKS / 64) < 0.06

    def test_glass_reflects_on_the_paint_only(self, monkeypatch):
        glazed = self._render()
        monkeypatch.setattr(rq, "_furies_paint_glass", lambda image: None)
        bare = self._render()
        diff = ImageChops.difference(glazed, bare).getbbox()
        assert diff is not None, "no reflection on the glass"
        x0, y0, x1, y1 = diff
        assert rq._FURIES_PANEL_XS[0] <= x0 and x1 <= rq._FURIES_PANEL_XS[-1] + rq._FURIES_PANEL_W
        assert rq._FURIES_PANEL_Y <= y0 and y1 <= rq._FURIES_PANEL_Y + rq._FURIES_PANEL_H
        # One reflection across three panes, not three separate ones.
        for i in range(3):
            assert pixel_bytes(glazed.crop(self._panel_box(i))) != pixel_bytes(bare.crop(self._panel_box(i)))

    def test_gilt_frames_are_gold(self):
        """The moulding's flat is yellow-major: gilt, not a second orange."""
        image = self._render()
        x = rq._FURIES_PANEL_XS[1]
        y = rq._FURIES_PANEL_Y + rq._FURIES_PANEL_H // 2
        strip = image.crop((x - rq._FURIES_FRAME + 2, y - 40, x - 1, y + 40))
        counts = ink_counts(strip)
        yellow = counts.get(rq.SPECTRA6["yellow"], 0)
        assert yellow / sum(counts.values()) > 0.7

    def test_missing_attribution_renders(self):
        row = {**self.ROW, "author": "", "title": "", "source_id": ""}
        assert distinct_inks(self._render(row)) <= set(rq.SPECTRA6.values())


class TestBoschFrame:
    """``bosch`` — *The Garden of Earthly Delights*, the triptych open.

    Paradise / Garden / Hell, the quote lettered on a banderole across the
    centre panel, and the whole altarpiece crazed by ``paint_craquelure``.
    """

    ROW = dict(
        display_quote="It was about half past two when the clock struck and the "
                      "afternoon light came slanting through the tall windows.",
        matched_text="half past two",
        author="Jane Austen",
        title="Emma",
        source_id="158",
        line_number=482,
    )
    LONG = dict(
        ROW,
        display_quote="It was just five minutes to midnight when the last of the carriages rolled "
                      "away down the long avenue, and the great house, which had blazed with light "
                      "and music for six hours together, fell dark and silent all at once, as though "
                      "someone had blown out a candle; and in the silence the old clock in the hall "
                      "was heard to strike, very faintly, some hour of its own devising.",
        matched_text="five minutes to midnight",
    )

    @staticmethod
    def _render(row=None, time_str="14:30", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or TestBoschFrame.ROW)),
                         *size, mode="production", theme="bosch")

    @staticmethod
    def _lettering(row):
        """The banderole's text as a mask, laid out exactly as the frame lays it."""
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["white"])
        draw = ImageDraw.Draw(image)
        regular, bold, wrapped, lh, rect = rq._bosch_scroll_layout(draw, make_row(**row))
        mask = Image.new("L", (800, 480), 0)
        rq._bosch_draw_lettering(ImageDraw.Draw(mask), regular, bold, wrapped, lh, rect,
                                 make_row(**row), 255, 255)
        return mask, rect

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert "bosch" in rq.THEMES
        assert "bosch" in rq.THEME_ORDER
        assert "bosch" not in rq.CYCLE_EXCLUDED_THEMES
        assert display_inky.THEME_SATURATION["bosch"] == 0.5
        assert rq.theme_font_candidates("bosch", "quote_regular")[0] == (rq.GRENZE_GOTISCH_VARIABLE, "Medium")
        assert rq.theme_font_candidates("bosch", "quote_bold")[0] == (rq.GRENZE_GOTISCH_VARIABLE, "Bold")
        font = pathlib.Path(rq.GRENZE_GOTISCH_VARIABLE)
        assert font.exists() and (font.parent / "OFL.txt").exists()

    def test_grenze_instances_are_pinned(self):
        """A variable face without its variation call renders its default
        instance; pin that Medium and Bold really are different weights."""
        regular = rq.load_font(rq.theme_font_candidates("bosch", "quote_regular"), size=30)
        bold = rq.load_font(rq.theme_font_candidates("bosch", "quote_bold"), size=30)

        def ink(font):
            mask = Image.new("L", (400, 80), 0)
            ImageDraw.Draw(mask).text((4, 4), "Garden of Delights", font=font, fill=255)
            return mask.point(lambda v: 255 if v > 127 else 0).histogram()[255]
        assert ink(bold) > ink(regular) * 1.1

    def test_no_clock_reaches_the_frame(self):
        """An altarpiece carries no hour: ``time_str`` is del-asserted and the
        matched phrase is the clock, so every time renders byte-identically."""
        first = pixel_bytes(self._render(time_str="14:30"))
        for time_str in ("00:00", "03:05", "23:59", "bogus"):
            assert pixel_bytes(self._render(time_str=time_str)) == first

    def test_on_palette_deterministic_and_all_six_inks(self):
        image = self._render()
        assert distinct_inks(image) == set(rq.SPECTRA6.values())
        assert pixel_bytes(image) == pixel_bytes(self._render())

    @pytest.mark.parametrize("row_name", ["ROW", "LONG"])
    def test_cracks_never_cut_the_lettering(self, row_name, monkeypatch):
        """The craquelure crazes the whole altarpiece, banderole included, but
        a dilated halo round every glyph is off-limits: the lettering pixels
        are byte-identical with and without the crack pass."""
        row = getattr(self, row_name)
        crazed = self._render(row)
        monkeypatch.setattr(rq, "paint_craquelure", lambda *a, **k: None)
        clean = self._render(row)
        mask, rect = self._lettering(row)
        guard = mask.filter(ImageFilter.MaxFilter(5))
        ca, cb, gp = crazed.load(), clean.load(), guard.load()
        x0, y0, x1, y1 = rect
        diffs_near_text = diffs_on_scroll = 0
        for y in range(y0, y1):
            for x in range(x0, x1):
                if ca[x, y] != cb[x, y]:
                    if gp[x, y]:
                        diffs_near_text += 1
                    else:
                        diffs_on_scroll += 1
        assert diffs_near_text == 0
        assert diffs_on_scroll > 100, "the banderole should be crazed too, away from the letters"

    def test_crack_polarity_follows_the_paint(self):
        """Grime on light paint, chalk ground through dark paint — and the
        chalk opens far more sparingly than the grime darkens."""
        white, black = rq.SPECTRA6["white"], rq.SPECTRA6["black"]
        image = Image.new("RGB", (400, 200), white)
        image.paste(black, (200, 0, 400, 200))
        region = Image.new("L", image.size, 255)
        painted = rq.paint_craquelure(image, region, seed=7, cell=(24, 14))
        light_side = ink_counts(image.crop((0, 0, 200, 200))).get(black, 0)
        dark_side = ink_counts(image.crop((200, 0, 400, 200))).get(white, 0)
        assert light_side > 800 and dark_side > 50
        assert dark_side < light_side * 0.4
        assert ink_counts(painted.convert("RGB")).get((255, 255, 255), 0) == light_side + dark_side

    def test_craquelure_is_confined_seeded_and_kept_out(self):
        white = rq.SPECTRA6["white"]
        region = Image.new("L", (300, 200), 0)
        ImageDraw.Draw(region).rectangle((0, 0, 149, 199), fill=255)
        keep = Image.new("L", (300, 200), 0)
        ImageDraw.Draw(keep).rectangle((40, 60, 100, 120), fill=255)

        def run(seed):
            image = Image.new("RGB", (300, 200), white)
            painted = rq.paint_craquelure(image, region, seed=seed, keep_out=keep, keep_out_pad=2)
            return image, painted

        a, painted = run(3)
        assert painted.crop((150, 0, 300, 200)).getbbox() is None, "cracks escaped the region"
        assert painted.crop((38, 58, 103, 123)).getbbox() is None, "cracks entered the keep-out"
        assert painted.crop((0, 0, 150, 200)).getbbox() is not None
        assert pixel_bytes(a) == pixel_bytes(run(3)[0])
        assert pixel_bytes(a) != pixel_bytes(run(4)[0])

    def test_wing_tops_are_the_centre_arch_halved_and_mirrored(self):
        """Closed, each wing covers half the centre; opened, its free edge —
        the half-arch's apex — swings outermost. So an open wing is high at
        the outside and low at the hinge, and the centre peaks in the middle."""
        centre = rq._bosch_arch_tops("garden", 436)
        assert centre[218] < 1 and centre[0] > rq._BOSCH_ARCH_RISE - 2
        assert abs(centre[10] - centre[-11]) < 0.01
        paradise = rq._bosch_arch_tops("paradise", 158)
        hell = rq._bosch_arch_tops("hell", 158)
        assert paradise[0] < 1 and paradise[-1] > rq._BOSCH_ARCH_RISE - 2
        assert hell[-1] < 1 and hell[0] > rq._BOSCH_ARCH_RISE - 2
        assert all(a >= b for a, b in zip(paradise[1:], paradise)), "paradise should fall toward its hinge"

    def test_banderole_is_sized_to_its_text_and_stays_on_the_centre_panel(self):
        draw = ImageDraw.Draw(Image.new("RGB", (800, 480)))
        short = rq._bosch_scroll_layout(draw, make_row(**{**self.ROW, "display_quote": "Twelve o'clock.",
                                                         "matched_text": "Twelve o'clock"}))[-1]
        long = rq._bosch_scroll_layout(draw, make_row(**self.LONG))[-1]
        assert (short[2] - short[0]) < (long[2] - long[0])
        assert (short[3] - short[1]) < (long[3] - long[1])
        _, (gx0, gy0, gx1, gy1) = rq._BOSCH_PANELS[1]
        for x0, y0, x1, y1 in (short, long):
            assert gx0 < x0 - rq._BOSCH_ROLL_W and x1 + rq._BOSCH_ROLL_W < gx1
            assert gy0 + rq._BOSCH_ARCH_RISE < y0 and y1 < gy1

    def test_phrase_is_rubricated(self):
        """The matched phrase is solid red on the banderole, the prose black."""
        image = self._render()
        mask, rect = self._lettering(self.ROW)
        counts = ink_counts(Image.composite(image, Image.new("RGB", image.size, rq.SPECTRA6["white"]),
                                            mask.point(lambda v: 255 if v > 200 else 0)).crop(rect))
        assert counts.get(rq.SPECTRA6["red"], 0) > 150
        assert counts.get(rq.SPECTRA6["black"], 0) > counts.get(rq.SPECTRA6["red"], 0)

    def test_hell_burns_bright(self):
        """Red over black is the lowest-contrast pair the inks offer, so the
        fire must be carried by yellow: the blaze band is yellow-dominant."""
        _, (x0, y0, x1, _) = rq._BOSCH_PANELS[2]
        counts = ink_counts(self._render().crop((x0 + 4, y0 + 40, x1 - 4, y0 + 110)))
        assert counts.get(rq.SPECTRA6["yellow"], 0) > counts.get(rq.SPECTRA6["red"], 0)
        assert counts.get(rq.SPECTRA6["yellow"], 0) > 0.2 * sum(counts.values())

    def test_bare_row_still_renders(self):
        image = self._render({**self.ROW, "author": "", "title": ""})
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())

    def test_rank_field_is_clamped_and_immutable(self):
        """Every jittered rank lies in 0..63, so a share of 0 paints nothing
        and a share of 1 paints everything; and the field is a tuple, built
        once and published whole (preview threads may race to build it)."""
        field = rq._bosch_rank_field()
        assert isinstance(field, tuple) and len(field) == 480
        assert all(len(row) == 800 for row in field)
        assert min(min(row) for row in field) == 0 and max(max(row) for row in field) == 63
        white, green = rq.SPECTRA6["white"], rq.SPECTRA6["green"]
        assert all(rq._bosch_pick(r, ((white, 0.0), (green, 1))) == green for r in range(64))

    def test_parchment_carries_no_stray_red(self):
        """Red on the banderole belongs to the rubricated phrase alone: with
        no phrase matched, the scroll's centre band has no red at all."""
        row = {**self.ROW, "matched_text": "no such phrase"}
        image = self._render(row)
        _, rect = self._lettering(row)
        x0, y0, x1, y1 = rect
        mid = (y0 + y1) // 2
        band = image.crop((x0 + 4, mid - 20, x1 - 4, mid + 20))
        assert ink_counts(band).get(rq.SPECTRA6["red"], 0) == 0


class TestSemioticFrame:
    """``semiotic`` — Ron Cobb's Semiotic Standard on a Nostromo bulkhead.

    The signs are LouH's CC BY 4.0 vector set, packed into a sheet by
    ``scripts/ingest_semiotic_signs.py`` and classified onto the inks at render
    time. The hour chooses the featured sign and the section; the quote
    chooses the companions.
    """

    ROW = dict(
        display_quote="It was about half past two when the clock struck and the "
                      "afternoon slipped quietly away from them.",
        matched_text="half past two",
        author="Edith Wharton",
        title="The House of Mirth",
        source_id="141",
        line_number=482,
    )

    @staticmethod
    def _render(row=None, time_str="14:30", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or TestSemioticFrame.ROW)),
                         *size, mode="production", theme="semiotic")

    @staticmethod
    def _feature(img):
        x, y, w, h = rq._SEMIOTIC_FEATURE_BOX
        return img.crop((x, y, x + w, y + h))

    def test_on_palette_and_surfaces_all_six_inks(self):
        assert distinct_inks(self._render()) == set(rq.SPECTRA6.values())

    def test_every_minute_of_an_hour_renders_identically(self):
        """Hour only: nothing on the frame reads the clock's minute."""
        first = pixel_bytes(self._render(time_str="09:00"))
        for minute in (5, 17, 30, 59):
            assert pixel_bytes(self._render(time_str=f"09:{minute:02d}")) == first

    def test_twelve_distinct_hour_signs(self):
        codes = [rq._SEMIOTIC_HOUR_SIGNS[h] for h in range(1, 13)]
        assert len(set(codes)) == 12
        assert all(code in rq._SEMIOTIC_INDEX for code in codes)
        # 13:00 and 01:00 are the same hour on a 12-hour dial.
        assert rq._semiotic_hour("13:00") == rq._semiotic_hour("01:00") == 1
        assert rq._semiotic_hour("00:10") == rq._semiotic_hour("12:10") == 12

    def test_featured_sign_follows_the_hour(self):
        crops = {pixel_bytes(self._feature(self._render(time_str=f"{h:02d}:00"))) for h in range(1, 13)}
        assert len(crops) == 12

    def test_companions_come_from_the_quote(self):
        other = dict(self.ROW, source_id="999", line_number=7)
        a = rq._semiotic_companions(make_row(**self.ROW), "006")
        b = rq._semiotic_companions(make_row(**other), "006")
        assert a != b
        for picks in (a, b):
            assert len(set(picks)) == 3 and "006" not in picks
            assert all(code in rq._SEMIOTIC_COMPANION_POOL for code in picks)

    def test_sign_seams_stay_on_the_signs_own_inks(self):
        """Regression: classifying against all seven source values let the
        bulkhead door's black/white seam average onto the dark green."""
        feature = self._feature(self._render(time_str="02:00"))  # 006 bulkhead door
        assert rq.SPECTRA6["green"] not in distinct_inks(feature)
        assert rq.SPECTRA6["blue"] not in distinct_inks(feature)

    def test_grey_signs_become_a_black_white_stipple(self):
        feature = self._feature(self._render(time_str="06:00"))  # 010 laser, grey field
        counts = ink_counts(feature)
        assert counts.get(rq.SPECTRA6["black"], 0) > 0.1 * feature.width * feature.height
        assert set(counts) <= {rq.SPECTRA6["white"], rq.SPECTRA6["black"], rq.SPECTRA6["red"]}

    def test_quote_is_on_the_placard(self):
        img = self._render()
        x0, y0, x1, y1 = rq._SEMIOTIC_QUOTE_RECT
        counts = ink_counts(img.crop((x0, y0, x1, y1)))
        assert counts.get(rq.SPECTRA6["red"], 0) > 200      # the matched phrase
        assert counts.get(rq.SPECTRA6["black"], 0) > 2000   # the prose

    def test_missing_sheet_degrades_to_blank_signs(self, monkeypatch, tmp_path):
        monkeypatch.setattr(rq, "SEMIOTIC_SIGNS", tmp_path / "absent.png")
        monkeypatch.setattr(rq, "_SEMIOTIC_SHEET_CACHE", {})
        img = self._render()
        assert distinct_inks(img) <= set(rq.SPECTRA6.values())
        assert rq.SPECTRA6["red"] in distinct_inks(self._feature(img))

    def test_downscales_the_canonical_frame(self):
        small = self._render(size=(320, 192))
        big = self._render()
        assert small.size == (320, 192)
        assert pixel_bytes(small) == pixel_bytes(big.resize((320, 192), Image.Resampling.NEAREST))

    def test_sheet_matches_the_ingest_legend(self):
        import importlib.util
        path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ingest_semiotic_signs.py"
        spec = importlib.util.spec_from_file_location("ingest_semiotic_signs", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert [name.split(".")[0] for name in mod.SIGNS] == [code for code, _ in rq._SEMIOTIC_SIGNS]
        assert mod.TILE == rq._SEMIOTIC_TILE and mod.COLS == rq._SEMIOTIC_SHEET_COLS
        sheet = rq._semiotic_sheet()
        rows = -(-len(mod.SIGNS) // mod.COLS)
        assert sheet.size == (mod.COLS * mod.TILE[0], rows * mod.TILE[1])

    def test_attribution_ships_with_the_sheet(self):
        readme = rq.BASE_DIR / "assets" / "semiotic" / "README.md"
        text = readme.read_text()
        assert "CC BY 4.0" in text and "louh/semiotic-standard" in text and "Ron Cobb" in text


class TestSarosFrame:
    """``saros`` — Housemarque's *Saros*, the eclipse over Carcosa.

    A black sun in a dithered corona whose phase is the hour, a sunset band
    ringing the horizon with the colony cut out of it, the
    quote in the dark sky with the matched phrase as an ember.
    """

    ROW = dict(
        display_quote="The clock was striking ten when he came back, and the whole "
                      "house seemed asleep; only the stars were awake over the river.",
        matched_text="striking ten",
        author="H. G. Wells",
        title="The Time Machine",
        source_id="35",
        line_number=646,
    )

    @staticmethod
    def _render(row=None, time_str="10:00", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or TestSarosFrame.ROW)),
                         *size, mode="production", theme="saros")

    @staticmethod
    def _bead_window(hour):
        bx, by = rq._saros_bead(hour)
        return (int(bx) - 14, int(by) - 14, int(bx) + 14, int(by) + 14)

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert "saros" in rq.THEMES
        assert "saros" in rq.THEME_ORDER
        assert "saros" not in rq.CYCLE_EXCLUDED_THEMES
        assert display_inky.THEME_SATURATION["saros"] == 0.7
        # Saira stands in for Tamba Sans (the game's text face), Orbitron for
        # Arame (its display face), Michroma for Korataki (its chrome); Exo 2,
        # the earlier body face, is the fallback.
        assert rq.theme_font_candidates("saros", "quote_regular")[0] == (rq.SAIRA_VARIABLE, "Regular")
        assert rq.theme_font_candidates("saros", "quote_bold")[0] == (rq.SAIRA_VARIABLE, "SemiBold")
        assert rq.theme_font_candidates("saros", "quote_regular")[1] == (rq.EXO2_VARIABLE, "Regular")
        for path in (rq.SAIRA_VARIABLE, rq.SAIRA_ITALIC_VARIABLE, rq.ORBITRON_VARIABLE,
                     rq.EXO2_VARIABLE, rq.EXO2_ITALIC_VARIABLE, rq.MICHROMA_REGULAR):
            assert pathlib.Path(path).exists()
            assert (pathlib.Path(path).parent / "OFL.txt").exists()

    def test_frame_is_on_palette_and_deterministic(self):
        image = self._render()
        inks = distinct_inks(image)
        assert inks <= set(rq.SPECTRA6.values())
        # Fire, sky, the horizon haze — and never green.
        for ink in ("black", "red", "yellow", "white", "blue"):
            assert rq.SPECTRA6[ink] in inks, ink
        assert rq.SPECTRA6["green"] not in inks
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_every_minute_of_an_hour_renders_identically(self):
        """Hour only: the eclipse's phase is the hour, nothing reads the minute."""
        first = pixel_bytes(self._render(time_str="09:00"))
        for minute in (5, 17, 30, 59):
            assert pixel_bytes(self._render(time_str=f"09:{minute:02d}")) == first

    def test_twelve_is_totality(self):
        assert rq._saros_moon_centre(12) == tuple(float(v) for v in rq._SAROS_SUN)
        assert rq._saros_occlusion(12) == 100
        assert all(rq._saros_occlusion(h) < 100 for h in range(1, 12))
        assert pixel_bytes(self._render(time_str="00:00")) == pixel_bytes(self._render(time_str="12:00"))
        # No diamond ring at totality: no white bead on the limb anywhere.
        total = self._render(time_str="12:00")
        for hour in range(1, 12):
            window = total.crop(self._bead_window(hour))
            assert ink_counts(window).get(rq.SPECTRA6["white"], 0) < 40

    def test_the_bead_is_the_hour_hand(self):
        """The exposed sliver and its bead sit where the hour hand would point."""
        cx, cy = rq._SAROS_SUN
        r = rq._SAROS_RADIUS
        assert rq._saros_bead(3) == pytest.approx((cx + r, cy))
        assert rq._saros_bead(6) == pytest.approx((cx, cy + r))
        assert rq._saros_bead(9) == pytest.approx((cx - r, cy))
        assert rq._saros_bead(12) == pytest.approx((cx, cy - r))
        for hour in (3, 9):
            image = self._render(time_str=f"{hour:02d}:00")
            lit = ink_counts(image.crop(self._bead_window(hour))).get(rq.SPECTRA6["white"], 0)
            dark = ink_counts(image.crop(self._bead_window(12 - hour))).get(rq.SPECTRA6["white"], 0)
            assert lit > dark + 60, (hour, lit, dark)

    def test_twelve_distinct_hour_frames(self):
        frames = {pixel_bytes(self._render(time_str=f"{h:02d}:00")) for h in range(1, 13)}
        assert len(frames) == 12

    def test_the_corona_holds_no_blue(self):
        """Blue is in the dither palette for the horizon haze only; a blue
        channel in the fire would be paid out as blue specks in the corona."""
        image = self._render(time_str="12:00")
        assert rq.SPECTRA6["blue"] not in distinct_inks(image.crop((420, 0, 800, 300)))

    def test_silhouettes_cut_the_dusk(self):
        """The tallest colony tower stands black against the sunset band; the
        sky beside it at the same height is lit."""
        image = self._render(time_str="12:00")
        tower = image.crop((750, 330, 782, 362))
        assert distinct_inks(tower) == {rq.SPECTRA6["black"]}
        beside = image.crop((724, 330, 740, 362))
        assert rq.SPECTRA6["red"] in distinct_inks(beside) or rq.SPECTRA6["yellow"] in distinct_inks(beside)

    def test_quote_is_white_prose_with_an_ember_phrase(self):
        image = self._render()
        counts = ink_counts(image.crop(rq._SAROS_QUOTE_RECT))
        assert counts.get(rq.SPECTRA6["white"], 0) > 2000
        assert counts.get(rq.SPECTRA6["yellow"], 0) > 200

    def test_motes_come_from_the_quote_and_never_land_on_the_moon(self):
        other = dict(self.ROW, source_id="999", line_number=7)
        a = self._render(time_str="12:00")
        b = self._render(row=other, time_str="12:00")
        # Same text, same hour: only the spores differ, and they must.
        assert pixel_bytes(a) != pixel_bytes(b)
        cx, cy = rq._SAROS_SUN
        for image in (a, b):
            assert distinct_inks(image.crop((cx - 70, cy - 70, cx + 70, cy + 70))) == {rq.SPECTRA6["black"]}

    def test_chrome_face_carries_every_glyph_it_sets(self):
        font = rq.load_font([rq.MICHROMA_REGULAR], 10)
        for ch in set("SAROS CARCOSA COLONY DIAMOND RING TOTALITY OCCLUSION 0123456789%"):
            assert rq.font_has_glyph(font, ch), ch

    def test_missing_author_falls_back_to_the_source(self):
        row = dict(self.ROW, author="", title="")
        image = self._render(row=row)
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())


class TestAtroposFrame:
    """``atropos`` — Housemarque's *Returnal*: night in the Overgrown Ruins.

    The night is painted in continuous tone and dithered to the cold inks; the
    lights, the volley of orbs, the cipher and the HUD readings go on top. The
    hour is the cycle counter; the orbs, the cipher and the readings are
    seeded from the quote.
    """

    ROW = dict(
        display_quote="It was about half past two when the clock struck and the "
                      "afternoon slipped quietly away from them.",
        matched_text="half past two",
        author="Edith Wharton",
        title="The House of Mirth",
        source_id="141",
        line_number=482,
    )
    COUNTER_BOX = (560, 10, 790, 36)

    @staticmethod
    def _render(row=None, time_str="14:30", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or TestAtroposFrame.ROW)),
                         *size, mode="production", theme="atropos")

    def test_on_palette_and_surfaces_all_six_inks(self):
        assert distinct_inks(self._render()) == set(rq.SPECTRA6.values())

    def test_every_minute_of_an_hour_renders_identically(self):
        """Hour only: nothing on the frame reads the clock's minute."""
        first = pixel_bytes(self._render(time_str="09:00"))
        for minute in (5, 17, 30, 59):
            assert pixel_bytes(self._render(time_str=f"09:{minute:02d}")) == first

    def test_cycle_counter_follows_the_hour(self):
        crops = {pixel_bytes(self._render(time_str=f"{h:02d}:00").crop(self.COUNTER_BOX)) for h in range(1, 13)}
        assert len(crops) == 12
        assert rq._atropos_hour("13:00") == rq._atropos_hour("01:00") == 1
        assert rq._atropos_hour("00:10") == rq._atropos_hour("12:10") == 12

    def test_scene_is_dithered_to_the_cold_inks_only(self):
        """Red and yellow stay out of the quantiser so diffusion cannot warm the night."""
        inks = distinct_inks(rq._atropos_background())
        assert inks <= {rq.SPECTRA6[k] for k in ("black", "blue", "green", "white")}
        assert rq.SPECTRA6["blue"] in inks and rq.SPECTRA6["green"] in inks

    def test_background_is_painted_once_per_process(self):
        assert rq._atropos_background() is rq._atropos_background()

    def test_quote_is_white_with_a_tangerine_phrase(self):
        counts = ink_counts(self._render().crop(rq._ATROPOS_QUOTE_RECT))
        assert counts.get(rq.SPECTRA6["white"], 0) > 2000     # the prose
        assert counts.get(rq.SPECTRA6["yellow"], 0) > 150     # the phrase's core
        assert counts.get(rq.SPECTRA6["red"], 0) > 20         # and its halo

    def test_embers_sit_on_the_tendrils(self):
        img = self._render()
        nodules = [(x, y) for _, _, ns in rq._atropos_tendril_paths() for x, y, _ in ns]
        assert len(nodules) >= 6
        lit = sum(img.getpixel((round(x), round(y))) == rq.SPECTRA6["yellow"] for x, y in nodules)
        assert lit >= len(nodules) * 0.8

    def test_volley_and_cipher_are_seeded_from_the_quote(self):
        other = dict(self.ROW, display_quote="Nine o'clock came and went, and still nobody stirred in the house.",
                     matched_text="Nine o'clock", source_id="999", line_number=7)
        a, b = self._render(), self._render(other)
        x0, y0, x1, y1 = rq._ATROPOS_SLAB
        assert pixel_bytes(a.crop((x0, y0, x1, y1))) != pixel_bytes(b.crop((x0, y0, x1, y1)))
        # The same quote is the same volley.
        assert pixel_bytes(a) == pixel_bytes(self._render())

    def test_cipher_alphabet_is_stable_and_distinct(self):
        glyphs = {ch: rq._atropos_glyph(ch) for ch in "abcdefghijklmnopqrstuvwxyz"}
        assert all(rq._atropos_glyph(ch) == g for ch, g in glyphs.items())
        assert len(set(glyphs.values())) >= 20
        for strokes, dot in glyphs.values():
            assert 3 <= len(strokes) <= 5
            assert dot is None or dot in {(c, r) for r in range(4) for c in range(3)}

    def test_cipher_carries_the_phrase_first(self):
        text = rq._atropos_cipher_text(make_row(**self.ROW))
        assert text.startswith("half past two ")
        assert set(text) <= set("abcdefghijklmnopqrstuvwxyz ")

    def test_downscales_the_canonical_frame(self):
        small = self._render(size=(320, 192))
        big = self._render()
        assert small.size == (320, 192)
        assert pixel_bytes(small) == pixel_bytes(big.resize((320, 192), Image.Resampling.NEAREST))

    def test_volley_stays_clear_of_the_translation_frame(self):
        """An orb beside a glyph read as a yellow dot stuck to the phrase."""
        for source_id in ("141", "999", "7", "2701", "43"):
            row = dict(self.ROW, source_id=source_id)
            cold = rq._atropos_background().copy()
            rq._atropos_paint_orbs(cold, make_row(**row))
            for x0, y0, x1, y1 in (rq._atropos_quote_keepout(), rq._ATROPOS_SLAB):
                inside = cold.crop((x0 - 4, y0 - 4, x1 + 4, y1 + 4))
                assert rq.SPECTRA6["yellow"] not in distinct_inks(inside), source_id


class TestExpeditionFrame:
    """``expedition`` — Sandfall's *Clair Obscur: Expedition 33*: the Monolith
    from the Lumière promenade.

    The dusk is painted in continuous tone and dithered against the panel's
    calibrated inks; the painted hour, the gust of petals, the journal page
    and the chrome go on top. The hour is the number on the Monolith; the
    gust is seeded from the quote.
    """

    ROW = dict(
        display_quote="It was about half past two when the clock struck and the "
                      "afternoon slipped quietly away from them.",
        matched_text="half past two",
        author="Edith Wharton",
        title="The House of Mirth",
        source_id="141",
        line_number=482,
    )

    @staticmethod
    def _render(row=None, time_str="14:30", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or TestExpeditionFrame.ROW)),
                         *size, mode="production", theme="expedition")

    def test_on_palette_and_surfaces_all_six_inks(self):
        assert distinct_inks(self._render()) == set(rq.SPECTRA6.values())

    def test_every_minute_of_an_hour_renders_identically(self):
        """Hour only: nothing on the frame reads the clock's minute."""
        first = pixel_bytes(self._render(time_str="09:00"))
        for minute in (5, 17, 30, 59):
            assert pixel_bytes(self._render(time_str=f"09:{minute:02d}")) == first

    def test_number_on_the_monolith_follows_the_hour(self):
        box = rq._EXPEDITION_NUMERAL_BOX
        crops = {pixel_bytes(self._render(time_str=f"{h:02d}:00").crop(box)) for h in range(1, 13)}
        assert len(crops) == 12
        assert rq._expedition_hour("13:00") == rq._expedition_hour("01:00") == 1
        assert rq._expedition_hour("00:10") == rq._expedition_hour("12:10") == 12

    def test_number_is_painted_in_the_box(self):
        """The painted hour is a lit yellow core inside the Monolith's face;
        its drips may run below the box but nothing else leaves it."""
        x0, y0, x1, y1 = rq._EXPEDITION_NUMERAL_BOX
        for hour in (1, 7, 12):
            mask = rq._expedition_numeral_mask(hour)
            assert mask is rq._expedition_numeral_mask(hour)
            bx0, by0, bx1, by1 = mask.getbbox()
            assert bx0 >= x0 - 12 and bx1 <= x1 + 12 and by0 >= y0 - 6 and by1 <= y1 + 64
            counts = ink_counts(self._render(time_str=f"{hour:02d}:00").crop((x0, y0, x1, y1)))
            assert counts.get(rq.SPECTRA6["yellow"], 0) > 800
            assert counts.get(rq.SPECTRA6["white"], 0) > 150

    def test_scene_is_quantised_against_the_calibrated_inks(self):
        """A field of the panel's *measured* red must come back as pure red,
        and the measured pink (red + white averaged) as a half-and-half
        stipple of those two inks — proof the quantiser saw the measured
        colours and the output was re-labelled with the nominal ones."""
        measured_red = rq._EXPEDITION_PANEL_INKS["red"]
        flat = Image.new("RGB", (64, 64), measured_red)
        assert distinct_inks(rq._expedition_dither(flat, rq._EXPEDITION_SKY_INKS)) == {rq.SPECTRA6["red"]}
        pink = tuple((a + b) // 2 for a, b in zip(measured_red, rq._EXPEDITION_PANEL_INKS["white"]))
        counts = ink_counts(rq._expedition_dither(Image.new("RGB", (64, 64), pink), rq._EXPEDITION_SKY_INKS))
        assert counts.get(rq.SPECTRA6["red"], 0) > 64 * 64 * 0.3
        assert counts.get(rq.SPECTRA6["white"], 0) > 64 * 64 * 0.3
        assert distinct_inks(rq._expedition_dither(flat, rq._EXPEDITION_SKY_INKS)) <= set(rq.SPECTRA6.values())

    def test_sky_has_no_green_and_the_sea_has_some(self):
        """Green stays out of the sky's quantiser; the water gets it back for the teal."""
        background = rq._expedition_background()
        sky = background.crop((0, 0, 800, rq._EXPEDITION_HORIZON))
        assert rq.SPECTRA6["green"] not in distinct_inks(sky)
        sea = background.crop((0, rq._EXPEDITION_HORIZON + 1, 540, rq._EXPEDITION_RAIL_TOP))
        assert rq.SPECTRA6["green"] in distinct_inks(sea)

    def test_background_is_painted_once_per_process(self):
        assert rq._expedition_background() is rq._expedition_background()

    def test_lamp_is_lit(self):
        gx0, gy0, gx1, gy1 = rq._EXPEDITION_LAMP_GLASS
        counts = ink_counts(self._render().crop((gx0, gy0, gx1, gy1)))
        lit = counts.get(rq.SPECTRA6["yellow"], 0) + counts.get(rq.SPECTRA6["white"], 0)
        assert lit > (gx1 - gx0) * (gy1 - gy0) * 0.6

    def test_quote_is_white_with_the_phrase_in_paint(self):
        counts = ink_counts(self._render().crop(rq._EXPEDITION_QUOTE_RECT))
        assert counts.get(rq.SPECTRA6["white"], 0) > 2000     # the prose
        assert counts.get(rq.SPECTRA6["yellow"], 0) > 150     # the phrase's core
        assert counts.get(rq.SPECTRA6["red"], 0) > 20         # and its halo

    def test_wordmark_and_credo_are_painted(self):
        image = self._render()
        wordmark = ink_counts(image.crop(rq._EXPEDITION_WORDMARK_BOX))
        assert wordmark.get(rq.SPECTRA6["white"], 0) > 400     # CLAIR OBSCUR / EXPEDITION 33
        assert wordmark.get(rq.SPECTRA6["yellow"], 0) > 150    # the gold rule and its diamonds
        credo = ink_counts(image.crop(rq._EXPEDITION_CREDO_BOX))
        assert credo.get(rq.SPECTRA6["yellow"], 0) > 150

    def test_gust_is_seeded_from_the_quote_and_keeps_out_of_the_page(self):
        other = dict(self.ROW, display_quote="Nine o'clock came and went, and still nobody stirred in the house.",
                     matched_text="Nine o'clock", source_id="999", line_number=7)
        a = rq._expedition_gust(make_row(**self.ROW))
        b = rq._expedition_gust(make_row(**other))
        assert a and b and a != b
        assert a == rq._expedition_gust(make_row(**self.ROW))
        keepouts = (rq._expedition_quote_keepout(), rq._EXPEDITION_WORDMARK_BOX, rq._EXPEDITION_CREDO_BOX,
                    rq._EXPEDITION_NUMERAL_BOX, rq._EXPEDITION_LAMP_BOX)
        for source_id in ("141", "999", "7", "2701", "43"):
            for x, y, size, _, density in rq._expedition_gust(make_row(**dict(self.ROW, source_id=source_id))):
                assert size < y < rq._EXPEDITION_RAIL_TOP and 0 < x < 800
                assert 0.3 <= density <= 0.7
                for kx0, ky0, kx1, ky1 in keepouts:
                    assert not (kx0 - size < x < kx1 + size and ky0 - size < y < ky1 + size), source_id
        # The same quote is the same gust, byte for byte.
        assert pixel_bytes(self._render()) == pixel_bytes(self._render())

    def test_petals_are_pink(self):
        """A petal is a red + white stipple: the gust's pixels carry both inks."""
        background = rq._expedition_background().copy()
        rq._expedition_paint_petals(background, make_row(**self.ROW))
        diff = ImageChops.difference(background, rq._expedition_background()).convert("L").point(lambda v: 255 if v else 0)
        touched = ink_counts(Image.composite(background, Image.new("RGB", background.size, (1, 2, 3)), diff))
        assert touched.get(rq.SPECTRA6["white"], 0) > 300
        assert touched.get(rq.SPECTRA6["red"], 0) > 300

    def test_downscales_the_canonical_frame(self):
        small = self._render(size=(320, 192))
        big = self._render()
        assert small.size == (320, 192)
        assert pixel_bytes(small) == pixel_bytes(big.resize((320, 192), Image.Resampling.NEAREST))


class TestWitcherFrame:
    """``witcher`` — The Witcher 3: a bestiary page under the meditation dial.

    The page is cached once per process; the hour is the sun or moon on the
    dial's radius; the signs the entry is susceptible to are seeded from the
    quote.
    """

    ROW = dict(
        display_quote="It was about half past two when the clock struck and the "
                      "afternoon slipped quietly away from them.",
        matched_text="half past two",
        author="Edith Wharton",
        title="The House of Mirth",
        source_id="141",
        line_number=482,
    )

    @staticmethod
    def _render(row=None, time_str="14:30", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or TestWitcherFrame.ROW)),
                         *size, mode="production", theme="witcher")

    @staticmethod
    def _dial_box():
        cx, cy = rq._WITCHER_DIAL_CENTRE
        r = rq._WITCHER_DIAL_RADIUS
        return (cx - r, cy - r, cx + r, cy + r)

    def test_on_palette_and_surfaces_all_six_inks(self):
        """Blue arrives only with Aard or Yrden, so pick an entry susceptible to one."""
        assert distinct_inks(self._render()) <= set(rq.SPECTRA6.values())
        row = next(dict(self.ROW, source_id=str(n)) for n in range(1, 400)
                   if rq._witcher_susceptible(make_row(**dict(self.ROW, source_id=str(n)))) & {"AARD", "YRDEN"})
        assert distinct_inks(self._render(row)) == set(rq.SPECTRA6.values())

    def test_every_minute_of_an_hour_renders_identically(self):
        first = pixel_bytes(self._render(time_str="09:00"))
        for minute in (5, 17, 30, 59):
            assert pixel_bytes(self._render(time_str=f"09:{minute:02d}")) == first

    def test_marker_walks_the_dial_and_knows_night_from_day(self):
        crops = {pixel_bytes(self._render(time_str=f"{h:02d}:00").crop(self._dial_box())) for h in range(24)}
        assert len(crops) == 24          # twelve radii, each with a sun and a moon
        assert rq._witcher_hour("13:00") == 13 and rq._witcher_hour("00:10") == 0
        assert rq._witcher_hour("garbage") == 12

    def test_page_is_painted_once_per_process(self):
        assert rq._witcher_page() is rq._witcher_page()

    def test_page_is_deckled_cream_in_a_dark_binding(self):
        page = rq._witcher_page()
        x0, y0, x1, y1 = rq._WITCHER_PAGE_RECT
        inside = ink_counts(page.crop((x0 + 40, y0 + 40, x0 + 140, y0 + 60)))
        assert inside.get(rq.SPECTRA6["white"], 0) > 100 * 20 * 0.6
        assert inside.get(rq.SPECTRA6["yellow"], 0) > 50
        outside = ink_counts(page.crop((0, 0, 800, y0 - 8)))
        assert outside.get(rq.SPECTRA6["black"], 0) > 800 * (y0 - 8) * 0.8
        mask = rq._witcher_page_mask((800, 480))
        edge = mask.crop((x0 + 60, y1 - 4, x0 + 460, y1))
        assert 0 < edge.histogram()[255] < 400 * 4    # torn, not ruled

    def test_medallion_carries_the_numeral(self):
        cx, cy = rq._WITCHER_DIAL_CENTRE
        r = rq._WITCHER_MEDALLION_RADIUS
        counts = ink_counts(self._render().crop((cx - r, cy - r, cx + r, cy + r)))
        assert counts.get(rq.SPECTRA6["black"], 0) > 2500     # the disc and the weathering
        assert counts.get(rq.SPECTRA6["white"], 0) > 1800     # the III and the silver rings
        # Three bars: a horizontal scan through the device crosses white six times.
        y = cy
        row = [self._render().getpixel((x, y)) == rq.SPECTRA6["white"] for x in range(cx - r + 8, cx + r - 8)]
        crossings = sum(1 for a, b in zip(row, row[1:]) if a != b)
        assert crossings == 6

    def test_quote_is_black_with_a_tangerine_phrase(self):
        counts = ink_counts(self._render().crop(rq._WITCHER_QUOTE_RECT))
        assert counts.get(rq.SPECTRA6["black"], 0) > 2000
        assert counts.get(rq.SPECTRA6["red"], 0) > 150
        assert counts.get(rq.SPECTRA6["yellow"], 0) > 150

    def test_header_carries_the_title_and_the_gutenberg_id(self):
        a = self._render()
        b = self._render(dict(self.ROW, title="Persuasion", source_id="105"))
        header = (56, rq._WITCHER_HEADER_Y - 4, 744, rq._WITCHER_HEADER_RULE_Y - 2)
        assert pixel_bytes(a.crop(header)) != pixel_bytes(b.crop(header))

    def test_susceptibility_is_seeded_from_the_quote(self):
        other = dict(self.ROW, source_id="2701", line_number=9)
        foot = (rq._WITCHER_SIGNS_RIGHT - 140, rq._WITCHER_FOOT_Y - 2, rq._WITCHER_SIGNS_RIGHT + 2, rq._WITCHER_FOOT_Y + 22)
        a, b = self._render(), self._render(other)
        assert pixel_bytes(a.crop(foot)) != pixel_bytes(b.crop(foot))
        assert pixel_bytes(a) == pixel_bytes(self._render())
        assert rq._witcher_susceptible(make_row(**self.ROW))
        assert distinct_inks(a.crop(foot)) - {rq.SPECTRA6["black"], rq.SPECTRA6["white"], rq.SPECTRA6["yellow"]}

    def test_downscales_the_canonical_frame(self):
        small = self._render(size=(320, 192))
        big = self._render()
        assert small.size == (320, 192)
        assert pixel_bytes(small) == pixel_bytes(big.resize((320, 192), Image.Resampling.NEAREST))
