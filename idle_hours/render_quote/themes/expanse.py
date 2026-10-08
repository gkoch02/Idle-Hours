"""The ``expanse`` theme: the Rocinante's console from *The Expanse*, the quote an incoming tightbeam.

Design notes: docs/themes.md § expanse
"""

from __future__ import annotations

import math
import random
from itertools import pairwise

from PIL import Image, ImageDraw

from .._paths import (
    BARLOW_BOLD,
    BARLOW_MEDIUM,
    BARLOW_SEMIBOLD,
    BARLOWCOND_BOLD,
    BARLOWCOND_MEDIUM,
    BARLOWCOND_SEMIBOLD,
    META_FONT_BOLD_CANDIDATES,
    META_FONT_CANDIDATES,
    SHARETECHMONO_REGULAR,
    SPACEMONO_REGULAR,
)
from ..fonts import _font_ascent, load_font, normalize_dashes
from ..furniture import _clock_hour12, _row_digest, fallback_title
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, pixel_access, snap_image_to_palette
from ..primitives import _fill_swatch_stipple, paint_neon_mask
from ..spec import FrameSpec
from ..text import draw_text_dithered, draw_tracked, fit_text_to_width, tracked_width

_EXPANSE_SEED = 0x524F4349            # ROCI
_EXPANSE_GRID_PITCH = 23              # coprime with the 4x4 / 8x8 Bayer tiles
_EXPANSE_TAG_RECT = (24, 8, 150, 54)
_EXPANSE_ORBIT_RECT = (164, 8, 776, 54)
_EXPANSE_ORBIT_STATIONS = ("LUNA", "MARS", "CERES", "TYCHO", "GANYMEDE", "SATURN")
_EXPANSE_PLOT_RECT = (24, 64, 232, 392)
_EXPANSE_PLOT_CENTRE = (128, 196)
_EXPANSE_PLOT_RINGS = (28, 56, 84)
_EXPANSE_CONTACT_RADIUS = 70
_EXPANSE_STATIC_CONTACTS = ((40, 215), (38, 318))   # (radius, bearing) of the unknowns
_EXPANSE_ARC_GAUGE_Y = 340
_EXPANSE_ARC_GAUGE_XS = (56, 104, 152, 200)
_EXPANSE_ARC_GAUGE_R = 15
_EXPANSE_ARC_GAUGES = ("RCS", "PWR", "O2", "TMP")
_EXPANSE_FEED_RECT = (244, 64, 652, 392)
_EXPANSE_HEADER_H = 24
_EXPANSE_SENDER_Y = 98
_EXPANSE_QUOTE_RECT = (268, 134, 628, 324)
_EXPANSE_FRAME_RECT = (258, 126, 638, 332)         # the feed's own thin frame round the quote
_EXPANSE_SOURCE_Y = 344
_EXPANSE_PROMPT_Y = 370
_EXPANSE_LIST_RECT = (664, 64, 776, 392)
_EXPANSE_LIST_ROW_Y = 96
_EXPANSE_LIST_ROW_H = 46
_EXPANSE_LIST_ROWS = ("ROCINANTE", "CONTACT", "UNK 01", "UNK 02")
_EXPANSE_SCATTER_RECT = (676, 290, 764, 360)
_EXPANSE_FOOT_RECT = (24, 402, 776, 472)
_EXPANSE_PILL_ROWS = ("PDC", "TORP", "RCS", "EPS")
_EXPANSE_CHART_RECT = (236, 414, 556, 462)
_EXPANSE_SYSTEXT_X = 574
_EXPANSE_CHAMFER = 12
_EXPANSE_SCENE: dict = {}


def _expanse_bearing(hour: int) -> int:
    """The contact's bearing in degrees clockwise from north: twelve is 000."""
    return (hour % 12) * 30


def _expanse_polar(radius: float, bearing_deg: float) -> tuple[float, float]:
    """A point on the plot at ``radius`` and a bearing clockwise from north."""
    cx, cy = _EXPANSE_PLOT_CENTRE
    a = math.radians(bearing_deg)
    return cx + radius * math.sin(a), cy - radius * math.cos(a)


def _expanse_label_font(size: int):
    """Barlow Condensed Medium — the tracked DIN-style labels."""
    return load_font([BARLOWCOND_MEDIUM, BARLOW_MEDIUM, *META_FONT_CANDIDATES], size=size)


def _expanse_label_bold_font(size: int):
    """Barlow Condensed SemiBold — the module headers."""
    return load_font([BARLOWCOND_SEMIBOLD, BARLOW_SEMIBOLD, *META_FONT_BOLD_CANDIDATES], size=size)


def _expanse_mono_font(size: int):
    """Share Tech Mono — the readouts, the system text and the command line."""
    return load_font([SHARETECHMONO_REGULAR, SPACEMONO_REGULAR, *META_FONT_CANDIDATES], size=size)


def _expanse_chamfered(rect, cut: int, corners=("tr", "bl")) -> list:
    """A rectangle's outline, clockwise from the top left, with the named
    corners cut at 45 degrees — the console's panel shape."""
    x0, y0, x1, y1 = rect
    pts: list = []
    pts += [(x0, y0 + cut), (x0 + cut, y0)] if "tl" in corners else [(x0, y0)]
    pts += [(x1 - cut, y0), (x1, y0 + cut)] if "tr" in corners else [(x1, y0)]
    pts += [(x1, y1 - cut), (x1 - cut, y1)] if "br" in corners else [(x1, y1)]
    pts += [(x0 + cut, y1), (x0, y1 - cut)] if "bl" in corners else [(x0, y1)]
    return pts


def _expanse_paint_bracket(draw: ImageDraw.ImageDraw, x: int, y: int, dx: int, dy: int, ink, length: int = 14,
                           width: int = 2) -> None:
    """An L-shaped corner bracket at ``(x, y)`` opening toward ``(dx, dy)``."""
    draw.line([(x, y), (x + dx * length, y)], fill=ink, width=width)
    draw.line([(x, y), (x, y + dy * length)], fill=ink, width=width)


def _expanse_paint_brackets(draw: ImageDraw.ImageDraw, rect, ink, length: int = 10, width: int = 1) -> None:
    """Brackets on all four corners of ``rect`` — the feed's frame."""
    x0, y0, x1, y1 = rect
    for cx, cy, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x1, y1, -1, -1), (x0, y1, 1, -1)):
        _expanse_paint_bracket(draw, cx, cy, dx, dy, ink, length=length, width=width)


def _expanse_dashed(draw: ImageDraw.ImageDraw, points: list, ink, on: int = 6, off: int = 5, width: int = 1) -> None:
    """A polyline drawn as dashes, the dash phase carried across vertices."""
    run, lit = 0.0, True
    for (ax, ay), (bx, by) in pairwise(points):
        seg = math.hypot(bx - ax, by - ay)
        t = 0.0
        while t < seg:
            step = min(seg - t, (on if lit else off) - run)
            if lit:
                draw.line([(ax + (bx - ax) * t / seg, ay + (by - ay) * t / seg),
                           (ax + (bx - ax) * (t + step) / seg, ay + (by - ay) * (t + step) / seg)],
                          fill=ink, width=width)
            t += step
            run += step
            if run >= (on if lit else off) - 1e-6:
                run, lit = 0.0, not lit


def _expanse_dotted_rule(px, x0: int, x1: int, y: int, ink, pitch: int = 3) -> None:
    """A dotted horizontal leader — the baseline under every readout."""
    for x in range(x0, x1, pitch):
        px[x, y] = ink


def _expanse_paint_amber_rect(image: Image.Image, rect) -> None:
    """The MCRN orange as a block: red + yellow at 1/2 : 1/2."""
    _fill_swatch_stipple(image, rect, SPECTRA6["red"], SPECTRA6["yellow"], 0.5)


def _expanse_paint_cyan_rect(image: Image.Image, rect) -> None:
    """The console's cyan as a block: blue + white at 1/2 : 1/2."""
    _fill_swatch_stipple(image, rect, SPECTRA6["blue"], SPECTRA6["white"], 0.5)


def _expanse_paint_pill(image: Image.Image, draw: ImageDraw.ImageDraw, rect, ink: str) -> None:
    """A status pill: a small rounded cell filled solid (green / red /
    white), stippled amber, or left as a blue hairline when dark."""
    x0, y0, x1, y1 = rect
    if ink == "amber":
        draw.rounded_rectangle(rect, radius=2, fill=SPECTRA6["black"])
        _expanse_paint_amber_rect(image, (x0 + 1, y0 + 1, x1, y1))
    elif ink == "dark":
        draw.rounded_rectangle(rect, radius=2, outline=SPECTRA6["blue"], width=1)
    else:
        draw.rounded_rectangle(rect, radius=2, fill=SPECTRA6[ink])


def _expanse_paint_systext(draw: ImageDraw.ImageDraw, x: int, y: int, lines, ink=None, size: int = 9) -> int:
    """A few lines of the console's ``//`` system text in the mono — the
    under-the-hood register every module on the Roci carries. Returns the
    y below the block."""
    font = _expanse_mono_font(size)
    for line in lines:
        draw.text((x, y), line, font=font, fill=ink or SPECTRA6["white"])
        y += size + 3
    return y


def _expanse_paint_ground(image: Image.Image) -> None:
    """Black glass with a sparse blue dot grid, so the panels sit on a
    surface rather than in a void."""
    px = pixel_access(image)
    blue = SPECTRA6["blue"]
    w, h = image.size
    for y in range(6, h, _EXPANSE_GRID_PITCH):
        for x in range(6, w, _EXPANSE_GRID_PITCH):
            px[x, y] = blue


def _expanse_paint_tag(image: Image.Image) -> None:
    """The ship's tag at the top left: the service as an orange block, the
    name beneath it, the class under that."""
    draw = ImageDraw.Draw(image)
    black, white = SPECTRA6["black"], SPECTRA6["white"]
    x0, y0, x1, y1 = _EXPANSE_TAG_RECT
    draw.rectangle((x0, y0, x0 + 46, y0 + 16), fill=black)
    _expanse_paint_amber_rect(image, (x0, y0, x0 + 46, y0 + 16))
    tag = _expanse_label_bold_font(12)
    draw_tracked(draw, (x0 + (46 - tracked_width(draw, "MCRN", tag, tracking=2)) / 2, y0 + 2), "MCRN", tag, black, tracking=2)
    name = load_font([BARLOW_SEMIBOLD, BARLOWCOND_SEMIBOLD, *META_FONT_BOLD_CANDIDATES], size=15)
    draw_tracked(draw, (x0, y0 + 20), "ROCINANTE", name, white, tracking=2)
    draw_tracked(draw, (x0, y0 + 38), "CORVETTE-CLASS", _expanse_label_font(10), white, tracking=2)
    draw.line([(x1, y0), (x1, y1)], fill=SPECTRA6["blue"], width=1)


def _expanse_paint_orbit(image: Image.Image) -> None:
    """The system plot across the top: the stations as column heads over
    vertical rules, two trajectories curving through them, a banded gas
    giant, a ringed one and a moon."""
    draw = ImageDraw.Draw(image)
    px = pixel_access(image)
    white, blue, yellow, red = SPECTRA6["white"], SPECTRA6["blue"], SPECTRA6["yellow"], SPECTRA6["red"]
    x0, y0, x1, y1 = _EXPANSE_ORBIT_RECT
    draw.line([(x0, y1), (x1, y1)], fill=blue, width=1)
    _expanse_dotted_rule(px, x0, x1, y0, blue, pitch=2)
    n = len(_EXPANSE_ORBIT_STATIONS)
    pitch = (x1 - x0) / n
    font = _expanse_label_font(10)
    for k, station in enumerate(_EXPANSE_ORBIT_STATIONS):
        sx = int(x0 + k * pitch)
        draw.line([(sx, y0 + 2), (sx, y1 - 2)], fill=blue, width=1)
        draw_tracked(draw, (sx + 5, y0 + 2), station, font, white, tracking=1)

    def bezier(p0, p1, p2, steps: int = 60) -> list:
        return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                 (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])
                for t in (i / steps for i in range(steps + 1))]

    _expanse_dashed(draw, bezier((x0 + 6, y1 - 6), (x0 + 300, y0 + 2), (x1 - 8, y1 - 16)), blue, on=5, off=4)
    draw.line(bezier((x0 + 30, y0 + 10), (x0 + 330, y1 + 10), (x1 - 40, y0 + 12)), fill=yellow, width=1)
    # A banded gas giant at Ganymede's column, with the Roci's ship marker beside it.
    gx, gy, gr = int(x0 + 4.5 * pitch), y0 + 28, 11
    disc = Image.new("L", image.size, 0)
    ImageDraw.Draw(disc).ellipse((gx - gr, gy - gr, gx + gr, gy + gr), fill=255)
    _expanse_paint_stipple_masked(image, disc, SPECTRA6["red"], SPECTRA6["yellow"])
    disc.close()
    for band in (-6, -2, 3, 7):
        draw.line([(gx - gr + 2, gy + band), (gx + gr - 2, gy + band)], fill=red, width=1)
    draw.polygon([(gx + gr + 10, gy - 4), (gx + gr + 16, gy), (gx + gr + 10, gy + 4)], fill=white)
    # A ringed planet at Saturn's column.
    sx, sy, sr = int(x0 + 5.5 * pitch), y0 + 24, 6
    draw.ellipse((sx - sr, sy - sr, sx + sr, sy + sr), fill=white)
    draw.ellipse((sx - 13, sy - 4, sx + 13, sy + 4), outline=yellow, width=1)
    draw.ellipse((sx - sr, sy - sr, sx + sr, sy + sr), outline=white, width=1)
    # A moon at Mars's column, and Ceres as a fleck.
    mx, my = int(x0 + 1.5 * pitch), y1 - 14
    draw.ellipse((mx - 3, my - 3, mx + 3, my + 3), fill=white)
    draw.rectangle((int(x0 + 2.5 * pitch), y0 + 22, int(x0 + 2.5 * pitch) + 1, y0 + 23), fill=white)


def _expanse_paint_panel(image: Image.Image, rect, title: str, *, corners=("tr", "bl"), header: bool = True,
                         sub: str = "") -> None:
    """A console panel: black glass in a chamfered blue hairline, yellow
    brackets on the square corners, and a header strip with its title and
    an optional subtitle at the right."""
    draw = ImageDraw.Draw(image)
    black, blue, yellow, white = SPECTRA6["black"], SPECTRA6["blue"], SPECTRA6["yellow"], SPECTRA6["white"]
    x0, y0, x1, y1 = rect
    outline = _expanse_chamfered(rect, _EXPANSE_CHAMFER, corners)
    draw.polygon(outline, fill=black)
    draw.line(outline + [outline[0]], fill=blue, width=1)
    for cx, cy, dx, dy, name in ((x0, y0, 1, 1, "tl"), (x1, y0, -1, 1, "tr"), (x1, y1, -1, -1, "br"), (x0, y1, 1, -1, "bl")):
        if name not in corners:
            _expanse_paint_bracket(draw, cx, cy, dx, dy, yellow)
    if header:
        hy = y0 + _EXPANSE_HEADER_H
        draw.line([(x0, hy), (x1, hy)], fill=blue, width=1)
        font = _expanse_label_bold_font(13)
        _expanse_paint_amber_rect(image, (x0 + 1, y0 + 1, x0 + 8, hy - 1))
        draw_tracked(draw, (x0 + 16, y0 + 6), title, font, white, tracking=3)
        if sub:
            draw_tracked(draw, (x1 - 10, y0 + 7), sub, _expanse_label_font(11), white, tracking=2, anchor_right=True)


def _expanse_paint_plot(image: Image.Image) -> None:
    """The tactical plot: range rings as arcs gapped at the cardinals,
    bearing ticks, a gapped crosshair, the Roci as a white chevron at the
    centre, two unknowns as hollow blue triangles, a tick ruler down the
    panel's left edge, and the rings of the four arc gauges beneath."""
    draw = ImageDraw.Draw(image)
    px = pixel_access(image)
    blue, white = SPECTRA6["blue"], SPECTRA6["white"]
    cx, cy = _EXPANSE_PLOT_CENTRE
    for r in _EXPANSE_PLOT_RINGS:
        for quadrant in range(4):
            start = quadrant * 90 - 90 + 5
            draw.arc((cx - r, cy - r, cx + r, cy + r), start, start + 80, fill=blue, width=1)
    outer = _EXPANSE_PLOT_RINGS[-1]
    for k in range(36):
        length = 6 if k % 3 == 0 else 3
        (ax, ay), (bx, by) = _expanse_polar(outer + 2, k * 10), _expanse_polar(outer + 2 + length, k * 10)
        draw.line([(ax, ay), (bx, by)], fill=blue if k % 3 else white, width=1)
    font = _expanse_mono_font(10)
    for bearing, text in ((0, "000"), (90, "090"), (180, "180"), (270, "270")):
        tx, ty = _expanse_polar(outer + 15, bearing)
        draw.text((tx, ty), text, font=font, fill=white, anchor="mm")
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        draw.line([(cx + dx * 8, cy + dy * 8), (cx + dx * (outer - 6), cy + dy * (outer - 6))], fill=blue, width=1)
    draw.polygon([(cx, cy - 6), (cx + 5, cy + 5), (cx, cy + 2), (cx - 5, cy + 5)], fill=white)
    for radius, bearing in _EXPANSE_STATIC_CONTACTS:
        px_, py_ = _expanse_polar(radius, bearing)
        draw.polygon([(px_, py_ - 5), (px_ + 5, py_ + 4), (px_ - 5, py_ + 4)], outline=blue, width=1)
    x0, y0, x1, y1 = _EXPANSE_PLOT_RECT
    # The ruler down the left edge, inside the frame.
    for y in range(y0 + _EXPANSE_HEADER_H + 8, _EXPANSE_ARC_GAUGE_Y - 30, 6):
        tick = 5 if (y - y0) % 30 == 2 else 2
        draw.line([(x0 + 3, y), (x0 + 3 + tick, y)], fill=blue if tick == 2 else white, width=1)
    # The arc gauges' outer rings and labels; the sweeps are the quote's.
    r = _EXPANSE_ARC_GAUGE_R
    _expanse_dotted_rule(px, x0 + 10, x1 - 10, _EXPANSE_ARC_GAUGE_Y - r - 10, blue)
    label = _expanse_label_font(9)
    for gx, name in zip(_EXPANSE_ARC_GAUGE_XS, _EXPANSE_ARC_GAUGES, strict=True):
        gy = _EXPANSE_ARC_GAUGE_Y
        draw.arc((gx - r, gy - r, gx + r, gy + r), 135, 405, fill=blue, width=1)
        draw.arc((gx - r + 9, gy - r + 9, gx + r - 9, gy + r - 9), 135, 405, fill=blue, width=1)
        draw_tracked(draw, (gx - tracked_width(draw, name, label, tracking=1) / 2, gy + r + 3), name, label, white, tracking=1)


def _expanse_paint_list(image: Image.Image) -> None:
    """The contacts list: boxed rows with a silhouette and a name, and a
    drive scatter box beneath with its system text."""
    draw = ImageDraw.Draw(image)
    px = pixel_access(image)
    white, blue, yellow = SPECTRA6["white"], SPECTRA6["blue"], SPECTRA6["yellow"]
    x0, y0, x1, y1 = _EXPANSE_LIST_RECT
    font = _expanse_label_font(10)
    for k, name in enumerate(_EXPANSE_LIST_ROWS):
        ry = _EXPANSE_LIST_ROW_Y + k * _EXPANSE_LIST_ROW_H
        draw.rectangle((x0 + 8, ry, x1 - 8, ry + _EXPANSE_LIST_ROW_H - 8), outline=blue, width=1)
        sx, sy = x0 + 22, ry + 14
        if k == 0:       # the Roci: a corvette, nose right
            draw.polygon([(sx - 10, sy - 3), (sx + 4, sy - 3), (sx + 11, sy), (sx + 4, sy + 3), (sx - 10, sy + 3)], fill=white)
            draw.rectangle((sx - 8, sy - 6, sx - 4, sy + 6), fill=white)
        elif k == 1:     # the contact: a diamond, orange
            glyph = Image.new("L", image.size, 0)
            ImageDraw.Draw(glyph).polygon([(sx, sy - 7), (sx + 9, sy), (sx, sy + 7), (sx - 9, sy)], fill=255)
            _expanse_paint_stipple_masked(image, glyph, SPECTRA6["red"], SPECTRA6["yellow"])
            glyph.close()
        else:            # unknowns: hollow triangles
            draw.polygon([(sx, sy - 7), (sx + 7, sy + 5), (sx - 7, sy + 5)], outline=blue, width=1)
        draw_tracked(draw, (x0 + 40, ry + 6), name, font, white, tracking=1)
        _expanse_dotted_rule(px, x0 + 40, x1 - 14, ry + 21, blue)
    # The drive scatter box: a square with a crosshair and a seeded scatter.
    sx0, sy0, sx1, sy1 = _EXPANSE_SCATTER_RECT
    draw.rectangle(_EXPANSE_SCATTER_RECT, outline=blue, width=1)
    _expanse_paint_brackets(draw, (sx0 - 3, sy0 - 3, sx1 + 3, sy1 + 3), white, length=6)
    mx, my = (sx0 + sx1) // 2, (sy0 + sy1) // 2
    draw.line([(mx, sy0 + 4), (mx, sy1 - 4)], fill=blue, width=1)
    draw.line([(sx0 + 4, my), (sx1 - 4, my)], fill=blue, width=1)
    rng = random.Random(_EXPANSE_SEED + 4)
    for _ in range(26):
        dx, dy = rng.gauss(0, 12), rng.gauss(0, 9)
        x, y = int(mx + dx), int(my + dy)
        if sx0 + 3 < x < sx1 - 3 and sy0 + 3 < y < sy1 - 3:
            px[x, y] = white
            if rng.random() < 0.3:
                px[x + 1, y] = white
    draw.ellipse((mx - 3, my - 3, mx + 3, my + 3), outline=yellow, width=1)
    draw_tracked(draw, (x0 + 12, y1 - 24), "DRIVE 01", _expanse_label_bold_font(10), white, tracking=1)
    w = draw_tracked(draw, (x1 - 12, y1 - 23), "OPTIMAL", _expanse_label_font(9), white, tracking=1, anchor_right=True)
    draw.rounded_rectangle((x1 - 12 - w - 14, y1 - 22, x1 - 12 - w - 6, y1 - 16), radius=2, fill=SPECTRA6["green"])


def _expanse_paint_foot(image: Image.Image) -> None:
    """The readout strip's chrome: the pill-grid row labels, the chart's
    frame and dotted baseline, and the system text block."""
    _expanse_paint_panel(image, _EXPANSE_FOOT_RECT, "", corners=("tl", "br"), header=False)
    draw = ImageDraw.Draw(image)
    px = pixel_access(image)
    blue, white = SPECTRA6["blue"], SPECTRA6["white"]
    x0, y0, x1, y1 = _EXPANSE_FOOT_RECT
    label = _expanse_label_font(9)
    for k, name in enumerate(_EXPANSE_PILL_ROWS):
        draw_tracked(draw, (x0 + 34, y0 + 9 + k * 13), name, label, white, tracking=1)
    draw.line([(x0 + 200, y0 + 10), (x0 + 200, y1 - 10)], fill=blue, width=1)
    cx0, cy0, cx1, cy1 = _EXPANSE_CHART_RECT
    draw_tracked(draw, (cx0, cy0 - 2), "DSR", _expanse_label_bold_font(9), white, tracking=1)
    _expanse_dotted_rule(px, cx0 + 24, cx1, cy1 - 1, blue)
    _expanse_dotted_rule(px, cx0 + 24, cx1, cy0 + (cy1 - cy0) // 2, blue, pitch=5)
    for k in range(0, cx1 - cx0 - 24, 30):
        draw.line([(cx0 + 24 + k, cy1), (cx0 + 24 + k, cy1 + 3)], fill=blue, width=1)
    draw.line([(cx1 + 12, y0 + 10), (cx1 + 12, y1 - 10)], fill=blue, width=1)
    _expanse_paint_systext(draw, _EXPANSE_SYSTEXT_X, y0 + 8, (
        "// REX MASTER LOAD CONTROL",
        "PROG. GENERATOR <01> // PROC. RLF001",
        "// WAIT  RUN 03  MASTER LOADED <04>",
    ))


def _expanse_scene() -> Image.Image:
    """The console without its transmission: ground, tag, orbital strip,
    the three panels, the plot, the list and the readout strip. Painted
    once per process."""
    key = (_expanse_paint_ground, _expanse_paint_tag, _expanse_paint_orbit, _expanse_paint_panel,
           _expanse_paint_plot, _expanse_paint_list, _expanse_paint_foot)
    cached = _EXPANSE_SCENE.get("frame")
    if cached is not None and cached[0] == key:
        return cached[1]
    image = Image.new("RGB", (800, 480), SPECTRA6["black"])
    _expanse_paint_ground(image)
    _expanse_paint_tag(image)
    _expanse_paint_orbit(image)
    _expanse_paint_panel(image, _EXPANSE_PLOT_RECT, "TACTICAL", sub="RNG 500")
    _expanse_paint_plot(image)
    _expanse_paint_panel(image, _EXPANSE_FEED_RECT, "COMMS", sub="TIGHTBEAM · ENCRYPTED")
    _expanse_paint_panel(image, _EXPANSE_LIST_RECT, "CONTACTS")
    _expanse_paint_list(image)
    draw = ImageDraw.Draw(image)
    px = pixel_access(image)
    x0, y0, x1, _ = _EXPANSE_FEED_RECT
    draw_tracked(draw, (x0 + 84, y0 + 7), "FEED 01 · INCOMING", _expanse_label_font(11), SPECTRA6["white"], tracking=2)
    draw_tracked(draw, (x0 + 14, _EXPANSE_SENDER_Y + 7), "FROM", _expanse_label_font(10), SPECTRA6["white"], tracking=2)
    draw.rectangle(_EXPANSE_FRAME_RECT, outline=SPECTRA6["blue"], width=1)
    fx0, fy0, fx1, fy1 = _EXPANSE_FRAME_RECT
    _expanse_paint_brackets(draw, (fx0 - 3, fy0 - 3, fx1 + 3, fy1 + 3), SPECTRA6["white"], length=9)
    for k in range(fx0 + 20, fx1 - 10, 20):
        draw.line([(k, fy1 - 4), (k, fy1 - 1)], fill=SPECTRA6["blue"], width=1)
    draw_tracked(draw, (x0 + 14, _EXPANSE_SOURCE_Y + 2), "SRC", _expanse_label_font(10), SPECTRA6["white"], tracking=2)
    draw_tracked(draw, (x1 - 128, _EXPANSE_SOURCE_Y + 2), "SIG", _expanse_label_font(10), SPECTRA6["white"], tracking=2)
    _expanse_dotted_rule(px, x0 + 14, x1 - 14, _EXPANSE_SOURCE_Y + 16, SPECTRA6["blue"])
    _expanse_paint_foot(image)
    _EXPANSE_SCENE["frame"] = (key, image)
    return image


def _expanse_paint_contact(image: Image.Image, hour: int) -> None:
    """The tracked contact at the hour's bearing: its track arced through
    it in blue, the intercept dashed in orange from the Roci, an orange
    diamond in brackets with a white core and an amber bloom, and the
    bearing in the contact's row of the list."""
    draw = ImageDraw.Draw(image)
    black, white, blue, yellow, red = (SPECTRA6["black"], SPECTRA6["white"], SPECTRA6["blue"],
                                       SPECTRA6["yellow"], SPECTRA6["red"])
    bearing = _expanse_bearing(hour)
    r = _EXPANSE_CONTACT_RADIUS
    # A flyby: the track passes through the contact and bows outward at both ends.
    track = [_expanse_polar(r + 12 * ((a - bearing) / 48) ** 2, a) for a in range(bearing - 48, bearing + 49, 4)]
    _expanse_dashed(draw, track, blue, on=7, off=5)
    tx, ty = _expanse_polar(r, bearing)
    _expanse_dashed(draw, [_EXPANSE_PLOT_CENTRE, (tx, ty)], yellow, on=4, off=4)
    glow = Image.new("L", image.size, 0)
    ImageDraw.Draw(glow).polygon([(tx, ty - 6), (tx + 6, ty), (tx, ty + 6), (tx - 6, ty)], fill=255)
    paint_neon_mask(image, glow, yellow, yellow, radius=7, gamma=1.6, cap=0.55, tile=BAYER_8x8,
                    glow_minor=red, glow_minor_share=0.4, ground=frozenset({black, blue}))
    glow.close()
    draw.polygon([(tx, ty - 3), (tx + 3, ty), (tx, ty + 3), (tx - 3, ty)], fill=white)
    for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        _expanse_paint_bracket(draw, int(tx + sx * 11), int(ty + sy * 11), -sx, -sy, yellow, length=5, width=1)
    x0, _, x1, _ = _EXPANSE_LIST_RECT
    ry = _EXPANSE_LIST_ROW_Y + _EXPANSE_LIST_ROW_H
    draw.text((x0 + 40, ry + 24), f"BRG {bearing:03d}", font=_expanse_mono_font(11), fill=yellow)


def _expanse_paint_sender(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The sender — the author, or the book when there is none — in Barlow
    Bold capitals, the MCRN orange."""
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "")
    name = (author or title or "UNKNOWN STATION").upper()
    x0, _, x1, _ = _EXPANSE_FEED_RECT
    font, text = fit_text_to_width(draw, name, [BARLOW_BOLD, BARLOWCOND_BOLD, *META_FONT_BOLD_CANDIDATES],
                                   20, x1 - x0 - 90, floor=15, tracking=2)
    x = float(x0 + 52)
    for ch in text:
        draw_text_dithered(image, (int(round(x)), _EXPANSE_SENDER_Y), ch, font, SPECTRA6["red"], SPECTRA6["yellow"],
                           light_density=0.5)
        x += draw.textlength(ch, font=font) + 2


def _expanse_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The transmission: white Barlow, ragged right, the matched phrase
    SemiBold in the MCRN orange, centred in the feed's frame."""
    x0, y0, x1, y1 = _EXPANSE_QUOTE_RECT
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    quote_font, quote_font_bold, wrapped, line_height, _ = fit_quote(
        draw, display_quote, quote_row.get("matched_text") or "",
        x1 - x0, y1 - y0, font_max=36, font_min=14, line_height_mult=1.3, theme="expanse",
    )
    # A short transmission sits in the middle of the frame rather than
    # leaving the glass under it dark.
    y = y0 + max(0, (y1 - y0 - len(wrapped) * line_height) // 2)
    ascent = _font_ascent(quote_font)
    for line in wrapped:
        x = x0
        for chunk, is_bold in line:
            font = quote_font_bold if is_bold else quote_font
            chunk_y = y + (ascent - _font_ascent(font))
            if is_bold and chunk.strip():
                draw_text_dithered(image, (x, chunk_y), chunk, font, SPECTRA6["red"], SPECTRA6["yellow"], light_density=0.5)
            elif not is_bold:
                draw.text((x, chunk_y), chunk, font=font, fill=SPECTRA6["white"])
            x += int(round(draw.textlength(chunk, font=font)))
        y += line_height


def _expanse_gauges(quote_row: dict) -> tuple[int, ...]:
    """The four arc gauges' sweeps, 0..12 each, dealt from the row digest."""
    d = _row_digest(quote_row)
    return tuple((d >> (5 * k)) % 13 for k in range(len(_EXPANSE_ARC_GAUGES)))


def _expanse_pills(quote_row: dict) -> tuple[tuple[str, ...], ...]:
    """The pill grid, four rows of three: each pill green, amber, red or
    dark, dealt from the row digest two bits at a time."""
    d = _row_digest(quote_row) ^ 0x5A5A5A5A
    inks = ("green", "amber", "red", "dark")
    return tuple(tuple(inks[(d >> (2 * (3 * r + c))) & 3] for c in range(3)) for r in range(len(_EXPANSE_PILL_ROWS)))


def _expanse_signal(quote_row: dict) -> int:
    """Signal strength, 1..8 bars, from the row digest."""
    return 1 + (_row_digest(quote_row) >> 30) % 8


def _expanse_tx_id(quote_row: dict) -> str:
    """The transmission's ID: four hex digits of the row digest."""
    return f"TX-{_row_digest(quote_row) & 0xFFFF:04X}"


def _expanse_paint_segments(image: Image.Image, draw: ImageDraw.ImageDraw, x: int, y: int, filled: int, total: int,
                            *, cell: int = 6, gap: int = 3, height: int = 10) -> None:
    """A segmented bar: lit cells in cyan, the rest as blue hairline boxes."""
    for k in range(total):
        rect = (x + k * (cell + gap), y, x + k * (cell + gap) + cell - 1, y + height - 1)
        if k < filled:
            _expanse_paint_cyan_rect(image, (rect[0], rect[1], rect[2] + 1, rect[3] + 1))
        else:
            draw.rectangle(rect, outline=SPECTRA6["blue"], width=1)


def _expanse_paint_source(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The foot of the feed: the book as the source, the signal bars, and
    the command line with the transmission ID."""
    x0, _, x1, y1 = _EXPANSE_FEED_RECT
    white = SPECTRA6["white"]
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "").strip()
    if title:
        font, text = fit_text_to_width(draw, title.upper(), [BARLOWCOND_MEDIUM, BARLOW_MEDIUM, *META_FONT_CANDIDATES],
                                       13, x1 - x0 - 220, floor=11, tracking=1)
        draw_tracked(draw, (x0 + 44, _EXPANSE_SOURCE_Y + 1), text, font, white, tracking=1)
    _expanse_paint_segments(image, draw, x1 - 100, _EXPANSE_SOURCE_Y + 2, _expanse_signal(quote_row), 8, cell=7, gap=4)
    mono = _expanse_mono_font(12)
    prompt = f"> comms.rx tightbeam --decrypt ok  [{_expanse_tx_id(quote_row)}]"
    draw.text((x0 + 14, _EXPANSE_PROMPT_Y), prompt, font=mono, fill=white)
    cursor_x = int(x0 + 14 + draw.textlength(prompt + " ", font=mono))
    _expanse_paint_amber_rect(image, (cursor_x, _EXPANSE_PROMPT_Y + 2, cursor_x + 7, _EXPANSE_PROMPT_Y + 13))


def _expanse_paint_arc_gauges(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The four arc gauges' sweeps: a cyan arc over the outer ring and an
    orange arc on the inner, each sweeping the quote's value of 270°."""
    r = _EXPANSE_ARC_GAUGE_R
    for gx, sweep in zip(_EXPANSE_ARC_GAUGE_XS, _expanse_gauges(quote_row), strict=True):
        gy = _EXPANSE_ARC_GAUGE_Y
        end = 135 + 270 * sweep / 12
        mask = Image.new("L", image.size, 0)
        md = ImageDraw.Draw(mask)
        md.arc((gx - r + 2, gy - r + 2, gx + r - 2, gy + r - 2), 135, end, fill=255, width=4)
        _expanse_paint_stipple_masked(image, mask, SPECTRA6["blue"], SPECTRA6["white"])
        md.rectangle((0, 0, image.size[0], image.size[1]), fill=0)
        md.arc((gx - r + 9, gy - r + 9, gx + r - 9, gy + r - 9), 135, 135 + 270 * ((sweep * 7) % 13) / 12, fill=255, width=3)
        image.paste(SPECTRA6["black"], (0, 0), mask)
        _expanse_paint_stipple_masked(image, mask, SPECTRA6["red"], SPECTRA6["yellow"])
        mask.close()
        draw.ellipse((gx - 1, gy - 1, gx + 1, gy + 1), fill=SPECTRA6["white"])


def _expanse_paint_stipple_masked(image: Image.Image, mask: Image.Image, ink_a, ink_b) -> None:
    """A 50/50 ``ink_a``/``ink_b`` checker through an ``L`` mask: blue + white
    for the cyan, red + yellow for the MCRN orange."""
    bbox = mask.getbbox()
    if not bbox:
        return
    swatch = Image.new("RGB", image.size, SPECTRA6["black"])
    _fill_swatch_stipple(swatch, bbox, ink_a, ink_b, 0.5)
    image.paste(swatch, (0, 0), mask)
    swatch.close()


def _expanse_paint_readouts(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The foot's quote-dependent modules: the pill grid, the waveform
    chart and the boxed IDs under the system text."""
    x0, y0, x1, y1 = _EXPANSE_FOOT_RECT
    for r, row in enumerate(_expanse_pills(quote_row)):
        for c, ink in enumerate(row):
            px0 = x0 + 66 + c * 40
            py0 = y0 + 10 + r * 13
            _expanse_paint_pill(image, draw, (px0, py0, px0 + 32, py0 + 8), ink)
    # The waveform: a seeded walk filled to the baseline in cyan with a white crest.
    cx0, cy0, cx1, cy1 = _EXPANSE_CHART_RECT
    rng = random.Random(_row_digest(quote_row))
    base = cy1 - 2
    height = cy1 - cy0 - 6
    pts = []
    v = 0.4
    for x in range(cx0 + 24, cx1):
        v = min(1.0, max(0.05, v + rng.uniform(-0.09, 0.09) + (0.5 - v) * 0.04))
        pts.append((x, base - int(v * height)))
    area = Image.new("L", image.size, 0)
    ImageDraw.Draw(area).polygon([(cx0 + 24, base)] + pts + [(cx1 - 1, base)], fill=255)
    _expanse_paint_stipple_masked(image, area, SPECTRA6["blue"], SPECTRA6["white"])
    area.close()
    draw.line(pts, fill=SPECTRA6["white"], width=1)
    # Boxed IDs under the system text, as the modules carry.
    mono = _expanse_mono_font(10)
    d = _row_digest(quote_row)
    bx, by = _EXPANSE_SYSTEXT_X, y0 + 46
    for _k, text in enumerate((f"{d % 10_000_000:07d}", f"SY{(d >> 8) % 100_000:05d}")):
        w = int(draw.textlength(text, font=mono)) + 10
        draw.rectangle((bx, by, bx + w, by + 15), outline=SPECTRA6["blue"], width=1)
        draw.text((bx + 5, by + 2), text, font=mono, fill=SPECTRA6["white"])
        bx += w + 8
    armed_w = draw_tracked(draw, (x1 - 14, by + 3), "ARMED", _expanse_label_font(9), SPECTRA6["white"], tracking=1, anchor_right=True)
    draw.rectangle((x1 - 14 - armed_w - 14, by + 2, x1 - 14 - armed_w - 7, by + 13), fill=SPECTRA6["red"])


def render_expanse_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The Rocinante's console with the quote as an incoming tightbeam (see docs/themes.md)."""
    hour = _clock_hour12(time_str)
    del time_str
    image = _expanse_scene().copy()
    draw = ImageDraw.Draw(image)
    _expanse_paint_contact(image, hour)
    _expanse_paint_sender(image, draw, quote_row)
    _expanse_paint_quote(image, draw, quote_row)
    _expanse_paint_source(image, draw, quote_row)
    _expanse_paint_arc_gauges(image, draw, quote_row)
    _expanse_paint_readouts(image, draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("expanse",), render=render_expanse_frame)
