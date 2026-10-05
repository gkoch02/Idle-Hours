"""The ``oblivion`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .._paths import EXO2_VARIABLE, META_FONT_CANDIDATES
from ..fonts import load_font
from ..furniture import _clock_hour12, _paint_placed, _place_quote, _row_digest, fallback_title
from ..palette import _PANEL_INKS, SPECTRA6, SPECTRA6_PALETTE, _dither_calibrated, snap_image_to_palette
from ..primitives import _shade_silhouette, _smooth_noise, _soft_ellipse_mask, paint_neon_mask, shade_height_field
from ..text import draw_tracked, fit_text_to_width

# ---------------------------------------------------------------------------
# oblivion — *Oblivion* (2013): the Sky Tower's light table
# ---------------------------------------------------------------------------
# The Sky Tower's desk is a light table whose glass is the interface: a glow
# pooled under the hand, frosted panes, hairline geometry, a topographic map
# with the hydro rigs, a drone, and one warm accent. Full design notes:
# docs/themes.md (``oblivion``).
#
# The glass (grey edges, a white pool under the quote, darker soft-edged
# panes, the drone's blurred shadow, a fine grain) and the drone (a sphere
# shaded by ``shade_height_field``, pods by ``_shade_silhouette``) are painted in
# continuous tone and Floyd–Steinberg dithered to white and black
# (``_dither_calibrated``). The map's contours (a seeded height field sliced at
# ``_OBLIVION_CONTOUR_LEVELS`` levels, each slice's one-pixel rim), the
# hairlines, the type and the red go on after the dither.
#
# The hour is the rig and the bearing: the hour's rig is red with a leader to
# its number, the dial's tick at the hour's clock-face position is a red wedge
# with a red dot on station, and the hour's cell in the status row is filled.
# All pinned across the minutes; the matched phrase carries the minute. The
# waveform and numeral columns are seeded from the quote. Composed at 800x480
# and NEAREST-downsampled otherwise (the ``metro`` convention).
# ---------------------------------------------------------------------------
_OBLIVION_SEED = 0x4F424C56           # OBLV
_OBLIVION_INKS = ("white", "black")
_OBLIVION_QUOTE_RECT = (40, 112, 450, 366)
_OBLIVION_BYLINE_Y = 380
_OBLIVION_MAP_RECT = (470, 104, 770, 398)
_OBLIVION_DIAL_CENTRE = (600, 270)
_OBLIVION_DIAL_RADII = (112, 86, 34)
_OBLIVION_DRONE_CENTRE = (728, 146)
_OBLIVION_DRONE_RADIUS = 34
_OBLIVION_WAVE_RECT = (40, 416, 450, 458)
_OBLIVION_RIG_BAND = (470, 416, 770, 458)
_OBLIVION_RIG_GAP = 4
_OBLIVION_CONTOUR_LEVELS = 5
_OBLIVION_SCENE: dict = {}
# Calibrated end points of ``_oblivion_tone``: the white ink is the pool.
_OBLIVION_WHITE = _PANEL_INKS["white"]
_OBLIVION_BLACK = _PANEL_INKS["black"]


def _oblivion_tone(t: float) -> tuple[int, int, int]:
    """A grey ``t`` of the way from the white ink to the black ink."""
    return tuple(round(w + (k - w) * t) for w, k in zip(_OBLIVION_WHITE, _OBLIVION_BLACK))


def _oblivion_font(size: int, instance: str = "Light"):
    return load_font([(EXO2_VARIABLE, instance), *META_FONT_CANDIDATES], size=size)


def _oblivion_polar(radius: float, hour: int) -> tuple[float, float]:
    cx, cy = _OBLIVION_DIAL_CENTRE
    a = math.radians((hour % 12) * 30)
    return cx + radius * math.sin(a), cy - radius * math.cos(a)


def _oblivion_rig_rects() -> list:
    x0, y0, x1, y1 = _OBLIVION_RIG_BAND
    width = (x1 - x0 - 11 * _OBLIVION_RIG_GAP) // 12
    return [(x0 + i * (width + _OBLIVION_RIG_GAP), y0, x0 + i * (width + _OBLIVION_RIG_GAP) + width, y1)
            for i in range(12)]


def _oblivion_numeral_rect() -> tuple[int, int, int, int]:
    """The column of readouts at the map's upper left, under its label."""
    x0, y0, x1, y1 = _OBLIVION_MAP_RECT
    return (x0 + 4, y0 + 22, x0 + 62, y0 + 92)


def _oblivion_rig_points() -> list:
    """The twelve rigs' positions on the map, seeded, kept off the dial's
    hub and inside the pane."""
    rng = random.Random(_OBLIVION_SEED + 3)
    x0, y0, x1, y1 = _OBLIVION_MAP_RECT
    cx, cy = _OBLIVION_DIAL_CENTRE
    points = []
    while len(points) < 12:
        x, y = rng.randint(x0 + 22, x1 - 22), rng.randint(y0 + 22, y1 - 22)
        if math.hypot(x - cx, y - cy) < _OBLIVION_DIAL_RADII[2] + 14:
            continue
        if math.hypot(x - _OBLIVION_DRONE_CENTRE[0], y - _OBLIVION_DRONE_CENTRE[1]) < _OBLIVION_DRONE_RADIUS + 26:
            continue
        nx0, ny0, nx1, ny1 = _oblivion_numeral_rect()
        if nx0 - 12 <= x <= nx1 + 20 and ny0 - 12 <= y <= ny1 + 12:
            continue
        if any(math.hypot(x - px, y - py) < 30 for px, py in points):
            continue
        points.append((x, y))
    return points


def _oblivion_paint_glass(scene: Image.Image) -> Image.Image:
    """The light table in continuous tone: grey glass, the white pool under
    the quote, the frosted panes, the drone's shadow, the grain. Returns the
    pool's mask, whose saturated heart is cleaned after the dither."""
    size = scene.size
    scene.paste(Image.new("RGB", size, _oblivion_tone(0.07)), (0, 0))
    # Saturated inside so the pool's heart is clean white; the blur only softens its edge.
    pool = _soft_ellipse_mask(size, (-60, 30, 540, 430), 50).point(lambda v: min(255, v * 2))
    scene.paste(Image.new("RGB", size, _OBLIVION_WHITE), (0, 0), pool)
    # The panes: the map and the two strips, a shade darker with soft edges.
    for rect in (_OBLIVION_MAP_RECT, _OBLIVION_WAVE_RECT, _OBLIVION_RIG_BAND):
        pane = Image.new("L", size, 0)
        ImageDraw.Draw(pane).rectangle(rect, fill=255)
        pane = pane.filter(ImageFilter.GaussianBlur(2)).point(lambda v: int(v * 0.55))
        scene.paste(Image.new("RGB", size, _oblivion_tone(0.13)), (0, 0), pane)
    # The drone's shadow on the glass beneath it.
    dx, dy = _OBLIVION_DRONE_CENTRE
    r = _OBLIVION_DRONE_RADIUS
    shadow = _soft_ellipse_mask(size, (dx - r + 2, dy + r + 6, dx + r + 12, dy + r + 22), 6).point(lambda v: int(v * 0.4))
    scene.paste(Image.new("RGB", size, _oblivion_tone(0.34)), (0, 0), shadow)
    # The glass's grain, kept out of the pool so the quote sits on clean white.
    grain = _smooth_noise(size, (120, 72), _OBLIVION_SEED + 1).point(lambda v: v * 6 // 255)
    grain = ImageChops.multiply(grain, pool.point(lambda v: 255 - v))
    scene.paste(ImageChops.subtract(ImageChops.add(scene, Image.merge("RGB", (grain, grain, grain))),
                                    Image.new("RGB", size, (3, 3, 3))))
    shadow.close()
    return pool


def _oblivion_paint_drone_tone(scene: Image.Image) -> None:
    """The drone before the dither: a shaded sphere and two shaded pods."""
    size = scene.size
    cx, cy = _OBLIVION_DRONE_CENTRE
    r = _OBLIVION_DRONE_RADIUS
    pods = Image.new("L", size, 0)
    pd = ImageDraw.Draw(pods)
    pd.rounded_rectangle((cx - r - 16, cy - 9, cx - r + 8, cy + 11), radius=5, fill=255)
    pd.rounded_rectangle((cx + r - 8, cy - 9, cx + r + 16, cy + 11), radius=5, fill=255)
    shaded = _shade_silhouette(pods, _oblivion_tone(0.34), _oblivion_tone(0.08), _oblivion_tone(0.66), offset=4, blur=3)
    disc = Image.new("L", size, 0)
    ImageDraw.Draw(disc).ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    field = disc.filter(ImageFilter.GaussianBlur(r * 0.55))
    tone = shade_height_field(field, relief=0.03, ambient=0.18, diffuse=0.75, specular=0.9, shininess=30)
    # Map the shading onto the white hull: lit faces to the white ink, the
    # terminator toward a mid grey, never full black — it is white plastic.
    def hull_tone(v, lo=60, hi=150):
        t = max(0.0, min(1.0, (v - lo) / (hi - lo)))
        return _oblivion_tone(0.55 * (1.0 - t))

    lut = [hull_tone(v) for v in range(256)]
    hull = Image.merge("RGB", tuple(tone.point([lut[v][c] for v in range(256)]) for c in range(3)))
    scene.paste(hull, (0, 0), disc)
    # The pods, mounted either side of the hull.
    scene.paste(shaded, (0, 0), ImageChops.subtract(pods, disc))
    for m in (pods, shaded, disc, field, tone, hull):
        m.close()


def _oblivion_contours(size) -> Image.Image:
    """The map's contour lines as an ``L`` mask: a seeded height field
    sliced at ``_OBLIVION_CONTOUR_LEVELS`` levels, each slice's one-pixel rim."""
    x0, y0, x1, y1 = _OBLIVION_MAP_RECT
    w, h = x1 - x0, y1 - y0
    field = _smooth_noise((w, h), (5, 4), _OBLIVION_SEED + 2)
    lines = Image.new("L", (w, h), 0)
    for level in range(1, _OBLIVION_CONTOUR_LEVELS + 1):
        cut = round(255 * level / (_OBLIVION_CONTOUR_LEVELS + 1))
        slab = field.point(lambda v, c=cut: 255 if v >= c else 0)
        rim = ImageChops.subtract(slab, slab.filter(ImageFilter.MinFilter(3)))
        lines = ImageChops.lighter(lines, rim)
    mask = Image.new("L", size, 0)
    mask.paste(lines, (x0 + 1, y0 + 1))
    inner = Image.new("L", size, 0)
    idr = ImageDraw.Draw(inner)
    idr.rectangle((x0 + 2, y0 + 2, x1 - 2, y1 - 2), fill=255)
    # The hub of the dial and the drone's station are clear glass.
    cx, cy = _OBLIVION_DIAL_CENTRE
    r1 = _OBLIVION_DIAL_RADII[1]
    idr.ellipse((cx - r1, cy - r1, cx + r1, cy + r1), fill=0)
    # And the numeral column at the pane's upper left.
    idr.rectangle(_oblivion_numeral_rect(), fill=0)
    dx, dy = _OBLIVION_DRONE_CENTRE
    dr = _OBLIVION_DRONE_RADIUS + 4
    idr.ellipse((dx - dr, dy - dr, dx + dr, dy + dr), fill=0)
    return ImageChops.multiply(mask, inner)


def _oblivion_scene() -> Image.Image:
    """The glass, the panes, the drone and the contours — everything the
    hour and the quote do not touch. Painted once per process."""
    key = (_oblivion_paint_glass, _oblivion_paint_drone_tone, _oblivion_contours)
    cached = _OBLIVION_SCENE.get("frame")
    if cached is not None and cached[0] == key:
        return cached[1]
    size = (800, 480)
    scene = Image.new("RGB", size, _OBLIVION_WHITE)
    pool = _oblivion_paint_glass(scene)
    _oblivion_paint_drone_tone(scene)
    image = _dither_calibrated(scene, _OBLIVION_INKS)
    # Error diffusion carries the grey glass's residue a little way into the
    # pool; wipe its saturated heart back to white.
    if pool is not None:        # the decoration fence neuters the glass painter
        image.paste(Image.new("RGB", size, SPECTRA6["white"]), (0, 0), pool.point(lambda v: 255 if v == 255 else 0))
        pool.close()
    image.paste(Image.new("RGB", size, SPECTRA6["black"]), (0, 0), _oblivion_contours(size))
    _OBLIVION_SCENE["frame"] = (key, image)
    return image


def _oblivion_paint_chrome(draw: ImageDraw.ImageDraw) -> None:
    """Corner brackets, the header's tracked capitals, the pane borders and
    the rules."""
    black = SPECTRA6["black"]
    for (x, y), (dx, dy) in (((20, 20), (1, 1)), ((780, 20), (-1, 1)), ((20, 460), (1, -1)), ((780, 460), (-1, -1))):
        draw.line((x, y, x + 18 * dx, y), fill=black, width=1)
        draw.line((x, y, x, y + 18 * dy), fill=black, width=1)
    font = _oblivion_font(13, "Regular")
    draw_tracked(draw, (40, 44), "TECH 49", _oblivion_font(22, "Regular"), black, tracking=4)
    draw_tracked(draw, (40, 74), "TOWER 49   ·   TET LINK ESTABLISHED", font, black, tracking=3)
    draw_tracked(draw, (760, 48), "SKY TOWER", font, black, tracking=3, anchor_right=True)
    draw_tracked(draw, (760, 68), "DRONE 166   ONLINE", font, black, tracking=3, anchor_right=True)
    draw.line((40, 96, 760, 96), fill=black, width=1)
    for rect in (_OBLIVION_MAP_RECT, _OBLIVION_WAVE_RECT, _OBLIVION_RIG_BAND):
        draw.rectangle(rect, outline=black, width=1)
    small = _oblivion_font(9, "Regular")
    x0, y0, x1, y1 = _OBLIVION_MAP_RECT
    draw.rectangle((x0 + 1, y0 + 1, x0 + 118, y0 + 18), fill=SPECTRA6["white"])
    draw_tracked(draw, (x0 + 8, y0 + 6), "SECTOR 17   ·   TOPO", small, black, tracking=2)
    draw_tracked(draw, (_OBLIVION_WAVE_RECT[0] + 8, _OBLIVION_WAVE_RECT[1] + 4), "HYDRO FLOW", small, black, tracking=2)
    draw_tracked(draw, (_OBLIVION_RIG_BAND[0] + 8, _OBLIVION_RIG_BAND[1] - 12), "RIG STATUS", small, black, tracking=2)


def _oblivion_paint_dial(draw: ImageDraw.ImageDraw, hour: int) -> None:
    """The dial over the map: hairline rings, a crosshair, twelve ticks, the
    hour's tick as a red wedge and a red dot on station."""
    black, red = SPECTRA6["black"], SPECTRA6["red"]
    cx, cy = _OBLIVION_DIAL_CENTRE
    r0, r1, r2 = _OBLIVION_DIAL_RADII
    for r in (r0, r1, r2):
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=black, width=1)
    draw.line((cx - r2 - 8, cy, cx + r2 + 8, cy), fill=black, width=1)
    draw.line((cx, cy - r2 - 8, cx, cy + r2 + 8), fill=black, width=1)
    draw.rectangle((cx - 4, cy - 4, cx + 4, cy + 4), fill=black)
    font = _oblivion_font(10, "Regular")
    for h in range(1, 13):
        (ax, ay), (bx, by) = _oblivion_polar(r0, h), _oblivion_polar(r0 - 8, h)
        draw.line((ax, ay, bx, by), fill=black, width=1)
        lx, ly = _oblivion_polar(r0 + 11, h)
        label = f"{(h % 12) * 30:03d}"
        draw.text((lx - draw.textlength(label, font=font) / 2, ly - 5), label, font=font, fill=black)
    a = math.radians((hour % 12) * 30)
    wedge = [(cx + r0 * math.sin(a + d), cy - r0 * math.cos(a + d)) for d in (-0.06, 0.06)]
    wedge += [(cx + (r0 - 12) * math.sin(a + d), cy - (r0 - 12) * math.cos(a + d)) for d in (0.06, -0.06)]
    draw.polygon(wedge, fill=red)
    dx, dy = _oblivion_polar((r1 + r2) / 2, hour)
    draw.ellipse((dx - 5, dy - 5, dx + 5, dy + 5), fill=red)
    draw.ellipse((dx - 9, dy - 9, dx + 9, dy + 9), outline=black, width=1)


def _oblivion_paint_rigs(image: Image.Image, hour: int) -> None:
    """The rigs on the map as hairline glyphs with their numbers; the hour's
    in red with a leader. And the status row along the foot, the hour's
    cell filled."""
    draw = ImageDraw.Draw(image)
    black, white, red = SPECTRA6["black"], SPECTRA6["white"], SPECTRA6["red"]
    font = _oblivion_font(9, "Regular")
    for i, (x, y) in enumerate(_oblivion_rig_points()):
        active = (i + 1) == hour
        if active:
            draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=red)
            draw.ellipse((x - 10, y - 10, x + 10, y + 10), outline=red, width=1)
            # The leader runs toward the pane's centre so the label stays inside it.
            side = -1 if x > (_OBLIVION_MAP_RECT[0] + _OBLIVION_MAP_RECT[2]) / 2 else 1
            draw.line((x + 10 * side, y, x + 24 * side, y - 12), fill=red, width=1)
            label = f"RIG {i + 1:02d}"
            lx = x + 26 if side > 0 else x - 26 - draw.textlength(label, font=font)
            draw.text((lx, y - 18), label, font=font, fill=red, stroke_width=2, stroke_fill=white)
        else:
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=white, outline=black, width=1)
            draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill=black)
            draw.text((x + 8, y - 5), f"{i + 1:02d}", font=font, fill=black, stroke_width=2, stroke_fill=white)
    cell_font = _oblivion_font(9, "Regular")
    for i, (x0, y0, x1, y1) in enumerate(_oblivion_rig_rects()):
        active = (i + 1) == hour
        draw.rectangle((x0, y0 + 14, x1, y1 - 4), fill=black if active else None, outline=black, width=1)
        ink = white if active else black
        label = f"{i + 1:02d}"
        draw.text((x0 + (x1 - x0 - draw.textlength(label, font=cell_font)) / 2, y0 + 17), label, font=cell_font,
                  fill=ink)
        if active:
            draw.ellipse(((x0 + x1) / 2 - 3, y1 - 15, (x0 + x1) / 2 + 3, y1 - 9), fill=red)
        else:
            draw.rectangle(((x0 + x1) / 2 - 4, y1 - 13, (x0 + x1) / 2 + 4, y1 - 11), fill=black)


def _oblivion_paint_drone_detail(image: Image.Image) -> None:
    """After the dither: the lens, its catchlight, a red bloom into the
    glass, and the hull's seam."""
    draw = ImageDraw.Draw(image)
    cx, cy = _OBLIVION_DRONE_CENTRE
    r = _OBLIVION_DRONE_RADIUS
    black, white, red = SPECTRA6["black"], SPECTRA6["white"], SPECTRA6["red"]
    lx, ly = cx - 8, cy - 4
    glow = Image.new("L", image.size, 0)
    ImageDraw.Draw(glow).ellipse((lx - 9, ly - 9, lx + 9, ly + 9), fill=255)
    paint_neon_mask(image, glow, None, red, radius=5, gamma=1.8, cap=0.4, ground=(white,))
    glow.close()
    draw.ellipse((lx - 9, ly - 9, lx + 9, ly + 9), fill=red, outline=black, width=1)
    draw.ellipse((lx - 4, ly - 4, lx + 4, ly + 4), fill=black)
    draw.ellipse((lx - 6, ly - 7, lx - 3, ly - 4), fill=white)
    draw.arc((cx - r, cy - r, cx + r, cy + r), 200, 340, fill=black, width=1)
    for x0, x1 in ((cx - r - 16, cx - r + 8), (cx + r - 8, cx + r + 16)):
        draw.rounded_rectangle((x0, cy - 9, x1, cy + 11), radius=5, outline=black, width=1)


def _oblivion_paint_data(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The waveform strip and the numeral columns, seeded from the quote."""
    black = SPECTRA6["black"]
    rng = random.Random(_OBLIVION_SEED ^ _row_digest(quote_row))
    x0, y0, x1, y1 = _OBLIVION_WAVE_RECT
    base = (y0 + y1) / 2 + 7
    amp = (y1 - y0) / 2 - 14
    phases = [(rng.uniform(0, math.tau), rng.uniform(0.04, 0.12), rng.uniform(0.3, 1.0)) for _ in range(3)]
    points = []
    for x in range(x0 + 6, x1 - 6):
        v = sum(math.sin(x * f + p) * a for p, f, a in phases) / 2.2
        points.append((x, base + v * amp))
    draw.line(points, fill=black, width=1)
    for x in range(x0 + 6, x1 - 6, 20):
        draw.line((x, y1 - 5, x, y1 - 2), fill=black, width=1)
    font = _oblivion_font(9, "Regular")
    mx0, my0, mx1, my1 = _OBLIVION_MAP_RECT
    nx0, ny0, nx1, ny1 = _oblivion_numeral_rect()
    for i in range(6):
        draw.text((nx0 + 4, ny0 + 2 + i * 11), f"{rng.randint(0, 9999):04d}.{rng.randint(0, 9)}", font=font,
                  fill=black)


def _oblivion_layout(draw: ImageDraw.ImageDraw, quote_row: dict):
    return _place_quote(draw, quote_row, _OBLIVION_QUOTE_RECT, theme="oblivion",
                        font_max=34, font_min=18, line_height_mult=1.34)


def _oblivion_paint_quote(draw: ImageDraw.ImageDraw, placed) -> None:
    _paint_placed(draw, placed, SPECTRA6["black"], SPECTRA6["red"])


def _oblivion_paint_byline(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "").strip()
    parts = [p.upper() for p in (author, title) if p]
    if not parts:
        return
    x0 = _OBLIVION_QUOTE_RECT[0]
    font, text = fit_text_to_width(draw, "   ·   ".join(parts), [(EXO2_VARIABLE, "Regular"), *META_FONT_CANDIDATES],
                                   14, _OBLIVION_QUOTE_RECT[2] - x0, floor=12, tracking=3)
    draw_tracked(draw, (x0, _OBLIVION_BYLINE_Y), text, font, SPECTRA6["black"], tracking=3)


def render_oblivion_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The Sky Tower's light table with the hour's rig and bearing (see the
    section comment above)."""
    hour = _clock_hour12(time_str)
    image = _oblivion_scene().copy()
    draw = ImageDraw.Draw(image)
    _oblivion_paint_chrome(draw)
    _oblivion_paint_dial(draw, hour)
    _oblivion_paint_rigs(image, hour)
    _oblivion_paint_drone_detail(image)
    draw = ImageDraw.Draw(image)
    _oblivion_paint_data(draw, quote_row)
    _oblivion_paint_quote(draw, _oblivion_layout(draw, quote_row))
    _oblivion_paint_byline(draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image
