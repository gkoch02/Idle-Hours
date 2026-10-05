"""The ``hal`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from .._paths import JOST_VARIABLE, META_FONT_CANDIDATES, MICHROMA_REGULAR, ORNAMENT_FONT_CANDIDATES
from ..fonts import load_font
from ..furniture import _clock_hour12, _paint_placed, _place_quote, _row_digest, fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, snap_image_to_palette
from ..primitives import paint_neon_mask
from ..spec import FrameSpec
from ..text import draw_tracked, fit_text_to_width
from ._shared import _crt_paint_scanlines

# ---------------------------------------------------------------------------
# hal — *2001: A Space Odyssey* (1968): the Discovery One's monitors, HAL 9000
# ---------------------------------------------------------------------------
# The Discovery's monitors are flat fields of one saturated colour captioned
# with a three-letter subsystem mnemonic — solid flats, which six inks render
# exactly. Full design notes: docs/themes.md (``hal``).
#
# Layout: the main monitor (blue field, the active mnemonic in Michroma,
# seeded readout bars, the quote in white Jost with the matched phrase Bold in
# yellow, a tracked byline); the twelve subsystem tiles along the foot; and the
# right column — nameplate, HAL's lens, the VEH wireframe and the HIB monitor's
# two life traces.
#
# The hour is which subsystem is up: the hour's tile is white and its mnemonic
# heads the main monitor. The order is fixed, so the frame is byte-identical
# across the minutes of an hour; nothing reads the wall clock. Every colour is
# a solid ink; the only stipples are the ``paint_neon_mask`` blooms, each with
# ``ground`` pinned so it cannot eat the bezel. Composed at 800x480 and
# NEAREST-downsampled otherwise (the ``metro`` convention).
# ---------------------------------------------------------------------------
_HAL_SEED = 0x48414C39                # HAL9
_HAL_MNEMONICS = ("COM", "NAV", "VEH", "ATM", "HIB", "GDE", "LIF", "MEM", "DMG", "FLX", "CNT", "NUC")
_HAL_TILE_INKS = ("red", "yellow", "green", "blue")
_HAL_HOUSING_RECT = (16, 16, 644, 392)   # the monitor's housing, a hairline on black
_HAL_MONITOR_RECT = (26, 26, 634, 382)   # the screen inside it
_HAL_SCREEN_RADIUS = 20
_HAL_HEADER_RULE_Y = 96
_HAL_QUOTE_RECT = (56, 110, 604, 338)
_HAL_BYLINE_Y = 352
_HAL_TILE_BAND = (24, 402, 636, 462)
_HAL_TILE_GAP = 6
_HAL_PLATE_RECT = (664, 24, 780, 92)
_HAL_EYE_CENTRE = (722, 196)
_HAL_EYE_RADIUS = 44
_HAL_SHIP_RECT = (664, 292, 780, 370)   # VEH: the Discovery in wireframe
_HAL_TRACE_RECT = (664, 378, 780, 462)  # HIB: the life traces
_HAL_SCANLINE_PERIOD = 4


def _hal_mnemonic(hour: int) -> str:
    return _HAL_MNEMONICS[(hour - 1) % 12]


def _hal_tile_rects() -> list:
    """The twelve foot tiles, left to right, one per hour."""
    x0, y0, x1, y1 = _HAL_TILE_BAND
    width = (x1 - x0 - 11 * _HAL_TILE_GAP) // 12
    used = 12 * width + 11 * _HAL_TILE_GAP
    start = x0 + (x1 - x0 - used) // 2
    return [(start + i * (width + _HAL_TILE_GAP), y0, start + i * (width + _HAL_TILE_GAP) + width, y1)
            for i in range(12)]


def _hal_chrome_font(size: int):
    """Michroma — the monitors' squared capitals — for every label."""
    return load_font([MICHROMA_REGULAR, (JOST_VARIABLE, "Bold"), *ORNAMENT_FONT_CANDIDATES], size=size)


def _hal_paint_monitor(image: Image.Image, hour: int, quote_row: dict) -> None:
    """The main monitor: the blue field, the active mnemonic, a row of
    readout bars seeded from the quote, and the rule under both."""
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = _HAL_MONITOR_RECT
    blue, white, black = SPECTRA6["blue"], SPECTRA6["white"], SPECTRA6["black"]
    # The housing: a hairline on the black, and the phosphor's light leaking
    # onto it from the glass.
    draw.rounded_rectangle(_HAL_HOUSING_RECT, radius=_HAL_SCREEN_RADIUS + 8, fill=black, outline=white, width=1)
    glass = Image.new("L", image.size, 0)
    ImageDraw.Draw(glass).rounded_rectangle((x0, y0, x1, y1), radius=_HAL_SCREEN_RADIUS, fill=255)
    paint_neon_mask(image, glass, None, blue, radius=7, gamma=1.6, cap=0.5, ground=(black,))
    glass.close()
    draw.rounded_rectangle((x0, y0, x1, y1), radius=_HAL_SCREEN_RADIUS, fill=blue)
    # The mnemonic in its title box, the way the film's screens caption
    # themselves, and a seeded bar chart beside it.
    font = _hal_chrome_font(36)
    name = _hal_mnemonic(hour)
    tw = draw.textlength(name, font=font)
    draw.rectangle((x0 + 28, y0 + 18, x0 + 28 + tw + 24, y0 + 72), outline=white, width=2)
    draw.text((x0 + 40, y0 + 24), name, font=font, fill=white)
    rng = random.Random(_HAL_SEED ^ _row_digest(quote_row))
    bar_x = x1 - 30 - 12 * 15
    for i in range(12):
        h = rng.randint(6, 44)
        bx = bar_x + i * 15
        draw.rectangle((bx, y0 + 70 - h, bx + 9, y0 + 70), fill=white)
    draw.rectangle((bar_x - 2, y0 + 71, x1 - 30, y0 + 72), fill=white)
    draw.rectangle((x0 + 28, _HAL_HEADER_RULE_Y, x1 - 30, _HAL_HEADER_RULE_Y + 2), fill=white)


def _hal_layout(draw: ImageDraw.ImageDraw, quote_row: dict):
    """The quote's lines on the monitor, with the bold chunks positioned."""
    return _place_quote(draw, quote_row, _HAL_QUOTE_RECT, theme="hal",
                        font_max=36, font_min=16, line_height_mult=1.28)


def _hal_paint_quote(draw: ImageDraw.ImageDraw, placed) -> None:
    """White Jost on the blue field; the matched phrase Bold in yellow."""
    _paint_placed(draw, placed, SPECTRA6["white"], SPECTRA6["yellow"])


def _hal_paint_byline(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """Author and title as the monitor's tracked capitals along its foot."""
    x0 = _HAL_QUOTE_RECT[0]
    measure = _HAL_QUOTE_RECT[2] - x0
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "").strip()
    parts = [p.upper() for p in (author, title) if p]
    if not parts:
        return
    text = "   /   ".join(parts)
    font, text = fit_text_to_width(draw, text, [(JOST_VARIABLE, "Medium"), *META_FONT_CANDIDATES],
                                   16, measure, floor=13, tracking=2)
    draw_tracked(draw, (x0, _HAL_BYLINE_Y), text, font, SPECTRA6["white"], tracking=2)


def _hal_paint_tiles(image: Image.Image, hour: int, quote_row: dict) -> None:
    """The twelve subsystem tiles along the foot: the film's colours in
    rotation, the hour's tile white, each with a seeded mini-readout."""
    draw = ImageDraw.Draw(image)
    rng = random.Random(_HAL_SEED + 7 + _row_digest(quote_row))
    white, black = SPECTRA6["white"], SPECTRA6["black"]
    font = _hal_chrome_font(11)
    for i, (x0, y0, x1, y1) in enumerate(_hal_tile_rects()):
        active = (i + 1) == hour
        ink = "white" if active else _HAL_TILE_INKS[i % len(_HAL_TILE_INKS)]
        fill = SPECTRA6[ink]
        label = black if ink in ("white", "yellow") else white
        draw.rounded_rectangle((x0, y0, x1, y1), radius=5, fill=fill)
        name = _HAL_MNEMONICS[i]
        tw = draw.textlength(name, font=font)
        draw.text((x0 + (x1 - x0 - tw) / 2, y0 + 7), name, font=font, fill=label)
        for b in range(4):
            h = rng.randint(3, 18)
            bx = x0 + 6 + b * 9
            draw.rectangle((bx, y1 - 8 - h, bx + 5, y1 - 8), fill=label)
        _crt_paint_scanlines(image, (x0, y0, x1 + 1, y1 + 1), (fill,), period=_HAL_SCANLINE_PERIOD, phase=1)
        if active:
            draw.rectangle((x0, y0 - 8, x1, y0 - 6), fill=white)


def _hal_paint_plate(draw: ImageDraw.ImageDraw) -> None:
    """The nameplate above the lens: HAL over 9000 on the blue plate."""
    x0, y0, x1, y1 = _HAL_PLATE_RECT
    blue, white = SPECTRA6["blue"], SPECTRA6["white"]
    draw.rectangle((x0, y0, x1, y1), fill=blue)
    big, small = _hal_chrome_font(24), _hal_chrome_font(15)
    cx = (x0 + x1) / 2
    draw.text((cx - draw.textlength("HAL", font=big) / 2, y0 + 8), "HAL", font=big, fill=white)
    draw.text((cx - draw.textlength("9000", font=small) / 2, y0 + 42), "9000", font=small, fill=white)


def _hal_paint_eye(image: Image.Image) -> None:
    """The lens: a red disc in a white bezel, a yellow bloom at its centre
    with a white catchlight, and red light spilling into the black."""
    cx, cy = _HAL_EYE_CENTRE
    r = _HAL_EYE_RADIUS
    draw = ImageDraw.Draw(image)
    black, white, red, yellow = SPECTRA6["black"], SPECTRA6["white"], SPECTRA6["red"], SPECTRA6["yellow"]
    draw.ellipse((cx - r - 6, cy - r - 6, cx + r + 6, cy + r + 6), fill=black, outline=white, width=3)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=red)
    glow = Image.new("L", image.size, 0)
    ImageDraw.Draw(glow).ellipse((cx - 13, cy - 13, cx + 13, cy + 13), fill=255)
    paint_neon_mask(image, glow, yellow, yellow, radius=9, gamma=1.8, cap=0.6, ground=(red,))
    draw.ellipse((cx - 19, cy - 19, cx - 9, cy - 9), fill=white)
    bloom = Image.new("L", image.size, 0)
    ImageDraw.Draw(bloom).ellipse((cx - r - 8, cy - r - 8, cx + r + 8, cy + r + 8), fill=255)
    paint_neon_mask(image, bloom, None, red, radius=12, gamma=2.0, cap=0.45, ground=(black,))
    glow.close()
    bloom.close()


def _hal_paint_ship(draw: ImageDraw.ImageDraw) -> None:
    """The vehicle monitor under the lens: the Discovery One in white
    wireframe — the command sphere, the spine of fuel tanks, the engine
    block — the kind of schematic the film's screens drew by hand."""
    x0, y0, x1, y1 = _HAL_SHIP_RECT
    white = SPECTRA6["white"]
    draw.rectangle((x0, y0, x1, y1), outline=white, width=1)
    draw.text((x0 + 8, y0 + 6), "VEH", font=_hal_chrome_font(11), fill=white)
    cy = y0 + 50
    sx = x0 + 10
    draw.ellipse((sx, cy - 11, sx + 22, cy + 11), outline=white, width=1)
    draw.ellipse((sx + 6, cy - 5, sx + 16, cy + 5), outline=white, width=1)
    draw.line((sx + 22, cy, x1 - 26, cy), fill=white, width=1)
    for i in range(5):
        bx = sx + 30 + i * 11
        draw.rectangle((bx, cy - 4, bx + 7, cy + 4), outline=white, width=1)
    draw.rectangle((x1 - 26, cy - 8, x1 - 10, cy + 8), outline=white, width=1)
    draw.line((x1 - 10, cy - 5, x1 - 6, cy - 5), fill=white, width=1)
    draw.line((x1 - 10, cy + 5, x1 - 6, cy + 5), fill=white, width=1)
    draw.line((sx + 24, cy - 18, sx + 24, cy + 18), fill=white, width=1)
    draw.line((sx + 18, cy - 18, sx + 30, cy - 18), fill=white, width=1)


def _hal_paint_traces(image: Image.Image, quote_row: dict) -> None:
    """The hibernation monitor under the ship: two life traces, seeded
    from the quote, in a white hairline frame."""
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = _HAL_TRACE_RECT
    white = SPECTRA6["white"]
    draw.rectangle((x0, y0, x1, y1), outline=white, width=1)
    draw.text((x0 + 8, y0 + 6), "HIB", font=_hal_chrome_font(11), fill=white)
    rng = random.Random(_HAL_SEED + 11 + _row_digest(quote_row))
    inner_top = y0 + 24
    lane = (y1 - inner_top) // 2
    for t in range(2):
        base = inner_top + t * lane + lane // 2 + 6
        amp = lane // 2 - 6
        phase = rng.uniform(0, math.tau)
        freq = rng.uniform(0.25, 0.55)
        spike = rng.randint(6, 14)
        points = []
        for x in range(x0 + 8, x1 - 8):
            v = math.sin((x - x0) * freq + phase) * amp * 0.45
            if (x - x0) % 34 < 3:
                v -= spike
            points.append((x, round(base + v)))
        draw.line(points, fill=white, width=1)


def render_hal_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The Discovery's main monitor with the hour's subsystem up, HAL's eye
    beside it (see the section comment above)."""
    hour = _clock_hour12(time_str)
    image = Image.new("RGB", (800, 480), SPECTRA6["black"])
    _hal_paint_monitor(image, hour, quote_row)
    draw = ImageDraw.Draw(image)
    _hal_paint_quote(draw, _hal_layout(draw, quote_row))
    _hal_paint_byline(draw, quote_row)
    _crt_paint_scanlines(image, _HAL_MONITOR_RECT, (SPECTRA6["blue"],), period=_HAL_SCANLINE_PERIOD)
    _hal_paint_tiles(image, hour, quote_row)
    _hal_paint_plate(ImageDraw.Draw(image))
    _crt_paint_scanlines(image, _HAL_PLATE_RECT, (SPECTRA6["blue"],), period=_HAL_SCANLINE_PERIOD)
    _hal_paint_eye(image)
    draw = ImageDraw.Draw(image)
    _hal_paint_ship(draw)
    _hal_paint_traces(image, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("hal",), render=render_hal_frame)
