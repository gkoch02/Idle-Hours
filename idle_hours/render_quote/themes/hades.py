"""The ``hades`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .._paths import (
    CAESARDRESSING_REGULAR,
    CINZELDECORATIVE_BOLD,
    HAMMERSMITHONE_REGULAR,
    JOST_VARIABLE,
    LATO_BOLD,
    META_FONT_BOLD_CANDIDATES,
    META_FONT_CANDIDATES,
    SPECTRAL_MEDIUM,
    SPECTRALSC_MEDIUM,
)
from ..fonts import load_font
from ..furniture import _clock_hour12, _paint_placed, _place_quote, _row_digest, fallback_title
from ..palette import _PANEL_INKS, SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, _dither_calibrated, snap_image_to_palette
from ..primitives import _lerp_stops, _smooth_noise, _white_noise, paint_neon_mask
from ..text import draw_tracked, fit_text_to_width, tracked_width

# ---------------------------------------------------------------------------
# hades — Supergiant Games' *Hades II* (2025): a boon at the Crossroads under
# the moon
# ---------------------------------------------------------------------------
# The Crossroads at night, lit by the moon and Hecate's green witchfire, and a
# **boon** card: dark, gold-framed, a portrait medallion at the left, the god's
# name across the top and the description beneath. The author is the god, the
# quote is the boon, the matched phrase is lit in gold.
#
# **The moon is the hour**: full at twelve, new at six, first quarter at nine,
# last quarter at three. Hour-only, pinned byte-identical across the minutes
# of an hour by ``TestHadesFrame``. The terminator is the ellipse
# ``x = cos(2πp)·√(1-y²)``; the unlit limb keeps a thin blue rim so a new moon
# is still a moon.
#
# **The sky is painted in continuous tone and dithered** against the
# calibrated inks (the ``expedition`` posture; black, blue, green, white, no
# red). Stars, ridge and braziers go on after the dither so they stay crisp;
# the brazier flame is a white core in a green bloom.
#
# **The card** is black with a sparse blue fleck (six-ink midnight) in a double
# gold rule with bossed corners and a **Greek-key frieze** (one continuous line
# on a 3 px grid). The medallion holds Chronos's **hourglass**, the sand Y with
# a red lattice so it reads amber rather than lemon.
#
# **Type**: Caesar Dressing for the author (yellow with a 1 px red stroke so it
# reads as beaten gold), Spectral for the body and matched phrase, Spectral SC
# for the title, Lato for the rarity label, Hammersmith One (the open
# Johnston) for the chrome.
#
# **Rarity is a roll**: ``_row_digest`` picks Common .. Legendary at the
# game's rough odds; pips are filled in the rarity's colour.
#
# The scene is quote- and hour-independent and painted once per process
# (``_HADES_SCENE``, keyed on the painters). Composed at 800x480 and
# NEAREST-downsampled (the ``metro`` convention).
# ---------------------------------------------------------------------------
_HADES_SEED = 0x4D454C                 # MEL
_HADES_HORIZON = 176                   # the card's top edge; the sky ends here
_HADES_RIDGE_Y = 156
_HADES_MOON_CENTRE = (636, 84)
_HADES_MOON_RADIUS = 46
_HADES_PANEL_RECT = (34, 176, 766, 448)
_HADES_PANEL_INSET = 7
_HADES_FRIEZE_UNIT = 3
_HADES_FRIEZE_TOP = 188                # the head frieze's top row; the foot's mirrors it
_HADES_MEDALLION_CENTRE = (130, 310)
_HADES_MEDALLION_RADIUS = 66
_HADES_DIVIDER_X = 216
_HADES_TITLE_X = 238
_HADES_TITLE_RIGHT = 738
_HADES_TITLE_Y = 204
_HADES_RULE_Y = 250
_HADES_QUOTE_RECT = (238, 260, 738, 396)
_HADES_FOOT_Y = 404
_HADES_BRAZIERS = (84, 716)            # the torches on the ridge
_HADES_WORDMARK_XY = (36, 16)
_HADES_LABEL_XY = (37, 48)
# Two quantisers, the ``expedition`` posture: the upper sky without green
# (the grain otherwise tips the zenith's black-violet into green specks)
# and the horizon band with it, where the teal and the witchfire live.
_HADES_SKY_INKS = ("black", "blue", "white")
_HADES_HORIZON_INKS = ("black", "blue", "green", "white")
_HADES_HORIZON_BAND = 112              # green is admitted below this row
# Night, top to the card's edge, in the calibrated space: black-violet
# zenith, the panel's blue, a teal glow at the horizon.
_HADES_SKY_STOPS = (
    (0, (24, 26, 52)), (60, (30, 40, 88)), (120, (36, 56, 112)),
    (156, (40, 70, 110)), (_HADES_HORIZON, (44, 84, 96)),
)
_HADES_MOON_GLOW = (150, 168, 184)
_HADES_WITCH_GLOW = (66, 122, 92)
# (label, pips, pip fill, pip outline) at the game's rough odds; the roll is
# ``_row_digest`` mod 100 against ``_HADES_RARITY_FLOORS``.
_HADES_RARITIES = (
    ("COMMON", 1, "white", "white"),
    ("RARE", 2, "blue", "blue"),
    ("EPIC", 3, "blue", "red"),
    ("HEROIC", 4, "red", "red"),
    ("LEGENDARY", 5, "yellow", "yellow"),
)
_HADES_RARITY_FLOORS = (0, 50, 78, 92, 98)
_HADES_SCENE: dict = {}


def _hades_phase(hour: int) -> float:
    """Lunar phase for the hour, 0 new .. 0.5 full .. 1 new: full at twelve,
    new at six, first quarter at nine, last quarter at three."""
    return ((hour % 12) + 6) / 12.0 % 1.0


def _hades_title_font(size: int):
    """Caesar Dressing — the game's title-card face — before Cinzel Decorative."""
    return load_font([CAESARDRESSING_REGULAR, CINZELDECORATIVE_BOLD, *META_FONT_BOLD_CANDIDATES], size=size)


def _hades_chrome_font(size: int):
    """Hammersmith One — the open Johnston, for the game's P22 Underground chrome."""
    return load_font([HAMMERSMITHONE_REGULAR, (JOST_VARIABLE, "Medium"), *META_FONT_BOLD_CANDIDATES], size=size)


def _hades_label_font(size: int):
    """Lato Bold — the game's secondary face — for the rarity label."""
    return load_font([LATO_BOLD, *META_FONT_BOLD_CANDIDATES], size=size)


def _hades_paint_sky(scene: Image.Image) -> None:
    """The night in continuous tone: the gradient, the brush facture, the
    moon's halo and the witch-glow pooled under the braziers."""
    width, height = scene.size
    hz = _HADES_HORIZON
    column = Image.new("RGB", (1, hz))
    cp = column.load()
    for y in range(hz):
        cp[0, y] = _lerp_stops(_HADES_SKY_STOPS, y)
    scene.paste(column.resize((width, hz), Image.Resampling.NEAREST), (0, 0))
    scene.paste(Image.new("RGB", (width, height - hz), _HADES_SKY_STOPS[-1][1]), (0, hz))
    # Brush facture: a stretched noise, ±7 levels, so the dither lays grain
    # across the sky rather than a flat field.
    grain = _smooth_noise((width, height), (64, 24), _HADES_SEED + 1).point(lambda v: v // 18)
    tint = Image.merge("RGB", (grain, grain, grain))
    scene.paste(ImageChops.subtract(ImageChops.add(scene, tint), Image.new("RGB", scene.size, (7, 7, 7))))
    # The moon's halo.
    mx, my = _HADES_MOON_CENTRE
    reach = _HADES_MOON_RADIUS * 1.7
    halo = Image.new("L", scene.size, 0)
    ImageDraw.Draw(halo).ellipse((mx - reach, my - reach, mx + reach, my + reach), fill=255)
    halo = halo.filter(ImageFilter.GaussianBlur(36)).point(lambda v: int(v * 0.62))
    scene.paste(Image.new("RGB", scene.size, _HADES_MOON_GLOW), (0, 0), halo)
    # Witchfire pooled on the horizon under each brazier.
    fire = Image.new("L", scene.size, 0)
    fd = ImageDraw.Draw(fire)
    for bx in _HADES_BRAZIERS:
        fd.ellipse((bx - 80, _HADES_RIDGE_Y - 40, bx + 80, _HADES_RIDGE_Y + 44), fill=255)
    fire = fire.filter(ImageFilter.GaussianBlur(28)).point(lambda v: int(v * 0.55))
    scene.paste(Image.new("RGB", scene.size, _HADES_WITCH_GLOW), (0, 0), fire)


def _hades_paint_stars(image: Image.Image) -> None:
    """A seeded field of stars above the ridge, clear of the moon: most a
    single white pixel, some a 2x2, a few a four-point cross."""
    rng = random.Random(_HADES_SEED + 2)
    draw = ImageDraw.Draw(image)
    px = image.load()
    white = SPECTRA6["white"]
    mx, my = _HADES_MOON_CENTRE
    keep = _HADES_MOON_RADIUS + 28
    for _ in range(190):
        x, y = rng.randrange(4, image.size[0] - 4), rng.randrange(4, _HADES_RIDGE_Y - 24)
        roll = rng.random()
        if math.hypot(x - mx, y - my) < keep:
            continue
        if roll < 0.72:
            px[x, y] = white
        elif roll < 0.92:
            draw.rectangle((x, y, x + 1, y + 1), fill=white)
        else:
            draw.line([(x - 3, y), (x + 3, y)], fill=white, width=1)
            draw.line([(x, y - 3), (x, y + 3)], fill=white, width=1)


def _hades_paint_ridge(image: Image.Image) -> None:
    """The Crossroads' horizon in silhouette: a low ridge over black earth
    that runs to the foot of the frame, cypresses, and two broken columns
    with a blue fluting glint on the taller one."""
    draw = ImageDraw.Draw(image)
    black, blue = SPECTRA6["black"], SPECTRA6["blue"]
    rng = random.Random(_HADES_SEED + 3)
    width = image.size[0]
    height = image.size[1]
    ridge = [(0, height)]
    x, y = 0, _HADES_RIDGE_Y + 6
    while x <= width:
        ridge.append((x, y))
        x += rng.randint(30, 70)
        y = max(_HADES_RIDGE_Y - 6, min(_HADES_RIDGE_Y + 12, y + rng.randint(-6, 6)))
    ridge.extend([(width, y), (width, height)])
    draw.polygon(ridge, fill=black)
    earth = Image.new("L", image.size, 0)
    ImageDraw.Draw(earth).polygon(ridge, fill=255)
    fleck = _white_noise(width, height, _HADES_SEED + 8).point(lambda v: 255 if v < 6 else 0)
    image.paste(blue, (0, 0), ImageChops.multiply(earth, fleck))
    earth.close()
    base = _HADES_RIDGE_Y + 8
    for cx, h, w in ((188, 64, 12), (212, 88, 15), (236, 56, 11), (462, 70, 13), (484, 48, 10), (556, 94, 16)):
        draw.polygon([(cx, base - h), (cx + w * 0.34, base - h * 0.74), (cx + w * 0.5, base - h * 0.42),
                      (cx + w * 0.4, base), (cx - w * 0.4, base), (cx - w * 0.5, base - h * 0.42),
                      (cx - w * 0.34, base - h * 0.74)], fill=black)
    for cx, h, broken in ((330, 72, False), (372, 44, True)):
        draw.rectangle((cx - 7, base - h, cx + 7, base), fill=black)
        if broken:
            draw.polygon([(cx - 7, base - h), (cx - 3, base - h - 9), (cx + 2, base - h - 3),
                          (cx + 7, base - h - 11), (cx + 7, base - h)], fill=black)
        else:
            draw.rectangle((cx - 11, base - h - 6, cx + 11, base - h), fill=black)
            draw.line([(cx - 3, base - h + 4), (cx - 3, base - 2)], fill=blue, width=1)


def _hades_paint_braziers(image: Image.Image) -> None:
    """Hecate's torches on the ridge: a gold tripod and bowl, and a flame
    that is a white core in a green bloom — witchfire."""
    draw = ImageDraw.Draw(image)
    black, yellow = SPECTRA6["black"], SPECTRA6["yellow"]
    flame = Image.new("L", image.size, 0)
    fd = ImageDraw.Draw(flame)
    by = _HADES_RIDGE_Y
    for bx in _HADES_BRAZIERS:
        for dx in (-9, 0, 9):
            draw.line([(bx + dx * 1.7, by + 22), (bx + dx * 0.4, by + 4)], fill=yellow, width=2)
        draw.chord((bx - 16, by - 10, bx + 16, by + 12), 0, 180, fill=black, outline=yellow, width=2)
        draw.line([(bx - 17, by + 1), (bx + 17, by + 1)], fill=yellow, width=2)
        fd.polygon([(bx, by - 48), (bx + 7, by - 30), (bx + 11, by - 12), (bx + 6, by - 2), (bx - 6, by - 2),
                    (bx - 11, by - 14), (bx - 6, by - 32)], fill=255)
        fd.polygon([(bx + 8, by - 36), (bx + 15, by - 22), (bx + 9, by - 6)], fill=255)
        fd.polygon([(bx - 9, by - 32), (bx - 16, by - 20), (bx - 9, by - 6)], fill=255)
    paint_neon_mask(image, flame, SPECTRA6["white"], SPECTRA6["green"], radius=7, gamma=1.5, cap=0.62,
                    tile=BAYER_8x8, core_minor=SPECTRA6["green"], core_minor_share=0.45,
                    ground=frozenset({SPECTRA6["black"], SPECTRA6["blue"], SPECTRA6["green"]}))
    flame.close()


def _hades_meander(draw: ImageDraw.ImageDraw, x0: int, top: int, x1: int, ink, flip: bool = False) -> None:
    """A Greek key as one continuous line on a ``_HADES_FRIEZE_UNIT`` grid:
    a baseline with a square spiral rising from it every period. ``flip``
    hangs the spirals from the baseline instead, for the foot."""
    u = _HADES_FRIEZE_UNIT
    period = 4 * u
    n = int((x1 - x0) // period)

    def row(k: int) -> int:
        return top + (3 - k) * u if flip else top + k * u

    draw.line([(x0, row(3)), (x0 + n * period, row(3))], fill=ink, width=1)
    x = x0
    for _ in range(n):
        draw.line([(x, row(3)), (x, row(0)), (x + 3 * u, row(0)), (x + 3 * u, row(2)),
                   (x + u, row(2)), (x + u, row(1)), (x + 2 * u, row(1))], fill=ink, width=1)
        x += period


def _hades_paint_panel(image: Image.Image) -> None:
    """The boon card: a midnight ground (black with a blue fleck) in a double
    gold rule, a meander frieze at the head and foot, bossed corners, and the
    divider between the portrait and the text."""
    x0, y0, x1, y1 = _HADES_PANEL_RECT
    draw = ImageDraw.Draw(image)
    black, yellow, blue = SPECTRA6["black"], SPECTRA6["yellow"], SPECTRA6["blue"]
    draw.rectangle((x0, y0, x1, y1), fill=black)
    fleck = _white_noise(x1 - x0 + 1, y1 - y0 + 1, _HADES_SEED + 5).point(lambda v: 255 if v < 9 else 0)
    image.paste(blue, (x0, y0), fleck)
    draw.rectangle((x0, y0, x1, y1), outline=yellow, width=2)
    i = _HADES_PANEL_INSET
    draw.rectangle((x0 + i, y0 + i, x1 - i, y1 - i), outline=yellow, width=1)
    frieze_h = 3 * _HADES_FRIEZE_UNIT
    _hades_meander(draw, x0 + 30, _HADES_FRIEZE_TOP, x1 - 30, yellow)
    _hades_meander(draw, x0 + 30, y1 - (_HADES_FRIEZE_TOP - y0) - frieze_h, x1 - 30, yellow, flip=True)
    for cx, cy in ((x0 + 18, y0 + 18), (x1 - 18, y0 + 18), (x0 + 18, y1 - 18), (x1 - 18, y1 - 18)):
        draw.polygon([(cx, cy - 7), (cx + 7, cy), (cx, cy + 7), (cx - 7, cy)], fill=yellow)
        draw.polygon([(cx, cy - 2), (cx + 2, cy), (cx, cy + 2), (cx - 2, cy)], fill=black)
    dx = _HADES_DIVIDER_X
    draw.line([(dx, y0 + 34), (dx, y1 - 34)], fill=yellow, width=1)
    for fy in (y0 + 30, y1 - 30):
        draw.polygon([(dx, fy - 5), (dx + 4, fy), (dx, fy + 5), (dx - 4, fy)], fill=yellow)


def _hades_hourglass_masks(size, cx: int, cy: int, s: int, w: int) -> tuple[Image.Image, Image.Image, list, list]:
    """The two bulbs as ``L`` masks plus their outlines: wide at the frame
    bars, three pixels at the neck."""
    def bulb(sign: int) -> list:
        right = []
        for k in range(13):
            t = k / 12.0
            right.append((cx + w * (1 - t ** 2.2) + 3 * t ** 2.2, cy + sign * (s - t * (s - 2))))
        return right + [(2 * cx - x, y) for x, y in reversed(right)]

    upper, lower = bulb(-1), bulb(1)
    masks = []
    for pts in (upper, lower):
        mask = Image.new("L", size, 0)
        ImageDraw.Draw(mask).polygon(pts, fill=255)
        masks.append(mask)
    return masks[0], masks[1], upper, lower


def _hades_paint_medallion(image: Image.Image) -> None:
    """The portrait medallion: a blue bloom behind a black disc in gold
    rings, with Chronos's hourglass in it and his name beneath."""
    cx, cy = _HADES_MEDALLION_CENTRE
    r = _HADES_MEDALLION_RADIUS
    black, yellow, blue, red = SPECTRA6["black"], SPECTRA6["yellow"], SPECTRA6["blue"], SPECTRA6["red"]
    glow = Image.new("L", image.size, 0)
    ImageDraw.Draw(glow).ellipse((cx - r + 2, cy - r + 2, cx + r - 2, cy + r - 2), fill=255)
    paint_neon_mask(image, glow, None, blue, radius=16, gamma=1.3, cap=0.5, tile=BAYER_8x8,
                    ground=frozenset({black, blue}))
    glow.close()
    draw = ImageDraw.Draw(image)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=black)
    disc = Image.new("L", image.size, 0)
    ImageDraw.Draw(disc).ellipse((cx - r + 8, cy - r + 8, cx + r - 8, cy + r - 8), fill=255)
    speck = _white_noise(image.size[0], image.size[1], _HADES_SEED + 6).point(lambda v: 255 if v < 30 else 0)
    image.paste(blue, (0, 0), ImageChops.multiply(disc, speck))
    disc.close()
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=yellow, width=3)
    draw.ellipse((cx - r + 7, cy - r + 7, cx + r - 7, cy + r - 7), outline=yellow, width=1)
    for k in range(8):
        a = math.radians(k * 45)
        tx, ty = cx + math.cos(a) * (r - 4), cy + math.sin(a) * (r - 4)
        draw.ellipse((tx - 2, ty - 2, tx + 2, ty + 2), fill=yellow)
    # The hourglass: frame bars and posts, the bulbs outlined, the sand.
    s, w = 38, 24
    draw.rectangle((cx - w - 5, cy - s - 5, cx + w + 5, cy - s), fill=yellow)
    draw.rectangle((cx - w - 5, cy + s, cx + w + 5, cy + s + 5), fill=yellow)
    for sx in (-1, 1):
        draw.line([(cx + sx * (w + 3), cy - s), (cx + sx * (w + 3), cy + s)], fill=yellow, width=2)
    upper_mask, lower_mask, upper, lower = _hades_hourglass_masks(image.size, cx, cy, s, w)
    sand = Image.new("L", image.size, 0)
    sd = ImageDraw.Draw(sand)
    sd.rectangle((cx - w, cy - s * 0.5, cx + w, cy), fill=255)
    sd.polygon([(cx - w * 0.85, cy + s), (cx, cy + s * 0.3), (cx + w * 0.85, cy + s)], fill=255)
    sand = ImageChops.multiply(sand, ImageChops.lighter(upper_mask, lower_mask))
    image.paste(yellow, (0, 0), sand)
    lattice = Image.new("L", image.size, 0)
    lp = lattice.load()
    bbox = sand.getbbox()
    if bbox:
        for y in range(bbox[1], bbox[3], 2):
            for x in range(bbox[0] + (y // 2) % 2, bbox[2], 2):
                lp[x, y] = 255
    image.paste(red, (0, 0), ImageChops.multiply(sand, lattice))
    for pts in (upper, lower):
        draw.line(pts + [pts[0]], fill=yellow, width=2, joint="curve")
    draw.line([(cx, cy - 1), (cx, cy + s - 8)], fill=yellow, width=1)
    for m in (upper_mask, lower_mask, sand, lattice):
        m.close()
    font = _hades_chrome_font(12)
    draw_tracked(draw, (cx - tracked_width(draw, "CHRONOS", font, tracking=4) / 2, cy + r + 10),
                 "CHRONOS", font, yellow, tracking=4)


def _hades_paint_label(image: Image.Image) -> None:
    """The title card at the top left: the wordmark in Caesar Dressing over
    the location in the open Johnston."""
    draw = ImageDraw.Draw(image)
    yellow, white = SPECTRA6["yellow"], SPECTRA6["white"]
    mark = _hades_title_font(24)
    x, y = _HADES_WORDMARK_XY
    for ch in "HADES II":
        draw.text((x, y), ch, font=mark, fill=yellow, stroke_width=1, stroke_fill=SPECTRA6["red"])
        x += draw.textlength(ch, font=mark) + 3
    label = _hades_chrome_font(12)
    w = draw_tracked(draw, _HADES_LABEL_XY, "THE CROSSROADS", label, white, tracking=5)
    lx, ly = _HADES_LABEL_XY
    draw.line([(lx, ly + 19), (lx + w, ly + 19)], fill=yellow, width=1)


def _hades_scene() -> Image.Image:
    """The card without its boon: sky, stars, ridge, braziers, card,
    medallion, title card. Painted once per process."""
    key = (_hades_paint_sky, _hades_paint_stars, _hades_paint_ridge, _hades_paint_braziers,
           _hades_paint_panel, _hades_paint_medallion, _hades_paint_label)
    cached = _HADES_SCENE.get("frame")
    if cached is not None and cached[0] == key:
        return cached[1]
    size = (800, 480)
    scene = Image.new("RGB", size, _PANEL_INKS["black"])
    _hades_paint_sky(scene)
    image = _dither_calibrated(scene, _HADES_SKY_INKS)
    horizon = _dither_calibrated(scene, _HADES_HORIZON_INKS)
    # Feathered over 40 rows, so the seam between the quantisers is a drift
    # of green into the blue rather than a rule across the sky.
    band = Image.new("L", size, 0)
    ImageDraw.Draw(band).rectangle((0, _HADES_HORIZON_BAND + 20, size[0], size[1]), fill=255)
    band = band.filter(ImageFilter.GaussianBlur(12))
    image = Image.composite(horizon, image, band.point(lambda v: 255 if v > 128 - (v % 7) * 18 else 0))
    _hades_paint_stars(image)
    _hades_paint_ridge(image)
    _hades_paint_braziers(image)
    _hades_paint_panel(image)
    _hades_paint_medallion(image)
    _hades_paint_label(image)
    _HADES_SCENE["frame"] = (key, image)
    return image


def _hades_paint_moon(image: Image.Image, hour: int) -> None:
    """The moon at the hour's phase: the lit disc white with a blue dapple
    of maria, the unlit disc black with a thin blue rim."""
    phase = _hades_phase(hour)
    cx, cy = _HADES_MOON_CENTRE
    r = _HADES_MOON_RADIUS
    white, black, blue = SPECTRA6["white"], SPECTRA6["black"], SPECTRA6["blue"]
    maria = _smooth_noise((2 * r + 1, 2 * r + 1), (26, 26), _HADES_SEED + 7)
    mp = maria.load()
    px = image.load()
    k = math.cos(2 * math.pi * phase)
    waxing = phase < 0.5
    for y in range(cy - r, cy + r + 1):
        v = (y - cy) / r
        half = math.sqrt(max(0.0, 1 - v * v))
        term = k * half
        for x in range(cx - r, cx + r + 1):
            u = (x - cx) / r
            rr = u * u + v * v
            if rr > 1:
                continue
            lit = (u > term) if waxing else (u < -term)
            if lit:
                px[x, y] = blue if mp[x - cx + r, y - cy + r] < 58 else white
            else:
                px[x, y] = blue if rr > 0.86 else black


def _hades_paint_title(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The boon's name — the author — in Caesar Dressing, gold with a red
    stroke, over a gold rule with a diamond."""
    yellow, red = SPECTRA6["yellow"], SPECTRA6["red"]
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "")
    name = (author or title or "The Crossroads").upper()
    font, text = fit_text_to_width(draw, name, [CAESARDRESSING_REGULAR, CINZELDECORATIVE_BOLD, *META_FONT_BOLD_CANDIDATES],
                                   36, _HADES_TITLE_RIGHT - _HADES_TITLE_X, floor=22, tracking=2)
    x = _HADES_TITLE_X
    for ch in text:
        draw.text((x, _HADES_TITLE_Y), ch, font=font, fill=yellow, stroke_width=1, stroke_fill=red)
        x += draw.textlength(ch, font=font) + 2
    ry = _HADES_RULE_Y
    draw.line([(_HADES_TITLE_X + 10, ry), (_HADES_TITLE_RIGHT, ry)], fill=yellow, width=1)
    draw.polygon([(_HADES_TITLE_X + 4, ry - 4), (_HADES_TITLE_X + 8, ry), (_HADES_TITLE_X + 4, ry + 4),
                  (_HADES_TITLE_X, ry)], fill=yellow)


def _hades_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The boon's text: white Spectral, ragged right, the matched phrase
    SemiBold in gold — the card's highlighted key words."""
    placed = _place_quote(draw, quote_row, _HADES_QUOTE_RECT, theme="hades",
                          font_max=30, font_min=14, line_height_mult=1.3)
    _paint_placed(draw, placed, SPECTRA6["white"], SPECTRA6["yellow"])


def _hades_rarity(quote_row: dict) -> int:
    """The boon's rarity, 0 Common .. 4 Legendary: a roll from the digest."""
    roll = _row_digest(quote_row) % 100
    return max(i for i, floor in enumerate(_HADES_RARITY_FLOORS) if roll >= floor)


def _hades_paint_foot(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The foot: the rarity pips and label at the left, the book's title in
    small caps at the right."""
    yellow, white = SPECTRA6["yellow"], SPECTRA6["white"]
    label, pips, fill, outline = _HADES_RARITIES[_hades_rarity(quote_row)]
    y = _HADES_FOOT_Y
    for k in range(5):
        cx, cy = _HADES_TITLE_X + 6 + k * 16, y + 9
        diamond = [(cx, cy - 6), (cx + 6, cy), (cx, cy + 6), (cx - 6, cy)]
        if k < pips:
            draw.polygon(diamond, fill=SPECTRA6[fill], outline=SPECTRA6[outline])
        else:
            draw.line(diamond + [diamond[0]], fill=yellow, width=1)
    draw_tracked(draw, (_HADES_TITLE_X + 5 * 16 + 8, y + 2), label, _hades_label_font(12), white, tracking=3)
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "").strip()
    if title:
        font, text = fit_text_to_width(draw, title, [SPECTRALSC_MEDIUM, SPECTRAL_MEDIUM, *META_FONT_CANDIDATES],
                                       15, _HADES_TITLE_RIGHT - _HADES_TITLE_X - 200, floor=12, tracking=1)
        draw_tracked(draw, (_HADES_TITLE_RIGHT, y + 1), text, font, white, tracking=1, anchor_right=True)


def render_hades_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A boon at the Crossroads under the moon (see the section comment above)."""
    hour = _clock_hour12(time_str)
    image = _hades_scene().copy()
    draw = ImageDraw.Draw(image)
    _hades_paint_moon(image, hour)
    _hades_paint_title(image, draw, quote_row)
    _hades_paint_quote(image, draw, quote_row)
    _hades_paint_foot(image, draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image
