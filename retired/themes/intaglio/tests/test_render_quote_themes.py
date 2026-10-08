"""Tests of the retired ``intaglio`` theme, moved verbatim from ``tests/test_render_quote_themes.py``.

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
        worst = max(math.dist(a, b) for a, b in pairwise(pts))
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
