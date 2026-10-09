"""Tests of the retired ``grimdark`` theme, moved verbatim from ``tests/test_dither.py``.

Not collected (pytest only collects ``tests/``); restore them with the theme.
"""
# Original module header, kept so the tests read as they did:
"""Tests for the render-time image-dithering capability and the Anna Atkins
cyanotype plate it feeds."""
from __future__ import annotations

import pytest
from PIL import Image

from idle_hours import render_quote as rq
from idle_hours.render_quote import themes as rq_themes

from .pixel_helpers import distinct_inks, pixel_bytes


class TestGrimdarkPlate:
    def test_plate_asset_is_committed(self):
        assert rq.GRIMDARK_PLATE.exists(), "grimdark gunmetal plate asset is missing"

    def test_load_dithered_plate_is_on_palette_and_sized(self):
        plate = rq._load_dithered_plate(rq.GRIMDARK_PLATE, 200, 120, palette=rq._GUNMETAL_PALETTE)
        assert plate is not None
        assert plate.size == (200, 120)
        assert distinct_inks(plate) <= set(rq._GUNMETAL_PALETTE)

    def test_load_dithered_plate_is_cached(self):
        a = rq._load_dithered_plate(rq.GRIMDARK_PLATE, 160, 96, palette=rq._GUNMETAL_PALETTE)
        b = rq._load_dithered_plate(rq.GRIMDARK_PLATE, 160, 96, palette=rq._GUNMETAL_PALETTE)
        assert a is b  # memoised, same object
