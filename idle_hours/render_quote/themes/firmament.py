"""The ``firmament`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw, ImageFont

from .._paths import CARDO_BOLD, CARDO_ITALIC
from ..fonts import FontType
from ..palette import SPECTRA6, BAYER_4x4, pixel_access
from ..spec import BorderSpec

# Seed for the deterministic firmament star scatter (see
# ``_build_firmament_stars``). Stars stay in the top margin (y 4-64) and
# the bottom margin (y height-64 to height-4), clear of the body text
# (block_top ≥ 72) and the attribution.
_FIRMAMENT_STAR_SEED = 0xF18


def _build_firmament_stars(width: int, height: int) -> list[tuple[int, int, int]]:
    """Return 150 deterministic (x, y, magnitude) stars in the top and
    bottom decoration margins. Magnitude 1 = brightest (8-point sparkle),
    2 = 4-point cross, 3 = 2x2 cluster, 4 = single pixel. Reseeded per call,
    so any canvas size gives a stable scatter.
    """
    rng = random.Random(_FIRMAMENT_STAR_SEED)
    stars: list[tuple[int, int, int]] = []
    side_margin = 20

    def _add(count: int, magnitude: int) -> None:
        for _ in range(count):
            x = rng.randint(side_margin, width - side_margin - 1)
            # Top or bottom margin band (each ~60 px tall), 50/50.
            if rng.random() < 0.5:
                y = rng.randint(4, 64)
            else:
                y = rng.randint(height - 64, height - 4)
            stars.append((x, y, magnitude))

    _add(80, 4)   # very faint pinprick stars
    _add(40, 3)   # faint 2x2 clusters
    _add(20, 2)   # medium 4-point crosses
    _add(10, 1)   # bright 8-point sparkles
    return stars


def _paint_firmament_star(pixels, width: int, height: int, sx: int, sy: int, magnitude: int) -> None:
    """Paint one yellow star at (sx, sy). Magnitude sets the shape:

    * mag 4: single pixel
    * mag 3: 2×2 cluster
    * mag 2: 4-point cross with 2px arms + a centre dot
    * mag 1: 8-point sparkle, long N/S/E/W rays tapering from 3px to 1px
      plus shorter diagonals, like the bright stars of 17th-century
      celestial atlases.
    """
    yellow = SPECTRA6["yellow"]

    def _set(ax: int, ay: int) -> None:
        if 0 <= ax < width and 0 <= ay < height:
            pixels[ax, ay] = yellow

    if magnitude >= 4:
        _set(sx, sy)
    elif magnitude == 3:
        for dy in (0, 1):
            for dx in (0, 1):
                _set(sx + dx, sy + dy)
    elif magnitude == 2:
        # 4-point cross: a 2x2 core with one-pixel arms.
        for dy in (0, 1):
            for dx in (0, 1):
                _set(sx + dx, sy + dy)
        _set(sx + 2, sy)
        _set(sx + 2, sy + 1)
        _set(sx - 1, sy)
        _set(sx - 1, sy + 1)
        _set(sx, sy + 2)
        _set(sx + 1, sy + 2)
        _set(sx, sy - 1)
        _set(sx + 1, sy - 1)
    else:
        # Magnitude 1: 8-point sparkle. 3x3 core, 1 px cardinal rays to
        # 5 px, 2 px diagonal stubs.
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                _set(sx + dx, sy + dy)
        # Long cardinal rays, 1 px wide past the core.
        for offset in range(2, 6):
            _set(sx, sy - offset)  # N
            _set(sx, sy + offset)  # S
            _set(sx - offset, sy)  # W
            _set(sx + offset, sy)  # E
        # Inter-cardinal sparkle accents (2px diagonal stubs).
        for offset in (2, 3):
            _set(sx - offset, sy - offset)  # NW
            _set(sx + offset, sy - offset)  # NE
            _set(sx - offset, sy + offset)  # SW
            _set(sx + offset, sy + offset)  # SE


def draw_firmament_border(image: Image.Image, colors: dict) -> None:
    """Paint a 17th-century celestial-atlas frame around the quote.

    Layers, in Z-order:

    * **Layer 0: navy ground.** ``page_bg`` is black; half of it flips to
      blue on ``(x + y) & 1`` (B+K navy). Idempotent: the second
      ``_paint_theme_border`` call after the text finds no ``page_bg``
      pixels left to flip (the shape ``mucha`` / ``fillmore`` / ``atomic``
      use).
    * **Layer 1: Milky Way.** Two irregular rotated blobs (top, right of
      centre; bottom, left of centre) filled with a dense scatter of
      yellow pin-stars and sparse red / blue "nebular dust", thinning
      toward the rim; everything else reverts to the navy ground.
    * **Layer 2: star field** from ``_build_firmament_stars``, confined to
      the top and bottom margins.
    * **Layer 3: constellations**: Cassiopeia (TL), Orion's Belt (BR),
      Lyra with Vega (TR) and Crux (BL), joined by 1 px white lines and
      labelled in small Cardo italic.
    * **Layer 4: corner ornaments**: a yellow sun with a carved face (TL),
      a sky-blue (B+W) crescent moon with craters (TR, centre y=50, below
      the y=14-29 debug band, so no ``_DEBUG_LABEL_RIGHT_INSET`` entry), a
      white portolan compass rose with a yellow pivot and "N" (BL), and
      a tangerine Saturn with an equatorial band and two cyan (G+B)
      rings (BR).
    * **Layer 4b: Roman-numeral hour markers** XII / III / VI / IX at the
      page's cardinal edges, an astrolabe rim.
    * **Layer 5: ecliptic arc**: a shallow sky-blue arc across the top
      margin.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    page_bg = colors.get("page_bg")
    pixels = pixel_access(image)

    blue_ink = SPECTRA6["blue"]
    white_ink = SPECTRA6["white"]
    yellow_ink = SPECTRA6["yellow"]
    red_ink = SPECTRA6["red"]
    green_ink = SPECTRA6["green"]
    black_ink = SPECTRA6["black"]
    # Off-palette sentinels, one per ornament, so each post-pass filters
    # on its own sentinel. Don't use SPECTRA6["blue"]: Layer 0 makes half
    # the ground blue, and the post-pass would stipple all of it inside
    # the ornament's bbox.
    milky_sentinel = (2, 2, 2)
    moon_sentinel = (3, 3, 3)
    arc_sentinel = (4, 4, 4)

    # ---- Layer 0: Navy ground wash (B+K 1:1 via (x+y)&1 parity) ----
    if page_bg is not None:
        for y in range(height):
            for x in range(width):
                if pixels[x, y] == page_bg and (x + y) & 1:
                    pixels[x, y] = blue_ink

    # ---- Layer 1: Milky Way (dense star scatter inside two flowing blobs) ----
    # The Milky Way is a dense star field, so it is drawn as one: two
    # irregular blob silhouettes (not rectangles) painted in a sentinel,
    # then each sentinel pixel is resolved by a per-position hash
    # (reproducible without threading RNG state). Density falls off with
    # distance from the blob centre, so the cloud feathers into the navy:
    #   * yellow pin-star (bucket < 3, survives to the rim)
    #   * red / blue specks: warm / cool nebular dust
    #   * everything else reverts to the Layer 0 navy ground

    blob_rng = random.Random(_FIRMAMENT_STAR_SEED ^ 0x42)

    def _build_blob(cx: float, cy: float, base_r: float, aspect: float = 1.0,
                    angle: float = 0.0) -> tuple[list[tuple[float, float]], float, float, float, float]:
        n = 32
        points = []
        ca, sa = math.cos(angle), math.sin(angle)
        for i in range(n):
            t = 2.0 * math.pi * i / n
            # Per-vertex radial wobble (two random factors, ~0.55-1.20 ×
            # base_r) so the silhouette reads organic, not geometric.
            r = base_r * (0.65 + 0.40 * blob_rng.random()) * (
                0.85 + 0.30 * blob_rng.random()
            )
            # Build along the blob's own (long, short) axes, then rotate by
            # ``angle`` so the band lies on a diagonal like the Milky Way's
            # arm in classical atlases.
            lx = r * math.cos(t) * aspect
            ly = r * math.sin(t)
            points.append((cx + lx * ca - ly * sa, cy + lx * sa + ly * ca))
        # Also return the centre and axes, so the scatter can compute a
        # radial density falloff in the blob's own space.
        return points, cx, cy, base_r * aspect, base_r

    # Top blob: a shallow diagonal band tilted down-right, between
    # Cassiopeia (TL) and Lyra (TR), below the ecliptic arc.
    top_blob = _build_blob(width / 2 + 30, 52, 34, aspect=2.2, angle=0.18)
    # Bottom blob, tilted the opposite way.
    bottom_blob = _build_blob(width / 2 - 60, height - 30, 30, aspect=2.4, angle=-0.20)

    for poly, bcx, bcy, blob_rx, blob_ry in (top_blob, bottom_blob):
        draw.polygon(poly, fill=milky_sentinel)
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        x0, x1 = max(0, int(min(xs))), min(width, int(max(xs)) + 1)
        y0, y1 = max(0, int(min(ys))), min(height, int(max(ys)) + 1)
        inv_rx = 1.0 / max(1.0, blob_rx)
        inv_ry = 1.0 / max(1.0, blob_ry)
        for y in range(y0, y1):
            for x in range(x0, x1):
                if pixels[x, y] != milky_sentinel:
                    continue
                # ``edge`` is the normalised radial distance (0 at the
                # centre, ~1 at the silhouette); fewer hash buckets keep
                # paint as it grows.
                ndx = (x - bcx) * inv_rx
                ndy = (y - bcy) * inv_ry
                edge = ndx * ndx + ndy * ndy
                star_hash = (x * 73856093) ^ (y * 19349663)
                bucket = star_hash % 120
                # Core (edge<0.35) keeps ~9%, mid ~5%, rim (edge>0.85) only
                # the 1/40 pin-stars.
                if edge < 0.35:
                    keep = bucket < 11
                elif edge < 0.85:
                    keep = bucket < 6
                else:
                    keep = bucket < 3
                if not keep:
                    pixels[x, y] = blue_ink if (x + y) & 1 else black_ink
                elif bucket < 3:
                    pixels[x, y] = yellow_ink   # pin-star (survives to the rim)
                elif bucket < 7:
                    pixels[x, y] = red_ink      # warm nebular dust
                else:
                    pixels[x, y] = blue_ink     # cool nebular dust

    # ---- Layer 2: Star field ----
    for sx, sy, mag in _build_firmament_stars(width, height):
        _paint_firmament_star(pixels, width, height, sx, sy, mag)

    # ---- Layer 3: Constellation polylines + Latin labels ----
    # Cardo Italic for the constellation names, as on 17th-century atlas
    # labels; the bitmap default is the fallback if the font is missing.
    try:
        label_font: FontType = ImageFont.truetype(CARDO_ITALIC, 11)
    except OSError:
        label_font = ImageFont.load_default()

    # Cassiopeia — W shape, top-left margin. Five canonical stars.
    cassiopeia = [(60, 34), (95, 50), (130, 28), (165, 50), (200, 36)]
    for cx, cy in cassiopeia:
        _paint_firmament_star(pixels, width, height, cx, cy, magnitude=1)
    draw.line(cassiopeia, fill=white_ink, width=1)
    # Latin label below the W, white italic.
    draw.text((90, 60), "CASSIOPEIA", font=label_font, fill=white_ink)

    # Orion's Belt — three stars in a tilted line, bottom-right margin.
    orion_belt = [
        (width - 220, height - 30),
        (width - 160, height - 36),
        (width - 100, height - 42),
    ]
    for cx, cy in orion_belt:
        _paint_firmament_star(pixels, width, height, cx, cy, magnitude=1)
    draw.line(orion_belt, fill=white_ink, width=1)
    draw.text((width - 196, height - 18), "ORION", font=label_font, fill=white_ink)

    # Lyra: a small parallelogram in the top-right margin, between the
    # Milky Way and the moon. The first vertex is Vega.
    lyra = [
        (width - 280, 28),
        (width - 240, 18),
        (width - 220, 42),
        (width - 268, 52),
    ]
    for cx, cy in lyra:
        _paint_firmament_star(pixels, width, height, cx, cy, magnitude=2)
    # Vega — promote the first vertex to a brighter sparkle.
    _paint_firmament_star(pixels, width, height, lyra[0][0], lyra[0][1], magnitude=1)
    # Close the parallelogram (4 segments).
    lyra_closed = lyra + [lyra[0]]
    draw.line(lyra_closed, fill=white_ink, width=1)
    draw.text((width - 280, 60), "LYRA", font=label_font, fill=white_ink)

    # Crux (Southern Cross): four stars in a cross, bottom-left margin,
    # between the compass rose and the body.
    crux = [
        (200, height - 56),   # top
        (216, height - 42),   # right
        (200, height - 28),   # bottom
        (184, height - 42),   # left
    ]
    _paint_firmament_star(pixels, width, height, crux[0][0], crux[0][1], magnitude=1)
    for cx, cy in crux[1:]:
        _paint_firmament_star(pixels, width, height, cx, cy, magnitude=2)
    # Two crossing lines.
    draw.line((crux[0], crux[2]), fill=white_ink, width=1)
    draw.line((crux[1], crux[3]), fill=white_ink, width=1)
    draw.text((132, height - 18), "CRUX AUSTRALIS", font=label_font, fill=white_ink)

    # ---- Layer 4: Four corner astronomy ornaments ----

    # TL Sun: a filled yellow disc with 16 rays every 22.5° alternating long
    # and short, and an implied face (two eyes and a smile) carved in the
    # navy ground's own (x+y)&1 pattern, so it reads as relief. Solid
    # yellow, no post-pass.
    sun_cx, sun_cy = 36, 36
    sun_r = 11
    draw.ellipse(
        (sun_cx - sun_r, sun_cy - sun_r, sun_cx + sun_r, sun_cy + sun_r),
        fill=yellow_ink,
    )
    # Rays alternate long / short. An even count keeps the alternation
    # unbroken all the way round (issue #342).
    for i in range(16):
        angle = math.radians(i * 22.5)
        is_long = i % 2 == 0
        ray_inner = sun_r + (1 if is_long else 3)
        ray_outer = sun_r + (12 if is_long else 6)
        rx1 = sun_cx + ray_inner * math.cos(angle)
        ry1 = sun_cy + ray_inner * math.sin(angle)
        rx2 = sun_cx + ray_outer * math.cos(angle)
        ry2 = sun_cy + ray_outer * math.sin(angle)
        draw.line((rx1, ry1, rx2, ry2), fill=yellow_ink, width=1)
    # Face: two eye dots at cy-2 and a 5 px smile at cy+3, in the navy
    # ground stipple.
    for ex in (sun_cx - 3, sun_cx + 3):
        pixels[ex, sun_cy - 2] = blue_ink if (ex + sun_cy - 2) & 1 else black_ink
    # Smile.
    for dx in (-2, -1, 0, 1, 2):
        sy = sun_cy + 3 + (1 if abs(dx) >= 2 else 0)
        pixels[sun_cx + dx, sy] = blue_ink if (sun_cx + dx + sy) & 1 else black_ink

    # TR crescent moon: a sentinel disc carved by a page_bg disc offset
    # left, post-passed to sky-blue (B+W 1:1), with two crater dots.
    moon_cx, moon_cy = width - 36, 50
    moon_r = 13
    draw.ellipse(
        (moon_cx - moon_r, moon_cy - moon_r, moon_cx + moon_r, moon_cy + moon_r),
        fill=moon_sentinel,
    )
    # Carve the shadow.
    carve_r = 11
    carve_cx = moon_cx - 5
    draw.ellipse(
        (carve_cx - carve_r, moon_cy - carve_r, carve_cx + carve_r, moon_cy + carve_r),
        fill=page_bg if page_bg is not None else black_ink,
    )
    # Sky-blue post-pass, scoped to the moon bbox.
    mx0, mx1 = moon_cx - moon_r - 1, moon_cx + moon_r + 1
    my0, my1 = moon_cy - moon_r - 1, moon_cy + moon_r + 1
    for y in range(max(0, my0), min(height, my1 + 1)):
        for x in range(max(0, mx0), min(width, mx1 + 1)):
            if pixels[x, y] == moon_sentinel:
                pixels[x, y] = white_ink if (x + y) & 1 else blue_ink
    # Two craters: navy dots in the lit part.
    for cx_off, cy_off in ((4, -2), (6, 3)):
        ax, ay = moon_cx + cx_off, moon_cy + cy_off
        if 0 <= ax < width and 0 <= ay < height:
            pixels[ax, ay] = blue_ink if (ax + ay) & 1 else black_ink

    # BL compass rose (portolan wind rose): four large white cardinal
    # wedges, four small diagonal ones, a yellow pivot diamond and an "N"
    # above the north point.
    rose_cx, rose_cy = 40, height - 44
    long_r = 18
    short_r = 8
    side = 4  # half-width of the cardinal wedge at the base
    # Cardinal wedges: filled triangles from a narrow base to the tip.
    cardinals = [
        ((rose_cx, rose_cy - long_r), (rose_cx - side, rose_cy), (rose_cx + side, rose_cy)),   # N
        ((rose_cx + long_r, rose_cy), (rose_cx, rose_cy - side), (rose_cx, rose_cy + side)),   # E
        ((rose_cx, rose_cy + long_r), (rose_cx - side, rose_cy), (rose_cx + side, rose_cy)),   # S
        ((rose_cx - long_r, rose_cy), (rose_cx, rose_cy - side), (rose_cx, rose_cy + side)),   # W
    ]
    for triangle in cardinals:
        draw.polygon(triangle, fill=white_ink)
    # Diagonal points — thinner short wedges.
    diag_side = 2
    for angle_deg in (45, 135, 225, 315):
        angle = math.radians(angle_deg)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        # Perpendicular for the base width.
        perp_x, perp_y = -sin_a, cos_a
        tip = (rose_cx + short_r * cos_a, rose_cy + short_r * sin_a)
        base_a = (rose_cx + diag_side * perp_x, rose_cy + diag_side * perp_y)
        base_b = (rose_cx - diag_side * perp_x, rose_cy - diag_side * perp_y)
        draw.polygon((tip, base_a, base_b), fill=white_ink)
    # Inner filled yellow diamond (the "pivot").
    draw.polygon(
        ((rose_cx, rose_cy - 3), (rose_cx + 3, rose_cy),
         (rose_cx, rose_cy + 3), (rose_cx - 3, rose_cy)),
        fill=yellow_ink,
    )
    # "N" label above the north point.
    try:
        n_font: FontType = ImageFont.truetype(CARDO_BOLD, 11)
    except OSError:
        n_font = ImageFont.load_default()
    draw.text((rose_cx - 4, rose_cy - long_r - 13), "N", font=n_font, fill=yellow_ink)

    # BR Saturn: a red-sentinel disc (→ tangerine, R+Y 5/8:3/8) with a
    # black equatorial band, and two ring ellipses (outer + inner with a
    # 1 px Cassini division) as 96-point polylines tilted 18°, in a green
    # sentinel (→ cyan, G+B 1:1). The post-pass filters on each sentinel,
    # so disc and rings don't collide.
    saturn_cx, saturn_cy = width - 56, height - 48
    saturn_r = 11
    draw.ellipse(
        (saturn_cx - saturn_r, saturn_cy - saturn_r,
         saturn_cx + saturn_r, saturn_cy + saturn_r),
        fill=red_ink,
    )
    # Outer + inner ring, 1 px Cassini division between them.
    angle = math.radians(18)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    n_points = 96
    for ring_a, ring_b in ((22, 8), (19, 6)):
        ring_points = []
        for i in range(n_points + 1):
            t = 2.0 * math.pi * i / n_points
            xu = ring_a * math.cos(t)
            yu = ring_b * math.sin(t)
            ring_points.append((
                saturn_cx + xu * cos_a - yu * sin_a,
                saturn_cy + xu * sin_a + yu * cos_a,
            ))
        draw.line(ring_points, fill=green_ink, width=1)
    # Equatorial band: a black line drawn after the disc, matching
    # neither sentinel, so it survives the post-pass.
    band_y = saturn_cy + 1
    draw.line(
        (saturn_cx - saturn_r + 2, band_y, saturn_cx + saturn_r - 2, band_y),
        fill=black_ink, width=1,
    )
    # Saturn post-pass: two sentinel filters (red → tangerine, green →
    # cyan) in one corner bbox.
    sat_pad = 24
    sat_x0 = max(0, saturn_cx - sat_pad)
    sat_x1 = min(width, saturn_cx + sat_pad + 1)
    sat_y0 = max(0, saturn_cy - sat_pad)
    sat_y1 = min(height, saturn_cy + sat_pad + 1)
    for y in range(sat_y0, sat_y1):
        for x in range(sat_x0, sat_x1):
            px_val = pixels[x, y]
            if px_val == red_ink and BAYER_4x4[y & 3][x & 3] < 6:
                pixels[x, y] = yellow_ink
            elif px_val == green_ink and (x + y) & 1:
                pixels[x, y] = blue_ink

    # ---- Layer 4b: Roman-numeral hour markers ----
    # XII / III / VI / IX at the four cardinal page positions: an
    # astrolabe rim. Small Cardo italic at the canvas edges, clear of the
    # ornaments and the body.
    try:
        roman_font: FontType = ImageFont.truetype(CARDO_ITALIC, 12)
    except OSError:
        roman_font = ImageFont.load_default()
    # XII: top, left of the top Milky Way blob (centred at width/2 + 30).
    draw.text((width // 2 - 60, 4), "XII", font=roman_font, fill=white_ink)
    # VI: bottom, right of the bottom blob (centred at width/2 - 60).
    draw.text((width // 2 + 60, height - 16), "VI", font=roman_font, fill=white_ink)
    # III: right edge, at the vertical centre.
    draw.text((width - 16, height // 2 - 6), "III", font=roman_font, fill=white_ink)
    # IX — left edge, mirroring III.
    draw.text((4, height // 2 - 6), "IX", font=roman_font, fill=white_ink)

    # ---- Layer 5: Ecliptic arc ----
    # The upper half (180°–360°) of a wide ellipse in bbox
    # (40, 20)-(width-40, 140): peak at y=20, ends at y=80. Painted in an
    # off-palette sentinel so the post-pass can't touch Layer 0's blue.
    # The post-pass bbox comes from the arc's own geometry (down to the
    # ellipse's centre row, where the ends sit), so no sentinel pixel at
    # the ends survives to be snapped to black (issue #341).
    arc_bbox = (40, 20, width - 40, 140)
    draw.arc(arc_bbox, start=180, end=360, fill=arc_sentinel, width=1)
    ax0, ay0 = arc_bbox[0], arc_bbox[1]
    ax1, ay1 = arc_bbox[2], (arc_bbox[1] + arc_bbox[3]) // 2
    for y in range(max(0, ay0), min(height, ay1 + 1)):
        for x in range(max(0, ax0), min(width, ax1 + 1)):
            if pixels[x, y] == arc_sentinel:
                pixels[x, y] = white_ink if (x + y) & 1 else blue_ink


SPEC = BorderSpec(
    themes=("firmament",),
    paint=draw_firmament_border,
    # The look is the composite of two paints (issue #361).
    paints_twice=True,
)
