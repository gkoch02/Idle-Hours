"""The ``cartograph`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from .._paths import IMFELLENGLISH_ITALIC, IMFELLENGLISH_REGULAR, META_FONT_CANDIDATES
from ..fonts import load_font
from ..palette import SPECTRA6, BAYER_4x4

# Seeds for ``draw_cartograph_border``'s deterministic placement. A fixed
# chart keeps renders byte-identical and keeps the map silhouette stable
# from minute to minute. The values are arbitrary, chosen so the foxing,
# coastline wobble and place-name jitter don't visibly correlate.
_CARTOGRAPH_FOXING_SEED = 0xCA70
_CARTOGRAPH_COAST_TL_SEED = 0xC0A571
_CARTOGRAPH_COAST_BR_SEED = 0xC0A5B7


# Three Latin chart labels in the open-sea regions, not inside the
# coastlines (a sepia-stippled label inside a sepia coast would vanish).
# ``cx_frac`` / ``cy_frac`` are canvas-relative. Italic IM Fell English.
#
# Positions clear, at 800×480:
#   * the body clear_rect (typically (104..696, 116..360) with cartograph's
#     22/12/12 pad),
#   * the y=14-29 debug-mode banner band (top right),
#   * the TL coastline bbox (0,0)..(176, 96),
#   * the BR coastline bbox (624, 384)..(799, 479),
#   * the compass rose bbox (40..104, 372..436),
#   * the sea-serpent bbox ~(706..774, 252..276).
_CARTOGRAPH_PLACE_NAMES = (
    # Top sea, centred, label centre y≈48: below the debug band and above
    # the cartouche top in every layout (dense: 72 - 12 = 60).
    ("Mare Incognitum", 0.50, 0.10),
    # Top-right sea, same row, cx≈672: clear of Mare Incognitum and the
    # right edge.
    ("Insula Aurea", 0.84, 0.10),
    # Bottom sea, between the compass rose and the BR coast, centre
    # y≈413: below the dense cartouche (~y=400) and above the debug strip
    # (y≈454-466). Deliberately tight; any lower and it touches the strip.
    ("Terra Nova", 0.48, 0.86),
)


# Three small islands in the open sea, so the chart reads as populated.
# Each is ``(cx_frac, cy_frac, scale_w, scale_h, seed)``: a small seeded
# 8-point blob at (cx_frac × width, cy_frac × height), placed between the
# cartouche, coastlines, compass, serpent and labels.
_CARTOGRAPH_ISLANDS = (
    # Top sea, between the TL coastline and the "Mare Incognitum" label.
    (0.32, 0.16, 16, 10, 0xC0A511),
    # Bottom sea, between the compass rose and "Terra Nova", balancing the
    # BR landmass.
    (0.30, 0.85, 20, 12, 0xC0A522),
    # Bottom sea, between "Terra Nova" and the serpent.
    (0.62, 0.85, 14, 9, 0xC0A533),
)


# Graticule: meridians and parallels every 80 px (9 × 5 lines at
# 800×480), dotted every 3rd pixel so it reads as a faint reference grid.
_CARTOGRAPH_GRATICULE_SPACING = 80
_CARTOGRAPH_GRATICULE_DOT_PERIOD = 3


def _paint_cartograph_dotted_sepia_line(
    pixels,
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    dot_period: int,
    ground_ink_a,
    ground_ink_b,
    red_ink,
    green_ink,
) -> None:
    """Paint a dotted sepia line from ``(x0, y0)`` to ``(x1, y1)``.

    Dots alternate R/G in place by ``(px + py) & 1`` parity (sepia at
    viewing distance, no post-pass). Only pixels still equal to
    ``ground_ink_a`` (white) or ``ground_ink_b`` (cream yellow) are
    painted, so the line sits on the parchment and never overpaints
    earlier texture.

    ``dot_period``: 1 = solid, 2 = every other pixel, 3 = every third.
    The graticule uses 3 and the rhumb lines 2, so rhumbs dominate.
    """
    length = max(1, int(round(math.hypot(x1 - x0, y1 - y0))))
    for i in range(0, length + 1, dot_period):
        t = i / length
        px = round(x0 + (x1 - x0) * t)
        py = round(y0 + (y1 - y0) * t)
        if not (0 <= px < width and 0 <= py < height):
            continue
        current = pixels[px, py]
        if current not in (ground_ink_a, ground_ink_b):
            continue
        # Parity inverted vs. the coastline / island / label post-passes:
        # reds land at ``(px+py)&1 == 0``. Those post-passes flip parity-1
        # reds to green; reds at parity 1 here would be clobbered inside
        # any coastline or island bbox, breaking the R+G alternation.
        pixels[px, py] = green_ink if (px + py) & 1 else red_ink


def _draw_cartograph_graticule(
    pixels,
    width: int,
    height: int,
    ground_white,
    ground_cream,
    red_ink,
    green_ink,
) -> None:
    """Paint a faint sepia latitude / longitude graticule across the chart.

    The graticule is what turns decorated coastlines and a compass rose
    into a chart. Meridians at ``x = 80, 160, ..., 720`` and parallels at
    ``y = 80, 160, ..., 400`` (``_CARTOGRAPH_GRATICULE_SPACING``), dotted
    every 3rd pixel in in-place R/G sepia, so the grid reads as faint
    structure under the text. 3 px degree ticks mark each line at the
    canvas edges.

    Only cream-washed ground pixels are painted, so everything later
    layers over it; the cartouche knockout later re-washes the body rect,
    erasing the graticule there like a scroll laid over the map.
    """
    spacing = _CARTOGRAPH_GRATICULE_SPACING
    dot_period = _CARTOGRAPH_GRATICULE_DOT_PERIOD
    # Vertical meridians
    for x in range(spacing, width, spacing):
        _paint_cartograph_dotted_sepia_line(
            pixels, width, height, x, 0, x, height - 1,
            dot_period, ground_white, ground_cream, red_ink, green_ink,
        )
    # Horizontal parallels
    for y in range(spacing, height, spacing):
        _paint_cartograph_dotted_sepia_line(
            pixels, width, height, 0, y, width - 1, y,
            dot_period, ground_white, ground_cream, red_ink, green_ink,
        )
    # Edge ticks: 3 px solid sepia stubs where each line meets the canvas
    # edge, with the same inverted parity as
    # ``_paint_cartograph_dotted_sepia_line``.
    tick_len = 3
    for x in range(spacing, width, spacing):
        for offset in range(tick_len):
            # Top edge
            if 0 <= offset < height and pixels[x, offset] in (ground_white, ground_cream):
                pixels[x, offset] = green_ink if (x + offset) & 1 else red_ink
            # Bottom edge
            py = height - 1 - offset
            if 0 <= py < height and pixels[x, py] in (ground_white, ground_cream):
                pixels[x, py] = green_ink if (x + py) & 1 else red_ink
    for y in range(spacing, height, spacing):
        for offset in range(tick_len):
            # Left edge
            if 0 <= offset < width and pixels[offset, y] in (ground_white, ground_cream):
                pixels[offset, y] = green_ink if (offset + y) & 1 else red_ink
            # Right edge
            px = width - 1 - offset
            if 0 <= px < width and pixels[px, y] in (ground_white, ground_cream):
                pixels[px, y] = green_ink if (px + y) & 1 else red_ink


def _draw_cartograph_rhumb_lines(
    pixels,
    width: int,
    height: int,
    cx: int,
    cy: int,
    ground_white,
    ground_cream,
    red_ink,
    green_ink,
) -> None:
    """Paint eight rhumb lines radiating from the compass rose centre.

    One ray per principal bearing (N / NE / E / … / NW) out to the canvas
    edge minus a 12 px gap, the portolan-chart signature. Denser dotted
    sepia (period 2) than the graticule (period 3), so the compass is the
    focal feature. Only cream-washed ground pixels are painted, so later
    layers sit on top.
    """
    edge_pad = 12
    for angle_deg in (0, 45, 90, 135, 180, 225, 270, 315):
        angle = math.radians(angle_deg)
        dx = math.sin(angle)
        dy = -math.cos(angle)  # 0° = up
        # Find the closer edge in each axis (or skip if dx/dy is 0).
        t_x = float("inf")
        t_y = float("inf")
        if dx > 0:
            t_x = (width - edge_pad - cx) / dx
        elif dx < 0:
            t_x = (edge_pad - cx) / dx
        if dy > 0:
            t_y = (height - edge_pad - cy) / dy
        elif dy < 0:
            t_y = (edge_pad - cy) / dy
        t = min(t_x, t_y)
        if t == float("inf") or t <= 0:
            continue
        ex = round(cx + dx * t)
        ey = round(cy + dy * t)
        _paint_cartograph_dotted_sepia_line(
            pixels, width, height, cx, cy, ex, ey,
            dot_period=2, ground_ink_a=ground_white, ground_ink_b=ground_cream,
            red_ink=red_ink, green_ink=green_ink,
        )


def _draw_cartograph_island(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    scale_w: int,
    scale_h: int,
    ink_sentinel,
    seed: int,
) -> tuple[int, int, int, int]:
    """Paint a small wobbled-polygon island centred on ``(cx, cy)``.

    An 8-vertex polygon with seeded radial wobble, half-axes ``scale_w`` /
    ``scale_h``. Painted in ``ink_sentinel`` (red) for the caller's R+G
    sepia post-pass, like the coastlines.

    Returns the bbox for the post-pass.
    """
    rng = random.Random(seed)
    n_pts = 8
    pts: list[tuple[int, int]] = []
    for i in range(n_pts):
        angle = (i / n_pts) * 2 * math.pi
        # Wobble 0.7..1.3, gentler than the coastline, so islands read as
        # compact landmasses rather than straggly archipelagos.
        wobble = 0.7 + rng.random() * 0.6
        x = cx + round(scale_w * wobble * math.cos(angle))
        y = cy + round(scale_h * wobble * math.sin(angle))
        pts.append((x, y))
    draw.polygon(pts, fill=ink_sentinel)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1)


def _draw_cartograph_compass_rose(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    ink_sentinel,
) -> tuple[int, int, int, int]:
    """Paint an 8-point compass rose centred on ``(cx, cy)``.

    Four long cardinal triangles (32 px) and four shorter ordinals (18 px)
    fan from a small pivot circle, all in ``ink_sentinel`` for the caller's
    post-pass (in cartograph, R+Y 5/8:3/8 tangerine, a warm vermilion on
    the cream ground).

    Returns ``(x0, y0, x1, y1)``, padded 2 px so no sentinel pixel falls
    outside the caller's iteration window.
    """
    cardinal_len = 32
    ordinal_len = 18
    # Cardinals first, then ordinals. ``base_half`` is the half-width of
    # each triangle's base: 5 px cardinals dominate, 3 px ordinals keep
    # the 8-point rose silhouette rather than an even star.
    spikes = (
        (0, cardinal_len, 5),    # N
        (90, cardinal_len, 5),   # E
        (180, cardinal_len, 5),  # S
        (270, cardinal_len, 5),  # W
        (45, ordinal_len, 3),    # NE
        (135, ordinal_len, 3),   # SE
        (225, ordinal_len, 3),   # SW
        (315, ordinal_len, 3),   # NW
    )
    for angle_deg, length, base_half in spikes:
        angle = math.radians(angle_deg)
        # Tip: 0° is north, clockwise in screen space.
        tx = cx + round(length * math.sin(angle))
        ty = cy - round(length * math.cos(angle))
        # Base corners perpendicular to the spike axis.
        perp = math.radians(angle_deg + 90)
        bx0 = cx + round(base_half * math.sin(perp))
        by0 = cy - round(base_half * math.cos(perp))
        bx1 = cx - round(base_half * math.sin(perp))
        by1 = cy + round(base_half * math.cos(perp))
        draw.polygon([(tx, ty), (bx0, by0), (bx1, by1)], fill=ink_sentinel)
    # Centre pivot, same ink.
    draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=ink_sentinel)
    pad = 2
    return (cx - cardinal_len - pad, cy - cardinal_len - pad,
            cx + cardinal_len + pad, cy + cardinal_len + pad)


def _draw_cartograph_sea_serpent(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    ink,
) -> None:
    """Paint a small "here be dragons" sea serpent (~50 × 12 px).

    Solid ``ink``, no post-pass: engraved margin doodles had no halftone.
    A small triangular head at the left and three humps tapering to a
    tail; fewer humps read as a wave, more as a centipede.
    """
    # Wavy polyline through three humps.
    pts = [
        (cx - 24, cy + 4),
        (cx - 19, cy - 2),
        (cx - 14, cy + 4),
        (cx - 8, cy - 4),
        (cx - 2, cy + 4),
        (cx + 4, cy - 5),
        (cx + 10, cy + 4),
        (cx + 18, cy + 2),
    ]
    for i in range(len(pts) - 1):
        draw.line((pts[i], pts[i + 1]), fill=ink, width=2)
    # Head: a small filled triangle at the left end, an open snout.
    head_pts = [
        (cx - 24, cy + 4),
        (cx - 30, cy + 2),
        (cx - 28, cy + 7),
    ]
    draw.polygon(head_pts, fill=ink)


def _point_in_polygon(x: float, y: float, poly: list[tuple[int, int]]) -> bool:
    """Even-odd ray-cast point-in-polygon test (treats ``poly`` as closed)."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            x_cross = xi + (y - yi) * (xj - xi) / (yj - yi) if yj != yi else xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside


def _draw_cartograph_contours(
    draw: ImageDraw.ImageDraw,
    land_poly: list[tuple[int, int]],
    bbox: tuple[int, int, int, int],
    ink,
    seed: int,
) -> None:
    """Trace topographic contours over a synthetic height field, clipped
    to ``land_poly``, the way a chart hatches terrain relief.

    A few seeded Gaussian hills and basins are summed over the land's bbox
    and marching squares traces each of several elevation thresholds,
    giving nested multi-peak contours rather than shrunken copies of the
    coastline. Cells whose centre is off the land polygon are skipped.
    """
    x0, y0, x1, y1 = bbox
    x0 = max(0, int(x0))
    y0 = max(0, int(y0))
    x1 = int(x1)
    y1 = int(y1)
    w = x1 - x0
    h = y1 - y0
    if w < 8 or h < 8:
        return

    rng = random.Random(seed)
    # 3–4 Gaussian features (hills positive, basins negative). Spread
    # scales with the land size so contour spacing looks consistent.
    span = max(w, h)
    n_features = rng.randint(3, 4)
    features = []
    for _ in range(n_features):
        fx = x0 + rng.uniform(0.15, 0.85) * w
        fy = y0 + rng.uniform(0.15, 0.85) * h
        amp = rng.uniform(0.6, 1.0) * (1 if rng.random() < 0.65 else -1)
        sigma = rng.uniform(0.18, 0.34) * span
        features.append((fx, fy, amp, 2.0 * sigma * sigma))

    def height(px: float, py: float) -> float:
        total = 0.0
        for fx, fy, amp, two_sig_sq in features:
            dx = px - fx
            dy = py - fy
            total += amp * math.exp(-(dx * dx + dy * dy) / two_sig_sq)
        return total

    # Sample on a ~5 px grid: smooth enough, cheap enough in pure Python.
    step = 5
    gx = list(range(x0, x1 + step, step))
    gy = list(range(y0, y1 + step, step))
    grid = [[height(px, py) for px in gx] for py in gy]
    lo = min(min(row) for row in grid)
    hi = max(max(row) for row in grid)
    if hi - lo < 1e-6:
        return
    # Six iso-levels across the range, skipping the extremes (they'd trace
    # specks at the very peaks / pits).
    levels = [lo + (hi - lo) * f for f in (0.18, 0.32, 0.46, 0.60, 0.74, 0.88)]

    def interp(pa, va, pb, vb, lvl):
        # Linear crossing point between grid nodes pa (val va) and pb (vb).
        if abs(vb - va) < 1e-9:
            return pa
        t = (lvl - va) / (vb - va)
        return (pa[0] + (pb[0] - pa[0]) * t, pa[1] + (pb[1] - pa[1]) * t)

    for lvl in levels:
        for iy in range(len(gy) - 1):
            for ix in range(len(gx) - 1):
                # Cell corners (TL, TR, BR, BL) with field values.
                tlp = (gx[ix], gy[iy])
                tlv = grid[iy][ix]
                trp = (gx[ix + 1], gy[iy])
                trv = grid[iy][ix + 1]
                brp = (gx[ix + 1], gy[iy + 1])
                brv = grid[iy + 1][ix + 1]
                blp = (gx[ix], gy[iy + 1])
                blv = grid[iy + 1][ix]
                # Skip cells whose centre isn't on land.
                ccx = (gx[ix] + gx[ix + 1]) / 2.0
                ccy = (gy[iy] + gy[iy + 1]) / 2.0
                if not _point_in_polygon(ccx, ccy, land_poly):
                    continue
                code = (
                    (1 if tlv > lvl else 0)
                    | (2 if trv > lvl else 0)
                    | (4 if brv > lvl else 0)
                    | (8 if blv > lvl else 0)
                )
                if code == 0 or code == 15:
                    continue
                # Crossing points on each edge (top, right, bottom, left).
                top = interp(tlp, tlv, trp, trv, lvl)
                right = interp(trp, trv, brp, brv, lvl)
                bottom = interp(blp, blv, brp, brv, lvl)
                left = interp(tlp, tlv, blp, blv, lvl)
                # Marching-squares segment table (ambiguous saddles 5/10
                # split into two segments).
                segs = {
                    1: [(left, top)], 2: [(top, right)], 3: [(left, right)],
                    4: [(right, bottom)], 5: [(left, top), (right, bottom)],
                    6: [(top, bottom)], 7: [(left, bottom)], 8: [(left, bottom)],
                    9: [(top, bottom)], 10: [(left, bottom), (top, right)],
                    11: [(right, bottom)], 12: [(left, right)], 13: [(top, right)],
                    14: [(left, top)],
                }.get(code, [])
                for a, b in segs:
                    draw.line(
                        (round(a[0]), round(a[1]), round(b[0]), round(b[1])),
                        fill=ink, width=1,
                    )


def _draw_cartograph_coastline(
    draw: ImageDraw.ImageDraw,
    corner: tuple[int, int],
    extent: tuple[int, int],
    ink_sentinel,
    seed: int,
) -> tuple[int, int, int, int]:
    """Paint an irregular coastline as a filled polygon anchored at
    ``corner`` and extending toward ``extent``.

    ``corner`` is the canvas corner the land sits in (e.g. ``(0, 0)``);
    ``extent`` is the far point it sweeps toward (e.g. ``(180, 100)``).
    The shoreline is a 26-point seeded polyline closed back along the
    corner edges, with interior contour lines from
    ``_draw_cartograph_contours``.

    Painted in ``ink_sentinel`` for the caller's R+G sepia post-pass (the
    aged-ink recipe of ``newsprint`` / ``saloon`` / ``placard``).

    Returns ``(x0, y0, x1, y1)``, the bbox for the post-pass.
    """
    rng = random.Random(seed)
    corner_x, corner_y = corner
    extent_x, extent_y = extent
    # Direction signs, so the wobble pushes toward the corner's outside
    # (away from the body).
    sign_x = 1 if extent_x >= corner_x else -1
    sign_y = 1 if extent_y >= corner_y else -1
    n_pts = 26
    pts: list[tuple[int, int]] = []
    # Two-octave wobble: a slow swell carves broad bays and headlands, a
    # fast jitter adds the nibble of an engraved shoreline. A single
    # octave reads as a straight hypotenuse (a triangle, not land).
    slow_phase = rng.random() * math.tau
    slow_freq = 2.0 + rng.random() * 1.5
    for i in range(1, n_pts + 1):
        t = i / n_pts
        # Base position along the diagonal; the power curve flattens the
        # middle so the coast isn't a straight diagonal.
        bx = corner_x + round((extent_x - corner_x) * t)
        by = corner_y + round((extent_y - corner_y) * (1.0 - (1.0 - t) ** 1.8))
        # Swell + jitter, both toward the corner's outside, so the ragged
        # edge faces the open sea.
        swell = math.sin(slow_phase + t * slow_freq * math.tau)
        wobble_x = round((swell * 22 + (rng.random() - 0.5) * 26)) * sign_x
        wobble_y = round((swell * 18 + (rng.random() - 0.5) * 20)) * sign_y
        pts.append((bx + wobble_x, by + wobble_y))
    # Close back along the corner edges (y-axis edge first) so the polygon
    # hugs the corner.
    pts.insert(0, (corner_x, extent_y))
    pts.append((extent_x, corner_y))
    pts.append((corner_x, corner_y))
    draw.polygon(pts, fill=ink_sentinel)

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    bbox = (min(xs) - 1, min(ys) - 1, max(xs) + 1, max(ys) + 1)

    # Interior contour lines (marching squares over a synthetic height
    # field). Offset copies of the coastline bunch into a band and leave the
    # interior flat. Drawn in black, not the red sentinel, so the sepia
    # post-pass leaves them as crisp relief lines.
    _draw_cartograph_contours(draw, pts, bbox, SPECTRA6["black"], seed ^ 0x5EA1)

    return bbox


def draw_cartograph_border(
    image: Image.Image,
    colors: dict,
    clear_rect: tuple[int, int, int, int] | None = None,
) -> None:
    """Paint a hand-drawn antique cartographer's chart frame.

    Eleven layers, painted in Z-order:

    * **Layer 0 — cream Y+W Bayer wash.** Sparse 1-in-16 yellow
      stipple over every ``page_bg`` pixel, warming the flat white to
      vellum.
    * **Layer 1 — sepia graticule.** Dotted R/G meridians and parallels
      every 80 px (period-3 density) plus 3-px degree ticks at the
      frame; the strongest "this is a chart" cue.
    * **Layer 2 — sepia rhumb lines.** Eight rays at 45° from the
      compass-rose centre, at period-2 density so they read as a focal
      feature over the graticule.
    * **Layer 3 — sepia foxing.** ~120 seeded single-pixel dots, R or G
      by parity, which the eye averages to rust-brown.
    * **Layer 4 — two corner coastlines** (TL, BR) in R+G sepia via the
      sentinel-then-bbox-post-pass pattern. Seeded so the same chart
      recurs at every render.
    * **Layer 5 — three islands** (:data:`_CARTOGRAPH_ISLANDS`), same
      recipe.
    * **Layer 6 — compass rose** (bottom-left) in R+Y 5/8:3/8 tangerine,
      painted after the rhumb lines so it sits on top of them.
    * **Layer 7 — sea-serpent doodle** in solid black, as period margin
      doodles were inked.
    * **Layer 8 — three Latin place names** in IM Fell italic, R+G
      sepia (:data:`_CARTOGRAPH_PLACE_NAMES`); falls back through
      ``META_FONT_CANDIDATES``.
    * **Layer 9 — cartouche knockout.** With ``clear_rect``: a rounded
      white card, a fresh cream wash, a thin red outer rule and a thin
      black inner rule, erasing the map under the body text.
    * **Layer 10 — registration crosses** at the four inner-rule
      corners.

    When ``clear_rect`` is None (direct calls, ``render_static_message``,
    ``render_source_card``) Layers 9 and 10 are skipped; the map layers
    still paint.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    page_bg = colors.get("page_bg")
    cream_light = SPECTRA6["yellow"]
    red_ink = SPECTRA6["red"]
    green_ink = SPECTRA6["green"]
    yellow_ink = SPECTRA6["yellow"]
    black_ink = SPECTRA6["black"]
    white_ink = SPECTRA6["white"]

    pixels = image.load()

    # ------------------------------------------------------------------
    # Layer 0 — cream Y+W Bayer wash on page_bg pixels. Threshold < 1
    # = ~6.25% yellow, half the density ``illuminated`` / ``dispatch``
    # use, because the foxing layer (Layer 3) adds more warmth on top and
    # a denser ground would compete with the body text.
    if page_bg is not None:
        for y in range(height):
            row = BAYER_4x4[y & 3]
            for x in range(width):
                if pixels[x, y] == page_bg and row[x & 3] < 1:
                    pixels[x, y] = cream_light

    # ------------------------------------------------------------------
    # Layer 1 — sepia graticule, painted only over ground pixels so it
    # lies under everything painted later.
    _draw_cartograph_graticule(
        pixels, width, height,
        ground_white=white_ink, ground_cream=cream_light,
        red_ink=red_ink, green_ink=green_ink,
    )

    # ------------------------------------------------------------------
    # Layer 2 — sepia rhumb lines from the compass-rose centre, denser
    # than the graticule (every other pixel vs every third).
    rose_cx = 72
    rose_cy = height - 80
    _draw_cartograph_rhumb_lines(
        pixels, width, height, rose_cx, rose_cy,
        ground_white=white_ink, ground_cream=cream_light,
        red_ink=red_ink, green_ink=green_ink,
    )

    # ------------------------------------------------------------------
    # Layer 3 — sepia foxing scatter at seeded positions.
    if page_bg is not None:
        rng = random.Random(_CARTOGRAPH_FOXING_SEED)
        n_dots = 120
        for _ in range(n_dots):
            fx = rng.randint(2, width - 3)
            fy = rng.randint(2, height - 3)
            # Only paint over ground (cream or white), skipping graticule
            # and rhumb pixels.
            current = pixels[fx, fy]
            if current not in (cream_light, white_ink):
                continue
            # Parity picks R or G so neighbouring dots average to sepia.
            # Inverted vs. the coastline / island / label post-passes so
            # foxing reds survive them (see
            # ``_paint_cartograph_dotted_sepia_line``).
            pixels[fx, fy] = green_ink if (fx + fy) & 1 else red_ink

    # ------------------------------------------------------------------
    # Layer 4 — two diagonal-corner coastlines. Paint as red sentinel,
    # then post-pass to sepia (R+G) by flipping half the painted red
    # pixels to green per (x+y)&1 parity inside each bbox.
    tl_bbox = _draw_cartograph_coastline(
        draw,
        corner=(0, 0),
        extent=(round(width * 0.20), round(height * 0.18)),
        ink_sentinel=red_ink,
        seed=_CARTOGRAPH_COAST_TL_SEED,
    )
    br_bbox = _draw_cartograph_coastline(
        draw,
        corner=(width - 1, height - 1),
        extent=(round(width * 0.80), round(height * 0.82)),
        ink_sentinel=red_ink,
        seed=_CARTOGRAPH_COAST_BR_SEED,
    )
    # Post-pass: flip half the red pixels inside each bbox to green
    # for sepia.
    for bx0, by0, bx1, by1 in (tl_bbox, br_bbox):
        bx0 = max(0, bx0)
        by0 = max(0, by0)
        bx1 = min(width - 1, bx1)
        by1 = min(height - 1, by1)
        for py in range(by0, by1 + 1):
            for px in range(bx0, bx1 + 1):
                if pixels[px, py] == red_ink and (px + py) & 1:
                    pixels[px, py] = green_ink

    # ------------------------------------------------------------------
    # Layer 5 — three islands, red-sentinel polygons post-passed to R+G
    # sepia like the coastlines.
    island_bboxes: list[tuple[int, int, int, int]] = []
    for cx_frac, cy_frac, scale_w, scale_h, seed in _CARTOGRAPH_ISLANDS:
        island_cx = round(width * cx_frac)
        island_cy = round(height * cy_frac)
        island_bboxes.append(_draw_cartograph_island(
            draw, island_cx, island_cy, scale_w, scale_h, red_ink, seed,
        ))
    for bx0, by0, bx1, by1 in island_bboxes:
        bx0 = max(0, bx0)
        by0 = max(0, by0)
        bx1 = min(width - 1, bx1)
        by1 = min(height - 1, by1)
        for py in range(by0, by1 + 1):
            for px in range(bx0, bx1 + 1):
                if pixels[px, py] == red_ink and (px + py) & 1:
                    pixels[px, py] = green_ink

    # ------------------------------------------------------------------
    # Layer 6 — compass rose, centred on the rhumb-line origin so the
    # rays read as emanating from it, and painted on top of them.
    rose_bbox = _draw_cartograph_compass_rose(draw, rose_cx, rose_cy, ink_sentinel=red_ink)
    # Tangerine post-pass: flip red to yellow where ``BAYER_4x4 < 6`` (R+Y
    # 5/8:3/8). Bounded to the rose bbox so the other red sentinels are
    # untouched.
    bx0, by0, bx1, by1 = rose_bbox
    bx0 = max(0, bx0)
    by0 = max(0, by0)
    bx1 = min(width - 1, bx1)
    by1 = min(height - 1, by1)
    for py in range(by0, by1 + 1):
        row = BAYER_4x4[py & 3]
        for px in range(bx0, bx1 + 1):
            if pixels[px, py] == red_ink and row[px & 3] < 6:
                pixels[px, py] = yellow_ink

    # ------------------------------------------------------------------
    # Layer 7 — sea-serpent doodle in the bottom-mid sea, between the
    # "Terra Nova" label and the BR coastline. That ~50x20 px zone stays
    # clear of the cartouche on every layout; the right margin does not
    # (the dense cartouche leaves only ~37 px there).
    _draw_cartograph_sea_serpent(draw, round(width * 0.69), round(height * 0.84), ink=black_ink)

    # ------------------------------------------------------------------
    # Layer 8 — three Latin place names, red sentinel post-passed to
    # sepia like the coastlines.
    label_font_candidates = [
        IMFELLENGLISH_ITALIC,
        IMFELLENGLISH_REGULAR,
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
        *META_FONT_CANDIDATES,
    ]
    label_font = load_font(label_font_candidates, size=15)
    for label_text, cx_frac, cy_frac in _CARTOGRAPH_PLACE_NAMES:
        lx = round(width * cx_frac)
        ly = round(height * cy_frac)
        bbox = draw.textbbox((lx, ly), label_text, font=label_font)
        # Centre the label on (lx, ly).
        draw_x = lx - (bbox[2] - bbox[0]) // 2
        draw_y = ly - (bbox[3] - bbox[1]) // 2
        draw.text((draw_x, draw_y), label_text, font=label_font, fill=red_ink)
        # Post-pass to R+G sepia; the 1 px pad catches hinting jitter
        # outside the text bbox.
        lbbox = draw.textbbox((draw_x, draw_y), label_text, font=label_font)
        lx0 = max(0, lbbox[0] - 1)
        ly0 = max(0, lbbox[1] - 1)
        lx1 = min(width - 1, lbbox[2] + 1)
        ly1 = min(height - 1, lbbox[3] + 1)
        for py in range(ly0, ly1 + 1):
            for px in range(lx0, lx1 + 1):
                if pixels[px, py] == red_ink and (px + py) & 1:
                    pixels[px, py] = green_ink

    # ------------------------------------------------------------------
    # Layers 9 & 10 — cartouche knockout + registration corners. Only
    # paint when render() threaded clear_rect through.
    if clear_rect is None or page_bg is None:
        return
    cx0, cy0, cx1, cy1 = clear_rect
    cx0 = max(0, cx0)
    cy0 = max(0, cy0)
    cx1 = min(width - 1, cx1)
    cy1 = min(height - 1, cy1)
    # Skip the knockout if the clamped rect collapsed.
    if cx1 <= cx0 or cy1 <= cy0:
        return

    # Rounded white fill; radius 10 reads as a paper card without going
    # soft against the angular coastlines.
    cartouche_radius = 10
    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=cartouche_radius, fill=white_ink)
    # Fresh cream wash inside the knockout (same recipe as Layer 0).
    for py in range(cy0, cy1 + 1):
        row = BAYER_4x4[py & 3]
        for px in range(cx0, cx1 + 1):
            if pixels[px, py] == white_ink and row[px & 3] < 1:
                pixels[px, py] = cream_light

    # Doubled rule: thin red outer, thin black inner 3 px in.
    draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=cartouche_radius, outline=red_ink, width=1)
    inner_inset = 3
    if cx1 - cx0 > inner_inset * 2 and cy1 - cy0 > inner_inset * 2:
        draw.rounded_rectangle(
            (cx0 + inner_inset, cy0 + inner_inset, cx1 - inner_inset, cy1 - inner_inset),
            radius=max(2, cartouche_radius - inner_inset),
            outline=black_ink,
            width=1,
        )

    # Layer 10 — registration crosses (3 px arms) at the inner-rule
    # corners.
    tick_arm = 3
    tick_inset = inner_inset + 6  # past the inner rule + small breathing
    for tcx, tcy in (
        (cx0 + tick_inset, cy0 + tick_inset),
        (cx1 - tick_inset, cy0 + tick_inset),
        (cx0 + tick_inset, cy1 - tick_inset),
        (cx1 - tick_inset, cy1 - tick_inset),
    ):
        draw.line((tcx - tick_arm, tcy, tcx + tick_arm, tcy), fill=black_ink, width=1)
        draw.line((tcx, tcy - tick_arm, tcx, tcy + tick_arm), fill=black_ink, width=1)
