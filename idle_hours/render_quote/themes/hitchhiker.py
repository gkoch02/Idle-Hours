"""The ``hitchhiker`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from .._paths import JOST_VARIABLE, MICHROMA_REGULAR, ORNAMENT_FONT_CANDIDATES
from ..fonts import load_font
from ..furniture import _clock_hour12, _place_quote, _row_digest, fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, snap_image_to_palette
from ..primitives import _catmull_rom
from ..spec import FrameSpec
from ..text import fit_text_to_width
from ._shared import _crt_paint_scanlines

# ---------------------------------------------------------------------------
# hitchhiker — *The Hitchhiker's Guide to the Galaxy* (BBC, 1981): the Guide
# ---------------------------------------------------------------------------
# A Guide entry as the 1981 series animated them by hand: a black screen,
# square-shouldered capitals, flat-colour diagrams with numbered callouts and
# DON'T PANIC. Full design notes: docs/themes.md (``hitchhiker``).
#
# The entry's subject is the quoted author; its text is the quote in white
# with the matched phrase in yellow, each line headed by a marker in the inks
# in rotation. Every glyph is set on its own with a seeded one-pixel
# registration wobble (``_hitchhiker_draw``), the look of held cel lettering.
#
# Figure 1 is the Babel fish under a CRT raster. Figure 2 is a seeded
# two-armed galaxy with twelve sector lines, and that is the clock: the hour's
# sector, clockwise from the top like a clock face, is outlined in yellow with
# the Earth ringed inside it and a YOU ARE HERE leader. Pinned across the
# minutes; the matched phrase carries the minute. Composed at 800x480 and
# NEAREST-downsampled otherwise (the ``metro`` convention).
# ---------------------------------------------------------------------------
_HITCHHIKER_SEED = 0x48484747         # HHGG
_HITCHHIKER_ENTRY_Y = 58
_HITCHHIKER_QUOTE_RECT = (62, 116, 456, 392)
_HITCHHIKER_SEEALSO_Y = 414
_HITCHHIKER_FISH_RECT = (474, 102, 770, 268)
_HITCHHIKER_GALAXY_RECT = (474, 286, 770, 462)
_HITCHHIKER_GALAXY_CENTRE = (596, 384)
_HITCHHIKER_GALAXY_RADIUS = 62
_HITCHHIKER_MARKER_INKS = ("blue", "green", "yellow", "red")
_HITCHHIKER_CALLOUTS = (
    ("1", "BRAINWAVE SENSOR"), ("2", "TELEPATHIC MATRIX"), ("3", "GILL SLITS"),
    ("4", "NERVE SIGNAL"), ("5", "THOUGHT OUTFLOW"),
)


def _hitchhiker_font(size: int):
    return load_font([MICHROMA_REGULAR, (JOST_VARIABLE, "Bold"), *ORNAMENT_FONT_CANDIDATES], size=size)


def _hitchhiker_draw(draw: ImageDraw.ImageDraw, xy, text: str, font, fill, rng: random.Random, *,
                     tracking: float = 0.0) -> float:
    """Hand-animated lettering: each glyph set on its own with a seeded
    one-pixel registration wobble. Returns the run's width."""
    x, y = xy
    start = x
    for ch in text:
        if ch != " ":
            draw.text((x + rng.choice((-1, 0, 0, 1)), y + rng.choice((-1, 0, 0, 1))), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x - start


def _hitchhiker_paint_masthead(draw: ImageDraw.ImageDraw) -> None:
    """The Guide's name, a rule, and the DON'T PANIC badge."""
    yellow, black = SPECTRA6["yellow"], SPECTRA6["black"]
    rng = random.Random(_HITCHHIKER_SEED + 1)
    _hitchhiker_draw(draw, (40, 20), "THE HITCH HIKER'S GUIDE TO THE GALAXY", _hitchhiker_font(13), yellow, rng,
                     tracking=2)
    draw.rectangle((40, 44, 760, 45), fill=yellow)
    font = _hitchhiker_font(12)
    label = "DON'T PANIC"
    tw = draw.textlength(label, font=font)
    draw.rounded_rectangle((760 - tw - 20, 14, 760, 38), radius=6, fill=yellow)
    draw.text((760 - tw - 10, 19), label, font=font, fill=black)


def _hitchhiker_paint_entry(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The entry's subject — the author — under an ENTRY label, with the
    colour bars at its left."""
    white, green = SPECTRA6["white"], SPECTRA6["green"]
    y = _HITCHHIKER_ENTRY_Y
    for i, ink in enumerate(_HITCHHIKER_MARKER_INKS):
        draw.rectangle((40, y + i * 11, 54, y + i * 11 + 7), fill=SPECTRA6[ink])
    draw.text((62, y - 2), "ENTRY", font=_hitchhiker_font(11), fill=green)
    subject = (quote_row.get("author") or "").strip() or "ANONYMOUS"
    font, text = fit_text_to_width(draw, subject.upper(), [MICHROMA_REGULAR, (JOST_VARIABLE, "Bold"),
                                                            *ORNAMENT_FONT_CANDIDATES], 24, 394, floor=14)
    _hitchhiker_draw(draw, (62, y + 13), text, font, white, random.Random(_HITCHHIKER_SEED ^ _row_digest(quote_row)))


def _hitchhiker_layout(draw: ImageDraw.ImageDraw, quote_row: dict):
    return _place_quote(draw, quote_row, _HITCHHIKER_QUOTE_RECT, theme="hitchhiker",
                        font_max=22, font_min=12, line_height_mult=1.55)


def _hitchhiker_paint_quote(draw: ImageDraw.ImageDraw, placed, quote_row: dict) -> None:
    """The entry's text, hand-lettered: white with the matched phrase in
    yellow, each line headed by a marker in the inks in rotation."""
    white, yellow = SPECTRA6["white"], SPECTRA6["yellow"]
    rng = random.Random(_HITCHHIKER_SEED + 2 + _row_digest(quote_row))
    lines = sorted({y for _, y, *_ in placed})
    for i, y in enumerate(lines):
        lh = next(p[6] for p in placed if p[1] == y)
        ink = SPECTRA6[_HITCHHIKER_MARKER_INKS[i % len(_HITCHHIKER_MARKER_INKS)]]
        draw.rectangle((_HITCHHIKER_QUOTE_RECT[0] - 18, y + lh // 2 - 7, _HITCHHIKER_QUOTE_RECT[0] - 12, y + lh // 2 - 1),
                       fill=ink)
    for x, y, chunk, font, is_bold, *_ in placed:
        _hitchhiker_draw(draw, (x, y), chunk, font, yellow if is_bold else white, rng)


def _hitchhiker_paint_seealso(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "").strip()
    if not title:
        return
    font, text = fit_text_to_width(draw, "SEE ALSO:  " + title.upper(), [MICHROMA_REGULAR, (JOST_VARIABLE, "Bold"),
                                                                           *ORNAMENT_FONT_CANDIDATES], 12, 416,
                                   floor=10)
    draw.text((40, _HITCHHIKER_SEEALSO_Y), text, font=font, fill=SPECTRA6["white"])


def _hitchhiker_fish_centre() -> tuple[int, int]:
    x0, y0, x1, y1 = _HITCHHIKER_FISH_RECT
    return x0 + 134, y0 + 76


def _hitchhiker_fish_outline() -> list:
    """The Babel fish in side view, a spline through its control points."""
    x0, y0, x1, y1 = _HITCHHIKER_FISH_RECT
    cx, cy = _hitchhiker_fish_centre()
    body = [(cx - 118, cy), (cx - 96, cy - 22), (cx - 50, cy - 36), (cx + 10, cy - 32), (cx + 70, cy - 18),
            (cx + 108, cy - 6), (cx + 132, cy - 28), (cx + 144, cy - 24), (cx + 130, cy), (cx + 144, cy + 24),
            (cx + 132, cy + 28), (cx + 108, cy + 6), (cx + 70, cy + 18), (cx + 10, cy + 32), (cx - 50, cy + 36),
            (cx - 96, cy + 22)]
    return _catmull_rom(body, closed=True, samples=6)


def _hitchhiker_paint_fish(image: Image.Image) -> None:
    """Figure 1: the Babel fish in cross-section under a CRT raster, its
    organs in the inks, five numbered callouts on leaders."""
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = _HITCHHIKER_FISH_RECT
    white, yellow, blue, green, red, black = (SPECTRA6[k] for k in ("white", "yellow", "blue", "green", "red", "black"))
    draw.rectangle((x0, y0, x1, y1), outline=blue, width=1)
    draw.text((x0 + 8, y0 + 6), "FIG. 1   BABEL FISH", font=_hitchhiker_font(10), fill=green)
    cx, cy = _hitchhiker_fish_centre()
    outline = [(round(x), round(y)) for x, y in _hitchhiker_fish_outline()]
    draw.polygon(outline, fill=yellow)
    _crt_paint_scanlines(image, (x0 + 1, y0 + 1, x1, y1), (yellow,), period=3, phase=1)
    draw = ImageDraw.Draw(image)
    draw.line(outline + [outline[0]], fill=white, width=1)
    # The organs.
    draw.ellipse((cx - 108, cy - 7, cx - 94, cy + 7), fill=black)                   # the eye
    draw.ellipse((cx - 104, cy - 5, cx - 99, cy), fill=white)
    for i in range(3):
        draw.arc((cx - 86 + i * 7, cy - 18, cx - 70 + i * 7, cy + 18), 300, 60, fill=red, width=2)   # the gills
    draw.ellipse((cx - 56, cy - 22, cx - 14, cy + 4), fill=blue, outline=white, width=1)          # the sensor
    draw.ellipse((cx - 44, cy - 14, cx - 30, cy - 4), outline=white, width=1)
    matrix = [(cx - 12 + i * 10, cy + (10 if i % 2 else 18)) for i in range(10)]                     # the matrix
    draw.line(matrix, fill=green, width=2)
    draw.line((cx - 14, cy - 8, cx + 110, cy - 2), fill=white, width=1)                              # the nerve
    for i in range(4):
        draw.line((cx + 20 + i * 24, cy - 6, cx + 26 + i * 24, cy - 14), fill=white, width=1)
    draw.polygon([(cx + 130, cy - 2), (cx + 152, cy - 10), (cx + 152, cy + 6)], fill=green)         # the outflow
    # Callouts: numbered discs on the organs, and the legend in two columns
    # under the rule.
    anchors = ((cx - 36, cy - 10), (cx + 30, cy + 14), (cx - 78, cy - 10), (cx + 70, cy - 4), (cx + 144, cy - 2))
    font = _hitchhiker_font(9)
    rule_y = y1 - 42
    draw.line((x0 + 8, rule_y, x1 - 8, rule_y), fill=blue, width=1)
    for i, ((n, label), (ax, ay)) in enumerate(zip(_HITCHHIKER_CALLOUTS, anchors)):
        tx = x0 + 8 + (0 if i < 3 else 150)
        ty = rule_y + 5 + (i % 3) * 12
        draw.ellipse((ax - 5, ay - 5, ax + 5, ay + 5), fill=black, outline=white, width=1)
        draw.text((ax - 2, ay - 6), n, font=font, fill=white)
        draw.text((tx, ty), f"{n} {label}", font=font, fill=white)


def _hitchhiker_sector_angle(hour: int) -> tuple[float, float]:
    """The hour's sector on the chart: thirty degrees, clockwise from the
    top, like a clock face."""
    start = math.radians((hour % 12) * 30 - 90 - 15)
    return start, start + math.radians(30)


def _hitchhiker_paint_galaxy(draw: ImageDraw.ImageDraw, hour: int) -> None:
    """Figure 2: the galaxy as a seeded two-armed spiral of stars in a boxed
    chart with twelve sector lines; the hour's sector outlined, the Earth
    ringed in it, and YOU ARE HERE on a leader."""
    x0, y0, x1, y1 = _HITCHHIKER_GALAXY_RECT
    white, yellow, blue = SPECTRA6["white"], SPECTRA6["yellow"], SPECTRA6["blue"]
    draw.rectangle((x0, y0, x1, y1), outline=blue, width=1)
    draw.text((x0 + 8, y0 + 6), "FIG. 2   SECTOR ZZ9 PLURAL Z ALPHA", font=_hitchhiker_font(9), fill=SPECTRA6["green"])
    cx, cy = _HITCHHIKER_GALAXY_CENTRE
    radius = _HITCHHIKER_GALAXY_RADIUS
    for h in range(12):
        a = math.radians(h * 30 - 90 - 15)
        draw.line((cx, cy, cx + (radius + 10) * math.cos(a), cy + (radius + 10) * math.sin(a)), fill=blue, width=1)
    draw.ellipse((cx - radius - 10, cy - radius - 10, cx + radius + 10, cy + radius + 10), outline=blue, width=1)
    rng = random.Random(_HITCHHIKER_SEED + 3)
    for arm in (0.0, math.pi):
        for i in range(140):
            t = i / 140.0
            a = arm + t * 2.6 * math.pi
            r = 4 + t * (radius - 4)
            jitter = rng.gauss(0, 3 + 6 * t)
            px = cx + r * math.cos(a) + jitter
            py = cy + r * math.sin(a) + rng.gauss(0, 3 + 6 * t)
            if math.hypot(px - cx, py - cy) > radius:
                continue
            draw.point((round(px), round(py)), fill=yellow if rng.random() < 0.25 else white)
    draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=white)
    a0, a1 = _hitchhiker_sector_angle(hour)
    wedge = [(cx, cy)] + [(cx + (radius + 10) * math.cos(a0 + (a1 - a0) * k / 8), cy + (radius + 10) * math.sin(a0 + (a1 - a0) * k / 8))
                          for k in range(9)]
    draw.line(wedge + [(cx, cy)], fill=yellow, width=2)
    am = (a0 + a1) / 2
    ex, ey = cx + (radius - 12) * math.cos(am), cy + (radius - 12) * math.sin(am)
    draw.ellipse((ex - 2, ey - 2, ex + 2, ey + 2), fill=blue)
    draw.ellipse((ex - 6, ey - 6, ex + 6, ey + 6), outline=yellow, width=1)
    # The leader runs to the chart's free right column, where the label lives.
    lx, ly = x1 - 112, y0 + 60
    draw.line((ex + 6 * math.cos(am), ey + 6 * math.sin(am), lx - 6, ly + 6), fill=yellow, width=1)
    draw.text((lx, ly), "YOU ARE", font=_hitchhiker_font(10), fill=yellow)
    draw.text((lx, ly + 14), "HERE", font=_hitchhiker_font(10), fill=yellow)
    draw.text((lx, ly + 40), "MOSTLY", font=_hitchhiker_font(9), fill=white)
    draw.text((lx, ly + 52), "HARMLESS", font=_hitchhiker_font(9), fill=white)


def render_hitchhiker_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A Guide entry on the quoted author with its two figures, the hour's
    sector marked (see the section comment above)."""
    hour = _clock_hour12(time_str)
    image = Image.new("RGB", (800, 480), SPECTRA6["black"])
    draw = ImageDraw.Draw(image)
    _hitchhiker_paint_masthead(draw)
    _hitchhiker_paint_entry(draw, quote_row)
    _hitchhiker_paint_quote(draw, _hitchhiker_layout(draw, quote_row), quote_row)
    _hitchhiker_paint_seealso(draw, quote_row)
    _hitchhiker_paint_fish(image)
    draw = ImageDraw.Draw(image)
    _hitchhiker_paint_galaxy(draw, hour)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("hitchhiker",), render=render_hitchhiker_frame)
