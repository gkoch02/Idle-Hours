"""Smoke tests for the custom-render themes that bypass the standard literary layout.

These themes (``astrarium``, ``diags``, ``marquee``, ``tarot``,
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
import functools
import json
import math
import pathlib
import threading
from itertools import pairwise
from types import MappingProxyType

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from idle_hours import pick_quote as pq
from idle_hours import render_quote as rq
from idle_hours.jsonl_io import iter_jsonl
from idle_hours.render_quote import text as rq_text
from idle_hours.render_quote import themes as rq_themes

from .conftest import make_row
from .pixel_helpers import distinct_inks, ink_counts, pixel_bytes

CUSTOM_THEMES = ("marquee", "tarot", "vitrail", "outrun", "sampler", "lieder", "izakaya",
                 "abyssal", "pride", "pulp", "vhs", "cardcatalog", "metro", "bakelite",
                 "nocturne", "plaque", "daguerreotype")


# Input samples for the sweeps that pin a frame to the hour (issue #397).
# "Every minute of an hour renders identically" and "every hour renders" are
# properties that break at boundaries, not in the middle of a range, so the
# sweeps render the boundaries instead of all 60 minutes or all 24 hours.
#
# EDGE_MINUTES straddles every way a minute could leak in. ``buckets`` rounds
# with ((minute + 2) // 5) * 5, so 00 and 02 share the :00 bucket and 03 opens
# the :05 one; 27 | 28 and 32 | 33 are the two edges of the :30 bucket, with
# the half hour between them; and 58 and 59 round forward into the *next*
# hour's :00 bucket while 57 does not. A raw minute, a rounded minute, a
# past/to switch at the half hour and an hour rolled forward by rounding each
# separate at least two of these.
EDGE_MINUTES = (0, 2, 3, 27, 28, 30, 32, 33, 57, 58, 59)
# EDGE_HOURS covers the 12-hour clock's wraps (midnight 00 and noon 12, which
# both read 12; 11 -> 12 -> 1 and its PM twin 23 / 13) plus one mid-afternoon
# hour away from any wrap.
EDGE_HOURS = (0, 1, 11, 12, 13, 15, 23)


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
        monkeypatch.setattr(rq_themes.tarot, "TAROT_PLATES", pathlib.Path("/nonexistent/tarot_plates.png"))
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
        for _hour, numeral in rq._TAROT_ROMAN_NUMERALS.items():
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
        monkeypatch.setattr(rq_themes.tarot, "TAROT_PLATES", pathlib.Path("/nonexistent/tarot_plates.png"))
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
            rq_themes.tarot, "_tarot_paint_card_name",
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
        """The numeral mapping renders without raising and stays on-palette
        across the 12-hour clock's wraps (the 00 and 12 -> XII rollovers,
        11 -> XII -> I) and a mid-afternoon hour. A numeral that broke would
        break at a wrap, so ``EDGE_HOURS`` stands in for all 24 (issue #397)."""
        palette = set(rq.SPECTRA6.values())
        for hh in EDGE_HOURS:
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
                rq._lieder_contour(rq._row_digest(row), notes)
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
        theme_module = getattr(rq_themes, painter_name.split("_")[1])
        monkeypatch.setattr(theme_module, box_name, (box[0], box[1], box[0] + 1, box[3]))
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
        for earlier, later in pairwise(samples):
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
    @functools.cache
    def _bands(width: int = 800, height: int = 480) -> tuple[MappingProxyType, ...]:
        """Ink histograms per chevron band, bucketed by the painter's own term.

        Memoised (read-only) because the walk is a per-pixel Python loop that
        costs ~10 s and the three tests below all read the same 800x480 flag:
        measuring it once per worker instead of once per test (issue #397)
        changes nothing they assert.
        """
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
        return tuple(MappingProxyType(bucket) for bucket in buckets)

    def test_band_inks_and_order(self):
        buckets = self._bands()
        for index, (base, minority, _share) in enumerate(self.EXPECTED):
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

    ``runtime_render.current_time_str`` is ``datetime.now().strftime("%H:%M")`` —
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

    def test_frame_ignores_the_system_date(self, monkeypatch):
        """The regression this class exists for."""
        import datetime as _dt

        row = self._row()
        before = pixel_bytes(rq.render("14:30", row, 800, 480,
                                       mode="production", theme="vhs"))
        monkeypatch.setattr(rq.clock, "now", lambda: _dt.datetime(2031, 12, 25, 3, 4, 5))
        after = pixel_bytes(rq.render("14:30", row, 800, 480,
                                      mode="production", theme="vhs"))
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

        original = rq_themes.vhs.draw_text_chroma_shift
        try:
            rq_themes.vhs.draw_text_chroma_shift = flat
            base = ink_counts(rq.render("14:30", row, 800, 480,
                                        mode="production", theme="vhs"))
        finally:
            rq_themes.vhs.draw_text_chroma_shift = original

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
            rq_themes.vhs._vhs_apply_tears = lambda image: None
            clean = rq.render("14:30", row, 800, 480, mode="production", theme="vhs")
        finally:
            rq_themes.vhs._vhs_apply_tears = original

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
            real = rq_themes.vhs.draw_text_chroma_shift

            def maybe_ghostless(img, xy, text, font, *, core=None, left=None,
                                right=None, offset=2, ground=None):
                if not ghosts:
                    left = right = None
                return real(img, xy, text, font, core=core, left=left, right=right,
                            offset=offset, ground=ground)

            original_offset = rq._VHS_CHROMA_OFFSET
            try:
                rq_themes.vhs._VHS_CHROMA_OFFSET = offset
                rq_themes.vhs.draw_text_chroma_shift = maybe_ghostless
                rq._vhs_paint_quote(image, draw, row)
            finally:
                rq_themes.vhs.draw_text_chroma_shift = real
                rq_themes.vhs._VHS_CHROMA_OFFSET = original_offset
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

    FIXED_GEOMETRY_FRAMES = ("vhs", "cardcatalog", "metro", "bakelite", "nocturne",
                             "plaque", "daguerreotype", "autochrome", "photo", "tarot",
                             "control", "observation", "trisolaris", "biomech", "codex",
                             "culture", "orbital", "furies", "bosch", "saros", "goya",
                             "hal", "lumon", "dsky", "oblivion", "yorha", "hitchhiker",
                             "escritoire", "lasvegas", "bladerunner")

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
    for a fixed row, and the hours must all differ.

    Both sweeps render the boundaries rather than the whole range (issue
    #397): ``EDGE_MINUTES`` for the minutes, ``EDGE_HOURS`` for the hours.
    """

    ROW = make_row(display_quote="At half past two the bell rang and nobody moved.",
                   matched_text="half past two", author="L. M. Montgomery",
                   title="Anne of Avonlea")

    def _frame(self, time_str):
        return pixel_bytes(rq.render(time_str, self.ROW, 800, 480, mode="production", theme="bakelite"))

    def test_no_minute_reaches_the_console(self):
        frames = {self._frame(f"09:{minute:02d}") for minute in EDGE_MINUTES}
        assert len(frames) == 1, (
            "the minute is reaching the bakelite frame — the console shows an hour "
            "index, not a clock reading, and the matched phrase is the time carrier"
        )

    def test_every_hour_renders_differently(self):
        """Hours a 12-hour clock tells apart render differently, and the AM
        and PM twins (00 and 12, 01 and 13, 11 and 23) render the same."""
        frames = {hour: self._frame(f"{hour:02d}:30") for hour in EDGE_HOURS}
        for hour in EDGE_HOURS:
            for other in EDGE_HOURS:
                same_hour = hour % 12 == other % 12
                assert (frames[hour] == frames[other]) == same_hour, (
                    f"{hour:02d}:30 and {other:02d}:30 "
                    + ("render different consoles" if same_hour else "render the same console")
                )


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
        assert set(y - x for x, y in pairwise(lit)) == {3}, (
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
        """No yellow or red pixel lies outside the quote, rocket, water and butterfly.

        Built as a mask with the allowed boxes blanked out (inclusive bounds,
        as ``ImageDraw.rectangle`` draws them) rather than a per-pixel Python
        walk of the frame, which cost ~9 s for the same answer (issue #397).
        """
        img = self._render()
        gold = Image.new("L", img.size, 0)
        for ink in (rq.SPECTRA6["yellow"], rq.SPECTRA6["red"]):
            delta = ImageChops.difference(img, Image.new("RGB", img.size, ink)).split()
            off_ink = ImageChops.lighter(ImageChops.lighter(delta[0], delta[1]), delta[2])
            gold = ImageChops.lighter(gold, off_ink.point(lambda v: 255 if v == 0 else 0))
        qx0, qy0, qx1, qy1 = rq._NOCTURNE_QUOTE_RECT
        blank = ImageDraw.Draw(gold)
        blank.rectangle((qx0 - 16, qy0 - 16, qx1 + 16, qy1 + 16), fill=0)    # the quote
        blank.rectangle((520, 0, 800, 262), fill=0)                          # the rocket
        blank.rectangle((0, rq._NOCTURNE_SHORE[0] - 6, 800, 480), fill=0)    # the water
        blank.rectangle((728, 408, 780, 452), fill=0)                        # the butterfly
        bbox = gold.getbbox()
        if bbox is not None:
            mask = gold.load()
            strays = [(x, y) for y in range(bbox[1], bbox[3]) for x in range(bbox[0], bbox[2]) if mask[x, y]]
            pytest.fail(f"gold ink leaked outside the lit elements: {strays[:10]}")

    def test_time_never_reaches_the_canvas(self):
        frames = {pixel_bytes(self._render(t)) for t in ("03:07", "03:52", "09:30", "23:59")}
        assert len(frames) == 1, (
            "two clock times rendered differently — nocturne del-asserts time_str and "
            "the matched phrase alone carries the time"
        )

    def test_quote_bloom_cannot_eat_the_rocket(self, monkeypatch):
        lit = self._render()
        monkeypatch.setattr(rq_themes.nocturne, "_nocturne_paint_quote", lambda *a, **k: None)
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
        """Every minute of an hour casts the same tablet; every hour its own.

        Sampled at the boundaries (issue #397): the minutes of the noon hour,
        where a minute rounded forward (12:58 -> 13:00) would also cross the
        12 -> 1 wrap, and ``EDGE_HOURS`` at the half hour, whose AM and PM
        twins must cast the same Roman hour.
        """
        noon = {minute: self._frame(f"12:{minute:02d}") for minute in EDGE_MINUTES}
        assert len(set(noon.values())) == 1, (
            "two minutes of the same hour rendered differently — a minute is reaching "
            "the plaque, whose only time device is the ERECTED year's Roman hour"
        )
        hours = {hour: noon[30] if hour == 12 else self._frame(f"{hour:02d}:30") for hour in EDGE_HOURS}
        for hour in EDGE_HOURS:
            for other in EDGE_HOURS:
                same_hour = hour % 12 == other % 12
                assert (hours[hour] == hours[other]) == same_hour, (
                    f"{hour:02d}:30 and {other:02d}:30 "
                    + ("cast different tablets" if same_hour else "produced the same tablet")
                )


class TestDaguerreotypePlate:
    """The Atkinson mechanism (the #227 kill criterion) and the case's rules.

    Atkinson must be *measurably* different from Floyd-Steinberg on the 2-ink
    sub-palette — blown highlights, crushed shadows — or the dithering half of
    the theme's pitch collapses. The case rules: the silver stays achromatic,
    the tarnish stays in its rim annulus, the quote is stamped on the lid's
    velvet, the case opens on a hinge, no clock reaches the canvas, and a
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
        monkeypatch.setattr(rq_themes.daguerreotype, "DAGUERREOTYPE_PLATE", rq.BASE_DIR / "assets" / "no_such_plate.png")
        img = self._render()
        counts = ink_counts(img.crop((540, 120, 650, 380)))
        assert counts.get(rq.SPECTRA6["white"], 0) > 0 and counts.get(rq.SPECTRA6["black"], 0) > 0, (
            "the fallback did not paint a photograph-shaped silver image"
        )

    def test_the_quote_is_stamped_on_the_velvet(self):
        """The case lies open: the quote sits on the lid's red pad in gold,
        the matched phrase in white, with no cream card anywhere."""
        text = self._render().crop(rq._DAG_TEXT)
        inks = distinct_inks(text)
        allowed = {rq.SPECTRA6[c] for c in ("red", "black", "yellow", "white")}
        assert inks <= allowed, f"stray inks {inks - allowed} on the velvet"
        counts = ink_counts(text)
        assert counts.get(rq.SPECTRA6["red"], 0) > 0.5 * text.width * text.height, (
            "the pad behind the stamped quote is no longer velvet"
        )
        assert counts.get(rq.SPECTRA6["yellow"], 0) > 0, "the gold stamping is missing"
        assert counts.get(rq.SPECTRA6["white"], 0) > 0, "the matched phrase lost its white"

    def test_the_case_opens_on_a_hinge(self):
        """Black leather between the halves, pewter knuckles on the spine."""
        px = self._render().load()
        spine = (rq._DAG_LID[2] + rq._DAG_BASE[0]) // 2
        assert px[spine, 240] == rq.SPECTRA6["black"], "the spine is not leather"
        knuckle = {px[spine + dx, rq._DAG_HINGES[0] + 10 + dy] for dx in (0, 1) for dy in (0, 1)}
        assert knuckle == {rq.SPECTRA6["white"], rq.SPECTRA6["black"]}, "the hinge is missing"


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
        monkeypatch.setattr(rq_text, "draw_faux_gray_text", boom)
        monkeypatch.setattr(rq_text, "draw_faux_3way_text", boom)
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
        monkeypatch.setattr(rq_text, "draw_text_dithered", boom)
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

    The slide rules follow: the caption is lettered on the black mask under
    the window, the mask frames the plate on every side, no clock reaches the
    canvas, and a stripped install still gets a colour picture.
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

    def test_the_caption_is_lettered_on_the_mask(self):
        """The slide carries its caption on the black mask, not on a card: the
        strip under the window holds only mask, white letters and the yellow
        matched phrase, and all three are present."""
        caption = self._render().crop(rq._AUTOCHROME_CAPTION)
        inks = distinct_inks(caption)
        allowed = {rq.SPECTRA6[c] for c in ("black", "white", "yellow")}
        assert inks <= allowed, (
            f"stray inks {inks - allowed} under the window — the plate is leaking "
            "into the caption, or a card has crept back"
        )
        counts = ink_counts(caption)
        assert counts.get(rq.SPECTRA6["black"], 0) > 0.6 * caption.width * caption.height, (
            "the caption strip is not mostly black mask"
        )
        assert rq.SPECTRA6["yellow"] in inks, "the matched phrase lost its yellow"

    def test_the_mask_frames_the_window(self):
        """Black paper on every side of the window, the plate's chroma only
        inside it, and the projectionist's white thumb-spot in the corner."""
        image = self._render()
        px = image.load()
        black = rq.SPECTRA6["black"]
        x0, y0, x1, y1 = rq._AUTOCHROME_WINDOW
        for x, y in ((x0 // 2, 240), ((x1 + 800) // 2, 240), (400, y0 // 3), (400, 476)):
            assert px[x, y] == black, f"mask missing at ({x}, {y})"
        window = image.crop((x0 + 12, y0 + 12, x1 - 12, y1 - 12))
        for ink in ("blue", "green", "red"):
            assert ink_counts(window).get(rq.SPECTRA6[ink], 0) > 0, (
                f"no {ink} in the window — the transparency is not a colour plate"
            )
        cx, cy, _ = rq._AUTOCHROME_THUMB_SPOT
        assert px[cx, cy] == rq.SPECTRA6["white"], "the thumb-spot is missing"

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
        monkeypatch.setattr(rq_themes.autochrome, "AUTOCHROME_PLATE", tmp_path / "absent.png")
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

    @staticmethod
    def _dark_ramp(peak, power):
        """A grey ramp from black, so its darkest tones are what an offset
        would move first."""
        source = Image.new("RGB", (800, 480))
        px = source.load()
        for x in range(800):
            v = int(peak * (x / 799) ** power)
            for y in range(480):
                px[x, y] = (v, v, v)
        return source

    def _assert_keeps_blacks(self, source, *, compressed=False):
        assert rq._photo_measure(source)[1] < rq._PHOTO_LIFT_TARGET - rq._PHOTO_MEAN_TOLERANCE, (
            "fixture is not dark enough to be lifted")
        if compressed:
            lifted_spread = rq._photo_measure(rq._photo_lift(source, rq._PHOTO_LIFT_TARGET))[2]
            assert lifted_spread > rq._PHOTO_SPREAD_CEILING, (
                "fixture's lifted spread is under the ceiling, so contrast compression never runs")
        conditioned = rq._photo_condition(source)
        hist = conditioned.convert("L").histogram()
        darkest_2pct = next(i for i, _ in enumerate(hist) if sum(hist[:i + 1]) >= 0.02 * 800 * 480)
        assert darkest_2pct < 30, (
            f"the darkest 2% of a lifted photograph sits at {darkest_2pct}/255 — "
            "something is raising the black point instead of the mid-tones")
        mean = rq._photo_measure(conditioned)[1]
        assert abs(mean - rq._PHOTO_LIFT_TARGET) <= rq._PHOTO_MEAN_TOLERANCE, (
            f"lifted to {mean:.2f} against a {rq._PHOTO_LIFT_TARGET} target")

    def test_a_dark_photograph_keeps_its_blacks(self):
        """The lift is a gamma curve, not an offset. An offset raised a dark
        forest scene's black point to ~36% grey, so nothing on the panel stayed
        dark and the whole frame read as fog."""
        self._assert_keeps_blacks(self._dark_ramp(160, 2))

    def test_a_high_contrast_dark_photograph_keeps_its_blacks(self):
        """A night scene with bright highlights is still too contrasty after
        the lift, so contrast compression runs. Compressing around the mean
        adds ``mean * (1 - scale)`` to black (~32/255 at the 0.75 floor),
        undoing the lift's guarantee; it has to scale toward black and let the
        gamma lift restore the mean."""
        self._assert_keeps_blacks(self._dark_ramp(255, 3), compressed=True)

    def test_a_moderately_dark_photograph_is_not_forced_high_key(self, tmp_path):
        """The autochrome mean is a ceiling for bright photographs, not a
        target for every one. A scene already inside the lift band keeps its
        exposure."""
        path = self._photo(tmp_path / "dusk.png", chroma_boost=0.25, mean=0.50)
        with Image.open(path) as raw:
            source = rq._photo_cover_crop(raw.convert("RGB"), 800, 480)
        before = rq._photo_measure(source)[1]
        after = rq._photo_measure(rq._photo_condition(source))[1]
        assert abs(after - before) < 0.03, f"an in-band dusk photograph moved {before:.2f} -> {after:.2f}"

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
            im.transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(tmp_path / "br.png")
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
        monkeypatch.setattr(rq_themes.photo, "_PHOTO_MAX_PIXELS", 100)  # 16x16 = 256 px, over it

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
        monkeypatch.setattr(rq_themes.photo, "_PHOTO_MAX_PIXELS", declared // 4)
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
        monkeypatch.setattr(rq_themes.photo, "_PHOTO_MAX_PIXELS", 100)
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
        monkeypatch.setattr(rq_themes.photo, "_photo_for_row", lambda row: photo)
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
        monkeypatch.setattr(rq_themes.photo, "_photo_for_row", lambda row: photo)
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

    def test_the_default_picture_is_not_autochromes(self):
        """Unconfigured, the theme shows its own coast, not ``autochrome``'s
        garden: borrowing that plate made the two themes look the same in the
        rotation. The coast is a blue-and-yellow picture where the garden is
        a green-and-red one, so the ink mix tells them apart."""
        assert rq_themes.photo.PHOTO_PLATE != rq.AUTOCHROME_PLATE
        rq.clear_photo_cache()
        plate, _ = rq_themes.photo._photo_fallback_frame(800, 480)
        counts = ink_counts(plate)
        coast = counts.get(rq.SPECTRA6["blue"], 0) + counts.get(rq.SPECTRA6["yellow"], 0)
        meadow = counts.get(rq.SPECTRA6["green"], 0) + counts.get(rq.SPECTRA6["red"], 0)
        assert coast > 2 * meadow, (
            f"blue+yellow {coast} vs green+red {meadow} — the default picture no "
            "longer reads as a coast"
        )
        for ink in rq.SPECTRA6.values():
            assert counts.get(ink, 0) > 0, "the coast plate has dropped an ink"

    def test_a_stripped_install_still_renders(self, tmp_path, monkeypatch):
        """Fallback of the fallback: nothing configured *and* the bundled plate
        gone. The synthesised coast keeps the theme a colour picture."""
        monkeypatch.setattr(rq_themes.photo, "PHOTO_PLATE", tmp_path / "absent.png")
        rq.clear_photo_cache()
        rq._DITHER_CACHE.clear()
        image = self._render()
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        counts = ink_counts(image)
        total = 800 * 480
        for ink in ("blue", "yellow", "green"):
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

        monkeypatch.setattr(rq_themes.control, "paint_neon_mask", core_only)
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

        monkeypatch.setattr(rq_themes.control, "paint_neon_mask", core_only)
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
        monkeypatch.setattr(rq_themes.control, "_CONTROL_RESONANCE", ())
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
        monkeypatch.setattr(rq_themes.control, "CONTROL_PLATE", tmp_path / "missing.png")
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
        for path in (rq.PLEXMONO_MEDIUM, rq.PLEXMONO_SEMIBOLD, rq.PLEXMONO_BOLD):
            assert pathlib.Path(path).exists(), path
        assert (pathlib.Path(rq.PLEXMONO_BOLD).parent / "OFL.txt").exists()

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
        monkeypatch.setattr(rq_themes.observation, "_observation_paint_tears", lambda image: None)
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

        monkeypatch.setattr(rq_themes.observation, "paint_neon_mask", core_only)
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
            cx = sum(m * s[0] for m, s in zip(masses, sample[0], strict=True)) / total
            cy = sum(m * s[1] for m, s in zip(masses, sample[0], strict=True)) / total
            assert abs(cx) < 1e-9 and abs(cy) < 1e-9

    def test_both_eras_occur_and_neither_dominates(self):
        """The era is physics, not decoration — so the day must actually
        contain both, each for a real share of the dial's buckets."""
        stable = [rq._trisolaris_era(f"{h:02d}:{m:02d}")[0] for h in range(12) for m in range(0, 60, 5)]
        share = sum(stable) / len(stable)
        assert 0.3 <= share <= 0.8, share
        switches = sum(1 for a, b in pairwise(stable) if a != b)
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

        monkeypatch.setattr(rq_themes.trisolaris, "_trisolaris_planet_accel", watched_accel)
        monkeypatch.setattr(rq_themes.trisolaris, "_trisolaris_rebirth", watched_rebirth)
        monkeypatch.setattr(rq_themes.trisolaris, "_TRISOLARIS_EPHEMERIS", None)
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

        monkeypatch.setattr(rq_themes.biomech, "paint_neon_mask", core_only)
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
        monkeypatch.setattr(rq_themes.biomech, "_biomech_paint_wall", lambda image, opening: None)
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
            for (upper, uxh), (lower, lxh) in pairwise(stack):
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
        for path in (rq.JURA_MEDIUM, rq.JURA_SEMIBOLD, rq.JURA_BOLD,
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

        monkeypatch.setattr(rq_themes.culture, "paint_neon_mask", core_only)
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
        monkeypatch.setattr(rq_themes.furies, "_FURIES_SMEAR_STRENGTH", 0.0)
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
        monkeypatch.setattr(rq_themes.furies, "_FURIES_SMEAR_STRENGTH", 0.0)
        counts = ink_counts(self._render().crop(rq._FURIES_QUOTE_RECT))
        red, yellow = counts.get(rq.SPECTRA6["red"], 0), counts.get(rq.SPECTRA6["yellow"], 0)
        assert red and yellow
        assert abs(red / (red + yellow) - rq._FURIES_PHRASE_RED_RANKS / 64) < 0.06

    def test_glass_reflects_on_the_paint_only(self, monkeypatch):
        glazed = self._render()
        monkeypatch.setattr(rq_themes.furies, "_furies_paint_glass", lambda image: None)
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
        monkeypatch.setattr(rq_themes.bosch, "paint_craquelure", lambda *a, **k: None)
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
        assert all(a >= b for b, a in pairwise(paradise)), "paradise should fall toward its hinge"

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
        monkeypatch.setattr(rq_themes.semiotic, "SEMIOTIC_SIGNS", tmp_path / "absent.png")
        monkeypatch.setattr(rq_themes.semiotic, "_SEMIOTIC_SHEET_CACHE", {})
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
        measured_red = rq._PANEL_INKS["red"]
        flat = Image.new("RGB", (64, 64), measured_red)
        assert distinct_inks(rq._dither_calibrated(flat, rq._EXPEDITION_SKY_INKS)) == {rq.SPECTRA6["red"]}
        pink = tuple((a + b) // 2 for a, b in zip(measured_red, rq._PANEL_INKS["white"], strict=True))
        counts = ink_counts(rq._dither_calibrated(Image.new("RGB", (64, 64), pink), rq._EXPEDITION_SKY_INKS))
        assert counts.get(rq.SPECTRA6["red"], 0) > 64 * 64 * 0.3
        assert counts.get(rq.SPECTRA6["white"], 0) > 64 * 64 * 0.3
        assert distinct_inks(rq._dither_calibrated(flat, rq._EXPEDITION_SKY_INKS)) <= set(rq.SPECTRA6.values())

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

    def test_hub_carries_three_claw_slashes(self):
        cx, cy = rq._WITCHER_DIAL_CENTRE
        r = rq._WITCHER_MEDALLION_RADIUS
        image = self._render()
        counts = ink_counts(image.crop((cx - r, cy - r, cx + r, cy + r)))
        assert counts.get(rq.SPECTRA6["red"], 0) > 900        # the slashes
        assert counts.get(rq.SPECTRA6["black"], 0) > 300      # their outlines
        # Three blades: a scan across the hub above the cut crosses three runs
        # of red at least four pixels long (the page's foxing is single flecks).
        y = cy - r // 4
        row = [image.getpixel((x, y)) == rq.SPECTRA6["red"] for x in range(cx - r, cx + r)]
        runs = sum(1 for run in "".join("r" if v else "." for v in row).split(".") if len(run) >= 4)
        assert runs == 3

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


class TestHadesFrame:
    """``hades`` — Hades II: a boon at the Crossroads under the moon.

    The scene is cached once per process; the hour is the moon's phase; the
    boon's rarity is rolled from the quote's digest.
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
        return rq.render(time_str, make_row(**(row or TestHadesFrame.ROW)),
                         *size, mode="production", theme="hades")

    @staticmethod
    def _moon_box():
        cx, cy = rq._HADES_MOON_CENTRE
        r = rq._HADES_MOON_RADIUS
        return (cx - r - 2, cy - r - 2, cx + r + 3, cy + r + 3)

    def test_on_palette_and_surfaces_all_six_inks(self):
        image = self._render()
        assert distinct_inks(image) == set(rq.SPECTRA6.values())

    def test_every_minute_of_an_hour_renders_identically(self):
        first = pixel_bytes(self._render(time_str="09:00"))
        for minute in (5, 17, 30, 59):
            assert pixel_bytes(self._render(time_str=f"09:{minute:02d}")) == first

    def test_moon_walks_twelve_phases_on_a_twelve_hour_clock(self):
        crops = {h % 12: pixel_bytes(self._render(time_str=f"{h:02d}:00").crop(self._moon_box())) for h in range(12)}
        assert len(set(crops.values())) == 12
        for h in range(12):
            assert pixel_bytes(self._render(time_str=f"{h + 12:02d}:00").crop(self._moon_box())) == crops[h]

    @staticmethod
    def _disc_counts(image) -> dict:
        """Ink counts inside the moon's disc, clear of the halo round it."""
        cx, cy = rq._HADES_MOON_CENTRE
        r = rq._HADES_MOON_RADIUS - 1
        counts: dict = {}
        for y in range(cy - r, cy + r + 1):
            for x in range(cx - r, cx + r + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                    ink = image.getpixel((x, y))
                    counts[ink] = counts.get(ink, 0) + 1
        return counts

    def test_moon_is_full_at_twelve_and_new_at_six(self):
        full = self._disc_counts(self._render(time_str="12:00"))
        new = self._disc_counts(self._render(time_str="06:00"))
        area = math.pi * rq._HADES_MOON_RADIUS ** 2
        assert full.get(rq.SPECTRA6["white"], 0) > area * 0.6
        assert new.get(rq.SPECTRA6["white"], 0) < area * 0.02
        assert new.get(rq.SPECTRA6["black"], 0) > area * 0.7
        assert new.get(rq.SPECTRA6["blue"], 0) > 60          # the rim keeps a new moon a moon
        assert rq._hades_phase(12) == 0.5 and rq._hades_phase(6) == 0.0
        assert rq._hades_phase(9) == 0.25 and rq._hades_phase(3) == 0.75

    def test_scene_is_painted_once_per_process(self):
        assert rq._hades_scene() is rq._hades_scene()

    def test_sky_is_a_dithered_night_over_black_earth(self):
        scene = rq._hades_scene()
        sky = ink_counts(scene.crop((40, 60, 400, 100)))
        assert sky.get(rq.SPECTRA6["blue"], 0) > 360 * 40 * 0.3
        assert sky.get(rq.SPECTRA6["black"], 0) > 360 * 40 * 0.2
        assert sky.get(rq.SPECTRA6["white"], 0) > 20            # stars
        assert rq.SPECTRA6["green"] not in sky and rq.SPECTRA6["red"] not in sky
        x0, y0, x1, y1 = rq._HADES_PANEL_RECT
        earth = ink_counts(scene.crop((x1 + 4, y0 + 40, 800, y1 - 40)))
        assert earth.get(rq.SPECTRA6["black"], 0) > (800 - x1 - 4) * (y1 - y0 - 80) * 0.9

    def test_witchfire_burns_green_over_the_braziers(self):
        scene = rq._hades_scene()
        for bx in rq._HADES_BRAZIERS:
            flame = ink_counts(scene.crop((bx - 20, rq._HADES_RIDGE_Y - 50, bx + 20, rq._HADES_RIDGE_Y)))
            assert flame.get(rq.SPECTRA6["green"], 0) > 150
            assert flame.get(rq.SPECTRA6["white"], 0) > 60

    def test_card_carries_a_gold_frieze_and_an_hourglass(self):
        scene = rq._hades_scene()
        x0, y0, x1, y1 = rq._HADES_PANEL_RECT
        top = rq._HADES_FRIEZE_TOP
        frieze = ink_counts(scene.crop((x0 + 30, top, x1 - 30, top + 3 * rq._HADES_FRIEZE_UNIT)))
        assert frieze.get(rq.SPECTRA6["yellow"], 0) > (x1 - x0 - 60) * 2
        cx, cy = rq._HADES_MEDALLION_CENTRE
        r = rq._HADES_MEDALLION_RADIUS
        medallion = ink_counts(scene.crop((cx - r, cy - r, cx + r, cy + r)))
        assert medallion.get(rq.SPECTRA6["yellow"], 0) > 1500       # rings, frame, sand
        assert medallion.get(rq.SPECTRA6["red"], 0) > 80            # the sand's lattice
        assert medallion.get(rq.SPECTRA6["blue"], 0) > 400          # the bloom

    def test_quote_is_white_with_a_gold_phrase(self):
        counts = ink_counts(self._render().crop(rq._HADES_QUOTE_RECT))
        assert counts.get(rq.SPECTRA6["white"], 0) > 2000
        assert counts.get(rq.SPECTRA6["yellow"], 0) > 300

    def test_title_is_the_author_in_gold_with_a_red_stroke(self):
        a = self._render()
        b = self._render(dict(self.ROW, author="Homer"))
        header = (rq._HADES_TITLE_X, rq._HADES_TITLE_Y, rq._HADES_TITLE_RIGHT, rq._HADES_RULE_Y - 2)
        assert pixel_bytes(a.crop(header)) != pixel_bytes(b.crop(header))
        counts = ink_counts(a.crop(header))
        assert counts.get(rq.SPECTRA6["yellow"], 0) > 800
        assert counts.get(rq.SPECTRA6["red"], 0) > 200
        # No author: the book's title stands in for the god's name.
        c = self._render(dict(self.ROW, author=""))
        assert ink_counts(c.crop(header)).get(rq.SPECTRA6["yellow"], 0) > 800

    def test_rarity_is_rolled_from_the_quote(self):
        rows = [dict(self.ROW, source_id=str(n), line_number=n) for n in range(1, 200)]
        rolls = {rq._hades_rarity(make_row(**row)) for row in rows}
        assert rolls == {0, 1, 2, 3, 4}
        assert rq._hades_rarity(make_row(**self.ROW)) == rq._hades_rarity(make_row(**self.ROW))
        foot = (rq._HADES_TITLE_X, rq._HADES_FOOT_Y, rq._HADES_TITLE_X + 200, rq._HADES_FOOT_Y + 20)
        common = next(r for r in rows if rq._hades_rarity(make_row(**r)) == 0)
        legendary = next(r for r in rows if rq._hades_rarity(make_row(**r)) == 4)
        a, b = self._render(common), self._render(legendary)
        assert pixel_bytes(a.crop(foot)) != pixel_bytes(b.crop(foot))
        assert ink_counts(b.crop(foot)).get(rq.SPECTRA6["yellow"], 0) > ink_counts(a.crop(foot)).get(rq.SPECTRA6["yellow"], 0)

    def test_downscales_the_canonical_frame(self):
        small = self._render(size=(320, 192))
        big = self._render()
        assert small.size == (320, 192)
        assert pixel_bytes(small) == pixel_bytes(big.resize((320, 192), Image.Resampling.NEAREST))


class TestExpanseFrame:
    """``expanse`` — The Expanse: the Rocinante's console with the quote as
    an incoming tightbeam.

    The chrome is cached once per process; the hour is the tracked contact's
    bearing on the tactical plot; the ship's state is dealt from the quote's
    digest.
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
        return rq.render(time_str, make_row(**(row or TestExpanseFrame.ROW)),
                         *size, mode="production", theme="expanse")

    @staticmethod
    def _plot_box():
        cx, cy = rq._EXPANSE_PLOT_CENTRE
        r = rq._EXPANSE_PLOT_RINGS[-1] + 4
        return (cx - r, cy - r, cx + r, cy + r)

    def test_on_palette_and_surfaces_all_six_inks(self):
        image = self._render()
        assert distinct_inks(image) == set(rq.SPECTRA6.values())

    def test_every_minute_of_an_hour_renders_identically(self):
        first = pixel_bytes(self._render(time_str="09:00"))
        for minute in (5, 17, 30, 59):
            assert pixel_bytes(self._render(time_str=f"09:{minute:02d}")) == first

    def test_contact_walks_twelve_bearings_on_a_twelve_hour_clock(self):
        crops = {h % 12: pixel_bytes(self._render(time_str=f"{h:02d}:00").crop(self._plot_box())) for h in range(12)}
        assert len(set(crops.values())) == 12
        for h in range(12):
            assert pixel_bytes(self._render(time_str=f"{h + 12:02d}:00").crop(self._plot_box())) == crops[h]
        assert rq._expanse_bearing(12) == 0 and rq._expanse_bearing(3) == 90 and rq._expanse_bearing(9) == 270

    def test_contact_sits_at_the_hours_bearing(self):
        r = rq._EXPANSE_CONTACT_RADIUS
        for hour in (12, 3, 6, 9, 2):
            image = self._render(time_str=f"{hour:02d}:00")
            tx, ty = rq._expanse_polar(r, rq._expanse_bearing(hour))
            box = (int(tx) - 13, int(ty) - 13, int(tx) + 14, int(ty) + 14)
            counts = ink_counts(image.crop(box))
            assert counts.get(rq.SPECTRA6["white"], 0) >= 9           # the core
            assert counts.get(rq.SPECTRA6["yellow"], 0) > 40           # diamond, brackets, bloom
            # The opposite bearing is empty plot: rings and crosshair only.
            ox, oy = rq._expanse_polar(r, rq._expanse_bearing(hour) + 180)
            far = ink_counts(image.crop((int(ox) - 13, int(oy) - 13, int(ox) + 14, int(oy) + 14)))
            assert rq.SPECTRA6["yellow"] not in far

    def test_bearing_readout_names_the_hour(self):
        x0, _, x1, _ = rq._EXPANSE_LIST_RECT
        ry = rq._EXPANSE_LIST_ROW_Y + rq._EXPANSE_LIST_ROW_H
        band = (x0 + 40, ry + 22, x1 - 10, ry + 36)
        a = self._render(time_str="02:00").crop(band)
        b = self._render(time_str="07:00").crop(band)
        assert pixel_bytes(a) != pixel_bytes(b)
        assert ink_counts(a).get(rq.SPECTRA6["yellow"], 0) > 60

    def test_scene_is_painted_once_per_process(self):
        assert rq._expanse_scene() is rq._expanse_scene()

    def test_plot_is_blue_rings_on_black_glass(self):
        scene = rq._expanse_scene()
        counts = ink_counts(scene.crop(self._plot_box()))
        area = (2 * rq._EXPANSE_PLOT_RINGS[-1] + 8) ** 2
        assert counts.get(rq.SPECTRA6["black"], 0) > area * 0.85
        assert counts.get(rq.SPECTRA6["blue"], 0) > 900             # three gapped rings, ticks, crosshair
        assert counts.get(rq.SPECTRA6["white"], 0) > 40              # the Roci and the cardinal labels
        assert rq.SPECTRA6["yellow"] not in counts                   # no contact before the hour is known

    def test_panels_are_chamfered_glass_with_orange_brackets(self):
        scene = rq._expanse_scene()
        x0, y0, x1, y1 = rq._EXPANSE_FEED_RECT
        cut = rq._EXPANSE_CHAMFER
        # The cut corner carries no outline pixel; the square corner carries a bracket.
        assert scene.getpixel((x1, y0)) == rq.SPECTRA6["black"]
        assert scene.getpixel((x1 - cut // 2, y0 + cut // 2)) == rq.SPECTRA6["blue"]
        bracket = ink_counts(scene.crop((x0, y0, x0 + 16, y0 + 16)))
        assert bracket.get(rq.SPECTRA6["yellow"], 0) >= 40
        header = ink_counts(scene.crop((x0 + 1, y0 + 1, x0 + 8, y0 + rq._EXPANSE_HEADER_H)))
        assert header.get(rq.SPECTRA6["red"], 0) > 30 and header.get(rq.SPECTRA6["yellow"], 0) > 30
        # The feed's own frame round the quote: a blue hairline with white brackets.
        fx0, fy0, fx1, fy1 = rq._EXPANSE_FRAME_RECT
        assert scene.getpixel((fx0, (fy0 + fy1) // 2)) == rq.SPECTRA6["blue"]
        assert ink_counts(scene.crop((fx0 - 4, fy0 - 4, fx0 + 8, fy0 + 8))).get(rq.SPECTRA6["white"], 0) >= 12

    def test_orbital_strip_tag_and_list_carry_the_chrome(self):
        scene = rq._expanse_scene()
        tag = ink_counts(scene.crop((24, 8, 70, 24)))
        assert tag.get(rq.SPECTRA6["red"], 0) > 200 and tag.get(rq.SPECTRA6["yellow"], 0) > 200
        x0, y0, x1, y1 = rq._EXPANSE_ORBIT_RECT
        orbit = ink_counts(scene.crop((x0, y0, x1, y1 + 1)))
        assert orbit.get(rq.SPECTRA6["blue"], 0) > 500              # rules, the dashed track
        assert orbit.get(rq.SPECTRA6["yellow"], 0) > 400             # the second track, the ring, the giant
        assert orbit.get(rq.SPECTRA6["red"], 0) > 60                 # the giant's bands and half its disc
        assert orbit.get(rq.SPECTRA6["white"], 0) > 150              # station names, planets, the ship marker
        lx0, ly0, lx1, ly1 = rq._EXPANSE_LIST_RECT
        rows = ink_counts(scene.crop((lx0 + 8, rq._EXPANSE_LIST_ROW_Y, lx1 - 8, rq._EXPANSE_LIST_ROW_Y + 4 * rq._EXPANSE_LIST_ROW_H)))
        assert rows.get(rq.SPECTRA6["blue"], 0) > 600                # four boxed rows and their leaders
        assert rows.get(rq.SPECTRA6["white"], 0) > 120               # silhouettes and names
        scatter = ink_counts(scene.crop(rq._EXPANSE_SCATTER_RECT))
        assert scatter.get(rq.SPECTRA6["white"], 0) > 10

    def test_quote_is_white_with_an_orange_phrase(self):
        counts = ink_counts(self._render().crop(rq._EXPANSE_QUOTE_RECT))
        assert counts.get(rq.SPECTRA6["white"], 0) > 2000
        assert counts.get(rq.SPECTRA6["red"], 0) > 150
        assert counts.get(rq.SPECTRA6["yellow"], 0) > 150

    def test_sender_is_the_author_in_orange(self):
        a = self._render()
        b = self._render(dict(self.ROW, author="Homer"))
        x0, _, x1, _ = rq._EXPANSE_FEED_RECT
        band = (x0 + 50, rq._EXPANSE_SENDER_Y, x1 - 20, rq._EXPANSE_SENDER_Y + 24)
        assert pixel_bytes(a.crop(band)) != pixel_bytes(b.crop(band))
        counts = ink_counts(a.crop(band))
        assert counts.get(rq.SPECTRA6["red"], 0) > 200
        assert counts.get(rq.SPECTRA6["yellow"], 0) > 200
        # No author: the book stands in for the sender.
        c = self._render(dict(self.ROW, author=""))
        assert ink_counts(c.crop(band)).get(rq.SPECTRA6["yellow"], 0) > 200

    def test_ships_state_is_dealt_from_the_quote(self):
        rows = [dict(self.ROW, source_id=str(n), line_number=n) for n in range(1, 120)]
        gauges = {rq._expanse_gauges(make_row(**row)) for row in rows}
        assert len(gauges) > 100
        assert all(0 <= g <= 12 for sweeps in gauges for g in sweeps)
        pills = {rq._expanse_pills(make_row(**row)) for row in rows}
        assert len(pills) > 100
        assert {ink for grid in pills for row in grid for ink in row} == {"green", "amber", "red", "dark"}
        assert {rq._expanse_signal(make_row(**row)) for row in rows} <= set(range(1, 9))
        assert rq._expanse_gauges(make_row(**self.ROW)) == rq._expanse_gauges(make_row(**self.ROW))
        assert rq._expanse_tx_id(make_row(**self.ROW)).startswith("TX-")
        foot = (rq._EXPANSE_FOOT_RECT[0] + 30, rq._EXPANSE_FOOT_RECT[1] + 6, rq._EXPANSE_FOOT_RECT[2] - 6, rq._EXPANSE_FOOT_RECT[3] - 4)
        a, b = self._render(rows[0]), self._render(rows[1])
        assert pixel_bytes(a.crop(foot)) != pixel_bytes(b.crop(foot))
        chart = ink_counts(a.crop(rq._EXPANSE_CHART_RECT))
        assert chart.get(rq.SPECTRA6["blue"], 0) > 500 and chart.get(rq.SPECTRA6["white"], 0) > 500   # the cyan area
        gx = rq._EXPANSE_ARC_GAUGE_XS[0]
        gy, r = rq._EXPANSE_ARC_GAUGE_Y, rq._EXPANSE_ARC_GAUGE_R
        dial = (gx - r - 1, gy - r - 1, gx + r + 2, gy + r + 2)
        assert pixel_bytes(a.crop(dial)) != pixel_bytes(self._render(rows[5]).crop(dial)) or \
            rq._expanse_gauges(make_row(**rows[0]))[0] == rq._expanse_gauges(make_row(**rows[5]))[0]

    def test_downscales_the_canonical_frame(self):
        small = self._render(size=(320, 192))
        big = self._render()
        assert small.size == (320, 192)
        assert pixel_bytes(small) == pixel_bytes(big.resize((320, 192), Image.Resampling.NEAREST))


class TestBeksinskiFrame:
    """``beksinski`` — a procession across a dead plain toward a cathedral
    of bone.

    The scene is cached once per process; the hour is the number of figures
    in the file; the quote sits in the haze and the byline on the plain.
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
        return rq.render(time_str, make_row(**(row or TestBeksinskiFrame.ROW)),
                         *size, mode="production", theme="beksinski")

    @staticmethod
    def _road_box():
        (nx, ny), (fx, fy) = rq._BEKSINSKI_ROAD
        return (nx - 40, fy - 70, fx + 40, ny + 12)

    def test_on_palette_with_no_green_and_no_blue(self):
        inks = distinct_inks(self._render())
        assert inks == {rq.SPECTRA6[k] for k in ("black", "red", "yellow", "white")}

    def test_every_minute_of_an_hour_renders_identically(self):
        first = pixel_bytes(self._render(time_str="09:00"))
        for minute in (5, 17, 30, 59):
            assert pixel_bytes(self._render(time_str=f"09:{minute:02d}")) == first

    def test_the_file_is_one_figure_per_hour(self):
        """Neutering the painter leaves the empty road; every hour adds black
        to it, and twelve hours is the same count as midnight."""
        box = self._road_box()
        road = self._render(time_str="12:00")
        empty = rq._beksinski_scene().crop(box)
        baseline = ink_counts(empty).get(rq.SPECTRA6["black"], 0)
        added = []
        for hour in range(1, 13):
            crop = self._render(time_str=f"{hour:02d}:00").crop(box)
            added.append(ink_counts(crop).get(rq.SPECTRA6["black"], 0) - baseline)
        assert added[0] > 60                                   # one walker at one
        assert all(b > a for a, b in pairwise(added))   # each hour adds a figure
        assert pixel_bytes(self._render(time_str="00:00")) == pixel_bytes(road)

    def test_the_leader_stands_at_the_cathedrals_foot_from_one_oclock(self):
        """The file grows backward along the road: the leader's pixels at one
        are the same at twelve."""
        (nx, ny), (fx, fy) = rq._BEKSINSKI_ROAD
        head = (fx - 24, fy - 40, fx + 24, fy + 6)
        one = self._render(time_str="01:00").crop(head)
        assert ink_counts(one).get(rq.SPECTRA6["black"], 0) > 60
        assert pixel_bytes(one) == pixel_bytes(self._render(time_str="12:00").crop(head))

    def test_scene_is_painted_once_per_process(self):
        assert rq._beksinski_scene() is rq._beksinski_scene()

    def test_haze_is_a_dithered_ochre_over_an_umber_plain(self):
        scene = rq._beksinski_scene()
        hz = rq._BEKSINSKI_HORIZON
        haze = ink_counts(scene.crop((40, 180, 460, hz - 10)))
        area = 420 * (hz - 190)
        assert haze.get(rq.SPECTRA6["white"], 0) > area * 0.3
        assert haze.get(rq.SPECTRA6["yellow"], 0) > area * 0.15
        assert haze.get(rq.SPECTRA6["black"], 0) < area * 0.2
        plain = ink_counts(scene.crop((40, hz + 40, 460, 436)))
        area = 420 * (436 - hz - 40)
        assert plain.get(rq.SPECTRA6["black"], 0) > area * 0.45
        assert plain.get(rq.SPECTRA6["red"], 0) > area * 0.1
        assert plain.get(rq.SPECTRA6["white"], 0) < area * 0.1

    def test_cathedral_is_bone_with_a_rust_rim_and_windows_of_haze(self):
        scene = rq._beksinski_scene()
        mask = rq._beksinski_tower_mask(scene.size)
        x0, x1 = rq._BEKSINSKI_TOWER
        hz = rq._BEKSINSKI_HORIZON
        bbox = mask.getbbox()
        assert bbox[0] < x0 - 20 and bbox[2] > x1 + 20 and bbox[1] < 60   # buttresses and spires
        bone = ink_counts(Image.composite(scene, Image.new("RGB", scene.size, rq.SPECTRA6["blue"]), mask))
        inside = sum(bone.values()) - bone.get(rq.SPECTRA6["blue"], 0)
        assert bone.get(rq.SPECTRA6["black"], 0) > inside * 0.5
        assert bone.get(rq.SPECTRA6["red"], 0) > inside * 0.08             # the rim light
        # The windows: light inside the footprint, above the horizon, off the mask.
        holes = Image.new("L", scene.size, 0)
        ImageDraw.Draw(holes).rectangle((x0 + 20, hz - 120, x1 - 20, hz - 10), fill=255)
        holes = ImageChops.subtract(holes, mask)
        through = ink_counts(Image.composite(scene, Image.new("RGB", scene.size, rq.SPECTRA6["blue"]), holes))
        assert through.get(rq.SPECTRA6["white"], 0) + through.get(rq.SPECTRA6["yellow"], 0) > 400

    def test_figures_carry_a_bone_white_edge(self):
        """White pixels the figures add — their lit edge — net of the road's
        own white they cover (a figure hides more than its line adds)."""
        box = self._road_box()
        white = rq.SPECTRA6["white"]
        empty = rq._beksinski_scene().crop(box)
        full = self._render(time_str="12:00").crop(box)
        ep, fp = empty.load(), full.load()
        new_white = sum(1 for y in range(empty.size[1]) for x in range(empty.size[0])
                        if fp[x, y] == white and ep[x, y] != white)
        assert new_white > 12 * 8

    def test_quote_is_black_in_the_haze_with_a_red_phrase(self):
        counts = ink_counts(self._render().crop(rq._BEKSINSKI_QUOTE_RECT))
        assert counts.get(rq.SPECTRA6["black"], 0) > 2500
        assert counts.get(rq.SPECTRA6["red"], 0) > 300
        # The haze under the text is still mostly light.
        assert counts.get(rq.SPECTRA6["white"], 0) > counts.get(rq.SPECTRA6["black"], 0)

    def test_byline_is_bone_white_on_the_plain(self):
        bx, by = rq._BEKSINSKI_BYLINE_XY
        foot = (bx, by, bx + rq._BEKSINSKI_BYLINE_WIDTH, by + 22)
        a = self._render()
        b = self._render(dict(self.ROW, author="Homer"))
        assert pixel_bytes(a.crop(foot)) != pixel_bytes(b.crop(foot))
        assert ink_counts(a.crop(foot)).get(rq.SPECTRA6["white"], 0) > 300
        # Nothing: the foot is the bare plain.
        c = self._render(dict(self.ROW, author="", title="", source_id="", source_path=""))
        assert pixel_bytes(c.crop(foot)) == pixel_bytes(rq._beksinski_scene().crop(foot))

    def test_downscales_the_canonical_frame(self):
        small = self._render(size=(320, 192))
        big = self._render()
        assert small.size == (320, 192)
        assert pixel_bytes(small) == pixel_bytes(big.resize((320, 192), Image.Resampling.NEAREST))


class TestGoyaFrame:
    """``goya`` — Goya's *Pinturas negras*: *El Perro*, the quote written into
    the ochre void and the dog looking up at the time.

    The void, slope and craze are cached once per process; the dog's pitch is
    taken from the matched phrase's position; the label is the Prado's.
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
    DOG_BOX = (150, 180, 380, 372)
    NO_BLUE_GREEN = {rq.SPECTRA6["black"], rq.SPECTRA6["red"], rq.SPECTRA6["yellow"], rq.SPECTRA6["white"]}

    @staticmethod
    def _render(row=None, time_str="14:30", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or TestGoyaFrame.ROW)),
                         *size, mode="production", theme="goya")

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert "goya" in rq.THEMES
        assert "goya" in rq.THEME_ORDER
        assert "goya" not in rq.CYCLE_EXCLUDED_THEMES
        assert display_inky.THEME_SATURATION["goya"] == 0.7
        assert rq.theme_font_candidates("goya", "quote_regular")[0] == (rq.LIBREBASKERVILLE_VARIABLE, "Regular")
        assert rq.theme_font_candidates("goya", "quote_bold")[0] == (rq.LIBREBASKERVILLE_VARIABLE, "Bold")
        for path in (rq.LIBREBASKERVILLE_VARIABLE, rq.LIBREBASKERVILLE_ITALIC_VARIABLE):
            assert pathlib.Path(path).exists(), path
        assert (pathlib.Path(rq.LIBREBASKERVILLE_VARIABLE).parent / "OFL.txt").exists()

    def test_bold_instance_is_pinned_off_the_axis_default(self):
        """The roman's default instance is Regular; the Bold the matched
        phrase is set in must be a different drawing."""
        from PIL import ImageFont
        pinned = rq.load_font([(rq.LIBREBASKERVILLE_VARIABLE, "Bold")], size=40)
        bare = ImageFont.truetype(rq.LIBREBASKERVILLE_VARIABLE, 40)
        glyph = "Hamburgefonts"

        def ink(font):
            img = Image.new("L", (400, 60), 0)
            ImageDraw.Draw(img).text((0, 0), glyph, font=font, fill=255)
            return sum(img.point(lambda v: 1 if v > 127 else 0).histogram()[1:])

        assert ink(pinned) > ink(bare)

    def test_a_painting_carries_no_clock(self):
        first = pixel_bytes(self._render(time_str="14:30"))
        for time_str in ("00:00", "03:05", "09:59", "23:45", "bogus"):
            assert pixel_bytes(self._render(time_str=time_str)) == first

    def test_on_palette_deterministic_and_earth_only(self):
        """Goya's earths in four inks: never blue, never green."""
        image = self._render()
        assert distinct_inks(image) == self.NO_BLUE_GREEN
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_scene_is_painted_once_per_process(self):
        assert rq._goya_scene() is rq._goya_scene()

    def test_void_is_a_dithered_ochre_over_a_black_slope(self):
        scene = rq._goya_scene()
        void = ink_counts(scene.crop((0, 120, 800, 300)))
        area = 800 * 180
        assert void.get(rq.SPECTRA6["yellow"], 0) > area * 0.3
        assert void.get(rq.SPECTRA6["black"], 0) > area * 0.12
        assert void.get(rq.SPECTRA6["red"], 0) > area * 0.03
        assert void.get(rq.SPECTRA6["white"], 0) > area * 0.03
        assert set(void) <= self.NO_BLUE_GREEN
        # The slope is a warm black: mostly black ink with a red-and-yellow
        # fleck that makes it umber rather than ink, never a flat fill.
        slope = ink_counts(scene.crop((600, 410, 800, 480)))
        assert slope.get(rq.SPECTRA6["black"], 0) > 200 * 70 * 0.75
        assert slope.get(rq.SPECTRA6["red"], 0) > 200 * 70 * 0.05
        # The slope rises to the right: black at the top of the slope's
        # left end, and black already at a row on the right that is still
        # void on the left.
        left = ink_counts(scene.crop((0, 392, 120, 480)))
        right = ink_counts(scene.crop((680, 330, 800, 350)))
        assert left.get(rq.SPECTRA6["black"], 0) > 120 * 88 * 0.75
        assert right.get(rq.SPECTRA6["black"], 0) > 120 * 20 * 0.6
        assert ink_counts(scene.crop((0, 330, 120, 350))).get(rq.SPECTRA6["black"], 0) < 120 * 20 * 0.5

    def test_craze_is_part_of_the_cached_scene(self):
        """The net goes on the cached scene, so the quote is never cracked
        through: the cache key names ``paint_craquelure``."""
        rq._goya_scene()
        assert rq.paint_craquelure in rq._GOYA_SCENE["frame"][0]

    def test_gaze_follows_the_matched_phrase(self):
        def placed(x, y, bold=True):
            return [(x, y, "two", None, bold, 40, 40)]
        px, py = rq._GOYA_DOG_PIVOT
        high = rq._goya_gaze(placed(px + 300, 60))
        low = rq._goya_gaze(placed(px + 300, 260))
        assert rq._GOYA_GAZE_MIN <= low < high <= rq._GOYA_GAZE_MAX
        assert rq._goya_gaze(placed(px + 500, py)) == rq._GOYA_GAZE_MIN          # level: clamped up
        assert rq._goya_gaze(placed(px - 100, 60)) == rq._GOYA_GAZE_MAX          # behind: the full lift
        assert rq._goya_gaze(placed(px + 300, 60, bold=False)) == rq._GOYA_GAZE_DEFAULT
        assert rq._goya_gaze([]) == rq._GOYA_GAZE_DEFAULT

    def test_dog_turns_with_the_quote(self):
        """Two quotes whose phrases land in different places get two dogs;
        the void around the dog is the same scene."""
        early = dict(self.ROW, display_quote="Half past two, and the long afternoon slipped quietly away from "
                                             "them all while the clock went on striking in the hall below.")
        late = dict(self.ROW, display_quote="The long afternoon slipped quietly away from them all while the "
                                            "clock went on striking in the hall below, until half past two.")
        a, b = self._render(early), self._render(late)
        assert pixel_bytes(a.crop(self.DOG_BOX)) != pixel_bytes(b.crop(self.DOG_BOX))
        assert pixel_bytes(a.crop((420, 300, 800, 370))) == pixel_bytes(b.crop((420, 300, 800, 370)))

    def test_dog_has_an_eye_and_stands_above_the_slope(self):
        image = self._render()
        dog = ink_counts(image.crop(self.DOG_BOX))
        assert dog.get(rq.SPECTRA6["white"], 0) > 0                # the catchlight
        assert dog.get(rq.SPECTRA6["red"], 0) > 300                # umber is a red-flecked stipple
        assert dog.get(rq.SPECTRA6["black"], 0) > 2000
        # Without the dog the same box is the void over the slope's edge.
        scene = ink_counts(rq._goya_scene().crop(self.DOG_BOX))
        assert dog.get(rq.SPECTRA6["yellow"], 0) < scene.get(rq.SPECTRA6["yellow"], 0)

    def test_quote_is_black_with_a_red_phrase(self):
        counts = ink_counts(self._render().crop(rq._GOYA_QUOTE_RECT))
        assert counts.get(rq.SPECTRA6["black"], 0) > 3000
        assert counts.get(rq.SPECTRA6["red"], 0) > 400
        plain = dict(self.ROW, matched_text="")
        scene = ink_counts(rq._goya_scene().crop(rq._GOYA_QUOTE_RECT))
        assert ink_counts(self._render(plain).crop(rq._GOYA_QUOTE_RECT)).get(rq.SPECTRA6["red"], 0) \
            <= scene.get(rq.SPECTRA6["red"], 0)

    def test_label_is_the_prados(self):
        a = self._render()
        box = rq._GOYA_LABEL_RECT
        counts = ink_counts(a.crop(box))
        area = (box[2] - box[0]) * (box[3] - box[1])
        assert counts.get(rq.SPECTRA6["white"], 0) > area * 0.6
        assert counts.get(rq.SPECTRA6["black"], 0) > 800
        assert set(counts) == {rq.SPECTRA6["white"], rq.SPECTRA6["black"]}
        b = self._render(dict(self.ROW, author="Homer", title="The Odyssey", source_id="1727"))
        assert pixel_bytes(a.crop(box)) != pixel_bytes(b.crop(box))
        c = self._render(dict(self.ROW, author="", title=""))
        assert ink_counts(c.crop(box)).get(rq.SPECTRA6["black"], 0) > 400    # Anónimo and the medium lines

    def test_inventory_number_is_the_prados_form(self):
        assert rq._goya_inventory({"source_id": "141"}) == "P000141"
        assert rq._goya_inventory({"source_id": 1727}) == "P001727"
        assert rq._goya_inventory({"source_id": "pg2701"}) == "P002701"
        assert rq._goya_inventory({"source_id": "12345678"}) == "P345678"
        assert rq._goya_inventory({}) == "P000767"                # El Perro's own number
        assert rq._goya_inventory({"source_id": "local"}) == "P000767"

    def test_downscales_the_canonical_frame(self):
        small = self._render(size=(320, 192))
        big = self._render()
        assert small.size == (320, 192)
        assert pixel_bytes(small) == pixel_bytes(big.resize((320, 192), Image.Resampling.NEAREST))


class TestHalFrame:
    """``hal`` — *2001: A Space Odyssey*: the Discovery's main monitor with
    the hour's subsystem up, HAL's eye beside it.

    Solid flats only (the one stipple is the two blooms), the hour is which
    mnemonic is on the header and which foot tile is white, and nothing
    reads the wall clock.
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
        return rq.render(time_str, make_row(**(row or TestHalFrame.ROW)),
                         *size, mode="production", theme="hal")

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert "hal" in rq.THEMES
        assert "hal" in rq.THEME_ORDER
        assert "hal" not in rq.CYCLE_EXCLUDED_THEMES
        assert display_inky.THEME_SATURATION["hal"] == 0.7
        assert rq.theme_font_candidates("hal", "quote_regular")[0] == (rq.JOST_VARIABLE, "Regular")
        assert rq.theme_font_candidates("hal", "quote_bold")[0] == (rq.JOST_VARIABLE, "Bold")
        assert rq.theme_font_candidates("hal", "ornament")[0] == rq.MICHROMA_REGULAR
        for path in (rq.JOST_VARIABLE, rq.MICHROMA_REGULAR):
            assert pathlib.Path(path).exists(), path
            assert (pathlib.Path(path).parent / "OFL.txt").exists()

    def test_one_mnemonic_per_hour(self):
        assert len(rq._HAL_MNEMONICS) == 12 and len(set(rq._HAL_MNEMONICS)) == 12
        assert rq._hal_mnemonic(1) == "COM" and rq._hal_mnemonic(12) == "NUC"

    def test_on_palette_and_deterministic(self):
        image = self._render()
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_monitor_is_a_blue_flat_under_scanlines_with_white_type(self):
        image = self._render()
        counts = ink_counts(image.crop(rq._HAL_MONITOR_RECT))
        area = (rq._HAL_MONITOR_RECT[2] - rq._HAL_MONITOR_RECT[0]) * (rq._HAL_MONITOR_RECT[3] - rq._HAL_MONITOR_RECT[1])
        assert counts.get(rq.SPECTRA6["blue"], 0) > area * 0.55
        assert counts.get(rq.SPECTRA6["white"], 0) > 3000
        assert counts.get(rq.SPECTRA6["yellow"], 0) > 300           # the matched phrase
        assert rq.SPECTRA6["red"] not in counts and rq.SPECTRA6["green"] not in counts
        # The raster: one row in four is black where the field was blue, and
        # the rows between are untouched, in an empty patch of the screen.
        x0, y0 = rq._HAL_MONITOR_RECT[0] + 300, rq._HAL_MONITOR_RECT[1] + 240
        patch = image.crop((x0, y0 - (y0 - rq._HAL_MONITOR_RECT[1]) % rq._HAL_SCANLINE_PERIOD, x0 + 40, y0 + 40))
        rows = [ink_counts(patch.crop((0, r, 40, r + 1))) for r in range(rq._HAL_SCANLINE_PERIOD)]
        assert rows[0] == {rq.SPECTRA6["black"]: 40}
        assert all(row == {rq.SPECTRA6["blue"]: 40} for row in rows[1:])
        # The type is never cut by the raster: the phrase's yellow count is the
        # same with and without the scanline pass.
        assert counts.get(rq.SPECTRA6["yellow"], 0) == ink_counts(
            self._render().crop(rq._HAL_MONITOR_RECT)).get(rq.SPECTRA6["yellow"], 0)

    def test_screen_light_leaks_onto_the_housing(self):
        """Blue in the black band between the glass and the housing hairline."""
        image = self._render()
        band = image.crop((rq._HAL_MONITOR_RECT[0] + 60, rq._HAL_HOUSING_RECT[1] + 1,
                           rq._HAL_MONITOR_RECT[2] - 60, rq._HAL_MONITOR_RECT[1]))
        counts = ink_counts(band)
        assert 0 < counts.get(rq.SPECTRA6["blue"], 0) < band.size[0] * band.size[1] * 0.6
        assert counts.get(rq.SPECTRA6["black"], 0) > 0

    def test_ship_is_drawn_in_wireframe(self):
        counts = ink_counts(self._render().crop(rq._HAL_SHIP_RECT))
        area = (rq._HAL_SHIP_RECT[2] - rq._HAL_SHIP_RECT[0]) * (rq._HAL_SHIP_RECT[3] - rq._HAL_SHIP_RECT[1])
        assert counts.get(rq.SPECTRA6["black"], 0) > area * 0.8
        assert 300 < counts.get(rq.SPECTRA6["white"], 0) < area * 0.2

    def test_hour_is_which_tile_is_white(self):
        tiles = rq._hal_tile_rects()
        assert len(tiles) == 12
        for hour in (1, 7, 12):
            image = self._render(time_str=f"{hour:02d}:20")
            for i, rect in enumerate(tiles):
                counts = ink_counts(image.crop(rect))
                area = (rect[2] - rect[0]) * (rect[3] - rect[1])
                white = counts.get(rq.SPECTRA6["white"], 0)
                if i + 1 == hour:
                    assert white > area * 0.6, (hour, i)
                else:
                    assert white < area * 0.25, (hour, i)          # the label and bars only
                    assert counts.get(rq.SPECTRA6[rq._HAL_TILE_INKS[i % 4]], 0) > area * 0.6

    def test_tiles_are_pinned_across_the_minutes_of_an_hour(self):
        a = self._render(time_str="09:00")
        for time_str in ("09:05", "09:33", "09:59", "21:17"):
            assert pixel_bytes(self._render(time_str=time_str)) == pixel_bytes(a)
        assert pixel_bytes(self._render(time_str="10:00")) != pixel_bytes(a)

    def test_header_names_the_hours_subsystem(self):
        """The header mnemonic changes with the hour; the quote does not."""
        a, b = self._render(time_str="03:30"), self._render(time_str="04:30")
        header = (rq._HAL_MONITOR_RECT[0], rq._HAL_MONITOR_RECT[1], 300, rq._HAL_HEADER_RULE_Y)
        assert pixel_bytes(a.crop(header)) != pixel_bytes(b.crop(header))
        assert pixel_bytes(a.crop(rq._HAL_QUOTE_RECT)) == pixel_bytes(b.crop(rq._HAL_QUOTE_RECT))

    def test_eye_is_red_in_a_white_bezel_with_a_yellow_core(self):
        cx, cy = rq._HAL_EYE_CENTRE
        r = rq._HAL_EYE_RADIUS
        image = self._render()
        iris = ink_counts(image.crop((cx - r, cy - r, cx + r, cy + r)))
        assert iris.get(rq.SPECTRA6["red"], 0) > (2 * r) ** 2 * 0.45
        assert iris.get(rq.SPECTRA6["yellow"], 0) > 200
        assert iris.get(rq.SPECTRA6["white"], 0) > 40                 # the catchlight
        # The bloom: red spilled into the black around the bezel, sparse.
        ring = ink_counts(image.crop((cx - r - 24, cy - r - 24, cx + r + 24, cy - r - 10)))
        assert 0 < ring.get(rq.SPECTRA6["red"], 0) < 28 * 14 * 0.6

    def test_readouts_are_seeded_from_the_quote(self):
        a = self._render()
        b = self._render(dict(self.ROW, source_id="1727", line_number=9))
        assert pixel_bytes(a.crop(rq._HAL_TRACE_RECT)) != pixel_bytes(b.crop(rq._HAL_TRACE_RECT))
        assert pixel_bytes(a.crop(rq._HAL_PLATE_RECT)) == pixel_bytes(b.crop(rq._HAL_PLATE_RECT))

    def test_byline_is_tracked_capitals(self):
        a = self._render()
        band = (rq._HAL_QUOTE_RECT[0], rq._HAL_BYLINE_Y, rq._HAL_QUOTE_RECT[2], rq._HAL_BYLINE_Y + 18)
        assert ink_counts(a.crop(band)).get(rq.SPECTRA6["white"], 0) > 300
        c = self._render(dict(self.ROW, author="", title="", source_id="", source_path=""))
        assert ink_counts(c.crop(band)).get(rq.SPECTRA6["white"], 0) == 0

    def test_downscales_the_canonical_frame(self):
        small = self._render(size=(320, 192))
        big = self._render()
        assert small.size == (320, 192)
        assert pixel_bytes(small) == pixel_bytes(big.resize((320, 192), Image.Resampling.NEAREST))


class TestLumonFrame:
    """``lumon`` — *Severance*: the Macrodata Refinement terminal.

    The vignetted blue CRT is cached once per process; the hour is the file's
    completion and the scary cluster's column; the matched phrase sits in
    the refiner's hover box.
    """

    ROW = TestHalFrame.ROW

    @staticmethod
    def _render(row=None, time_str="14:30", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or TestLumonFrame.ROW)),
                         *size, mode="production", theme="lumon")

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert "lumon" in rq.THEMES
        assert "lumon" in rq.THEME_ORDER
        assert "lumon" not in rq.CYCLE_EXCLUDED_THEMES
        assert display_inky.THEME_SATURATION["lumon"] == 0.7
        assert rq.theme_font_candidates("lumon", "quote_regular")[0] == (rq.MONTSERRAT_VARIABLE, "Regular")
        assert rq.theme_font_candidates("lumon", "quote_bold")[0] == (rq.MONTSERRAT_VARIABLE, "Bold")
        assert rq.theme_font_candidates("lumon", "ornament")[0] == (rq.INTER_VARIABLE, "Medium")
        for path in (rq.MONTSERRAT_VARIABLE, rq.INTER_VARIABLE, rq.MICHROMA_REGULAR):
            assert pathlib.Path(path).exists(), path
            assert (pathlib.Path(path).parent / "OFL.txt").exists()

    def test_completion_is_the_hour_over_twelve(self):
        assert rq._lumon_completion(1) == 8
        assert rq._lumon_completion(6) == 50
        assert rq._lumon_completion(12) == 100

    def test_cluster_walks_the_hours_column_pair(self):
        assert rq._lumon_cluster(1) == (1, 0)
        assert rq._lumon_cluster(12) == (1, 22)
        cols = {rq._lumon_cluster(h)[1] for h in range(1, 13)}
        assert len(cols) == 12 and max(cols) + 1 < rq._LUMON_GRID_COLS

    def test_on_palette_deterministic_and_cached(self):
        image = self._render()
        assert distinct_inks(image) == {rq.SPECTRA6[k] for k in ("blue", "black", "white", "yellow")}
        assert pixel_bytes(image) == pixel_bytes(self._render())
        assert rq._lumon_scene() is rq._lumon_scene()

    def test_screen_is_blue_at_the_centre_and_darker_at_the_corners(self):
        scene = rq._lumon_scene()
        centre = ink_counts(scene.crop((300, 200, 500, 280)))
        assert centre.get(rq.SPECTRA6["blue"], 0) > 200 * 80 * 0.95
        corner = ink_counts(scene.crop((20, 20, 120, 80)))
        assert corner.get(rq.SPECTRA6["black"], 0) > 100 * 60 * 0.3
        assert corner.get(rq.SPECTRA6["blue"], 0) > 100 * 60 * 0.2
        # The housing outside the glass is the terminal's beige: a white
        # stipple with a yellow quarter, and nothing else.
        housing = ink_counts(scene.crop((0, 0, 8, 480)))
        assert set(housing) == {rq.SPECTRA6["white"], rq.SPECTRA6["yellow"]}
        assert housing[rq.SPECTRA6["yellow"]] == 8 * 480 // 4
        # Inside it, the recessed edge is black with the screen's light leaking on.
        gap = ink_counts(scene.crop((200, rq._LUMON_HOUSING + 1, 600, rq._LUMON_BEZEL)))
        assert gap.get(rq.SPECTRA6["black"], 0) > 0 and gap.get(rq.SPECTRA6["blue"], 0) > 0
        assert set(ink_counts(scene)) == {rq.SPECTRA6["blue"], rq.SPECTRA6["black"],
                                          rq.SPECTRA6["white"], rq.SPECTRA6["yellow"]}

    def test_scanlines_cross_the_screen_but_not_the_type(self):
        image = self._render()
        b = rq._LUMON_BEZEL
        # In the centre, where the field is pure blue, one row in four is black.
        y = b + ((300 - b) // rq._LUMON_SCANLINE_PERIOD) * rq._LUMON_SCANLINE_PERIOD
        assert ink_counts(image.crop((300, y, 340, y + 1))) == {rq.SPECTRA6["black"]: 40}
        assert ink_counts(image.crop((300, y + 1, 340, y + 2))) == {rq.SPECTRA6["blue"]: 40}
        # The phrase's yellow is untouched by the raster.
        draw = ImageDraw.Draw(Image.new("RGB", (800, 480)))
        placed = rq._lumon_layout(draw, make_row(**self.ROW))
        bold = [p for p in placed if p[4] and p[2].strip()]
        x0, y0 = bold[0][0], bold[0][1]
        chunk = image.crop((x0, y0, x0 + bold[0][5], y0 + bold[0][6]))
        assert ink_counts(chunk).get(rq.SPECTRA6["yellow"], 0) > 100

    def test_hour_moves_the_cluster_and_the_completion_only(self):
        a, b = self._render(time_str="03:30"), self._render(time_str="04:30")
        assert pixel_bytes(a.crop(rq._LUMON_GRID_RECT)) != pixel_bytes(b.crop(rq._LUMON_GRID_RECT))
        header_right = (500, rq._LUMON_HEADER_Y, 760, rq._LUMON_RULE_Y)
        assert pixel_bytes(a.crop(header_right)) != pixel_bytes(b.crop(header_right))
        assert pixel_bytes(a.crop(rq._LUMON_QUOTE_RECT)) == pixel_bytes(b.crop(rq._LUMON_QUOTE_RECT))
        assert pixel_bytes(a.crop(rq._LUMON_BINS_RECT)) == pixel_bytes(b.crop(rq._LUMON_BINS_RECT))
        for time_str in ("03:00", "03:59", "15:12"):
            assert pixel_bytes(self._render(time_str=time_str)) == pixel_bytes(a)

    def test_cluster_box_sits_in_the_hours_columns(self):
        cells = rq._lumon_grid_cells()
        for hour in (1, 5, 12):
            image = self._render(time_str=f"{hour:02d}:10")
            row0, col0 = rq._lumon_cluster(hour)
            x0, y0 = cells[row0][col0][:2]
            x1, y1 = cells[row0 + 1][col0 + 1][2:]
            box = image.crop((round(x0) - 4, round(y0) - 4, round(x1) + 4, round(y1) + 4))
            edge = ink_counts(box.crop((0, 0, box.size[0], 2)))
            assert edge.get(rq.SPECTRA6["white"], 0) > box.size[0] * 0.8, hour

    def test_phrase_is_yellow_in_one_hover_box(self):
        image = self._render()
        counts = ink_counts(image.crop(rq._LUMON_QUOTE_RECT))
        assert counts.get(rq.SPECTRA6["yellow"], 0) > 300
        assert counts.get(rq.SPECTRA6["white"], 0) > 3000
        draw = ImageDraw.Draw(Image.new("RGB", (800, 480)))
        placed = rq._lumon_layout(draw, make_row(**self.ROW))
        assert len(rq._lumon_hover_boxes(draw, placed)) == 1
        plain = dict(self.ROW, matched_text="")
        assert rq.SPECTRA6["yellow"] not in ink_counts(self._render(plain).crop(rq._LUMON_QUOTE_RECT))

    def test_hover_box_spans_a_phrase_broken_across_lines(self):
        draw = ImageDraw.Draw(Image.new("RGB", (800, 480)))
        font = rq.load_font([(rq.MONTSERRAT_VARIABLE, "Bold")], size=20)
        placed = [(50, 100, "half", font, True, 40, 26), (90, 100, " ", font, True, 10, 26),
                  (100, 100, "past", font, True, 40, 26), (50, 126, "two", font, True, 30, 26)]
        boxes = rq._lumon_hover_boxes(draw, placed)
        assert len(boxes) == 2
        assert boxes[0][0] < 50 and boxes[0][2] > 139 and boxes[1][1] == 124

    def test_file_name_and_bins_are_seeded_from_the_quote(self):
        a = self._render()
        b = self._render(dict(self.ROW, source_id="1727", line_number=9))
        assert rq._lumon_file_name(make_row(**self.ROW)) in rq._LUMON_FILES
        assert pixel_bytes(a.crop(rq._LUMON_BINS_RECT)) != pixel_bytes(b.crop(rq._LUMON_BINS_RECT))
        bins = ink_counts(a.crop(rq._LUMON_BINS_RECT))
        assert bins.get(rq.SPECTRA6["white"], 0) > 2000

    def test_downscales_the_canonical_frame(self):
        small = self._render(size=(320, 192))
        big = self._render()
        assert small.size == (320, 192)
        assert pixel_bytes(small) == pixel_bytes(big.resize((320, 192), Image.Resampling.NEAREST))


class _CustomFrameCase:
    """Shared checks for the four hour-pinned frames added together."""

    THEME = ""
    SATURATION = 0.7
    ROW = TestHalFrame.ROW

    @classmethod
    def _render(cls, row=None, time_str="14:30", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or cls.ROW)), *size, mode="production", theme=cls.THEME)

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert self.THEME in rq.THEMES and self.THEME in rq.THEME_ORDER
        assert self.THEME not in rq.CYCLE_EXCLUDED_THEMES
        assert display_inky.THEME_SATURATION[self.THEME] == self.SATURATION
        for role in ("quote_regular", "quote_bold", "ornament"):
            first = rq.theme_font_candidates(self.THEME, role)[0]
            path = first[0] if isinstance(first, tuple) else first
            assert pathlib.Path(path).exists(), path
            licence = pathlib.Path(path).parent
            assert (licence / "OFL.txt").exists() or (licence / "LICENSE.txt").exists()

    def test_on_palette_and_deterministic(self):
        image = self._render()
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_pinned_across_the_minutes_of_an_hour(self):
        a = self._render(time_str="09:00")
        for time_str in ("09:05", "09:33", "09:59", "21:17"):
            assert pixel_bytes(self._render(time_str=time_str)) == pixel_bytes(a)
        assert pixel_bytes(self._render(time_str="10:00")) != pixel_bytes(a)
        assert pixel_bytes(self._render(time_str="bogus")) == pixel_bytes(self._render(time_str="00:00"))

    def test_downscales_the_canonical_frame(self):
        small = self._render(size=(320, 192))
        assert small.size == (320, 192)
        assert pixel_bytes(small) == pixel_bytes(self._render().resize((320, 192), Image.Resampling.NEAREST))


class TestDskyFrame(_CustomFrameCase):
    """``dsky`` — the Apollo DSKY on its console: the modelled unit dithered
    to the inks, the hour in PROG, the quote typed on the flight-plan card."""

    THEME = "dsky"

    def test_segment_encodings(self):
        assert rq._dsky_segments("8") == "abcdefg"
        assert rq._dsky_segments("1") == "bc"
        assert rq._dsky_segments("0") == "abcdef"
        assert rq._dsky_segments("+") == "g|" and rq._dsky_segments("-") == "g"
        assert rq._dsky_segments("x") == ""
        assert all(len(rq._dsky_segments(d)) >= 2 for d in "0123456789")

    def test_registers_are_signed_five_digit_and_seeded(self):
        regs = rq._dsky_registers(make_row(**self.ROW))
        assert len(regs) == 3
        assert all(r[0] in "+-" and len(r) == 6 and r[1:].isdigit() for r in regs)
        assert regs != rq._dsky_registers(make_row(**dict(self.ROW, source_id="1727", line_number=9)))

    def test_console_is_dithered_grey_and_cached(self):
        scene = rq._dsky_scene()
        assert scene is rq._dsky_scene()
        panel = ink_counts(scene.crop((460, 100, 474, 400)))
        area = 14 * 300
        assert 0.3 * area < panel.get(rq.SPECTRA6["black"], 0) < 0.75 * area
        # The unit's shadow falls on the panel below and right of it.
        below = ink_counts(scene.crop((500, 466, 780, 476))).get(rq.SPECTRA6["black"], 0) / (280 * 10)
        clear = ink_counts(scene.crop((460, 2, 780, 12))).get(rq.SPECTRA6["black"], 0) / (320 * 10)
        assert below > clear

    def test_card_is_cream_paper_with_a_clip(self):
        image = self._render()
        x0, y0, x1, y1 = rq._DSKY_CARD_RECT
        paper = ink_counts(image.crop((x0 + 20, y1 - 40, x1 - 20, y1 - 10)))
        assert set(paper) <= {rq.SPECTRA6["white"], rq.SPECTRA6["yellow"], rq.SPECTRA6["black"]}
        assert abs(paper[rq.SPECTRA6["yellow"]] / sum(paper.values()) - 0.25) < 0.02
        cx = (x0 + x1) // 2
        clip = ink_counts(image.crop((cx - 30, y0 - 8, cx + 30, y0 + 12)))
        assert clip.get(rq.SPECTRA6["black"], 0) > 600

    def test_quote_is_typed_black_with_a_red_phrase(self):
        assert rq.theme_font_candidates("dsky", "quote_regular")[0] == rq.SPECIALELITE_REGULAR
        counts = ink_counts(self._render().crop(rq._DSKY_QUOTE_RECT))
        assert counts.get(rq.SPECTRA6["black"], 0) > 2000
        assert counts.get(rq.SPECTRA6["red"], 0) > 300

    def test_display_glows_white_in_green_on_dark_glass(self):
        image = self._render()
        counts = ink_counts(image.crop(rq._DSKY_DISPLAY_RECT))
        assert counts.get(rq.SPECTRA6["white"], 0) > 1200       # the segments
        assert counts.get(rq.SPECTRA6["green"], 0) > 1500       # the bloom and COMP ACTY
        assert counts.get(rq.SPECTRA6["black"], 0) > 8000
        assert rq.SPECTRA6["yellow"] not in counts and rq.SPECTRA6["red"] not in counts

    def test_prog_register_is_the_hour(self):
        x0, y0, x1, _ = rq._DSKY_DISPLAY_RECT
        prog = (x1 - 8 - 2 * 16 - 4, y0 + 18, x1 - 4, y0 + 44)
        a, b = self._render(time_str="02:30"), self._render(time_str="11:30")
        assert pixel_bytes(a.crop(prog)) != pixel_bytes(b.crop(prog))
        verb = (x0 + 4, y0 + 50, x0 + 44, y0 + 88)
        assert pixel_bytes(a.crop(verb)) == pixel_bytes(b.crop(verb))

    def test_keys_are_modelled_domes_with_legends(self):
        image = self._render()
        kx0, ky0, kx1, ky1, label = rq._dsky_key_rects()[2]        # "7"
        assert label == "7"
        cap = ink_counts(image.crop((kx0, ky0, kx1 + 1, ky1 + 1)))
        assert cap.get(rq.SPECTRA6["white"], 0) > 60                # the lit edge and the legend
        assert cap.get(rq.SPECTRA6["black"], 0) > (rq._DSKY_KEY ** 2) * 0.6
        # The tray between the keys is a lighter grey than the caps.
        gap = ink_counts(image.crop((kx1 + 1, ky0 + 6, kx1 + rq._DSKY_KEY_GAP, ky1 - 6)))
        assert gap.get(rq.SPECTRA6["white"], 0) / max(1, sum(gap.values())) > 0.25
        # The lit edge: the cap's upper-left corner is whiter than its lower-right.
        ul = ink_counts(image.crop((kx0 + 1, ky0 + 1, kx0 + 9, ky0 + 9))).get(rq.SPECTRA6["white"], 0)
        lr = ink_counts(image.crop((kx1 - 9, ky1 - 9, kx1 - 1, ky1 - 1))).get(rq.SPECTRA6["white"], 0)
        assert ul > lr
        assert len(rq._dsky_key_rects()) == 19 and len(rq._dsky_lamp_rects()) == 14


class TestOblivionFrame(_CustomFrameCase):
    """``oblivion`` — the Sky Tower's light table: dithered glass, a contour
    map with the rigs on it, a shaded drone, the hour's rig and bearing."""

    THEME = "oblivion"
    SATURATION = 0.5

    def test_quote_is_light_black_with_a_red_phrase_on_clean_white(self):
        assert rq.theme_font_candidates("oblivion", "quote_regular")[0] == (rq.EXO2_VARIABLE, "Light")
        counts = ink_counts(self._render().crop(rq._OBLIVION_QUOTE_RECT))
        assert counts.get(rq.SPECTRA6["black"], 0) > 2000
        assert counts.get(rq.SPECTRA6["red"], 0) > 300
        assert distinct_inks(self._render()) == {rq.SPECTRA6["white"], rq.SPECTRA6["black"], rq.SPECTRA6["red"]}
        # The pool: the glass under the quote is pure white in the scene.
        x0, y0, x1, y1 = rq._OBLIVION_QUOTE_RECT
        pool = ink_counts(rq._oblivion_scene().crop(rq._OBLIVION_QUOTE_RECT))
        assert pool.get(rq.SPECTRA6["black"], 0) < (x1 - x0) * (y1 - y0) * 0.03     # grain at the pool's edge only
        assert set(ink_counts(rq._oblivion_scene().crop((x0, y0, x0 + 200, y0 + 120)))) == {rq.SPECTRA6["white"]}

    def test_glass_is_dithered_tone_and_cached(self):
        scene = rq._oblivion_scene()
        assert scene is rq._oblivion_scene()
        edge = ink_counts(scene.crop((600, 20, 780, 40)))
        area = 180 * 20
        assert 0.02 * area < edge.get(rq.SPECTRA6["black"], 0) < 0.2 * area
        x0, y0, x1, y1 = rq._OBLIVION_MAP_RECT
        pane = ink_counts(scene.crop((x0 + 20, y1 - 60, x0 + 80, y1 - 20)))
        assert pane.get(rq.SPECTRA6["black"], 0) > edge.get(rq.SPECTRA6["black"], 0) * (60 * 40) / area

    def test_map_has_contours_but_the_dial_is_clear(self):
        contours = rq._oblivion_contours((800, 480))
        x0, y0, x1, y1 = rq._OBLIVION_MAP_RECT
        assert contours.crop((x0, y0, x1, y1)).getbbox() is not None
        assert contours.crop((0, 0, x0 - 1, 480)).getbbox() is None
        cx, cy = rq._OBLIVION_DIAL_CENTRE
        half = int(rq._OBLIVION_DIAL_RADII[1] / math.sqrt(2)) - 2      # a square inside the middle ring
        assert contours.crop((cx - half, cy - half, cx + half, cy + half)).getbbox() is None

    def test_drone_is_a_shaded_sphere_with_a_red_lens(self):
        image = self._render()
        cx, cy = rq._OBLIVION_DRONE_CENTRE
        r = rq._OBLIVION_DRONE_RADIUS
        hull = ink_counts(image.crop((cx - r, cy - r, cx + r, cy + r)))
        assert hull.get(rq.SPECTRA6["red"], 0) > 150
        assert hull.get(rq.SPECTRA6["white"], 0) > (2 * r) ** 2 * 0.4
        # Lit upper-left quadrant is whiter than the lower-right terminator.
        ul = ink_counts(image.crop((cx - r + 4, cy - r + 4, cx - 12, cy - 12))).get(rq.SPECTRA6["black"], 0)
        lr = ink_counts(image.crop((cx + 12, cy + 12, cx + r - 4, cy + r - 4))).get(rq.SPECTRA6["black"], 0)
        assert lr > ul

    def test_hour_is_the_filled_rig_cell(self):
        rects = rq._oblivion_rig_rects()
        assert len(rects) == 12 and len(rq._oblivion_rig_points()) == 12
        for hour in (1, 6, 12):
            image = self._render(time_str=f"{hour:02d}:10")
            for i, (x0, y0, x1, y1) in enumerate(rects):
                cell = ink_counts(image.crop((x0 + 1, y0 + 15, x1, y1 - 4)))
                area = (x1 - x0 - 1) * (y1 - y0 - 19)
                black = cell.get(rq.SPECTRA6["black"], 0)
                assert (black > area * 0.6) == (i + 1 == hour), (hour, i)
                assert (rq.SPECTRA6["red"] in ink_counts(image.crop((x0, y0, x1 + 1, y1 + 1)))) == (i + 1 == hour)

    def test_hours_rig_is_red_on_the_map(self):
        points = rq._oblivion_rig_points()
        for hour in (2, 8):
            image = self._render(time_str=f"{hour:02d}:00")
            x, y = points[hour - 1]
            assert ink_counts(image.crop((x - 7, y - 7, x + 7, y + 7))).get(rq.SPECTRA6["red"], 0) > 80
            ox, oy = points[(hour + 5) % 12]
            assert rq.SPECTRA6["red"] not in ink_counts(image.crop((ox - 4, oy - 4, ox + 4, oy + 4)))

    def test_dial_marks_the_hours_bearing(self):
        r0 = rq._OBLIVION_DIAL_RADII[0]
        for hour in (3, 9, 12):
            image = self._render(time_str=f"{hour:02d}:00")
            x, y = rq._oblivion_polar(r0 - 6, hour)
            assert ink_counts(image.crop((x - 8, y - 8, x + 8, y + 8))).get(rq.SPECTRA6["red"], 0) > 40, hour
            dx, dy = rq._oblivion_polar(sum(rq._OBLIVION_DIAL_RADII[1:]) / 2, hour)
            assert ink_counts(image.crop((dx - 6, dy - 6, dx + 6, dy + 6))).get(rq.SPECTRA6["red"], 0) > 40, hour

    def test_data_is_seeded_from_the_quote(self):
        a = self._render()
        b = self._render(dict(self.ROW, source_id="1727", line_number=9))
        assert pixel_bytes(a.crop(rq._OBLIVION_WAVE_RECT)) != pixel_bytes(b.crop(rq._OBLIVION_WAVE_RECT))
        assert pixel_bytes(a.crop(rq._oblivion_numeral_rect())) != pixel_bytes(b.crop(rq._oblivion_numeral_rect()))


class TestYorhaFrame(_CustomFrameCase):
    """``yorha`` — the YoRHa archives: a dithered cream sheet with the blurred
    city and the hatch, crisp panels with shadows, Pod 042, the hour's row
    inverted and the phrase knocked out of a black box."""

    THEME = "yorha"
    SATURATION = 0.5

    def test_set_in_a_classical_serif(self):
        assert rq.theme_font_candidates("yorha", "quote_regular")[0] == rq.EBGARAMOND_REGULAR
        assert rq.theme_font_candidates("yorha", "quote_bold")[0] == rq.EBGARAMOND_BOLD

    def test_bold_instance_is_pinned_off_the_axis_default(self):
        """Montserrat's default instance is Regular; the Bold the lumon phrase
        and scary digits use must be a different drawing."""
        from PIL import ImageFont
        pinned = rq.load_font([(rq.MONTSERRAT_VARIABLE, "Bold")], size=40)
        bare = ImageFont.truetype(rq.MONTSERRAT_VARIABLE, 40)

        def ink(font):
            img = Image.new("L", (400, 60), 0)
            ImageDraw.Draw(img).text((0, 0), "Hamburgefonts", font=font, fill=255)
            return sum(img.point(lambda v: 1 if v > 127 else 0).histogram()[1:])

        assert ink(pinned) > ink(bare)

    def test_sheet_is_three_ink_tone_and_cached(self):
        scene = rq._yorha_scene()
        assert scene is rq._yorha_scene()
        assert set(ink_counts(scene)) == {rq.SPECTRA6["white"], rq.SPECTRA6["yellow"], rq.SPECTRA6["black"]}
        # The open sheet between the menu and the pane: cream with the hatch's black.
        gap = ink_counts(scene.crop((232, 100, 248, 380)))
        total = sum(gap.values())
        assert 0.1 < gap.get(rq.SPECTRA6["yellow"], 0) / total < 0.45
        assert 0 < gap.get(rq.SPECTRA6["black"], 0) / total < 0.3
        # The corners are darker than the middle of the sheet.
        corner = ink_counts(scene.crop((0, 60, 24, 76))).get(rq.SPECTRA6["black"], 0) / (24 * 16)
        assert corner > gap.get(rq.SPECTRA6["black"], 0) / total

    def test_panels_are_crisp_cream_with_shadows(self):
        scene = rq._yorha_scene()
        x0, y0, x1, y1 = rq._YORHA_PANE_RECT
        face = ink_counts(scene.crop((x0 + 40, y0 + 60, x0 + 200, y0 + 140)))
        area = 160 * 80
        assert abs(face[rq.SPECTRA6["yellow"]] / area - 0.125) < 0.02
        assert face.get(rq.SPECTRA6["black"], 0) < area * 0.02          # only the dot grid
        # The shadow: darker just below the pane's foot than above its head.
        below = ink_counts(scene.crop((x0 + 40, y1 + 2, x1 - 40, y1 + 8))).get(rq.SPECTRA6["black"], 0)
        above = ink_counts(scene.crop((x0 + 40, y0 - 8, x1 - 40, y0 - 2))).get(rq.SPECTRA6["black"], 0)
        assert below > above * 1.5

    def test_pod_is_lit_from_the_upper_left(self):
        image = self._render()
        faces = rq._yorha_pod_faces()

        def black_share(name):
            xs, ys = [p[0] for p in faces[name]], [p[1] for p in faces[name]]
            # The face's interior, clear of its outline.
            counts = ink_counts(image.crop((min(xs) + 3, min(ys) + 2, max(xs) - 2, max(ys) - 1)))
            return counts.get(rq.SPECTRA6["black"], 0) / sum(counts.values())

        top = image.crop((min(p[0] for p in faces["top"]) + 12, faces["top"][2][1] + 2,
                          faces["top"][1][0] - 2, faces["top"][0][1] - 1))
        assert set(ink_counts(top)) == {rq.SPECTRA6["white"]}               # the lit top
        assert black_share("front") > 0.15                                   # the shaded end, and its port
        hands = [arm[-1] for arm in faces["arms"]]
        for hx, hy in hands:
            assert ink_counts(image.crop((hx - 3, hy - 1, hx, hy + 2))) == {rq.SPECTRA6["black"]: 9}
        # The white keyline lifts it off the stippled sheet, and nothing reaches the menu.
        cx, cy = rq._YORHA_POD_CENTRE
        assert min(p[1] for p in faces["top"]) - 3 > rq._YORHA_MENU_RECT[3]
        assert image.getpixel((faces["side"][0][0] - 2, cy)) == rq.SPECTRA6["white"]

    def test_hour_is_the_inverted_row(self):
        rows = rq._yorha_menu_rows()
        assert len(rows) == 12
        for hour in (1, 7, 12):
            image = self._render(time_str=f"{hour:02d}:40")
            for i, (x0, y0, x1, y1) in enumerate(rows):
                counts = ink_counts(image.crop((x0 + 2, y0 + 2, x1 - 2, y1 - 2)))
                area = (x1 - x0 - 4) * (y1 - y0 - 4)
                black = counts.get(rq.SPECTRA6["black"], 0)
                assert (black > area * 0.6) == (i + 1 == hour), (hour, i)

    def test_menu_labels_sit_centred_in_their_rows(self):
        """EB Garamond's ascent carries accent room over the caps, so a
        top-anchored label sat low; the cap height is centred instead."""
        image = self._render(time_str="05:00")
        for i, (x0, y0, _x1, y1) in enumerate(rq._yorha_menu_rows()):
            ink = rq.SPECTRA6["white" if i == 4 else "black"]
            rows = [y for y in range(y0 + 2, y1 - 1)
                    if any(image.getpixel((x, y)) == ink for x in range(x0 + 24, x0 + 60))]
            above, below = rows[0] - y0, y1 - rows[-1]
            assert abs(above - below) <= 2, (i, above, below)

    def test_phrase_box_hugs_the_ink(self):
        """The bar spans the bold face's ascender top to its descender foot
        with an even margin, not the whole line height."""
        draw = ImageDraw.Draw(Image.new("RGB", (800, 480)))
        placed = rq._yorha_layout(draw, make_row(**self.ROW))
        bold = next(item[3] for item in placed if item[4])
        (bx0, by0, bx1, by1), = rq._yorha_phrase_boxes(draw, placed)
        y = next(item[1] for item in placed if item[4])
        _l, ink_top, _r, ink_foot = bold.getbbox("hp", anchor="la")
        assert 0 < (y + ink_top) - by0 <= bold.size * 0.15
        assert 0 < by1 - (y + ink_foot) <= bold.size * 0.15
        assert abs(((y + ink_top) - by0) - (by1 - (y + ink_foot))) <= 1
        assert (by1 - by0) < bold.size * 1.3

    def test_phrase_is_knocked_out_of_a_black_box(self):
        image = self._render()
        draw = ImageDraw.Draw(Image.new("RGB", (800, 480)))
        boxes = rq._yorha_phrase_boxes(draw, rq._yorha_layout(draw, make_row(**self.ROW)))
        assert len(boxes) == 1
        box = ink_counts(image.crop(boxes[0]))
        area = (boxes[0][2] - boxes[0][0]) * (boxes[0][3] - boxes[0][1])
        assert box.get(rq.SPECTRA6["black"], 0) > area * 0.5
        assert box.get(rq.SPECTRA6["white"], 0) > 100
        plain = dict(self.ROW, matched_text="")
        pane = ink_counts(self._render(plain).crop(rq._YORHA_QUOTE_RECT))
        assert pane.get(rq.SPECTRA6["black"], 0) < ink_counts(image.crop(rq._YORHA_QUOTE_RECT))[rq.SPECTRA6["black"]]

    def test_pane_titles_the_book_and_counts_the_hour(self):
        a = self._render(time_str="03:00")
        b = self._render(dict(self.ROW, title="The Odyssey"), time_str="03:00")
        c = self._render(time_str="04:00")
        head = (rq._YORHA_PANE_RECT[0], rq._YORHA_PANE_RECT[1], rq._YORHA_PANE_RECT[2], rq._YORHA_PANE_RECT[1] + 44)
        assert pixel_bytes(a.crop(head)) != pixel_bytes(b.crop(head))
        assert pixel_bytes(a.crop(head)) != pixel_bytes(c.crop(head))
        assert pixel_bytes(a.crop(rq._YORHA_QUOTE_RECT)) == pixel_bytes(c.crop(rq._YORHA_QUOTE_RECT))

    def test_tab_bar_opens_intel_under_the_crest(self):
        image = self._render()
        bar = ink_counts(image.crop(rq._YORHA_HEADER_RECT))
        assert bar.get(rq.SPECTRA6["black"], 0) > 800 * 36 * 0.8
        assert bar.get(rq.SPECTRA6["white"], 0) > 1500                   # the tabs, the open tab's box, the crest


class TestHitchhikerFrame(_CustomFrameCase):
    """``hitchhiker`` — a Guide entry on the author with its two figures: the
    Babel fish under a raster, and the galaxy chart with the hour's sector
    marked YOU ARE HERE."""

    THEME = "hitchhiker"

    def test_masthead_is_yellow_with_the_badge(self):
        image = self._render()
        assert ink_counts(image.crop((40, 14, 760, 46))).get(rq.SPECTRA6["yellow"], 0) > 1200
        badge = ink_counts(image.crop((660, 16, 758, 36)))
        assert badge.get(rq.SPECTRA6["yellow"], 0) > 800 and badge.get(rq.SPECTRA6["black"], 0) > 80

    def test_entry_is_the_author_and_the_quote_white_with_yellow(self):
        a, b = self._render(), self._render(dict(self.ROW, author="Homer"))
        band = (62, rq._HITCHHIKER_ENTRY_Y + 10, 456, rq._HITCHHIKER_ENTRY_Y + 46)
        assert pixel_bytes(a.crop(band)) != pixel_bytes(b.crop(band))
        counts = ink_counts(a.crop(rq._HITCHHIKER_QUOTE_RECT))
        assert counts.get(rq.SPECTRA6["white"], 0) > 2000 and counts.get(rq.SPECTRA6["yellow"], 0) > 200
        assert rq.theme_font_candidates("hitchhiker", "quote_regular")[0] == rq.MICHROMA_REGULAR
        # Each line of the entry is headed by a marker in the inks in rotation.
        markers = ink_counts(a.crop((rq._HITCHHIKER_QUOTE_RECT[0] - 20, rq._HITCHHIKER_QUOTE_RECT[1],
                                     rq._HITCHHIKER_QUOTE_RECT[0] - 10, rq._HITCHHIKER_QUOTE_RECT[3])))
        assert {rq.SPECTRA6["blue"], rq.SPECTRA6["green"], rq.SPECTRA6["yellow"], rq.SPECTRA6["red"]} <= set(markers)

    def test_lettering_wobbles_but_is_seeded(self):
        """Hand-animated cels: the same text sets the same way every time,
        and a glyph run is not a straight ``draw.text`` of the string."""
        font = rq._hitchhiker_font(20)
        a = Image.new("RGB", (400, 40), "black")
        rq._hitchhiker_draw(ImageDraw.Draw(a), (4, 4), "DON'T PANIC", font, "white", rq.random.Random(7))
        b = Image.new("RGB", (400, 40), "black")
        rq._hitchhiker_draw(ImageDraw.Draw(b), (4, 4), "DON'T PANIC", font, "white", rq.random.Random(7))
        c = Image.new("RGB", (400, 40), "black")
        ImageDraw.Draw(c).text((4, 4), "DON'T PANIC", font=font, fill="white")
        assert pixel_bytes(a) == pixel_bytes(b)
        assert pixel_bytes(a) != pixel_bytes(c)

    def test_babel_fish_is_yellow_under_a_raster_with_its_organs(self):
        image = self._render()
        fish = ink_counts(image.crop(rq._HITCHHIKER_FISH_RECT))
        assert fish.get(rq.SPECTRA6["yellow"], 0) > 4000
        for ink in ("blue", "green", "red", "white"):
            assert fish.get(rq.SPECTRA6[ink], 0) > 100, ink
        cx, cy = rq._hitchhiker_fish_centre()
        # The raster: one row in three is black across the yellow body.
        body = image.crop((cx - 50, cy + 20, cx - 14, cy + 26))        # the belly, clear of the organs
        rows = [set(ink_counts(body.crop((0, r, 36, r + 1)))) for r in range(6)]
        assert sum(1 for r in rows if r == {rq.SPECTRA6["black"]}) == 2
        assert sum(1 for r in rows if r == {rq.SPECTRA6["yellow"]}) >= 3
        assert pixel_bytes(image.crop(rq._HITCHHIKER_FISH_RECT)) == \
            pixel_bytes(self._render(time_str="03:00").crop(rq._HITCHHIKER_FISH_RECT))

    def test_hour_is_the_outlined_sector(self):
        cx, cy = rq._HITCHHIKER_GALAXY_CENTRE
        radius = rq._HITCHHIKER_GALAXY_RADIUS
        for hour in (1, 5, 12):
            image = self._render(time_str=f"{hour:02d}:25")
            a0, a1 = rq._hitchhiker_sector_angle(hour)
            am = (a0 + a1) / 2
            ex, ey = cx + (radius - 12) * math.cos(am), cy + (radius - 12) * math.sin(am)
            earth = ink_counts(image.crop((round(ex) - 8, round(ey) - 8, round(ex) + 8, round(ey) + 8)))
            assert earth.get(rq.SPECTRA6["yellow"], 0) > 10 and earth.get(rq.SPECTRA6["blue"], 0) > 4, hour
            # The opposite sector carries no yellow ring.
            ox, oy = cx + (radius - 12) * math.cos(am + math.pi), cy + (radius - 12) * math.sin(am + math.pi)
            assert ink_counts(image.crop((round(ox) - 8, round(oy) - 8, round(ox) + 8, round(oy) + 8))).get(
                rq.SPECTRA6["yellow"], 0) < 6, hour
        assert rq._hitchhiker_sector_angle(12)[0] < rq._hitchhiker_sector_angle(1)[0]

    def test_galaxy_is_a_seeded_spiral_in_its_chart(self):
        image = self._render()
        chart = ink_counts(image.crop(rq._HITCHHIKER_GALAXY_RECT))
        assert chart.get(rq.SPECTRA6["white"], 0) > 150                # the stars and the labels
        assert chart.get(rq.SPECTRA6["blue"], 0) > 400                 # the sector lines and the ring
        label = ink_counts(image.crop((rq._HITCHHIKER_GALAXY_RECT[2] - 112, rq._HITCHHIKER_GALAXY_RECT[1] + 58,
                                       rq._HITCHHIKER_GALAXY_RECT[2] - 4, rq._HITCHHIKER_GALAXY_RECT[1] + 90)))
        assert label.get(rq.SPECTRA6["yellow"], 0) > 100                # YOU ARE HERE


def _escritoire_to_canvas(u: float, v: float) -> tuple[float, float]:
    """Sheet units to canvas pixels: the closed-form inverse of
    ``rq._escritoire_coeffs`` (the renderer only ever maps the other way)."""
    a, b, c, d, e, f, g, h = rq._escritoire_coeffs()
    m11, m12, m21, m22 = a - g * u, b - h * u, d - g * v, e - h * v
    det = m11 * m22 - m12 * m21
    return ((u - c) * m22 - (v - f) * m12) / det, ((v - f) * m11 - (u - c) * m21) / det


class TestEscritoireFrame:
    """``escritoire`` — a handwritten letter on a writing desk, seen at an
    angle: the quote laid out flat, warped into perspective, with faint
    earlier lines in the foreshortened band and brass out of focus beyond.

    Not a ``_CustomFrameCase``: that base asserts the frame changes with the
    hour, and this one deliberately carries no clock."""

    THEME = "escritoire"
    ROW = dict(display_quote="At half past two Mr. and Mrs. Irving left, and everybody went to "
                             "Bright River to see them off on the afternoon train.",
               matched_text="half past two", author="L. M. Montgomery", title="Anne of Avonlea",
               source_id="47", line_number=9699)
    HERO = dict(ROW, display_quote="It was a little after four now.", matched_text="a little after four")
    DENSE = dict(ROW, display_quote=(
        "Besides, you overlook the fact that the crime was committed at twenty minutes past eleven "
        "in the evening, as is shown by the clock, while the nocturnal visit, mentioned by the "
        "concierge, occurred at three o'clock in the morning."), matched_text="twenty minutes past eleven")

    @classmethod
    def _render(cls, row=None, time_str="14:30", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or cls.ROW)), *size, mode="production", theme=cls.THEME)

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert self.THEME in rq.THEMES and self.THEME in rq.THEME_ORDER
        assert self.THEME not in rq.CYCLE_EXCLUDED_THEMES
        # A cream sheet over most of the frame: the light-ground tier.
        assert display_inky.THEME_SATURATION[self.THEME] == 0.5
        for role in ("quote_regular", "quote_bold", "ornament"):
            first = rq.theme_font_candidates(self.THEME, role)[0]
            assert first[0] == rq.DANCINGSCRIPT_VARIABLE and first[1] in ("Regular", "Bold")
            assert (pathlib.Path(first[0]).parent / "OFL.txt").exists()
        # The hand is the letter theme's, shared rather than copied, so the
        # two fallback chains cannot drift apart.
        for role in ("quote_regular", "quote_bold"):
            assert rq.THEME_FONTS[self.THEME][role] is rq.THEME_FONTS["letter"][role]

    def test_on_palette_deterministic_and_clockless(self):
        image = self._render()
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        assert pixel_bytes(image) == pixel_bytes(self._render())
        # No clock: the matched phrase carries the time, so the hour is inert.
        for time_str in ("03:00", "23:59", "bogus"):
            assert pixel_bytes(self._render(time_str=time_str)) == pixel_bytes(image)

    def test_warp_lands_ink_solid(self):
        """The masks are thresholded after the warp: a grey fringe would come
        out of the palette snap as a ragged stipple around every glyph."""
        mask = Image.new("L", (rq._ESCRITOIRE_SHEET[0] * 2, rq._ESCRITOIRE_SHEET[1] * 2), 0)
        ImageDraw.Draw(mask).ellipse((400, 500, 900, 700), fill=255)
        warped = rq._escritoire_warp(mask, 120)
        assert warped.size == (800, 480)
        assert set(warped.tobytes()) == {0, 255}

    def test_sheet_mapping_round_trips(self):
        coeffs = rq._escritoire_coeffs()
        for u, v in ((0, 0), (900, 0), (450, 300), (100, 520)):
            x, y = _escritoire_to_canvas(u, v)
            a, b, c, d, e, f, g, h = coeffs
            den = g * x + h * y + 1
            assert abs((a * x + b * y + c) / den - u) < 1e-6
            assert abs((d * x + e * y + f) / den - v) < 1e-6
        # The far edge is foreshortened: narrower on the canvas than the near.
        (tlx, _), (trx, _), (brx, _), (blx, _) = rq._ESCRITOIRE_QUAD
        assert 0.5 < (trx - tlx) / (brx - blx) < 0.7

    @staticmethod
    def _vanishing_point(p0, p1, q0, q1):
        (x1, y1), (x2, y2), (x3, y3), (x4, y4) = p0, p1, q0, q1
        den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        a, b = x1 * y2 - y1 * x2, x3 * y4 - y3 * x4
        return ((a * (x3 - x4) - (x1 - x2) * b) / den, (a * (y3 - y4) - (y1 - y2) * b) / den)

    def test_sheet_is_a_real_perspective_with_a_level_horizon(self):
        # A sheet lying flat on the desk, seen by a level eye: the vanishing
        # points of its rows and of its sides share one horizontal horizon.
        # A quad drawn freehand can rise along its far edge while its sides
        # lean as if it were turned the other way; the writing then follows
        # neither and reads as climbing off the paper.
        tl, tr, br, bl = rq._ESCRITOIRE_QUAD
        rows = self._vanishing_point(tl, tr, bl, br)
        sides = self._vanishing_point(tl, bl, tr, br)
        assert sides[1] < 0, "the horizon sits above the panel"
        tilt = math.degrees(math.atan2(rows[1] - sides[1], rows[0] - sides[0]))
        assert abs(tilt) < 0.25, (rows, sides)
        # Turned so the right side lies further away: every row rises to the right.
        assert rows[0] > 800 and tr[1] < tl[1] and br[1] < bl[1]

    def test_quote_is_black_and_the_phrase_blue_on_the_paper(self):
        image = self._render()
        paper = rq._escritoire_sheet_mask(image.size)
        off_paper = Image.new("RGB", image.size, rq.SPECTRA6["white"])
        off_paper.paste(image, (0, 0), ImageChops.invert(paper))
        assert ink_counts(off_paper).get(rq.SPECTRA6["blue"], 0) == 0
        counts = ink_counts(image)
        assert counts.get(rq.SPECTRA6["blue"], 0) > 300
        # Removing the phrase from the row takes the blue with it.
        assert ink_counts(self._render(dict(self.ROW, matched_text=""))).get(rq.SPECTRA6["blue"], 0) == 0

    @pytest.mark.parametrize("row_name", ["HERO", "ROW", "DENSE"])
    def test_every_length_stays_on_the_page_and_the_panel(self, row_name):
        row = make_row(**getattr(self, row_name))
        layout = rq._escritoire_layout(row)
        top, bottom = layout["block"]
        band_top, band_bottom = rq._ESCRITOIRE_BAND
        assert band_top <= top and bottom <= band_bottom + 1
        left, right = rq._ESCRITOIRE_LEFT, rq._ESCRITOIRE_LEFT + rq._ESCRITOIRE_MEASURE
        for u, v in ((left, top), (right, top), (left, bottom), (right, bottom)):
            x, y = _escritoire_to_canvas(u, v)
            assert 8 <= x <= 792 and 8 <= y <= 472, (row_name, u, v, x, y)
        # Sizes stay above the floor a script face needs after the warp.
        assert layout["size"] >= rq._ESCRITOIRE_SIZES[rq.choose_layout(row["display_quote"])][1] * rq._ESCRITOIRE_SS

    def test_faint_lines_are_seeded_from_the_quote(self):
        a = make_row(**self.ROW)
        b = make_row(**dict(self.ROW, source_id="48"))
        faint_a = rq._escritoire_masks(a, rq._escritoire_layout(a))[2]
        faint_b = rq._escritoire_masks(b, rq._escritoire_layout(b))[2]
        assert faint_a.getbbox() is not None
        assert pixel_bytes(faint_a) == pixel_bytes(rq._escritoire_masks(a, rq._escritoire_layout(a))[2])
        assert pixel_bytes(faint_a) != pixel_bytes(faint_b)
        # They stop above the quote rather than running into it.
        assert faint_a.getbbox()[3] < rq._escritoire_layout(a)["top"]

    def test_brass_beyond_the_sheet_and_the_pen_across_it(self):
        image = self._render()
        brass = ink_counts(image.crop((500, 0, 800, 120)))
        for ink in ("red", "yellow", "white", "black"):
            assert brass.get(rq.SPECTRA6[ink], 0) > 200, ink
        ax, ay, ux, uy, length, _ = rq._escritoire_pen_axis()
        mid = (round(ax + ux * length / 2), round(ay + uy * length / 2))
        barrel = ink_counts(image.crop((mid[0] - 4, mid[1] - 4, mid[0] + 4, mid[1] + 4)))
        assert barrel.get(rq.SPECTRA6["black"], 0) > 50
        band_t = 127
        bx, by = round(ax + ux * band_t), round(ay + uy * band_t)
        band = ink_counts(image.crop((bx - 3, by - 3, bx + 3, by + 3)))
        assert band.get(rq.SPECTRA6["red"], 0) > 4 and band.get(rq.SPECTRA6["yellow"], 0) > 2
        # The nib rests on the paper, above where the quote starts.
        assert rq._escritoire_sheet_mask(image.size).getpixel((round(ax), round(ay))) == 255

    def test_long_and_missing_metadata(self):
        long_title = "The Extraordinary Adventures of Arsène Lupin, Gentleman-Burglar, " * 3
        for row in (dict(self.ROW, title=long_title), dict(self.ROW, author="", title="")):
            image = self._render(row)
            assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        # No author: no signature line. No title: the shared Gutenberg fallback.
        bare = make_row(**dict(self.ROW, author="", title=""))
        layout = rq._escritoire_layout(bare)
        assert layout["author"] == "" and layout["title"] == rq.fallback_title(bare)

    def test_extreme_lengths_shrink_rather_than_overflow(self):
        """The curator previews raw rows of up to ~470 characters, far past
        anything the clock picks; they must still end inside the band."""
        sentence = "At half past two the whole household went down to the river to see them off. "
        row = make_row(**dict(self.ROW, display_quote=(sentence * 6).strip()))
        assert len(row["display_quote"]) > 460
        layout = rq._escritoire_layout(row)
        assert layout["block"][1] <= rq._ESCRITOIRE_BAND[1] + 1
        assert layout["size"] >= rq._ESCRITOIRE_FLOOR * rq._ESCRITOIRE_SS
        for u in (rq._ESCRITOIRE_LEFT, rq._ESCRITOIRE_LEFT + rq._ESCRITOIRE_MEASURE):
            for v in layout["block"]:
                x, y = _escritoire_to_canvas(u, v)
                assert 8 <= x <= 792 and 8 <= y <= 472

    def test_signature_reserve_follows_the_fields_present(self):
        """Room is reserved per signature line present, not a fixed two lines:
        without an author the quote has more of the band and sets no smaller,
        and the block ends no lower."""
        for row in (self.HERO, self.ROW, self.DENSE):
            full = rq._escritoire_layout(make_row(**row))
            untitled = rq._escritoire_layout(make_row(**dict(row, author="")))
            assert untitled["author"] == "" and untitled["title"] == row["title"]
            assert untitled["size"] >= full["size"]
            assert untitled["block"][1] <= rq._ESCRITOIRE_BAND[1] + 1
        # On the dense row, which is height-bound, the freed line buys a larger
        # size outright.
        dense_full = rq._escritoire_layout(make_row(**self.DENSE))
        dense_bare = rq._escritoire_layout(make_row(**dict(self.DENSE, author="")))
        assert dense_bare["size"] > dense_full["size"]

    def test_missing_display_quote_renders(self):
        for value in ("", None):
            image = self._render(dict(self.ROW, display_quote=value, matched_text=""))
            assert distinct_inks(image) <= set(rq.SPECTRA6.values())

    def test_shadow_does_not_wrap_onto_the_top_rows(self):
        """The sheet runs off the bottom of the panel; a wrapping shift carried
        its shadow round to rows 0-25 and blacked out the lamp light there."""
        image = Image.new("RGB", (800, 480), rq.SPECTRA6["red"])
        rq._escritoire_paint_shadow(image)
        assert ink_counts(image.crop((0, 0, 800, 40))) == {rq.SPECTRA6["red"]: 800 * 40}
        # It does land on the desk past the sheets' right edge.
        assert ink_counts(image.crop((700, 140, 800, 440))).get(rq.SPECTRA6["black"], 0) > 100

    def test_scene_cache_rebuilds_when_a_painter_changes(self, monkeypatch):
        """The cache is keyed on the painters, so a neutered painter is seen
        even when an earlier render warmed it (the decoration fence relies on
        this)."""
        warm = rq._escritoire_scene()
        for name in ("_escritoire_paint_desk", "_escritoire_paint_shadow",
                     "_escritoire_paint_brass", "_escritoire_paint_sheet"):
            with monkeypatch.context() as m:
                m.setattr(rq_themes.escritoire, name, lambda image: None)
                assert pixel_bytes(rq._escritoire_scene()) != pixel_bytes(warm), name
        assert pixel_bytes(rq._escritoire_scene()) == pixel_bytes(warm)

    def test_desk_is_mahogany_not_aubergine(self):
        """Red over black alone read as plum on the panel: a fixed share of
        the desk's lit stipple is yellow, the print-sepia direction."""
        image = Image.new("RGB", (800, 480))
        rq._escritoire_paint_desk(image)
        counts = ink_counts(image.crop((300, 0, 500, 60)))
        red, yellow = counts.get(rq.SPECTRA6["red"], 0), counts.get(rq.SPECTRA6["yellow"], 0)
        assert red > 0 and yellow > 0
        assert 0.2 < yellow / (red + yellow) < 0.45
        assert set(counts) <= {rq.SPECTRA6["black"], rq.SPECTRA6["red"], rq.SPECTRA6["yellow"]}

    def test_brass_pieces_stand_whole_on_the_panel(self):
        """Cut off by the top edge they read as lit columns; each piece's top
        must be on the panel, with desk showing above it."""
        image = self._render()
        for cx, knots in rq._ESCRITOIRE_BRASS:
            top = knots[0][0]
            assert top >= 20, cx
            above = ink_counts(image.crop((cx - 6, top - 14, cx + 6, top - 6)))
            assert not above.get(rq.SPECTRA6["white"], 0), cx
            body_y = (knots[0][0] + knots[-1][0]) // 2
            body = ink_counts(image.crop((cx - 20, body_y - 6, cx + 20, body_y + 6)))
            assert body.get(rq.SPECTRA6["yellow"], 0) > 40, cx

    def test_pens_stand_in_the_cup_and_lie_behind(self):
        image = self._render()
        (bx, by), (tx, ty) = rq._ESCRITOIRE_CUP_PENS[0]
        shaft = ink_counts(image.crop((min(bx, tx), 6, max(bx, tx), by - 6)))
        assert shaft.get(rq.SPECTRA6["black"], 0) > 30
        for (nx, ny), _, _ in rq._ESCRITOIRE_BACK_PENS:
            nib = ink_counts(image.crop((nx - 30, ny - 12, nx, ny + 6)))
            assert nib.get(rq.SPECTRA6["yellow"], 0) > 10, (nx, ny)

    def test_a_page_lies_under_the_letter(self):
        image = self._render()
        under = rq._escritoire_sheet_mask(image.size, rq._ESCRITOIRE_UNDER_QUAD)
        sheet = rq._escritoire_sheet_mask(image.size)
        wedge = ImageChops.subtract(under, sheet)
        assert ink_counts(wedge.convert("RGB")).get((255, 255, 255), 0) > 1500
        shown = Image.new("RGB", image.size, rq.SPECTRA6["green"])
        shown.paste(image, (0, 0), wedge)
        counts = ink_counts(shown)
        paper = counts.get(rq.SPECTRA6["white"], 0) + counts.get(rq.SPECTRA6["yellow"], 0)
        assert paper > 800
        # It carries more yellow than the letter does, so the two separate.
        letter = Image.new("RGB", image.size, rq.SPECTRA6["green"])
        letter.paste(image, (0, 0), sheet)
        lc = ink_counts(letter.crop((400, 140, 700, 200)))
        letter_paper = lc.get(rq.SPECTRA6["white"], 0) + lc.get(rq.SPECTRA6["yellow"], 0)
        assert counts.get(rq.SPECTRA6["yellow"], 0) / paper > lc.get(rq.SPECTRA6["yellow"], 0) / max(1, letter_paper)


class TestLasvegasFrame(_CustomFrameCase):
    """``lasvegas`` — *Blade Runner 2049*: the dithered orange haze of the
    dead Las Vegas, K among the hives, and the LAPD archive pane whose lit
    drawer is the hour."""

    THEME = "lasvegas"
    SATURATION = 0.7

    def test_quote_is_white_barlow_with_a_yellow_phrase_on_black(self):
        assert rq.theme_font_candidates("lasvegas", "quote_regular")[0] == rq.BARLOW_MEDIUM
        assert rq.theme_font_candidates("lasvegas", "quote_bold")[0] == rq.BARLOW_BOLD
        image = self._render()
        counts = ink_counts(image.crop(rq._LASVEGAS_QUOTE_RECT))
        assert set(counts) <= {rq.SPECTRA6["black"], rq.SPECTRA6["white"], rq.SPECTRA6["yellow"]}
        assert counts.get(rq.SPECTRA6["white"], 0) > 2000
        assert counts.get(rq.SPECTRA6["yellow"], 0) > 300
        assert distinct_inks(image) == {rq.SPECTRA6[k] for k in ("red", "yellow", "black", "white")}

    def test_haze_is_a_red_heavy_dither_and_cached(self):
        scene = rq._lasvegas_scene()
        assert scene is rq._lasvegas_scene()
        # Open haze between the pane and the statue, above the towers.
        counts = ink_counts(scene.crop((440, 150, 530, 250)))
        red, yellow = counts.get(rq.SPECTRA6["red"], 0), counts.get(rq.SPECTRA6["yellow"], 0)
        assert red > yellow > 0.2 * 90 * 100
        # The sun's core is the palest passage in the sky.
        sx, sy, sr = rq._LASVEGAS_SUN
        core = ink_counts(scene.crop((sx - sr // 2, sy - sr // 2, sx + sr // 2, sy + sr // 2)))
        assert core.get(rq.SPECTRA6["white"], 0) > core.get(rq.SPECTRA6["red"], 0)

    def test_hour_is_the_lit_archive_drawer(self):
        rects = rq._lasvegas_cell_rects()
        assert len(rects) == 12
        for hour in (1, 7, 12):
            image = self._render(time_str=f"{hour:02d}:20")
            for i, (x0, y0, x1, y1) in enumerate(rects):
                cell = ink_counts(image.crop((x0, y0, x1 + 1, y1 + 1)))
                area = (x1 - x0 + 1) * (y1 - y0 + 1)
                assert (cell.get(rq.SPECTRA6["yellow"], 0) > area * 0.6) == (i + 1 == hour), (hour, i)

    def test_k_and_the_hives_stand_in_the_scanner_brackets(self):
        image = self._render()
        fx, gy = rq._LASVEGAS_K_FOOT
        assert ink_counts(image.crop((fx - 8, gy - 50, fx + 8, gy))).get(rq.SPECTRA6["black"], 0) > 300
        assert ink_counts(image.crop(rq._LASVEGAS_HIVES)).get(rq.SPECTRA6["black"], 0) > 400
        x0, y0, x1, y1 = rq._LASVEGAS_SCAN_RECT
        assert x0 < fx < x1 and y0 < gy < y1
        assert image.getpixel((x0 + 4, y0)) == rq.SPECTRA6["white"]      # a bracket's arm

    def test_dna_and_radiation_are_seeded_from_the_quote(self):
        a = self._render()
        b = self._render(dict(self.ROW, source_id="1727", line_number=9))
        assert pixel_bytes(a.crop(rq._LASVEGAS_DNA_RECT)) != pixel_bytes(b.crop(rq._LASVEGAS_DNA_RECT))
        assert pixel_bytes(a.crop(rq._LASVEGAS_DNA_RECT)) == pixel_bytes(self._render().crop(rq._LASVEGAS_DNA_RECT))


class TestBladerunnerFrame(_CustomFrameCase):
    """``bladerunner`` — *Blade Runner 2049*'s systems: an LAPD records
    terminal with the quote as a record, the dithered bone scan, the twins'
    identical DNA, and the baseline test whose lit prompt is the hour."""

    THEME = "bladerunner"
    SATURATION = 0.7

    def test_quote_is_white_condensed_with_a_yellow_phrase_on_black(self):
        assert rq.theme_font_candidates("bladerunner", "quote_regular")[0] == rq.BARLOWCOND_MEDIUM
        assert rq.theme_font_candidates("bladerunner", "quote_bold")[0] == rq.BARLOWCOND_BOLD
        image = self._render()
        counts = ink_counts(image.crop(rq._BLADERUNNER_QUOTE_RECT))
        assert set(counts) <= {rq.SPECTRA6["black"], rq.SPECTRA6["white"], rq.SPECTRA6["yellow"]}
        assert counts.get(rq.SPECTRA6["white"], 0) > 2000
        assert counts.get(rq.SPECTRA6["yellow"], 0) > 300
        assert distinct_inks(image) == {rq.SPECTRA6[k] for k in ("black", "white", "yellow", "blue", "red")}

    def test_xray_is_dithered_blue_and_white_on_black_and_cached(self):
        scene = rq._bladerunner_scene()
        assert scene is rq._bladerunner_scene()
        x0, y0, x1, y1 = rq._BLADERUNNER_SCAN_RECT
        plate = ink_counts(scene.crop((x0 + 1, y0 + 18, x1, y1)))
        assert set(plate) == {rq.SPECTRA6["black"], rq.SPECTRA6["blue"], rq.SPECTRA6["white"]}
        assert plate[rq.SPECTRA6["blue"]] > plate[rq.SPECTRA6["white"]] > 1000
        # Off the plate the glass is plain black.
        assert set(ink_counts(scene.crop((0, 0, x0, 480)))) == {rq.SPECTRA6["black"]}
        # The bone sits where the mask says: denser inside it than beside it.
        mask = rq._bladerunner_bone_mask((x1 - x0 - 1, y1 - y0 - 19))
        assert mask.getpixel((mask.width // 2, 50)) == 255          # the sacrum
        assert mask.getpixel((mask.width // 2, 8)) == 0              # clear above it

    def test_serial_is_boxed_and_magnified_in_red(self):
        image = self._render()
        x0, y0, x1, y1 = rq._BLADERUNNER_SCAN_RECT
        inset = ink_counts(image.crop((x1 - 118, y1 - 40, x1 - 7, y1 - 9)))
        assert inset.get(rq.SPECTRA6["red"], 0) > 300 and inset.get(rq.SPECTRA6["white"], 0) > 150

    def test_twins_dna_is_identical_and_seeded_from_the_quote(self):
        row = make_row(**self.ROW)
        assert rq._bladerunner_sequence(row, 40) == rq._bladerunner_sequence(row, 40)
        other = make_row(**dict(self.ROW, source_id="1727", line_number=9))
        assert rq._bladerunner_sequence(row, 40) != rq._bladerunner_sequence(other, 40)
        image = self._render()
        x0, y0, x1, _ = rq._BLADERUNNER_DNA_RECT
        first = pixel_bytes(image.crop((x0 + 8, y0 + 39, x1 - 4, y0 + 65)))
        second = pixel_bytes(image.crop((x0 + 8, y0 + 89, x1 - 4, y0 + 115)))
        assert first == second                                       # base for base

    def test_hour_is_the_lit_baseline_prompt(self):
        rects = rq._bladerunner_word_rects()
        assert len(rects) == 12 == len(rq._BLADERUNNER_WORDS)
        for hour in (1, 9, 12):
            image = self._render(time_str=f"{hour:02d}:40")
            for i, (x0, y0, x1, y1) in enumerate(rects):
                cell = ink_counts(image.crop((x0, y0, x1 + 1, y1 + 1)))
                area = (x1 - x0 + 1) * (y1 - y0 + 1)
                assert (cell.get(rq.SPECTRA6["yellow"], 0) > area * 0.6) == (i + 1 == hour), (hour, i)
            # The trace marker stands over the hour's prompt, and only there.
            tx0, ty0, tx1, ty1 = rq._BLADERUNNER_TRACE_BAND
            band = image.crop((tx0, ty0 - 2, tx1, ty1 + 3))
            reds = [x for x in range(band.width) for y in range(band.height) if band.getpixel((x, y)) == rq.SPECTRA6["red"]]
            x0, _, x1, _ = rects[hour - 1]
            assert reds and all(x0 <= tx0 + x <= x1 for x in reds), hour


class TestTraumateamFrame(_CustomFrameCase):
    """``traumateam`` — *Cyberpunk*: a Trauma Team dispatch screen, the drawn
    wordmark over a red band naming the hour's unit, and a vitals trace."""

    THEME = "traumateam"

    def test_inks_are_black_white_red_and_the_cyan_tabs(self):
        image = self._render()
        assert distinct_inks(image) == {rq.SPECTRA6[k] for k in ("black", "white", "red", "green", "blue")}
        assert rq.theme_font_candidates("traumateam", "quote_regular")[0] == (rq.OXANIUM_VARIABLE, "Regular")
        assert rq.theme_font_candidates("traumateam", "quote_bold")[0] == (rq.OXANIUM_VARIABLE, "Bold")

    def test_lockup_is_white_and_centred(self):
        image = self._render()
        lockup = image.crop((0, 0, 800, rq._TRAUMATEAM_BAND[1] - 4))
        assert set(ink_counts(lockup)) == {rq.SPECTRA6["black"], rq.SPECTRA6["white"]}
        bbox = lockup.convert("L").point(lambda v: 255 if v > 128 else 0).getbbox()
        assert bbox is not None
        assert abs((bbox[0] + bbox[2]) / 2 - 400) <= 2
        assert bbox[1] >= 4

    def test_every_wordmark_glyph_stays_on_its_grid(self):
        for ch, (width, polys) in rq._TRAUMATEAM_GLYPHS.items():
            for poly in polys:
                assert all(0 <= x <= width and 0 <= y <= 9 for x, y in poly), ch
        assert set("TRAUMATEAM") <= set(rq._TRAUMATEAM_GLYPHS)

    def test_band_is_red_and_carries_the_hours_unit(self):
        assert rq._traumateam_unit_code(1) == "AV-01"
        assert rq._traumateam_unit_code(12) == "AV-12"
        assert rq._traumateam_status(make_row(**self.ROW)) in rq._TRAUMATEAM_STATUSES
        a, b = self._render(time_str="03:30"), self._render(time_str="04:30")
        band = ink_counts(a.crop(rq._TRAUMATEAM_BAND))
        assert band.get(rq.SPECTRA6["red"], 0) > 10000 and band.get(rq.SPECTRA6["white"], 0) > 400
        assert pixel_bytes(a.crop(rq._TRAUMATEAM_BAND)) != pixel_bytes(b.crop(rq._TRAUMATEAM_BAND))
        assert pixel_bytes(a.crop(rq._TRAUMATEAM_QUOTE_RECT)) == pixel_bytes(b.crop(rq._TRAUMATEAM_QUOTE_RECT))

    def test_phrase_is_white_on_a_red_block(self):
        image = self._render()
        counts = ink_counts(image.crop(rq._TRAUMATEAM_QUOTE_RECT))
        assert counts.get(rq.SPECTRA6["red"], 0) > 1000 and counts.get(rq.SPECTRA6["white"], 0) > 3000
        plain = dict(self.ROW, matched_text="")
        assert rq.SPECTRA6["red"] not in ink_counts(self._render(plain).crop(rq._TRAUMATEAM_QUOTE_RECT))

    def test_vitals_trace_is_seeded_from_the_quote(self):
        a = self._render()
        b = self._render(dict(self.ROW, source_id="1727", line_number=9))
        assert pixel_bytes(a.crop(rq._TRAUMATEAM_VITALS)) != pixel_bytes(b.crop(rq._TRAUMATEAM_VITALS))
        x0, y0, x1, y1 = rq._TRAUMATEAM_VITALS
        points = rq._traumateam_vitals_points(make_row(**self.ROW))
        assert all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in points)
        assert ink_counts(a.crop(rq._TRAUMATEAM_VITALS)).get(rq.SPECTRA6["white"], 0) > 800


class TestRedactedFrame:
    """``redacted`` — *Control*: a declassified Bureau document, the quote
    typed under the letterhead with seeded black bars over words the censor
    took, and never over the time."""

    THEME = "redacted"
    ROW = dict(
        display_quote="They had left the farmhouse that morning a little after three o'clock, having "
                      "packed their surveying equipment the day before, and crossed the pasture.",
        matched_text="a little after three",
        author="Willa Cather",
        title="The Song of the Lark",
    )

    @classmethod
    def _render(cls, row=None, time_str="14:30", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or cls.ROW)), *size, mode="production", theme=cls.THEME)

    @staticmethod
    def _placed(row):
        draw = ImageDraw.Draw(Image.new("RGB", (800, 480)))
        return draw, rq._place_quote(draw, make_row(**row), rq._REDACTED_QUOTE_RECT, theme="redacted",
                                     font_max=34, font_min=16, line_height_mult=1.45)

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert self.THEME in rq.THEMES and self.THEME in rq.THEME_ORDER
        assert self.THEME not in rq.CYCLE_EXCLUDED_THEMES
        assert display_inky.THEME_SATURATION[self.THEME] == 0.5
        assert rq.theme_font_candidates(self.THEME, "quote_regular")[0] == rq.SPECIALELITE_REGULAR

    def test_inks_are_black_white_and_red_and_deterministic(self):
        image = self._render()
        assert distinct_inks(image) == {rq.SPECTRA6[k] for k in ("black", "white", "red")}
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_never_reads_the_clock(self):
        a = self._render(time_str="09:00")
        for time_str in ("09:33", "21:17", "00:00", "bogus"):
            assert pixel_bytes(self._render(time_str=time_str)) == pixel_bytes(a)

    def test_downscales_the_canonical_frame(self):
        small = self._render(size=(320, 192))
        assert pixel_bytes(small) == pixel_bytes(self._render().resize((320, 192), Image.Resampling.NEAREST))

    def test_censor_spares_the_phrase_and_time_words(self):
        draw, placed = self._placed(self.ROW)
        phrase = [(x, x + w, y) for x, y, _c, _f, is_bold, w, _lh in placed if is_bold]
        assert phrase
        candidates = rq._redacted_candidates(draw, placed)
        assert candidates
        for _line, x0, x1, y in candidates:
            assert not any(py == y and x0 < px1 and px0 < x1 for px0, px1, py in phrase)
        words = {c.strip(rq._REDACTED_EDGE_PUNCT).lower() for _x, _y, c, *_ in placed}
        assert {"that", "morning", "before"} <= words & rq._REDACTED_SPARED
        assert len(candidates) < len([w for w in words if w])

    def test_censor_spares_compound_time_words(self):
        # A second time outside matched_text (corpus row 83:5162) must stay legible.
        for word in ("FORTY-SEVEN", "twenty-five", "half-past", "Quarter–Hour"):
            assert rq._redacted_is_spared(word), word
        assert not rq._redacted_is_spared("farm-house")
        row = dict(self.ROW, display_quote="TWENTY MINUTES PAST TEN TO FORTY-SEVEN MINUTES PAST TEN P. M.",
                   matched_text="TWENTY MINUTES PAST TEN")
        draw, placed = self._placed(row)
        assert rq._redacted_candidates(draw, placed) == []

    def test_at_least_one_bar_and_never_too_many(self):
        draw, placed = self._placed(self.ROW)
        candidates = rq._redacted_candidates(draw, placed)
        chosen = rq._redacted_choose(candidates, make_row(**self.ROW))
        assert 1 <= len(chosen) <= max(1, int(len(candidates) * rq._REDACTED_CAP))
        assert rq._redacted_choose([], make_row(**self.ROW)) == []

    def test_bars_are_seeded_from_the_quote(self):
        a = self._render()
        b = self._render(dict(self.ROW, source_id="1727", line_number=9))
        rect = rq._REDACTED_QUOTE_RECT
        assert pixel_bytes(a.crop(rect)) != pixel_bytes(b.crop(rect))
        assert rq._redacted_doc_fields(make_row(**self.ROW))[0] in rq._REDACTED_DOC_TYPES

    def test_phrase_is_red_and_only_the_phrase(self):
        rect = rq._REDACTED_QUOTE_RECT
        assert ink_counts(self._render().crop(rect)).get(rq.SPECTRA6["red"], 0) > 300
        plain = dict(self.ROW, matched_text="")
        assert rq.SPECTRA6["red"] not in ink_counts(self._render(plain).crop(rect))

    def test_stamp_stays_on_the_panel_and_clear_of_the_body(self):
        for seed in range(8):
            row = dict(self.ROW, line_number=seed)
            image = self._render(row)
            top = ink_counts(image.crop((0, 0, 800, 1)))
            assert rq.SPECTRA6["red"] not in top, seed
            plain = self._render(dict(row, matched_text=""))
            assert rq.SPECTRA6["red"] not in ink_counts(plain.crop((0, rq._REDACTED_FIELDS_Y + 24, 800, 480))), seed


class TestRedactedSleepFrame:
    """``redacted``'s own sleep frame: a SUSPENDED Standby Order, every word
    blacked out but "lights" early in the first line and "out" partway along
    the last."""

    @staticmethod
    def _words():
        draw = ImageDraw.Draw(Image.new("RGB", (800, 480)))
        words = rq._redacted_sleep_words(draw, rq._redacted_sleep_layout(draw))
        return words, rq._redacted_sleep_kept(words)

    def test_is_the_themes_sleep_frame(self):
        assert rq.FRAME_SPECS["redacted"].sleep is rq.render_redacted_sleep

    def test_lights_opens_the_page_and_out_hides_in_the_last_line(self):
        words, (lights, out) = self._words()
        last = words[-1][0]
        assert words[lights][1] == "lights" and words[lights][0] == 0
        assert words[out][1] == "out" and words[out][0] == last
        line_start = min(i for i, w in enumerate(words) if w[0] == last)
        line_end = max(i for i, w in enumerate(words) if w[0] == last)
        assert line_start < out < line_end, "out must sit inside its line, not at an end"
        assert 4 <= last + 1 <= 6

    def test_inks_and_only_two_red_words(self):
        image = rq.render_sleep_frame("22:00", 800, 480, theme="redacted")
        assert distinct_inks(image) == {rq.SPECTRA6[k] for k in ("black", "white", "red")}
        words, kept = self._words()
        body = image.crop(rq._REDACTED_QUOTE_RECT)
        assert ink_counts(body).get(rq.SPECTRA6["red"], 0) > 200
        x0, y0 = rq._REDACTED_QUOTE_RECT[:2]
        for i, (_line, _word, wx0, wx1, y, font) in enumerate(words):
            if i in kept:
                continue
            word = image.crop((int(wx0) + 2, y + 6, int(wx1) - 2, y + font.size - 4))
            assert rq.SPECTRA6["red"] not in ink_counts(word), _word

    def test_never_reads_the_clock_and_downscales(self):
        a = rq.render_redacted_sleep("22:00", 800, 480)
        for time_str in ("23:59", "06:00", "bogus"):
            assert pixel_bytes(rq.render_redacted_sleep(time_str, 800, 480)) == pixel_bytes(a)
        small = rq.render_redacted_sleep("22:00", 320, 192)
        assert pixel_bytes(small) == pixel_bytes(a.resize((320, 192), Image.Resampling.NEAREST))

    def test_quote_frame_is_unchanged_by_the_sleep_frame(self):
        frame = rq.render("14:30", make_row(**TestRedactedFrame.ROW), 800, 480, mode="production", theme="redacted")
        assert pixel_bytes(frame) != pixel_bytes(rq.render_redacted_sleep("14:30", 800, 480))


class TestMarqueeSleepFrame:
    """``marquee``'s own sleep frame: the house closed for the night, the
    bulbs still lit around a backlit letter board reading CLOSED over SEE YOU
    TOMORROW."""

    def test_is_the_themes_sleep_frame(self):
        assert rq.FRAME_SPECS["marquee"].sleep is rq.render_marquee_sleep

    def test_inks_are_the_quote_frames(self):
        image = rq.render_sleep_frame("22:00", 800, 480, theme="marquee")
        assert distinct_inks(image) == {rq.SPECTRA6[k] for k in ("black", "white", "red", "yellow")}

    def test_bulbs_stay_lit(self):
        # A dark marquee would read as a dead panel: the border keeps both bulb inks.
        image = rq.render_marquee_sleep("22:00", 800, 480)
        top = ink_counts(image.crop((0, 0, 800, 30)))
        assert top.get(rq.SPECTRA6["yellow"], 0) > 300
        assert top.get(rq.SPECTRA6["red"], 0) > 300

    def test_board_is_backlit_with_closed_in_red_above_black_letters(self):
        image = rq.render_marquee_sleep("22:00", 800, 480)
        x0, y0, x1, y1 = rq._MARQUEE_SLEEP_BOARD
        face = image.crop((x0 + 10, y0 + 10, x1 - 10, y1 - 10))
        counts = ink_counts(face)
        assert max(counts, key=counts.get) == rq.SPECTRA6["white"]
        assert set(counts) == {rq.SPECTRA6[k] for k in ("white", "black", "red")}
        # Red (CLOSED) sits entirely in the upper row; the lower row is black type only.
        (_, _, _, closed_cy), (_, _, _, second_cy) = rq._MARQUEE_SLEEP_LINES
        mid = (closed_cy + second_cy) // 2
        assert ink_counts(image.crop((x0 + 10, y0 + 10, x1 - 10, mid))).get(rq.SPECTRA6["red"], 0) > 5000
        assert rq.SPECTRA6["red"] not in ink_counts(image.crop((x0 + 10, mid, x1 - 10, y1 - 10)))
        # The trim is yellow, all the way round.
        assert image.getpixel((x0 + 2, (y0 + y1) // 2)) == rq.SPECTRA6["yellow"]
        assert image.getpixel(((x0 + x1) // 2, y1 - 2)) == rq.SPECTRA6["yellow"]

    def test_lettering_clears_the_board_face(self):
        # Long rows shrink rather than run off the board: the face margins stay white
        # between the rails.
        image = rq.render_marquee_sleep("22:00", 800, 480)
        x0, y0, x1, y1 = rq._MARQUEE_SLEEP_BOARD
        for _text, _cap, _colour, cy in rq._MARQUEE_SLEEP_LINES:
            for x in (x0 + 12, x0 + 20, x1 - 20, x1 - 12):
                assert image.getpixel((x, cy)) == rq.SPECTRA6["white"], (x, cy)

    def test_never_reads_the_clock_and_downscales(self):
        a = rq.render_marquee_sleep("22:00", 800, 480)
        for time_str in ("23:59", "06:00", "bogus"):
            assert pixel_bytes(rq.render_marquee_sleep(time_str, 800, 480)) == pixel_bytes(a)
        small = rq.render_marquee_sleep("22:00", 320, 192)
        assert small.size == (320, 192)
        assert pixel_bytes(small) == pixel_bytes(a.resize((320, 192), Image.Resampling.NEAREST))

    def test_quote_frame_is_unchanged_by_the_sleep_frame(self):
        row = make_row(display_quote="It was ten o'clock.", matched_text="ten o'clock", author="A. Author", title="A Book")
        frame = rq.render("14:30", row, 800, 480, mode="production", theme="marquee")
        assert pixel_bytes(frame) != pixel_bytes(rq.render_marquee_sleep("14:30", 800, 480))
        assert pixel_bytes(rq.render_sleep_frame("22:00", 800, 480, theme="marquee")) == pixel_bytes(
            rq.render_marquee_sleep("22:00", 800, 480))


class TestWitcherSleepFrame:
    """``witcher``'s own sleep frame: the meditation screen, set to rest until dawn.

    A 24-hour dial (noon at the top, midnight at the foot) whose band is lit
    tangerine from the hour quiet hours began round to dawn, where the hand
    stands. Hour-only; nothing prints a digit.
    """

    @staticmethod
    def _sleep(time_str="22:00", size=(800, 480)):
        return rq.render_witcher_sleep(time_str, *size)

    @staticmethod
    def _band_box(hour: float, half: int = 4):
        """A small box on the middle of the dial's band at ``hour``."""
        cx, cy = rq._WITCHER_SLEEP_DIAL_CENTRE
        mid = rq._WITCHER_SLEEP_DIAL_RADIUS - rq._WITCHER_SLEEP_BAND / 2
        a = rq._witcher_sleep_angle(hour)
        x, y = round(cx + math.cos(a) * mid), round(cy + math.sin(a) * mid)
        return (x - half, y - half, x + half + 1, y + half + 1)

    def test_is_the_themes_sleep_renderer(self):
        assert rq.FRAME_SPECS["witcher"].sleep is rq.render_witcher_sleep

    def test_render_sleep_frame_dispatches_to_it(self):
        assert pixel_bytes(rq.render_sleep_frame("22:00", 800, 480, theme="witcher")) == pixel_bytes(self._sleep())

    def test_on_palette_with_the_expected_inks(self):
        """Parchment (white + yellow), black line-work, red chrome and the
        tangerine arc, plus the binding's foxing green; no blue on this page."""
        inks = distinct_inks(self._sleep())
        assert inks <= set(rq.SPECTRA6.values())
        assert {rq.SPECTRA6[k] for k in ("black", "white", "yellow", "red", "green")} <= inks

    def test_deterministic(self):
        assert pixel_bytes(self._sleep()) == pixel_bytes(self._sleep())

    def test_every_minute_of_an_hour_renders_identically(self):
        first = pixel_bytes(self._sleep("23:00"))
        for minute in (1, 17, 30, 59):
            assert pixel_bytes(self._sleep(f"23:{minute:02d}")) == first

    def test_a_different_hour_moves_the_arc(self):
        assert pixel_bytes(self._sleep("22:00")) != pixel_bytes(self._sleep("23:00"))

    @pytest.mark.parametrize("bad", ["", "bogus", "xx:yy", None])
    def test_malformed_time_does_not_raise(self, bad):
        assert pixel_bytes(self._sleep(bad)) == pixel_bytes(self._sleep("12:00"))

    def test_downscale_is_a_nearest_resize_of_the_canonical_frame(self):
        small = self._sleep(size=(320, 192))
        assert small.size == (320, 192)
        expected = self._sleep().resize((320, 192), Image.Resampling.NEAREST)
        assert pixel_bytes(small) == pixel_bytes(expected)

    def test_arc_is_lit_from_the_hour_to_dawn(self):
        """At 22:00 the band at midnight is tangerine (red + yellow); the band
        at mid-afternoon, outside the rest, carries no red."""
        image = self._sleep("22:00")
        lit = ink_counts(image.crop(self._band_box(0)))
        assert lit.get(rq.SPECTRA6["red"], 0) and lit.get(rq.SPECTRA6["yellow"], 0)
        assert not ink_counts(image.crop(self._band_box(15))).get(rq.SPECTRA6["red"], 0)

    def test_arc_starts_at_the_quiet_hour(self):
        """Quiet hours entered at five leave midnight's band unlit."""
        image = self._sleep("05:00")
        assert not ink_counts(image.crop(self._band_box(0))).get(rq.SPECTRA6["red"], 0)
        assert ink_counts(image.crop(self._band_box(5.5))).get(rq.SPECTRA6["red"], 0)


class TestQuestlineSleepFrame:
    """``questline``'s own sleep frame: the same RPG scene after dark, an inn
    on the hills with Z's drifting from its dark upstairs window, and the
    innkeeper's "You rest at the inn" line in the dialogue box."""

    def test_is_the_themes_sleep_frame(self):
        assert rq.FRAME_SPECS["questline"].sleep is rq.render_questline_sleep

    def test_inks(self):
        image = rq.render_sleep_frame("22:00", 800, 480, theme="questline")
        assert pixel_bytes(image) == pixel_bytes(rq.render_questline_sleep("22:00", 800, 480))
        assert distinct_inks(image) == {rq.SPECTRA6[k] for k in ("black", "white", "red", "blue", "green", "yellow")}

    def test_never_reads_the_clock_and_downscales(self):
        a = rq.render_questline_sleep("22:00", 800, 480)
        assert pixel_bytes(rq.render_questline_sleep("22:00", 800, 480)) == pixel_bytes(a)
        for time_str in ("23:59", "06:00", "00:00", "bogus"):
            assert pixel_bytes(rq.render_questline_sleep(time_str, 800, 480)) == pixel_bytes(a)
        small = rq.render_questline_sleep("22:00", 320, 192)
        assert small.size == (320, 192)
        assert pixel_bytes(small) == pixel_bytes(a.resize((320, 192), Image.Resampling.NEAREST))

    def test_night_sky_has_a_moon_and_no_sun(self):
        image = rq.render_questline_sleep("22:00", 800, 480)
        sky = ink_counts(image.crop((0, 0, 800, rq._QUESTLINE_SKY_BOTTOM)))
        # A navy (blue + black) night, not the quote frame's blue + white day.
        assert sky.get(rq.SPECTRA6["white"], 0) < 0.05 * sum(sky.values())
        assert sky.get(rq.SPECTRA6["black"], 0) > 0.3 * sum(sky.values())
        cx, cy, r = rq._QUESTLINE_MOON
        assert ink_counts(image.crop((cx - r, cy - r, cx + r, cy + r))).get(rq.SPECTRA6["yellow"], 0) > 400
        # Where the daytime sun sits, the inn's roof and chimney stand instead.
        sun = ink_counts(image.crop((656, 38, 724, 106)))
        assert rq.SPECTRA6["yellow"] not in sun

    def test_inn_and_innkeeper_dialogue(self):
        image = rq.render_questline_sleep("22:00", 800, 480)
        x0, y0 = rq._QUESTLINE_INN_ORIGIN
        inn = ink_counts(image.crop((x0, y0, x0 + 22 * rq._QUESTLINE_INN_SCALE, y0 + 16 * rq._QUESTLINE_INN_SCALE)))
        assert inn.get(rq.SPECTRA6["red"], 0) > 4000  # the roof
        assert inn.get(rq.SPECTRA6["yellow"], 0) > 300  # lit window and door
        bx0, by0, bx1, by1 = rq._QUESTLINE_BOX
        body = ink_counts(image.crop((bx0 + 34, by0 + 28, bx1 - 34, by1 - 40)))
        assert body.get(rq.SPECTRA6["yellow"], 0) > 1000  # "rest at the inn" highlighted
        assert body.get(rq.SPECTRA6["white"], 0) > 3000
        assert rq._QUESTLINE_SLEEP_ROW["matched_text"] in rq._QUESTLINE_SLEEP_ROW["display_quote"]

    def test_quote_frame_is_unchanged_by_the_sleep_frame(self):
        row = make_row(display_quote="It was half past three.", matched_text="half past three", author="A", title="B")
        frame = rq.render("14:30", row, 800, 480, mode="production", theme="questline")
        assert pixel_bytes(frame) != pixel_bytes(rq.render_questline_sleep("14:30", 800, 480))


class TestYorhaSleepFrame:
    """``yorha``'s own sleep frame: the System menu with SLEEP MODE selected
    and the confirmation dialog "Enter sleep mode?" answered Yes, under Pod
    042's proposal."""

    def test_is_the_themes_sleep_frame(self):
        assert rq.FRAME_SPECS["yorha"].sleep is rq.render_yorha_sleep

    def test_inks_are_the_themes_own(self):
        image = rq.render_sleep_frame("22:00", 800, 480, theme="yorha")
        assert distinct_inks(image) == {rq.SPECTRA6[k] for k in ("white", "yellow", "black")}

    def test_never_reads_the_clock_and_downscales(self):
        a = rq.render_yorha_sleep("22:00", 800, 480)
        for time_str in ("23:59", "06:00", "12:00", "bogus"):
            assert pixel_bytes(rq.render_yorha_sleep(time_str, 800, 480)) == pixel_bytes(a)
        assert pixel_bytes(rq.render_yorha_sleep("22:00", 800, 480)) == pixel_bytes(a)
        small = rq.render_yorha_sleep("22:00", 320, 192)
        assert small.size == (320, 192)
        assert pixel_bytes(small) == pixel_bytes(a.resize((320, 192), Image.Resampling.NEAREST))

    def test_sleep_mode_row_and_yes_are_selected(self):
        image = rq.render_yorha_sleep("22:00", 800, 480)
        black = rq.SPECTRA6["black"]
        rows = rq._yorha_menu_rows()
        assert rq._YORHA_SLEEP_MENU[rq._YORHA_SLEEP_SELECTED] == "SLEEP MODE"

        def black_share(rect):
            counts = ink_counts(image.crop((rect[0] + 1, rect[1] + 1, rect[2], rect[3])))
            return counts.get(black, 0) / sum(counts.values())

        for i, row in enumerate(rows):
            if i == rq._YORHA_SLEEP_SELECTED:
                assert black_share(row) > 0.7
            else:
                assert black_share(row) < 0.4, rq._YORHA_SLEEP_MENU[i]
        yes, no = rq._yorha_sleep_option_rows()
        assert black_share(yes) > 0.7
        assert black_share(no) < 0.3

    def test_the_dialog_is_a_clean_panel_with_no_glitch(self):
        # The dialog's face between the prompt and the options is the crisp
        # W 7/8 : Y 1/8 panel stipple, untouched: a resting unit, not a broken one.
        image = rq.render_yorha_sleep("22:00", 800, 480)
        x0, y0, x1, _y1 = rq._YORHA_SLEEP_DIALOG_RECT
        strip = image.crop((x0 + 20, y0 + 76, x1 - 20, rq._yorha_sleep_option_rows()[0][1] - 2))
        counts = ink_counts(strip)
        assert set(counts) == {rq.SPECTRA6["white"], rq.SPECTRA6["yellow"]}
        assert 0.10 < counts[rq.SPECTRA6["yellow"]] / sum(counts.values()) < 0.15

    def test_quote_frame_is_unchanged_by_the_sleep_frame(self):
        row = make_row(author="Test Author", title="Test Title")
        frame = rq.render("03:00", row, 800, 480, mode="production", theme="yorha")
        assert pixel_bytes(frame) != pixel_bytes(rq.render_yorha_sleep("03:00", 800, 480))


class TestMetroSleepFrame:
    """``metro``'s own sleep frame: the same map on its night timetable. Day
    routes are hollow (two rails of their ink, white between), the night
    route runs dotted on top, and a service notice replaces the quote card."""

    def test_is_the_themes_sleep_frame(self):
        assert rq.FRAME_SPECS["metro"].sleep is rq.render_metro_sleep

    def test_full_palette_and_dispatch(self):
        image = rq.render_sleep_frame("22:00", 800, 480, theme="metro")
        assert pixel_bytes(image) == pixel_bytes(rq.render_metro_sleep("22:00", 800, 480))
        assert distinct_inks(image) == set(rq.SPECTRA6.values())

    def test_day_lines_are_hollow_where_the_day_map_is_solid(self):
        # The red route's last run (y=74, x 686..800) is clear of the card in
        # both frames: solid red by day, red rails around a white core at night.
        red, white = rq.SPECTRA6["red"], rq.SPECTRA6["white"]
        day = rq.render("22:00", make_row(), 800, 480, mode="production", theme="metro")
        night = rq.render_metro_sleep("22:00", 800, 480)
        assert day.getpixel((750, 74)) == red
        assert night.getpixel((750, 74)) == white
        column = [night.getpixel((750, y)) for y in range(64, 85)]
        assert column.count(red) >= 4, "the suspended line keeps its rails"
        assert ink_counts(night.crop((690, 60, 800, 90)))[red] < ink_counts(day.crop((690, 60, 800, 90)))[red]

    def test_night_line_runs_dotted(self):
        # The night route's first leg is x=84 from the masthead down to y=118:
        # a broken run of blue dots, not one solid stroke.
        blue = rq.SPECTRA6["blue"]
        night = rq.render_metro_sleep("22:00", 800, 480)
        column = [night.getpixel((84, y)) == blue for y in range(50, 112)]
        runs = sum(1 for prev, cur in pairwise([False, *column]) if cur and not prev)
        assert runs >= 3
        assert not all(column)
        # Its horizontal run under the interchanges is visible above the card.
        assert ink_counts(night.crop((200, 214, 600, 231))).get(blue, 0) > 500

    def test_never_reads_the_clock_and_downscales(self):
        a = rq.render_metro_sleep("22:00", 800, 480)
        for time_str in ("23:59", "06:00", "00:00", "bogus"):
            assert pixel_bytes(rq.render_metro_sleep(time_str, 800, 480)) == pixel_bytes(a)
        assert pixel_bytes(rq.render_metro_sleep("22:00", 800, 480)) == pixel_bytes(a)
        small = rq.render_metro_sleep("22:00", 320, 192)
        assert small.size == (320, 192)
        assert pixel_bytes(small) == pixel_bytes(a.resize((320, 192), Image.Resampling.NEAREST))

    def test_prints_no_digits(self, monkeypatch):
        drawn: list[str] = []
        original = ImageDraw.ImageDraw.text

        def spy(self, xy, text, *args, **kwargs):
            drawn.append(str(text))
            return original(self, xy, text, *args, **kwargs)

        monkeypatch.setattr(ImageDraw.ImageDraw, "text", spy)
        rq.render_metro_sleep("07:45", 800, 480)
        assert drawn, "the spy must see the frame's text"
        assert not any(ch.isdigit() for text in drawn for ch in text), drawn

    def test_quote_frame_is_unchanged_by_the_sleep_frame(self):
        frame = rq.render("14:30", make_row(), 800, 480, mode="production", theme="metro")
        assert pixel_bytes(frame) != pixel_bytes(rq.render_metro_sleep("14:30", 800, 480))


class TestTarotSleepFrame:
    """``tarot``'s own sleep frame: XVIII La Lune dealt in place of the hour's
    trump, with the bundled sleep quote as its reading."""

    def _render(self, time_str="22:00", size=(800, 480)):
        return rq.render_sleep_frame(time_str, *size, theme="tarot")

    def test_is_the_themes_sleep_frame(self):
        assert rq.FRAME_SPECS["tarot"].sleep is rq.render_tarot_sleep
        assert pixel_bytes(self._render()) == pixel_bytes(rq.render_tarot_sleep("22:00", 800, 480))

    def test_inks_determinism_and_no_time(self):
        a = self._render()
        assert distinct_inks(a) <= set(rq.SPECTRA6.values())
        for time_str in ("03:00", "12:59", "bogus"):
            assert pixel_bytes(self._render(time_str)) == pixel_bytes(a)
        assert pixel_bytes(self._render(size=(320, 192))) == pixel_bytes(a.resize((320, 192), Image.Resampling.NEAREST))

    def test_the_moon_is_past_every_hour(self):
        assert rq._TAROT_MOON_NUMERAL == "XVIII"
        assert rq._TAROT_MOON_NUMERAL not in rq._TAROT_ROMAN_NUMERALS.values()
        assert rq._TAROT_MOON_NAME not in rq._TAROT_TRUMP_NAMES.values()

    def test_the_card_carries_the_moon_plate(self):
        """The illustration panel is the committed XVIII plate, not any hour's."""
        image = rq.render_tarot_sleep("22:00", 800, 480)
        x0, y0, x1, y1 = rq._TAROT_CARD_RECT
        panel = (x0 + 21, y0 + 69, x1 - 20, y1 - 74)
        sleep_panel = pixel_bytes(image.crop(panel))
        for hour in range(1, 13):
            quote = rq.render(f"{hour:02d}:00", make_row(), 800, 480, mode="production", theme="tarot")
            assert pixel_bytes(quote.crop(panel)) != sleep_panel, hour
        assert ink_counts(image.crop(panel)).get(rq.SPECTRA6["black"], 0) > 5000

    def test_falls_back_to_a_painted_moon_without_the_plate(self, monkeypatch, tmp_path):
        from idle_hours.render_quote.themes import tarot
        monkeypatch.setattr(tarot, "TAROT_MOON_PLATE", tmp_path / "missing.png")
        monkeypatch.setitem(tarot._TAROT_PLATE_CACHE, "moon", None)
        fallback = rq.render_tarot_sleep("22:00", 800, 480)
        assert distinct_inks(fallback) <= set(rq.SPECTRA6.values())
        monkeypatch.undo()
        assert pixel_bytes(fallback) != pixel_bytes(rq.render_tarot_sleep("22:00", 800, 480))

    def test_the_reading_is_the_sleep_quote_on_one_line(self):
        draw = ImageDraw.Draw(Image.new("RGB", (800, 480)))
        x0, y0, x1, y1 = rq._TAROT_READING_RECT
        row = rq.SLEEP_QUOTE_ROW
        *_, wrapped, _lh, _size = rq.fit_quote(
            draw, row["display_quote"], row["matched_text"], (x1 - x0) - 16, (y1 - 30 - y0) - 16,
            font_max=rq._TAROT_SLEEP_FONT_MAX, font_min=15, line_height_mult=1.24, theme="tarot",
        )
        assert len(wrapped) == 1

    def test_the_sleep_row_has_one_home(self):
        from idle_hours.render_quote import core, furniture
        assert core.SLEEP_QUOTE_ROW is furniture.SLEEP_QUOTE_ROW is rq.SLEEP_QUOTE_ROW


class TestChronoSleepFrame:
    """``chrono``'s own sleep frame: the End of Time, a lamppost burning on a
    platform in the void, the portrait hourglass run out, and the narrator's
    promise that the gates open again at dawn."""

    def _render(self, time_str="22:00", size=(800, 480)):
        return rq.render_sleep_frame(time_str, *size, theme="chrono")

    def test_is_the_themes_sleep_frame(self):
        assert rq.FRAME_SPECS["chrono"].sleep is rq.render_chrono_sleep
        assert pixel_bytes(self._render()) == pixel_bytes(rq.render_chrono_sleep("22:00", 800, 480))

    def test_inks_and_determinism(self):
        image = self._render()
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        assert {rq.SPECTRA6[k] for k in ("black", "white", "blue", "yellow", "red")} <= distinct_inks(image)
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_never_reads_the_time_and_downscales(self):
        a = self._render()
        for time_str in ("23:59", "06:00", "bogus"):
            assert pixel_bytes(self._render(time_str)) == pixel_bytes(a)
        assert pixel_bytes(self._render(size=(320, 192))) == pixel_bytes(a.resize((320, 192), Image.Resampling.NEAREST))

    def test_the_hourglass_has_run_out(self):
        """The upper bulb holds no sand; the lower one more than the quote
        frame's, which drains from above."""
        run_out = rq._chrono_build_hourglass(run_out=True)
        running = rq._chrono_build_hourglass()
        sand = {5, 6, 7}

        def sand_rows(img, y0, y1):
            return sum(1 for y in range(y0, y1) for x in range(img.width) if img.getpixel((x, y)) in sand)

        assert sand_rows(run_out, 9, 37) == 0 and sand_rows(running, 9, 37) > 0
        assert sand_rows(run_out, 38, 63) > sand_rows(running, 38, 63)
        assert pixel_bytes(running) == pixel_bytes(rq._chrono_build_hourglass(run_out=False))

    def test_the_lamp_is_lit_and_glows_into_the_void(self):
        image = self._render()
        x0, y0, x1, y1 = rq._CHRONO_LAMP_HEAD
        lantern = ink_counts(image.crop((x0 + 3, y0 + 3, x1 - 3, y1 - 3)))
        assert lantern.get(rq.SPECTRA6["yellow"], 0) > 0.5 * sum(lantern.values())
        halo = ink_counts(image.crop((x1 + 10, y0, x1 + 40, y1)))
        assert rq.SPECTRA6["yellow"] in halo and rq.SPECTRA6["black"] in halo

    def test_lamplight_pools_on_the_platform_not_round_it(self):
        """The pool is filled under the lamp and stops at the platform's rim.

        A core-less ``paint_neon_mask`` painted only a halo round its mask: a
        hollow ring with no light inside, spilling past the rim (PR #378).
        """
        image = self._render()
        yellow = rq.SPECTRA6["yellow"]
        x0, y0, x1, y1 = rq._CHRONO_PLATFORM
        cx = rq._CHRONO_LAMP_X

        def share(box):
            counts = ink_counts(image.crop(box))
            return counts.get(yellow, 0) / sum(counts.values())

        assert share((cx - 50, y0 + 12, cx - 12, y0 + 20)) > 0.2
        assert share((x0 + 60, y1 + 3, x1 - 60, y1 + 14)) == 0
        assert share((cx - 90, y0 - 12, cx - 20, y0 - 3)) == 0

    def test_quote_frame_still_shows_a_running_hourglass(self):
        row = make_row(display_quote="It was half past two.", matched_text="half past two")
        quote = rq.render("14:30", row, 800, 480, mode="production", theme="chrono")
        assert pixel_bytes(quote) != pixel_bytes(self._render())


class TestSamplerSleepFrame:
    """``sampler``'s own sleep frame: the bedtime prayer stitched as a sampler,
    under the alphabet row, with the maker's line, a moon and stars, and the
    motif band's house with its windows dark."""

    def _render(self, time_str="22:00", size=(800, 480)):
        return rq.render_sleep_frame(time_str, *size, theme="sampler")

    def test_is_the_themes_sleep_frame(self):
        assert rq.FRAME_SPECS["sampler"].sleep is rq.render_sampler_sleep
        assert pixel_bytes(self._render()) == pixel_bytes(rq.render_sampler_sleep("22:00", 800, 480))

    def test_inks_determinism_and_no_time(self):
        a = self._render()
        assert distinct_inks(a) <= set(rq.SPECTRA6.values())
        assert {rq.SPECTRA6[k] for k in ("black", "white", "red", "blue", "green", "yellow")} <= distinct_inks(a)
        for time_str in ("03:00", "12:59", "bogus"):
            assert pixel_bytes(self._render(time_str)) == pixel_bytes(a)
        assert pixel_bytes(self._render(size=(320, 192))) == pixel_bytes(a.resize((320, 192), Image.Resampling.NEAREST))

    def test_the_prayer_is_the_first_couplet_only(self):
        assert rq._SAMPLER_PRAYER == (
            "Now I lay me down to sleep,",
            "I pray the Lord my soul to keep.",
        )
        text = " ".join(rq._SAMPLER_PRAYER).lower()
        assert "die" not in text and "wake" not in text

    def test_the_rows_rejoin_into_the_prayer(self):
        rows = rq._sampler_prayer_rows()
        assert len(rows) == 4
        assert [" ".join(rows[i:i + 2]) for i in (0, 2)] == list(rq._SAMPLER_PRAYER)
        assert rq._SAMPLER_PRAYER_ACCENT in rows[1]

    def test_sleep_is_stitched_in_red_and_the_prayer_in_black(self):
        """The prayer band carries black floss and one red word; the red is
        confined to the second row, where "sleep" falls."""
        image = rq.render_sampler_sleep("22:00", 800, 480)
        red, black = rq.SPECTRA6["red"], rq.SPECTRA6["black"]
        line_h = rq._SAMPLER_LINE_ROWS * rq._SAMPLER_PRAYER_SIZE
        top = 102
        rows = [ink_counts(image.crop((60, top + i * line_h, 740, top + (i + 1) * line_h))) for i in range(4)]
        assert all(r.get(black, 0) > 1000 for r in rows)
        assert rows[1].get(red, 0) > 1000
        assert all(rows[i].get(red, 0) == 0 for i in (0, 2, 3))

    def test_the_houses_windows_are_dark(self):
        assert rq._SAMPLER_HOUSE_DARK[:4] == rq._SAMPLER_HOUSE[:4]
        assert all("Y" not in row for row in rq._SAMPLER_HOUSE_DARK[4:])
        assert all("Y" in row for row in rq._SAMPLER_HOUSE[4:])

    def test_differs_from_the_quote_frame(self):
        quote = rq.render("22:00", make_row(), 800, 480, mode="production", theme="sampler")
        assert pixel_bytes(quote) != pixel_bytes(self._render())


class TestTrisolarisSleepFrame:
    """``trisolaris``'s own sleep frame: a chaotic era has begun and the order
    is to dehydrate, with the dried rolls racked in their store under the
    promise of rehydration when the stable era returns."""

    def _render(self, time_str="22:00", size=(800, 480)):
        return rq.render_sleep_frame(time_str, *size, theme="trisolaris")

    def test_is_the_themes_sleep_frame(self):
        assert rq.FRAME_SPECS["trisolaris"].sleep is rq.render_trisolaris_sleep
        assert pixel_bytes(self._render()) == pixel_bytes(rq.render_trisolaris_sleep("22:00", 800, 480))

    def test_inks_and_determinism(self):
        image = self._render()
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        assert {rq.SPECTRA6[k] for k in ("black", "white", "blue", "yellow", "red")} <= distinct_inks(image)
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_never_reads_the_time_and_downscales(self):
        a = self._render()
        for time_str in ("03:00", "12:59", "06:30", "bogus"):
            assert pixel_bytes(self._render(time_str)) == pixel_bytes(a)
        assert pixel_bytes(self._render(size=(320, 192))) == pixel_bytes(a.resize((320, 192), Image.Resampling.NEAREST))

    def test_frozen_at_the_start_of_a_chaotic_era(self):
        """The sky is the first sample after a stable era gives way, so the
        header gives the order to dehydrate."""
        from idle_hours.render_quote.themes import trisolaris
        ephemeris = trisolaris._trisolaris_ephemeris()
        index = trisolaris._TRISOLARIS_SLEEP_INDEX
        dominance = trisolaris._TRISOLARIS_STABLE_DOMINANCE
        assert ephemeris[index - 1][2] > dominance >= ephemeris[index][2]
        # ... and the chaotic era it opens is a long one, not a flicker.
        assert all(ephemeris[k][2] <= dominance for k in range(index, index + 60))

    def test_the_header_shows_a_chaotic_era(self):
        """All three discs of the era glyph are filled, as in a chaotic quote frame."""
        image = self._render()
        x1 = rq._TRISOLARIS_COLUMN[1]
        yellow = rq.SPECTRA6["yellow"]
        for k in range(3):
            cx = x1 - 40 + 4 + k * 14
            assert image.getpixel((cx, 100)) == yellow, k

    def test_the_store_is_racked_and_the_quote_column_is_replaced(self):
        image = self._render()
        store = ink_counts(image.crop(rq._TRISOLARIS_SLEEP_STORE))
        assert store.get(rq.SPECTRA6["white"], 0) > 1500
        assert store.get(rq.SPECTRA6["yellow"], 0) > 100
        row = make_row(display_quote="It was half past two.", matched_text="half past two")
        for time_str in ("22:00", "02:30"):
            quote = rq.render(time_str, row, 800, 480, mode="production", theme="trisolaris")
            assert pixel_bytes(quote) != pixel_bytes(image)


class TestLiederSleepFrame:
    """``lieder``'s own sleep frame: the opening phrase of Brahms's
    *Wiegenlied*, Op. 49 No. 4, engraved with the quote frame's painters,
    "gut' Nacht" sung in red."""

    def _render(self, time_str="22:00", size=(800, 480)):
        return rq.render_sleep_frame(time_str, *size, theme="lieder")

    def test_is_the_themes_sleep_frame(self):
        assert rq.FRAME_SPECS["lieder"].sleep is rq.render_lieder_sleep
        assert pixel_bytes(self._render()) == pixel_bytes(rq.render_lieder_sleep("22:00", 800, 480))

    def test_inks_and_determinism(self):
        image = self._render()
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        assert {rq.SPECTRA6[k] for k in ("black", "white", "red")} <= distinct_inks(image)
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_never_reads_the_time_and_downscales(self):
        a = self._render()
        for time_str in ("23:59", "03:00", "12:00", "bogus"):
            assert pixel_bytes(self._render(time_str)) == pixel_bytes(a)
        assert pixel_bytes(self._render(size=(320, 192))) == pixel_bytes(a.resize((320, 192), Image.Resampling.NEAREST))

    def test_the_melody_is_brahms(self):
        """C major (Brahms wrote E-flat): E E | G. E E | G, upbeat of two quavers."""
        assert [(pitch, beats) for _text, pitch, beats, _hyphen in rq._LIEDER_SLEEP_MELODY] == [
            ("E4", 0.5), ("E4", 0.5), ("G4", 1.5), ("E4", 0.5), ("E4", 1.0), ("G4", 2.0),
        ]
        lyric = "".join(text + ("-" if hyphen else " ") for text, _p, _b, hyphen in rq._LIEDER_SLEEP_MELODY)
        assert lyric.strip() == "Gu-ten A-bend, gut' Nacht,"

    def test_bars_are_full_three_four(self):
        """The upbeat is one beat; every bar after it holds exactly three."""
        notes = rq._lieder_sleep_notes()
        bars, current = [], 0.0
        for note in notes:
            if note["bar"]:
                bars.append(current)
                current = 0.0
            current += note["beats"]
        bars.append(current)
        assert bars == [1.0, 3.0, 3.0]
        assert notes[-1].get("rest") and notes[-1]["beats"] == 1.0
        assert [n["pitch"] for n in notes if not n.get("rest")] == [0, 0, 2, 0, 0, 2]

    def test_red_is_good_night_on_the_stave(self):
        """Red appears only in the system (the sung "gut' Nacht" and its slur),
        in its right half; the header, stanza and plate line are black."""
        image = rq.render_lieder_sleep("22:00", 800, 480)
        red = rq.SPECTRA6["red"]
        top = rq._LIEDER_SLEEP_STAFF_TOP - 4 * rq._LIEDER_SLEEP_GAP
        bottom = rq._LIEDER_SLEEP_STANZA_TOP - 30
        assert red not in ink_counts(image.crop((0, 0, 800, top)))
        assert red not in ink_counts(image.crop((0, bottom, 800, 480)))
        assert red not in ink_counts(image.crop((0, top, 400, bottom)))
        assert ink_counts(image.crop((400, top, 800, bottom))).get(red, 0) > 300
        # The five staff lines run the width of the page.
        staff = image.crop((100, rq._LIEDER_SLEEP_STAFF_TOP, 700, rq._LIEDER_SLEEP_STAFF_TOP + 1))
        assert ink_counts(staff).get(rq.SPECTRA6["black"], 0) > 500

    def test_quote_frame_is_unchanged_by_the_sleep_frame(self):
        frame = rq.render("14:30", make_row(), 800, 480, mode="production", theme="lieder")
        assert pixel_bytes(frame) != pixel_bytes(rq.render_lieder_sleep("14:30", 800, 480))


class TestSemioticSleepFrame:
    """``semiotic``'s own sleep frame: HYPERSLEEP — the same bulkhead with the
    crew in stasis, Cobb's 004 CRYOGENIC VAULT in place of the hour's sign,
    and a text-only status placard."""

    def _render(self, time_str="22:00", size=(800, 480)):
        return rq.render_sleep_frame(time_str, *size, theme="semiotic")

    def test_is_the_themes_sleep_frame(self):
        assert rq.FRAME_SPECS["semiotic"].sleep is rq.render_semiotic_sleep
        assert pixel_bytes(self._render()) == pixel_bytes(rq.render_semiotic_sleep("22:00", 800, 480))

    def test_inks_and_determinism(self):
        image = self._render()
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        assert {rq.SPECTRA6[k] for k in ("black", "white", "red", "yellow", "blue")} <= distinct_inks(image)
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_never_reads_the_time_and_downscales(self):
        a = self._render()
        for time_str in ("23:59", "06:00", "bogus"):
            assert pixel_bytes(self._render(time_str)) == pixel_bytes(a)
        assert pixel_bytes(self._render(size=(320, 192))) == pixel_bytes(a.resize((320, 192), Image.Resampling.NEAREST))

    def test_the_featured_sign_is_cobbs_cryogenic_vault(self):
        """The feature panel is 004 CRYOGENIC VAULT from the CC BY sheet: pixel
        for pixel the panel the 04:00 quote frame features, since 004 is that
        hour's sign."""
        assert rq._SEMIOTIC_SLEEP_SIGN == "004" == rq._SEMIOTIC_HOUR_SIGNS[4]
        assert rq._SEMIOTIC_NAMES["004"] == "CRYOGENIC VAULT"
        x, y, w, h = rq._SEMIOTIC_FEATURE_BOX
        box = (x, y, x + w, y + h)
        sleep = rq.render_semiotic_sleep("22:00", 800, 480).crop(box)
        row = make_row(display_quote="It was four o'clock.", matched_text="four o'clock")
        vault = rq.render("04:00", row, 800, 480, mode="production", theme="semiotic").crop(box)
        assert pixel_bytes(sleep) == pixel_bytes(vault)

    def test_the_placard_is_text_only_and_centred(self):
        """Between the header and footer rules the placard carries only black
        status text on white: no pictograms (every sign on the frame is one of
        Cobb's), and no red, since it is a status panel, not an alarm. The
        text block sits centred between the two rules."""
        image = rq.render_semiotic_sleep("22:00", 800, 480)
        x0, _, x1, _ = rq._SEMIOTIC_PLACARD
        top, bottom = rq._SEMIOTIC_HEADER_RULE_Y + 4, rq._SEMIOTIC_FOOTER_RULE_Y - 4
        band = image.crop((x0 + 30, top, x1 - 30, bottom))
        assert set(ink_counts(band)) == {rq.SPECTRA6["white"], rq.SPECTRA6["black"]}
        ink = band.convert("L").point(lambda v: 255 if v < 128 else 0).getbbox()
        assert ink is not None
        above, below = ink[1], band.height - ink[3]
        assert abs(above - below) <= 8, (above, below)

    def test_companions_are_real_signs_from_the_sheet(self):
        assert all(code in rq._SEMIOTIC_INDEX for code in rq._SEMIOTIC_SLEEP_COMPANIONS)
        assert len(set(rq._SEMIOTIC_SLEEP_COMPANIONS)) == 3
        assert rq._SEMIOTIC_SLEEP_SIGN not in rq._SEMIOTIC_SLEEP_COMPANIONS

    def test_quote_frame_is_unchanged_by_the_sleep_frame(self):
        row = make_row(display_quote="It was half past two.", matched_text="half past two")
        quote = rq.render("14:30", row, 800, 480, mode="production", theme="semiotic")
        assert pixel_bytes(quote) != pixel_bytes(self._render())


class TestDskySleepFrame:
    """``dsky``'s own sleep frame: the computer put to bed for the crew's rest
    period, STBY lit and P06's VERB 50 NOUN 25 on the display, with the
    presleep checklist typed on the flight plan."""

    def _render(self, time_str="22:00", size=(800, 480)):
        return rq.render_sleep_frame(time_str, *size, theme="dsky")

    def test_is_the_themes_sleep_frame(self):
        assert rq.FRAME_SPECS["dsky"].sleep is rq.render_dsky_sleep
        assert pixel_bytes(self._render()) == pixel_bytes(rq.render_dsky_sleep("22:00", 800, 480))

    def test_inks_and_determinism(self):
        image = self._render()
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        assert {rq.SPECTRA6[k] for k in ("black", "white", "green", "yellow", "red")} <= distinct_inks(image)
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_never_reads_the_time_and_downscales(self):
        a = self._render()
        for time_str in ("23:59", "06:00", "bogus"):
            assert pixel_bytes(self._render(time_str)) == pixel_bytes(a)
        assert pixel_bytes(self._render(size=(320, 192))) == pixel_bytes(a.resize((320, 192), Image.Resampling.NEAREST))

    def test_display_shows_the_standby_prompt_with_prog_blank(self, monkeypatch):
        """Only VERB 50, NOUN 25 and R1's checklist code light. PROG stays dark:
        in the quote frame that register is the hour, so any digit there
        would read as a time."""
        drawn: list[str] = []
        real = rq_themes.dsky._dsky_draw_glyph

        def spy(draw, x, y, ch, **kw):
            drawn.append(ch)
            return real(draw, x, y, ch, **kw)

        monkeypatch.setattr(rq_themes.dsky, "_dsky_draw_glyph", spy)
        rq.render_dsky_sleep("22:00", 800, 480)
        assert drawn[:2] == [" ", " "]
        assert "".join(drawn).replace(" ", "") == "502500062"

    def test_stby_is_lit_and_comp_acty_is_dark(self):
        image = self._render()
        stby = next(r for r in rq._dsky_lamp_rects() if r[4] == "STBY")
        lamp = ink_counts(image.crop((stby[0] + 2, stby[1] + 2, stby[2] - 2, stby[3] - 2)))
        assert lamp.get(rq.SPECTRA6["white"], 0) > 0.6 * sum(lamp.values())
        x0, y0 = rq._DSKY_DISPLAY_RECT[:2]
        assert rq.SPECTRA6["green"] not in ink_counts(image.crop((x0 + 9, y0 + 9, x0 + 40, y0 + 36)))

    def test_quote_frame_is_unchanged_by_the_sleep_frame(self):
        quote = rq.render("14:30", make_row(), 800, 480, mode="production", theme="dsky")
        x0, y0 = rq._DSKY_DISPLAY_RECT[:2]
        assert rq.SPECTRA6["green"] in ink_counts(quote.crop((x0 + 9, y0 + 9, x0 + 40, y0 + 36)))
        assert pixel_bytes(quote) != pixel_bytes(self._render())


class TestPillowFloorApis:
    """The renderer must run on the declared Pillow floor (``Pillow>=9.3`` in
    pyproject.toml; Raspberry Pi OS bookworm ships 9.4), but this suite runs
    on a current Pillow, so an API added later never fails here. Fence the
    ones that have slipped in: ``rounded_rectangle(corners=...)`` is Pillow
    9.5+ and once crashed the ``semiotic`` sleep frame on the floor (PR #380).
    """

    POST_FLOOR_KWARGS = {"rounded_rectangle": {"corners"}}

    def test_no_post_floor_keyword_arguments(self):
        import ast
        root = pathlib.Path(rq.__file__).parent
        offenders = []
        for path in sorted(root.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(), str(path))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    banned = self.POST_FLOOR_KWARGS.get(node.func.attr, set())
                    offenders += [f"{path.relative_to(root)}:{node.lineno} {node.func.attr}({kw.arg}=)"
                                  for kw in node.keywords if kw.arg in banned]
        assert not offenders, offenders


class TestVhsSleepFrame:
    """``vhs``'s own sleep frame: the late movie was taped off-air and the
    tape ran on into the station sign-off, colour bars over the sign-off card,
    under the quote frame's wear."""

    def _render(self, time_str="22:00", size=(800, 480)):
        return rq.render_sleep_frame(time_str, *size, theme="vhs")

    def test_is_the_themes_sleep_frame(self):
        assert rq.FRAME_SPECS["vhs"].sleep is rq.render_vhs_sleep
        assert pixel_bytes(self._render()) == pixel_bytes(rq.render_vhs_sleep("22:00", 800, 480))

    def test_inks_and_determinism(self):
        image = self._render()
        assert distinct_inks(image) == set(rq.SPECTRA6.values())
        assert pixel_bytes(image) == pixel_bytes(self._render())

    def test_never_reads_the_time_and_downscales(self):
        a = self._render()
        for time_str in ("23:59", "06:00", "bogus"):
            assert pixel_bytes(self._render(time_str)) == pixel_bytes(a)
        assert pixel_bytes(self._render(size=(320, 192))) == pixel_bytes(a.resize((320, 192), Image.Resampling.NEAREST))

    def test_no_clock_and_the_deck_is_playing(self, monkeypatch):
        """The quote frame's OSD burns in HH:MM; the sleep frame must print no
        digit at all, and the deck's PLAY replaces the camcorder's REC."""
        texts: list[str] = []
        real_text = ImageDraw.ImageDraw.text
        real_chroma = rq_themes.vhs.draw_text_chroma_shift

        def spy_text(self, xy, text, *args, **kwargs):
            texts.append(text)
            return real_text(self, xy, text, *args, **kwargs)

        def spy_chroma(image, xy, text, *args, **kwargs):
            texts.append(text)
            return real_chroma(image, xy, text, *args, **kwargs)

        monkeypatch.setattr(ImageDraw.ImageDraw, "text", spy_text)
        monkeypatch.setattr(rq_themes.vhs, "draw_text_chroma_shift", spy_chroma)
        rq.render_vhs_sleep("14:30", 800, 480)
        assert "PLAY" in texts and "GOOD NIGHT" in texts and "REC" not in texts
        assert not any(ch.isdigit() for text in texts for ch in text)

    def test_seven_bars_in_order(self):
        """Each bar's middle holds the inks of its recipe: the six inks solid,
        grey as W+K, cyan as G+B+W, magenta as R+B."""
        image = self._render()
        x0, y0, x1, y1 = rq._VHS_BARS_RECT
        ink = rq.SPECTRA6
        recipes = ({ink["white"], ink["black"]}, {ink["yellow"]}, {ink["green"], ink["blue"], ink["white"]},
                   {ink["green"]}, {ink["red"], ink["blue"]}, {ink["red"]}, {ink["blue"]})
        bar_w = (x1 - x0) // len(recipes)
        for i, recipe in enumerate(recipes):
            cx = x0 + i * bar_w + bar_w // 2
            counts = ink_counts(image.crop((cx - 20, 60, cx + 20, 120)))
            share = sum(counts.get(c, 0) for c in recipe) / sum(counts.values())
            assert share > 0.9, (i, counts)
            assert all(counts.get(c, 0) for c in recipe), (i, counts)

    def test_the_bars_carry_the_tape_noise(self, monkeypatch):
        """The bars are painted over the tape ground, so the noise is laid
        again on top of them; without that the bars came out cleaner than the
        card below them (PR #382 review). The yellow bar is solid ink, so with
        the dropouts and tears off (both also put white or blue there) any
        white or blue left in it is noise."""
        monkeypatch.setattr(rq_themes.vhs, "_vhs_paint_dropouts", lambda image: None)
        monkeypatch.setattr(rq_themes.vhs, "_vhs_apply_tears", lambda image: None)
        image = self._render()
        x0, y0, x1, y1 = rq._VHS_BARS_RECT
        bar_w = (x1 - x0) // 7
        counts = ink_counts(image.crop((x0 + bar_w + 4, y0 + 50, x0 + 2 * bar_w - 4, y1 - rq._VHS_CASTELLATION_H)))
        assert counts.get(rq.SPECTRA6["white"], 0) + counts.get(rq.SPECTRA6["blue"], 0) > 20

    def test_tears_spare_the_sign_off_card(self, monkeypatch):
        """The card's lines sit outside every row the tears move. Through the
        small type a tear read as strikethrough; through GOOD NIGHT it shredded
        the words (the draft of this frame). Measured as the rows a render
        without tears differs on, so a change to the tear seed or pool that
        moves a tear onto the card fails here."""
        torn = self._render()
        monkeypatch.setattr(rq_themes.vhs, "_vhs_apply_tears", lambda image: None)
        clean = self._render()
        diff = ImageChops.difference(torn, clean)
        moved = {y for y in range(480 - rq._VHS_HEAD_SWITCH_H)
                 if diff.crop((0, y, 800, y + 1)).getbbox() is not None}
        assert moved, "the tears no longer move any row"
        for text, size, _bold, top in rq._VHS_SIGNOFF_LINES:
            assert not moved & set(range(top, top + size)), text

    def test_quote_frame_keeps_its_camcorder_osd(self):
        quote = rq.render("14:30", make_row(), 800, 480, mode="production", theme="vhs")
        assert pixel_bytes(quote) != pixel_bytes(self._render())


class TestGantryFrame:
    """``gantry`` — an overhead motorway message sign at night: the quote in
    amber LEDs on one lattice, the matched phrase lit white and bold, and the
    source on a green guide sign whose exit number is the hour."""

    THEME = "gantry"
    ROW = dict(
        display_quote="It was at ten o'clock today that the first of all Time Machines began its career.",
        matched_text="ten o'clock",
        author="H. G. Wells",
        title="The Time Machine",
    )

    @classmethod
    def _render(cls, row=None, time_str="10:00", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or cls.ROW)), *size, mode="production", theme=cls.THEME)

    @staticmethod
    def _fit(text, matched=""):
        x0, y0, x1, y1 = rq._GANTRY_FACE
        words = rq._gantry_words(make_row(display_quote=text, matched_text=matched))
        return words, rq._gantry_fit(words, x1 - x0, y1 - y0)

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert self.THEME in rq.THEMES and self.THEME in rq.THEME_ORDER
        assert self.THEME not in rq.CYCLE_EXCLUDED_THEMES
        assert display_inky.THEME_SATURATION[self.THEME] == 0.7
        assert rq.FRAME_SPECS[self.THEME].render is rq.render_gantry_frame

    def test_the_font_is_read_as_a_five_by_seven_matrix(self):
        """Lumen's dots sit a tenth of an em apart, so sampling the grid
        centres gives the classic matrix: caps five columns by seven rows on
        rows 2-8, descenders down to row 10, narrow glyphs trimmed to their ink."""
        width, cells = rq._gantry_glyph("H")
        assert width == 5
        assert {r for _, r in cells} == set(range(2, 9))
        assert {(0, r) for r in range(2, 9)} <= cells and {(4, r) for r in range(2, 9)} <= cells
        assert max(r for _, r in rq._gantry_glyph("g")[1]) == 10
        assert rq._gantry_glyph(".") == (1, frozenset({(0, 8)}))
        assert rq._gantry_glyph(" ") == (0, frozenset())

    def test_characters_the_face_lacks_get_stand_ins(self):
        assert rq._gantry_chars("£") == "L"
        assert rq._gantry_chars("œ") == "oe"
        assert rq._gantry_chars("—") == "-"
        assert rq._gantry_chars("é") == "é"     # the face carries it
        for ch in "£œ—’":
            assert all(rq._gantry_glyph(sub)[0] for sub in rq._gantry_chars(ch)), ch

    def test_arrows_are_the_faces_own_ligatures(self):
        """``->`` is one glyph: the face's 12-dot arrow, not a hyphen and a
        chevron side by side. Only the arrows are tokenised."""
        width, cells = rq._gantry_glyph("->")
        assert width == 12
        assert width > rq._gantry_glyph("-")[0] + 1 + rq._gantry_glyph(">")[0]
        assert {r for _, r in cells} == set(range(3, 8))
        assert rq._gantry_tokens("go -> now <3") == ["g", "o", " ", "->", " ", "n", "o", "w", " ", "<", "3"]

    def test_short_quotes_get_big_dots_and_long_ones_still_fit_whole(self):
        _, (pitch, *_rest) = self._fit("It was a little after four now.")
        assert pitch == rq._GANTRY_PITCHES[0]
        longest = max((row["display_quote"] for row in iter_jsonl(pathlib.Path(pq.DEFAULT_DATABASE_PATH))), key=len)
        words, (pitch, cols, _rows, _line_rows, lines) = self._fit(longest)
        assert pitch >= 4, "the longest corpus quote should not need the 3 px fallback"
        assert sum(len(line) for line in lines) == len(words), "a word was dropped"
        assert all(rq._gantry_line_width(line) <= cols - 2 for line in lines)

    def test_lines_are_balanced(self):
        """The narrowest measure that keeps the line count: no line ends up a
        stub under a full one."""
        _, (_pitch, _cols, _rows, _line_rows, lines) = self._fit(self.ROW["display_quote"])
        widths = [rq._gantry_line_width(line) for line in lines]
        assert len(widths) > 1 and min(widths) > 0.6 * max(widths)

    def test_matched_phrase_is_bold_and_the_only_white_on_the_face(self):
        def white_on_face(image):
            return ink_counts(image.crop(rq._GANTRY_FACE)).get(rq.SPECTRA6["white"], 0)
        assert white_on_face(self._render()) > 500
        assert white_on_face(self._render(row={**self.ROW, "matched_text": ""})) == 0
        _, (_p, cols, rows, line_rows, lines) = self._fit(self.ROW["display_quote"], self.ROW["matched_text"])
        body, lit = rq._gantry_lit_cells(lines, cols, rows, line_rows)
        plain_cells = sum(len(rq._gantry_glyph(ch)[1]) for ch in "tenoclock")
        assert len(lit) > 1.5 * plain_cells, "the phrase should be doubled-column bold"
        assert not body & lit

    def test_dead_leds_are_seeded_from_the_quote(self):
        a, b = self._render(), self._render()
        assert pixel_bytes(a) == pixel_bytes(b)
        other = {**self.ROW, "display_quote": self.ROW["display_quote"].replace("career.", "career!")}
        assert pixel_bytes(self._render(row=other)) != pixel_bytes(a)

    def test_exit_number_is_the_hour_and_nothing_else_reads_the_time(self):
        ten = self._render(time_str="10:05")
        assert pixel_bytes(self._render(time_str="10:55")) == pixel_bytes(ten)
        assert pixel_bytes(self._render(time_str="22:30")) == pixel_bytes(ten)
        eleven = self._render(time_str="11:05")
        diff = ImageChops.difference(ten, eleven).getbbox()
        assert diff is not None
        x0, y0, x1, _y1 = rq._GANTRY_GUIDE
        assert x0 <= diff[0] and diff[2] <= x1 and y0 - 24 <= diff[1] and diff[3] <= y0 + 6

    def test_on_palette_and_downscales(self):
        image = self._render()
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        small = self._render(size=(320, 192))
        assert pixel_bytes(small) == pixel_bytes(image.resize((320, 192), Image.Resampling.NEAREST))


_GANTRY_ARROW = "->"


class TestGantrySleepFrame:
    """``gantry``'s own sleep frame: the small hours on the same motorway, the
    traffic gone, the beacons dark, TIRED? REST AREA NEXT EXIT on the sign."""

    def test_is_the_spec_sleep_renderer(self):
        assert rq.FRAME_SPECS["gantry"].sleep is rq.render_gantry_sleep

    def test_never_reads_the_clock_and_downscales(self):
        a = rq.render_gantry_sleep("22:00", 800, 480)
        for time_str in ("23:59", "03:00", "bogus"):
            assert pixel_bytes(rq.render_gantry_sleep(time_str, 800, 480)) == pixel_bytes(a)
        small = rq.render_gantry_sleep("22:00", 320, 192)
        assert pixel_bytes(small) == pixel_bytes(a.resize((320, 192), Image.Resampling.NEAREST))

    def test_the_sign_points_to_the_exit(self):
        assert _GANTRY_ARROW in [w for line in self._lines() for word in line for w, _ in word]

    @staticmethod
    def _lines():
        return [rq._gantry_segment_words([(text, lit)]) for text, lit in rq._GANTRY_SLEEP_MESSAGE]

    def test_the_road_is_empty_and_the_question_is_lit(self):
        sleep = rq.render_gantry_sleep("22:00", 800, 480)
        quote = rq.render("22:00", make_row(**TestGantryFrame.ROW), 800, 480, mode="production", theme="gantry")
        # The middle lane's tail-light pair, near the foot of the frame. The
        # asphalt's dither carries a little red of its own, so compare, not zero.
        lane = (380, 430, 480, 480)
        red = rq.SPECTRA6["red"]
        assert ink_counts(quote.crop(lane)).get(red, 0) > 6 * ink_counts(sleep.crop(lane)).get(red, 0)
        # TIRED? is the white line: white LEDs sit only in the top third of the face.
        x0, y0, x1, y1 = rq._GANTRY_FACE
        top = ink_counts(sleep.crop((x0, y0, x1, y0 + (y1 - y0) // 3))).get(rq.SPECTRA6["white"], 0)
        rest = ink_counts(sleep.crop((x0, y0 + (y1 - y0) // 3, x1, y1))).get(rq.SPECTRA6["white"], 0)
        assert top > 500 and rest == 0


class TestPlatformFrame:
    """``platform`` — a railway departure board after dark: Lumen Round
    Medium dots for the body, Round Bold for the matched phrase, the book as
    the destination and the station clock underneath."""

    THEME = "platform"
    ROW = dict(
        display_quote="It was at ten o'clock today that the first of all Time Machines began its career.",
        matched_text="ten o'clock",
        author="H. G. Wells",
        title="The Time Machine",
    )

    @classmethod
    def _render(cls, row=None, time_str="10:00", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or cls.ROW)), *size, mode="production", theme=cls.THEME)

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert self.THEME in rq.THEMES and self.THEME in rq.THEME_ORDER
        assert display_inky.THEME_SATURATION[self.THEME] == 0.7
        assert rq.FRAME_SPECS[self.THEME].render is rq.render_platform_frame

    @pytest.mark.parametrize("instance, share", [("Medium", "_PLATFORM_MEDIUM_DOT"), ("Bold", "_PLATFORM_BOLD_DOT")])
    def test_dot_shares_are_measured_from_the_face(self, instance, share):
        """A full stop is one dot: its width at 1000 px is the instance's dot
        in thousandths of the 100-unit cell."""
        font = rq.load_font([(rq.LUMEN_VARIABLE, instance)], size=1000)
        canvas = Image.new("L", (1000, 1200), 0)
        ImageDraw.Draw(canvas).text((0, 0), ".", font=font, fill=255)
        box = canvas.getbbox()
        assert box is not None
        assert abs((box[2] - box[0]) / 100 - getattr(rq, share)) < 0.02

    def test_bold_dots_are_always_bigger(self):
        for pitch in rq._PLATFORM_MESSAGE_PITCHES:
            medium, bold = rq._platform_diameter(pitch, False), rq._platform_diameter(pitch, True)
            assert medium < bold <= pitch, pitch
            assert pitch - medium >= 1, "Medium dots must leave a gap"

    def test_matched_phrase_is_drawn_in_bigger_dots(self):
        """With and without the matched phrase, the same words: Bold dots put
        more amber on the board than Medium ones."""
        x0, y0, x1, y1 = rq._PLATFORM_WINDOW
        message = (x0, rq._PLATFORM_MESSAGE[0], x1, rq._PLATFORM_MESSAGE[1])
        yellow = rq.SPECTRA6["yellow"]
        lit = ink_counts(self._render().crop(message)).get(yellow, 0)
        plain = ink_counts(self._render(row={**self.ROW, "matched_text": ""}).crop(message)).get(yellow, 0)
        assert lit > plain * 1.05

    def test_short_quotes_get_big_dots_and_the_longest_still_fits(self):
        width = rq._PLATFORM_WINDOW[2] - rq._PLATFORM_WINDOW[0] - 2 * rq._PLATFORM_INSET
        height = rq._PLATFORM_MESSAGE[1] - rq._PLATFORM_MESSAGE[0]
        short = rq._platform_message_words(make_row(display_quote="It was a little after four now."))
        assert rq._platform_fit_message(short, width, height)[0] == rq._PLATFORM_MESSAGE_PITCHES[0]
        longest = max((r["display_quote"] for r in iter_jsonl(pathlib.Path(pq.DEFAULT_DATABASE_PATH))), key=len)
        words = rq._platform_message_words(make_row(display_quote=longest, matched_text=""))
        pitch, _rows, lines = rq._platform_fit_message(words, width, height)
        assert sum(len(line) for line in lines) == len(words), "a word was dropped"

    def test_long_destinations_are_truncated_with_dots(self):
        words = rq._platform_words("Around the World in Eighty Days", bold=True)
        line = rq._platform_truncate(words, 60)
        assert rq._platform_line_width(line) <= 60
        assert [g for g, _ in line[-1][-3:]] == ["."] * 3
        assert rq._platform_truncate(words, 1000) == words

    def test_the_board_is_a_clock(self):
        """The render time is the departure and the clock; the board changes
        with every minute, and nothing else about it does."""
        a, b = self._render(time_str="10:00"), self._render(time_str="10:05")
        diff = ImageChops.difference(a, b).getbbox()
        assert diff is not None
        assert diff[1] >= rq._PLATFORM_HEAD_TOP and diff[3] <= rq._PLATFORM_WINDOW[3]
        assert not ImageChops.difference(a.crop((0, rq._PLATFORM_LABEL_TOP, 800, rq._PLATFORM_CLOCK_TOP)),
                                         b.crop((0, rq._PLATFORM_LABEL_TOP, 800, rq._PLATFORM_CLOCK_TOP))).getbbox()
        assert pixel_bytes(self._render(time_str="10:00")) == pixel_bytes(a)

    def test_on_palette_and_downscales(self):
        image = self._render()
        assert distinct_inks(image) <= {rq.SPECTRA6[k] for k in ("black", "yellow", "red", "blue", "white")}
        small = self._render(size=(320, 192))
        assert pixel_bytes(small) == pixel_bytes(image.resize((320, 192), Image.Resampling.NEAREST))


class TestPlatformSleepFrame:
    """``platform``'s own sleep frame: no further departures, a good-night
    message, and the clock dark."""

    def test_is_the_spec_sleep_renderer(self):
        assert rq.FRAME_SPECS["platform"].sleep is rq.render_platform_sleep

    def test_never_reads_the_clock_and_downscales(self):
        a = rq.render_platform_sleep("22:00", 800, 480)
        for time_str in ("23:59", "03:00", "bogus"):
            assert pixel_bytes(rq.render_platform_sleep(time_str, 800, 480)) == pixel_bytes(a)
        small = rq.render_platform_sleep("22:00", 320, 192)
        assert pixel_bytes(small) == pixel_bytes(a.resize((320, 192), Image.Resampling.NEAREST))

    def test_the_clock_is_dark(self):
        x0, _, x1, y1 = rq._PLATFORM_WINDOW
        clock = (x0, rq._PLATFORM_MESSAGE[1] + 8, x1, y1)
        sleep = rq.render_platform_sleep("22:00", 800, 480).crop(clock)
        day = rq.render("22:00", make_row(**TestPlatformFrame.ROW), 800, 480, mode="production",
                        theme="platform").crop(clock)
        assert rq.SPECTRA6["yellow"] not in ink_counts(sleep)
        assert ink_counts(day).get(rq.SPECTRA6["yellow"], 0) > 300


class TestSplitflapFrame:
    """``splitflap`` — a split-flap message board: capitals in the board's
    character set on a fixed tile grid, the matched phrase on yellow tiles,
    two tiles caught mid-flip."""

    THEME = "splitflap"
    ROW = dict(
        display_quote="It was at ten o'clock today that the first of all Time Machines began its career.",
        matched_text="ten o'clock",
        author="H. G. Wells",
        title="The Time Machine",
    )

    @classmethod
    def _render(cls, row=None, time_str="10:00", size=(800, 480)):
        return rq.render(time_str, make_row(**(row or cls.ROW)), *size, mode="production", theme=cls.THEME)

    def test_registered_everywhere(self):
        from idle_hours import display_inky
        assert self.THEME in rq.THEMES and self.THEME in rq.THEME_ORDER
        assert display_inky.THEME_SATURATION[self.THEME] == 0.7
        assert rq.FRAME_SPECS[self.THEME].render is rq.render_splitflap_frame

    def test_only_the_boards_characters(self):
        assert rq._splitflap_chars("a") == "A"
        assert rq._splitflap_chars("’") == "'"
        assert rq._splitflap_chars("—") == "-"
        assert rq._splitflap_chars("é") == "E"
        assert rq._splitflap_chars("*") == ""
        tiles = rq._splitflap_layout(make_row(display_quote="Café *at* “ten”", matched_text="ten"))
        assert {ch for ch, _ in tiles.values()} <= rq._SPLITFLAP_CHARSET | {" "}

    def test_every_corpus_quote_fits_the_fixed_grid(self):
        """The grid never changes size, so the quote's rows are a hard budget."""
        for row in iter_jsonl(pathlib.Path(pq.DEFAULT_DATABASE_PATH)):
            words = rq._splitflap_words([(row["display_quote"], False)])
            assert len(rq._splitflap_wrap(words, rq._SPLITFLAP_COLS)) <= rq._SPLITFLAP_QUOTE_ROWS, row["display_quote"]

    def test_matched_phrase_is_on_yellow_tiles_with_its_spaces(self):
        tiles = rq._splitflap_layout(make_row(**self.ROW))
        lit = "".join(ch for (col, row), (ch, matched) in sorted(tiles.items(), key=lambda t: (t[0][1], t[0][0]))
                      if matched)
        assert lit == "TEN O'CLOCK"
        assert ink_counts(self._render().crop((*rq._SPLITFLAP_ORIGIN, 780, 460))).get(rq.SPECTRA6["yellow"], 0) > 1500

    def test_byline_drops_the_title_before_cutting_the_author(self):
        row = make_row(author="Fyodor Dostoyevsky", title="Crime and Punishment")
        assert "".join(ch for ch, _ in rq._splitflap_byline(row, 24)) == "-FYODOR DOSTOYEVSKY"
        assert "".join(ch for ch, _ in rq._splitflap_byline(row, 60)) == "-FYODOR DOSTOYEVSKY, CRIME AND PUNISHMENT"

    def test_mid_flip_tiles_leave_the_letter_before(self):
        tiles = rq._splitflap_layout(make_row(**self.ROW))
        flips = rq._splitflap_flips(tiles, 1234)
        assert len(flips) == rq._SPLITFLAP_FLIPS
        for pos, old in flips.items():
            new, matched = tiles[pos]
            assert not matched and new.isalpha()
            assert old == "ZABCDEFGHIJKLMNOPQRSTUVWXYZ"["ZABCDEFGHIJKLMNOPQRSTUVWXYZ".index(new, 1) - 1]
        assert rq._splitflap_flips(tiles, 1234) == flips

    def test_never_reads_the_time_and_downscales(self):
        image = self._render()
        assert pixel_bytes(self._render(time_str="17:45")) == pixel_bytes(image)
        assert distinct_inks(image) <= set(rq.SPECTRA6.values())
        small = self._render(size=(320, 192))
        assert pixel_bytes(small) == pixel_bytes(image.resize((320, 192), Image.Resampling.NEAREST))


class TestSplitflapSleepFrame:
    """``splitflap``'s own sleep frame: tile art, a moon and stars over GOOD
    NIGHT."""

    def test_is_the_spec_sleep_renderer(self):
        assert rq.FRAME_SPECS["splitflap"].sleep is rq.render_splitflap_sleep

    def test_never_reads_the_clock_and_downscales(self):
        a = rq.render_splitflap_sleep("22:00", 800, 480)
        for time_str in ("23:59", "03:00", "bogus"):
            assert pixel_bytes(rq.render_splitflap_sleep(time_str, 800, 480)) == pixel_bytes(a)
        small = rq.render_splitflap_sleep("22:00", 320, 192)
        assert pixel_bytes(small) == pixel_bytes(a.resize((320, 192), Image.Resampling.NEAREST))

    def test_the_moon_is_yellow_tiles(self):
        image = rq.render_splitflap_sleep("22:00", 800, 480)
        for col, row in rq._SPLITFLAP_MOON:
            x, y = rq._splitflap_tile_xy(col, row)
            assert image.getpixel((x + 4, y + 4)) == rq.SPECTRA6["yellow"]


class TestPaintHatchedTone:
    """``paint_hatched_tone``: a parallel line family whose weight tracks a
    tone field at constant pitch (``witcher`` uses it)."""

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
