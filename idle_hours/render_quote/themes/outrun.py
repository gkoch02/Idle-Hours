"""The ``outrun`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import random

from PIL import Image, ImageDraw

from .._paths import ANTONIO_VARIABLE, META_FONT_BOLD_CANDIDATES, META_FONT_CANDIDATES
from ..fonts import _font_ascent, load_font, normalize_dashes
from ..furniture import fallback_title
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_4x4, snap_image_to_palette
from ..spec import FrameSpec
from ..text import draw_text_dithered

# ── outrun (synthwave) ──────────────────────────────────────────────────────
# Reference geometry is the 800×480 panel. All raw PixelAccess writes are
# bounds-clipped (/api/preview renders down to ~60 px tall), so a shorter
# canvas just crops the lower composition.
_OUTRUN_HORIZON = 300                  # sky/grid divide
_OUTRUN_SUN_CENTER = (400, 332)        # disc centre sits below the horizon …
_OUTRUN_SUN_RADIUS = 132               # … so only the upper cap shows as a half-sun
_OUTRUN_QUOTE_RECT = (60, 38, 740, 150)  # x0, y0, x1, y1 — quote block in the dark sky
_OUTRUN_STAR_SEED = 0x07A50


def _outrun_line_points(x0: int, y0: int, x1: int, y1: int):
    """Integer Bresenham point list — PIL has no per-pixel line colour, and the
    neon grid lines alternate two inks per pixel to synthesise magenta / cyan."""
    points = []
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
    return points


def _outrun_paint_sky(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """Vertical Bayer-gradient twilight sky + deterministic stars.

    Two stacked density ramps: indigo navy (blue + black) at the zenith fading
    to pure blue, then blue gaining red toward a purple horizon. The ink pair
    swaps where the black density reaches 0, so there is no visible seam. Warm
    colour is reserved for the sun, keeping the white quote high-contrast.
    """
    width, height = image.size
    BLUE = SPECTRA6["blue"]
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    WHITE = SPECTRA6["white"]
    horizon = _OUTRUN_HORIZON
    px = image.load()
    for y in range(min(horizon, height)):
        frac = y / horizon
        if frac < 0.42:
            # Zenith indigo navy → pure blue (black wash 0.55 → 0).
            d = 0.55 * (1 - frac / 0.42)
            dark, light = BLUE, BLACK
        else:
            # Blue → purple at the horizon. Red density peaks at 0.36 (not
            # 50/50): red out-luminates blue, so an even mix reads hot.
            d = 0.36 * ((frac - 0.42) / 0.58)
            dark, light = BLUE, RED
        threshold = round(d * 16)
        row = BAYER_4x4[y % 4]
        for x in range(width):
            px[x, y] = light if row[x % 4] < threshold else dark
    # Stars — deterministic white specks in the upper sky, above the sun cap.
    rng = random.Random(_OUTRUN_STAR_SEED)
    star_ceiling = min(_OUTRUN_SUN_CENTER[1] - _OUTRUN_SUN_RADIUS - 4, height - 1)
    for _ in range(70):
        sx = rng.randint(4, width - 4)
        sy = rng.randint(6, max(7, star_ceiling))
        if 0 <= sx < width and 0 <= sy < height:
            px[sx, sy] = WHITE
            if rng.random() < 0.18 and sx + 1 < width and sy + 1 < height:
                px[sx + 1, sy] = WHITE
                px[sx, sy + 1] = WHITE


def _outrun_paint_grid(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """Dark ground + neon perspective grid + a bright horizon line.

    Magenta verticals (red/blue per-pixel alternation) fan out from a central
    vanishing point; cyan horizontals (green/blue alternation) are spaced
    densest near the horizon. The alternation reads as solid neon at distance.
    """
    width, height = image.size
    BLUE = SPECTRA6["blue"]
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    GREEN = SPECTRA6["green"]
    WHITE = SPECTRA6["white"]
    horizon = _OUTRUN_HORIZON
    if horizon >= height:
        return
    px = image.load()
    # Dark near-black ground with a faint blue tint so the neon grid pops.
    for y in range(horizon, height):
        row = BAYER_4x4[y % 4]
        for x in range(width):
            px[x, y] = BLUE if row[x % 4] < 2 else BLACK
    # Vertical magenta lines fanning from the vanishing point to the foot.
    vp_x = width // 2
    for k in range(-9, 10):
        bx = vp_x + k * 96
        for (x, y) in _outrun_line_points(vp_x, horizon, bx, height - 1):
            if 0 <= x < width and horizon <= y < height:
                px[x, y] = RED if (x + y) & 1 else BLUE
    # Horizontal cyan lines, perspective-spaced (t² → tight near the horizon).
    rows = 9
    span = height - horizon
    for i in range(1, rows + 1):
        t = i / rows
        yy = horizon + int(span * (t * t))
        if yy >= height:
            yy = height - 1
        for x in range(width):
            px[x, yy] = GREEN if (x + yy) & 1 else BLUE
    # Bright horizon line with a cyan under-glow.
    for x in range(width):
        for hy in (horizon - 1, horizon):
            if 0 <= hy < height:
                px[x, hy] = WHITE
        gy = horizon + 1
        if gy < height:
            px[x, gy] = GREEN if x & 1 else BLUE


def _outrun_paint_sun(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """The retrowave half-sun: a warm gradient disc cap sliced by widening slits.

    Only the cap above the horizon is painted (the centre sits below it). The
    cap carries a golden → tangerine → magenta gradient across its *visible*
    height, and unpainted slits, widening toward the horizon, let the sky show
    through.
    """
    width, height = image.size
    BLUE = SPECTRA6["blue"]
    RED = SPECTRA6["red"]
    YELLOW = SPECTRA6["yellow"]
    cx, cy = _OUTRUN_SUN_CENTER
    R = _OUTRUN_SUN_RADIUS
    horizon = _OUTRUN_HORIZON
    top_vis = cy - R
    if top_vis >= horizon or top_vis >= height:
        return
    # Slit bands: y-intervals (left unpainted) widening toward the horizon.
    slits = []
    pos = horizon
    i = 0
    while pos > top_vis + 34:
        gap = max(2, 14 - i * 3)
        slits.append((pos - gap, pos))
        pos -= gap + 7
        i += 1

    def in_slit(yy: int) -> bool:
        for lo, hi in slits:
            if lo <= yy < hi:
                return True
        return False

    visible_h = horizon - top_vis
    px = image.load()
    y_lo = max(0, top_vis)
    y_hi = min(horizon, height)
    for y in range(y_lo, y_hi):
        if in_slit(y):
            continue
        # Vertical position across the *visible* cap (0 top → 1 at horizon).
        tv = (y - top_vis) / visible_h
        if tv < 0.34:
            dark, light, d = RED, YELLOW, 0.60      # warm golden crown
        elif tv < 0.66:
            dark, light, d = RED, YELLOW, 0.375     # tangerine body
        else:
            dark, light, d = RED, BLUE, 0.42        # magenta foot melting into the sky
        threshold = round(d * 16)
        row = BAYER_4x4[y % 4]
        # Horizontal span of the disc at this row.
        half = int((R * R - (y - cy) ** 2) ** 0.5)
        x_lo = max(0, cx - half)
        x_hi = min(width, cx + half)
        for x in range(x_lo, x_hi):
            px[x, y] = light if (d > 0 and row[x % 4] < threshold) else dark


def _outrun_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The literary quote in white Oxanium, matched phrase in synthesised magenta.

    Centred line-by-line in the dark upper sky; the body is solid white. The
    matched phrase is a 5/8:3/8 red+blue stipple: red-biased because a 50/50
    mix's blue half melts into the blue sky behind it and reads dim.
    """
    width = image.size[0]
    WHITE = SPECTRA6["white"]
    BLUE = SPECTRA6["blue"]
    RED = SPECTRA6["red"]
    x0, y0, x1, y1 = _OUTRUN_QUOTE_RECT
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    matched = quote_row.get("matched_text") or ""
    quote_font, quote_font_bold, wrapped, line_height, _ = fit_quote(
        draw, display_quote, matched, x1 - x0, y1 - y0,
        font_max=36, font_min=15, line_height_mult=1.18, theme="outrun",
    )
    block_h = len(wrapped) * line_height
    y = y0 + max(0, ((y1 - y0) - block_h) // 2)
    ascent = _font_ascent(quote_font)
    for line in wrapped:
        start = 0
        while start < len(line) and line[start][0].strip() == "":
            start += 1
        end = len(line)
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        drawable = line[start:end]
        line_w = 0
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            bbox = draw.textbbox((0, 0), chunk, font=font)
            line_w += bbox[2] - bbox[0]
        x = (width - line_w) // 2
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            chunk_y = y + (ascent - _font_ascent(font))
            if is_bold and chunk.strip():
                draw_text_dithered(image, (x, chunk_y), chunk, font, dark=RED, light=BLUE, light_density=0.375)
            else:
                draw.text((x, chunk_y), chunk, font=font, fill=WHITE)
            bbox = draw.textbbox((0, 0), chunk, font=font)
            x += bbox[2] - bbox[0]
        y += line_height


def _outrun_paint_credits(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """Author (white) + title (magenta) credit line below the quote, in Antonio.

    Sits between the quote block and the sun cap. The title uses the matched
    phrase's red-biased magenta stipple so it holds against the blue sky.
    """
    width = image.size[0]
    WHITE = SPECTRA6["white"]
    BLUE = SPECTRA6["blue"]
    RED = SPECTRA6["red"]
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "")
    y = _OUTRUN_QUOTE_RECT[3] + 8
    max_w = width - 120
    if author:
        font = load_font([(ANTONIO_VARIABLE, "Bold"), *META_FONT_BOLD_CANDIDATES], size=15)
        text = author.upper()
        while text and draw.textlength(text, font=font) > max_w:
            text = text[:-1]
        bbox = draw.textbbox((0, 0), text, font=font)
        fx = (width - (bbox[2] - bbox[0])) // 2 - bbox[0]
        draw.text((fx, y - bbox[1]), text, font=font, fill=WHITE)
        y += (bbox[3] - bbox[1]) + 5
    if title:
        font = load_font([(ANTONIO_VARIABLE, "Regular"), *META_FONT_CANDIDATES], size=13)
        text = title
        while text and draw.textlength(f"— {text} —", font=font) > max_w:
            text = text[:-1]
        label = f"— {text} —"
        bbox = draw.textbbox((0, 0), label, font=font)
        fx = (width - (bbox[2] - bbox[0])) // 2 - bbox[0]
        draw_text_dithered(image, (fx, y - bbox[1]), label, font, dark=RED, light=BLUE, light_density=0.375)


def render_outrun_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """1980s synthwave / Outrun sunset (see the module section comment above).

    ``time_str`` is unused (the matched phrase carries the time); kept for
    dispatch-signature uniformity.
    """
    del time_str  # see docstring; deliberately unused.
    image = Image.new("RGB", (width, height), color=SPECTRA6["black"])
    draw = ImageDraw.Draw(image)
    _outrun_paint_sky(image, draw)
    _outrun_paint_grid(image, draw)
    _outrun_paint_sun(image, draw)
    _outrun_paint_quote(image, draw, quote_row)
    _outrun_paint_credits(image, draw, quote_row)
    return snap_image_to_palette(image, SPECTRA6_PALETTE)


SPEC = FrameSpec(themes=("outrun",), render=render_outrun_frame)
