"""Code more than one theme uses, so no theme module imports another.

Each piece keeps the name it had in the theme that grew it: tarot's numerals,
astrarium's cream wash, vitrail's glass fill, codex's asemic script, metro's
ellipsis, lumon's phrase boxes, gantry's Lumen dot reader, the CRT raster, the
autochrome plate photo falls back to, and the gunmetal ink pair control's
concrete dithers to. Renaming would
churn the design notes and tests that cite them for no change in behaviour.
"""

from __future__ import annotations

import functools
import math
import random
import unicodedata

from PIL import Image, ImageDraw

from .._paths import BASE_DIR
from ..fonts import GLYPH_FALLBACKS, font_has_glyph, load_font, theme_font_candidates
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_4x4, BAYER_8x8, gray_pixel_access, pixel_access
from ..primitives import _flow_stroke_hash

# The autochrome garden is dithered against the FULL six-ink palette — the
# chroma is the ground, standing in for the process's dyed starch grains (see
# the ``autochrome`` section). The default palette would do the same; the
# constant makes it read as a decision rather than an omission.
AUTOCHROME_PLATE = BASE_DIR / "assets" / "autochrome_garden.png"
_AUTOCHROME_PALETTE = SPECTRA6_PALETTE

# A greyscale plate dithers to white+black only: control's concrete plinth
# (``_CONCRETE_PALETTE``).
_GUNMETAL_PALETTE = [SPECTRA6["white"], SPECTRA6["black"]]


# ---------------------------------------------------------------------------
# Astrarium frame
# ---------------------------------------------------------------------------
# The astrarium theme has its own render path (like ``diags``): an
# astronomical-clock dial on the left, the quote on the right, a datum strip
# along the bottom. The coloured ring quadrants are documented two-ink
# stipples (R+Y tangerine, R+G sepia, G+B teal), so ``snap_image_to_palette``
# is a no-op.


def _astrarium_paint_cream_wash(image: Image.Image) -> None:
    """Sparse 1-in-8 yellow Bayer wash over the white page background.

    Same Layer 0 recipe as ``dispatch``: ``BAYER_4x4 < 2`` flips ~12.5% of white to yellow so the page
    reads as faintly cream paper.
    """
    px = pixel_access(image)
    w, h = image.size
    for y in range(h):
        row = BAYER_4x4[y % 4]
        for x in range(w):
            if row[x % 4] < 2 and px[x, y] == SPECTRA6["white"]:
                px[x, y] = SPECTRA6["yellow"]


_TAROT_ROMAN_NUMERALS = {
    1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI",
    7: "VII", 8: "VIII", 9: "IX", 10: "X", 11: "XI", 12: "XII",
}


def _vitrail_pane_ink(x: int, y: int, spec: tuple) -> tuple[int, int, int]:
    """Return the on-palette ink for pixel (x, y) within a pane, per the fill
    spec — solid, 2-ink stipple, or 3-ink Bayer partition. The stipple maths
    mirror _fill_swatch_stipple / _fill_swatch_stipple_3way exactly (absolute
    x/y so the Bayer phase stays continuous across adjacent panes), so the
    irregular polygon panes carry the same documented recipes the rectangular
    swatch fills do."""
    kind = spec[0]
    if kind == "solid":
        return spec[1]
    if kind == "2":
        _, dark, light, density = spec
        if density <= 0.25:
            return light if (x % 2 == 0 and y % 2 == 0) else dark
        if density >= 0.5:
            return dark if (x + y) % 2 == 0 else light
        return light if BAYER_4x4[y % 4][x % 4] < round(density * 16) else dark
    # "3" — 3-ink Bayer partition.
    _, ink_a, ink_b, ink_c, density_a, density_b = spec
    cell = BAYER_4x4[y % 4][x % 4]
    if cell < round(density_a * 16):
        return ink_a
    if cell < round((density_a + density_b) * 16):
        return ink_b
    return ink_c


def _vitrail_fill_polygon(image: Image.Image, polygon: list, spec: tuple) -> None:
    """Fill an arbitrary (irregular quadrilateral or triangular) glass shape
    with its jewel tone, clipped to the polygon via a 1-bit mask so the stipple
    only lands inside the leaded shape and never bleeds into a neighbour."""
    xs = [int(p[0]) for p in polygon]
    ys = [int(p[1]) for p in polygon]
    w, h = image.size
    x0 = max(0, min(xs))
    y0 = max(0, min(ys))
    x1 = min(w, max(xs) + 1)
    y1 = min(h, max(ys) + 1)
    if x1 <= x0 or y1 <= y0:
        return
    mask = Image.new("1", (x1 - x0, y1 - y0), 0)
    ImageDraw.Draw(mask).polygon([(int(px) - x0, int(py) - y0) for px, py in polygon], fill=1)
    mpx = pixel_access(mask)
    ipx = pixel_access(image)
    for yy in range(y1 - y0):
        ay = y0 + yy
        for xx in range(x1 - x0):
            if mpx[xx, yy]:
                ipx[x0 + xx, ay] = _vitrail_pane_ink(x0 + xx, ay, spec)


def _metro_ellipsize(draw, text: str, font, max_width: int) -> str:
    """Trim text to a measured pixel budget, preserving an ellipsis."""
    text = str(text)
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    if draw.textlength(ellipsis, font=font) > max_width:
        return ""
    while text and draw.textlength(text.rstrip() + ellipsis, font=font) > max_width:
        text = text[:-1]
    return text.rstrip(" ,;:") + ellipsis
_CODEX_WORD_OVERHEAD = 1.6                   # x-heights: lead-in + exit tail + loop overshoot
# How far a line of script can reach from its baseline, in x-heights. Every
# letter shape and diacritic is drawn inside these bounds, and every stacked
# pair of lines on the page is pitched at least ``BELOW·xh_upper +
# ABOVE·xh_lower`` apart, so an ascender can never cross the descender of the
# line above it (fenced by ``TestCodexFrame``).
_CODEX_REACH_ABOVE = 2.1
_CODEX_REACH_BELOW = 1.5


def _codex_letter_points(x0: float, base: float, xh: float, rng: random.Random) -> tuple[list, float, bool]:
    """One asemic letter as a pen path that starts and ends on the baseline.

    ``x = x0 + w·t + r·sin 2πt`` swings forward on the way up and back on the
    way down, crossing its own stroke (a loop) whenever ``r > w/4``. The vertical
    excursion is up for an ordinary letter, much taller for an ascender and
    below the line for a descender, so a line of these carries the rhythm of a
    cursive hand without being one. The third return value flags an ascender
    or descender, over which no diacritic is placed.
    """
    kind = rng.random()
    w = xh * rng.uniform(0.7, 1.25)
    above, below = _CODEX_REACH_ABOVE, _CODEX_REACH_BELOW
    if kind < 0.14:
        h, sign, r = xh * rng.uniform(above - 0.5, above), -1, w * rng.uniform(0.32, 0.45)   # ascender loop
    elif kind < 0.24:
        h, sign, r = xh * rng.uniform(below - 0.4, below), 1, w * rng.uniform(0.3, 0.42)    # descender loop
    elif kind < 0.62:
        h, sign, r = xh * rng.uniform(0.8, 1.1), -1, w * rng.uniform(0.28, 0.4)      # small loop
    else:
        h, sign, r = xh * rng.uniform(0.7, 1.0), -1, w * rng.uniform(0.0, 0.18)      # hump
    steps = 14
    pts = []
    for i in range(steps + 1):
        t = i / steps
        x = x0 + w * t + r * math.sin(2 * math.pi * t)
        y = base + sign * h * (1 - math.cos(2 * math.pi * t)) / 2
        pts.append((x, y))
    return pts, x0 + w, kind < 0.24


def _codex_script(draw: ImageDraw.ImageDraw, x: float, base: float, x_end: float, *,
                  xh: float, rng: random.Random, fill, width: int = 1,
                  max_words: int | None = None) -> float:
    """Write a line of asemic script from ``x`` to at most ``x_end``.

    Words of 2–7 letters joined in one continuous stroke, the pen lifted
    between words; an occasional diacritic dot or hook above a letter, the
    furniture every alphabet grows. Returns the x where the pen stopped.
    """
    words = 0
    while x < x_end:
        n = rng.randint(2, 7)
        # Never start a word that cannot finish inside the line. The budget is
        # the worst case (widest letter, 1.25 x-heights, plus lead-in, exit tail
        # and loop overshoot), so the ink provably stops at ``x_end``.
        if x + (n * 1.25 + _CODEX_WORD_OVERHEAD) * xh > x_end:
            n = int((x_end - x) / xh - _CODEX_WORD_OVERHEAD) * 4 // 5
            if n < 2:
                break
        pts = [(x, base)]
        lead = xh * 0.35
        pts.append((x + lead, base - xh * 0.25))
        cx = x + lead
        marks = []
        for _ in range(n):
            letter, cx, tall = _codex_letter_points(cx, base, xh, rng)
            pts.extend(letter[1:])
            # Diacritics sit over short letters only, where there is headroom
            # inside the reach bound; over an ascender they would collide
            # with it or climb out of the line.
            if not tall and rng.random() < 0.14:
                marks.append((letter[len(letter) // 2][0], base - xh * (_CODEX_REACH_ABOVE - 0.45)))
        pts.append((cx + xh * 0.4, base - xh * 0.2))
        draw.line(pts, fill=fill, width=width, joint="curve")
        for mx, my in marks:
            if rng.random() < 0.5:
                d = max(1, width)
                draw.ellipse((mx - d, my - d, mx + d, my + d), fill=fill)
            else:
                draw.arc((mx - xh * 0.5, my - xh * 0.4, mx + xh * 0.5, my + xh * 0.4),
                         200, 340, fill=fill, width=width)
        x = cx + xh * rng.uniform(1.2, 1.9)
        words += 1
        if max_words is not None and words >= max_words:
            break
    return x


def _crt_paint_scanlines(image: Image.Image, rect, ground, *, period: int = 4, phase: int = 0) -> None:
    """Raster lines over a CRT: every ``period``-th row inside ``rect`` goes
    black where it holds one of the ``ground`` inks, so glyphs and graphics
    painted over the phosphor stay solid and the type keeps its weight. One
    in four is the coarsest spacing that still reads as lines rather than
    stripes at the panel's pitch."""
    x0, y0, x1, y1 = rect
    width, height = image.size
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(width, x1), min(height, y1)
    if x1 <= x0 or y1 <= y0:
        return
    px = pixel_access(image)
    black = SPECTRA6["black"]
    ground = set(ground)
    for y in range(y0, y1):
        if (y - y0 + phase) % period:
            continue
        for x in range(x0, x1):
            if px[x, y] in ground:
                px[x, y] = black


def _lumon_hover_boxes(draw: ImageDraw.ImageDraw, placed) -> list:
    """One box per run of bold chunks on a line — the phrase, not each
    word — trimmed to the run's inked extent."""
    boxes = []
    run = None
    for x, y, chunk, font, is_bold, w, lh in placed:
        if not is_bold or not chunk.strip():
            if run is not None and (not is_bold or run[1] != y):
                boxes.append(run)
                run = None
            if is_bold and run is not None:
                run = (run[0], run[1], x + w, run[3])
            continue
        lead = draw.textlength(chunk, font=font) - draw.textlength(chunk.lstrip(), font=font)
        trail = draw.textlength(chunk, font=font) - draw.textlength(chunk.rstrip(), font=font)
        x0, x1 = round(x + lead), round(x + w - trail)
        if run is not None and run[1] == y:
            run = (run[0], y, x1, lh)
        else:
            if run is not None:
                boxes.append(run)
            run = (x0, y, x1, lh)
    if run is not None:
        boxes.append(run)
    return [(x0 - 3, y - 2, x1 + 2, y + lh - 6) for x0, y, x1, lh in boxes]


def _autochrome_paint_garden_fallback(image: Image.Image) -> None:
    """A stripped install still gets a garden-shaped colour field: the plate's
    three bands (sky hazing to white, tree line and lawn, a bloom-scattered
    bed) as ``BAYER_8x8`` density ramps, so the theme still reads as a colour
    picture rather than a blank ground.
    """
    px = pixel_access(image)
    white, black, blue, green, yellow, red = (
        SPECTRA6[c] for c in ("white", "black", "blue", "green", "yellow", "red"))
    horizon, beds = 192, 250
    for y in range(480):
        row = BAYER_8x8[y % 8]
        if y < horizon:
            # Sky: blue density falling toward the horizon haze.
            density = 0.42 * (1.0 - y / horizon) ** 0.8
            ink, ground = blue, white
        elif y < beds:
            density = 0.34
            ink, ground = green, white
        else:
            # Lawn deepening toward the viewer, warmed by the beds.
            t = (y - beds) / (480 - beds)
            density = 0.30 + 0.24 * t
            ink, ground = green, yellow
        cut = 64 * density
        for x in range(800):
            px[x, y] = ink if row[x % 8] < cut else ground
    # A drift of blooms across the beds, and the shadow under them: painted
    # from a positional hash so the fallback stays deterministic.
    for y in range(beds, 480):
        for x in range(800):
            h = _flow_stroke_hash(x // 3, y // 3, 11)
            if h < 0.020:
                px[x, y] = red
            elif h < 0.032:
                px[x, y] = yellow
            elif h < 0.044:
                px[x, y] = black


# ---------------------------------------------------------------------------
# The Lumen dot-matrix reader (gantry, platform)
# ---------------------------------------------------------------------------
# Lumen is a 5x7 LED matrix with its dots on a strict grid a tenth of an em
# apart. Rather than set it as type, the LED themes render each glyph once,
# supersampled, read the grid centres back as lit cells, and draw the dots
# themselves on a pitch of their own choosing (see ``gantry`` in
# docs/themes.md).

_GANTRY_SAMPLE = 8           # supersampling factor when reading the font's dots
# Characters the face lacks, beyond what render's glyph fallbacks already
# replaced: a sign can only show what its font carries.
_GANTRY_STANDINS = {**GLYPH_FALLBACKS, "œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE",
                    "£": "L", "ß": "ss"}
# Two-character sequences the face shapes into one glyph. Only the arrows: a
# motorway sign points, and the face's other ligatures (a heart, a smiley,
# maths operators) would turn the sign into a font demo.
_GANTRY_LIGATURES = ("->", "<-", "=>")


def _gantry_font():
    return load_font(theme_font_candidates("gantry", "quote_regular"), size=10 * _GANTRY_SAMPLE)


@functools.lru_cache(maxsize=1024)
def _gantry_glyph(ch: str) -> tuple[int, frozenset[tuple[int, int]]]:
    """``(ink width, lit cells)`` of one character or ligature, cells as
    ``(col, row)`` with the leftmost ink column at 0. Blank glyphs come back
    as width 0.

    A ligature (``_GANTRY_LIGATURES``) is drawn as its two-character string,
    which the face's ``liga`` feature shapes into one wide glyph; Pillow's
    wheels carry the raqm shaper that applies it. Without raqm the pair is
    read as its two characters, still legible.
    """
    s = _GANTRY_SAMPLE
    font = _gantry_font()
    span = 7 * len(ch) + 3
    canvas = Image.new("L", (s * span, s * 12), 0)
    # One cell of slack on the left catches any negative side bearing.
    ImageDraw.Draw(canvas).text((s, 0), ch, font=font, fill=255)
    px = gray_pixel_access(canvas)
    cells = set()
    for row in range(12):
        for col in range(span):
            if px[col * s + s // 2, row * s + s // 2] > 127:
                cells.add((col, row))
    if not cells:
        return 0, frozenset()
    left = min(c for c, _ in cells)
    right = max(c for c, _ in cells)
    return right - left + 1, frozenset((c - left, r) for c, r in cells)


def _gantry_chars(ch: str) -> str:
    """``ch`` as characters the sign's face can show."""
    if ch in _GANTRY_STANDINS:
        return _GANTRY_STANDINS[ch]
    if font_has_glyph(_gantry_font(), ch):
        return ch
    base = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode("ascii")
    return base or "?"


def _gantry_tokens(text: str) -> list[str]:
    """``text`` as the glyphs the sign draws: the arrow ligatures as one
    token each, every other character as what the face can show."""
    tokens: list[str] = []
    i = 0
    while i < len(text):
        pair = text[i:i + 2]
        if pair in _GANTRY_LIGATURES:
            tokens.append(pair)
            i += 2
            continue
        ch = text[i]
        tokens.extend([ch] if ch.isspace() else list(_gantry_chars(ch)))
        i += 1
    return tokens


@functools.lru_cache(maxsize=16)
def _gantry_dot(diameter: int) -> tuple[tuple[int, int], ...]:
    """Pixel offsets of one round LED of ``diameter``."""
    centre = (diameter - 1) / 2
    limit = (diameter / 2) ** 2 - 0.2
    return tuple((dx, dy) for dy in range(diameter) for dx in range(diameter)
                 if diameter <= 2 or (dx - centre) ** 2 + (dy - centre) ** 2 <= limit)
