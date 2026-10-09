"""Tests of the retired ``vinyl`` theme, moved verbatim from ``tests/test_render_quote.py``.

Not collected (pytest only collects ``tests/``); restore them with the theme.
"""
# Original module header, kept so the tests read as they did:
"""Tests for render_quote.py — layout selection, text helpers, color quantization."""
from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from unittest.mock import patch

import pytest

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PIL_AVAILABLE, reason="Pillow not installed")

from idle_hours import render_quote as rq  # noqa: E402
from idle_hours.render_quote import core as rq_core  # noqa: E402
from idle_hours.render_quote import fonts as rq_fonts  # noqa: E402
from idle_hours.render_quote import palette as rq_palette  # noqa: E402
from idle_hours.render_quote import text as rq_text  # noqa: E402

from .pixel_helpers import distinct_inks, ink_counts  # noqa: E402


@pytest.fixture(autouse=True)


def test_vinyl_frame_paints_spec_line():
    """The upleveled vinyl liner panel adds a spec strip (SIDE ONE · 33 RPM ·
    MONO · RUNNING TIME) below the READING heading, filling the dead cream
    between heading and quote body."""
    row = {
        "display_quote": "It was at ten o'clock today that the first of all Time Machines began.",
        "matched_text": "ten o'clock", "author": "H. G. Wells", "title": "The Time Machine",
        "source_id": "35", "line_number": 1, "quality_score": 90,
        "bucket": "h10_exact", "resolved_bucket": "h10_exact", "used_fallback": False,
    }
    img = rq.render("10:00", row, 800, 480, mode="production", theme="vinyl").convert("RGB")
    px = img.load()
    black = rq.SPECTRA6["black"]
    # The spec strip (hairline rule + Space Mono text) sits at y≈46-60 in the
    # right-half liner panel (x≥420).
    spec_black = sum(1 for x in range(420, 780) for y in range(46, 60) if px[x, y] == black)
    assert spec_black > 100, "vinyl spec strip missing"


def test_vinyl_spec_line_is_deterministic():
    """The spec strip's running time must derive from a STABLE bucket digest,
    not process-salted hash(), or renders of the same quote would differ and
    break the byte-exact golden / dedup contract."""
    row = {
        "display_quote": "It was at ten o'clock today.",
        "matched_text": "ten o'clock", "author": "A", "title": "B",
        "source_id": "1", "line_number": 1, "quality_score": 90,
        "bucket": "h10_exact", "resolved_bucket": "h10_exact", "used_fallback": False,
    }
    a = rq.render("10:00", row, 800, 480, mode="production", theme="vinyl").convert("RGB").tobytes()
    b = rq.render("10:00", row, 800, 480, mode="production", theme="vinyl").convert("RGB").tobytes()
    assert a == b, "vinyl frame not byte-deterministic across renders"
