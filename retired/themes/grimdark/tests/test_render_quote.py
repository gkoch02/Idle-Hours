"""Tests of the retired ``grimdark`` theme, moved verbatim from ``tests/test_render_quote.py``.

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


def test_grimdark_border_paints_aquila_and_skull():
    """The grimdark border paints a gold Imperial Aquila centred in the top
    margin and a bone-white memento-mori skull centred in the bottom margin."""
    img = Image.new("RGB", (800, 480), (0, 0, 0))
    rq.draw_grimdark_border(img, rq.THEMES["grimdark"])
    px = img.load()
    gold = rq.SPECTRA6["yellow"]
    bone = rq.SPECTRA6["white"]
    # Aquila — gold pixels clustered around (cx=400, ay=40).
    aquila_gold = sum(1 for x in range(360, 441) for y in range(26, 60) if px[x, y] == gold)
    assert aquila_gold > 120, "Imperial Aquila missing from top margin"
    # Skull — bone-white pixels clustered around (cx=400, sy=442).
    skull_bone = sum(1 for x in range(386, 415) for y in range(426, 458) if px[x, y] == bone)
    assert skull_bone > 80, "memento-mori skull missing from bottom margin"


def test_grimdark_border_paints_doubled_gold_blood_trim():
    """The grimdark trim is a thick gold outer rule + thin blood-red inner
    rule — both inks present, unlike gothic's red+white doubled rule."""
    img = Image.new("RGB", (800, 480), (0, 0, 0))
    rq.draw_grimdark_border(img, rq.THEMES["grimdark"])
    px = img.load()
    gold = rq.SPECTRA6["yellow"]
    blood = rq.SPECTRA6["red"]
    # Left-edge horizontal scan at y=120 (clear of the mid-edge blood stud
    # at y=240) crosses the gold outer rule (~x=12-14) then the blood inner
    # rule (~x=19).
    row_inks = {px[x, 120] for x in range(10, 24)}
    assert gold in row_inks, "gold outer trim missing"
    assert blood in row_inks, "blood inner trim missing"


def test_grimdark_matched_phrase_uses_forge_amber_recipe():
    """The grimdark matched-phrase red is rerouted to forge-amber (R+Y 5:3
    tangerine) in _draw_text_body, so a red-fill body paint produces both
    red and yellow pixels rather than solid red."""
    img = Image.new("RGB", (200, 60), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = rq.load_font(rq.QUOTE_FONT_BOLD_CANDIDATES, size=40)
    rq._draw_text_body(img, draw, (4, 4), "TWO", font=font, fill=rq.SPECTRA6["red"], theme="grimdark")
    inks = distinct_inks(img)
    assert rq.SPECTRA6["red"] in inks, "forge-amber should retain red pixels"
    assert rq.SPECTRA6["yellow"] in inks, "forge-amber should introduce yellow pixels"


def test_grimdark_border_paints_industrial_mottle():
    """The grimdark Layer-0 mottle stipples sparse white into the black void
    ground (synthesising dark gunmetal grey), but stays sparse enough to read
    as a dark charcoal rather than a light field — and uses only black/white
    so it never leaves the palette."""
    img = Image.new("RGB", (800, 480), (0, 0, 0))
    rq.draw_grimdark_border(img, rq.THEMES["grimdark"])
    px = img.load()
    white = rq.SPECTRA6["white"]
    black = rq.SPECTRA6["black"]
    # A background patch clear of ornaments and (border-only render) text.
    patch = [(x, y) for x in range(140, 220) for y in range(120, 175)]
    whites = sum(1 for x, y in patch if px[x, y] == white)
    frac = whites / len(patch)
    assert 0.02 < frac < 0.40, f"mottle density {frac:.3f} outside dark-grey range"
    # Every patch pixel is either void or grey-ink — never an off-palette tone.
    assert all(px[x, y] in (white, black) for x, y in patch)
