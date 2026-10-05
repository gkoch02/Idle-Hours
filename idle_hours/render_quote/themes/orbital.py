"""The ``orbital`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import functools
import math
import random

from PIL import Image, ImageChops, ImageDraw

from .._paths import JURA_SEMIBOLD, META_FONT_BOLD_CANDIDATES, META_FONT_CANDIDATES, SHARETECHMONO_REGULAR, SPACEMONO_REGULAR
from ..fonts import load_font
from ..furniture import fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, pixel_access, snap_image_to_palette
from ..primitives import _white_noise, paint_neon_mask, position_noise, wrap_quote_into_masks
from ..spec import FrameSpec
from ..text import fit_text_to_width
from ._culture_common import _culture_clock, _culture_face_ink, _culture_signal, _marain_code, _marain_draw_glyph

# -- orbital: the Arch from the plate --------------------------------------------
# A custom frame, standing on one of the Orbital's plates and looking up. The
# rest of the ring rises from both horizons and meets overhead — the Arch — and
# the page is lit by where the sun is in this plate's day.
#
# **The Arch is the clock.** A point a fraction ``f`` of the way round the ring
# keeps a local time ``f`` of a day ahead of ours, so each pixel of the band is
# lit or dark by its own local time: at noon the Arch is lit at its feet and
# dark overhead, at midnight the zenith burns in daylight over a black sky
# (Banks's own image). The sky follows the hour: blue by day, a warm horizon
# band at dawn and dusk, stars at night.
#
# **The Arch narrows as it rises**, because it recedes: a point ``phi`` round
# the ring is ``2R sin(phi/2)`` away, so its apparent width falls as
# ``1 / sin(phi/2)``.
#
# The quote card is white with dark type by day and black with white type by
# night, so it is legible against either sky.
_ORBITAL_HORIZON = 318
_ORBITAL_ARCH = (400, 474, 300)            # centre x, semi-axis a, semi-axis b
_ORBITAL_ARCH_PHI0 = math.radians(44)      # ring angle where the Arch meets the ground
_ORBITAL_ARCH_T_APEX = 0.03                # band width at the zenith, in radius units
_ORBITAL_CARD = (120, 102, 680, 330)
_ORBITAL_QUOTE_PAD = (26, 34, 26, 40)       # left, top, right, bottom inside the card
_ORBITAL_STAR_SEED = 0x0B17A1
_ORBITAL_STAR_COUNT = 420


def _orbital_sun(clock: float) -> float:
    """Cosine of the sun's angle from the zenith: 1 at noon, -1 at midnight."""
    return math.cos(2.0 * math.pi * (clock - 0.5))


def _orbital_period(clock: float) -> str:
    """``"day"``, ``"twilight"`` or ``"night"`` for the plate's sky."""
    sun = _orbital_sun(clock)
    if sun > 0.2:
        return "day"
    if sun > -0.2:
        return "twilight"
    return "night"


def _orbital_ramp_mask(width: int, height: int, density, *, jitter: bool = True,
                       column=None) -> Image.Image:
    """An ``L`` mask, 255 where an ordered dither of ``density(y)`` is lit.

    Built from image operations (gradient minus tiled ``BAYER_8x8`` threshold)
    rather than a per-pixel loop, since a sky is ~250k pixels. ``jitter``
    perturbs the threshold: an unjittered ramp over a large field lattices.
    """
    grad = Image.new("L", (1, height))
    grad.putdata([max(0, min(255, round(density(y) * 256))) for y in range(height)])
    grad = grad.resize((width, height), Image.Resampling.NEAREST)
    if column is not None:
        # A separable horizontal weight, multiplied in at C speed.
        cols = Image.new("L", (width, 1))
        cols.putdata([max(0, min(255, round(column(x) * 255))) for x in range(width)])
        grad = ImageChops.multiply(grad, cols.resize((width, height), Image.Resampling.NEAREST))
    thresh = _orbital_threshold(width, height, jitter)
    return ImageChops.subtract(grad, thresh).point(lambda v: 255 if v > 0 else 0)


@functools.lru_cache(maxsize=4)
def _orbital_threshold(width: int, height: int, jitter: bool) -> Image.Image:
    """The tiled (optionally jittered) ``BAYER_8x8`` threshold image.

    Quote- and clock-independent, so cached per geometry. Callers must only
    read it.
    """
    tile = Image.new("L", (8, 8))
    tile.putdata([BAYER_8x8[y][x] * 4 + 2 for y in range(8) for x in range(8)])
    thresh = Image.new("L", (width, height))
    for ty in range(0, height, 8):
        for tx in range(0, width, 8):
            thresh.paste(tile, (tx, ty))
    if jitter:
        noise = _white_noise(width, height, _ORBITAL_STAR_SEED).point(lambda v: v // 8)
        thresh = ImageChops.add(thresh, noise, offset=-16)
    return thresh


def _orbital_paint_sky(image: Image.Image, clock: float) -> None:
    """Day blue, twilight glow, or night and stars, above the horizon."""
    width = image.size[0]
    horizon = _ORBITAL_HORIZON
    sky = image.crop((0, 0, width, horizon))
    period = _orbital_period(clock)
    white, blue, black, red, yellow = (SPECTRA6[n] for n in ("white", "blue", "black", "red", "yellow"))
    if period == "day":
        sky.paste(blue, (0, 0, width, horizon))
        # Paler toward the horizon, where the eye looks through more air.
        sky.paste(white, (0, 0), _orbital_ramp_mask(width, horizon, lambda y: 0.18 + 0.5 * (y / horizon) ** 1.6))
    else:
        sky.paste(black, (0, 0, width, horizon))
        rng = random.Random(_ORBITAL_STAR_SEED)
        spx = pixel_access(sky)
        for _ in range(_ORBITAL_STAR_COUNT if period == "night" else _ORBITAL_STAR_COUNT // 4):
            x, y = rng.randrange(width), rng.randrange(horizon)
            roll = rng.random()
            if y < horizon * (0.95 if period == "night" else 0.45):
                spx[x, y] = yellow if roll < 0.07 else blue if roll < 0.2 else white
        # A navy haze toward the horizon (deeper and higher at twilight).
        reach = 0.45 if period == "twilight" else 0.25
        sky.paste(blue, (0, 0), _orbital_ramp_mask(
            width, horizon, lambda y: max(0.0, (y / horizon - (1 - reach)) / reach) * 0.55))
        if period == "twilight":
            # The warm band, strongest over the sun's side of the sky: red
            # rising into a thinner gold edge at the horizon itself.
            east_west = math.sin(2.0 * math.pi * (clock - 0.5))
            sun_x = 400 + 380 * east_west
            near_sun = lambda x: max(0.25, 1.0 - abs(x - sun_x) / 620.0)  # noqa: E731
            sky.paste(red, (0, 0), _orbital_ramp_mask(
                width, horizon, lambda y: max(0.0, (y / horizon - 0.66) / 0.34) ** 1.3 * 0.85,
                column=near_sun))
            sky.paste(yellow, (0, 0), _orbital_ramp_mask(
                width, horizon, lambda y: max(0.0, (y / horizon - 0.84) / 0.16) ** 1.5 * 0.6,
                column=near_sun))
    image.paste(sky, (0, 0))


def _orbital_sun_xy(clock: float) -> tuple[int, int] | None:
    """Where the sun stands, or ``None`` when it is below the horizon.

    The path is wide and steep so a low sun stands clear of the quote card, and
    the noon sun sits below the Arch's apex (an Orbital is tilted so the far side
    does not eclipse noon).
    """
    sun = _orbital_sun(clock)
    if sun <= 0.02:
        return None
    east_west = math.sin(2.0 * math.pi * (clock - 0.5))
    x = 400 + 380 * east_west
    y = _ORBITAL_HORIZON - 255 * sun ** 0.25
    return round(x), round(y)


def _orbital_paint_sun(image: Image.Image, clock: float) -> None:
    pos = _orbital_sun_xy(clock)
    if pos is None:
        return
    x, y = pos
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).ellipse((x - 11, y - 11, x + 11, y + 11), fill=255)
    glow = SPECTRA6["yellow"] if _orbital_period(clock) == "day" else SPECTRA6["red"]
    paint_neon_mask(image, mask, SPECTRA6["white"], glow, radius=6, gamma=1.4, cap=0.7,
                    ground=frozenset({SPECTRA6["blue"], SPECTRA6["white"], SPECTRA6["black"]}))
    mask.close()


def _orbital_arch_phi(alpha: float) -> float:
    """Ring angle seen at elliptical angle ``alpha`` (``pi`` = left foot, 0 = right)."""
    return _ORBITAL_ARCH_PHI0 + (1.0 - alpha / math.pi) * (2.0 * math.pi - 2.0 * _ORBITAL_ARCH_PHI0)


def _orbital_arch_width(phi: float) -> float:
    """Band width in radius units: ``1 / sin(phi/2)`` perspective falloff."""
    return _ORBITAL_ARCH_T_APEX / max(0.05, math.sin(phi / 2.0))


def _orbital_arch_day(clock: float, phi: float) -> float:
    """Sun-angle cosine at the plate ``phi`` round the ring: its local noon is 1."""
    return math.cos(2.0 * math.pi * (clock + phi / (2.0 * math.pi) - 0.5))


def _orbital_paint_arch(image: Image.Image, clock: float) -> None:
    """The far side of the ring, each pixel lit by its own local time.

    Each row walks only the two x-intervals the band can occupy (closed form
    from the ellipse), so the cost is the band's area, not the sky's.
    """
    cx, a, b = _ORBITAL_ARCH
    horizon = _ORBITAL_HORIZON
    px = pixel_access(image)
    width = image.size[0]
    period = _orbital_period(clock)
    black, white, blue, green, yellow = (SPECTRA6[n] for n in ("black", "white", "blue", "green", "yellow"))
    t_max = _orbital_arch_width(_ORBITAL_ARCH_PHI0)
    for y in range(0, horizon):
        q = (horizon - y) / b
        if q >= 1.0:
            continue
        outer = a * math.sqrt(1.0 - q * q)
        inner_sq = (1.0 - t_max) ** 2 - q * q
        inner = a * math.sqrt(inner_sq) if inner_sq > 0 else 0.0
        row = BAYER_8x8[y % 8]
        spans = ((cx - outer, cx - inner), (cx + inner, cx + outer))
        for lo, hi in spans:
            for x in range(max(0, int(lo) - 1), min(width, int(hi) + 2)):
                ux = (x - cx) / a
                rho = math.hypot(ux, q)
                alpha = math.atan2(q, ux)
                phi = _orbital_arch_phi(alpha)
                t = _orbital_arch_width(phi)
                across = (1.0 - rho) / t
                if not 0.0 <= across <= 1.0:
                    continue
                day = _orbital_arch_day(clock, phi)
                rank = row[x % 8]
                # The rim walls, a fixed ~1.5 px at every width, so the Arch keeps
                # its outline even where its surface is in night.
                rim = 1.5 / (t * b)
                if across < rim or across > 1.0 - rim:
                    px[x, y] = white if (day > 0 or period != "night") else blue
                    continue
                if day > 0:
                    ink = _culture_face_ink(rank, x, y, phi * 180.0, across, day)
                    # Seen through our own air by day: the far side washes pale.
                    if period == "day" and ink != white and position_noise(x, y) < 40:
                        ink = white
                    px[x, y] = ink
                elif period == "day":
                    # The far side's night, seen through a lit sky: a band of
                    # navy a shade deeper than the blue around it.
                    px[x, y] = black if rank < 20 else blue
                else:
                    px[x, y] = yellow if position_noise(x, y) < 14 and rank < 40 else black


def _orbital_lights(x: int, y: int, below_crest: float) -> bool:
    """A lit window: rare in open country, gathered into a few settlements that
    sit along the hills' far slopes and thin out toward the viewer."""
    town = math.sin(x * 0.021 + 0.7) + math.sin(x * 0.0063 + 2.9)
    if town > 1.0 and below_crest < 46:
        return position_noise(x, y) < 30 * (1.0 - below_crest / 46)
    return position_noise(x, y) < 1


def _orbital_paint_land(image: Image.Image, clock: float) -> None:
    """The plate itself: a hazy far range and near forested hills.

    By day the hills are forest green shading toward the foreground; at
    twilight and night they are silhouettes, lit only by their settlements —
    which stay dark at twilight, when nobody has needed a lamp yet.
    """
    width, height = image.size
    horizon = _ORBITAL_HORIZON
    period = _orbital_period(clock)
    black, white, blue, green, yellow = (SPECTRA6[n] for n in ("black", "white", "blue", "green", "yellow"))
    px = pixel_access(image)
    for x in range(width):
        far = horizon - 14 - 16 * math.sin(x * 0.011 + 0.8) - 7 * math.sin(x * 0.037 + 2.1)
        near = horizon + 34 + 18 * math.sin(x * 0.0072 + 2.6) + 8 * math.sin(x * 0.029)
        for y in range(int(far), height):
            rank = BAYER_8x8[y % 8][x % 8]
            if y < near:
                # The far range: through haze by day, a navy silhouette by night.
                if period == "day":
                    px[x, y] = blue if rank < 44 else white
                else:
                    px[x, y] = blue if rank < 16 else black
                continue
            depth = (y - near) / max(1.0, height - near)
            if period == "day":
                # Sunlit crests fading to forest shade toward the viewer.
                crest = y - near < 5
                cut = 64 * (0.06 + 0.34 * depth)
                px[x, y] = black if rank < cut else (yellow if crest and rank > 40 else green)
            elif y - near < 1.5:
                # A cold rim on the crest so the silhouette still reads.
                px[x, y] = blue
            elif period == "night" and _orbital_lights(x, y, y - near):
                px[x, y] = yellow
            else:
                px[x, y] = black


def _orbital_paint_card(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict,
                        clock: float) -> None:
    """The quote on a card floating under the Arch, inked for the hour."""
    x0, y0, x1, y1 = _ORBITAL_CARD
    white, black, blue, yellow, green = (SPECTRA6[n] for n in ("white", "black", "blue", "yellow", "green"))
    night = _orbital_period(clock) != "day"
    face, ink, rule = (black, white, white) if night else (white, black, black)
    # Shadow ledge by day (the ``kanagawa`` / ``pride`` card), a blue field
    # bloom by night — a drone's field, not a sheet of paper.
    if night:
        mask = Image.new("L", image.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((x0, y0, x1, y1), radius=12, fill=255)
        paint_neon_mask(image, mask, None, blue, radius=5, gamma=1.3, cap=0.6)
        mask.close()
    else:
        draw.rounded_rectangle((x0 + 4, y0 + 4, x1 + 4, y1 + 4), radius=12, fill=black)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=12, fill=face, outline=rule, width=1)

    sig = _culture_signal(quote_row)
    mono = [SHARETECHMONO_REGULAR, SPACEMONO_REGULAR, *META_FONT_CANDIDATES]
    small = load_font(mono, size=12)
    header = f"{sig['plate'].upper()} PLATE · {sig['orbital'].upper()} ORBITAL"
    draw.text((x0 + 20, y0 + 12), header, font=small, fill=ink)
    # The header's Marain: the plate's name, as its own signage would carry it.
    code_x = x1 - 20
    for ch in reversed(sig["plate"].lower()):
        code = _marain_code(ch)
        if code is None:
            continue
        code_x -= 12
        _marain_draw_glyph(draw, code_x, y0 + 12, code, 4, ink, stroke=1, dot=1)

    pl, pt, pr, pb = _ORBITAL_QUOTE_PAD
    rect = (x0 + pl, y0 + pt, x1 - pr, y1 - pb)
    prose, hot, _ = wrap_quote_into_masks(draw, image.size, quote_row, rect, theme="orbital",
                                          font_max=32, font_min=14, line_height_mult=1.28)
    image.paste(ink, (0, 0), prose.point(lambda v: 255 if v > 128 else 0))
    if night:
        paint_neon_mask(image, hot, yellow, green, radius=3, gamma=1.7, cap=0.55,
                        ground=frozenset({face}), tile=BAYER_8x8)
    else:
        image.paste(blue, (0, 0), hot.point(lambda v: 255 if v > 128 else 0))
    prose.close()
    hot.close()

    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or fallback_title(quote_row) or "").strip()
    credit = " · ".join(p for p in (author, title) if p)
    if credit:
        font, text = fit_text_to_width(draw, credit, [JURA_SEMIBOLD, *META_FONT_BOLD_CANDIDATES],
                                       15, x1 - x0 - 48, floor=11)
        draw.text(((x0 + x1) // 2, y1 - 26), text, font=font, fill=ink, anchor="ma")


def render_orbital_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The Arch from the plate, lit by the hour (see the section comment)."""
    clock = _culture_clock(time_str)
    image = Image.new("RGB", (800, 480), color=SPECTRA6["black"])
    draw = ImageDraw.Draw(image)
    _orbital_paint_sky(image, clock)
    _orbital_paint_sun(image, clock)
    _orbital_paint_arch(image, clock)
    _orbital_paint_land(image, clock)
    _orbital_paint_card(image, draw, quote_row, clock)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("orbital",), render=render_orbital_frame)
