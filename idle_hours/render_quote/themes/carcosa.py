"""The ``carcosa`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from ..palette import SPECTRA6, BAYER_4x4
from ..primitives import position_noise
from ..spec import BorderSpec

# The King in Yellow — Robert W. Chambers, 1895.
#
#     Along the shore the cloud waves break,
#     The twin suns sink behind the lake,
#         The shadows lengthen
#             In Carcosa.
#     Strange is the night where black stars rise,
#     And strange moons circle through the skies ...
#
# ``carcosa`` stages the page as the play itself: a tattered yellow curtain
# drawn back at either side, the Yellow Sign hung over the proscenium, black
# stars in a sickly sky, and — along the foot — the towers of Carcosa standing
# against twin suns as they sink into Lake Hali. Everything is solid Spectra-6
# ink laid with ``ImageDraw`` primitives, plus two sparse haze washes and one
# tangerine post-pass on the curtain folds, all bounds-checked so the painter
# clips cleanly at the ``/api/preview`` thumbnail sizes.
#
# The Yellow Sign here is an original glyph — Chambers never describes it, and
# the well-known triskelion is a later artist's design — so it is drawn as
# three hooked arms spiralling off a ring, asymmetric enough to feel wrong.

# (x as a fraction of width, y, radius) for the black stars in the top margin.
# Positioned by hand so none crowds the Yellow Sign at the top centre.
_CARCOSA_BLACK_STARS: tuple[tuple[float, int, int], ...] = (
    (0.17, 20, 5),
    (0.29, 40, 4),
    (0.38, 16, 3),
    (0.62, 18, 4),
    (0.72, 42, 5),
    (0.83, 22, 3),
)
# (x fraction, radius) for the twin suns, both sitting on the horizon.
_CARCOSA_SUNS: tuple[tuple[float, int], ...] = ((0.655, 30), (0.765, 19))
# Carcosa's skyline as (x fraction, half width, height, spire) — a spire of 0
# is a flat-topped tower. Kept low enough that both suns' crowns stay clear:
# the city stands *against* the suns, it does not hide them.
_CARCOSA_TOWERS: tuple[tuple[float, int, int, int], ...] = (
    (0.596, 2, 7, 5),
    (0.61, 3, 12, 8),
    (0.626, 2, 20, 12),
    (0.64, 4, 9, 6),
    (0.655, 2, 26, 14),
    (0.668, 3, 14, 9),
    (0.684, 2, 10, 7),
    (0.70, 3, 17, 10),
    (0.716, 2, 8, 5),
    (0.735, 3, 12, 8),
    (0.752, 2, 22, 12),
    (0.768, 4, 9, 6),
    (0.785, 2, 14, 9),
    (0.803, 3, 7, 5),
)


def _carcosa_haze(image: Image.Image, x0: int, x1: int, y_near: int, y_far: int, peak: float) -> None:
    """Scatter a sparse yellow haze over black, densest at ``y_near``.

    Density falls linearly to zero at ``y_far`` (either side of ``y_near``), and
    only black pixels are touched so nothing already painted is overwritten. A
    positional hash rather than a Bayer rank, because at these densities an
    ordered tile lays a visible lattice (see :func:`position_noise`).
    """
    width, height = image.size
    px = image.load()
    black = SPECTRA6["black"]
    yellow = SPECTRA6["yellow"]
    span = y_far - y_near
    if span == 0:
        return
    lo, hi = sorted((y_near, y_far))
    for y in range(max(0, lo), min(height, hi + 1)):
        density = peak * (1.0 - (y - y_near) / span)
        if density <= 0:
            continue
        cut = int(density * 256)
        for x in range(max(0, x0), min(width, x1)):
            if px[x, y] == black and position_noise(x, y) < cut:
                px[x, y] = yellow


def _carcosa_star(cx: float, cy: float, r: float) -> list[tuple[float, float]]:
    """A four-pointed star: long cardinal rays, pinched waist."""
    waist = max(1.0, r * 0.32)
    points = []
    for i in range(8):
        angle = math.pi / 4 * i - math.pi / 2
        radius = r if i % 2 == 0 else waist
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


def _carcosa_paint_drape(image: Image.Image, draw: ImageDraw.ImageDraw, side: int, scale: float) -> None:
    """One tattered yellow curtain, tied back, down the left (-1) or right (+1).

    The inner edge is torn — two incommensurate sines plus a notch every so
    often — and the hem breaks into hanging strands. Fold creases run from the
    rail to the tie-back and fan out below it; each crease is laid as a 3 px
    red shadow under a 1 px black line, and the red is then Bayer-flipped to
    the R+Y 5/8:3/8 tangerine so the folds read as shadowed, decaying cloth.
    """
    width, height = image.size
    yellow = SPECTRA6["yellow"]
    red = SPECTRA6["red"]
    black = SPECTRA6["black"]
    top_w = 34 * scale
    tie_w = 12 * scale
    hem_w = 29 * scale
    tie_y = int(height * 0.56)
    hem_y = int(height * 0.79)

    def edge(y: int) -> float:
        if y <= tie_y:
            t = y / max(1, tie_y)
            w = top_w + (tie_w - top_w) * (t ** 1.4)
        else:
            t = (y - tie_y) / max(1, hem_y - tie_y)
            w = tie_w + (hem_w - tie_w) * math.sqrt(t)
        tear = 1.6 * math.sin(y * 0.31) + 1.1 * math.sin(y * 0.117 + 1.3)
        if (y // 6) % 9 == 4:
            tear -= 4 * scale  # a rent in the cloth
        return max(2.0, w + tear * scale)

    def fx(x: float) -> float:
        return x if side < 0 else width - 1 - x

    step = 3
    inner = [(fx(edge(y)), y) for y in range(0, hem_y + 1, step)]
    # Ragged hem: strands of irregular length hanging below ``hem_y``.
    hem = []
    x = edge(hem_y)
    strand = 0
    while x > 0:
        drop = int((10 + 22 * abs(math.sin(strand * 2.3 + side))) * scale)
        hem.append((fx(x), hem_y + drop))
        x -= 3 * scale
        hem.append((fx(max(0.0, x)), hem_y + int(drop * 0.3)))
        x -= 3 * scale
        strand += 1
    polygon = [(fx(0), 0)] + inner + hem + [(fx(0), hem_y)]
    draw.polygon(polygon, fill=yellow)

    # Fold creases: rail → tie-back, then tie-back → hem.
    tie_x = tie_w * 0.5
    creases = []
    for frac in (0.3, 0.62, 0.9):
        creases.append(((top_w * frac, 0), (tie_x, tie_y)))
    for frac in (0.25, 0.7):
        creases.append(((tie_x, tie_y), (hem_w * frac, hem_y)))
    for (ax, ay), (bx, by) in creases:
        draw.line([(fx(ax + 1), ay), (fx(bx + 1), by)], fill=red, width=3)
    for (ax, ay), (bx, by) in creases:
        draw.line([(fx(ax), ay), (fx(bx), by)], fill=black, width=1)
    # Tangerine shadow: flip 3/8 of the crease red to yellow on the 4x4 tile.
    px = image.load()
    x_lo = 0 if side < 0 else max(0, int(width - 1 - top_w - 4))
    x_hi = min(width, int(top_w + 4)) if side < 0 else width
    for y in range(0, min(height, hem_y + 1)):
        for xx in range(x_lo, x_hi):
            if px[xx, y] == red and BAYER_4x4[y % 4][xx % 4] < 6:
                px[xx, y] = yellow

    # Blood-red tie-back cord, knotted once, with a tassel hanging off it.
    cord_x1 = fx(tie_w + 3 * scale)
    draw.line([(fx(0), tie_y - 2), (cord_x1, tie_y + 1)], fill=red, width=max(1, int(3 * scale)))
    knot = max(1, int(3 * scale))
    draw.ellipse((cord_x1 - knot, tie_y - knot + 1, cord_x1 + knot, tie_y + knot + 1), fill=red)
    draw.line([(cord_x1, tie_y + knot), (cord_x1 - side * 2 * scale, tie_y + 16 * scale)], fill=red, width=1)

    # Moth-holes and black stars eaten through the cloth.
    for fy, fxr, r in ((0.12, 0.45, 3), (0.31, 0.55, 2), (0.47, 0.5, 1.5), (0.68, 0.6, 2)):
        y = int(height * fy)
        cx = fx(edge(y) * fxr)
        rr = r * scale
        if rr >= 2:
            draw.polygon(_carcosa_star(cx, y, rr * 1.8), fill=black)
        else:
            draw.ellipse((cx - 1, y - 1, cx + 1, y + 1), fill=black)


def _carcosa_paint_sign(draw: ImageDraw.ImageDraw, cx: float, cy: float, s: float, ink) -> None:
    """The Yellow Sign: three hooked arms spiralling off a small ring.

    Each arm is an Archimedean spiral swept through 110 degrees and closed by
    a short backward hook; the arms are rotated 120 degrees apart but the third
    is drawn longer, so the glyph is almost — not quite — symmetric.
    """
    stroke = max(1, int(round(s / 7)))
    ring = s * 0.22
    draw.ellipse((cx - ring, cy - ring, cx + ring, cy + ring), outline=ink, width=stroke)
    for arm, base in enumerate((-90.0, 30.0, 150.0)):
        reach = s * (1.12 if arm == 2 else 0.95)
        points = []
        for i in range(15):
            t = i / 14
            theta = math.radians(base + 110 * t)
            r = ring + (reach - ring) * t
            points.append((cx + r * math.cos(theta), cy + r * math.sin(theta)))
        # The hook: curl back inward from the arm's tip.
        tip_theta = math.radians(base + 110)
        hook_r = reach * 0.66
        points.append((cx + hook_r * math.cos(tip_theta + 0.45), cy + hook_r * math.sin(tip_theta + 0.45)))
        draw.line(points, fill=ink, width=stroke, joint="curve")
    # A single dot beneath, like a punctuation mark that is not in any alphabet.
    dot = max(1.0, s * 0.09)
    dy = cy + s * 1.3
    draw.ellipse((cx - dot, dy - dot, cx + dot, dy + dot), fill=ink)


def _carcosa_paint_sky(image: Image.Image, draw: ImageDraw.ImageDraw, scale: float) -> None:
    """The sickly top margin: a thin yellow haze and the black stars rising in it."""
    width, height = image.size
    yellow = SPECTRA6["yellow"]
    black = SPECTRA6["black"]
    margin = int(40 * scale)
    band = int(56 * scale)
    _carcosa_haze(image, margin, width - margin, 0, band, 0.09)
    for fx, y, r in _CARCOSA_BLACK_STARS:
        cx, cy, rr = width * fx, y * scale, r * scale
        if rr < 2 or cy + rr >= height:
            continue
        # Clear a pocket in the haze, then draw the star as a black shape with
        # a yellow rim — a black star has to be outlined to be seen at all.
        halo = rr + 2
        draw.ellipse((cx - halo, cy - halo, cx + halo, cy + halo), fill=black)
        draw.polygon(_carcosa_star(cx, cy, rr + 1), fill=black, outline=yellow)


def _carcosa_paint_lake(image: Image.Image, draw: ImageDraw.ImageDraw, scale: float) -> None:
    """Lake Hali along the foot: cloud-waves, twin suns, Carcosa, reflections."""
    width, height = image.size
    yellow = SPECTRA6["yellow"]
    white = SPECTRA6["white"]
    black = SPECTRA6["black"]
    horizon = height - int(32 * scale)
    margin = int(42 * scale)
    if horizon <= 0 or width <= 2 * margin:
        return

    # Glow of the setting suns over the far shore.
    _carcosa_haze(image, margin, width - margin, horizon - 1, horizon - int(34 * scale), 0.12)

    # The twin suns, half-sunk.
    for fx, r in _CARCOSA_SUNS:
        cx, rr = width * fx, r * scale
        draw.pieslice((cx - rr, horizon - rr, cx + rr, horizon + rr), 180, 360, fill=yellow)

    # Carcosa, black against the suns and the glow.
    for fx, half, h, spire in _CARCOSA_TOWERS:
        cx = width * fx
        hw, hh, sp = half * scale, h * scale, spire * scale
        top = horizon - hh
        draw.rectangle((cx - hw, top, cx + hw, horizon), fill=black)
        if sp:
            draw.polygon([(cx - hw, top), (cx, top - sp), (cx + hw, top)], fill=black)
        # One lit window in the taller towers — someone is awake in Carcosa.
        if h >= 17:
            wy = top + hh * 0.3
            draw.line([(cx, wy), (cx, wy + 2)], fill=yellow, width=1)

    # The shore line itself.
    draw.line([(margin, horizon), (width - margin, horizon)], fill=yellow, width=1)

    # Cloud-waves breaking along the shore to the left of the city: rows of
    # small white crests that thin out as they near the water.
    wave_r = max(2, int(5 * scale))
    x_end = width * 0.55
    for row, dy in enumerate((3, 9, 15)):
        y = horizon + int(dy * scale)
        x = margin + (row % 2) * wave_r
        while x + 2 * wave_r < x_end:
            if (int(x) // (2 * wave_r) + row) % (row + 1) == 0:
                draw.arc((x, y - wave_r, x + 2 * wave_r, y + wave_r), 200, 340, fill=white, width=1)
            x += 2 * wave_r + int(3 * scale)

    # The suns' reflections in the lake: broken dashes that narrow with depth.
    for fx, r in _CARCOSA_SUNS:
        cx = width * fx
        for i, dy in enumerate(range(3, int(26 * scale), 3)):
            half = r * scale * (1.0 - i * 0.11)
            if half < 1:
                break
            shift = 2.5 * math.sin(i * 1.9 + fx * 10) * scale
            y = horizon + dy
            if y >= height:
                break
            gap = max(1.0, half * 0.25)
            draw.line([(cx - half + shift, y), (cx - gap + shift, y)], fill=yellow, width=1)
            draw.line([(cx + gap + shift, y), (cx + half + shift, y)], fill=yellow, width=1)


def draw_carcosa_border(image: Image.Image, colors: dict) -> None:
    """Paint the King in Yellow stage: curtains, the Sign, the sky, Lake Hali.

    Composition, back to front:

    * **Sky** — a sparse yellow haze across the top margin, fading by y≈56,
      with six black stars rising in it (black four-pointed stars, rimmed in
      yellow so a black shape can be seen against black).
    * **The Yellow Sign** — centred at the top, clear of the right-aligned
      ``DEBUG MODE`` banner.
    * **Tattered curtains** — one down each side, drawn back to a blood-red
      tie-back cord, torn along the inner edge and frayed into strands at the
      hem, with tangerine-shadowed folds and holes eaten through them.
    * **Lake Hali** — along the foot, the towers of Carcosa stand in
      silhouette against twin suns as they sink, cloud-waves break along the
      shore to the left, and the suns' reflections break up in the water.

    Only the curtains reach the side margins (x ≤ 34 at the rail; the body
    column starts at x≈60); the sky stays above y≈56 and the lake below
    y≈416, the bands the shared layout leaves free.
    """
    del colors  # every ink here is the theme's own; the THEMES slots are the text's.
    width, height = image.size
    scale = min(1.0, width / 800, height / 480)
    draw = ImageDraw.Draw(image)
    _carcosa_paint_sky(image, draw, scale)
    sign_s = 22 * scale
    if sign_s >= 5:
        _carcosa_paint_sign(draw, width / 2, 28 * scale, sign_s, SPECTRA6["yellow"])
    _carcosa_paint_lake(image, draw, scale)
    for side in (-1, 1):
        _carcosa_paint_drape(image, draw, side, scale)


SPEC = BorderSpec(
    themes=("carcosa",),
    paint=draw_carcosa_border,
    # carcosa: the right-hand curtain hangs from the rail at x=width-35..width-1
    # straight through the y=14-29 banner band; 46 clears its torn inner edge.
    debug_label_inset=46,
)
