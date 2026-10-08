"""Tests of the retired ``grimoire`` theme, moved verbatim from ``tests/test_render_quote_themes.py``.

Not collected (pytest only collects ``tests/``); restore them with the theme.
"""
# Original module header, kept so the tests read as they did:
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
from itertools import pairwise

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from idle_hours import pick_quote as pq
from idle_hours import render_quote as rq
from idle_hours.jsonl_io import iter_jsonl
from idle_hours.render_quote import text as rq_text
from idle_hours.render_quote import themes as rq_themes

from .conftest import make_row
from .pixel_helpers import distinct_inks, ink_counts, pixel_bytes

CUSTOM_THEMES = ("marquee", "tarot", "vinyl", "vitrail", "outrun", "sampler", "lieder", "izakaya",
                 "abyssal", "pride", "pulp", "vhs", "cardcatalog", "metro", "bakelite", "intaglio",
                 "nocturne", "plaque", "daguerreotype")


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
