"""The ``traumateam`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import random

from PIL import Image, ImageDraw

from .._paths import META_FONT_BOLD_CANDIDATES, META_FONT_CANDIDATES, OXANIUM_VARIABLE
from ..fonts import load_font
from ..furniture import _clock_hour12, _paint_placed, _place_quote, _row_digest, fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, snap_image_to_palette
from ..primitives import _fill_swatch_stipple
from ..spec import FrameSpec
from ..text import fit_text_to_width
from ._shared import _lumon_hover_boxes

# ---------------------------------------------------------------------------
# traumateam — *Cyberpunk*: a Trauma Team International dispatch screen
# ---------------------------------------------------------------------------
# The armoured ambulance service of Night City, on a black screen: the
# wordmark in white block capitals either side of the six-armed mark, a red
# dispatch band beneath it, the quote as the call, and a vitals trace along
# the foot. Full design notes: docs/themes.md (``traumateam``).
#
# The wordmark is drawn, not set: no open face has the brand's stencilled
# block capitals, so each letter is a handful of polygons on a 3 x 9 stroke
# grid (``_TRAUMATEAM_GLYPHS``), inspired by the logo rather than traced from it.
#
# The hour is the responding unit, ``AV-01`` to ``AV-12``, byte-identical
# across the minutes of an hour; the matched phrase carries the minute, set
# Bold in white on a red block, the band's red. Red ink on black reads
# nearly black on the panel, so red is only ever a ground under white.
# Composed at 800x480 and NEAREST-downsampled otherwise (the ``metro``
# convention).
# ---------------------------------------------------------------------------
_TRAUMATEAM_SEED = 0x54524D41             # TRMA
_TRAUMATEAM_UNIT = 6                      # px per stroke-grid unit; caps are 9 units tall
_TRAUMATEAM_LOCKUP_Y = 30                 # top of the capitals
_TRAUMATEAM_LETTER_GAP = 1.6              # units between letters
_TRAUMATEAM_MARK_GAP = 22                 # px between the mark and each word
_TRAUMATEAM_BAND = (24, 126, 776, 152)    # the red dispatch band
_TRAUMATEAM_QUOTE_RECT = (48, 176, 752, 372)
_TRAUMATEAM_BYLINE_Y = 382
_TRAUMATEAM_VITALS = (24, 418, 776, 462)  # the vitals strip at the foot
_TRAUMATEAM_STATUSES = ("EN ROUTE", "ON SCENE", "EXTRACTION", "STABILISING", "IN FLIGHT", "CLIENT SECURED")
_TRAUMATEAM_FRAME_SIZE = (800, 480)

# Block capitals on a stroke grid: x 0..width, y 0..9, one unit a stroke.
# Each entry is ``(width, [polygon, ...])``; a polygon is a list of points.
_TRAUMATEAM_GLYPHS: dict[str, tuple[float, list[list[tuple[float, float]]]]] = {
    "T": (3, [
        [(0, 0), (3, 0), (2.5, 1), (0, 1)],
        [(1.5, 1), (2.5, 1), (2.5, 9), (1.5, 9)],
    ]),
    "R": (3, [
        [(0, 0), (3, 0), (3, 4.6), (1.2, 4.6), (2.3, 4.6), (3, 6), (3, 9), (2, 9), (2, 6.4), (1.2, 4.6),
         (1, 4.6), (1, 9), (0, 9)],
    ]),
    "A": (3, [
        [(0, 0), (3, 0), (3, 9), (2, 9), (2, 5), (1, 5), (1, 9), (0, 9)],
    ]),
    "U": (3, [
        [(0, 1), (1, 1), (1, 8), (2, 8), (2, 0), (3, 0), (3, 9), (0, 9)],
    ]),
    "M": (5, [
        [(0, 0), (2, 0), (2, 1), (1, 1), (1, 9), (0, 9)],
        [(2, 0), (5, 0), (5, 9), (4, 9), (4, 1), (3, 1), (3, 9), (2, 9)],
    ]),
    "E": (3, [
        [(0, 0), (3, 0), (3, 1), (1, 1), (1, 4), (2, 4), (2, 5), (1, 5), (1, 8), (2, 8), (2, 5.2),
         (3, 5.2), (3, 9), (0, 9)],
    ]),
}
_TRAUMATEAM_COUNTERS: dict[str, list[tuple[float, float]]] = {"A": [(1, 1), (2, 1), (2, 4), (1, 4)], "R": [(1, 1), (2, 1), (2, 3.6), (1, 3.6)]}


def _traumateam_unit_code(hour: int) -> str:
    """The responding aerial unit, named for the hour."""
    return f"AV-{hour:02d}"


def _traumateam_status(quote_row: dict) -> str:
    """The call's status, chosen by the quote."""
    return _TRAUMATEAM_STATUSES[_row_digest(quote_row) % len(_TRAUMATEAM_STATUSES)]


def _traumateam_word_width(word: str) -> float:
    """A word's width in grid units."""
    widths = [_TRAUMATEAM_GLYPHS[ch][0] for ch in word]
    return sum(widths) + _TRAUMATEAM_LETTER_GAP * (len(widths) - 1)


def _traumateam_paint_word(draw: ImageDraw.ImageDraw, word: str, x: float, y: float, fill) -> None:
    """Paint ``word`` in the block capitals with its top-left at ``(x, y)``."""
    u = _TRAUMATEAM_UNIT
    for ch in word:
        width, polys = _TRAUMATEAM_GLYPHS[ch]
        for poly in polys:
            draw.polygon([(round(x + px * u), round(y + py * u)) for px, py in poly], fill=fill)
        counter = _TRAUMATEAM_COUNTERS.get(ch)
        if counter is not None:
            draw.polygon([(round(x + px * u), round(y + py * u)) for px, py in counter], fill=SPECTRA6["black"])
        x += (width + _TRAUMATEAM_LETTER_GAP) * u


def _traumateam_mark_polygons(cx: float, cy: float, height: float) -> tuple[list, list]:
    """The six-armed mark centred on ``(cx, cy)``: ``(solid, cut)`` polygons.

    A vertical bar crossed by two broad diagonal bands with square-cut ends,
    and a thin cut from the bar's upper left down to the centre."""
    half_w = height * 0.375
    bar = height * 0.16
    band = height * 0.24
    slope = 0.72
    top, bottom = cy - height / 2, cy + height / 2
    left, right = cx - half_w, cx + half_w
    solid = [[(cx - bar / 2, top), (cx + bar / 2, top), (cx + bar / 2, bottom), (cx - bar / 2, bottom)]]
    for s in (slope, -slope):
        yl, yr = cy + s * (left - cx), cy + s * (right - cx)
        solid.append([(left, yl - band / 2), (right, yr - band / 2), (right, yr + band / 2), (left, yl + band / 2)])
    cut = [(cx - bar / 2, cy - height * 0.24), (cx - bar / 2, cy - height * 0.30),
           (cx + height * 0.12, cy + height * 0.02), (cx + height * 0.08, cy + height * 0.02)]
    return solid, [cut]


def _traumateam_paint_lockup(draw: ImageDraw.ImageDraw) -> None:
    """``TRAUMA`` and ``TEAM`` either side of the mark, centred on the frame."""
    u = _TRAUMATEAM_UNIT
    cap = 9 * u
    mark_h = cap * 1.9
    mark_w = mark_h * 0.75
    left_w = _traumateam_word_width("TRAUMA") * u
    right_w = _traumateam_word_width("TEAM") * u
    total = left_w + mark_w + right_w + 2 * _TRAUMATEAM_MARK_GAP
    x = (_TRAUMATEAM_FRAME_SIZE[0] - total) / 2
    white = SPECTRA6["white"]
    _traumateam_paint_word(draw, "TRAUMA", x, _TRAUMATEAM_LOCKUP_Y, white)
    cx = x + left_w + _TRAUMATEAM_MARK_GAP + mark_w / 2
    solid, cut = _traumateam_mark_polygons(cx, _TRAUMATEAM_LOCKUP_Y + cap / 2, mark_h)
    for poly in solid:
        draw.polygon([(round(px), round(py)) for px, py in poly], fill=white)
    for poly in cut:
        draw.polygon([(round(px), round(py)) for px, py in poly], fill=SPECTRA6["black"])
    _traumateam_paint_word(draw, "TEAM", cx + mark_w / 2 + _TRAUMATEAM_MARK_GAP, _TRAUMATEAM_LOCKUP_Y, white)


def _traumateam_paint_band(image: Image.Image, hour: int, quote_row: dict) -> None:
    """The red dispatch band: the service tier on the left, the unit and the
    call's status on the right, and a cyan (green + blue) hazard tab at each
    end."""
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = _TRAUMATEAM_BAND
    draw.rectangle((x0, y0, x1, y1), fill=SPECTRA6["red"])
    tab = 18
    for tx in (x0, x1 - tab):
        _fill_swatch_stipple(image, (tx, y0, tx + tab + 1, y1 + 1), SPECTRA6["green"], SPECTRA6["blue"], 0.5)
    font = load_font([(OXANIUM_VARIABLE, "SemiBold"), *META_FONT_BOLD_CANDIDATES], size=16)
    ty = y0 + (y1 - y0 - 16) // 2 - 1
    white = SPECTRA6["white"]
    draw.text((x0 + tab + 10, ty), "PLATINUM RESPONSE", font=font, fill=white)
    right = f"{_traumateam_unit_code(hour)}  //  {_traumateam_status(quote_row)}"
    draw.text((x1 - tab - 10 - draw.textlength(right, font=font), ty), right, font=font, fill=white)


def _traumateam_layout(draw: ImageDraw.ImageDraw, quote_row: dict):
    """The quote's lines under the band, with the bold chunks positioned."""
    return _place_quote(draw, quote_row, _TRAUMATEAM_QUOTE_RECT, theme="traumateam",
                        font_max=34, font_min=15, line_height_mult=1.3)


def _traumateam_paint_quote(draw: ImageDraw.ImageDraw, placed) -> None:
    """White Oxanium; the matched phrase Bold in white on a red block."""
    for box in _lumon_hover_boxes(draw, placed):
        draw.rectangle(box, fill=SPECTRA6["red"])
    _paint_placed(draw, placed, SPECTRA6["white"], SPECTRA6["white"])


def _traumateam_paint_byline(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """Author and title under the quote, after a short white tick."""
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "").strip()
    parts = [p for p in (author, title) if p]
    if not parts:
        return
    x0 = _TRAUMATEAM_QUOTE_RECT[0]
    draw.rectangle((x0, _TRAUMATEAM_BYLINE_Y + 9, x0 + 18, _TRAUMATEAM_BYLINE_Y + 11), fill=SPECTRA6["white"])
    font, text = fit_text_to_width(draw, " — ".join(parts), [(OXANIUM_VARIABLE, "Medium"), *META_FONT_CANDIDATES],
                                   18, _TRAUMATEAM_QUOTE_RECT[2] - x0 - 28, floor=14)
    draw.text((x0 + 28, _TRAUMATEAM_BYLINE_Y), text, font=font, fill=SPECTRA6["white"])


def _traumateam_vitals_points(quote_row: dict) -> list[tuple[int, int]]:
    """The ECG trace across the vitals strip: a flat line with a P-QRS-T
    complex every beat, the rhythm's phase and rate seeded from the quote."""
    x0, y0, x1, y1 = _TRAUMATEAM_VITALS
    rng = random.Random(_TRAUMATEAM_SEED ^ _row_digest(quote_row))
    base = (y0 + y1) // 2 + 6
    period = rng.randint(118, 146)
    x = x0 + 86 + rng.randint(0, period // 2)
    amp = (y1 - y0) // 2 + 4
    points = [(x0 + 80, base)]
    while x + 60 < x1 - 14:
        points += [
            (x, base), (x + 6, base - 4), (x + 12, base),            # P
            (x + 20, base), (x + 23, base + 5),                        # Q
            (x + 28, base - amp), (x + 33, base + 9), (x + 37, base),  # R, S
            (x + 47, base), (x + 54, base - 7), (x + 61, base),        # T
        ]
        x += period
    points.append((x1 - 14, base))
    return points


def _traumateam_paint_vitals(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """``VITALS`` and the heart trace along the foot, ending in a live dot."""
    x0, y0, x1, y1 = _TRAUMATEAM_VITALS
    white = SPECTRA6["white"]
    draw.line((x0, y0 - 6, x1, y0 - 6), fill=white, width=1)
    font = load_font([(OXANIUM_VARIABLE, "SemiBold"), *META_FONT_BOLD_CANDIDATES], size=14)
    draw.text((x0, (y0 + y1) // 2 - 2), "VITALS", font=font, fill=white)
    points = _traumateam_vitals_points(quote_row)
    draw.line(points, fill=white, width=2, joint="curve")
    ex, ey = points[-1]
    draw.ellipse((ex - 4, ey - 4, ex + 4, ey + 4), fill=white)


def render_traumateam_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The Trauma Team dispatch screen with the hour's responding unit (see
    the section comment above)."""
    hour = _clock_hour12(time_str)
    image = Image.new("RGB", _TRAUMATEAM_FRAME_SIZE, SPECTRA6["black"])
    draw = ImageDraw.Draw(image)
    _traumateam_paint_lockup(draw)
    _traumateam_paint_band(image, hour, quote_row)
    _traumateam_paint_quote(draw, _traumateam_layout(draw, quote_row))
    _traumateam_paint_byline(draw, quote_row)
    _traumateam_paint_vitals(draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != _TRAUMATEAM_FRAME_SIZE:
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("traumateam",), render=render_traumateam_frame)
