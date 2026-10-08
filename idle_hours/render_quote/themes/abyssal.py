"""The ``abyssal`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from .._paths import META_FONT_BOLD_CANDIDATES, META_FONT_CANDIDATES
from ..fonts import load_font, theme_font_candidates
from ..furniture import _clock_hour12, fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_4x4, pixel_access, snap_image_to_palette
from ..primitives import paint_neon_mask, wrap_quote_into_masks
from ..spec import FrameSpec

# ─── abyssal (deep sea) ──────────────────────────────────────────────────────
#
# A quote read through deep water: a vertical gradient from a seafoam surface
# to near-black, a caustic light net fading out below it, marine snow, and
# bioluminescent jellyfish.
#
# The surface band is the catalogue's **seafoam (G+B+W @ 40/30/30)**, a 3-way
# Bayer partition whose weights fall with depth (turquoise → pure blue).
# Bioluminescence goes through ``paint_neon_mask``: a blue bloom for the prose
# so it sits *in* the water, a mint-green bloom for the matched phrase.
#
# **The hour is a depth.** At 500 m per hour the sounding gauge down the left
# margin runs 500 m at one o'clock to 6000 m at twelve — the floor of the
# abyssal zone. ``time_str`` is therefore used.

_ABYSSAL_SURFACE_BOTTOM = 96     # seafoam band fades to plain blue by here
_ABYSSAL_CAUSTIC_BOTTOM = 172    # the light net dies out by here
_ABYSSAL_DEEP_TOP = 208          # below this the water darkens toward black
_ABYSSAL_QUOTE_RECT = (128, 150, 688, 330)
_ABYSSAL_GAUGE_X = 54
_ABYSSAL_GAUGE_TOP = 62
_ABYSSAL_GAUGE_BOTTOM = 428
_ABYSSAL_METRES_PER_HOUR = 500
# (cx, cy, bell radius) — kept clear of the quote rect and the gauge column.
_ABYSSAL_JELLYFISH = ((252, 392, 25), (566, 374, 19), (712, 236, 14))
_ABYSSAL_SNOW_SEED = 0xA1B255
_ABYSSAL_SNOW_COUNT = 260


def _abyssal_water_ground() -> frozenset:
    """Inks a bloom may overwrite: the water itself, not what is lit in it.

    Excludes white and green so a later halo cannot repaint the caustics, the
    snow or an already-painted jellyfish.
    """
    return frozenset({SPECTRA6["blue"], SPECTRA6["black"]})


def _abyssal_paint_water(image: Image.Image) -> None:
    """The depth gradient: seafoam surface → blue → navy → near-black.

    The surface is a 3-way Bayer partition (white / green / blue) whose white
    and green weights fall linearly with depth; the middle is plain blue; the
    deep band flips blue to black on a rising ramp capped short of solid, since
    a fully black floor reads as a border rather than water.
    """
    px = pixel_access(image)
    width, height = image.size
    blue, white, green, black = (SPECTRA6["blue"], SPECTRA6["white"],
                                 SPECTRA6["green"], SPECTRA6["black"])
    deep_span = max(1, height - _ABYSSAL_DEEP_TOP)
    for y in range(height):
        row = BAYER_4x4[y % 4]
        if y < _ABYSSAL_SURFACE_BOTTOM:
            frac = 1.0 - y / _ABYSSAL_SURFACE_BOTTOM
            # Seafoam G+B+W @ 40/30/30 in 16 Bayer cells: 6 green / 5 blue /
            # 5 white at the surface. Both weights scale with `frac`, so the
            # ratio holds as the band fades into plain blue.
            white_cells = 5.0 * frac
            green_cells = white_cells + 6.0 * frac
            for x in range(width):
                cell = row[x % 4]
                px[x, y] = white if cell < white_cells else (green if cell < green_cells else blue)
        elif y >= _ABYSSAL_DEEP_TOP:
            frac = (y - _ABYSSAL_DEEP_TOP) / deep_span
            black_cells = min(14.0, 16.0 * (frac ** 0.85))
            for x in range(width):
                px[x, y] = black if row[x % 4] < black_cells else blue
        else:
            for x in range(width):
                px[x, y] = blue


def _abyssal_paint_caustics(image: Image.Image) -> None:
    """The rippling net of surface light, thinning with depth.

    A caustic net is a **contour** of the interference field: a thin band
    around the zero crossing (``abs(f) < eps``) is a connected net, where
    thresholding the peaks gives confetti. Two sines alone form a regular
    lattice; the third, incommensurate term warps it into irregular cells.
    Density falls with depth so the band has no visible lower edge.
    """
    px = pixel_access(image)
    width = image.size[0]
    white, blue = SPECTRA6["white"], SPECTRA6["blue"]
    for y in range(min(image.size[1], _ABYSSAL_CAUSTIC_BOTTOM)):
        fade = (1.0 - y / _ABYSSAL_CAUSTIC_BOTTOM) ** 1.2
        density = 6.5 * fade
        if density <= 0:
            continue
        row = BAYER_4x4[y % 4]
        for x in range(width):
            field = (math.sin(x * 0.038 + y * 0.021)
                     + math.sin(x * 0.026 - y * 0.033)
                     + 0.8 * math.sin(x * 0.014 + y * 0.047))
            if abs(field) < 0.13 and row[x % 4] < density and px[x, y] == blue:
                px[x, y] = white


def _abyssal_paint_snow(image: Image.Image) -> None:
    """Marine snow — the constant drift of detritus that makes water read as deep.

    Seeded, so a given frame is byte-identical on re-render. Skips the surface
    band, where it would be lost in the caustics anyway.
    """
    rng = random.Random(_ABYSSAL_SNOW_SEED)
    px = pixel_access(image)
    width, height = image.size
    white = SPECTRA6["white"]
    ground = _abyssal_water_ground()
    # Clamp the start to the canvas: on a short /api/preview thumbnail the band
    # start can sit below the image, and randrange raises on an empty range.
    y_min = min(_ABYSSAL_CAUSTIC_BOTTOM // 2, max(0, height - 1))
    for _ in range(_ABYSSAL_SNOW_COUNT):
        x = rng.randrange(width)
        y = rng.randrange(y_min, height)
        if px[x, y] not in ground:
            continue
        px[x, y] = white
        if rng.random() < 0.22 and x + 1 < width and y + 1 < height:
            if px[x + 1, y] in ground:
                px[x + 1, y] = white


def _abyssal_paint_jellyfish(image: Image.Image, cx: int, cy: int, radius: int) -> None:
    """One bioluminescent jellyfish: a domed bell over trailing tentacles.

    One mask, so bell and tentacles share one bloom (separate blooms
    double-expose where the halos meet). White core, green halo.
    """
    mask = Image.new("L", image.size, 0)
    mdraw = ImageDraw.Draw(mask)
    # Bell: a hollow arc, not a filled dome, so the water shows through and it
    # reads as translucent.
    mdraw.arc((cx - radius, cy - radius, cx + radius, cy + radius), 180, 360, fill=255, width=2)
    mdraw.line((cx - radius, cy, cx + radius, cy), fill=255, width=2)
    # A couple of radial ribs inside the bell, the way a real medusa is veined.
    for rib in (-0.5, 0.0, 0.5):
        rx = cx + int(radius * rib * 0.8)
        mdraw.line((rx, cy - int(radius * (0.82 - abs(rib) * 0.5)), rx, cy), fill=255, width=1)
    # Tentacles: wavy lines trailing below, each with its own phase.
    for index in range(5):
        offset = cx + int((index - 2) * radius * 0.42)
        phase = index * 1.1
        length = int(radius * (2.6 + 0.5 * math.sin(phase)))
        prev = (offset, cy)
        for step in range(1, length, 3):
            sway = int(round(radius * 0.28 * math.sin(step * 0.16 + phase)))
            point = (offset + sway, cy + step)
            mdraw.line((prev[0], prev[1], point[0], point[1]), fill=255, width=1)
            prev = point
    paint_neon_mask(image, mask, SPECTRA6["white"], SPECTRA6["green"],
                    radius=max(3, radius // 3), gamma=2.0, cap=0.62,
                    ground=_abyssal_water_ground())


def _abyssal_paint_gauge(image: Image.Image, draw: ImageDraw.ImageDraw, hour: int) -> None:
    """Sounding gauge down the left margin — the hour, read as a depth.

    Twelve graduations at 500 m each (bottoming out at 6000 m). The current
    hour gets a filled marker and a label; every third graduation is long and
    numbered.
    """
    white, green = SPECTRA6["white"], SPECTRA6["green"]
    top, bottom = _ABYSSAL_GAUGE_TOP, _ABYSSAL_GAUGE_BOTTOM
    x = _ABYSSAL_GAUGE_X
    draw.line((x, top, x, bottom), fill=white, width=1)
    step = (bottom - top) / 12.0
    label_font = load_font(META_FONT_CANDIDATES, size=11)
    for mark in range(1, 13):
        y = top + step * mark
        long_mark = mark % 3 == 0
        draw.line((x, y, x + (13 if long_mark else 7), y), fill=white, width=1)
        # Skip the graduation numeral on the hour's own mark — the green marker
        # label lands in the same place and the two overprint into mush (most
        # visibly at 12 o'clock, where both read "6000").
        if long_mark and mark != hour:
            draw.text((x + 17, y), f"{mark * _ABYSSAL_METRES_PER_HOUR}", font=label_font,
                      fill=white, anchor="lm")
    # The hour: a filled marker, drawn last so it sits over its graduation.
    marker_y = top + step * hour
    draw.polygon([(x - 9, marker_y - 5), (x - 1, marker_y), (x - 9, marker_y + 5)], fill=green)
    depth_font = load_font(META_FONT_BOLD_CANDIDATES, size=12)
    draw.text((x + 17, marker_y), f"{hour * _ABYSSAL_METRES_PER_HOUR} m", font=depth_font,
              fill=green, anchor="lm")


def _abyssal_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> int:
    """The quote, lit like everything else down here. Returns the block bottom.

    Two masks, as in izakaya: white cores throughout, a blue bloom on the body
    and a mint-green bloom on the matched phrase.
    """
    cool, hot, bottom = wrap_quote_into_masks(
        draw, image.size, quote_row, _ABYSSAL_QUOTE_RECT,
        theme="abyssal", line_height_mult=1.38,
    )
    ground = _abyssal_water_ground()
    paint_neon_mask(image, cool, SPECTRA6["white"], SPECTRA6["blue"],
                    radius=6, gamma=2.1, cap=0.55, ground=ground)
    paint_neon_mask(image, hot, SPECTRA6["white"], SPECTRA6["green"],
                    radius=6, gamma=1.9, cap=0.7, ground=ground)
    return bottom


def _abyssal_paint_credits(image: Image.Image, draw: ImageDraw.ImageDraw,
                           quote_row: dict, top: int) -> None:
    """author · title below the quote, unlit — a label, not a light source."""
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or fallback_title(quote_row) or "").strip()
    parts = [p for p in (author, title) if p]
    if not parts:
        return
    text = "  ·  ".join(parts)
    font = load_font(theme_font_candidates("abyssal", "ornament"), size=14)
    width = image.size[0]
    max_w = max(40, width - 260)
    while len(text) > 1 and draw.textlength(text, font=font) > max_w:
        text = text[:-2].rstrip(" ·") + "…"
    y = min(max(top + 14, _ABYSSAL_QUOTE_RECT[3] - 2), image.size[1] - 40)
    draw.text((width // 2, y), text, font=font, fill=SPECTRA6["white"], anchor="ma")


def render_abyssal_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Deep sea (see the module section comment above).

    Laid out against the canonical 800×480; smaller canvases (``/api/preview``
    thumbnails) crop rather than reflow. Raw pixel writes clamp to
    ``image.size``; the gauge and credits use ``ImageDraw``, which clips.
    """
    image = Image.new("RGB", (width, height), color=SPECTRA6["blue"])
    _abyssal_paint_water(image)
    _abyssal_paint_caustics(image)
    _abyssal_paint_snow(image)
    for cx, cy, radius in _ABYSSAL_JELLYFISH:
        _abyssal_paint_jellyfish(image, cx, cy, radius)
    draw = ImageDraw.Draw(image)
    _abyssal_paint_gauge(image, draw, _clock_hour12(time_str))
    block_bottom = _abyssal_paint_quote(image, draw, quote_row)
    _abyssal_paint_credits(image, draw, quote_row, block_bottom)
    return snap_image_to_palette(image, SPECTRA6_PALETTE)


SPEC = FrameSpec(themes=("abyssal",), render=render_abyssal_frame)
