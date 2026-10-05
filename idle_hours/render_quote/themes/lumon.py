"""The ``lumon`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from .._paths import (
    INTER_VARIABLE,
    JOST_VARIABLE,
    META_FONT_BOLD_CANDIDATES,
    META_FONT_CANDIDATES,
    MICHROMA_REGULAR,
    MONTSERRAT_VARIABLE,
    ORNAMENT_FONT_CANDIDATES,
    QUOTE_FONT_BOLD_CANDIDATES,
    QUOTE_FONT_REGULAR_CANDIDATES,
)
from ..fonts import _font_ascent, load_font
from ..furniture import _clock_hour12, _paint_placed, _place_quote, _row_digest, fallback_title
from ..palette import _PANEL_INKS, SPECTRA6, SPECTRA6_PALETTE, _dither_calibrated, snap_image_to_palette
from ..primitives import _fill_swatch_stipple, paint_neon_mask
from ..text import fit_text_to_width
from ._shared import _crt_paint_scanlines, _lumon_hover_boxes

# ---------------------------------------------------------------------------
# lumon — *Severance* (2022–): the Macrodata Refinement terminal
# ---------------------------------------------------------------------------
# Macrodata Refinement: a file named after a town as a field of white digits
# on a blue CRT; the refiner boxes the "scary" cluster and sweeps it into one
# of five bins. Full design notes: docs/themes.md (``lumon``).
#
# The screen is a vignetted blue field computed at quarter resolution,
# bicubic-upsampled and Floyd–Steinberg dithered to blue and black
# (``_dither_calibrated``) so the vignette is error-diffused, not latticed. It
# sits in a recessed black edge inside a beige (W+Y stipple) housing, cached
# per process (``_LUMON_SCENE``).
#
# The hour is the completion, ``N% Complete`` with ``N = hour / 12`` (noon and
# midnight are 100%), and also the column pair of the boxed scary cluster,
# which walks left to right across the twelve hours. Both are byte-identical
# across the minutes of an hour; the matched phrase carries the minute.
#
# Faces (the show's are custom, so each register takes the nearest open face):
# Montserrat (for Gotham) for the digits and the quote, with the matched phrase
# Bold in yellow inside a white hover box; Inter (for Forma DJR) for the file
# name, completion and byline; Michroma (for Manifold Extended) for the
# wordmark. Composed at 800x480 and NEAREST-downsampled otherwise (the
# ``metro`` convention).
# ---------------------------------------------------------------------------
_LUMON_SEED = 0x4C554D4F              # LUMO
_LUMON_FILES = ("Cold Harbor", "Siena", "Dranesville", "Tumwater", "Allentown", "Sunset Park",
                "Lexington", "Nanning", "Moonbeam", "Lucknow", "Billings", "Wellington")
_LUMON_INKS = ("blue", "black")
_LUMON_HOUSING = 10                   # the beige housing, a W+Y stipple
_LUMON_GAP = 6                        # the recessed black edge of the glass
_LUMON_BEZEL = _LUMON_HOUSING + _LUMON_GAP
_LUMON_BEZEL_RADIUS = 26
_LUMON_SCANLINE_PERIOD = 4
_LUMON_HEADER_Y = 28
_LUMON_RULE_Y = 82
_LUMON_GRID_RECT = (44, 94, 756, 198)
_LUMON_GRID_COLS = 24
_LUMON_GRID_ROWS = 4
_LUMON_QUOTE_RECT = (50, 214, 750, 386)
_LUMON_BYLINE_Y = 392
_LUMON_BINS_RECT = (44, 414, 756, 460)
_LUMON_BIN_GAP = 12
_LUMON_SCENE: dict = {}
_LUMON_BLUE = _PANEL_INKS["blue"]
_LUMON_BLACK = _PANEL_INKS["black"]


def _lumon_completion(hour: int) -> int:
    """The file's completion in percent: the hour over twelve."""
    return round(hour * 100 / 12)


def _lumon_file_name(quote_row: dict) -> str:
    """The file's town, chosen by the quote."""
    return _LUMON_FILES[_row_digest(quote_row) % len(_LUMON_FILES)]


def _lumon_scene() -> Image.Image:
    """The vignetted blue CRT inside its bezel, dithered. Painted once per
    process."""
    key = (_lumon_paint_screen,)
    cached = _LUMON_SCENE.get("frame")
    if cached is not None and cached[0] == key:
        return cached[1]
    size = (800, 480)
    image = Image.new("RGB", size, SPECTRA6["black"])
    _lumon_paint_screen(image)
    _LUMON_SCENE["frame"] = (key, image)
    return image


def _lumon_paint_screen(image: Image.Image) -> None:
    """The blue field falling to black at the corners, error-diffused to the
    two inks, in a recessed black edge inside a beige housing, with the
    phosphor's light leaking onto the edge."""
    width, height = image.size
    small = Image.new("RGB", (width // 4, height // 4))
    sp = small.load()
    cx, cy = small.size[0] / 2.0, small.size[1] / 2.0
    rmax = math.hypot(cx, cy)
    for y in range(small.size[1]):
        for x in range(small.size[0]):
            t = min(1.0, (math.hypot(x + 0.5 - cx, y + 0.5 - cy) / rmax) ** 2.8 * 0.85)
            sp[x, y] = tuple(round(b * (1 - t) + k * t) for b, k in zip(_LUMON_BLUE, _LUMON_BLACK))
    field = _dither_calibrated(small.resize((width, height), Image.Resampling.BICUBIC), _LUMON_INKS)
    # The housing: the beige of the show's terminals, white with a yellow
    # quarter, with the glass opening cut out of it.
    _fill_swatch_stipple(image, (0, 0, width, height), SPECTRA6["white"], SPECTRA6["yellow"], 0.25)
    h = _LUMON_HOUSING
    ImageDraw.Draw(image).rounded_rectangle((h, h, width - h, height - h), radius=_LUMON_BEZEL_RADIUS + _LUMON_GAP,
                                            fill=SPECTRA6["black"])
    b = _LUMON_BEZEL
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((b, b, width - b, height - b), radius=_LUMON_BEZEL_RADIUS, fill=255)
    paint_neon_mask(image, mask, None, SPECTRA6["blue"], radius=5, gamma=1.6, cap=0.5, ground=(SPECTRA6["black"],))
    image.paste(field, (0, 0), mask)
    small.close()
    field.close()
    mask.close()


def _lumon_paint_header(draw: ImageDraw.ImageDraw, hour: int, quote_row: dict) -> None:
    """The file name, the Lumon globe and wordmark, and the completion."""
    white = SPECTRA6["white"]
    x0, x1 = _LUMON_GRID_RECT[0], _LUMON_GRID_RECT[2]
    name_font = load_font([(INTER_VARIABLE, "Medium"), *META_FONT_BOLD_CANDIDATES], size=26)
    draw.text((x0, _LUMON_HEADER_Y), _lumon_file_name(quote_row), font=name_font, fill=white)
    # The globe: a circle with three latitude lines.
    gx, gy, gr = x1 - 18, _LUMON_HEADER_Y + 20, 16
    draw.ellipse((gx - gr, gy - gr, gx + gr, gy + gr), outline=white, width=2)
    for dy, half in ((-8, 13), (0, 16), (8, 13)):
        draw.line((gx - half, gy + dy, gx + half, gy + dy), fill=white, width=1)
    draw.line((gx, gy - gr, gx, gy + gr), fill=white, width=1)
    mark = load_font([MICHROMA_REGULAR, (JOST_VARIABLE, "Bold"), *ORNAMENT_FONT_CANDIDATES], size=14)
    right = gx - gr - 12
    draw.text((right - draw.textlength("LUMON", font=mark), _LUMON_HEADER_Y - 2), "LUMON", font=mark, fill=white)
    line = f"{_lumon_completion(hour)}% Complete"
    small = load_font([(INTER_VARIABLE, "Regular"), *META_FONT_CANDIDATES], size=15)
    draw.text((right - draw.textlength(line, font=small), _LUMON_HEADER_Y + 22), line, font=small, fill=white)
    draw.rectangle((x0, _LUMON_RULE_Y, x1, _LUMON_RULE_Y + 1), fill=white)


def _lumon_grid_cells():
    """The grid's cell boxes, row-major."""
    x0, y0, x1, y1 = _LUMON_GRID_RECT
    cw = (x1 - x0) / _LUMON_GRID_COLS
    ch = (y1 - y0) / _LUMON_GRID_ROWS
    return [[(x0 + c * cw, y0 + r * ch, x0 + (c + 1) * cw, y0 + (r + 1) * ch)
             for c in range(_LUMON_GRID_COLS)] for r in range(_LUMON_GRID_ROWS)]


def _lumon_cluster(hour: int) -> tuple[int, int]:
    """The scary cluster's top-left cell ``(row, col)``: the middle rows,
    the hour's column pair."""
    return 1, 2 * (hour - 1)


def _lumon_paint_grid(draw: ImageDraw.ImageDraw, hour: int, quote_row: dict) -> None:
    """The field of digits, seeded from the quote, with the hour's cluster
    boxed, a size larger and nudged off the grid."""
    white = SPECTRA6["white"]
    rng = random.Random(_LUMON_SEED ^ _row_digest(quote_row))
    cells = _lumon_grid_cells()
    plain = load_font([(MONTSERRAT_VARIABLE, "Medium"), *QUOTE_FONT_REGULAR_CANDIDATES], size=17)
    scary = load_font([(MONTSERRAT_VARIABLE, "Bold"), *QUOTE_FONT_BOLD_CANDIDATES], size=23)
    row0, col0 = _lumon_cluster(hour)
    for r, row in enumerate(cells):
        for c, (cx0, cy0, cx1, cy1) in enumerate(row):
            digit = str(rng.randint(0, 9))
            in_cluster = row0 <= r <= row0 + 1 and col0 <= c <= col0 + 1
            font = scary if in_cluster else plain
            dx = rng.randint(-2, 2) if in_cluster else 0
            dy = rng.randint(-2, 2) if in_cluster else 0
            tw = draw.textlength(digit, font=font)
            th = _font_ascent(font)
            draw.text((cx0 + (cx1 - cx0 - tw) / 2 + dx, cy0 + (cy1 - cy0 - th) / 2 - 2 + dy), digit, font=font,
                      fill=white)
    bx0, by0 = cells[row0][col0][0], cells[row0][col0][1]
    bx1, by1 = cells[row0 + 1][col0 + 1][2], cells[row0 + 1][col0 + 1][3]
    draw.rectangle((round(bx0) - 3, round(by0) - 3, round(bx1) + 3, round(by1) + 3), outline=white, width=1)


def _lumon_layout(draw: ImageDraw.ImageDraw, quote_row: dict):
    """The quote's lines on the terminal, with the bold chunks positioned."""
    return _place_quote(draw, quote_row, _LUMON_QUOTE_RECT, theme="lumon",
                        font_max=30, font_min=14, line_height_mult=1.32)


def _lumon_paint_quote(draw: ImageDraw.ImageDraw, placed) -> None:
    """White Montserrat; the matched phrase Bold in yellow inside the
    refiner's white hover box."""
    white, yellow = SPECTRA6["white"], SPECTRA6["yellow"]
    for box in _lumon_hover_boxes(draw, placed):
        draw.rectangle(box, outline=white, width=1)
    _paint_placed(draw, placed, white, yellow)


def _lumon_paint_byline(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """Author and title under the quote, in Inter."""
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "").strip()
    parts = [p for p in (author, title) if p]
    if not parts:
        return
    x0 = _LUMON_QUOTE_RECT[0]
    font, text = fit_text_to_width(draw, " — ".join(parts), [(INTER_VARIABLE, "Regular"), *META_FONT_CANDIDATES],
                                   16, _LUMON_QUOTE_RECT[2] - x0, floor=13)
    draw.text((x0, _LUMON_BYLINE_Y), text, font=font, fill=SPECTRA6["white"])


def _lumon_paint_bins(image: Image.Image, quote_row: dict) -> None:
    """The five bins along the foot, each boxed with a stippled progress bar
    at a level seeded from the quote."""
    draw = ImageDraw.Draw(image)
    white, blue = SPECTRA6["white"], SPECTRA6["blue"]
    x0, y0, x1, y1 = _LUMON_BINS_RECT
    width = (x1 - x0 - 4 * _LUMON_BIN_GAP) // 5
    rng = random.Random(_LUMON_SEED + 3 + _row_digest(quote_row))
    label = load_font([(MONTSERRAT_VARIABLE, "Medium"), *QUOTE_FONT_REGULAR_CANDIDATES], size=14)
    small = load_font([(MONTSERRAT_VARIABLE, "Medium"), *QUOTE_FONT_REGULAR_CANDIDATES], size=11)
    for i in range(5):
        bx0 = x0 + i * (width + _LUMON_BIN_GAP)
        bx1 = bx0 + width
        draw.rectangle((bx0, y0, bx1, y1), outline=white, width=1)
        draw.text((bx0 + 8, y0 + 5), f"0{i}", font=label, fill=white)
        level = rng.randint(4, 96)
        pct = f"{level}%"
        draw.text((bx1 - 8 - draw.textlength(pct, font=small), y0 + 7), pct, font=small, fill=white)
        bar = (bx0 + 8, y1 - 16, bx1 - 8, y1 - 7)
        draw.rectangle(bar, outline=white, width=1)
        fill_w = round((bar[2] - bar[0] - 4) * level / 100)
        if fill_w > 0:
            _fill_swatch_stipple(image, (bar[0] + 2, bar[1] + 2, bar[0] + 2 + fill_w, bar[3] - 1), blue, white, 0.5)


def render_lumon_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The Macrodata Refinement terminal with the hour's file completion and
    the scary cluster in the hour's column (see the section comment above)."""
    hour = _clock_hour12(time_str)
    image = _lumon_scene().copy()
    draw = ImageDraw.Draw(image)
    _lumon_paint_header(draw, hour, quote_row)
    _lumon_paint_grid(draw, hour, quote_row)
    _lumon_paint_quote(draw, _lumon_layout(draw, quote_row))
    _lumon_paint_byline(draw, quote_row)
    _lumon_paint_bins(image, quote_row)
    b = _LUMON_BEZEL
    _crt_paint_scanlines(image, (b, b, 800 - b, 480 - b), (SPECTRA6["blue"],), period=_LUMON_SCANLINE_PERIOD)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image
