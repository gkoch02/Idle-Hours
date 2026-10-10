"""The ``hippochomp`` theme's border painter and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from .._paths import BRICOLAGE_VARIABLE, QUOTE_FONT_BOLD_CANDIDATES
from ..fonts import load_font
from ..furniture import _clock_hour12
from ..palette import SPECTRA6, BAYER_8x8, rgb_pixel_access
from ..spec import BorderSpec

# ---------------------------------------------------------------------------
# hippochomp — the *HippoChomp* toddler toy's field, with the quote on the
# marketing page's white card. Every size below is at the 800x480 panel and
# scales with the canvas. Design notes: docs/themes.md § hippochomp.

_HIPPOCHOMP_MARGIN = 28
_HIPPOCHOMP_CARD_RADIUS = 24
# The card's flat, unblurred drop: the page's ``0 8px 0`` shadow.
_HIPPOCHOMP_SHADOW_DROP = 8
# The horizon, as a fraction of the height (the app's sky is the top 38%).
_HIPPOCHOMP_HORIZON = 0.38
_HIPPOCHOMP_HORIZON_BAND = 6
# The hippo's scale against the app's point geometry, and the bounds the
# room under the quote may push it to.
_HIPPOCHOMP_HIPPO_SCALE = 0.5
_HIPPOCHOMP_HIPPO_SCALE_MIN = 0.36
_HIPPOCHOMP_HIPPO_SCALE_MAX = 0.56
# The hippo's height in app points, shadow foot to ear top.
_HIPPOCHOMP_HIPPO_POINTS = 125
# Where feet and fruit stand, measured up from the foot.
_HIPPOCHOMP_GROUND_RISE = 9
_HIPPOCHOMP_FRUIT_PITCH = 31
_HIPPOCHOMP_FRUIT_MIN_SCALE = 0.3
# ``render`` pads the body by this much below the attribution, so the text
# ends this far above the card's foot.
_HIPPOCHOMP_PAD_BOTTOM = 24
# Off-palette sentinels for the hippo's synthesised hide tones.
_HIPPOCHOMP_SENTINEL_HIDE = (7, 7, 7)
_HIPPOCHOMP_SENTINEL_HIDE_DARK = (8, 8, 8)
_HIPPOCHOMP_SENTINEL_SNOUT = (9, 9, 9)
_HIPPOCHOMP_SENTINEL_PINK = (10, 10, 10)
_HIPPOCHOMP_SENTINEL_ORANGE = (11, 11, 11)
_HIPPOCHOMP_SENTINEL_LIME = (12, 12, 12)
# Each sentinel's bands on one 8x8 Bayer rank: ``(ink, upper_rank)`` pairs,
# read in order, the last ink taking the rest. Hide is the app's #948CB3
# lavender as B 2/8 + R 1/8 + W 5/8; the far legs carry one more eighth of
# blue; the snout and belly are the pale lilac #B3A8CC as B 1/8 + W 7/8.
_HIPPOCHOMP_BANDS: dict[tuple[int, int, int], tuple[tuple[str, int], ...]] = {
    _HIPPOCHOMP_SENTINEL_HIDE: (("blue", 16), ("red", 24), ("white", 64)),
    _HIPPOCHOMP_SENTINEL_HIDE_DARK: (("blue", 24), ("red", 32), ("white", 64)),
    _HIPPOCHOMP_SENTINEL_SNOUT: (("blue", 8), ("white", 64)),
    _HIPPOCHOMP_SENTINEL_PINK: (("red", 32), ("white", 64)),
    _HIPPOCHOMP_SENTINEL_ORANGE: (("red", 32), ("yellow", 64)),
    _HIPPOCHOMP_SENTINEL_LIME: (("green", 32), ("yellow", 64)),
}
# The fruit cycle, in the order the app's fruit pop up.
_HIPPOCHOMP_FRUIT = ("watermelon", "pineapple", "tomato", "banana")
# A fixed seed: the scatter of tufts and flowers is the same on every frame.
_HIPPOCHOMP_SCATTER_SEED = 0x41AA0C


def _hippochomp_clamp_rect(rect, width: int, height: int):
    x0, y0, x1, y1 = rect
    x0 = max(0, int(x0))
    y0 = max(0, int(y0))
    x1 = min(width - 1, int(x1))
    y1 = min(height - 1, int(y1))
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _hippochomp_post_pass(image: Image.Image, bbox) -> None:
    """Replace every sentinel pixel inside ``bbox`` with its banded stipple."""
    rect = _hippochomp_clamp_rect(bbox, *image.size)
    if rect is None:
        return
    x0, y0, x1, y1 = rect
    px = rgb_pixel_access(image)
    bands: dict[tuple[int, ...], tuple[tuple[tuple[int, int, int], int], ...]] = {
        sentinel: tuple((SPECTRA6[ink], upper) for ink, upper in spec)
        for sentinel, spec in _HIPPOCHOMP_BANDS.items()
    }
    for y in range(y0, y1 + 1):
        row = BAYER_8x8[y & 7]
        for x in range(x0, x1 + 1):
            spec = bands.get(px[x, y])
            if spec is None:
                continue
            rank = row[x & 7]
            for ink, upper in spec:
                if rank < upper:
                    px[x, y] = ink
                    break


def _hippochomp_horizon(height: int) -> int:
    return round(height * _HIPPOCHOMP_HORIZON)


def _hippochomp_checker(size: tuple[int, int], ink_a: str, ink_b: str) -> Image.Image:
    """A canvas-sized 1:1 checkerboard on absolute ``(x + y) & 1`` parity."""
    tile = Image.new("RGB", (2, 2), SPECTRA6[ink_b])
    tile.putpixel((0, 0), SPECTRA6[ink_a])
    tile.putpixel((1, 1), SPECTRA6[ink_a])
    width, height = size
    board = Image.new("RGB", (width + 1, height + 1))
    for ty in range(0, height + 1, 2):
        for tx in range(0, width + 1, 2):
            board.paste(tile, (tx, ty))
    return board.crop((0, 0, width, height))


def _hippochomp_paint_ground(image: Image.Image) -> None:
    """Sky over grass, each a 1:1 checkerboard: B+W sky blue, G+Y lime grass,
    with a solid green band at the horizon."""
    width, height = image.size
    horizon = _hippochomp_horizon(height)
    image.paste(_hippochomp_checker((width, height), "green", "yellow"))
    if horizon > 0:
        image.paste(_hippochomp_checker((width, horizon), "blue", "white"), (0, 0))
    band_h = max(1, round(_HIPPOCHOMP_HORIZON_BAND * height / 480))
    ImageDraw.Draw(image).rectangle((0, horizon, width - 1, min(height - 1, horizon + band_h - 1)), fill=SPECTRA6["green"])


def _hippochomp_paint_sun(image: Image.Image, draw, k: float) -> None:
    """The app's sun, top right: a yellow disc in an orange rim, eight rays."""
    width, _ = image.size
    cx = width - 66 * k
    cy = 30 * k
    r = 20 * k
    yellow = SPECTRA6["yellow"]
    ray_w = max(1, round(3 * k))
    for i in range(8):
        a = math.tau * i / 8 + math.pi / 8
        draw.line(
            (cx + math.cos(a) * (r + 6 * k), cy + math.sin(a) * (r + 6 * k),
             cx + math.cos(a) * (r + 13 * k), cy + math.sin(a) * (r + 13 * k)),
            fill=yellow, width=ray_w,
        )
    rim = max(1, round(3 * k))
    box = (cx - r, cy - r, cx + r, cy + r)
    draw.ellipse(box, fill=_HIPPOCHOMP_SENTINEL_ORANGE)
    draw.ellipse((box[0] + rim, box[1] + rim, box[2] - rim, box[3] - rim), fill=yellow)
    _hippochomp_post_pass(image, box)


# The app's cloud: five circles, ``(dx, dy, r)`` in points, y down.
_HIPPOCHOMP_CLOUD = ((0, 0, 26), (-28, 4, 18), (28, 4, 18), (10, -10, 16), (-12, -9, 15))


def _hippochomp_paint_cloud(draw, cx: float, cy: float, s: float) -> None:
    white = SPECTRA6["white"]
    for dx, dy, r in _HIPPOCHOMP_CLOUD:
        draw.ellipse((cx + (dx - r) * s, cy + (dy - r) * s, cx + (dx + r) * s, cy + (dy + r) * s), fill=white)
    # A flat underside, as the app's lowest circles sit on one line.
    draw.rectangle((cx - 28 * s, cy + 4 * s, cx + 28 * s, cy + 22 * s), fill=white)


def _hippochomp_paint_scatter(image: Image.Image, draw, k: float) -> None:
    """Grass tufts and five-petal flowers over the field, on a fixed seed."""
    width, height = image.size
    horizon = _hippochomp_horizon(height) + round(_HIPPOCHOMP_HORIZON_BAND * k) + 10
    if horizon >= height - 4:
        return
    rng = random.Random(_HIPPOCHOMP_SCATTER_SEED)
    green = SPECTRA6["green"]
    blade = max(1, round(2 * k))
    for _ in range(46):
        x = rng.uniform(8, 792) * width / 800
        y = horizon + rng.uniform(0, 1) * (height - 6 - horizon)
        for dx, dy in ((-5, -9), (0, -12), (5, -9)):
            draw.line((x, y, x + dx * k, y + dy * k), fill=green, width=blade)
    petals = (("white", "yellow"), ("yellow", "red"), ("red", "yellow"), ("white", "red"))
    for i in range(64):
        x = rng.uniform(8, 792) * width / 800
        y = horizon + rng.uniform(0, 1) * (height - 6 - horizon)
        petal, centre = petals[i % len(petals)]
        pr = 2.6 * k
        ring = 3.6 * k
        for j in range(5):
            a = math.tau * j / 5 - math.pi / 2
            px_, py_ = x + math.cos(a) * ring, y + math.sin(a) * ring
            draw.ellipse((px_ - pr, py_ - pr, px_ + pr, py_ + pr), fill=SPECTRA6[petal])
        cr = 2.0 * k
        draw.ellipse((x - cr, y - cr, x + cr, y + cr), fill=SPECTRA6[centre])


def _hippochomp_paint_card(image: Image.Image, draw, rect, k: float) -> None:
    """The white card on its flat drop: the ground directly under the dropped
    silhouette goes solid (blue on the sky, green on the grass), the
    unblurred ``0 8px 0`` shadow of the page's cards."""
    width, height = image.size
    x0, y0, x1, y1 = rect
    radius = max(2, round(_HIPPOCHOMP_CARD_RADIUS * k))
    drop = max(1, round(_HIPPOCHOMP_SHADOW_DROP * k))
    mask = Image.new("1", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((x0, y0 + drop, x1, y1 + drop), radius=radius, fill=1)
    horizon = _hippochomp_horizon(height)
    shade_sky = Image.new("RGB", (width, height), SPECTRA6["blue"])
    shade_grass = Image.new("RGB", (width, height), SPECTRA6["green"])
    if horizon > 0:
        image.paste(shade_sky.crop((0, 0, width, horizon)), (0, 0), mask.crop((0, 0, width, horizon)))
    image.paste(shade_grass.crop((0, horizon, width, height)), (0, horizon), mask.crop((0, horizon, width, height)))
    draw.rounded_rectangle(rect, radius=radius, fill=SPECTRA6["white"])


def _hippochomp_paint_wordmark(draw, k: float) -> None:
    """"HippoChomp" as the store art's sticker: green, white outline."""
    size = max(8, round(26 * k))
    font = load_font([(BRICOLAGE_VARIABLE, "ExtraBold"), *QUOTE_FONT_BOLD_CANDIDATES], size=size)
    draw.text(
        (_HIPPOCHOMP_MARGIN * k, 37 * k), "HippoChomp", font=font, fill=SPECTRA6["green"], anchor="ls",
        stroke_width=max(1, round(3 * k)), stroke_fill=SPECTRA6["white"],
    )


def _hippochomp_quad(p0, p1, p2, steps: int = 10):
    return [
        (
            (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
            (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1],
        )
        for t in (i / steps for i in range(steps + 1))
    ]


def _hippochomp_paint_hippo(image: Image.Image, draw, cx: float, cy: float, s: float) -> None:
    """The app's hippo (``HippoNode``), facing right, at scale ``s``.

    ``cx, cy`` is the body centre; the app's points are y-up, so every
    offset is flipped on the way in."""
    black = SPECTRA6["black"]
    white = SPECTRA6["white"]

    def pt(x, y):
        return (cx + x * s, cy - y * s)

    def ellipse(x, y, w, h, fill, outline=None, line=0):
        box = (cx + (x - w / 2) * s, cy - (y + h / 2) * s, cx + (x + w / 2) * s, cy - (y - h / 2) * s)
        draw.ellipse(box, fill=fill, outline=outline, width=max(1, round(line * s)) if outline else 0)

    # Ground shadow, the darker grass under him.
    ellipse(0, -54, 150, 26, SPECTRA6["green"])
    # Legs: far pair in the darker hide, near pair in hide.
    for x, sentinel in ((-52, _HIPPOCHOMP_SENTINEL_HIDE_DARK), (24, _HIPPOCHOMP_SENTINEL_HIDE_DARK),
                        (-22, _HIPPOCHOMP_SENTINEL_HIDE), (54, _HIPPOCHOMP_SENTINEL_HIDE)):
        x0, y0 = pt(x - 13, -18)
        x1, y1 = pt(x + 13, -58)
        draw.rounded_rectangle((x0, y0, x1, y1), radius=max(1, round(12 * s)), fill=sentinel,
                               outline=black, width=max(1, round(3 * s)))
    # Tail.
    draw.line(_hippochomp_quad(pt(-72, -8), pt(-88, -10), pt(-94, 6)), fill=black, width=max(1, round(5 * s)), joint="curve")
    # Body and belly.
    ellipse(0, 0, 152, 96, _HIPPOCHOMP_SENTINEL_HIDE, black, 4)
    ellipse(-4, -18, 96, 52, _HIPPOCHOMP_SENTINEL_SNOUT)
    # Head group at (62, 22): ears behind the skull.
    hx, hy = 62, 22
    for ex, ey in ((-12, 34), (16, 30)):
        ellipse(hx + ex, hy + ey, 22, 22, _HIPPOCHOMP_SENTINEL_HIDE, black, 3)
        ellipse(hx + ex, hy + ey, 10, 10, _HIPPOCHOMP_SENTINEL_PINK)
    ellipse(hx, hy, 72, 72, _HIPPOCHOMP_SENTINEL_HIDE, black, 4)
    ellipse(hx - 16, hy - 6, 14, 9, _HIPPOCHOMP_SENTINEL_PINK)
    ellipse(hx + 28, hy - 10, 68, 50, _HIPPOCHOMP_SENTINEL_SNOUT, black, 4)
    for nx in (20, 40):
        ellipse(hx + nx, hy + 2, 8, 11, black)
    draw.line(_hippochomp_quad(pt(hx + 14, hy - 22), pt(hx + 32, hy - 30), pt(hx + 46, hy - 18)),
              fill=black, width=max(1, round(3 * s)), joint="curve")
    for ex in (-4, 22):
        ellipse(hx + ex, hy + 16, 20, 20, white, black, 2)
        ellipse(hx + ex + 2, hy + 16, 9, 9, black)
    _hippochomp_post_pass(image, (cx - 100 * s, cy - 72 * s, cx + 130 * s, cy + 64 * s))


def _hippochomp_paint_fruit(image: Image.Image, draw, kind: str, cx: float, base: float, k: float) -> None:
    """One fruit standing on ``base``, centred on ``cx``: black outlines, the
    app's flat fills, a white shine."""
    black = SPECTRA6["black"]
    white = SPECTRA6["white"]
    green = SPECTRA6["green"]
    line = max(1, round(2 * k))
    if kind == "watermelon":
        w, h = 26 * k, 19 * k
        box = (cx - w / 2, base - h, cx + w / 2, base)
        draw.ellipse(box, fill=_HIPPOCHOMP_SENTINEL_LIME)
        _hippochomp_post_pass(image, box)
        stripe = max(1, round(3 * k))
        for dx in (-7, 0, 7):
            draw.arc((cx + (dx - 4) * k, base - h + 1, cx + (dx + 4) * k, base - 1),
                     start=270 if dx < 0 else (90 if dx > 0 else 270), end=90 if dx < 0 else (270 if dx > 0 else 90),
                     fill=green, width=stripe)
        draw.ellipse(box, outline=black, width=line)
        draw.ellipse((cx - 8 * k, base - h + 4 * k, cx - 3 * k, base - h + 7 * k), fill=white)
    elif kind == "pineapple":
        w, h = 18 * k, 22 * k
        box = (cx - w / 2, base - h, cx + w / 2, base)
        for dx in (-5, 0, 5):
            draw.polygon(((cx + (dx - 2) * k, base - h + 2), (cx + dx * 1.6 * k, base - h - 10 * k), (cx + (dx + 2) * k, base - h + 2)), fill=green)
        draw.ellipse(box, fill=SPECTRA6["yellow"])
        mask = Image.new("1", image.size, 0)
        ImageDraw.Draw(mask).ellipse(box, fill=1)
        lattice = Image.new("RGB", image.size, SPECTRA6["yellow"])
        ld = ImageDraw.Draw(lattice)
        for off in range(-30, 31, 6):
            ld.line((cx + (off - 12) * k, base, cx + (off + 12) * k, base - h), fill=SPECTRA6["red"], width=1)
            ld.line((cx + (off + 12) * k, base, cx + (off - 12) * k, base - h), fill=SPECTRA6["red"], width=1)
        image.paste(lattice, (0, 0), mask)
        draw.ellipse(box, outline=black, width=line)
    elif kind == "tomato":
        w, h = 24 * k, 20 * k
        box = (cx - w / 2, base - h, cx + w / 2, base)
        draw.ellipse(box, fill=SPECTRA6["red"], outline=black, width=line)
        top = base - h + 1
        for dx, dy in ((-6, 3), (-3, -2), (3, -2), (6, 3)):
            draw.line((cx, top, cx + dx * k, top + dy * k), fill=green, width=max(1, round(2 * k)))
        draw.line((cx, top, cx, top - 4 * k), fill=green, width=max(1, round(2 * k)))
        draw.ellipse((cx - 8 * k, base - h + 6 * k, cx - 4 * k, base - h + 9 * k), fill=white)
    else:  # banana
        # A thick yellow crescent in a black outline, brown-black tips.
        w, h = 30 * k, 24 * k
        box = (cx - w / 2, base - 2 * h + 4 * k, cx + w / 2, base)
        thick = max(3, round(9 * k))
        draw.arc(box, start=15, end=165, fill=black, width=thick)
        inset = box[0] + line, box[1] + line, box[2] - line, box[3] - line
        draw.arc(inset, start=19, end=161, fill=SPECTRA6["yellow"], width=max(1, thick - 2 * line))
        for angle in (15, 165):
            tx = cx + math.cos(math.radians(angle)) * (w / 2 - thick / 2)
            ty = (box[1] + box[3]) / 2 + math.sin(math.radians(angle)) * (h - thick / 2)
            draw.ellipse((tx - 2 * k, ty - 2 * k, tx + 2 * k, ty + 2 * k), fill=black)


def _hippochomp_hippo_scale(height: int, k: float, clear_rect) -> float:
    """As big as the room under the quote allows: his ears may rise into the
    card's bottom padding but never into the attribution above it."""
    if clear_rect is None:
        return _HIPPOCHOMP_HIPPO_SCALE * k
    text_bottom = clear_rect[3] - _HIPPOCHOMP_PAD_BOTTOM * k
    room = height - _HIPPOCHOMP_GROUND_RISE * k - (text_bottom + 4 * k)
    scale = room / _HIPPOCHOMP_HIPPO_POINTS
    return max(_HIPPOCHOMP_HIPPO_SCALE_MIN * k, min(_HIPPOCHOMP_HIPPO_SCALE_MAX * k, scale))


def _hippochomp_paint_foreground(image: Image.Image, draw, k: float, s: float, hour: int | None) -> None:
    """The hippo at the foot, bottom left, and the hour's fruit in a row
    ahead of him — one fruit for one o'clock, twelve for twelve."""
    width, height = image.size
    ground = height - _HIPPOCHOMP_GROUND_RISE * k
    cx = _HIPPOCHOMP_MARGIN * k + 94 * s
    cy = ground - 58 * s
    _hippochomp_paint_hippo(image, draw, cx, cy, s)
    # Below about a third of the panel the fruit would be a few pixels
    # across, too small to draw a fruit at all.
    if not hour or k < _HIPPOCHOMP_FRUIT_MIN_SCALE:
        return
    x = cx + 124 * s + 22 * k
    for i in range(hour):
        fx = x + i * _HIPPOCHOMP_FRUIT_PITCH * k
        if fx + 16 * k > width - _HIPPOCHOMP_MARGIN * k:
            break
        _hippochomp_paint_fruit(image, draw, _HIPPOCHOMP_FRUIT[i % len(_HIPPOCHOMP_FRUIT)], fx, ground, k)


def draw_hippochomp_border(image: Image.Image, colors: dict, clear_rect=None, time_str: str | None = None) -> None:
    """Paint the HippoChomp field: sky, grass, sun, clouds, the card, the
    hippo and the hour's fruit.

    Repaints the whole canvas, so ``render``'s two calls compose identically.
    Without a ``clear_rect`` (the source card, the static message) the card
    takes a fixed rect; without a time there is no fruit.
    """
    del colors
    width, height = image.size
    k = min(width / 800, height / 480)
    _hippochomp_paint_ground(image)
    draw = ImageDraw.Draw(image)
    _hippochomp_paint_scatter(image, draw, k)
    _hippochomp_paint_cloud(draw, width * 0.42, 27 * k, 0.55 * k)
    _hippochomp_paint_cloud(draw, width * 0.66, 22 * k, 0.45 * k)
    _hippochomp_paint_sun(image, draw, k)
    if clear_rect is None:
        card = _hippochomp_clamp_rect(
            (_HIPPOCHOMP_MARGIN * k, 60 * k, width - _HIPPOCHOMP_MARGIN * k, height - 80 * k), width, height
        )
    else:
        card = _hippochomp_clamp_rect(clear_rect, width, height)
    if card is not None:
        _hippochomp_paint_card(image, draw, card, k)
    _hippochomp_paint_wordmark(draw, k)
    s = _hippochomp_hippo_scale(height, k, clear_rect if card is not None else None)
    hour = _clock_hour12(time_str) if time_str else None
    _hippochomp_paint_foreground(image, draw, k, s, hour)


SPEC = BorderSpec(
    themes=("hippochomp",),
    paint=draw_hippochomp_border,
    # The card is the body rect grown by the page's card padding, radius 24
    # so the corner arcs clear a first or last line; the time picks the
    # number of fruit.
    clear_rect_pad=(28, 18, _HIPPOCHOMP_PAD_BOTTOM),
    wants_time=True,
    # The sun's rays reach x = width - 98 inside the debug banner's band.
    debug_label_inset=110,
)
