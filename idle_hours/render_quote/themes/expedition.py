"""The ``expedition`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

from .._paths import (
    ANTONIO_VARIABLE,
    BEBASNEUE_REGULAR,
    CINZELDECORATIVE_BOLD,
    CINZELDECORATIVE_REGULAR,
    META_FONT_BOLD_CANDIDATES,
    QUOTE_FONT_BOLD_CANDIDATES,
)
from ..fonts import load_font
from ..furniture import _clock_hour12, _row_digest, fallback_title
from ..palette import (
    _PANEL_INKS,
    SPECTRA6,
    SPECTRA6_PALETTE,
    BAYER_4x4,
    BAYER_8x8,
    _dither_calibrated,
    gray_pixel_access,
    pixel_access,
    snap_image_to_palette,
)
from ..primitives import _halo_paste, _lerp_stops, _smooth_noise, paint_flow_strokes, paint_neon_mask, wrap_quote_into_masks
from ..spec import FrameSpec
from ..text import draw_tracked, fit_text_to_width, tracked_width

# ---------------------------------------------------------------------------
# expedition — Sandfall Interactive's *Clair Obscur: Expedition 33* (2025):
# the Monolith from the Lumière promenade
# ---------------------------------------------------------------------------
# The view from the Lumière promenade: stone balustrade and gas lamp in the
# foreground, the dusk sea, and on the far islet the Monolith with the
# Paintress beside it, brush raised. The number she has just painted is the
# **hour**. The quote is a page from an expedition journal.
#
# **Clair-obscur, literally**: black zenith and silhouettes against one warm
# light, the horizon glow behind the Monolith. The scene (dusk gradient,
# pooled glow, a vignette keeping the journal's corner dark, the sea with
# shimmer and broken reflection, silhouettes, a brush-stroke facture) is
# painted in continuous tone and Floyd–Steinberg-dithered.
#
# **Dithered against the calibrated inks, not the nominal ones.** Tones are
# specified in the panel's measured colour space and the quantiser is given
# the same measured inks, so diffusion weighs red as the near-black it is on
# the panel; indices are then re-labelled with the nominal inks
# (``_dither_calibrated``). Nominal-RGB design goes to mud on the panel. The
# sky is quantised without green (diffusion uses any ink it is given); the sea
# gets green back for the B+G teal of lit water.
#
# **The number is paint.** ``_expedition_numeral_mask`` sets the hour in Bebas
# Neue and roughs it into a brushed stroke (bristle gaps, swelling edges,
# drips, a flick). Painted as a yellow core with white at 1/4 in a red + yellow
# halo at 1/2 (a 5/8-red halo reads as shadow). The water carries its
# reflection as a density stipple (``_expedition_stipple_field``). The
# Paintress's brush tip reaches into the halo.
#
# **The petals are the Gommage**: a gust of rose petals along a cubic path from
# the promenade toward the number, each a teardrop in a red + white stipple
# (pink is the only way a petal reads against the night when panel red is so
# dark), rimmed white on the lit side. Sizes fall along the path. Seeded from
# ``_row_digest``; the gust keeps out of the journal, byline, wordmark, credo
# and number.
#
# **The chroma**: ``paint_flow_strokes`` sweeps the sky round the number
# through a swirl-plus-wind field, blue/white in the cold sky, red/yellow near
# the glow.
#
# **The game's own faces.** The journal is **IM Fell Double Pica**, roman body
# and (no bold exists) italic matched phrase, painted in the number's recipe.
# The number and every label are **Bebas Neue**; solid-yellow Bebas at 15 px
# survives the panel where a stippled serif would shred. The wordmark is
# spaced **Cinzel Decorative** with a gold hairline and diamond.
#
# **Time surfaces.** The number is hour-only, pinned byte-identical across the
# minutes of an hour by ``TestExpeditionFrame``. The scene is quote- and
# hour-independent and cached once per process (``_EXPEDITION_BACKGROUND``,
# keyed on the painters). Composed at 800x480 and NEAREST-downsampled (the
# ``metro`` convention).
# ---------------------------------------------------------------------------
_EXPEDITION_SEED = 0xE33
_EXPEDITION_HORIZON = 306
_EXPEDITION_RAIL_TOP = 430
_EXPEDITION_QUOTE_RECT = (126, 76, 548, 216)
_EXPEDITION_BYLINE_TOP = 226
_EXPEDITION_WORDMARK_BOX = (44, 12, 340, 70)
_EXPEDITION_CREDO_BOX = (470, 396, 770, 418)
_EXPEDITION_MONOLITH = ((596, 26), (720, 26), (724, 322), (592, 322))   # the slab, top to the islet
_EXPEDITION_NUMERAL_BOX = (606, 78, 710, 214)          # where the Paintress paints
_EXPEDITION_NUMERAL_CENTRE = (658, 146)
_EXPEDITION_PAINTRESS_BOX = (460, 156, 586, 322)
_EXPEDITION_BRUSH = ((506, 236), (618, 146))           # handle end, tip — into the number's halo
_EXPEDITION_LAMP_X = 66
_EXPEDITION_LAMP_GLASS = (56, 206, 76, 244)
_EXPEDITION_LAMP_BOX = (44, 184, 90, 262)
_EXPEDITION_SKY_INKS = ("black", "blue", "red", "yellow", "white")
_EXPEDITION_SEA_INKS = ("black", "blue", "green", "red", "yellow", "white")
# Dusk, top to horizon, in the calibrated space: blue-black zenith, deep
# blue, violet, rose, amber.
_EXPEDITION_SKY_STOPS = (
    (0, (31, 34, 40)), (104, (33, 50, 98)), (196, (60, 54, 98)),
    (258, (108, 72, 74)), (292, (158, 124, 72)), (_EXPEDITION_HORIZON, (178, 150, 92)),
)
_EXPEDITION_SEA_STOPS = (
    (_EXPEDITION_HORIZON, (62, 86, 120)), (338, (44, 64, 108)),
    (400, (36, 48, 82)), (480, (31, 36, 50)),
)
_EXPEDITION_SILHOUETTE = (24, 22, 28)               # a hair off the panel's black
_EXPEDITION_GLOW = (196, 162, 92)                   # the horizon pooled behind the Monolith
_EXPEDITION_BACKGROUND: dict = {}
_EXPEDITION_NUMERALS: dict = {}


def _expedition_label_font(size: int):
    """Bebas Neue — the game's numeral and label face — falling back through
    Antonio, the bundle's other condensed caps, before the system faces."""
    return load_font([BEBASNEUE_REGULAR, (ANTONIO_VARIABLE, "Bold"), *META_FONT_BOLD_CANDIDATES], size=size)


def _expedition_wordmark_font(size: int):
    """Cinzel Decorative Bold — the poster's lettering — for ``EXPEDITION 33``."""
    return load_font([CINZELDECORATIVE_BOLD, CINZELDECORATIVE_REGULAR, *META_FONT_BOLD_CANDIDATES], size=size)


def _expedition_paint_sky(scene: Image.Image) -> None:
    """The dusk: the gradient, the glow pooled behind the Monolith, the
    vignette over the journal's corner, and the brush facture."""
    width, height = scene.size
    hz = _EXPEDITION_HORIZON
    column = Image.new("RGB", (1, height))
    for y in range(height):
        column.putpixel((0, y), _lerp_stops(_EXPEDITION_SKY_STOPS, min(y, hz)))
    scene.paste(column.resize((width, height), Image.Resampling.NEAREST))

    # The light: an elliptical pool behind the Monolith, brightest at the
    # horizon, which is what the slab and the Paintress are silhouetted on.
    glow = Image.new("L", (width, height), 0)
    gp = pixel_access(glow)
    gx, gy = _EXPEDITION_NUMERAL_CENTRE[0], hz
    for y in range(hz + 1):
        dy = (y - gy) / 150.0
        for x in range(width):
            dx = (x - gx) / 300.0
            gp[x, y] = round(255 * min(1.0, 0.92 * math.exp(-(dx * dx + dy * dy))))
    lit = Image.new("RGB", (width, height), _EXPEDITION_GLOW)
    scene.paste(Image.composite(lit, scene, glow))

    # The vignette: the corner the journal page sits in stays black, so the
    # halo under the type has nothing to fight.
    shade = Image.new("L", (width, height), 0)
    sp = gray_pixel_access(shade)
    for y in range(hz + 1):
        dy = (y - 128) / 160.0
        for x in range(width):
            dx = (x - 290) / 310.0
            sp[x, y] = round(255 * 0.7 * math.exp(-(dx * dx + dy * dy)))
    dark = Image.new("RGB", (width, height), (31, 34, 38))
    scene.paste(Image.composite(dark, scene, shade))

    # Facture: long horizontal strokes and a finer streak, multiplied in.
    broad = _smooth_noise((width, height), (10, 72), _EXPEDITION_SEED).point(lambda v: 196 + v * 0.46)
    fine = _smooth_noise((width, height), (26, 160), _EXPEDITION_SEED + 1).point(lambda v: 222 + v * 0.26)
    brushed = ImageChops.multiply(scene, ImageChops.multiply(broad, fine).convert("RGB"))
    brushed = ImageEnhance.Brightness(brushed).enhance(1.18)
    sky = Image.new("L", (width, height), 0)
    ImageDraw.Draw(sky).rectangle((0, 0, width, hz), fill=255)
    scene.paste(Image.composite(brushed, scene, sky))


def _expedition_paint_sea(scene: Image.Image) -> None:
    """The water: a depth gradient, shimmer streaks, and the glow's reflection
    under the Monolith, broken by the same streaks."""
    width, height = scene.size
    hz = _EXPEDITION_HORIZON
    column = Image.new("RGB", (1, height))
    for y in range(height):
        column.putpixel((0, y), _lerp_stops(_EXPEDITION_SEA_STOPS, max(y, hz)))
    water = column.resize((width, height), Image.Resampling.NEAREST)

    streaks = _smooth_noise((width, height), (14, 110), _EXPEDITION_SEED + 2)
    water = ImageChops.multiply(water, streaks.point(lambda v: 186 + v * 0.38).convert("RGB"))
    water = ImageEnhance.Brightness(water).enhance(1.12)

    reflect = Image.new("L", (width, height), 0)
    rp = gray_pixel_access(reflect)
    sp = gray_pixel_access(streaks)
    gx = _EXPEDITION_NUMERAL_CENTRE[0]
    for y in range(hz, height):
        fall = math.exp(-(y - hz) / 62.0)
        for x in range(width):
            dx = (x - gx) / 96.0
            rp[x, y] = round(255 * 0.8 * fall * math.exp(-dx * dx) * (0.35 + 0.65 * sp[x, y] / 255.0))
    lit = Image.new("RGB", (width, height), (176, 138, 80))
    water = Image.composite(lit, water, reflect)

    sea = Image.new("L", (width, height), 0)
    ImageDraw.Draw(sea).rectangle((0, hz, width, height), fill=255)
    scene.paste(Image.composite(water, scene, sea))


def _expedition_paint_continent(scene: Image.Image) -> None:
    """The Continent's coast, far off on the left horizon, hazed into the sky."""
    hz = _EXPEDITION_HORIZON
    draw = ImageDraw.Draw(scene)
    coast = [(0, hz + 1), (0, hz - 7), (40, hz - 9), (96, hz - 13), (150, hz - 10), (204, hz - 15),
             (250, hz - 11), (300, hz - 12), (344, hz - 8), (380, hz - 5), (402, hz + 1)]
    draw.polygon(coast, fill=(124, 104, 86))


def _expedition_paint_monolith(scene: Image.Image) -> None:
    """The slab on its islet: a stone face with a rim of the glow down each
    edge, and the rocks it rises from."""
    draw = ImageDraw.Draw(scene)
    (x0, y0), (x1, _), (x2, y2), (x3, _) = _EXPEDITION_MONOLITH
    face = Image.new("L", scene.size, 0)
    ImageDraw.Draw(face).polygon(list(_EXPEDITION_MONOLITH), fill=255)
    stone = Image.new("RGB", scene.size, (27, 26, 33))
    grain = _smooth_noise(scene.size, (20, 6), _EXPEDITION_SEED + 3).point(lambda v: 214 + v * 0.16)
    stone = ImageChops.multiply(stone, grain.convert("RGB"))
    scene.paste(Image.composite(stone, scene, face))
    # Rim light: the glow grazes both edges, strongest at the base.
    for y in range(y0, y2):
        t = (y - y0) / max(1, y2 - y0)
        lx = round(x3 + (x0 - x3) * (1 - t))
        rx = round(x2 + (x1 - x2) * (1 - t))
        amount = 0.15 + 0.85 * t * t
        rim = tuple(round(27 + (c - 27) * amount) for c in (168, 126, 70))
        draw.line([(lx, y), (lx + 1, y)], fill=rim)
        draw.line([(rx - 1, y), (rx, y)], fill=tuple(round(c * 0.7) for c in rim))
    # The islet: low jagged rock either side of the base, breaking the horizon.
    hz = _EXPEDITION_HORIZON
    rocks = [
        [(556, hz + 12), (570, hz - 2), (590, hz - 8), (612, hz - 4), (626, hz + 2), (640, hz + 14)],
        [(690, hz + 14), (704, hz - 3), (726, hz - 9), (748, hz - 5), (768, hz + 1), (784, hz + 14)],
        [(600, hz + 14), (640, hz + 2), (680, hz - 1), (730, hz + 4), (760, hz + 16)],
    ]
    for rock in rocks:
        draw.polygon(rock, fill=_EXPEDITION_SILHOUETTE)
    draw.rectangle((556, hz + 8, 784, hz + 18), fill=_EXPEDITION_SILHOUETTE)


def _expedition_paint_paintress(scene: Image.Image) -> None:
    """The Paintress, seated on the islet beside the Monolith, brush raised to
    the number — a silhouette against the one light in the picture."""
    draw = ImageDraw.Draw(scene)
    ink = _EXPEDITION_SILHOUETTE
    # Hair, first: a long mass down her back and over the rock behind her.
    draw.polygon([(502, 170), (520, 162), (536, 168), (540, 186), (534, 206), (522, 226), (508, 250),
                  (498, 276), (494, 302), (484, 318), (468, 318), (470, 294), (478, 262), (488, 228),
                  (494, 196)], fill=ink)
    # The seated body: hips and folded legs, the torso leaning to the slab, a raised knee.
    draw.polygon([(474, 318), (480, 292), (494, 270), (518, 262), (548, 268), (564, 286), (570, 304),
                  (572, 318)], fill=ink)
    draw.polygon([(496, 272), (500, 236), (510, 206), (530, 198), (542, 212), (544, 244), (540, 270)],
                 fill=ink)
    draw.polygon([(522, 268), (534, 246), (550, 240), (562, 256), (570, 290), (556, 300), (540, 282)],
                 fill=ink)                                                       # the knee
    draw.polygon([(514, 206), (520, 194), (530, 192), (534, 204)], fill=ink)     # neck
    draw.ellipse((532, 164, 562, 200), fill=ink)                                 # head
    # The arm, reaching for the Monolith, and the brush it holds.
    draw.line([(534, 220), (560, 196), (578, 178)], fill=ink, width=11)
    draw.ellipse((598, 170, 612, 184), fill=ink)                                 # hand
    (hx, hy), (tx, ty) = _EXPEDITION_BRUSH
    draw.line([(hx, hy), (tx, ty)], fill=ink, width=4)
    # The brush head: a tapered tuft at the tip, flared back along the handle.
    ang = math.atan2(ty - hy, tx - hx)
    nx, ny = -math.sin(ang), math.cos(ang)
    bx, by = tx - math.cos(ang) * 14, ty - math.sin(ang) * 14
    draw.polygon([(tx, ty), (bx + nx * 5, by + ny * 5), (bx - nx * 5, by - ny * 5)], fill=ink)


def _expedition_paint_promenade(scene: Image.Image) -> None:
    """Lumière's edge: the balustrade across the foot of the page, lit from
    the lamp, and the lamp itself — post, bracket, lantern — as silhouette.
    The lantern's glass is left pale for the bloom to take."""
    width, height = scene.size
    draw = ImageDraw.Draw(scene)
    ink = _EXPEDITION_SILHOUETTE
    top = _EXPEDITION_RAIL_TOP
    lamp_x = _EXPEDITION_LAMP_X

    def lit(x: int, base, amount: float):
        glow = math.exp(-((x - lamp_x) / 150.0) ** 2) * amount
        return tuple(round(b + (g - b) * glow) for b, g in zip(base, (132, 104, 58), strict=True))

    # Rail and plinth, lit toward the lamp.
    for x in range(width):
        draw.line([(x, top), (x, top + 9)], fill=lit(x, (36, 34, 40), 0.75))
        draw.line([(x, top + 10), (x, top + 11)], fill=lit(x, (20, 18, 24), 0.3))
        draw.line([(x, top + 42), (x, height)], fill=lit(x, (30, 28, 34), 0.5))
    # Balusters: a vase profile each, 36 px pitch, the sea showing between.
    for cx in range(26, width + 18, 36):
        tone = lit(cx, ink, 0.45)
        draw.rectangle((cx - 7, top + 12, cx + 7, top + 15), fill=tone)
        draw.polygon([(cx - 4, top + 16), (cx + 4, top + 16), (cx + 7, top + 24), (cx + 5, top + 32),
                      (cx + 6, top + 41), (cx - 6, top + 41), (cx - 5, top + 32), (cx - 7, top + 24)],
                     fill=tone)
    # The lamp post, with its base, bracket curls and the lantern cage.
    draw.rectangle((lamp_x - 4, 262, lamp_x + 3, height), fill=ink)
    draw.rectangle((lamp_x - 9, 418, lamp_x + 8, 430), fill=ink)
    draw.rectangle((lamp_x - 7, 400, lamp_x + 6, 418), fill=ink)
    draw.arc((lamp_x - 22, 256, lamp_x, 284), 180, 360, fill=ink, width=2)
    draw.arc((lamp_x - 1, 256, lamp_x + 21, 284), 180, 360, fill=ink, width=2)
    gx0, gy0, gx1, gy1 = _EXPEDITION_LAMP_GLASS
    draw.polygon([(gx0 - 4, gy1 + 2), (gx1 + 4, gy1 + 2), (gx1 + 1, gy1 + 16), (gx0 - 1, gy1 + 16)], fill=ink)
    draw.rectangle((gx0, gy0, gx1, gy1), fill=(168, 158, 100))                  # the glass
    draw.polygon([(gx0 - 6, gy0), (gx1 + 6, gy0), (lamp_x + 1, gy0 - 14), (lamp_x - 1, gy0 - 14)], fill=ink)
    draw.polygon([(lamp_x - 3, gy0 - 12), (lamp_x + 3, gy0 - 12), (lamp_x, gy0 - 22)], fill=ink)


def _expedition_paint_chroma(image: Image.Image) -> None:
    """The swirl the Paintress leaves in the sky: streamline strokes round the
    number, blue and white in the cold sky, red and yellow near the glow."""
    cx, cy = _EXPEDITION_NUMERAL_CENTRE
    qx0, qy0, qx1, qy1 = _expedition_quote_keepout()
    wx0, wy0, wx1, wy1 = _EXPEDITION_WORDMARK_BOX
    mx0 = _EXPEDITION_MONOLITH[0][0] - 6
    mx1 = _EXPEDITION_MONOLITH[1][0] + 6
    px0, py0, px1, py1 = _EXPEDITION_PAINTRESS_BOX
    black, blue, white = SPECTRA6["black"], SPECTRA6["blue"], SPECTRA6["white"]
    red, yellow = SPECTRA6["red"], SPECTRA6["yellow"]

    def direction(x: float, y: float) -> float:
        dx, dy = x - cx, y - cy
        r = math.hypot(dx, dy) or 1.0
        swirl = math.exp(-(r / 260.0) ** 2)
        tx, ty = -dy / r, dx / r                          # tangent, clockwise about the number
        wx, wy = math.cos(-0.18), math.sin(-0.18)         # the wind, a little upward
        return math.atan2(ty * swirl + wy * (1 - swirl), tx * swirl + wx * (1 - swirl))

    def ink_at(x: int, y: int, r: float):
        if y > _EXPEDITION_HORIZON - 30:
            return None
        if qx0 - 8 < x < qx1 + 8 and qy0 - 8 < y < qy1 + 8:
            return None
        if wx0 < x < wx1 and wy0 < y < wy1:
            return None
        if mx0 < x < mx1 or (px0 < x < px1 and py0 < y < py1):
            return None
        near = math.hypot(x - cx, y - cy)
        if near < 150:
            return red if r < 0.16 else yellow if r < 0.22 else None
        if r < 0.035 and near < 330:
            return white
        return blue if r < 0.44 else None

    paint_flow_strokes(image, (0, 0, image.size[0], _EXPEDITION_HORIZON), direction, ink_at,
                       cell=11, length=22, width=2, steps=4, ground=frozenset({black, blue, red}),
                       salt=_EXPEDITION_SEED)


def _expedition_paint_lamp(image: Image.Image) -> None:
    """The gas lamp lit: a yellow core with white in it, a yellow bloom with
    white at 3/10 — gaslight, not neon — and the cage bars back over it."""
    gx0, gy0, gx1, gy1 = _EXPEDITION_LAMP_GLASS
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rectangle((gx0 + 1, gy0 + 1, gx1 - 1, gy1 - 1), fill=255)
    paint_neon_mask(image, mask, SPECTRA6["yellow"], SPECTRA6["yellow"], radius=9, gamma=1.4, cap=0.62,
                    tile=BAYER_8x8, glow_minor=SPECTRA6["white"], glow_minor_share=0.3,
                    core_minor=SPECTRA6["white"], core_minor_share=0.3)
    draw = ImageDraw.Draw(image)
    black = SPECTRA6["black"]
    mid = (gx0 + gx1) // 2
    draw.line([(mid, gy0), (mid, gy1)], fill=black, width=1)
    draw.line([(gx0, (gy0 + gy1) // 2), (gx1, (gy0 + gy1) // 2)], fill=black, width=1)
    draw.rectangle((gx0, gy0, gx1, gy1), outline=black, width=1)
    mask.close()


def _expedition_background() -> Image.Image:
    """The quote- and hour-independent view, painted and dithered once per process."""
    key = (_expedition_paint_sky, _expedition_paint_sea, _expedition_paint_continent,
           _expedition_paint_monolith, _expedition_paint_paintress, _expedition_paint_promenade,
           _expedition_paint_chroma, _expedition_paint_lamp)
    cached = _EXPEDITION_BACKGROUND.get("frame")
    if cached is not None and cached[0] == key:
        return cached[1]
    size = (800, 480)
    scene = Image.new("RGB", size, _PANEL_INKS["black"])
    _expedition_paint_sky(scene)
    _expedition_paint_sea(scene)
    _expedition_paint_continent(scene)
    _expedition_paint_monolith(scene)
    _expedition_paint_paintress(scene)
    _expedition_paint_promenade(scene)
    # Two quantisers: the sky without green, the water with it.
    image = _dither_calibrated(scene, _EXPEDITION_SKY_INKS)
    sea = _dither_calibrated(scene, _EXPEDITION_SEA_INKS)
    band = Image.new("L", size, 0)
    ImageDraw.Draw(band).rectangle((0, _EXPEDITION_HORIZON + 1, size[0], _EXPEDITION_RAIL_TOP - 1), fill=255)
    image = Image.composite(sea, image, band)
    _expedition_paint_chroma(image)
    _expedition_paint_lamp(image)
    _EXPEDITION_BACKGROUND["frame"] = (key, image)
    return image


def _expedition_quote_keepout() -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = _EXPEDITION_QUOTE_RECT
    return (x0 - 8, y0 - 8, x1 + 8, _EXPEDITION_BYLINE_TOP + 22)


def _expedition_stipple_field(image: Image.Image, field: Image.Image, major, minor, *,
                              cap: float, minor_share: float, ground) -> None:
    """Paint an ``L`` density field as an ordered stipple of two inks on
    ``ground`` pixels — ``paint_neon_mask``'s halo rule applied to a field
    that is itself the light, with no solid core to grow it from."""
    bbox = field.getbbox()
    if bbox is None:
        return
    fp = gray_pixel_access(field)
    px = pixel_access(image)
    levels = 64
    for y in range(bbox[1], bbox[3]):
        row = BAYER_8x8[y % 8]
        for x in range(bbox[0], bbox[2]):
            level = fp[x, y] / 255.0
            if level <= 0.02 or px[x, y] not in ground:
                continue
            rank = row[x % 8]
            lit = min(cap, level) * levels
            if rank < lit:
                px[x, y] = minor if rank < lit * minor_share else major


def _expedition_numeral_mask(hour: int) -> Image.Image:
    """The hour as the Paintress painted it: Bebas Neue brushed rough —
    bristle gaps, biting edges, drips from its lowest points, a flick."""
    cached = _EXPEDITION_NUMERALS.get(hour)
    if cached is not None:
        return cached
    size = (800, 480)
    x0, y0, x1, y1 = _EXPEDITION_NUMERAL_BOX
    box_w, box_h = x1 - x0, y1 - y0
    text = str(hour)
    candidates = [BEBASNEUE_REGULAR, (ANTONIO_VARIABLE, "Bold"), *QUOTE_FONT_BOLD_CANDIDATES]
    font_size = 196
    while font_size > 40:
        font = load_font(candidates, font_size)
        bbox = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= box_w and bbox[3] - bbox[1] <= box_h:
            break
        font_size -= 4
    glyph = Image.new("L", size, 0)
    gd = ImageDraw.Draw(glyph)
    tx = x0 + (box_w - (bbox[2] - bbox[0])) // 2 - bbox[0]
    ty = y0 + (box_h - (bbox[3] - bbox[1])) // 2 - bbox[1]
    gd.text((tx, ty), text, font=font, fill=255)

    rng = random.Random(_EXPEDITION_SEED * 31 + hour)
    # Bristle gaps: vertical streaks carved out where a tall-celled noise dips.
    bristle = _smooth_noise(size, (120, 6), _EXPEDITION_SEED + 10 + hour).point(lambda v: 255 if v > 26 else 0)
    glyph = ImageChops.multiply(glyph, bristle)
    # Edges that swell and bite: grow where one noise is high, shrink where low.
    bite = _smooth_noise(size, (60, 36), _EXPEDITION_SEED + 20 + hour).point(lambda v: 255 if v > 150 else 0)
    glyph = Image.composite(glyph.filter(ImageFilter.MaxFilter(3)), glyph.filter(ImageFilter.MinFilter(3)), bite)
    # Drips, from the lowest painted pixel in three columns of the glyph.
    gp = pixel_access(glyph)
    gd = ImageDraw.Draw(glyph)
    columns = [x for x in range(x0, x1) if any(gp[x, y] for y in range(y0, y1 + 8))]
    if columns:
        for _ in range(2):
            x = rng.choice(columns)
            bottom = max(y for y in range(y0, y1 + 8) if gp[x, y])
            length = rng.randint(14, 40)
            gd.line([(x, bottom), (x, bottom + length)], fill=255, width=2)
            gd.ellipse((x - 2, bottom + length - 1, x + 2, bottom + length + 3), fill=255)
    # A flick of the brush beside the number, where the stroke left the slab.
    fx, fy = x0 + rng.randint(-6, 4), y1 + rng.randint(4, 12)
    gd.line([(fx, fy), (fx + 22, fy - 16)], fill=255, width=2)
    _EXPEDITION_NUMERALS[hour] = glyph
    return glyph


def _expedition_paint_numeral(image: Image.Image, hour: int) -> None:
    """The number, wet and lit: a yellow core with white at 1/4 in a red +
    yellow halo at 1/2, and its reflection broken on the water."""
    mask = _expedition_numeral_mask(hour)
    paint_neon_mask(image, mask, SPECTRA6["yellow"], SPECTRA6["red"], radius=10, gamma=1.25, cap=0.8,
                    tile=BAYER_8x8, glow_minor=SPECTRA6["yellow"], glow_minor_share=0.5,
                    core_minor=SPECTRA6["white"], core_minor_share=0.25)

    hz = _EXPEDITION_HORIZON
    x0, y0, x1, y1 = _EXPEDITION_NUMERAL_BOX
    reach = y1 - y0 + 48
    slab = mask.crop((x0 - 20, y0 - 4, x1 + 20, y1 + 44)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    slab = slab.resize((slab.size[0], round(slab.size[1] * 1.25)), Image.Resampling.BILINEAR)
    field = Image.new("L", image.size, 0)
    field.paste(slab, (x0 - 20, hz + 4))
    field = field.filter(ImageFilter.GaussianBlur(2.5))
    fade = Image.new("L", image.size, 0)
    fp = gray_pixel_access(fade)
    streaks = gray_pixel_access(_smooth_noise(image.size, (14, 110), _EXPEDITION_SEED + 2))
    for y in range(hz, min(image.size[1], hz + 4 + round(reach * 1.25) + 8)):
        depth = math.exp(-(y - hz) / 90.0)
        for x in range(x0 - 20, x1 + 20):
            fp[x, y] = round(255 * depth * (0.3 + 0.7 * streaks[x, y] / 255.0))
    field = ImageChops.multiply(field, fade)
    _expedition_stipple_field(image, field, SPECTRA6["yellow"], SPECTRA6["red"], cap=0.7, minor_share=0.5,
                              ground=frozenset({SPECTRA6["blue"], SPECTRA6["black"], SPECTRA6["green"]}))
    field.close()
    fade.close()


def _expedition_petal_polygon(cx: float, cy: float, size: float, angle: float) -> list:
    """A rose petal: a teardrop, rounded at the base and narrowing to the tip."""
    pts = []
    ca, sa = math.cos(angle), math.sin(angle)
    for k in range(16):
        t = 2 * math.pi * k / 16
        x = math.cos(t) * size
        y = math.sin(t) * size * (0.5 - 0.3 * math.cos(t))
        pts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return pts


def _expedition_gust(quote_row: dict) -> list:
    """The petals, as ``(x, y, size, angle, white_density)``: a cubic path
    from the promenade, under the journal page, up past the Paintress to the
    number, plus a few strays loose in the sky. Seeded from the quote."""
    rng = random.Random(_row_digest(quote_row) ^ _EXPEDITION_SEED)
    p0, p1, p2, p3 = (26, 446), (250, 404), (470, 332), (628, 166)
    keepouts = (_expedition_quote_keepout(), _EXPEDITION_WORDMARK_BOX, _EXPEDITION_CREDO_BOX,
                (_EXPEDITION_NUMERAL_BOX[0] - 10, _EXPEDITION_NUMERAL_BOX[1] - 10,
                 _EXPEDITION_NUMERAL_BOX[2] + 10, _EXPEDITION_NUMERAL_BOX[3] + 30),
                _EXPEDITION_LAMP_BOX)

    def clear(x: float, y: float, size: float) -> bool:
        if not (size < x < 800 - size and size < y < _EXPEDITION_RAIL_TOP - size):
            return False
        return not any(kx0 - size < x < kx1 + size and ky0 - size < y < ky1 + size
                       for kx0, ky0, kx1, ky1 in keepouts)

    petals = []
    for _ in range(64):
        t = rng.random() ** 0.85
        u = 1 - t
        x = u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0]
        y = u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]
        dx = 3 * u * u * (p1[0] - p0[0]) + 6 * u * t * (p2[0] - p1[0]) + 3 * t * t * (p3[0] - p2[0])
        dy = 3 * u * u * (p1[1] - p0[1]) + 6 * u * t * (p2[1] - p1[1]) + 3 * t * t * (p3[1] - p2[1])
        heading = math.atan2(dy, dx)
        spread = 16 + 44 * math.sin(math.pi * t)
        off = rng.gauss(0, spread)
        x += -math.sin(heading) * off
        y += math.cos(heading) * off
        size = 3.0 + 12.0 * u * u + rng.uniform(-1.0, 1.5)
        if size < 1.5 or not clear(x, y, size):
            continue
        angle = heading + rng.uniform(-0.9, 0.9)
        petals.append((x, y, size, angle, 0.34 + 0.26 * t))
    for _ in range(10):
        x, y = rng.uniform(20, 780), rng.uniform(20, _EXPEDITION_HORIZON - 20)
        size = rng.uniform(1.8, 4.5)
        if clear(x, y, size):
            petals.append((x, y, size, rng.uniform(0, math.pi), 0.5))
    return petals


def _expedition_paint_petals(image: Image.Image, quote_row: dict) -> None:
    """The gust: each petal a red + white stipple with a white rim toward the
    light and a red one away from it."""
    width, height = image.size
    px = pixel_access(image)
    red, white = SPECTRA6["red"], SPECTRA6["white"]
    lx, ly = _EXPEDITION_NUMERAL_CENTRE
    for x, y, size, angle, density in _expedition_gust(quote_row):
        if size < 2.6:
            ix, iy = round(x), round(y)
            for ox, oy, ink in ((0, 0, white), (1, 0, red), (0, 1, red), (1, 1, white)):
                if 0 <= ix + ox < width and 0 <= iy + oy < height:
                    px[ix + ox, iy + oy] = ink
            continue
        pts = _expedition_petal_polygon(x, y, size, angle)
        bx0 = max(0, int(min(p[0] for p in pts)) - 1)
        by0 = max(0, int(min(p[1] for p in pts)) - 1)
        bx1 = min(width - 1, int(max(p[0] for p in pts)) + 1)
        by1 = min(height - 1, int(max(p[1] for p in pts)) + 1)
        mask = Image.new("L", (bx1 - bx0 + 1, by1 - by0 + 1), 0)
        ImageDraw.Draw(mask).polygon([(p[0] - bx0, p[1] - by0) for p in pts], fill=255)
        edge = ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(3)))
        mp, ep = pixel_access(mask), pixel_access(edge)
        toward = math.atan2(ly - y, lx - x)
        tx, ty = math.cos(toward), math.sin(toward)
        for yy in range(mask.size[1]):
            row = BAYER_4x4[(by0 + yy) % 4]
            for xx in range(mask.size[0]):
                if not mp[xx, yy]:
                    continue
                ax, ay = bx0 + xx, by0 + yy
                if ep[xx, yy]:
                    px[ax, ay] = white if (ax - x) * tx + (ay - y) * ty > 0 else red
                else:
                    px[ax, ay] = white if row[ax % 4] < density * 16 else red


def _expedition_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The journal page: white Fell roman over a black halo, the matched
    phrase in Fell italic and the number's own paint."""
    prose, hot, _ = wrap_quote_into_masks(
        draw, image.size, quote_row, _EXPEDITION_QUOTE_RECT, theme="expedition",
        font_max=31, font_min=13, line_height_mult=1.36,
    )
    _halo_paste(image, ImageChops.lighter(prose, hot), None)
    image.paste(SPECTRA6["white"], (0, 0), prose.point(lambda v: 255 if v > 110 else 0))
    paint_neon_mask(image, hot, SPECTRA6["yellow"], SPECTRA6["red"], radius=3, gamma=1.8, cap=0.5,
                    ground=frozenset({SPECTRA6["black"]}), tile=BAYER_8x8,
                    glow_minor=SPECTRA6["yellow"], glow_minor_share=0.5)
    prose.close()
    hot.close()


def _expedition_paint_byline(image: Image.Image, quote_row: dict) -> None:
    """Author and title as the journal's signature, gold Bebas capitals."""
    x0, _, x1, _ = _EXPEDITION_QUOTE_RECT
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "")
    byline = "  ·  ".join(part.upper() for part in (author, title) if part)
    if not byline:
        return
    mask = Image.new("L", image.size, 0)
    md = ImageDraw.Draw(mask)
    candidates = [BEBASNEUE_REGULAR, (ANTONIO_VARIABLE, "Bold"), *META_FONT_BOLD_CANDIDATES]
    font, text = fit_text_to_width(md, byline, candidates, 17, x1 - x0, floor=13, tracking=3)
    w = tracked_width(md, text, font, tracking=3)
    draw_tracked(md, ((x0 + x1 - w) / 2, _EXPEDITION_BYLINE_TOP), text, font, 255, tracking=3)
    _halo_paste(image, mask, SPECTRA6["yellow"], halo=5)
    mask.close()


def _expedition_paint_chrome(image: Image.Image) -> None:
    """The wordmark and its gold rule, and the expedition's credo."""
    yellow, white = SPECTRA6["yellow"], SPECTRA6["white"]
    x0, y0, _, _ = _EXPEDITION_WORDMARK_BOX
    mask = Image.new("L", image.size, 0)
    md = ImageDraw.Draw(mask)
    draw_tracked(md, (x0 + 2, y0 + 2), "CLAIR OBSCUR", _expedition_label_font(15), 255, tracking=6)
    draw_tracked(md, (x0, y0 + 20), "EXPEDITION 33", _expedition_wordmark_font(25), 255, tracking=3)
    _halo_paste(image, mask, white, halo=5)
    mask.close()
    # The rule: a gold hairline with a diamond at its centre — the ornament
    # every panel of the game's interface is drawn with.
    draw = ImageDraw.Draw(image)
    ry = y0 + 56
    rx1 = x0 + 262
    draw.line([(x0, ry), (rx1, ry)], fill=yellow, width=1)
    mid = (x0 + rx1) // 2
    draw.polygon([(mid, ry - 4), (mid + 4, ry), (mid, ry + 4), (mid - 4, ry)], fill=yellow)
    draw.polygon([(x0, ry - 2), (x0 + 2, ry), (x0, ry + 2), (x0 - 2, ry)], fill=yellow)
    draw.polygon([(rx1, ry - 2), (rx1 + 2, ry), (rx1, ry + 2), (rx1 - 2, ry)], fill=yellow)

    cx0, cy0, cx1, _ = _EXPEDITION_CREDO_BOX
    mask = Image.new("L", image.size, 0)
    md = ImageDraw.Draw(mask)
    font = _expedition_label_font(16)
    draw_tracked(md, (cx1, cy0 + 2), "FOR THOSE WHO COME AFTER", font, 255, tracking=4, anchor_right=True)
    _halo_paste(image, mask, yellow, halo=5)
    mask.close()


def render_expedition_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The Monolith from the Lumière promenade (see the section comment above)."""
    hour = _clock_hour12(time_str)
    image = _expedition_background().copy()
    draw = ImageDraw.Draw(image)
    _expedition_paint_numeral(image, hour)
    _expedition_paint_petals(image, quote_row)
    _expedition_paint_quote(image, draw, quote_row)
    _expedition_paint_byline(image, quote_row)
    _expedition_paint_chrome(image)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("expedition",), render=render_expedition_frame)
