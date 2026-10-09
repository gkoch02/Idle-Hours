"""Tests of the retired ``vinyl`` theme, moved verbatim from ``tests/test_render_quote_themes.py``.

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
        assert all(b < a for a, b in pairwise(radii)), f"stylus did not track inward: {radii}"
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
