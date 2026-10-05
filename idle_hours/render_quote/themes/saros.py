"""The ``saros`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageChops, ImageDraw

from .._paths import (
    EXO2_ITALIC_VARIABLE,
    META_FONT_BOLD_CANDIDATES,
    META_FONT_CANDIDATES,
    MICHROMA_REGULAR,
    ORBITRON_VARIABLE,
    SAIRA_ITALIC_VARIABLE,
)
from ..fonts import load_font
from ..furniture import _clock_hour12, _row_digest, fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, dither_image_to_palette, snap_image_to_palette
from ..primitives import _bayer_threshold_field, _halo_paste, paint_neon_mask, wrap_quote_into_masks
from ..spec import FrameSpec
from ..text import draw_tracked

# ---------------------------------------------------------------------------
# saros — Housemarque's *Saros* (2026): the eclipse over Carcosa
# ---------------------------------------------------------------------------
# The colony of Carcosa under the eclipse that never ends: a black sun over a
# dead colony, spores drifting through a red-and-black sky, the quote in the
# one dark stretch of sky.
#
# **The corona is painted in continuous tone and dithered, not stippled**: a
# chromospheric rim decaying over a few pixels, a mid corona over half a
# radius, an outer haze over one and a half, and *streamers* (angular Gaussian
# lobes brightening the mid and outer terms). The profile is sampled every
# ``_SAROS_SKY_STEP`` px (a glow has no finer detail) and bicubic-upsampled;
# the photosphere and moon are then painted sharp at full resolution, because
# the exposed sliver is the one hard edge in the sky. The field is
# Floyd-Steinberg-dithered to K/R/Y/W plus blue (``_SAROS_SKY_PALETTE``). Blue
# is only for the horizon haze away from the sun; its channel is zero
# elsewhere so error diffusion cannot scatter blue into the fire. No green.
#
# **The time is the eclipse's phase.** At twelve the moon is centred and the
# eclipse total. At other hours the moon is offset ``_SAROS_HOUR_OFFSET`` radii
# *away* from the hour's clock-face position, so the diamond ring sits where
# the hour hand would point (the wordmark's O carries the same bead). Hour
# only: every minute of an hour renders byte-identically. The status line's
# occlusion figure comes from the same geometry.
#
# **The ground is silhouette plus rim light.** Spires, towers and a bone arch
# are one black mask; the rim is the shape minus itself shifted two pixels
# away from the sun, weighted by the sky's falloff and stippled yellow where
# strong, red where weak. Everything lit on the frame is lit by the sun. The
# sky is quote-independent and cached per hour (``_SAROS_SKY_CACHE``, keyed on
# the painter so the decoration fence measures a painter, not a cache).
#
# **The quote** is Saira (ragged-left, a transmission rather than a verse)
# pasted white over a black halo grown from its own mask, so no dithered
# corona speck lands between strokes; the matched phrase is a yellow core in a
# tangerine split-band bloom, ``ground`` pinned to black. Spore motes are
# seeded from ``_row_digest``.
#
# Composed at 800x480 and NEAREST-downsampled (the ``metro`` convention).
# ---------------------------------------------------------------------------
_SAROS_SUN = (556, 186)                   # the sun's centre
_SAROS_RADIUS = 108                       # the photosphere's radius, px
_SAROS_MOON_SCALE = 1.03                  # the moon is a shade larger: totality is total
_SAROS_HOUR_OFFSET = 0.10                 # moon offset in sun radii at every hour but twelve
_SAROS_SKY_STEP = 4                       # the corona is sampled every N px, then upsampled
_SAROS_SKY_REACH = 3.6                    # beyond this many radii the sky is black
_SAROS_HORIZON = 390
_SAROS_QUOTE_RECT = (48, 104, 376, 348)
_SAROS_SEED = 0x5A205
_SAROS_SKY_PALETTE = [SPECTRA6["black"], SPECTRA6["red"], SPECTRA6["yellow"], SPECTRA6["white"],
                      SPECTRA6["blue"]]
# Coronal streamers as (angle in degrees — screen axes, 0 = right, 90 = down —
# half-width in degrees, reach in radii, weight). Asymmetric on purpose: a
# corona at solar minimum is a few long equatorial plumes and short polar
# brushes, not a halo.
_SAROS_STREAMERS = (
    (-74, 6, 3.1, 1.00), (-31, 9, 2.5, 0.80), (16, 5, 3.4, 1.10), (58, 8, 2.2, 0.70),
    (121, 7, 2.9, 0.90), (165, 10, 2.0, 0.60), (-133, 8, 2.6, 0.85), (-108, 4, 1.8, 0.50),
)
# Distant spires on the left ridge as (x, half width, height, lean): the
# colony's alien skyline, receding toward the arch.
_SAROS_SPIRES = (
    (46, 4, 74, 3), (68, 3, 52, -2), (104, 6, 96, 2), (131, 3, 60, -3), (166, 5, 118, 1),
    (191, 3, 70, 3), (228, 7, 142, -2), (258, 4, 88, 2), (296, 3, 58, -1), (322, 5, 104, 2),
)
_SAROS_SKY_CACHE: dict = {}


def _saros_hour_vector(hour: int) -> tuple[float, float]:
    """Unit vector from the sun's centre toward the hour's place on a clock
    face, in screen coordinates (12 straight up, 3 to the right)."""
    angle = math.radians(hour * 30.0)
    return math.sin(angle), -math.cos(angle)


def _saros_moon_centre(hour: int) -> tuple[float, float]:
    """The moon sits opposite the hour, so the exposed sliver is on the hour."""
    cx, cy = _SAROS_SUN
    if hour == 12:
        return float(cx), float(cy)
    ux, uy = _saros_hour_vector(hour)
    return cx - ux * _SAROS_HOUR_OFFSET * _SAROS_RADIUS, cy - uy * _SAROS_HOUR_OFFSET * _SAROS_RADIUS


def _saros_bead(hour: int) -> tuple[float, float]:
    """Where the diamond ring sits: on the photosphere's limb, at the hour."""
    cx, cy = _SAROS_SUN
    ux, uy = _saros_hour_vector(hour)
    return cx + ux * _SAROS_RADIUS, cy + uy * _SAROS_RADIUS


def _saros_occlusion(hour: int) -> int:
    """Percentage of the photosphere the moon covers, for the status line.

    Two discs' overlap by the lens formula; 100 at twelve, where the slightly
    larger moon covers all of it.
    """
    if hour == 12:
        return 100
    r = float(_SAROS_RADIUS)
    rm = r * _SAROS_MOON_SCALE
    d = _SAROS_HOUR_OFFSET * r
    a = r * r * math.acos((d * d + r * r - rm * rm) / (2 * d * r))
    b = rm * rm * math.acos((d * d + rm * rm - r * r) / (2 * d * rm))
    c = 0.5 * math.sqrt((-d + r + rm) * (d + r - rm) * (d - r + rm) * (d + r + rm))
    return int(round(100 * (a + b - c) / (math.pi * r * r)))


def _saros_streamer_gain(theta_deg: float, d: float) -> float:
    """How much the streamers brighten the corona at polar coordinate
    ``(theta, d)``: a sum of angular Gaussian lobes, each fading past its reach."""
    gain = 0.0
    for angle, sigma, reach, weight in _SAROS_STREAMERS:
        da = ((theta_deg - angle + 180.0) % 360.0) - 180.0
        gain += weight * math.exp(-(da * da) / (2.0 * sigma * sigma)) * math.exp(-max(0.0, d - reach) / 0.35)
    return min(1.3, gain)


def _saros_corona_field(size) -> tuple[Image.Image, Image.Image]:
    """The continuous-tone sky and its lighting falloff, both at full size.

    Returns ``(sky, falloff)``: ``sky`` is RGB, black beyond the corona's
    reach; ``falloff`` is an ``"L"`` map of how strongly the sun lights a
    point — what the ground's rim light is weighted by.
    """
    width, height = size
    step = _SAROS_SKY_STEP
    cols, rows = -(-width // step), -(-height // step)
    cx, cy = _SAROS_SUN
    radius = float(_SAROS_RADIUS)
    pixels = []
    light = []
    for j in range(rows):
        y = j * step + step / 2 - cy
        for i in range(cols):
            x = i * step + step / 2 - cx
            d = math.hypot(x, y) / radius
            # The sunset that rings the horizon under a total eclipse: a red
            # band fading up from the ground, strongest under the sun.
            dusk = _saros_dusk(i * step, j * step)
            r, g, b = int(150 * dusk), int(36 * dusk), _saros_haze(i * step, j * step)
            lit = 0.0
            if d < _SAROS_SKY_REACH:
                e = max(0.0, d - 1.0)
                gain = _saros_streamer_gain(math.degrees(math.atan2(y, x)), d)
                rim = math.exp(-e / 0.06)
                mid = math.exp(-e / 0.36) * (0.35 + 0.65 * gain)
                outer = math.exp(-e / 1.1) * 0.22 * (0.3 + 0.7 * gain)
                # No blue in the fire, not even on the white-hot rim: error
                # diffusion would pay it out as blue specks in the corona.
                r += int(255 * rim + 255 * mid + 150 * outer)
                g += int(210 * rim + 112 * mid + 18 * outer)
                lit = 0.55 * rim + 0.6 * mid + 0.9 * outer
            pixels.append((min(255, r), min(255, g), min(255, b)))
            light.append(min(255, int(255 * lit)))
    sky = Image.new("RGB", (cols, rows))
    sky.putdata(pixels)
    falloff = Image.new("L", (cols, rows))
    falloff.putdata(light)
    full = (cols * step, rows * step)
    sky = sky.resize(full, Image.Resampling.BICUBIC).crop((0, 0, width, height))
    falloff = falloff.resize(full, Image.Resampling.BICUBIC).crop((0, 0, width, height))
    return sky, falloff


def _saros_dusk(x: float, y: float) -> float:
    """The horizon glow, 0..1: an exponential band up from the ground line,
    strongest beneath the sun and never more than a third as bright at the
    far edges — enough to cut every silhouette out of the sky."""
    if y > _SAROS_HORIZON + 8:
        return 0.0
    band = math.exp(-max(0.0, _SAROS_HORIZON - y) / 58.0)
    lateral = 0.3 + 0.7 * math.exp(-abs(x - _SAROS_SUN[0]) / 360.0)
    return band * lateral


def _saros_haze(x: float, y: float) -> int:
    """The cold blue haze on the horizon, left of the sun, as a blue channel
    value 0..24: a Gaussian band about the horizon fading out to the right."""
    if x > 340 or y > _SAROS_HORIZON + 6:
        return 0
    band = math.exp(-((y - _SAROS_HORIZON) / 44.0) ** 2)
    lateral = max(0.0, 1.0 - x / 340.0) ** 0.8
    return int(24 * band * lateral)


def _saros_paint_sky(image: Image.Image, hour: int) -> Image.Image:
    """Paint the dithered eclipse sky onto ``image`` and return the falloff map."""
    size = image.size
    sky, falloff = _saros_corona_field(size)
    draw = ImageDraw.Draw(sky)
    cx, cy = _SAROS_SUN
    r = _SAROS_RADIUS
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 248, 222))
    mx, my = _saros_moon_centre(hour)
    rm = r * _SAROS_MOON_SCALE
    draw.ellipse((mx - rm, my - rm, mx + rm, my + rm), fill=(0, 0, 0))
    image.paste(dither_image_to_palette(sky, _SAROS_SKY_PALETTE))
    sky.close()
    return falloff


def _saros_sky(hour: int) -> tuple[Image.Image, Image.Image]:
    """The quote-independent sky for ``hour``, dithered once per process.

    Keyed on the painter so a test that neuters ``_saros_paint_sky`` is not
    handed a sky painted before the patch (the ``biomech`` cache rule).
    """
    key = (hour, _saros_paint_sky, _saros_corona_field)
    cached = _SAROS_SKY_CACHE.get(hour)
    if cached is not None and cached[0] == key:
        return cached[1], cached[2]
    image = Image.new("RGB", (800, 480), SPECTRA6["black"])
    falloff = _saros_paint_sky(image, hour)
    if falloff is None:
        falloff = Image.new("L", image.size, 0)
    _SAROS_SKY_CACHE[hour] = (key, image, falloff)
    return image, falloff


def _saros_paint_bead(image: Image.Image, hour: int) -> None:
    """The diamond ring: a white bead with a yellow bloom on the exposed
    limb, and a horizontal lens spike. Nothing at totality."""
    if hour == 12:
        return
    bx, by = _saros_bead(hour)
    bead = Image.new("L", image.size, 0)
    ImageDraw.Draw(bead).ellipse((bx - 5, by - 5, bx + 5, by + 5), fill=255)
    paint_neon_mask(image, bead, SPECTRA6["white"], SPECTRA6["yellow"],
                    radius=9, gamma=1.5, cap=0.7, tile=BAYER_8x8)
    spike = Image.new("L", image.size, 0)
    ImageDraw.Draw(spike).line([(bx - 54, by), (bx + 54, by)], fill=255, width=1)
    paint_neon_mask(image, spike, None, SPECTRA6["white"], radius=3, gamma=1.8, cap=0.5,
                    ground=frozenset({SPECTRA6["black"], SPECTRA6["red"]}), tile=BAYER_8x8)
    bead.close()
    spike.close()


def _saros_ground_y(x: float) -> float:
    """The horizon line: a gentle swell, lower toward the right."""
    return _SAROS_HORIZON + 5 * math.sin(x / 97.0) + 3 * math.sin(x / 41.0 + 1.0) + x * 0.012


def _saros_silhouette(size) -> Image.Image:
    """Everything that stands black against the sky, in one ``"L"`` mask."""
    width, height = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    # The ground.
    line = [(x, _saros_ground_y(x)) for x in range(0, width + 8, 8)]
    draw.polygon([(0, height), *line, (width, height)], fill=255)
    # The spires of the left ridge.
    for x, half, tall, lean in _SAROS_SPIRES:
        base = _saros_ground_y(x) + 2
        draw.polygon([(x - half, base), (x + lean, base - tall), (x + half, base)], fill=255)
    # A bone arch over the middle distance, thick at the feet, thin at the crown.
    for k in range(40):
        t0, t1 = k / 40, (k + 1) / 40
        pts = []
        for t in (t0, t1):
            x = 300 + (452 - 300) * t
            y = _saros_ground_y(x) + 2 - 128 * math.sin(math.pi * t) ** 0.9
            pts.append((x, y))
        w = max(5, int(14 * (1 - math.sin(math.pi * (t0 + t1) / 2)) + 5))
        draw.line(pts, fill=255, width=w)
    # Colony towers to the right: broken blocks with a mast.
    for x0, x1, top in ((664, 700, 318), (708, 722, 346), (742, 790, 304)):
        base = _saros_ground_y((x0 + x1) / 2) + 2
        draw.polygon([(x0, base), (x0, top + 6), (x0 + 8, top), ((x0 + x1) // 2, top + 9),
                      (x1 - 6, top + 2), (x1, top + 10), (x1, base)], fill=255)
    draw.line([(765, 304), (765, 236)], fill=255, width=2)
    draw.line([(758, 250), (772, 250)], fill=255, width=1)
    return mask


def _saros_paint_ground(image: Image.Image, falloff: Image.Image) -> None:
    """Lay the silhouettes over the sky, then light their sun-facing edges."""
    size = image.size
    shape = _saros_silhouette(size)
    image.paste(SPECTRA6["black"], (0, 0), shape)
    # The rim: the shape minus itself shifted away from the sun, so only the
    # edge that faces the light survives. Left of the sun the light comes
    # from the upper right, right of it from the upper left.
    from_right = ImageChops.subtract(shape, ImageChops.offset(shape, -2, 2))
    from_left = ImageChops.subtract(shape, ImageChops.offset(shape, 2, 2))
    half = Image.new("L", size, 0)
    ImageDraw.Draw(half).rectangle((0, 0, _SAROS_SUN[0], size[1]), fill=255)
    rim = Image.composite(from_right, from_left, half)
    rim = ImageChops.multiply(rim, falloff.point(lambda v: min(255, int(v * 1.7))))
    bayer = _bayer_threshold_field(size)
    strong = ImageChops.subtract(rim, bayer.point(lambda v: min(255, v + 120))).point(lambda v: 255 if v else 0)
    weak = ImageChops.subtract(rim.point(lambda v: min(255, int(v * 1.5))), bayer).point(lambda v: 255 if v else 0)
    image.paste(SPECTRA6["red"], (0, 0), weak)
    image.paste(SPECTRA6["yellow"], (0, 0), strong)
    for layer in (shape, from_right, from_left, half, rim, bayer, strong, weak):
        layer.close()


def _saros_paint_motes(image: Image.Image, quote_row: dict) -> None:
    """Spores drifting up through the sky, seeded from the quote."""
    rng = random.Random(_row_digest(quote_row) ^ _SAROS_SEED)
    mx, my = _SAROS_SUN
    keep = (_SAROS_RADIUS * _SAROS_MOON_SCALE + 6) ** 2
    motes = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(motes)
    for _ in range(72):
        x = rng.uniform(8, 792)
        y = rng.uniform(40, _SAROS_HORIZON - 4) if rng.random() < 0.6 else rng.uniform(220, _SAROS_HORIZON - 4)
        if (x - mx) ** 2 + (y - my) ** 2 < keep:
            continue
        size = 1 if rng.random() < 0.7 else 2
        draw.ellipse((x - size, y - size, x + size, y + size), fill=255)
    paint_neon_mask(image, motes, SPECTRA6["white"], SPECTRA6["yellow"], radius=2, gamma=1.4, cap=0.5,
                    ground=frozenset({SPECTRA6["black"]}))
    motes.close()


def _saros_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> int:
    """White Saira prose over a black halo; the matched phrase an ember.
    Returns the block's bottom y."""
    prose, hot, bottom = wrap_quote_into_masks(
        draw, image.size, quote_row, _SAROS_QUOTE_RECT, theme="saros",
        font_max=34, font_min=14, line_height_mult=1.34, align="left",
    )
    _halo_paste(image, ImageChops.lighter(prose, hot), None, halo=7)
    image.paste(SPECTRA6["white"], (0, 0), prose.point(lambda v: 255 if v > 110 else 0))
    paint_neon_mask(image, hot, SPECTRA6["yellow"], SPECTRA6["red"],
                    radius=4, gamma=1.5, cap=0.6, ground=frozenset({SPECTRA6["black"]}),
                    tile=BAYER_8x8, glow_minor=SPECTRA6["yellow"], glow_minor_share=0.375)
    prose.close()
    hot.close()
    return bottom


def _saros_paint_byline(image: Image.Image, quote_row: dict, top: int) -> None:
    """Author and title, flush left under the quote, ellipsised to the column."""
    x0, _, x1, _ = _SAROS_QUOTE_RECT
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or fallback_title(quote_row) or "").strip()
    text = " — ".join(p for p in (author, title) if p)
    if not text:
        return
    font = load_font([(SAIRA_ITALIC_VARIABLE, "Italic"), (EXO2_ITALIC_VARIABLE, "Italic"), *META_FONT_CANDIDATES], 15)
    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    while draw.textlength(text, font=font) > x1 - x0 and len(text) > 8:
        text = text[:-2].rstrip(" ,.;:") + "…"
    draw.text((x0, min(_SAROS_HORIZON - 16, top + 24)), text, font=font, fill=255, anchor="ls")
    _halo_paste(image, mask, SPECTRA6["white"], halo=5)
    mask.close()


def _saros_paint_chrome(image: Image.Image, draw: ImageDraw.ImageDraw, hour: int) -> None:
    """The wordmark, with the O as a small eclipse carrying the hour's bead,
    the colony line beneath it and the eclipse status at the right."""
    white, yellow, black = SPECTRA6["white"], SPECTRA6["yellow"], SPECTRA6["black"]
    x0 = _SAROS_QUOTE_RECT[0]
    # Orbitron for the wordmark — the nearest open face to Arame, the game's
    # main display face; Michroma, the Korataki stand-in, keeps the small chrome.
    wordmark = load_font([(ORBITRON_VARIABLE, "Bold"), MICHROMA_REGULAR, *META_FONT_BOLD_CANDIDATES], 22)
    tracking = 6
    y = 30
    x = draw_tracked(draw, (x0, y), "SAR", wordmark, white, tracking=tracking) + x0
    cap = draw.textbbox((0, 0), "S", font=wordmark)
    cap_h = cap[3] - cap[1]
    r = cap_h / 2 + 1
    # The O sits one tracking step after the R and one before the S, like a
    # glyph in the run; ``draw_tracked`` returns the run's width *without* a
    # trailing step, so the step is added here.
    cx, cy = x + tracking + r + 1, y + cap[1] + cap_h / 2
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=black, outline=white, width=2)
    if hour != 12:
        ux, uy = _saros_hour_vector(hour)
        bx, by = cx + ux * (r - 1), cy + uy * (r - 1)
        draw.ellipse((bx - 2, by - 2, bx + 2, by + 2), fill=yellow)
    x = cx + r + 1 + tracking
    draw_tracked(draw, (x, y), "S", wordmark, white, tracking=tracking)
    small = load_font([MICHROMA_REGULAR, *META_FONT_CANDIDATES], 10)
    draw_tracked(draw, (x0, y + 34), "CARCOSA COLONY", small, white, tracking=3)
    status = "TOTALITY" if hour == 12 else "DIAMOND RING"
    occlusion = f"OCCLUSION {_saros_occlusion(hour)}%"
    draw_tracked(draw, (748, 30), status, small, white, tracking=3, anchor_right=True)
    draw_tracked(draw, (748, 47), occlusion, small, white, tracking=3, anchor_right=True)
    draw.ellipse((756, 31, 766, 41), fill=yellow if hour != 12 else black, outline=yellow, width=2)
    del image


def render_saros_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The eclipse over Carcosa (see the section comment above)."""
    hour = _clock_hour12(time_str)
    sky, falloff = _saros_sky(hour)
    image = sky.copy()
    _saros_paint_bead(image, hour)
    _saros_paint_ground(image, falloff)
    _saros_paint_motes(image, quote_row)
    draw = ImageDraw.Draw(image)
    _saros_paint_chrome(image, draw, hour)
    bottom = _saros_paint_quote(image, draw, quote_row)
    _saros_paint_byline(image, quote_row, bottom)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("saros",), render=render_saros_frame)
