"""The ``atropos`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random
from itertools import pairwise

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

from .._paths import META_FONT_BOLD_CANDIDATES, MICHROMA_REGULAR, OXANIUM_VARIABLE, SAIRA_VARIABLE
from ..fonts import load_font
from ..furniture import _clock_hour12, _row_digest, fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, dither_image_to_palette, snap_image_to_palette
from ..primitives import _halo_paste, _lerp_stops, _smooth_noise, _white_noise, paint_neon_mask, wrap_quote_into_masks
from ..spec import FrameSpec
from ..text import draw_tracked, fit_text_to_width, tracked_width

# ---------------------------------------------------------------------------
# atropos — Housemarque's *Returnal* (2021): night in the Overgrown Ruins
# ---------------------------------------------------------------------------
# One night in the rain-soaked ruins: teal fog over a black plain, rain, the
# Sentient statues, the wreck of the *Helios*, black tendrils glowing where
# alive, bullet-hell orbs, and a HUD over it all. The quote is a **xenoglyph
# cipher** the scout has just translated.
#
# **Cold scene, hot layer — two passes, two palettes.** The night is painted
# in continuous tone and Floyd–Steinberg-dithered to **black / blue / green /
# white only**, so error diffusion can never warm it; the teal is a B+G mix
# whose density falls with the fog, hence dithered rather than stippled.
# Everything that glows is laid on top through ``paint_neon_mask`` with
# ``ground`` pinned to the three cold inks: ember nodules, hot orbs and the
# matched phrase in a yellow core with a tangerine halo (red with yellow at
# 3/8), violet orbs in a white core with a blue + red halo at 1/2.
#
# **The scene is quote-independent and cached** (``_ATROPOS_BACKGROUND``,
# keyed on the painters, the ``biomech`` pattern). Orbs, cipher and HUD
# readings are seeded from ``_row_digest``, never ``hash()`` or the clock.
#
# **The cipher is the quote in alien script.** ``_atropos_glyph`` builds a
# 26-letter alphabet once from a fixed seed (three to five strokes on a 3x4
# lattice plus an optional dot); the slab carries the matched phrase and then
# the quote, so the same letter is always the same glyph. 1 px strokes are a
# single white ink so they survive the snap.
#
# **The time is the cycle counter, hour only** (``CYCLE 07`` top-right),
# pinned byte-identical across the minutes of an hour by ``TestAtroposFrame``.
# Custom frames never draw the debug banner, so no ``_DEBUG_LABEL_RIGHT_INSET``.
#
# **Saira** for the translation, **Michroma** for the HUD: the nearest open
# faces to Returnal's Erbaum and Kellion (see ``docs/themes.md``).
#
# Composed at 800x480 and NEAREST-downsampled (the ``metro`` convention).
# ---------------------------------------------------------------------------
_ATROPOS_SEED = 0xA7C0
_ATROPOS_HORIZON = 334
_ATROPOS_QUOTE_RECT = (166, 72, 666, 256)
_ATROPOS_BYLINE_BASELINE = 288
_ATROPOS_SLAB = (704, 60, 768, 406)         # the cipher monolith
_ATROPOS_STATUE = (104, 118)                # centre x, crown y of the near Sentient
_ATROPOS_GATE = (418, 302, 112)             # centre x, centre y, radius of the ring gate
_ATROPOS_HELIOS = (476, 212, 652, 332)      # bounding box of the wreck
_ATROPOS_HELIOS_BEACON = (598, 236)
_ATROPOS_CYCLE_RIGHT = 766
_ATROPOS_SCENE_PALETTE = [SPECTRA6["black"], SPECTRA6["blue"], SPECTRA6["green"], SPECTRA6["white"]]
_ATROPOS_COLD_GROUND = frozenset({SPECTRA6["black"], SPECTRA6["blue"], SPECTRA6["green"]})
_ATROPOS_SKY_STOPS = (
    (0, (0, 0, 0)), (140, (1, 4, 5)), (230, (4, 18, 20)), (284, (14, 56, 62)),
    (_ATROPOS_HORIZON, (42, 124, 128)),
)
_ATROPOS_GROUND_STOPS = ((_ATROPOS_HORIZON, (26, 84, 88)), (400, (9, 32, 34)), (480, (2, 8, 9)))
# Pools of lit fog, as (centre x, centre y, radius, strength): behind the near
# Sentient, so the figure reads as a silhouette in mist, and round the wreck,
# whose beacon lights the fog from inside.
_ATROPOS_FOG_LIGHTS = ((104, 236, 130, 0.62), (590, 262, 120, 0.5))
_ATROPOS_DARK = (3, 9, 10)                  # the silhouettes' own black, a hair off pure
_ATROPOS_RIM = (96, 178, 182)               # teal rim light the fog throws on an edge
_ATROPOS_BACKGROUND: dict = {}
_ATROPOS_PATHS: dict = {}
_ATROPOS_GLYPHS: dict = {}


def _atropos_font(size: int):
    """Michroma, falling back through the techno sans before the system faces."""
    return load_font([MICHROMA_REGULAR, (OXANIUM_VARIABLE, "Medium"), *META_FONT_BOLD_CANDIDATES], size=size)


def _atropos_haze(colour, amount: float):
    """``_ATROPOS_DARK`` pushed ``amount`` of the way toward ``colour`` — how far
    a silhouette has dissolved into the fog in front of it."""
    return tuple(round(d + (c - d) * amount) for d, c in zip(_ATROPOS_DARK, colour, strict=True))


def _atropos_paint_sky(image: Image.Image) -> None:
    """The night: a black zenith falling to teal fog at the horizon, the fog
    banked by stretched noise, spores drifting in the air, a wet plain below."""
    width, height = image.size
    hz = _ATROPOS_HORIZON
    column = Image.new("RGB", (1, height))
    for y in range(height):
        stops = _ATROPOS_SKY_STOPS if y <= hz else _ATROPOS_GROUND_STOPS
        column.putpixel((0, y), _lerp_stops(stops, y))
    image.paste(column.resize((width, height), Image.Resampling.NEAREST))

    # Fog banks: long horizontal streaks, densest just above the horizon.
    envelope = Image.new("L", (1, height))
    for y in range(height):
        e = math.exp(-((y - hz + 14) / 58.0) ** 2) if y <= hz + 20 else 0.0
        envelope.putpixel((0, y), round(255 * e))
    envelope = envelope.resize((width, height), Image.Resampling.NEAREST)
    streaks = _smooth_noise((width, height), (8, 44), _ATROPOS_SEED)
    light = ImageChops.multiply(streaks.point(lambda v: max(0, v - 120) * 3), envelope)
    bright = ImageEnhance.Brightness(image).enhance(1.75)
    image.paste(Image.composite(bright, image, light))

    # Lit pools in the fog, where something stands in it or burns inside it.
    pools = Image.new("L", (width, height), 0)
    pd = ImageDraw.Draw(pools)
    for px, py, pr, strength in _ATROPOS_FOG_LIGHTS:
        pd.ellipse((px - pr, py - pr * 0.8, px + pr, py + pr * 0.8), fill=round(255 * strength))
    pools = pools.filter(ImageFilter.GaussianBlur(44))
    lit = Image.composite(Image.new("RGB", (width, height), (52, 136, 140)), image, pools)
    image.paste(Image.blend(image, lit, 0.85))

    # Spores: a sparse scatter of pale teal motes hanging in the air.
    motes = _white_noise(width, height, _ATROPOS_SEED + 1).point(lambda v: 255 if v > 252 else 0)
    air = Image.new("L", (width, height), 0)
    ImageDraw.Draw(air).rectangle((0, 40, width, hz + 60), fill=255)
    motes = ImageChops.multiply(motes, air.filter(ImageFilter.GaussianBlur(30)))
    image.paste((96, 170, 172), (0, 0), motes)


def _atropos_paint_rain(image: Image.Image) -> None:
    """Rain: hundreds of short slanted streaks, brighter where the fog lights them."""
    width, height = image.size
    draw = ImageDraw.Draw(image)
    rng = random.Random(_ATROPOS_SEED + 2)
    for _ in range(380):
        x = rng.uniform(-20, width + 20)
        y = rng.uniform(-30, height)
        length = rng.uniform(9, 30)
        near = rng.random()
        tone = 0.25 + 0.75 * near * (0.45 + 0.55 * min(1.0, y / _ATROPOS_HORIZON))
        colour = tuple(round(c * tone) for c in (62, 138, 142))
        draw.line([(x, y), (x - length * 0.22, y + length)], fill=colour, width=1)


def _atropos_sentient(draw: ImageDraw.ImageDraw, cx: int, crown: int, scale: float, colour, rim=None) -> None:
    """A Sentient statue: the long crested skull swept back, a thin neck, sloped
    shoulders, a robe falling to the ground, arms hanging to elongated hands."""
    def pt(x, y):
        return (round(cx + x * scale), round(crown + y * scale))

    head = [pt(-11, 46), pt(-10, 24), pt(-2, 6), pt(18, -10), pt(48, -24), pt(56, -18), pt(44, -2),
            pt(26, 16), pt(16, 32), pt(11, 46), pt(5, 56), pt(-5, 56)]
    body = [pt(-5, 52), pt(5, 52), pt(7, 70), pt(28, 76), pt(36, 130), pt(44, 216), pt(-44, 216),
            pt(-36, 130), pt(-28, 76), pt(-7, 70)]
    arms = []
    for s in (-1, 1):
        arms.append([pt(s * 24, 80), pt(s * 36, 84), pt(s * 46, 150), pt(s * 48, 186), pt(s * 40, 188),
                     pt(s * 34, 152), pt(s * 26, 100)])
        for k in range(3):                                   # three long fingers
            fx = s * (38 + k * 5)
            arms.append([pt(fx - 1.5, 184), pt(fx + 1.5, 184), pt(fx + 2 + s * 2, 206 + k * 4), pt(fx - 1 + s * 2, 206 + k * 4)])
    if rim is not None:
        for poly in (head, body, *arms):
            draw.polygon([(x + 3, y - 1) for x, y in poly], fill=rim)
    for poly in (head, body, *arms):
        draw.polygon(poly, fill=colour)
    draw.polygon([pt(-3, 44), pt(3, 44), pt(3, 54), pt(-3, 54)], fill=colour)  # neck


def _atropos_paint_ruins(image: Image.Image) -> None:
    """Atropos at the horizon: a far skyline of broken monoliths, the ring
    gate, the layered pillars, the *Helios* on its nose, the Sentients, the
    cipher slab, then the plain's wet reflection of all of it."""
    width, height = image.size
    draw = ImageDraw.Draw(image)
    hz = _ATROPOS_HORIZON
    horizon_sky = _lerp_stops(_ATROPOS_SKY_STOPS, hz - 6)
    rng = random.Random(_ATROPOS_SEED + 3)

    # Far skyline: a broken row of monoliths, most dissolved into the fog.
    far = _atropos_haze(horizon_sky, 0.58)
    x = -10
    while x < width:
        w = rng.randint(8, 34)
        h = rng.randint(6, 54) + (30 if 560 < x < 700 else 0)
        lean = rng.randint(-4, 4)
        draw.polygon([(x, hz + 2), (x + lean, hz - h), (x + w + lean, hz - h + rng.randint(-8, 8)), (x + w, hz + 2)], fill=far)
        x += w + rng.randint(4, 40)

    # The ring gate, half sunk, with the fog brighter through it.
    gx, gy, gr = _ATROPOS_GATE
    through = Image.new("L", (width, height), 0)
    ImageDraw.Draw(through).ellipse((gx - gr + 10, gy - gr + 10, gx + gr - 10, gy + gr - 10), fill=120)
    sky = Image.new("L", (width, height), 0)
    ImageDraw.Draw(sky).rectangle((0, 0, width, hz), fill=255)
    through = ImageChops.multiply(through.filter(ImageFilter.GaussianBlur(26)), sky)
    image.paste(Image.composite(ImageEnhance.Brightness(image).enhance(1.9), image, through))
    gate = _atropos_haze(horizon_sky, 0.22)
    mask = Image.new("L", (width, height), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse((gx - gr, gy - gr, gx + gr, gy + gr), fill=255)
    md.ellipse((gx - gr + 12, gy - gr + 12, gx + gr - 12, gy + gr - 12), fill=0)
    md.rectangle((0, hz, width, height), fill=0)
    for k in range(8):                                      # carved notches round the ring
        a = -math.pi / 2 + k * math.pi / 7
        nx, ny = gx + math.cos(a) * (gr - 6), gy + math.sin(a) * (gr - 6)
        md.ellipse((nx - 4, ny - 4, nx + 4, ny + 4), fill=0)
    image.paste(gate, (0, 0), mask)

    # Layered pillars to the right, in front of the skyline, behind the slab.
    near = _atropos_haze(horizon_sky, 0.08)
    for px, pw, top in ((596, 22, 206), (628, 30, 176), (666, 18, 228), (690, 26, 190), (736, 34, 150)):
        draw.rectangle((px, top, px + pw, hz + 4), fill=near)
        draw.polygon([(px, top), (px + pw, top), (px + pw + 3, top - 6 - pw // 6), (px - 2, top - 3)], fill=near)
        for ly in range(top + 10, hz, 14):                   # the strata's seams
            draw.line([(px + 1, ly), (px + pw - 1, ly)], fill=_atropos_haze(horizon_sky, 0.26), width=1)
    draw.polygon([(590, 182), (730, 150), (734, 160), (594, 194)], fill=near)   # a fallen lintel

    # The Helios: nose buried, tail in the air, the hull split.
    hx0, hy0, hx1, hy1 = _ATROPOS_HELIOS
    hull = _atropos_haze(horizon_sky, 0.03)
    draw.polygon([(hx0 + 10, hy1), (hx0 + 34, hy1 - 30), (hx0 + 86, hy0 + 44), (hx1 - 48, hy0 + 2),
                  (hx1 - 20, hy0), (hx1, hy0 + 16), (hx1 - 36, hy0 + 48), (hx0 + 110, hy1 - 36),
                  (hx0 + 70, hy1)], fill=hull)
    draw.polygon([(hx1 - 44, hy0 + 20), (hx1 - 2, hy0 - 22), (hx1 + 8, hy0 - 14), (hx1 - 30, hy0 + 34)], fill=hull)  # fin
    for k in range(4):                                      # the cabin windows, lit by the fog
        wx, wy = hx0 + 96 + k * 16, hy0 + 40 - k * 6
        draw.rectangle((wx, wy, wx + 5, wy + 3), fill=(44, 110, 114))
    draw.line([(hx0 + 60, hy1 - 18), (hx0 + 84, hy0 + 62)], fill=(30, 84, 88), width=1)  # the split

    # The Sentients: one near, one a long way off.
    sx, sy = _ATROPOS_STATUE
    _atropos_sentient(draw, 262, 226, 0.5, _atropos_haze(horizon_sky, 0.3))
    _atropos_sentient(draw, sx, sy, 1.0, _ATROPOS_DARK, rim=_ATROPOS_RIM)

    # The cipher slab: a bevelled monolith, lighter where the fog catches its edge.
    x0, y0, x1, y1 = _ATROPOS_SLAB
    draw.rectangle((x0 - 4, y0 - 4, x1 + 4, y1 + 4), fill=(40, 96, 100))
    draw.rectangle((x0, y0, x1, y1), fill=(5, 14, 16))
    draw.line([(x0 - 4, y0 - 4), (x0 - 12, y0 + 4), (x0 - 12, y1 + 12), (x0 - 4, y1 + 4)], fill=(24, 60, 64), width=3)

    # Fog over every base, then the wet plain: the horizon mirrored, streaked.
    fog = Image.new("L", (1, height))
    for y in range(height):
        fog.putpixel((0, y), round(130 * math.exp(-((y - hz + 4) / 11.0) ** 2)))
    fog = ImageChops.multiply(fog.resize((width, height), Image.Resampling.NEAREST),
                              _smooth_noise((width, height), (14, 60), _ATROPOS_SEED + 4)).point(lambda v: min(255, v * 2))
    image.paste(Image.composite(Image.new("RGB", (width, height), (36, 104, 108)), image, fog))
    band = image.crop((0, hz - 70, width, hz)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    band = ImageEnhance.Brightness(band.resize((width, 110), Image.Resampling.BILINEAR)).enhance(0.55)
    wet = _smooth_noise((width, 110), (160, 3), _ATROPOS_SEED + 5).point(lambda v: max(0, v - 70) * 2)
    fade = Image.new("L", (1, 110))
    for y in range(110):
        fade.putpixel((0, y), round(255 * (1 - y / 110) ** 1.6))
    wet = ImageChops.multiply(wet, fade.resize((width, 110), Image.Resampling.NEAREST))
    image.paste(Image.composite(band, image.crop((0, hz, width, hz + 110)), wet), (0, hz))


def _atropos_tendril_paths() -> list:
    """The tendrils as ``(points, base_width, nodules)`` — a seeded random walk
    per root, pulled toward a target, with ember nodules dropped along the
    stem. Memoised: the tendril painter and the ember painter both read it,
    and the embers must sit on the stems that were actually drawn."""
    cached = _ATROPOS_PATHS.get("paths")
    if cached is not None:
        return cached
    rng = random.Random(_ATROPOS_SEED + 6)
    roots = (
        ((-12, 468), (70, 160), 13, 46), ((36, 492), (150, 350), 9, 24), ((210, 492), (560, 402), 11, 44),
        ((612, 494), (560, 318), 8, 30), ((812, 466), (736, 150), 13, 44), ((760, 494), (690, 372), 8, 22),
        ((-8, 300), (120, 400), 6, 26),
    )
    paths = []
    x: float
    y: float
    for (x, y), (tx, ty), base, steps in roots:
        heading = math.atan2(ty - y, tx - x)
        points: list[tuple[float, float]] = [(x, y)]
        nodules = []
        for i in range(steps):
            want = math.atan2(ty - y, tx - x)
            heading += (want - heading) * 0.14 + rng.gauss(0, 0.34)
            x += math.cos(heading) * 9
            y += math.sin(heading) * 9
            points.append((x, y))
            # Nodules only where they can be seen: on the canvas, and clear
            # of the HUD readouts along the foot that paint over the growth.
            if i > steps * 0.2 and rng.random() < 0.1 and 8 <= x <= 792 and 8 <= y <= 428:
                nodules.append((x, y, rng.uniform(2.6, 4.6)))
        paths.append((points, base, nodules))
    _ATROPOS_PATHS["paths"] = paths
    return paths


def _atropos_paint_tendrils(image: Image.Image) -> None:
    """The black growth: tapering stems with a teal rim, side shoots, and a
    swelling where each nodule will glow."""
    draw = ImageDraw.Draw(image)
    rng = random.Random(_ATROPOS_SEED + 7)
    for points, base, nodules in _atropos_tendril_paths():
        n = len(points) - 1
        for pass_colour, extra in ((_ATROPOS_RIM, 2), (_ATROPOS_DARK, 0)):
            for i, ((x0, y0), (x1, y1)) in enumerate(pairwise(points)):
                w = max(1, round(base * (1 - i / n) ** 0.8 + 1)) + extra
                draw.line([(x0, y0), (x1, y1)], fill=pass_colour, width=w)
                if extra == 0 and i % 6 == 3 and i < n - 4:              # a side shoot
                    a = math.atan2(y1 - y0, x1 - x0) + rng.choice((-1, 1)) * rng.uniform(0.7, 1.3)
                    length = rng.uniform(10, 26) * (1 - i / n)
                    draw.line([(x1, y1), (x1 + math.cos(a) * length, y1 + math.sin(a) * length)],
                              fill=_ATROPOS_DARK, width=max(1, w // 2))
        for x, y, r in nodules:
            draw.ellipse((x - r - 2, y - r - 2, x + r + 2, y + r + 2), fill=_ATROPOS_DARK)


def _atropos_background() -> Image.Image:
    """The quote-independent night, painted and dithered once per process."""
    key = (_atropos_paint_sky, _atropos_paint_rain, _atropos_paint_ruins, _atropos_paint_tendrils)
    cached = _ATROPOS_BACKGROUND.get("frame")
    if cached is not None and cached[0] == key:
        return cached[1]
    size = (800, 480)
    scene = Image.new("RGB", size, SPECTRA6["black"])
    _atropos_paint_sky(scene)
    _atropos_paint_rain(scene)
    _atropos_paint_ruins(scene)
    _atropos_paint_tendrils(scene)
    image = dither_image_to_palette(scene, _ATROPOS_SCENE_PALETTE)
    _ATROPOS_BACKGROUND["frame"] = (key, image)
    return image


def _atropos_glow_hot(image: Image.Image, mask: Image.Image, core, *, radius: int, gamma: float, cap: float,
                      ground=_ATROPOS_COLD_GROUND, yellow_share: float = 0.375) -> None:
    """A tangerine bloom: red with yellow at 3/8, the warning orange of the HUD.

    Scene lights pass ``yellow_share=0.5``: panel red is nearly black, so a
    5/8-red halo reads as shadow rather than light. The phrase keeps 3/8,
    since on pure black the hue is what matters.
    """
    paint_neon_mask(image, mask, core, SPECTRA6["red"], radius=radius, gamma=gamma, cap=cap,
                    ground=ground, tile=BAYER_8x8, glow_minor=SPECTRA6["yellow"], glow_minor_share=yellow_share)


def _atropos_paint_embers(image: Image.Image) -> None:
    """Where the growth is alive: each nodule a yellow core in a tangerine
    bloom; the *Helios* beacon the same, still blinking in the wreck."""
    mask = Image.new("L", image.size, 0)
    md = ImageDraw.Draw(mask)
    for _, _, nodules in _atropos_tendril_paths():
        for x, y, r in nodules:
            md.ellipse((x - r, y - r, x + r, y + r), fill=255)
    bx, by = _ATROPOS_HELIOS_BEACON
    md.ellipse((bx - 2, by - 2, bx + 2, by + 2), fill=255)
    # The Sentient's xenotech seams: thin lines of light along the crest and
    # down the chest, the one thing on the statue that is still awake.
    sx, sy = _ATROPOS_STATUE
    md.line([(sx + 4, sy + 8), (sx + 36, sy - 10)], fill=255, width=1)
    md.line([(sx, sy + 76), (sx, sy + 150)], fill=255, width=1)
    _atropos_glow_hot(image, mask, SPECTRA6["yellow"], radius=6, gamma=1.2, cap=0.8, yellow_share=0.5)
    mask.close()


def _atropos_paint_orbs(image: Image.Image, quote_row: dict) -> None:
    """The volley: glowing projectiles with fading trails, a different pattern
    per quote. Hot orbs are yellow in tangerine, violet ones white in R+B."""
    rng = random.Random(_row_digest(quote_row) ^ _ATROPOS_SEED)
    width, height = image.size
    # The volley stays clear of the translation frame (an orb beside a glyph
    # reads as a dot stuck to the phrase) and of the cipher slab.
    reach = 26                                                   # how far a bloom spills past its mask
    keepouts = (_atropos_quote_keepout(), _ATROPOS_SLAB)         # the text, and the glyphs it translates

    def clear(px, py):
        return not any(kx0 - reach < px < kx1 + reach and ky0 - reach < py < ky1 + reach
                       for kx0, ky0, kx1, ky1 in keepouts)

    for _ in range(6 + rng.randrange(4)):
        r = rng.uniform(4.5, 8.0)
        for _attempt in range(60):
            x, y = rng.uniform(40, width - 40), rng.uniform(52, _ATROPOS_HORIZON + 16)
            a = rng.uniform(0, 2 * math.pi)
            dots = [(x - math.cos(a) * k * r * 1.6, y - math.sin(a) * k * r * 1.6) for k in range(1, 8)]
            if clear(x, y) and all(clear(tx, ty) for tx, ty in dots):
                break
        else:                                                    # pragma: no cover - 60 draws never all collide
            continue
        hot = rng.random() < 0.7
        core = Image.new("L", image.size, 0)
        trail = Image.new("L", image.size, 0)
        ImageDraw.Draw(core).ellipse((x - r, y - r, x + r, y + r), fill=255)
        td = ImageDraw.Draw(trail)
        for k, (tx, ty) in enumerate(dots, start=1):
            tr = r * (1 - k / 8) * 0.9
            td.ellipse((tx - tr, ty - tr, tx + tr, ty + tr), fill=round(255 * (1 - k / 9)))
        if hot:
            _atropos_glow_hot(image, trail, None, radius=5, gamma=1.8, cap=0.55, yellow_share=0.5)
            _atropos_glow_hot(image, core, SPECTRA6["yellow"], radius=8, gamma=1.1, cap=0.85, yellow_share=0.5)
            ir = r * 0.42                                        # white-hot centre
            ImageDraw.Draw(image).ellipse((x - ir, y - ir, x + ir, y + ir), fill=SPECTRA6["white"])
        else:
            for m, c, rad, g, cp in ((trail, None, 5, 1.8, 0.5), (core, SPECTRA6["white"], 8, 1.1, 0.8)):
                paint_neon_mask(image, m, c, SPECTRA6["blue"], radius=rad, gamma=g, cap=cp,
                                ground=_ATROPOS_COLD_GROUND, tile=BAYER_8x8,
                                glow_minor=SPECTRA6["red"], glow_minor_share=0.5)
        core.close()
        trail.close()


def _atropos_quote_keepout() -> tuple[int, int, int, int]:
    """The translation frame, brackets and byline included, that no orb may
    sit inside."""
    x0, y0, x1, _ = _ATROPOS_QUOTE_RECT
    return (x0 - 18, y0 - 22, x1 + 18, _ATROPOS_BYLINE_BASELINE + 12)


def _atropos_glyph(letter: str) -> tuple:
    """The xenoglyph for ``letter``: strokes on a 3x4 lattice and an optional
    dot, built once per letter from a fixed seed so the alphabet is stable."""
    glyph = _ATROPOS_GLYPHS.get(letter)
    if glyph is None:
        rng = random.Random(_ATROPOS_SEED * 31 + ord(letter))
        lattice = [(c, r) for r in range(4) for c in range(3)]
        strokes = []
        start = rng.choice(lattice)
        for _ in range(rng.randint(3, 5)):
            end = rng.choice([p for p in lattice if p != start and (p[0] == start[0] or p[1] == start[1]
                                                                    or abs(p[0] - start[0]) == abs(p[1] - start[1]))])
            strokes.append((start, end))
            start = end if rng.random() < 0.7 else rng.choice(lattice)
        dot = rng.choice(lattice) if rng.random() < 0.45 else None
        glyph = _ATROPOS_GLYPHS[letter] = (tuple(strokes), dot)
    return glyph


def _atropos_cipher_text(quote_row: dict) -> str:
    """The letters the slab carries: the matched phrase, then the quote."""
    text = f"{quote_row.get('matched_text') or ''} {quote_row.get('display_quote') or ''}".lower()
    return "".join(ch if ch.isalpha() and ch.isascii() else " " for ch in text)


def _atropos_paint_cipher(image: Image.Image, quote_row: dict) -> None:
    """The xenoglyph wall: the quote in alien script down the slab, white
    strokes in a faint blue bloom, a space as an empty cell."""
    x0, y0, x1, y1 = _ATROPOS_SLAB
    cell_w, cell_h, pitch = 10, 14, 22
    columns = (x0 + 12, x0 + 38)
    rows = (y1 - y0 - 16) // pitch
    mask = Image.new("L", image.size, 0)
    md = ImageDraw.Draw(mask)
    letters = _atropos_cipher_text(quote_row)
    text = " ".join(letters.split())
    index = 0
    for row in range(rows):
        for cx in columns:
            if index >= len(text):
                break
            ch = text[index]
            index += 1
            if ch == " ":
                continue
            strokes, dot = _atropos_glyph(ch)
            top = y0 + 10 + row * pitch
            for (c0, r0), (c1, r1) in strokes:
                md.line([(cx + c0 * cell_w / 2, top + r0 * cell_h / 3), (cx + c1 * cell_w / 2, top + r1 * cell_h / 3)],
                        fill=255, width=1)
            if dot is not None:
                dx, dy = cx + dot[0] * cell_w / 2, top + dot[1] * cell_h / 3
                md.ellipse((dx - 1, dy - 1, dx + 1, dy + 1), fill=255)
    paint_neon_mask(image, mask, SPECTRA6["white"], SPECTRA6["blue"], radius=2, gamma=1.6, cap=0.4,
                    ground=_ATROPOS_COLD_GROUND, tile=BAYER_8x8)
    mask.close()


def _atropos_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The translation: white Saira over a black halo, the matched phrase
    a yellow core in the HUD's tangerine."""
    prose, hot, _ = wrap_quote_into_masks(
        draw, image.size, quote_row, _ATROPOS_QUOTE_RECT, theme="atropos",
        font_max=30, font_min=12, line_height_mult=1.42,
    )
    _halo_paste(image, ImageChops.lighter(prose, hot), None)
    image.paste(SPECTRA6["white"], (0, 0), prose.point(lambda v: 255 if v > 110 else 0))
    _atropos_glow_hot(image, hot, SPECTRA6["yellow"], radius=3, gamma=1.8, cap=0.5,
                      ground=frozenset({SPECTRA6["black"]}))
    prose.close()
    hot.close()


def _atropos_paint_byline(image: Image.Image, quote_row: dict) -> None:
    """Author and title as the cipher's source line, small capitals in white."""
    x0, _, x1, _ = _ATROPOS_QUOTE_RECT
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "")
    byline = "  ·  ".join(part.upper() for part in (author, title) if part)
    if not byline:
        return
    mask = Image.new("L", image.size, 0)
    md = ImageDraw.Draw(mask)
    candidates = [(SAIRA_VARIABLE, "Medium"), MICHROMA_REGULAR, *META_FONT_BOLD_CANDIDATES]
    font, text = fit_text_to_width(md, byline, candidates, 13, x1 - x0, floor=10, tracking=1)
    w = tracked_width(md, text, font, tracking=1)
    draw_tracked(md, ((x0 + x1 - w) / 2, _ATROPOS_BYLINE_BASELINE - 12), text, font, 255, tracking=1)
    _halo_paste(image, mask, SPECTRA6["white"], halo=3)
    mask.close()


def _atropos_brackets(draw: ImageDraw.ImageDraw, box, length: int, fill) -> None:
    x0, y0, x1, y1 = box
    for cx, sx in ((x0, 1), (x1, -1)):
        for cy, sy in ((y0, 1), (y1, -1)):
            draw.line([(cx, cy + sy * length), (cx, cy), (cx + sx * length, cy)], fill=fill, width=1)


def _atropos_paint_hud(image: Image.Image, draw: ImageDraw.ImageDraw, hour: int, quote_row: dict) -> None:
    """The scout's HUD: the biome title, the cycle counter, the translation
    frame and its label, the integrity bar and adrenaline pips, and the
    uplink that never answers."""
    white, black = SPECTRA6["white"], SPECTRA6["black"]
    digest = _row_digest(quote_row)
    width = image.size[0]

    # Biome title, top-left.
    draw_tracked(draw, (34, 16), "ATROPOS", _atropos_font(14), white, tracking=4)
    draw_tracked(draw, (34, 36), "OVERGROWN RUINS", _atropos_font(10), white, tracking=3)

    # Cycle counter, top-right, with a ring icon: the hour, nothing else.
    font = _atropos_font(15)
    label = f"CYCLE {hour:02d}"
    draw_tracked(draw, (_ATROPOS_CYCLE_RIGHT, 15), label, font, white, tracking=3, anchor_right=True)
    cx = _ATROPOS_CYCLE_RIGHT - tracked_width(draw, label, font, tracking=3) - 18
    draw.ellipse((cx - 8, 15, cx + 8, 31), outline=white, width=1)
    draw.ellipse((cx - 3, 20, cx + 3, 26), fill=white)

    # The translation frame: corner brackets round the quote, a label above.
    x0, y0, x1, y1 = _ATROPOS_QUOTE_RECT
    _atropos_brackets(draw, _atropos_quote_keepout(), 16, white)
    draw_tracked(draw, (x0 - 6, y0 - 19), "XENOGLYPH CIPHER", _atropos_font(10), white, tracking=3)
    draw_tracked(draw, (x1 + 6, y0 - 19), "TRANSLATED", _atropos_font(10), white, tracking=3, anchor_right=True)

    # Integrity and adrenaline, bottom-left: this run's readings.
    bx0, by, bx1 = 34, 452, 262
    draw.rectangle((bx0 - 3, by - 18, bx1 + 3, by + 11), fill=black)
    draw_tracked(draw, (bx0, by - 16), "INTEGRITY", _atropos_font(10), white, tracking=2)
    draw.rectangle((bx0, by, bx1, by + 7), outline=white, width=1)
    fill_to = bx0 + round((bx1 - bx0) * (0.34 + (digest % 61) / 100))
    draw.rectangle((bx0 + 2, by + 2, fill_to, by + 5), fill=white)
    for tx in range(bx0 + 38, bx1, 38):
        draw.line([(tx, by), (tx, by + 7)], fill=black, width=1)
    lit = 1 + digest // 61 % 5
    draw.rectangle((bx1 + 14, by - 18, bx1 + 136, by + 11), fill=black)
    draw_tracked(draw, (bx1 + 18, by - 16), "ADRENALINE", _atropos_font(10), white, tracking=2)
    for k in range(5):
        px, py = bx1 + 24 + k * 16, by + 4
        pts = [(px, py - 5), (px + 5, py), (px, py + 5), (px - 5, py)]
        if k < lit:
            draw.polygon(pts, fill=white)
        else:
            draw.polygon(pts, outline=white)

    # The uplink, bottom-right.
    draw.rectangle((width - 190, by - 18, width - 30, by + 11), fill=black)
    draw_tracked(draw, (width - 34, by - 16), "HELIOS UPLINK", _atropos_font(10), white, tracking=2, anchor_right=True)
    draw_tracked(draw, (width - 34, by - 2), "NO SIGNAL", _atropos_font(10), white, tracking=3, anchor_right=True)


def render_atropos_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Night in the Overgrown Ruins of Atropos (see the section comment above)."""
    hour = _clock_hour12(time_str)
    image = _atropos_background().copy()
    draw = ImageDraw.Draw(image)
    _atropos_paint_embers(image)
    _atropos_paint_orbs(image, quote_row)
    _atropos_paint_cipher(image, quote_row)
    _atropos_paint_quote(image, draw, quote_row)
    _atropos_paint_byline(image, quote_row)
    _atropos_paint_hud(image, draw, hour, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("atropos",), render=render_atropos_frame)
