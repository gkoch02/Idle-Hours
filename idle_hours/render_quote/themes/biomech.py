"""The ``biomech`` theme's frame: a pointed arch cut through H. R. Giger's
biomechanical wall onto a Zdzisław Beksiński dusk, both painted and dithered at render time.

Design notes: docs/themes.md § biomech
"""

from __future__ import annotations

import math
import random
from itertools import pairwise

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from .._paths import GRENZE_GOTISCH_VARIABLE, META_FONT_BOLD_CANDIDATES, META_FONT_CANDIDATES, SPECTRAL_MEDIUM_ITALIC
from ..fonts import load_font
from ..furniture import _clock_hour12, draw_truncated_centred_byline
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, dither_image_to_palette, snap_image_to_palette
from ..primitives import (
    _bayer_threshold_field,
    _halo_paste,
    _lerp_stops,
    _smooth_noise,
    paint_neon_mask,
    shade_height_field,
    wrap_quote_into_masks,
)
from ..spec import FrameSpec
from ._shared import _TAROT_ROMAN_NUMERALS

_BIOMECH_ARCH = (126, 674, 96, 12, 452)     # left x, right x, springline y, apex y, sill y
_BIOMECH_QUOTE_RECT = (172, 58, 628, 262)
_BIOMECH_HORIZON = 372
_BIOMECH_SUN = (402, 356, 42)               # centre x, centre y, radius
_BIOMECH_BYLINE_BASELINE = 440
_BIOMECH_PLATE = (306, 457, 494, 477)
_BIOMECH_SEED = 0xB10
_BIOMECH_SCENE_PALETTE = [SPECTRA6["black"], SPECTRA6["red"], SPECTRA6["yellow"], SPECTRA6["white"]]
_BIOMECH_WALL_PALETTE = [SPECTRA6["black"], SPECTRA6["white"]]
# The dusk, as (y, rgb) stops interpolated per row: a near-black zenith the
# quote can sit on, a blood-red middle sky, a molten band at the horizon, and
# a ground that falls back to black toward the sill.
_BIOMECH_SKY_STOPS = (
    (0, (0, 0, 0)), (168, (0, 0, 0)), (236, (52, 3, 2)), (292, (138, 14, 6)),
    (334, (206, 58, 12)), (360, (246, 140, 36)), (_BIOMECH_HORIZON, (255, 196, 92)),
)
_BIOMECH_GROUND_STOPS = ((_BIOMECH_HORIZON, (96, 16, 6)), (404, (34, 4, 2)), (480, (4, 0, 0)))
# The ruined cathedral's spires, as (centre x, half width, top y). The tallest
# stands in front of the sun so it reads against the brightest thing on the page.
_BIOMECH_SPIRES = (
    (344, 3, 328), (356, 5, 306), (368, 3, 320), (381, 6, 292), (402, 9, 268),
    (421, 5, 296), (434, 3, 318), (447, 5, 304), (459, 3, 330),
)
# Crosses on the horizon to the left, as (x, height, lean): stood against the
# brightest band of sky so a thin black stroke still reads.
_BIOMECH_CROSSES = ((172, 30, -3), (206, 24, 2), (236, 19, -2), (262, 15, 3), (284, 12, -1), (302, 9, 1))
_BIOMECH_BACKGROUND: dict = {}


def _biomech_arch_halfwidth(y: float) -> float:
    """Half the opening's width at row ``y``: straight piers below the
    springline, then a curve that closes to a point at the apex."""
    left, right, spring, apex, _ = _BIOMECH_ARCH
    half = (right - left) / 2
    if y >= spring:
        return half
    if y <= apex:
        return 0.0
    t = (spring - y) / (spring - apex)
    return half * (1 - t ** 1.7) ** 0.62


def _biomech_arch_outline(offset: float = 0.0) -> list[tuple[float, float]]:
    """The opening's edge from the left sill up over the apex to the right
    sill, pushed ``offset`` px outward (into the wall)."""
    left, right, spring, apex, sill = _BIOMECH_ARCH
    cx = (left + right) / 2
    ys = [sill - i for i in range(0, int(sill - apex) + 1, 4)] + [apex]
    side: list[tuple[float, float]] = [(cx - _biomech_arch_halfwidth(y) - offset, y) for y in ys]
    side[-1] = (cx, apex - offset)
    return side + [(2 * cx - x, y) for x, y in reversed(side[:-1])]


def _biomech_opening_mask(size) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon([(round(x), round(y)) for x, y in _biomech_arch_outline()], fill=255)
    return mask


def _biomech_haze(colour, amount: float):
    """Black pushed ``amount`` of the way toward ``colour`` — how far a
    silhouette has dissolved into the air in front of it."""
    return tuple(round(c * amount) for c in colour)


def _biomech_paint_sky(image: Image.Image) -> None:
    """The dusk and the ground: per-row gradient, streaked cloud, a half-set sun."""
    width, height = image.size
    column = Image.new("RGB", (1, height))
    for y in range(height):
        stops = _BIOMECH_SKY_STOPS if y <= _BIOMECH_HORIZON else _BIOMECH_GROUND_STOPS
        column.putpixel((0, y), _lerp_stops(stops, y))
    base = column.resize((width, height), Image.Resampling.NEAREST)

    # Cloud: long horizontal streaks, brightening and darkening the middle sky
    # only — the zenith stays black for the quote, the horizon stays molten.
    envelope = Image.new("L", (1, height))
    for y in range(height):
        e = 0.0
        if 170 < y < _BIOMECH_HORIZON:
            e = math.sin(math.pi * (y - 170) / (_BIOMECH_HORIZON - 170)) ** 1.4
        envelope.putpixel((0, y), round(255 * e))
    envelope = envelope.resize((width, height), Image.Resampling.NEAREST)
    streaks = _smooth_noise((width, height), (9, 38), _BIOMECH_SEED)
    light = ImageChops.multiply(streaks.point(lambda v: max(0, v - 132) * 3), envelope)
    dark = ImageChops.multiply(streaks.point(lambda v: max(0, 112 - v) * 3), envelope)
    bright = ImageEnhance.Brightness(base).enhance(1.9)
    image.paste(Image.composite(bright, base, light))
    image.paste(Image.composite(ImageEnhance.Brightness(image).enhance(0.35), image, dark))

    # Sun: a wide glow and a pale disc, half set behind the horizon.
    sx, sy, sr = _BIOMECH_SUN
    glow = Image.new("L", (width, height), 0)
    ImageDraw.Draw(glow).ellipse((sx - sr * 2.6, sy - sr * 2.2, sx + sr * 2.6, sy + sr * 2.2), fill=150)
    sky = Image.new("L", (width, height), 0)
    ImageDraw.Draw(sky).rectangle((0, 0, width, _BIOMECH_HORIZON), fill=255)
    glow = ImageChops.multiply(glow.filter(ImageFilter.GaussianBlur(sr)), sky)
    image.paste(Image.composite(Image.new("RGB", (width, height), (255, 214, 120)), image, glow))
    disc = Image.new("L", (width, height), 0)
    ImageDraw.Draw(disc).ellipse((sx - sr, sy - sr, sx + sr, sy + sr), fill=255)
    image.paste((255, 244, 206), (0, 0), ImageChops.multiply(disc.filter(ImageFilter.GaussianBlur(2)), sky))


def _biomech_paint_landscape(image: Image.Image) -> None:
    """Beksiński's distance: a far ridge, a cathedral of bone spires against
    the sun, a shrouded giant, leaning crosses, then a fog over the horizon."""
    width, height = image.size
    draw = ImageDraw.Draw(image)
    hz = _BIOMECH_HORIZON
    horizon_sky = _lerp_stops(_BIOMECH_SKY_STOPS, 330)
    rng = random.Random(_BIOMECH_SEED)

    # Far ridge: a low ragged line, most dissolved into the air.
    ridge: list[tuple[float, float]] = [(0, hz + 2)]
    for x in range(0, width + 12, 12):
        ridge.append((x, hz - 2 - rng.random() * 9 - (7 if 520 < x < 640 else 0)))
    ridge.append((width, hz + 2))
    draw.polygon([(round(x), round(y)) for x, y in ridge], fill=_biomech_haze(horizon_sky, 0.52))

    # The shrouded giant, right of centre: a hooded figure, half-hazed.
    gx, top = 574, 280
    giant = _biomech_haze(horizon_sky, 0.26)
    draw.ellipse((gx - 6, top, gx + 8, top + 16), fill=giant)             # hood
    shroud = [(gx - 5, top + 10), (gx + 9, top + 9), (gx + 13, top + 26), (gx + 12, top + 60),
              (gx + 19, hz)]
    for i in range(8):
        shroud.append((gx + 19 - i * 5, hz - (3 if i % 2 else 10)))
    shroud += [(gx - 21, hz - 5), (gx - 13, top + 58), (gx - 11, top + 26)]
    draw.polygon([(round(x), round(y)) for x, y in shroud], fill=giant)

    # The cathedral: organ-pipe spires of bone, eroded and thorned, a low
    # nave, lancets lit by the sun behind.
    near = (6, 1, 0)
    draw.polygon([(330, hz + 3), (336, 346), (350, 336), (452, 336), (468, 348), (474, hz + 3)], fill=near)
    for cx, hw, sy in _BIOMECH_SPIRES:
        jag = rng.random() * 4
        draw.polygon([(cx - hw, hz + 3), (cx - hw, sy + hw * 5), (cx - hw * 0.4, sy + hw * 2 + jag),
                      (cx, sy), (cx + hw * 0.5, sy + hw * 2), (cx + hw, sy + hw * 5 + jag),
                      (cx + hw, hz + 3)], fill=near)
        for k in range(4):                                          # thorns
            ty = sy + hw * 5 + 8 + k * 11
            if ty < 336:
                side = -1 if (k + cx) % 2 else 1
                draw.polygon([(cx + side * hw, ty), (cx + side * (hw + 4), ty - 7),
                              (cx + side * hw, ty + 3)], fill=near)
    for wx in (356, 381, 402, 421, 447):                            # lancets, lit from behind
        draw.polygon([(wx - 2, 362), (wx - 2, 350), (wx, 345), (wx + 2, 350), (wx + 2, 362)],
                     fill=(250, 170, 50))

    # Crosses on the horizon, leaning, receding.
    for cx, h, lean in _BIOMECH_CROSSES:
        w = 2 if h > 16 else 1
        draw.line([(cx, hz + 1), (cx + lean, hz - h)], fill=near, width=w)
        ay = hz - h * 0.72
        arm = h * 0.3
        draw.line([(cx + lean * 0.7 - arm, ay), (cx + lean * 0.7 + arm, ay - lean * 0.3)], fill=near, width=w)

    # Fog: a low band across the horizon, streaked, veiling every base.
    fog = Image.new("L", (1, height))
    for y in range(height):
        fog.putpixel((0, y), round(150 * math.exp(-((y - hz + 2) / 9.0) ** 2)))
    fog = ImageChops.multiply(fog.resize((width, height), Image.Resampling.NEAREST),
                              _smooth_noise((width, height), (14, 60), _BIOMECH_SEED + 1))
    fog = fog.point(lambda v: min(255, v * 2))
    image.paste(Image.composite(Image.new("RGB", (width, height), (168, 40, 14)), image, fog))


def _biomech_layer(size, paint, blur: float, peak: int) -> Image.Image:
    """One form of the wall: painted solid, blurred into a rounded profile,
    scaled to its height. ``paint`` receives an ``ImageDraw`` on an ``"L"`` layer."""
    layer = Image.new("L", size, 0)
    paint(ImageDraw.Draw(layer))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    return layer if peak >= 255 else layer.point(lambda v: v * peak // 255)


def _biomech_resample(points, step: float):
    """Points every ``step`` px of arc length along a polyline, with the unit
    normal there — where a corrugated hose's grooves go."""
    out = []
    carry = 0.0
    for (x0, y0), (x1, y1) in pairwise(points):
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg == 0:
            continue
        ux, uy = (x1 - x0) / seg, (y1 - y0) / seg
        d = carry
        while d < seg:
            out.append((x0 + ux * d, y0 + uy * d, -uy, ux))
            d += step
        carry = d - seg
    return out


def _biomech_hose(size, points, width: int, peak: int, pitch: float) -> Image.Image:
    """A corrugated hose: a blurred line for the tube, grooves carved across
    it every ``pitch`` px so the light picks out each rib."""
    pts = [(round(x), round(y)) for x, y in points]
    tube = _biomech_layer(size, lambda d: d.line(pts, fill=255, width=width, joint="curve"),
                          width * 0.26, peak)
    if pitch:
        half = width / 2 + 1
        grooves = _biomech_layer(size, lambda d: [
            d.line([(round(x - nx * half), round(y - ny * half)), (round(x + nx * half), round(y + ny * half))],
                   fill=255, width=2)
            for x, y, nx, ny in _biomech_resample(points, pitch)], 0.8, int(peak * 0.3))
        tube = ImageChops.subtract(tube, grooves)
    return tube


def _biomech_skull(size, cx: int, top: int) -> Image.Image:
    """An elongated skull crowning a pier: cranium dome, carved sockets, a
    nasal cavity and a row of teeth."""
    head = _biomech_layer(size, lambda d: (
        d.ellipse((cx - 32, top, cx + 32, top + 70), fill=255),
        d.ellipse((cx - 24, top + 46, cx + 24, top + 92), fill=255)), 5, 236)
    sockets = _biomech_layer(size, lambda d: (
        d.ellipse((cx - 23, top + 44, cx - 5, top + 62), fill=255),
        d.ellipse((cx + 5, top + 44, cx + 23, top + 62), fill=255),
        d.polygon([(cx - 4, top + 72), (cx + 4, top + 72), (cx, top + 64)], fill=255)), 2.2, 220)
    head = ImageChops.subtract(head, sockets)
    teeth = _biomech_layer(size, lambda d: [
        d.rounded_rectangle((cx - 15 + i * 6, top + 78, cx - 11 + i * 6, top + 89), radius=2, fill=255)
        for i in range(6)], 1.0, 250)
    return ImageChops.lighter(head, teeth)


def _biomech_vertebrae(size, cx: int, y0: int, y1: int, pitch: int) -> Image.Image:
    """A spinal column: stacked vertebral bodies, each with a spinous knob and
    two transverse processes swept downward."""
    def paint_bodies(d):
        for y in range(y0, y1, pitch):
            d.rounded_rectangle((cx - 23, y - 10, cx + 23, y + 10), radius=9, fill=255)

    def paint_processes(d):
        for y in range(y0, y1, pitch):
            for s in (-1, 1):
                d.line([(cx + s * 20, y), (cx + s * 40, y + 7), (cx + s * 46, y + 14)], fill=255, width=6,
                       joint="curve")

    def paint_knobs(d):
        for y in range(y0, y1, pitch):
            d.ellipse((cx - 7, y - 7, cx + 7, y + 7), fill=255)

    bodies = _biomech_layer(size, paint_bodies, 3.6, 214)
    processes = _biomech_layer(size, paint_processes, 2.0, 176)
    knobs = _biomech_layer(size, paint_knobs, 2.0, 250)
    return ImageChops.lighter(ImageChops.lighter(bodies, processes), knobs)


def _biomech_height_field(size, opening: Image.Image) -> Image.Image:
    """The Giger wall as heights: a textured ground plane, then piers of
    vertebrae and hoses crowned by skulls, a ribbed archivolt round the
    opening, tendrils in the spandrels and a hose along the sill."""
    width, height = size
    left, right, _, _, sill = _BIOMECH_ARCH
    wall = ImageOps.invert(opening)
    grain = _smooth_noise(size, (width // 3, height // 3), _BIOMECH_SEED + 2)
    flesh = _smooth_noise(size, (width // 26, height // 26), _BIOMECH_SEED + 3)
    ground = ImageChops.add(grain.point(lambda v: v * 34 // 255), flesh.point(lambda v: 40 + v * 60 // 255))
    field = ImageChops.multiply(ground, wall.filter(ImageFilter.GaussianBlur(2)))

    forms = []
    for cx in (left // 2, (right + width) // 2):
        forms.append(_biomech_skull(size, cx, 8))
        forms.append(_biomech_vertebrae(size, cx, 118, sill - 6, 27))
        for dx, phase in ((-47, 0.0), (47, 1.7)):
            pts: list[tuple[float, float]] = [(cx + dx + 4 * math.sin(y / 23 + phase), y) for y in range(96, sill + 4, 6)]
            forms.append(_biomech_hose(size, pts, 14, 224, 6))
    rim = _biomech_arch_outline(9)
    forms.append(_biomech_hose(size, rim, 15, 244, 13))
    forms.append(_biomech_hose(size, _biomech_arch_outline(31), 12, 214, 6))
    # Spandrel tendrils: hoses sweeping out of the top edge and down the arch.
    for sx, ex, drop in ((140, 262, 46), (178, 330, 22), (660, 538, 46), (622, 470, 22)):
        pts = [(sx + (ex - sx) * t, -8 + drop * t * t + 6 * math.sin(t * 6)) for t in [i / 20 for i in range(21)]]
        forms.append(_biomech_hose(size, pts, 12, 206, 5))
    forms.append(_biomech_hose(size, [(-10, sill + 16), (width + 10, sill + 16)], 20, 230, 6))
    for form in forms:
        field = ImageChops.lighter(field, form)
    # Nothing of the wall stands inside the opening, but the rim may overhang it.
    return ImageChops.multiply(field, ImageChops.lighter(wall, _biomech_rim_overhang(size)))


def _biomech_rim_overhang(size) -> Image.Image:
    """The archivolt's inner lip: a band just inside the opening where the
    rim is allowed to overhang the view."""
    band = Image.new("L", size, 0)
    ImageDraw.Draw(band).line([(round(x), round(y)) for x, y in _biomech_arch_outline(9)],
                              fill=255, width=26, joint="curve")
    return band


def _biomech_paint_wall(image: Image.Image, opening: Image.Image) -> None:
    """Shade the height field, dither it to K+W, stipple in the red rim light
    from the portal, and lay it over the scene outside the opening."""
    size = image.size
    width = size[0]
    field = _biomech_height_field(size, opening)
    tone = shade_height_field(field, relief=0.03, ambient=0.06, diffuse=0.9, specular=0.85, shininess=22)
    # Recesses fall to black: the ground plane sits low and dark, only the
    # forms stand up into the light.
    depth = field.point(lambda v: round(255 * min(1.0, max(0.0, v - 28) / 172) ** 1.25))
    cavity = ImageChops.subtract(field.filter(ImageFilter.GaussianBlur(5)), field)
    tone = ImageChops.multiply(tone, depth)
    tone = ImageChops.multiply(tone, cavity.point(lambda v: 255 - min(255, v * 5)))
    wall = dither_image_to_palette(tone.convert("RGB"), _BIOMECH_WALL_PALETTE)

    # Rim light from the fire: each pier lit from the portal side, low.
    rim_l = shade_height_field(field, light=(0.9, 0.25, 0.25), relief=0.03,
                               ambient=0.0, diffuse=1.0, specular=0.0, shininess=1)
    rim_r = shade_height_field(field, light=(-0.9, 0.25, 0.25), relief=0.03,
                               ambient=0.0, diffuse=1.0, specular=0.0, shininess=1)
    side = Image.new("L", size, 0)
    ImageDraw.Draw(side).rectangle((0, 0, width // 2, size[1]), fill=255)
    rim = Image.composite(rim_l, rim_r, side)
    near_portal = opening.filter(ImageFilter.GaussianBlur(28)).point(lambda v: min(255, v * 3))
    rim = ImageChops.multiply(rim.point(lambda v: max(0, v - 132) * 2), depth)
    rim = ImageChops.multiply(rim, near_portal)
    red = ImageChops.subtract(rim, _bayer_threshold_field(size)).point(lambda v: 255 if v else 0)
    wall.paste(SPECTRA6["red"], (0, 0), red)

    solid = ImageChops.lighter(ImageOps.invert(opening), field.point(lambda v: 255 if v > 150 else 0))
    image.paste(wall, (0, 0), solid)


def _biomech_background() -> Image.Image:
    """The quote-independent frame: dusk + wall, painted and dithered once.

    Keyed on the painter functions, looked up at call time, so a test that
    patches a painter gets a fresh frame rather than a stale cache (a plain
    "built yet?" flag would let the decoration fences measure the cache).
    """
    key = (_biomech_paint_sky, _biomech_paint_landscape, _biomech_paint_wall)
    cached = _BIOMECH_BACKGROUND.get("frame")
    if cached is not None and cached[0] == key:
        return cached[1]
    size = (800, 480)
    scene = Image.new("RGB", size, SPECTRA6["black"])
    _biomech_paint_sky(scene)
    _biomech_paint_landscape(scene)
    image = dither_image_to_palette(scene, _BIOMECH_SCENE_PALETTE)
    _biomech_paint_wall(image, _biomech_opening_mask(size))
    _BIOMECH_BACKGROUND["frame"] = (key, image)
    return image


def _biomech_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """Bone-white prose over a black halo; the matched phrase an ember."""
    prose, hot, _ = wrap_quote_into_masks(
        draw, image.size, quote_row, _BIOMECH_QUOTE_RECT, theme="biomech",
        font_max=42, font_min=14, line_height_mult=1.3,
    )
    _halo_paste(image, ImageChops.lighter(prose, hot), None)
    image.paste(SPECTRA6["white"], (0, 0), prose.point(lambda v: 255 if v > 110 else 0))
    paint_neon_mask(image, hot, SPECTRA6["yellow"], SPECTRA6["red"],
                    radius=3, gamma=1.5, cap=0.62,
                    ground=frozenset({SPECTRA6["black"]}), tile=BAYER_8x8)
    prose.close()
    hot.close()


def _biomech_paint_byline(image: Image.Image, quote_row: dict) -> None:
    """Author and title, small and bone-white, over the dark plain."""
    left, right, *_ = _BIOMECH_ARCH
    mask = Image.new("L", image.size, 0)
    font = load_font([SPECTRAL_MEDIUM_ITALIC, *META_FONT_CANDIDATES], size=15)
    draw_truncated_centred_byline(ImageDraw.Draw(mask), quote_row, centre=(left + right) // 2,
                                  baseline=_BIOMECH_BYLINE_BASELINE, max_width=right - left - 60,
                                  font=font, fill=255)
    _halo_paste(image, mask, SPECTRA6["white"])
    mask.close()


def _biomech_paint_plate(draw: ImageDraw.ImageDraw, hour: int) -> None:
    """The sill cartouche: the work's title, the hour its Roman number."""
    x0, y0, x1, y1 = _BIOMECH_PLATE
    # The numeral is yellow, not red: red on black is the lowest-contrast pair
    # the six inks offer.
    white, yellow, black = SPECTRA6["white"], SPECTRA6["yellow"], SPECTRA6["black"]
    draw.rounded_rectangle((x0, y0, x1, y1), radius=6, fill=black, outline=white, width=1)
    font = load_font([(GRENZE_GOTISCH_VARIABLE, "SemiBold"), *META_FONT_BOLD_CANDIDATES], size=15)
    title, numeral = "Biomechanoid · ", _TAROT_ROMAN_NUMERALS[hour]
    total = draw.textlength(title + numeral, font=font)
    x = (x0 + x1 - total) / 2
    base = y1 - 6
    draw.text((x, base), title, font=font, fill=white, anchor="ls")
    draw.text((x + draw.textlength(title, font=font), base), numeral, font=font, fill=yellow, anchor="ls")


def render_biomech_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Giger's wall round a Beksiński dusk (see the module section comment above)."""
    hour = _clock_hour12(time_str)
    image = _biomech_background().copy()
    draw = ImageDraw.Draw(image)
    _biomech_paint_quote(image, draw, quote_row)
    _biomech_paint_byline(image, quote_row)
    _biomech_paint_plate(draw, hour)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("biomech",), render=render_biomech_frame)
