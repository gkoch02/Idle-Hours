"""The ``synoptic`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
from itertools import pairwise

from PIL import Image, ImageDraw

from .._paths import META_FONT_BOLD_CANDIDATES, SPACEMONO_BOLD
from ..fonts import load_font
from ..palette import SPECTRA6, pixel_access
from ..spec import BorderSpec

# ---------------------------------------------------------------------------
# synoptic — a meteorological surface analysis (issue #215).
#
# The weather chart of the navigation family (``firmament`` celestial atlas,
# ``astrarium`` instrument, ``cartograph`` terrestrial chart): a field laid
# over geography — nested isobars, pressure centres and front symbols.
#
# The occluded front is drawn purple on a real chart because it is a cold
# and a warm front merged, so the R+B 1:1 mix is semantically right here.
#
# The time rides the validity stamp, ``VALID 1630 LT`` — a real chart
# carries its observation time, so a number genuinely belongs.
#
# Shared literary layout plus this painter and a ``clear_rect`` knockout.
# Everything is drawn with ImageDraw primitives that PIL clips, so the
# ``/api/preview`` thumbnail path crops rather than raises.
# ---------------------------------------------------------------------------
# Pressure centres as (x, y, label, innermost radius) in 800x480 space, in
# opposite corners so the isobars sweep diagonally across the page.
_SYNOPTIC_CENTRES = (
    (74, 96, "H", 26),
    (716, 388, "L", 24),
)
_SYNOPTIC_RINGS = 5
_SYNOPTIC_RING_STEP = 26
_SYNOPTIC_BASE_PRESSURE = {"H": 1032, "L": 984}
_SYNOPTIC_ISOBAR_POINTS = 48
# Fronts as (kind, polyline). Kinds: "cold" (blue, triangles), "warm" (red,
# semicircles), "occluded" (purple, alternating). Hand-placed so the three
# sweep across the middle band without crossing the quote cartouche.
_SYNOPTIC_FRONTS = (
    ("cold", ((36, 74), (150, 46), (272, 60), (368, 30))),
    ("warm", ((470, 44), (566, 70), (664, 58), (768, 82))),
    ("occluded", ((44, 430), (170, 452), (300, 436), (410, 458))),
)
_SYNOPTIC_PIP_SPACING = 34
_SYNOPTIC_PIP_SIZE = 7
# Station plots as (x, y, wind barb angle in degrees, number of full barbs).
_SYNOPTIC_STATIONS = (
    (26, 240, 210, 2), (30, 340, 250, 3), (128, 442, 160, 1),
    (610, 118, 300, 2), (770, 210, 20, 3), (556, 452, 120, 1),
    (312, 30, 340, 2), (452, 464, 70, 1),
)
_SYNOPTIC_GRATICULE_STEP = 64


def _synoptic_isobar(cx: float, cy: float, radius: float, squash: float, seed: float) -> list[tuple[float, float]]:
    """One closed isobar as a polyline, gently deformed so it is not an ellipse.

    Two low-order harmonics on the radius make it smooth but irregular with
    no randomness, so the chart stays byte-deterministic.
    """
    points = []
    for i in range(_SYNOPTIC_ISOBAR_POINTS):
        angle = math.tau * i / _SYNOPTIC_ISOBAR_POINTS
        wobble = 1.0 + 0.10 * math.sin(2 * angle + seed) + 0.05 * math.sin(3 * angle - seed)
        r = radius * wobble
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle) * squash))
    points.append(points[0])
    return points


def _synoptic_paint_graticule(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    """Faint dotted lat/long grid — the geography the analysis is drawn over."""
    faint = SPECTRA6["blue"]
    for x in range(_SYNOPTIC_GRATICULE_STEP, width, _SYNOPTIC_GRATICULE_STEP):
        for y in range(0, height, 6):
            draw.point((x, y), fill=faint)
    for y in range(_SYNOPTIC_GRATICULE_STEP, height, _SYNOPTIC_GRATICULE_STEP):
        for x in range(0, width, 6):
            draw.point((x, y), fill=faint)


def _synoptic_paint_isobars(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    """Nested pressure contours around each centre, with pressure labels."""
    black = SPECTRA6["black"]
    label_font = load_font([SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=11)
    centre_font = load_font([SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=30)
    for index, (x800, y480, label, inner) in enumerate(_SYNOPTIC_CENTRES):
        cx = x800 * width / 800.0
        cy = y480 * height / 480.0
        step = _SYNOPTIC_BASE_PRESSURE[label]
        for ring in range(_SYNOPTIC_RINGS):
            radius = inner + ring * _SYNOPTIC_RING_STEP
            points = _synoptic_isobar(cx, cy, radius, 0.82, seed=index * 1.7 + ring * 0.4)
            draw.line([(int(px), int(py)) for px, py in points], fill=black, width=1)
            # Pressure figure riding the contour, the way a real chart breaks
            # the line to letter it. Outermost ring only, to avoid a thicket.
            if ring == _SYNOPTIC_RINGS - 1:
                value = step - 4 * ring if label == "H" else step + 4 * ring
                lx, ly = points[_SYNOPTIC_ISOBAR_POINTS // 8]
                draw.text((int(lx), int(ly)), str(value), font=label_font, fill=black, anchor="mm")
        draw.text((int(cx), int(cy)), label, font=centre_font,
                  fill=SPECTRA6["blue"] if label == "H" else SPECTRA6["red"], anchor="mm")


def _synoptic_front_pips(points, spacing):
    """Walk a polyline and yield (x, y, normal angle) every ``spacing`` px.

    Each pip needs the local direction as well as a position, hence the walk
    by arc length rather than over the vertices.
    """
    pips = []
    carry = spacing / 2.0
    for (x0, y0), (x1, y1) in pairwise(points):
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg < 1e-6:
            continue
        angle = math.atan2(y1 - y0, x1 - x0)
        travelled = carry
        while travelled <= seg:
            t = travelled / seg
            pips.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, angle))
            travelled += spacing
        carry = travelled - seg
    return pips


def _synoptic_paint_front(image, draw, kind, points, width, height):
    """One front: the line, then its symbol furniture.

    Cold gets triangles, warm semicircles, occluded alternates the two. The
    occluded line and pips are painted in an off-palette sentinel and
    bbox-post-passed to R+B purple, because ``ImageDraw`` has no per-pixel
    fill.
    """
    red, blue = SPECTRA6["red"], SPECTRA6["blue"]
    scaled = [(x * width / 800.0, y * height / 480.0) for x, y in points]
    sentinel = (7, 7, 7)
    ink = {"cold": blue, "warm": red, "occluded": sentinel}[kind]
    draw.line([(int(x), int(y)) for x, y in scaled], fill=ink, width=3, joint="curve")

    size = _SYNOPTIC_PIP_SIZE
    for index, (px, py, angle) in enumerate(_synoptic_front_pips(scaled, _SYNOPTIC_PIP_SPACING)):
        if kind == "occluded":
            shape = "triangle" if index % 2 == 0 else "semicircle"
        else:
            shape = "triangle" if kind == "cold" else "semicircle"
        # Normal to the left of travel, the symbol side for these west-to-east
        # fronts.
        nx, ny = math.sin(angle), -math.cos(angle)
        if shape == "triangle":
            tip = (px + nx * size * 1.6, py + ny * size * 1.6)
            back = (math.cos(angle) * size, math.sin(angle) * size)
            draw.polygon([(int(tip[0]), int(tip[1])),
                          (int(px - back[0]), int(py - back[1])),
                          (int(px + back[0]), int(py + back[1]))], fill=ink)
        else:
            box = (int(px - size), int(py - size), int(px + size), int(py + size))
            start = math.degrees(angle) + 180
            draw.pieslice(box, start, start + 180, fill=ink)
    if kind == "occluded":
        _synoptic_resolve_occluded(image, scaled, size)


def _synoptic_resolve_occluded(image, scaled, size) -> None:
    """Flip the occluded front's sentinel ink to the R+B 1:1 purple.

    Scoped to the front's own bounding box so it cannot touch the isobars or
    the graticule, and keyed on the sentinel colour so it is idempotent.
    """
    width, height = image.size
    px = pixel_access(image)
    red, blue = SPECTRA6["red"], SPECTRA6["blue"]
    xs = [x for x, _ in scaled]
    ys = [y for _, y in scaled]
    pad = size * 3
    x0 = max(0, int(min(xs) - pad))
    x1 = min(width, int(max(xs) + pad) + 1)
    y0 = max(0, int(min(ys) - pad))
    y1 = min(height, int(max(ys) + pad) + 1)
    for y in range(y0, y1):
        for x in range(x0, x1):
            if px[x, y] == (7, 7, 7):
                px[x, y] = red if (x + y) & 1 else blue


def _synoptic_paint_stations(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    """Station model plots — circle plus a wind barb with feathers.

    Instantly legible as "weather chart" even to a reader who cannot decode
    one.
    """
    black = SPECTRA6["black"]
    for sx, sy, bearing, barbs in _SYNOPTIC_STATIONS:
        cx = sx * width / 800.0
        cy = sy * height / 480.0
        draw.ellipse((int(cx - 5), int(cy - 5), int(cx + 5), int(cy + 5)), outline=black, width=2)
        angle = math.radians(bearing)
        shaft = 26
        ex, ey = cx + math.cos(angle) * shaft, cy + math.sin(angle) * shaft
        draw.line((int(cx), int(cy), int(ex), int(ey)), fill=black, width=2)
        # Feathers hang off the far end, perpendicular-ish to the shaft.
        for i in range(barbs):
            t = 1.0 - i * 0.22
            bx, by = cx + math.cos(angle) * shaft * t, cy + math.sin(angle) * shaft * t
            fx = bx + math.cos(angle + 2.2) * 9
            fy = by + math.sin(angle + 2.2) * 9
            draw.line((int(bx), int(by), int(fx), int(fy)), fill=black, width=2)


def _synoptic_paint_stamp(draw: ImageDraw.ImageDraw, width: int, height: int, time_str: str) -> None:
    """``VALID HHMM LT`` — the chart's observation time, and the clock.

    Labelled **LT** (local time), not the UTC a real analysis uses, because
    the clock renders naive local wall time and ``VALID 1230 UTC`` would be a
    false claim. Converting to UTC would make the theme's time carrier
    disagree with the quote; reading the host's zone abbreviation would make
    the frame (and its golden fixture) machine-dependent — the
    ``CLOCK_DEPENDENT_THEMES`` hazard.
    """
    black, red = SPECTRA6["black"], SPECTRA6["red"]
    digits = (time_str or "").replace(":", "")[:4] or "0000"
    font = load_font([SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=13)
    text = f"VALID {digits} LT"
    box = draw.textbbox((0, 0), text, font=font)
    pad = 6
    w, h = box[2] - box[0], box[3] - box[1]
    x1, y1 = width - 16, height - 14
    x0, y0 = x1 - w - 2 * pad, y1 - h - 2 * pad
    if x0 < 0 or y0 < 0:
        return
    draw.rectangle((x0, y0, x1, y1), fill=SPECTRA6["white"], outline=black, width=1)
    draw.text((x0 + pad - box[0], y0 + pad - box[1]), text, font=font, fill=red)


def draw_synoptic_border(image: Image.Image, colors: dict, clear_rect=None, time_str: str | None = None) -> None:
    """Surface analysis behind the quote (see the section comment above).

    ``time_str`` is optional because only ``render``'s knockout pass passes it
    (the spec sets ``wants_time``). The plain pass, which is all the button-C
    source card makes, gets a chart with no validity stamp, which is correct
    for a source card.
    """
    width, height = image.size
    draw = ImageDraw.Draw(image)
    _synoptic_paint_graticule(draw, width, height)
    _synoptic_paint_isobars(draw, width, height)
    for kind, points in _SYNOPTIC_FRONTS:
        _synoptic_paint_front(image, draw, kind, points, width, height)
    _synoptic_paint_stations(draw, width, height)
    if time_str:
        _synoptic_paint_stamp(draw, width, height, time_str)
    if clear_rect is not None:
        # The quote sits in a chart-legend box.
        x0, y0, x1, y1 = clear_rect
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(width - 1, x1)
        y1 = min(height - 1, y1)
        if x1 > x0 and y1 > y0:
            draw.rectangle((x0, y0, x1, y1), fill=colors.get("page_bg", SPECTRA6["white"]))
            draw.rectangle((x0, y0, x1, y1), outline=SPECTRA6["black"], width=2)
            draw.line((x0 + 8, y0 + 8, x1 - 8, y0 + 8), fill=SPECTRA6["blue"], width=1)
            draw.line((x0 + 8, y1 - 8, x1 - 8, y1 - 8), fill=SPECTRA6["blue"], width=1)


SPEC = BorderSpec(
    themes=("synoptic",),
    paint=draw_synoptic_border,
    # The analysis paints graticule, isobars, fronts and station plots in
    # one pass, then boxes the quote as a chart legend: a 2 px black frame
    # with blue rules inset 8 px, so the pad has to clear both. It takes
    # the time for the validity stamp; the source card's plain paint gets
    # no stamp, which is right, since a card is not an analysis.
    clear_rect_pad=(20, 14, 14),
    wants_time=True,
)
