"""The ``codex`` theme's frame: a botanical entry from Luigi Serafini's *Codex
Seraphinianus* (1981), with the quote as the page's one deciphered passage.

Design notes: docs/themes.md § codex
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from ..fonts import load_font, normalize_dashes, theme_font_candidates
from ..furniture import _clock_hh_mm, _row_digest, draw_centred_styled_lines, draw_truncated_centred_byline
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, pixel_access, snap_image_to_palette
from ..primitives import _white_noise
from ..spec import FrameSpec
from ._shared import _codex_script, _vitrail_fill_polygon, _vitrail_pane_ink

_CODEX_PLATE = (20, 40, 324, 452)            # the illustration's clear field
_CODEX_STEM_BASE = (128, 404)
_CODEX_STEM_TOP = (140, 118)
_CODEX_COLUMN = (344, 772)                   # text column x-range
_CODEX_QUOTE_RECT = (344, 146, 772, 392)
_CODEX_RAINBOW_CENTRE = (716, 76)
_CODEX_BANDS = (
    ("solid", SPECTRA6["red"]),
    ("2", SPECTRA6["red"], SPECTRA6["yellow"], 0.375),      # tangerine
    ("solid", SPECTRA6["yellow"]),
    ("solid", SPECTRA6["green"]),
    ("solid", SPECTRA6["blue"]),
    ("2", SPECTRA6["red"], SPECTRA6["blue"], 0.5),          # violet
)
_CODEX_LEAF_FILLS = (
    ("2", SPECTRA6["green"], SPECTRA6["blue"], 0.375),      # teal
    ("2", SPECTRA6["green"], SPECTRA6["white"], 0.5),       # mint
    ("solid", SPECTRA6["green"]),
)
_CODEX_PETAL_FILLS = (
    ("2", SPECTRA6["red"], SPECTRA6["white"], 0.5),         # rose
    ("2", SPECTRA6["red"], SPECTRA6["blue"], 0.5),          # violet
)
_CODEX_SEPIA = ("2", SPECTRA6["red"], SPECTRA6["green"], 0.5)
_CODEX_TANGERINE = ("2", SPECTRA6["red"], SPECTRA6["yellow"], 0.375)
_CODEX_CREAM_DENSITY = 14                    # of 256: sparse Y+W paper wash
_CODEX_NUMERAL_BASE = 21
_CODEX_HEADING = (58, 8)                     # (baseline, x-height) of the red rubric
_CODEX_UPPER_LINES = (92, 112, 132)          # script paragraph above the quote
_CODEX_LOWER_LINES = (418, 438)              # script paragraph below it
_CODEX_CAPTION_BASE = 466                    # plate caption, clear below the roots
_CODEX_BODY_XH = 5
_CODEX_BYLINE_MIN = 12
_CODEX_BYLINE_MAX = 18


def _codex_paint_page(image: Image.Image) -> None:
    """Cream paper: a sparse aperiodic yellow scatter over white.

    A hash field rather than a Bayer rank (a sparse ordered tile lattices),
    using the C-speed ``_white_noise`` since it covers the whole canvas.
    """
    noise = _white_noise(image.width, image.height, 0xC0DE)
    mask = noise.point(lambda v: 255 if v < _CODEX_CREAM_DENSITY else 0)
    image.paste(SPECTRA6["yellow"], (0, 0), mask)
    noise.close()
    mask.close()


def _codex_numeral_advance(digit: int, size: float) -> float:
    """Horizontal advance of one numeral: zero's bare ring is narrower."""
    return size * (0.85 if digit == 0 else 0.95)


def _codex_numeral(draw: ImageDraw.ImageDraw, x: float, base: float, digit: int, *,
                   size: float, fill, width: int = 2) -> float:
    """One of twenty-one invented digits, drawn from the bits of its value.

    Zero is a bare ring. Every other digit is a curved stem whose features are
    switched on by its five bits — a top loop, a foot hook, a crossbar, a dot, a
    tail curl — so the twenty glyphs are pairwise distinct and a given digit is
    always drawn the same way. Returns the advance.
    """
    s = size
    if digit == 0:
        draw.ellipse((x, base - s * 0.7, x + s * 0.6, base - s * 0.1), outline=fill, width=width)
        return _codex_numeral_advance(digit, s)
    stem = [(x + s * 0.15, base), (x + s * 0.35, base - s * 0.5), (x + s * 0.2, base - s)]
    draw.line(stem, fill=fill, width=width, joint="curve")
    if digit & 1:
        draw.arc((x + s * 0.1, base - s * 1.15, x + s * 0.55, base - s * 0.75), 90, 450, fill=fill, width=width)
    if digit & 2:
        draw.arc((x - s * 0.1, base - s * 0.3, x + s * 0.35, base + s * 0.1), 0, 180, fill=fill, width=width)
    if digit & 4:
        draw.line((x, base - s * 0.55, x + s * 0.6, base - s * 0.45), fill=fill, width=width)
    if digit & 8:
        d = width + 0.5
        cx, cy = x + s * 0.6, base - s * 0.85
        draw.ellipse((cx - d, cy - d, cx + d, cy + d), fill=fill)
    if digit & 16:
        draw.arc((x + s * 0.25, base - s * 0.35, x + s * 0.75, base + s * 0.05), 270, 90, fill=fill, width=width)
    return _codex_numeral_advance(digit, s)


def codex_page_digits(time_str: str) -> list[int]:
    """The minute of the day as base-21 digits, most significant first."""
    hh, mm = _clock_hh_mm(time_str)
    value = hh * 60 + mm
    digits = []
    while True:
        digits.append(value % _CODEX_NUMERAL_BASE)
        value //= _CODEX_NUMERAL_BASE
        if not value:
            break
    return digits[::-1]


def _codex_ellipse_poly(cx: float, cy: float, a: float, b: float, angle: float, n: int = 28) -> list:
    """A rotated ellipse as a polygon (PIL's ``ellipse`` cannot rotate)."""
    ca, sa = math.cos(angle), math.sin(angle)
    return [
        (cx + a * math.cos(t) * ca - b * math.sin(t) * sa,
         cy + a * math.cos(t) * sa + b * math.sin(t) * ca)
        for t in (2 * math.pi * i / n for i in range(n))
    ]


def _codex_fill(image: Image.Image, polygon: list, spec: tuple, outline=SPECTRA6["black"], width: int = 1) -> None:
    """Fill with a documented recipe, then ink the contour — coloured pencil
    inside a pen line, the way every plate in the book is drawn."""
    _vitrail_fill_polygon(image, polygon, spec)
    if outline is not None:
        ImageDraw.Draw(image).line(list(polygon) + [polygon[0]], fill=outline, width=width, joint="curve")


def _codex_stem_point(t: float) -> tuple[float, float]:
    """The stem's centreline: a gentle quadratic S from root to crown."""
    (x0, y0), (x1, y1) = _CODEX_STEM_BASE, _CODEX_STEM_TOP
    cx = x0 + 34
    x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1
    y = y0 + (y1 - y0) * t
    return x, y


def _codex_fill_mask(image: Image.Image, mask: Image.Image, spec: tuple) -> None:
    """Paint every set pixel of a ``1`` mask with a recipe, in place.

    Filling through a private mask gives the roots their R+G sepia without a
    red sentinel, whose bbox post-pass would also recolour any other red there.
    """
    bbox = mask.getbbox()
    if bbox is None:
        return
    mpx, ipx = pixel_access(mask), pixel_access(image)
    for y in range(bbox[1], bbox[3]):
        for x in range(bbox[0], bbox[2]):
            if mpx[x, y]:
                ipx[x, y] = _vitrail_pane_ink(x, y, spec)


def _codex_paint_roots(image: Image.Image, draw: ImageDraw.ImageDraw, rng: random.Random):
    """Sepia roots below a green-hatched ground line, each curling into a
    spiral. Returns the roots' ink bbox, so the caption can be kept clear of it.
    """
    bx, by = _CODEX_STEM_BASE
    # Ground: short green hatching, the mound the specimen stands on.
    for i in range(-70, 72, 5):
        h = 3 + int(4 * math.cos(i / 70 * math.pi / 2))
        draw.line((bx + i, by + 2, bx + i + 3, by + 2 - h), fill=SPECTRA6["green"], width=1)
    draw.line((bx - 78, by + 3, bx + 80, by + 3), fill=SPECTRA6["black"], width=1)
    mask = Image.new("1", image.size, 0)
    mdraw = ImageDraw.Draw(mask)
    y: float
    for k, dx in enumerate((-46, -20, 6, 30, 52)):
        pts: list[tuple[float, float]] = [(bx + dx * 0.2, by + 4)]
        x, y = bx + dx * 0.2, by + 4
        for _ in range(8):
            x += dx * 0.12 + rng.uniform(-2, 2)
            y += 4.2
            pts.append((x, y))
        # Spiral terminal: the root keeps curling the way it was heading. The
        # centre sits on the curl side, so the spiral starts at the root's tip
        # (angle pi from a centre to its right, 0 from one to its left) and
        # winds inward.
        curl = 1 if dx > 0 else -1
        r = 5 + k % 3
        ox, oy = x + curl * r, y
        start = math.pi if curl > 0 else 0.0
        for j in range(1, 16):
            a = start - curl * j * 0.55
            rr = r * (1 - j / 18)
            pts.append((ox + rr * math.cos(a), oy + rr * math.sin(a)))
        mdraw.line(pts, fill=1, width=3, joint="curve")
    bbox = mask.getbbox()
    _codex_fill_mask(image, mask, _CODEX_SEPIA)
    mask.close()
    return bbox


def _codex_paint_stem(image: Image.Image, draw: ImageDraw.ImageDraw, band_offset: int) -> None:
    """A tapering stem banded through the spectrum, inked on both flanks."""
    n = 22
    left, right = [], []
    samples = []
    for i in range(n + 1):
        t = i / n
        x, y = _codex_stem_point(t)
        hw = 9 - 5 * t
        samples.append((x, y, hw))
    for i in range(n):
        xa, ya, ha = samples[i]
        xb, yb, hb = samples[i + 1]
        band = (xa - ha, ya), (xa + ha, ya), (xb + hb, yb), (xb - hb, yb)
        _vitrail_fill_polygon(image, list(band), _CODEX_BANDS[(i + band_offset) % len(_CODEX_BANDS)])
        draw.line((xb - hb, yb, xb + hb, yb), fill=SPECTRA6["black"], width=1)
        left.append((xa - ha, ya))
        right.append((xa + ha, ya))
    left.append((samples[-1][0] - samples[-1][2], samples[-1][1]))
    right.append((samples[-1][0] + samples[-1][2], samples[-1][1]))
    draw.line(left, fill=SPECTRA6["black"], width=2, joint="curve")
    draw.line(right, fill=SPECTRA6["black"], width=2, joint="curve")


def _codex_paint_fish_leaf(image: Image.Image, draw: ImageDraw.ImageDraw, ax: float, ay: float,
                           side: int, spec: tuple, size: float) -> tuple[float, float]:
    """A leaf that is a fish: body, forked tail at the stem, scales, one eye.

    The tail is the petiole: the fish grows out of the stem nose-first.
    Returns the tip of the nose, for the plate's dotted leaders.
    """
    angle = -0.5 if side > 0 else math.pi + 0.5
    ca, sa = math.cos(angle), math.sin(angle)

    def rot(u: float, v: float) -> tuple[float, float]:
        return ax + u * ca - v * sa, ay + u * sa + v * ca

    a, b = size, size * 0.42
    tail_root = 10
    tail = [rot(tail_root + 2, 0), rot(0, -b * 0.8), rot(4, 0), rot(0, b * 0.8)]
    _codex_fill(image, tail, _CODEX_TANGERINE)
    cx = tail_root + a
    body = [rot(cx + a * math.cos(t), b * math.sin(t) * (0.75 + 0.25 * math.cos(t)))
            for t in (2 * math.pi * i / 30 for i in range(30))]
    _codex_fill(image, body, spec, width=2)
    # Scale arcs: rows of small blue crescents along the flank.
    for row in (-0.3, 0.2):
        for k in range(3):
            u = cx - a * 0.55 + k * a * 0.36
            sx, sy = rot(u, row * b)
            draw.arc((sx - 4, sy - 4, sx + 4, sy + 4), 0, 180, fill=SPECTRA6["blue"], width=1)
    # Gill line and eye near the nose.
    gx0, gy0 = rot(cx + a * 0.35, -b * 0.6)
    gx1, gy1 = rot(cx + a * 0.42, b * 0.6)
    draw.line((gx0, gy0, gx1, gy1), fill=SPECTRA6["black"], width=1)
    ex, ey = rot(cx + a * 0.62, -b * 0.15)
    draw.ellipse((ex - 3.5, ey - 3.5, ex + 3.5, ey + 3.5), fill=SPECTRA6["white"], outline=SPECTRA6["black"])
    draw.ellipse((ex - 1.5, ey - 1.5, ex + 1.5, ey + 1.5), fill=SPECTRA6["black"])
    # A dorsal fin, red, on the upper flank.
    fin = [rot(cx - a * 0.3, -b * 0.9), rot(cx - a * 0.05, -b * 1.55), rot(cx + a * 0.2, -b * 0.95)]
    _codex_fill(image, fin, ("solid", SPECTRA6["red"]))
    return rot(cx + a, 0)


def _codex_paint_blossom(image: Image.Image, draw: ImageDraw.ImageDraw, rng: random.Random) -> None:
    """A corolla of alternating rose and violet petals round an open eye."""
    cx, cy = _CODEX_STEM_TOP[0], _CODEX_STEM_TOP[1] - 36
    petals = rng.choice((8, 9, 10, 11))
    phase = rng.uniform(0, math.pi)
    for i in range(petals):
        a = phase + 2 * math.pi * i / petals
        px_, py_ = cx + 34 * math.cos(a), cy + 34 * math.sin(a)
        _codex_fill(image, _codex_ellipse_poly(px_, py_, 26, 11, a), _CODEX_PETAL_FILLS[i % 2], width=2)
    # Inner tangerine ring of sepals.
    for i in range(petals):
        a = phase + math.pi / petals + 2 * math.pi * i / petals
        px_, py_ = cx + 20 * math.cos(a), cy + 20 * math.sin(a)
        _codex_fill(image, _codex_ellipse_poly(px_, py_, 11, 5, a, 16), _CODEX_TANGERINE)
    # The eye: an almond of white sclera, a blue iris, a black pupil, a glint.
    almond = [(cx - 24 + 48 * t, cy - 14 * math.sin(math.pi * t)) for t in (i / 16 for i in range(17))]
    almond += [(cx + 24 - 48 * t, cy + 12 * math.sin(math.pi * t)) for t in (i / 16 for i in range(1, 16))]
    _codex_fill(image, almond, ("solid", SPECTRA6["white"]), width=2)
    draw.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), fill=SPECTRA6["blue"], outline=SPECTRA6["black"])
    draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=SPECTRA6["black"])
    draw.rectangle((cx - 6, cy - 7, cx - 4, cy - 5), fill=SPECTRA6["white"])
    # Lashes along the upper lid.
    for t in (0.18, 0.34, 0.5, 0.66, 0.82):
        x = cx - 24 + 48 * t
        y = cy - 14 * math.sin(math.pi * t)
        dx = (t - 0.5) * 10
        draw.line((x, y, x + dx, y - 6), fill=SPECTRA6["black"], width=1)


def _codex_paint_seeds(image: Image.Image, draw: ImageDraw.ImageDraw, rng: random.Random) -> None:
    """Striped seeds drifting off the crown on thread parachutes."""
    cx, cy = _CODEX_STEM_TOP[0], _CODEX_STEM_TOP[1] - 36
    for k in range(3):
        sx = cx + 70 + k * 28 + rng.uniform(-6, 6)
        sy = cy - 40 + k * 26 + rng.uniform(-6, 6)
        seed = _codex_ellipse_poly(sx, sy, 7, 4, 1.1)
        _codex_fill(image, seed, _CODEX_BANDS[(k * 2 + 1) % len(_CODEX_BANDS)])
        top = (sx - 5, sy - 14)
        for spread in (-8, -3, 3, 8):
            draw.line((sx - 1, sy - 3, top[0] + spread, top[1]), fill=SPECTRA6["black"], width=1)
        draw.arc((top[0] - 10, top[1] - 6, top[0] + 10, top[1] + 6), 180, 360, fill=SPECTRA6["black"], width=1)


def _codex_paint_labels(draw: ImageDraw.ImageDraw, rng: random.Random, anchors: list) -> None:
    """Dotted leaders from the specimen's parts to asemic labels — the
    diagrammatic apparatus of an encyclopedia plate, captioned in a script
    nobody can read."""
    x_label = _CODEX_PLATE[2] - 58
    for ax, ay in anchors:
        y = ay
        x = ax + 5
        while x < x_label - 6:
            draw.point((x, y), fill=SPECTRA6["black"])
            x += 3
        _codex_script(draw, x_label, y + 3, _CODEX_PLATE[2], xh=4, rng=rng,
                      fill=SPECTRA6["black"], max_words=1)


def _codex_paint_plate(image: Image.Image, rng: random.Random) -> None:
    draw = ImageDraw.Draw(image)
    _codex_paint_roots(image, draw, rng)
    band_offset = rng.randrange(len(_CODEX_BANDS))
    _codex_paint_stem(image, draw, band_offset)
    leaf_ts = (0.18, 0.38, 0.58, 0.76)
    anchors = []
    for i, t in enumerate(leaf_ts):
        x, y = _codex_stem_point(t)
        side = 1 if i % 2 == 0 else -1
        spec = _CODEX_LEAF_FILLS[(i + band_offset) % len(_CODEX_LEAF_FILLS)]
        nose = _codex_paint_fish_leaf(image, draw, x + side * (8 - 5 * t), y, side, spec, 32 - 6 * t)
        if side > 0:
            anchors.append(nose)
    _codex_paint_blossom(image, draw, rng)
    _codex_paint_seeds(image, draw, rng)
    _codex_paint_labels(draw, rng, anchors)
    # Plate caption under the specimen, in the script.
    _codex_script(draw, _CODEX_PLATE[0] + 40, _CODEX_CAPTION_BASE, _CODEX_PLATE[2] - 40,
                  xh=_CODEX_BODY_XH, rng=rng, fill=SPECTRA6["black"])


def _codex_paint_rainbow(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """A small rainbow beside the rubric heading, one foot dripping its bands
    into a puddle — a Serafinian object, familiar and then not."""
    cx, cy = _CODEX_RAINBOW_CENTRE
    inks = (SPECTRA6["red"], SPECTRA6["yellow"], SPECTRA6["green"], SPECTRA6["blue"])
    r = 40
    for ink in inks:
        draw.arc((cx - r, cy - r, cx + r, cy + r), 180, 360, fill=ink, width=5)
        r -= 5
    draw.arc((cx - 41, cy - 41, cx + 41, cy + 41), 180, 360, fill=SPECTRA6["black"], width=1)
    draw.arc((cx - 20, cy - 20, cx + 20, cy + 20), 180, 360, fill=SPECTRA6["black"], width=1)
    # The right foot runs: each band drips straight down into a puddle.
    for k, ink in enumerate(inks):
        x = cx + 38 - k * 5
        drop = 10 + (k * 7) % 12
        draw.line((x, cy, x, cy + drop), fill=ink, width=4)
        draw.ellipse((x - 2, cy + drop - 1, x + 2, cy + drop + 4), fill=ink)
    puddle = _codex_ellipse_poly(cx + 30, cy + 30, 16, 4, 0.0, 20)
    _codex_fill(image, puddle, _CODEX_BANDS[5])
    # The left foot is a pinned tab of paper: the rainbow is tacked to the page.
    draw.ellipse((cx - 42, cy - 3, cx - 34, cy + 5), fill=SPECTRA6["red"], outline=SPECTRA6["black"])


def _codex_paint_column(image: Image.Image, draw: ImageDraw.ImageDraw, rng: random.Random) -> None:
    """The untranslated text: a red rubric heading and a paragraph of script
    above the quote, and a further paragraph below it."""
    x0, x1 = _CODEX_COLUMN
    heading_base, heading_xh = _CODEX_HEADING
    _codex_script(draw, x0 + 30, heading_base, x1 - 30, xh=heading_xh, rng=rng,
                  fill=SPECTRA6["red"], width=2, max_words=4)
    for i, base in enumerate(_CODEX_UPPER_LINES):
        # The first two lines stop short of the rainbow vignette.
        end = _CODEX_RAINBOW_CENTRE[0] - 58 if i < 2 else x0 + (x1 - x0) * rng.uniform(0.45, 0.8)
        _codex_script(draw, x0 + (18 if i == 0 else 0), base, end, xh=_CODEX_BODY_XH, rng=rng,
                      fill=SPECTRA6["black"])
    for i, base in enumerate(_CODEX_LOWER_LINES):
        end = x1 if i == 0 else x0 + (x1 - x0) * rng.uniform(0.4, 0.7)
        _codex_script(draw, x0, base, end, xh=_CODEX_BODY_XH, rng=rng, fill=SPECTRA6["black"])


def _codex_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The one deciphered passage, in a pen hand, bracketed by blue rules."""
    x0, y0, x1, y1 = _CODEX_QUOTE_RECT
    quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    regular, italic, lines, line_height, size = fit_quote(
        draw, quote, quote_row.get("matched_text") or "", x1 - x0 - 16, y1 - y0 - 38,
        38, 15, 1.2, theme="codex",
    )
    block = len(lines) * line_height
    top = y0 + max(0, (y1 - y0 - 30 - block) // 2)
    draw_centred_styled_lines(draw, lines, x0=x0, x1=x1, top=top, line_height=line_height,
                              regular=regular, bold=italic, fill=SPECTRA6["black"],
                              accent=SPECTRA6["red"], min_inset=8)
    rule_y = top + block + 8
    mid = (x0 + x1) // 2
    draw.line((mid - 60, rule_y, mid + 60, rule_y), fill=SPECTRA6["blue"], width=1)
    draw.polygon([(mid, rule_y - 4), (mid + 4, rule_y), (mid, rule_y + 4), (mid - 4, rule_y)],
                 fill=SPECTRA6["red"])
    # Scaled with the body and clamped, so the byline stays visibly smaller
    # than a dense quote fitted near the 15 pt floor.
    byline = load_font(theme_font_candidates("codex", "quote_bold"),
                       max(_CODEX_BYLINE_MIN, min(_CODEX_BYLINE_MAX, int(size * 0.55))))
    draw_truncated_centred_byline(draw, quote_row, centre=mid, baseline=rule_y + 22,
                                  max_width=x1 - x0 - 16, font=byline, fill=SPECTRA6["blue"])


def _codex_paint_folio(draw: ImageDraw.ImageDraw, time_str: str) -> float:
    """The page number, bottom outer corner, in base-21 Serafinian numerals
    between two small flourishes. Returns where the pen stopped after the last
    digit, which is the column's right edge whatever digits the time needs."""
    digits = codex_page_digits(time_str)
    size = 20
    total = sum(_codex_numeral_advance(d, size) for d in digits)
    x = _CODEX_COLUMN[1] - total
    base = 462
    draw.arc((x - 24, base - 10, x - 6, base + 2), 200, 360, fill=SPECTRA6["blue"], width=1)
    for d in digits:
        x += _codex_numeral(draw, x, base, d, size=size, fill=SPECTRA6["red"])
    draw.arc((x + 2, base - 10, x + 20, base + 2), 180, 340, fill=SPECTRA6["blue"], width=1)
    return x


def render_codex_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A page of the Codex Seraphinianus (see the module section comment above)."""
    image = Image.new("RGB", (800, 480), color=SPECTRA6["white"])
    _codex_paint_page(image)
    rng = random.Random(_row_digest(quote_row))
    _codex_paint_plate(image, rng)
    draw = ImageDraw.Draw(image)
    _codex_paint_column(image, draw, rng)
    _codex_paint_rainbow(image, draw)
    _codex_paint_quote(image, draw, quote_row)
    _codex_paint_folio(draw, time_str)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("codex",), render=render_codex_frame)
