"""The ``beksinski`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .._paths import META_FONT_CANDIDATES, OLDSTANDARD_REGULAR
from ..furniture import _clock_hour12, _paint_placed, _place_quote, fallback_title
from ..palette import _PANEL_INKS, SPECTRA6, SPECTRA6_PALETTE, _dither_calibrated, pixel_access, snap_image_to_palette
from ..primitives import _lerp_stops, _smooth_noise, paint_craquelure
from ..spec import FrameSpec
from ..text import fit_text_to_width

# ---------------------------------------------------------------------------
# beksinski — Zdzisław Beksiński's fantastic period (c. 1964–1983): a
# procession across a dead plain toward a cathedral of bone
# ---------------------------------------------------------------------------
# A plain under a dust-coloured haze with a dim sun, a cathedral of bone grown
# on the horizon (spires, pointed openings, tendons into the ground), and
# hooded figures walking toward it. The quote is set in the haze.
#
# **The procession is the hour**: one figure per hour, led from the
# cathedral's foot back along the road, so the file grows and the leader never
# moves. Hour-only, pinned byte-identical across the minutes of an hour by
# ``TestBeksinskiFrame``. Each black figure has a 1 px bone-white edge toward
# the cathedral, which with the pale road keeps it legible on the dark plain.
#
# **Sky and plain are painted in continuous tone and dithered** against the
# calibrated inks (the ``expedition`` posture): umber-to-ochre gradient,
# scraped-oil noise, the sun's glow behind the spires, a vignette. **No green
# and no blue**: with green admitted the umber quantises to red-and-green
# confetti. The plain is lighter at the horizon (atmospheric perspective).
#
# **The cathedral** is an ``L`` mask: a mound, six ragged spires with a bulge
# so they read as bone rather than cones, pinnacles, tendon buttresses, and
# windows and an oculus knocked through. It is painted before the dither as a
# grained near-black body with a rust **rim light** (mask minus itself offset
# down-right). A far ruin on the left horizon makes the plain wide. After the
# dither ``paint_craquelure`` crazes the plain and the bone (not the sky),
# keeping the byline clear.
#
# **Type**: Old Standard TT, the Didone of 20th-century Central European book
# printing (Beksiński set no type): Regular body, Bold matched phrase in solid
# red, bone-white byline.
#
# The scene is quote- and hour-independent and painted once per process
# (``_BEKSINSKI_SCENE``, keyed on the painters). Composed at 800x480 and
# NEAREST-downsampled (the ``metro`` convention).
# ---------------------------------------------------------------------------
_BEKSINSKI_SEED = 0x5A42               # ZB
_BEKSINSKI_HORIZON = 318
_BEKSINSKI_QUOTE_RECT = (46, 42, 490, 266)
_BEKSINSKI_BYLINE_XY = (46, 444)
_BEKSINSKI_BYLINE_WIDTH = 420
_BEKSINSKI_SUN = (584, 126, 34)        # centre x, centre y, radius
_BEKSINSKI_TOWER = (548, 762)          # the cathedral's footprint on the horizon
_BEKSINSKI_ROAD = ((112, 430), (496, 354))   # near end .. far end of the road
_BEKSINSKI_RUIN_X = (74, 108, 150)     # the far ruin's spires, on the left horizon
_BEKSINSKI_SKY_INKS = ("black", "red", "yellow", "white")
_BEKSINSKI_GROUND_INKS = ("black", "red", "yellow", "white")
# Haze, zenith to horizon, in the calibrated space: smoky umber to a
# bone-ochre glow. Then the plain, hazed at its far edge and falling to
# near-black at the foot.
_BEKSINSKI_SKY_STOPS = (
    (0, (112, 98, 80)), (110, (142, 128, 96)), (230, (168, 156, 112)),
    (_BEKSINSKI_HORIZON, (184, 172, 124)),
)
_BEKSINSKI_GROUND_STOPS = (
    (_BEKSINSKI_HORIZON, (132, 112, 84)), (_BEKSINSKI_HORIZON + 26, (82, 58, 42)),
    (390, (54, 38, 32)), (480, (30, 26, 24)),
)
_BEKSINSKI_SUN_GLOW = (214, 206, 166)
_BEKSINSKI_SUN_DISC = (206, 198, 154)
_BEKSINSKI_ROAD_TONE = (104, 88, 72)
_BEKSINSKI_RUIN_TONE = (128, 112, 88)
_BEKSINSKI_BODY = (38, 31, 29)
_BEKSINSKI_RIM = (128, 68, 36)
_BEKSINSKI_ROOT = (24, 20, 20)
# (centre x offset from the footprint's left edge, height, base width, lean)
_BEKSINSKI_SPIRES = (
    (22, 150, 40, -0.02), (58, 236, 52, -0.01), (100, 296, 60, 0.0),
    (142, 254, 54, 0.015), (180, 196, 44, 0.03), (206, 128, 34, 0.05),
)
_BEKSINSKI_SCENE: dict = {}


def _beksinski_spindle(rng: random.Random, cx: float, base: float, h: float, w: float,
                       lean: float = 0.0) -> list[tuple[float, float]]:
    """A tapering spire with ragged edges and a bulge along its length — a
    bone, not a cone — as a polygon."""
    left, right = [], []
    steps = max(6, int(h) // 14)
    for i in range(steps + 1):
        t = i / steps
        y = base - h * t
        half = (w * 0.5 * (1 - t) ** 0.72 + 1.5) * (1 + 0.12 * math.sin(t * math.pi * 3.1 + cx))
        x = cx + lean * h * t
        left.append((x - half + rng.uniform(-2.5, 2.5), y))
        right.append((x + half + rng.uniform(-2.5, 2.5), y))
    return left + right[::-1]


def _beksinski_arch(cx: float, y_bottom: float, w: float, h: float) -> list[tuple[float, float]]:
    """A pointed arch, apex up, as a polygon."""
    half = w / 2
    return [(cx - half, y_bottom), (cx - half, y_bottom - h + half), (cx, y_bottom - h),
            (cx + half, y_bottom - h + half), (cx + half, y_bottom)]


def _beksinski_tower_mask(size: tuple[int, int]) -> Image.Image:
    """The cathedral as an ``L`` mask: mound, spires, pinnacles, buttresses,
    with the windows and the oculus knocked through."""
    mask = Image.new("L", size, 0)
    md = ImageDraw.Draw(mask)
    rng = random.Random(_BEKSINSKI_SEED + 3)
    base = _BEKSINSKI_HORIZON + 4
    x0, x1 = _BEKSINSKI_TOWER
    md.polygon([(x0 - 30, base), (x0 - 10, base - 40), (x0 + 30, base - 70), ((x0 + x1) // 2, base - 92),
                (x1 - 40, base - 70), (x1 + 2, base - 36), (x1 + 24, base)], fill=255)
    spires = [(x0 + dx, h, w, lean) for dx, h, w, lean in _BEKSINSKI_SPIRES]
    for cx, h, w, lean in spires:
        md.polygon(_beksinski_spindle(rng, cx, base, h, w, lean), fill=255)
        for _ in range(rng.randint(2, 4)):
            dx = rng.uniform(-w * 0.55, w * 0.55)
            md.polygon(_beksinski_spindle(rng, cx + dx, base - h * rng.uniform(0.25, 0.55),
                                          h * rng.uniform(0.18, 0.34), w * 0.3), fill=255)
    # Buttresses: tendons from the body down into the plain on both flanks,
    # thickening as they land.
    for sx, sy, ex, ey, w in ((x0 + 10, base - 120, x0 - 56, base + 2, 9),
                              (x0 + 40, base - 200, x0 - 22, base + 2, 7),
                              (x1 - 20, base - 100, x1 + 44, base + 2, 8),
                              (x1 - 60, base - 170, x1 + 16, base + 2, 6)):
        pts = []
        for i in range(9):
            t = i / 8
            pts.append((sx + (ex - sx) * t * t, sy + (ey - sy) * (1 - (1 - t) ** 2), w * (0.5 + t)))
        for (ax, ay, aw), (bx, by, _) in zip(pts, pts[1:]):
            md.line([(ax, ay), (bx, by)], fill=255, width=int(aw))
    # Windows: pointed arches through each spire, the haze showing through.
    for cx, h, w, lean in spires:
        for k in range(max(1, int(h // 70))):
            y = base - 30 - k * (h * 0.26)
            ww = max(5, int(w * 0.22 * (1 - k * 0.18)))
            x = cx + lean * (base - y) + rng.uniform(-2, 2)
            md.polygon(_beksinski_arch(x, y, ww, int(ww * 2.6)), fill=0)
    cx = spires[2][0]
    oy = base - 150
    md.ellipse((cx - 13, oy - 13, cx + 13, oy + 13), fill=0)
    md.ellipse((cx - 5, oy - 5, cx + 5, oy + 5), fill=255)
    return mask


def _beksinski_paint_sky(scene: Image.Image) -> None:
    """The haze and the plain in continuous tone: the gradients, the scraped
    facture, the sun behind the haze, the road, the far ruin, the vignette."""
    width, height = scene.size
    hz = _BEKSINSKI_HORIZON
    column = Image.new("RGB", (1, height))
    cp = pixel_access(column)
    for y in range(height):
        cp[0, y] = _lerp_stops(_BEKSINSKI_SKY_STOPS if y < hz else _BEKSINSKI_GROUND_STOPS, y)
    scene.paste(column.resize((width, height), Image.Resampling.NEAREST), (0, 0))
    # Scraped-oil facture: a horizontal streak and a broad smudge, both
    # centred on zero so the gradient's stops stay where they were set.
    streak = _smooth_noise((width, height), (48, 18), _BEKSINSKI_SEED + 1).point(lambda v: v // 10)
    smudge = _smooth_noise((width, height), (7, 5), _BEKSINSKI_SEED + 2).point(lambda v: v // 12)
    grain = ImageChops.add(streak, smudge)
    tint = Image.merge("RGB", (grain, grain, grain))
    scene.paste(ImageChops.subtract(ImageChops.add(scene, tint), Image.new("RGB", scene.size, (23, 23, 23))))
    # The sun: a pale disc behind the haze, its glow pooled round it. It sits
    # behind the left spires, so the cathedral is seen against the light.
    sx, sy, sr = _BEKSINSKI_SUN
    halo = Image.new("L", scene.size, 0)
    ImageDraw.Draw(halo).ellipse((sx - sr * 2.4, sy - sr * 2.4, sx + sr * 2.4, sy + sr * 2.4), fill=255)
    halo = halo.filter(ImageFilter.GaussianBlur(34)).point(lambda v: int(v * 0.34))
    scene.paste(Image.new("RGB", scene.size, _BEKSINSKI_SUN_GLOW), (0, 0), halo)
    disc = Image.new("L", scene.size, 0)
    ImageDraw.Draw(disc).ellipse((sx - sr, sy - sr, sx + sr, sy + sr), fill=255)
    disc = disc.filter(ImageFilter.GaussianBlur(3)).point(lambda v: int(v * 0.7))
    scene.paste(Image.new("RGB", scene.size, _BEKSINSKI_SUN_DISC), (0, 0), disc)
    # A ruin far off on the left horizon, in the haze's own colour: three
    # spires of the same construction, which is what makes the plain wide.
    rng = random.Random(_BEKSINSKI_SEED + 9)
    ruin = Image.new("L", scene.size, 0)
    rd = ImageDraw.Draw(ruin)
    for rx, h, w in zip(_BEKSINSKI_RUIN_X, (34, 58, 42), (14, 20, 16)):
        rd.polygon(_beksinski_spindle(rng, rx, hz + 1, h, w), fill=255)
    scene.paste(Image.new("RGB", scene.size, _BEKSINSKI_RUIN_TONE), (0, 0), ruin)
    # The road: a pale ash track across the plain, wider as it nears.
    (nx, ny), (fx, fy) = _BEKSINSKI_ROAD
    road = Image.new("L", scene.size, 0)
    ImageDraw.Draw(road).polygon([(nx - 70, ny + 16), (fx - 10, fy - 4), (fx + 30, fy - 2),
                                  (nx + 90, ny + 30), (nx - 10, ny + 34)], fill=255)
    road = road.filter(ImageFilter.GaussianBlur(9)).point(lambda v: int(v * 0.75))
    scene.paste(Image.new("RGB", scene.size, _BEKSINSKI_ROAD_TONE), (0, 0), road)
    # A vignette: the edges fall into the dark, the way the oils do.
    vignette = Image.new("L", scene.size, 0)
    ImageDraw.Draw(vignette).ellipse((-120, -90, width + 120, height + 90), fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(70)).point(lambda v: 180 + v * 75 // 255)
    scene.paste(Image.composite(scene, Image.new("RGB", scene.size, (0, 0, 0)), vignette))


def _beksinski_paint_tower(scene: Image.Image, mask: Image.Image) -> None:
    """The cathedral in continuous tone: a dark grained body on ``mask``, a
    rust rim light on the faces toward the sun, roots into the plain."""
    body = Image.new("RGB", scene.size, _BEKSINSKI_BODY)
    grain = _smooth_noise(scene.size, (20, 40), _BEKSINSKI_SEED + 4).point(lambda v: v // 9)
    scene.paste(ImageChops.add(body, Image.merge("RGB", (grain, grain, grain))), (0, 0), mask)
    rim = ImageChops.subtract(mask, ImageChops.offset(mask, 3, 2)).filter(ImageFilter.GaussianBlur(1.2))
    rim = ImageChops.multiply(rim, mask).point(lambda v: min(255, v * 2))
    scene.paste(Image.new("RGB", scene.size, _BEKSINSKI_RIM), (0, 0), rim)
    draw = ImageDraw.Draw(scene)
    rng = random.Random(_BEKSINSKI_SEED + 5)
    x0, x1 = _BEKSINSKI_TOWER
    for _ in range(10):
        x = rng.uniform(x0 - 10, x1 + 20)
        length = rng.uniform(24, 84)
        pts: list[tuple[float, float]] = [(x, _BEKSINSKI_HORIZON)]
        for i in range(1, 6):
            x += rng.uniform(-9, 9)
            pts.append((x, _BEKSINSKI_HORIZON + length * i / 5))
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            width = max(1, int(5 - 4 * (ay - _BEKSINSKI_HORIZON) / length))
            draw.line([(ax, ay), (bx, by)], fill=_BEKSINSKI_ROOT, width=width)


def _beksinski_scene() -> Image.Image:
    """The painting without its figures: haze, sun, ruin, cathedral, plain,
    craquelure. Painted once per process."""
    key = (_beksinski_paint_sky, _beksinski_paint_tower)
    cached = _BEKSINSKI_SCENE.get("frame")
    if cached is not None and cached[0] == key:
        return cached[1]
    size = (800, 480)
    scene = Image.new("RGB", size, _PANEL_INKS["black"])
    _beksinski_paint_sky(scene)
    tower = _beksinski_tower_mask(size)
    _beksinski_paint_tower(scene, tower)
    sky = _dither_calibrated(scene, _BEKSINSKI_SKY_INKS)
    ground = _dither_calibrated(scene, _BEKSINSKI_GROUND_INKS)
    # The plain and the bone are one surface for the craquelure; the sky is
    # not crazed, and the byline's footprint is kept out of the net.
    surface = Image.new("L", size, 0)
    ImageDraw.Draw(surface).rectangle((0, _BEKSINSKI_HORIZON, size[0], size[1]), fill=255)
    surface = ImageChops.lighter(surface, tower)
    image = Image.composite(ground, sky, surface)
    keep = Image.new("L", size, 0)
    bx, by = _BEKSINSKI_BYLINE_XY
    ImageDraw.Draw(keep).rectangle((bx - 4, by - 2, bx + _BEKSINSKI_BYLINE_WIDTH + 20, by + 24), fill=255)
    paint_craquelure(image, surface, seed=_BEKSINSKI_SEED + 6, cell=(26, 16), jitter=0.4, drop=0.25,
                     dark=SPECTRA6["black"], light=SPECTRA6["white"], light_share=0.16, keep_out=keep)
    _BEKSINSKI_SCENE["frame"] = (key, image)
    return image


def _beksinski_figure(cx: float, cy: float, h: float, lean: float) -> list[tuple[float, float]]:
    """A hooded, stooped walker standing on ``(cx, cy)``, ``h`` tall, leaning
    ``lean`` of its height toward the cathedral, with a ragged hem."""
    hw, sw, bw = h * 0.11, h * 0.16, h * 0.22
    top = cy - h
    lx = lean * h
    hem = [(cx + bw * (-1 + 2 * i / 6), cy - (3 if i % 2 else 0) * (h / 40)) for i in range(7)]
    return ([(cx + lx, top), (cx + lx + hw, top + h * 0.14), (cx + lx * 0.7 + sw, top + h * 0.36),
             (cx + lx * 0.3 + sw * 0.9, top + h * 0.62), (cx + bw, cy)]
            + hem[::-1][1:-1]
            + [(cx - bw, cy), (cx + lx * 0.3 - sw * 0.9, top + h * 0.62), (cx + lx * 0.7 - sw, top + h * 0.36),
               (cx + lx - hw, top + h * 0.14)])


def _beksinski_paint_figures(image: Image.Image, hour: int) -> None:
    """The procession: one figure per hour, led from the cathedral's foot
    back along the road, so the file grows through the day."""
    draw = ImageDraw.Draw(image)
    black, white = SPECTRA6["black"], SPECTRA6["white"]
    rng = random.Random(_BEKSINSKI_SEED + 7)
    (nx, ny), (fx, fy) = _BEKSINSKI_ROAD
    # Every figure's jitter is drawn whether or not it walks today, so the
    # ones that do stand where they always stand.
    walk = [(rng.uniform(-0.012, 0.012), rng.uniform(-5, 5), rng.uniform(0.02, 0.1), rng.uniform(0.8, 1.0))
            for _ in range(12)]
    for k in range(hour):
        jt, jy, lean, stoop = walk[k]
        t = 1 - k / 12 - 0.03 + jt
        cx = nx + (fx - nx) * t
        cy = ny + (fy - ny) * t + jy * (1 - t)
        h = (58 - 32 * t) * stoop
        body = _beksinski_figure(cx, cy, h, lean)
        draw.polygon(body, fill=black)
        if h > 30:
            draw.line([(cx + lean * h + h * 0.18, cy - h * 0.7), (cx + h * 0.21, cy + 2)], fill=black, width=1)
        # The glow catches the edge toward the cathedral: a bone-white line.
        draw.line(body[1:4], fill=white, width=1)


def _beksinski_paint_quote(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The quote in the haze: black Old Standard, ragged right, the matched
    phrase Bold in solid red."""
    placed = _place_quote(draw, quote_row, _BEKSINSKI_QUOTE_RECT, theme="beksinski",
                          font_max=32, font_min=15, line_height_mult=1.3)
    _paint_placed(draw, placed, SPECTRA6["black"], SPECTRA6["red"])


def _beksinski_paint_byline(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """Author and title in bone-white on the plain at the foot."""
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "")
    text = " — ".join(part for part in (author, title) if part)
    if not text:
        return
    font, text = fit_text_to_width(draw, text, [OLDSTANDARD_REGULAR, *META_FONT_CANDIDATES], 17,
                                   _BEKSINSKI_BYLINE_WIDTH, floor=13)
    draw.text(_BEKSINSKI_BYLINE_XY, text, font=font, fill=SPECTRA6["white"])


def render_beksinski_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A procession toward a cathedral of bone (see the section comment above)."""
    hour = _clock_hour12(time_str)
    image = _beksinski_scene().copy()
    draw = ImageDraw.Draw(image)
    _beksinski_paint_figures(image, hour)
    _beksinski_paint_quote(draw, quote_row)
    _beksinski_paint_byline(draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("beksinski",), render=render_beksinski_frame)
