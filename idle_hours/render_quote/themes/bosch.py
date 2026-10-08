"""The ``bosch`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from .._paths import GRENZE_GOTISCH_VARIABLE, META_FONT_BOLD_CANDIDATES
from ..fonts import load_font, normalize_dashes, theme_font_candidates
from ..furniture import draw_centred_styled_lines, draw_truncated_centred_byline
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, gray_pixel_access, pixel_access, snap_image_to_palette
from ..primitives import paint_craquelure, paint_neon_mask, position_noise
from ..spec import FrameSpec

# ---------------------------------------------------------------------------
# bosch — Hieronymus Bosch, *The Garden of Earthly Delights* (c. 1490-1510)
# ---------------------------------------------------------------------------
# A custom frame: the triptych standing open. Paradise on the left wing
# (Fountain of Life, owl, dragon tree), the Garden across the centre (far lake
# and fountains, the giant fruit, the lovers' bubble) and Hell on the right
# (burning city, knife between two ears, Tree-Man, frozen lake). The quote is
# lettered on a **phylactery banderole** across the centre panel, in black
# textura with the matched phrase **rubricated**.
#
# **Craquelure** (``paint_craquelure``) is built as a graph, not a per-pixel
# field: a jittered lattice whose edges are wobbled polylines, some dropped, a
# few diagonals added. A crack net is a set of connected edges; thresholding
# noise gives disconnected specks. Cells are wider than tall because oak-panel
# cracks run across the vertical grain.
#
# **A crack changes polarity with the paint it crosses**: grime-filled and dark
# on a light passage, open to the white ground on a dark one. Hence the
# primitive's separate ``dark`` and ``light`` inks.
#
# **Cracks never cut a letter.** The banderole's text is drawn a second time
# into a dilated ``keep_out`` mask so a fissure stops short of every stroke.
# Fenced by ``TestBoschFrame``.
#
# **The wing tops are the centre arch, halved and mirrored**: closed, each wing
# covers half the centre, so opened its free edge (the arch's apex) ends up
# outermost. The wings are narrower than half the centre, so the half-arch is
# compressed, but the direction is the physical one.
#
# Colour mixes use a *single* jittered ``BAYER_8x8`` read per pixel,
# partitioned into as many inks as the passage needs (a second read is
# correlated with the first and slides the hue; unjittered, broad fields
# lattice). Flesh is light orange (W+R+Y) run white-major, ~68 : 16 : 16,
# because Bosch's nudes are a cool pallor, not a peach.
#
# **No clock surface beyond the phrase**: ``time_str`` is ``del``-asserted.
#
# Composed at 800x480 and NEAREST-downsampled (the ``metro`` convention).
# ---------------------------------------------------------------------------
_BOSCH_PANELS = (
    ("paradise", (14, 14, 172, 466)),
    ("garden", (182, 14, 618, 466)),
    ("hell", (628, 14, 786, 466)),
)
_BOSCH_ARCH_RISE = 30            # sagitta of the centre panel's segmental arch
_BOSCH_SCROLL_CENTRE = (400, 236)
_BOSCH_TEXT_MAX = (344, 214)     # widest / tallest the lettered block may grow
_BOSCH_SCROLL_PAD = (22, 16)
_BOSCH_SCROLL_MIN_W = 250
_BOSCH_SCROLL_WAVE = 3.0         # the banderole's flutter, px
_BOSCH_ROLL_W = 13               # rolled ends
_BOSCH_CREDIT_SIZE = 16
_BOSCH_CRACK_CELL = (30, 17)
_BOSCH_CRACK_SEED = 0xB05C
_BOSCH_JITTER = 9                # ± ranks of positional jitter on the 8x8 tile


_BOSCH_RANK_FIELD: tuple[bytes, ...] = ()


def _bosch_rank_field() -> tuple[bytes, ...]:
    """The 8x8 Bayer rank plus a seeded jitter, for the whole canvas, once.

    Ordered dither with its rank nudged by up to ``_BOSCH_JITTER``, the jitter
    from a seeded ``Random.randbytes`` field rather than a per-pixel
    ``position_noise`` call (the frame reads ~450k ranks per render). Seeded,
    so byte-identical across processes.

    **Clamped to 0..63**, so share 0 means no pixels and share 1 means all,
    which every ``_bosch_pick`` call assumes.

    Built into a local and published in one assignment, because curator-UI
    previews render on concurrent threads.
    """
    global _BOSCH_RANK_FIELD
    field = _BOSCH_RANK_FIELD
    if not field:
        noise = random.Random(_BOSCH_CRACK_SEED ^ 0x5A5A).randbytes(800 * 480)
        span, j = 2 * _BOSCH_JITTER + 1, _BOSCH_JITTER
        field = tuple(
            bytes(min(63, max(0, BAYER_8x8[y % 8][x % 8] + noise[y * 800 + x] % span - j)) for x in range(800))
            for y in range(480)
        )
        _BOSCH_RANK_FIELD = field
    return field


def _bosch_pick(rank: int, parts):
    """One rank, partitioned: ``parts`` is ``((ink, share), ...)`` low to high.

    The last part takes the remainder. One read per pixel, never two.
    """
    acc = 0.0
    for ink, share in parts[:-1]:
        acc += share * 64
        if rank < acc:
            return ink
    return parts[-1][0]


def _bosch_ink(name: str):
    return SPECTRA6[name]


def _bosch_paint(tile: Image.Image, mask: Image.Image, shade) -> None:
    """Fill ``mask``'s set pixels with ``shade(x, y, rank) -> ink`` (``None`` skips)."""
    bbox = mask.getbbox()
    if bbox is None:
        return
    px, mp = pixel_access(tile), gray_pixel_access(mask)
    ox, oy = getattr(tile, "_bosch_origin", (0, 0))
    field = _bosch_rank_field()
    for y in range(bbox[1], bbox[3]):
        ranks = field[(y + oy) % 480]
        for x in range(bbox[0], bbox[2]):
            if mp[x, y] > 127:
                ink = shade(x, y, ranks[(x + ox) % 800])
                if ink is not None:
                    px[x, y] = ink


def _bosch_shape(size, painter) -> Image.Image:
    """An ``"L"`` mask with ``painter(ImageDraw)`` drawn into it."""
    mask = Image.new("L", size, 0)
    painter(ImageDraw.Draw(mask))
    return mask


def _bosch_arch_tops(kind: str, width: int) -> list[float]:
    """Panel-local y of the painted top edge, per column.

    The centre is a segmental arch; each wing is half of it, mirrored so the
    apex sits at the wing's outer edge (see the section comment).
    """
    centre_w = _BOSCH_PANELS[1][1][2] - _BOSCH_PANELS[1][1][0]
    rise = _BOSCH_ARCH_RISE
    radius = (centre_w * centre_w / 4 + rise * rise) / (2 * rise)

    def arch(d: float) -> float:          # d = distance from the centre's left edge
        off = d - centre_w / 2
        return rise - (math.sqrt(max(0.0, radius * radius - off * off)) - (radius - rise))

    tops = []
    for x in range(width):
        c = x + 0.5
        if kind == "garden":
            tops.append(arch(c))
        elif kind == "paradise":          # hinge on the right
            tops.append(arch((width - c) / width * centre_w / 2))
        else:                             # hell: hinge on the left
            tops.append(arch(c / width * centre_w / 2))
    return tops


def _bosch_panel_mask(kind: str, size) -> Image.Image:
    width, height = size
    tops = _bosch_arch_tops(kind, width)
    pts = [(x, round(t)) for x, t in enumerate(tops)] + [(width - 1, height - 1), (0, height - 1)]
    return _bosch_shape(size, lambda d: d.polygon(pts, fill=255))


# ---- the frame -------------------------------------------------------------

def _bosch_paint_frame(image: Image.Image) -> None:
    """Dark oak frame with a grain, a gilt fillet round each panel, and hinges."""
    width, height = image.size
    draw = ImageDraw.Draw(image)
    red, yellow, black = (_bosch_ink(n) for n in ("red", "yellow", "black"))
    px = pixel_access(image)
    # The panels cover most of the frame; only the rails, the gaps and the
    # spandrels above the arches show, so the per-pixel passes skip the rest.
    covered = [any(x0 + 4 <= x < x1 - 4 for _, (x0, _, x1, _) in _BOSCH_PANELS) for x in range(width)]
    open_top, open_bottom = 14 + _BOSCH_ARCH_RISE + 4, 466 - 4

    def visible(x: int, y: int) -> bool:
        return not (covered[x] and open_top < y < open_bottom)

    for y in range(height):                           # wavy grain streaks
        for x in range(width):
            if not visible(x, y):
                continue
            g = math.sin(x * 0.9 + 6.0 * math.sin(y * 0.021 + x * 0.013))
            if g > 0.96 and position_noise(x, y) % 3 == 0:
                px[x, y] = red
    for kind, (x0, y0, x1, y1) in _BOSCH_PANELS:
        tops = _bosch_arch_tops(kind, x1 - x0)
        pts = [(x0 + x, y0 + round(t) - 3) for x, t in enumerate(tops)]
        pts = [(x0 - 3, pts[0][1])] + pts + [(x1 + 2, pts[-1][1]), (x1 + 2, y1 + 2), (x0 - 3, y1 + 2)]
        draw.polygon(pts, fill=yellow)
    for gap_x in (174, 620):                          # iron-and-gilt hinge straps
        for hy in (70, 238, 406):
            draw.rectangle((gap_x - 3, hy, gap_x + 10, hy + 14), fill=yellow)
            draw.rectangle((gap_x + 3, hy + 2, gap_x + 4, hy + 12), fill=black)
    for y in range(height):                           # gold: Y+R 5/8:3/8
        row = BAYER_8x8[y % 8]
        for x in range(width):
            if visible(x, y) and px[x, y] == yellow and row[x % 8] < 24:
                px[x, y] = red


# ---- Paradise --------------------------------------------------------------

def _bosch_sky(tile, horizon: int, top_white: float, low_white: float) -> None:
    w = tile.size[0]
    white, blue = _bosch_ink("white"), _bosch_ink("blue")
    mask = _bosch_shape(tile.size, lambda d: d.rectangle((0, 0, w, horizon), fill=255))

    def shade(x, y, rank):
        t = y / max(1, horizon)
        return _bosch_pick(rank, ((white, top_white + (low_white - top_white) * t), (blue, 1)))
    _bosch_paint(tile, mask, shade)


def _bosch_meadow(tile, top: int) -> None:
    """Pale spring green at the horizon deepening to a dark forest foot,
    rippled by a slow undulation so the turf does not read as a flat band.

    The frame's hot loop, so written out rather than routed through
    ``_bosch_paint``: the undulation is separable (angle-sum identity) into
    per-column tables and per-row values, and the four-way partition is
    inlined as cumulative thresholds. Same single rank read.
    """
    w, h = tile.size
    white, yellow, green, black = (_bosch_ink(n) for n in ("white", "yellow", "green", "black"))
    px = pixel_access(tile)
    ox, oy = getattr(tile, "_bosch_origin", (0, 0))
    field = _bosch_rank_field()
    sx = [math.sin(x * 0.05) for x in range(w)]
    cx = [math.cos(x * 0.05) for x in range(w)]
    span = max(1, h - top)
    for y in range(top, h):
        ranks = field[(y + oy) % 480]
        base = (y - top) / span
        amp = 0.12 * math.sin(y * 0.11)
        cy_, sy_ = math.cos(y * 0.03) * amp, math.sin(y * 0.03) * amp
        for x in range(w):
            t = base + sx[x] * cy_ + cx[x] * sy_
            t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
            rank = ranks[(x + ox) % 800]
            c1 = 14.08 * (1 - t)                        # white  0.22 (1 - t)
            c2 = c1 + 21.76 * (1 - t) + 3.84            # yellow 0.34 (1 - t) + 0.06
            if rank < c1:
                px[x, y] = white
            elif rank < c2:
                px[x, y] = yellow
            elif rank < c2 + 21.76 * t:                 # black  0.34 t
                px[x, y] = black
            else:
                px[x, y] = green


def _bosch_hills(tile, horizon: int, peaks, seed: int) -> None:
    """Distant blue hills along the horizon, fading into the sky."""
    w = tile.size[0]
    rng = random.Random(seed)
    pts: list[tuple[float, float]] = [(0, horizon)]
    for x in range(0, w + 8, 8):
        y = horizon - 6 - 5 * math.sin(x * 0.045 + seed) - rng.randrange(4)
        for px_, height_, half in peaks:
            if abs(x - px_) < half:
                y = min(y, horizon - height_ * (1 - abs(x - px_) / half) ** 0.6)
        pts.append((x, y))
    pts.append((w, horizon + 1))
    mask = _bosch_shape(tile.size, lambda d: d.polygon(pts, fill=255))
    white, blue = _bosch_ink("white"), _bosch_ink("blue")
    _bosch_paint(tile, mask, lambda x, y, r: _bosch_pick(r, ((white, 0.38), (blue, 1))))


def _bosch_birds(draw, points, ink) -> None:
    for x, y, s in points:
        draw.line([(x - s, y - s // 2), (x, y), (x + s, y - s // 2)], fill=ink, width=1)


def _bosch_rose_tower(tile, cx: int, base: int, top: int, half: int, light: float = 0.36) -> None:
    """A slender pink Gothic spire: flared base, lancets, crockets, finial."""
    white, red, black = _bosch_ink("white"), _bosch_ink("red"), _bosch_ink("black")
    body = [(cx - half - 5, base), (cx - half, base - 12), (cx - half + 2, top + 26),
            (cx, top), (cx + half - 2, top + 26), (cx + half, base - 12), (cx + half + 5, base)]
    mask = _bosch_shape(tile.size, lambda d: d.polygon(body, fill=255))

    def shade(x, y, rank):
        side = (x - cx) / max(1, half)               # lit from the upper left
        r = light + 0.14 * max(0.0, side)
        k = 0.12 * max(0.0, side - 0.3)
        return _bosch_pick(rank, ((black, k), (red, r), (white, 1)))
    _bosch_paint(tile, mask, shade)
    draw = ImageDraw.Draw(tile)
    for _i, y in enumerate(range(top + 34, base - 16, 22)):           # lancets
        draw.ellipse((cx - 2, y, cx + 2, y + 10), fill=black)
        for s in (-1, 1):                                              # crockets
            draw.polygon([(cx + s * (half - 1), y + 4), (cx + s * (half + 5), y - 2),
                          (cx + s * (half - 1), y + 9)], fill=red)
    draw.line([(cx, top - 10), (cx, top)], fill=red, width=1)
    draw.ellipse((cx - 2, top - 14, cx + 2, top - 10), fill=red)


def _bosch_paint_paradise(tile: Image.Image) -> None:
    w, h = tile.size
    white, blue, red, black, yellow, green = (_bosch_ink(n) for n in
                                              ("white", "blue", "red", "black", "yellow", "green"))
    horizon = 168
    _bosch_sky(tile, horizon, 0.30, 0.78)
    _bosch_hills(tile, horizon, ((24, 64, 14), (132, 44, 18)), seed=3)
    _bosch_meadow(tile, horizon)
    draw = ImageDraw.Draw(tile)
    _bosch_birds(draw, ((40, 58, 4), (56, 70, 3), (104, 50, 4), (118, 64, 3)), black)

    # The pool, and the Fountain of Life rising out of it.
    pool = _bosch_shape(tile.size, lambda d: d.ellipse((14, 262, 144, 338), fill=255))
    _bosch_paint(tile, pool, lambda x, y, r: _bosch_pick(
        r, ((white, 0.30 + 0.25 * ((y - 262) / 76)), (blue, 1))))
    for y in (286, 300, 316):
        draw.arc((30, y - 6, 128, y + 6), 200, 340, fill=white, width=1)
    cx = 79
    _bosch_rose_tower(tile, cx, 306, 150, 9)
    # The orb at the fountain's foot, and the owl in its dark hollow.
    orb = _bosch_shape(tile.size, lambda d: d.ellipse((cx - 17, 282, cx + 17, 316), fill=255))
    _bosch_paint(tile, orb, lambda x, y, r: _bosch_pick(
        r, ((black, 0.18 * max(0.0, (x - cx) / 17)), (red, 0.42), (white, 1))))
    draw.ellipse((cx - 9, 290, cx + 9, 308), fill=black)
    draw.ellipse((cx - 6, 295, cx - 2, 299), fill=yellow)
    draw.ellipse((cx + 2, 295, cx + 6, 299), fill=yellow)
    draw.point([(cx - 4, 297), (cx + 4, 297)], fill=black)
    draw.polygon([(cx - 1, 300), (cx + 1, 300), (cx, 303)], fill=yellow)

    # The dragon tree: a bare sepia trunk and a fan of dark spiky fronds.
    trunk = _bosch_shape(tile.size, lambda d: d.polygon(
        [(126, 356), (136, 356), (134, 236), (130, 236)], fill=255))
    _bosch_paint(tile, trunk, lambda x, y, r: red if (x + y) & 1 else green)
    for i in range(9):
        a = math.radians(200 + i * 17.5)
        ex, ey = 132 + 30 * math.cos(a), 236 + 24 * math.sin(a)
        draw.line([(132, 236), (round(ex), round(ey))], fill=black, width=3)
        draw.line([(132, 236), (round(ex), round(ey))], fill=green, width=1)

    # Small beasts, which at this scale read as dark flecks in the grass.
    for x, y in ((24, 372), (58, 398), (98, 384), (140, 410), (36, 430)):
        draw.ellipse((x - 3, y - 2, x + 3, y + 2), fill=black)
        draw.point((x - 4, y - 2), fill=black)
    for x, y in ((18, 204), (30, 196), (26, 214), (40, 206)):          # a rose bush in flower
        draw.ellipse((x - 9, y - 7, x + 9, y + 7), fill=black)
        draw.ellipse((x - 7, y - 6, x + 7, y + 5), fill=green)
    for x, y in ((16, 200), (30, 193), (40, 204), (24, 212), (34, 214)):
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=red)
        draw.point((x - 1, y - 1), fill=white)


# ---- the Garden ------------------------------------------------------------

def _bosch_blue_orb(tile, cx: int, cy: int, r: int) -> None:
    """A cracked blue globe of the far fountains, lit from the upper left."""
    white, blue, black = _bosch_ink("white"), _bosch_ink("blue"), _bosch_ink("black")
    mask = _bosch_shape(tile.size, lambda d: d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255))

    def shade(x, y, rank):
        lit = ((x - cx) + (y - cy)) / (2 * r)          # -1 lit .. +1 shadow
        return _bosch_pick(rank, ((white, max(0.0, 0.35 - 0.4 * lit)),
                                  (black, max(0.0, 0.3 * lit)), (blue, 1)))
    _bosch_paint(tile, mask, shade)
    draw = ImageDraw.Draw(tile)
    draw.line([(cx - r // 3, cy - r + 2), (cx, cy - r // 4), (cx - r // 5, cy + r // 3)], fill=black, width=1)


def _bosch_spikes(draw, cx: int, cy: int, r: int, ink, count: int = 5) -> None:
    for i in range(count):
        a = math.radians(-160 + i * 140 / max(1, count - 1))
        bx, by = cx + r * math.cos(a), cy + r * math.sin(a)
        tx, ty = cx + (r + 11) * math.cos(a), cy + (r + 11) * math.sin(a)
        nx, ny = -math.sin(a) * 2.5, math.cos(a) * 2.5
        draw.polygon([(bx - nx, by - ny), (tx, ty), (bx + nx, by + ny)], fill=ink)


def _bosch_strawberry(tile, cx: int, cy: int, r: int) -> None:
    """A giant strawberry: rounded shoulders tapering to a point, seeded, crowned."""
    white, red, yellow, green, black = (_bosch_ink(n) for n in ("white", "red", "yellow", "green", "black"))
    body = []
    for i in range(33):
        a = math.pi + math.pi * i / 32                 # the rounded shoulders, left to right
        body.append((cx + r * math.cos(a), cy - r * 0.55 + r * 0.5 * math.sin(a)))
    for i in range(1, 16):                             # the flanks, bellying out to the tip
        t = i / 16
        body.append((cx + r * math.cos(t * math.pi / 2) ** 0.7, cy - r * 0.55 + r * 1.6 * t))
    for i in range(15, 0, -1):
        t = i / 16
        body.append((cx - r * math.cos(t * math.pi / 2) ** 0.7, cy - r * 0.55 + r * 1.6 * t))
    body = [(round(x), round(y)) for x, y in body]
    mask = _bosch_shape(tile.size, lambda d: d.polygon(body, fill=255))

    def shade(x, y, rank):
        lit = ((x - cx) + (y - cy)) / (2 * r)
        return _bosch_pick(rank, ((white, max(0.0, 0.2 - 0.4 * lit)), (black, max(0.0, 0.4 * lit)), (red, 1)))
    _bosch_paint(tile, mask, shade)
    draw = ImageDraw.Draw(tile)
    mp = gray_pixel_access(mask)
    for row, yy in enumerate(range(cy - round(r * 0.6), cy + r, 6)):   # seeds, staggered
        for xx in range(cx - r + (row % 2) * 3, cx + r, 6):
            if 0 <= xx < tile.size[0] and 0 <= yy + 2 < tile.size[1] and mp[xx, yy] and mp[xx, yy + 2]:
                draw.line([(xx, yy), (xx, yy + 1)], fill=yellow)
    top = cy - round(r * 0.55) - round(r * 0.5)
    for i in range(6):                                                 # calyx
        a = math.radians(-170 + i * 32)
        draw.polygon([(cx - 3, top + 3), (cx + round(r * 0.8 * math.cos(a)),
                       top + 4 + round(r * 0.35 * abs(math.sin(a)))), (cx + 3, top + 3)], fill=green)
    draw.line([(cx, top + 2), (cx + 4, top - 10)], fill=green, width=2)


def _bosch_cherry(tile, cx: int, cy: int, r: int, stem_to) -> None:
    white, red, black, green = (_bosch_ink(n) for n in ("white", "red", "black", "green"))
    mask = _bosch_shape(tile.size, lambda d: d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255))

    def shade(x, y, rank):
        lit = ((x - cx) + (y - cy)) / (2 * r)
        return _bosch_pick(rank, ((black, max(0.0, 0.45 * lit + 0.05)), (red, 1)))
    _bosch_paint(tile, mask, shade)
    draw = ImageDraw.Draw(tile)
    draw.ellipse((cx - r // 2 - 2, cy - r // 2 - 2, cx - r // 2 + 2, cy - r // 2 + 2), fill=white)
    draw.line([(cx, cy - r), stem_to], fill=green, width=2)


def _bosch_bubble(tile, cx: int, cy: int, r: int) -> None:
    """The lovers' glass bubble: the meadow seen through a pale blue skin."""
    white, blue = _bosch_ink("white"), _bosch_ink("blue")
    mask = _bosch_shape(tile.size, lambda d: d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255))

    def shade(x, y, rank):
        edge = math.hypot(x - cx, y - cy) / r
        if rank < 64 * (0.10 + 0.45 * edge ** 4):
            return blue if rank % 2 else white
        return None                                  # the meadow shows through
    _bosch_paint(tile, mask, shade)
    draw = ImageDraw.Draw(tile)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=blue, width=2)
    draw.arc((cx - r + 6, cy - r + 6, cx + r - 6, cy + r - 6), 200, 250, fill=white, width=3)
    # Two tiny lovers inside — pale shapes, as they are in the painting.
    for dx in (-6, 5):
        draw.ellipse((cx + dx - 3, cy + 2, cx + dx + 3, cy + 14), fill=white)
        draw.ellipse((cx + dx - 2, cy - 4, cx + dx + 2, cy + 1), fill=white)


def _bosch_bird(tile, cx: int, cy: int, facing: int, inks) -> None:
    """One of the Garden's giant birds, perched: body, head, beak, a wing
    bar in its second colour, and a tail."""
    black = _bosch_ink("black")
    main, bar = inks
    draw = ImageDraw.Draw(tile)
    f = facing
    draw.polygon([(cx - f * 14, cy + 2), (cx - f * 28, cy + 12), (cx - f * 24, cy + 16), (cx - f * 10, cy + 8)],
                 fill=black)                                           # tail
    draw.ellipse((cx - 16, cy - 10, cx + 14, cy + 12), fill=main, outline=black)
    draw.ellipse((cx + f * 10 - 8, cy - 20, cx + f * 10 + 8, cy - 4), fill=main, outline=black)
    draw.polygon([(cx + f * 17, cy - 14), (cx + f * 27, cy - 11), (cx + f * 17, cy - 9)], fill=black)   # beak
    draw.ellipse((cx + f * 12 - 2, cy - 15, cx + f * 12 + 1, cy - 12), fill=black)                    # eye
    draw.chord((cx - 12, cy - 6, cx + 8, cy + 10), 0 if f > 0 else 180, 180 if f > 0 else 360, fill=bar)
    draw.line([(cx - 2, cy + 12), (cx - 4, cy + 20)], fill=black, width=1)                             # legs
    draw.line([(cx + 4, cy + 12), (cx + 6, cy + 20)], fill=black, width=1)


def _bosch_paint_garden(tile: Image.Image) -> None:
    w, h = tile.size
    white, blue, red, black, yellow, green = (_bosch_ink(n) for n in
                                              ("white", "blue", "red", "black", "yellow", "green"))
    horizon, lake_foot = 74, 124
    _bosch_sky(tile, horizon, 0.62, 0.84)
    lake = _bosch_shape(tile.size, lambda d: d.rectangle((0, horizon, w, lake_foot), fill=255))
    _bosch_paint(tile, lake, lambda x, y, r: _bosch_pick(
        r, ((white, 0.48 - 0.22 * (y - horizon) / (lake_foot - horizon)), (blue, 1))))
    _bosch_hills(tile, horizon, ((30, 22, 24), (410, 26, 22)), seed=11)
    _bosch_meadow(tile, lake_foot)
    draw = ImageDraw.Draw(tile)

    # The fountains of the far lake, alternating rose spires and blue globes.
    _bosch_rose_tower(tile, 218, 118, 40, 8)
    _bosch_blue_orb(tile, 218, 104, 13)
    _bosch_spikes(draw, 218, 104, 13, red, 5)
    for cx, kind in ((58, "orb"), (128, "tower"), (310, "tower"), (380, "orb")):
        if kind == "orb":
            _bosch_blue_orb(tile, cx, 106, 12)
            _bosch_spikes(draw, cx, 106, 12, red, 3)
        else:
            _bosch_rose_tower(tile, cx, 120, 70, 6, light=0.44)
    rng = random.Random(0xB05C)
    x = 4                                                              # a hedge of far trees
    while x < w:
        r = rng.randrange(4, 9)
        draw.ellipse((x - r, lake_foot - r - 2, x + r, lake_foot + r - 2), fill=black)
        draw.ellipse((x - r + 2, lake_foot - r - 1, x + r - 4, lake_foot + r - 6), fill=green)
        x += r + rng.randrange(6, 22)

    # The middle distance: the pool of bathers, ringed by the cavalcade of
    # riders circling it — the hub the whole centre panel turns around.
    pcx, pcy = w // 2, 176
    pool = _bosch_shape(tile.size, lambda d: d.ellipse((pcx - 104, pcy - 20, pcx + 104, pcy + 20), fill=255))
    _bosch_paint(tile, pool, lambda x, y, r: _bosch_pick(r, ((white, 0.34), (blue, 1))))
    for i in range(9):
        bx = pcx - 80 + i * 20 + (i % 2) * 4
        draw.ellipse((bx - 2, pcy - 6 + (i % 3) * 4, bx + 2, pcy - 2 + (i % 3) * 4), fill=white)
    for i in range(36):
        a = 2 * math.pi * i / 36
        rx, ry = pcx + 150 * math.cos(a), pcy + 36 * math.sin(a)
        ink = (red, white, black, yellow, blue, black)[i % 6]
        draw.ellipse((round(rx) - 4, round(ry) - 2, round(rx) + 4, round(ry) + 2), fill=ink)
        draw.ellipse((round(rx) - 1, round(ry) - 6, round(rx) + 1, round(ry) - 2), fill=white)

    _bosch_bird(tile, 98, 360, 1, (yellow, red))                         # a goldfinch
    _bosch_bird(tile, 338, 362, -1, (blue, white))                     # a kingfisher

    # The giant fruit of the foreground.
    _bosch_strawberry(tile, 60, 414, 26)
    _bosch_bubble(tile, 158, 408, 30)
    _bosch_cherry(tile, 262, 418, 14, (276, 386))
    _bosch_cherry(tile, 292, 424, 13, (276, 386))
    _bosch_strawberry(tile, 384, 412, 22)
    _bosch_birds(draw, ((316, 30, 4), (332, 22, 3), (96, 34, 3)), black)


# ---- Hell ------------------------------------------------------------------

def _bosch_flesh(rank: int, lit: float):
    """Bosch's pallid flesh: W-major, a little red and yellow, shading to black."""
    white, red, yellow, black = (_bosch_ink(n) for n in ("white", "red", "yellow", "black"))
    return _bosch_pick(rank, ((black, max(0.0, 0.35 * lit)), (red, 0.16), (yellow, 0.16), (white, 1)))


def _bosch_ear(tile, cx: int, top: int, w: int, h: int, facing: int) -> None:
    """One giant ear in profile: a broad rounded shell narrowing to a lobe,
    with the helix rolled along its rim and the dark bowl of the concha.

    ``facing`` is +1 for an ear whose opening faces right, -1 for left.
    """
    black = _bosch_ink("black")
    half = w / 2
    outline = []
    for i in range(25):                                # the rounded top and back
        a = math.pi + math.pi * 1.25 * i / 24
        outline.append((cx - facing * half * math.cos(a) * -1, top + half + half * math.sin(a)))
    outline.append((cx + facing * half * 0.35, top + h * 0.82))           # the lobe
    outline.append((cx - facing * half * 0.05, top + h))
    outline.append((cx - facing * half * 0.55, top + h * 0.84))
    outline = [(round(x), round(y)) for x, y in outline]
    mask = _bosch_shape(tile.size, lambda d: d.polygon(outline, fill=255))
    _bosch_paint(tile, mask, lambda x, y, r: _bosch_flesh(r, max(0.0, ((x - cx) * facing + (y - top - h / 2)) / h)))
    draw = ImageDraw.Draw(tile)
    draw.polygon(outline, outline=black)
    inner = (cx - half * 0.62, top + half * 0.38, cx + half * 0.62, top + half * 1.62)
    start, end = (150, 20) if facing > 0 else (160, 30)
    draw.arc([round(v) for v in inner], start, end, fill=black, width=1)  # the helix fold
    bowl = (cx - facing * 3 - 5, top + half - 4, cx - facing * 3 + 5, top + half + 9)
    draw.ellipse([round(v) for v in bowl], fill=black)                     # the concha


def _bosch_paint_hell(tile: Image.Image) -> None:
    w, h = tile.size
    white, blue, red, black, yellow, green = (_bosch_ink(n) for n in
                                              ("white", "blue", "red", "black", "yellow", "green"))
    draw = ImageDraw.Draw(tile)

    # A wall of fire behind the city: yellow-hot at the root, red only at the
    # tips, because red on black is the lowest-contrast pair the inks offer.
    def crest(x: float) -> float:
        return 30 + 16 * abs(math.sin(x * 0.11)) + 10 * math.sin(x * 0.047 + 1.3)

    fire_foot = 112
    blaze = [(0, fire_foot)] + [(x, crest(x)) for x in range(0, w + 3, 3)] + [(w, fire_foot)]
    fire = _bosch_shape(tile.size, lambda d: d.polygon(blaze, fill=255))

    def flame(x, y, rank):
        t = (y - crest(x)) / max(1.0, fire_foot - crest(x))   # 0 tip .. 1 root
        return _bosch_pick(rank, ((white, 0.4 * t * t), (red, 0.75 * (1 - t) ** 1.5), (yellow, 1)))
    _bosch_paint(tile, fire, flame)
    paint_neon_mask(tile, fire, None, red, radius=7, gamma=1.3, cap=0.55,
                    ground=frozenset({black}), tile=BAYER_8x8,
                    glow_minor=yellow, glow_minor_share=0.375)
    fire.close()
    draw.rectangle((0, fire_foot, w, 150), fill=black)   # the glow lights the sky, not the ground
    # The city burning: black gables and towers against the blaze.
    skyline = [(0, 114), (0, 84), (8, 84), (8, 70), (16, 60), (24, 70), (24, 90), (36, 90), (36, 54),
               (42, 42), (48, 54), (48, 86), (60, 86), (60, 76), (72, 64), (84, 76), (84, 92), (98, 92),
               (98, 50), (104, 36), (110, 50), (110, 82), (124, 82), (130, 72), (136, 82), (136, 94),
               (w, 94), (w, 114)]
    draw.polygon(skyline, fill=black)
    for x, y in ((40, 62), (102, 58), (102, 70), (76, 80), (16, 76), (128, 88)):
        draw.rectangle((x, y, x + 1, y + 3), fill=yellow)

    # The knife between two ears — the blade marked with its letter M.
    _bosch_ear(tile, 42, 122, 38, 54, -1)
    _bosch_ear(tile, 86, 122, 38, 54, 1)
    blade = [(58, 146), (144, 132), (152, 138), (60, 160)]
    draw.polygon(blade, fill=white, outline=black)
    draw.line([(62, 153), (146, 136)], fill=blue, width=1)              # the bevel's cold edge
    draw.text((96, 139), "M", font=load_font([(GRENZE_GOTISCH_VARIABLE, "Black"), *META_FONT_BOLD_CANDIDATES],
                                            size=11), fill=black)
    draw.line([(8, 170), (140, 162)], fill=black, width=3)             # the arrow through them
    draw.line([(8, 170), (140, 162)], fill=white, width=1)
    draw.polygon([(146, 161), (134, 156), (136, 168)], fill=white, outline=black)
    for fx in (8, 14):
        draw.line([(fx, 164), (fx + 4, 176)], fill=red, width=2)

    # The Tree-Man: a broken egg-shell body on rotten trunk legs, turning
    # his head back toward us from under a disc hat carrying a bagpipe.
    for leg in ([(70, 292), (80, 292), (62, 372), (50, 372)], [(96, 292), (106, 292), (114, 372), (102, 372)]):
        m = _bosch_shape(tile.size, lambda d, leg=leg: d.polygon(leg, fill=255))
        _bosch_paint(tile, m, lambda x, y, r: black if r < 16 else (red if (x + y) & 1 else green))
        draw.polygon(leg, outline=black)
    draw.line([(68, 324), (54, 314)], fill=black, width=2)             # snapped branches
    draw.line([(106, 336), (120, 326)], fill=black, width=2)
    shell = (50, 226, 126, 300)
    body = _bosch_shape(tile.size, lambda d: d.ellipse(shell, fill=255))
    _bosch_paint(tile, body, lambda x, y, r: _bosch_flesh(r, max(0.0, ((x - 88) + (y - 263)) / 64)))
    draw.ellipse(shell, outline=black, width=1)
    draw.polygon([(104, 240), (126, 256), (126, 284), (110, 296), (100, 276), (108, 262)], fill=black)
    draw.rectangle((112, 270, 114, 275), fill=yellow)                  # the tavern inside him
    head_box = (34, 212, 62, 242)
    head = _bosch_shape(tile.size, lambda d: d.ellipse(head_box, fill=255))
    _bosch_paint(tile, head, lambda x, y, r: _bosch_flesh(r, max(0.0, (x - 48) / 14) * 0.5))
    draw.ellipse(head_box, outline=black, width=1)
    draw.ellipse((40, 222, 43, 225), fill=black)
    draw.ellipse((50, 222, 53, 225), fill=black)
    draw.arc((41, 226, 53, 236), 20, 160, fill=black, width=1)
    hat_box = (20, 202, 120, 216)                                      # the grey disc hat
    hat = _bosch_shape(tile.size, lambda d: d.ellipse(hat_box, fill=255))
    _bosch_paint(tile, hat, lambda x, y, r: black if r < 22 + (y - 209) * 3 else white)
    draw.ellipse(hat_box, outline=black, width=1)
    bag = _bosch_shape(tile.size, lambda d: d.ellipse((50, 186, 84, 208), fill=255))
    _bosch_paint(tile, bag, lambda x, y, r: _bosch_pick(r, ((black, max(0.0, (x - 67) / 60)), (red, 0.45), (white, 1))))
    draw.ellipse((50, 186, 84, 208), outline=black, width=1)
    draw.line([(80, 192), (102, 180)], fill=black, width=3)             # the chanter
    draw.line([(62, 188), (70, 172)], fill=black, width=2)              # the drone

    # The frozen lake: boats locked in the ice, a hole broken through it.
    ice = _bosch_shape(tile.size, lambda d: d.rectangle((0, 366, w, h), fill=255))
    _bosch_paint(tile, ice, lambda x, y, r: _bosch_pick(r, ((white, 0.56), (blue, 1))))
    for boat_x in (48, 110):
        draw.polygon([(boat_x - 18, 368), (boat_x + 18, 368), (boat_x + 11, 380), (boat_x - 11, 380)], fill=black)
    draw.ellipse((18, 412, 66, 430), fill=black)
    draw.line([(80, 396), (104, 410), (140, 404)], fill=white, width=1)
    draw.line([(10, 446), (40, 436), (72, 444)], fill=blue, width=1)
    for x, y in ((118, 428), (134, 438), (92, 440)):                   # skaters
        draw.rectangle((x, y - 6, x + 2, y), fill=black)
        draw.point((x + 1, y - 8), fill=black)


# ---- the banderole ---------------------------------------------------------

def _bosch_scroll_layout(draw, quote_row: dict):
    """Fit the quote and size the banderole to it (the ``pride`` card rule)."""
    text = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    max_w, max_h = _BOSCH_TEXT_MAX
    credit_h = _BOSCH_CREDIT_SIZE + 10
    regular, bold, wrapped, line_height, _ = fit_quote(
        draw, text, quote_row.get("matched_text") or "", max_w, max_h - credit_h,
        font_max=30, font_min=14, line_height_mult=1.2, theme="bosch",
    )
    widest = 0
    for line in wrapped:
        segment = [c for c in line]
        while segment and segment[0][0].strip() == "":
            segment.pop(0)
        while segment and segment[-1][0].strip() == "":
            segment.pop()
        widest = max(widest, sum(draw.textbbox((0, 0), c, font=bold if b else regular)[2] for c, b in segment))
    pad_x, pad_y = _BOSCH_SCROLL_PAD
    body_w = max(_BOSCH_SCROLL_MIN_W, min(max_w, widest) + 2 * pad_x)
    body_h = len(wrapped) * line_height + credit_h + 2 * pad_y
    cx, cy = _BOSCH_SCROLL_CENTRE
    rect = (cx - body_w // 2, cy - body_h // 2, cx + body_w // 2, cy + body_h // 2)
    return regular, bold, wrapped, line_height, rect


def _bosch_scroll_edge(x: float, rect, side: int) -> float:
    """y of the banderole's top (side=-1) or bottom (+1) edge — a flutter."""
    x0, y0, x1, y1 = rect
    wave = _BOSCH_SCROLL_WAVE * math.sin((x - x0) / (x1 - x0) * math.pi * 2.0 + 0.6)
    return (y0 if side < 0 else y1) + wave


def _bosch_scroll_mask(size, rect) -> Image.Image:
    x0, y0, x1, y1 = rect
    top = [(x, _bosch_scroll_edge(x, rect, -1)) for x in range(x0, x1 + 1, 4)]
    bottom = [(x, _bosch_scroll_edge(x, rect, 1)) for x in range(x1, x0 - 1, -4)]
    return _bosch_shape(size, lambda d: d.polygon(top + bottom, fill=255))


def _bosch_paint_scroll(image: Image.Image, rect) -> None:
    """Parchment banderole with a cast shadow and two rolled ends."""
    x0, y0, x1, y1 = rect
    white, yellow, black, red = (_bosch_ink(n) for n in ("white", "yellow", "black", "red"))
    shadow = _bosch_scroll_mask(image.size, (x0 + 6, y0 + 7, x1 + 6, y1 + 7))
    _bosch_paint(image, shadow, lambda x, y, r: black if r < 30 else None)
    body = _bosch_scroll_mask(image.size, rect)
    # Parchment: sparse cream, a touch darker toward the fluttering edges.
    cy = (y0 + y1) / 2

    def parchment(x, y, rank):
        edge = abs(y - cy) / ((y1 - y0) / 2)
        if rank < 64 * (0.13 + 0.10 * edge ** 3):
            return yellow
        if rank > 64 - 64 * 0.05 * edge ** 6:
            return red
        return white
    _bosch_paint(image, body, parchment)
    draw = ImageDraw.Draw(image)
    top = [(x, round(_bosch_scroll_edge(x, rect, -1))) for x in range(x0, x1 + 1, 2)]
    bottom = [(x, round(_bosch_scroll_edge(x, rect, 1))) for x in range(x0, x1 + 1, 2)]
    draw.line(top, fill=black, width=1)
    draw.line(bottom, fill=black, width=1)
    # Rolled ends: cylinders taller than the body, lit left, shaded right.
    rw = _BOSCH_ROLL_W
    for side, ex in ((-1, x0), (1, x1)):
        et, eb = _bosch_scroll_edge(ex, rect, -1), _bosch_scroll_edge(ex, rect, 1)
        rx0 = ex - rw if side < 0 else ex
        box = (rx0, round(et) - 5, rx0 + rw, round(eb) + 5)
        roll = _bosch_shape(image.size, lambda d, box=box: d.rounded_rectangle(box, radius=rw // 2, fill=255))

        def shade(x, y, rank, rx0=rx0):
            t = (x - rx0) / rw                          # 0 lit edge .. 1 shadow edge
            return _bosch_pick(rank, ((black, max(0.0, 0.55 * (t - 0.35))), (yellow, 0.3), (white, 1)))
        _bosch_paint(image, roll, shade)
        draw.rounded_rectangle(box, radius=rw // 2, outline=black, width=1)
        cx_ = rx0 + rw // 2
        draw.arc((cx_ - 4, box[1] + 2, cx_ + 4, box[1] + 8), 0, 300, fill=black, width=1)  # the spiral


def _bosch_draw_lettering(draw, regular, bold, wrapped, line_height, rect, quote_row: dict,
                          ink, accent) -> None:
    x0, y0, x1, y1 = rect
    pad_x, pad_y = _BOSCH_SCROLL_PAD
    credit_y = draw_centred_styled_lines(
        draw, wrapped, x0=x0, x1=x1, top=y0 + pad_y, line_height=line_height,
        regular=regular, bold=bold, fill=ink, accent=accent, min_inset=pad_x,
    )
    credit_font = load_font(theme_font_candidates("bosch", "quote_regular"), size=_BOSCH_CREDIT_SIZE)
    draw_truncated_centred_byline(
        draw, quote_row, centre=(x0 + x1) // 2, baseline=credit_y + _BOSCH_CREDIT_SIZE + 2,
        max_width=x1 - x0 - 2 * pad_x, font=credit_font, fill=ink,
    )


# ---- assembly ----------------------------------------------------------------

_BOSCH_PAINTERS = {
    "paradise": _bosch_paint_paradise,
    "garden": _bosch_paint_garden,
    "hell": _bosch_paint_hell,
}


def _bosch_panel_region(size) -> Image.Image:
    """The union of the three arched panel shapes, where craquelure may craze
    (never the frame). Pure geometry, so it does not depend on what was drawn."""
    region = Image.new("L", size, 0)
    for kind, (x0, y0, x1, y1) in _BOSCH_PANELS:
        mask = _bosch_panel_mask(kind, (x1 - x0, y1 - y0))
        region.paste(mask, (x0, y0), mask)
    return region


def _bosch_paint_panels(image: Image.Image) -> None:
    """Paint each wing onto its own tile and set it into the frame."""
    for kind, (x0, y0, x1, y1) in _BOSCH_PANELS:
        size = (x1 - x0, y1 - y0)
        ground = SPECTRA6["black"] if kind == "hell" else SPECTRA6["white"]
        tile = Image.new("RGB", size, ground)
        setattr(tile, "_bosch_origin", (x0, y0))  # noqa: B010 - not an Image attribute, so mypy rejects the plain assignment; read back with getattr in _bosch_paint
        _BOSCH_PAINTERS[kind](tile)
        image.paste(tile, (x0, y0), _bosch_panel_mask(kind, size))
        tile.close()


def render_bosch_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """*The Garden of Earthly Delights*, open (see the section comment above)."""
    del time_str  # an altarpiece carries no hour; the matched phrase is the clock.
    image = Image.new("RGB", (800, 480), color=SPECTRA6["black"])
    _bosch_paint_frame(image)
    _bosch_paint_panels(image)
    region = _bosch_panel_region(image.size)
    draw = ImageDraw.Draw(image)
    regular, bold, wrapped, line_height, rect = _bosch_scroll_layout(draw, quote_row)
    _bosch_paint_scroll(image, rect)
    _bosch_draw_lettering(draw, regular, bold, wrapped, line_height, rect, quote_row,
                          SPECTRA6["black"], SPECTRA6["red"])
    lettering = Image.new("L", image.size, 0)
    _bosch_draw_lettering(ImageDraw.Draw(lettering), regular, bold, wrapped, line_height, rect,
                          quote_row, 255, 255)
    paint_craquelure(image, region, seed=_BOSCH_CRACK_SEED, cell=_BOSCH_CRACK_CELL, keep_out=lettering)
    lettering.close()
    region.close()
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("bosch",), render=render_bosch_frame)
