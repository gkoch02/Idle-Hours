"""The ``escritoire`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import functools
import math
import random
from itertools import pairwise

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ..fonts import _font_ascent, load_font, normalize_dashes, theme_font_candidates
from ..furniture import _row_digest, fallback_title
from ..layout import _trim_line, choose_layout, fit_quote_balanced, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, gray_pixel_access, pixel_access, snap_image_to_palette
from ..primitives import _bayer_threshold_field, _shift_no_wrap
from ..spec import FrameSpec
from ._shared import _codex_script, _metro_ellipsize

# ---------------------------------------------------------------------------
# escritoire — a handwritten letter on a writing desk, seen at an angle
# ---------------------------------------------------------------------------
# The quote is the last paragraph of a letter on a mahogany desk, seen from
# the writer's chair: the sheet is a foreshortened, slightly rolled
# trapezoid, with out-of-focus brass beyond it, a second page under it and a
# fountain pen across it. Full design notes: docs/themes.md (``escritoire``).
#
# **Only the near half of the page is legible, on purpose.** At the far edge
# a glyph is 60% of its near-edge size, which is noise at panel resolution, so
# the far band carries the letter's earlier lines as faint asemic script
# (``_codex_script``, seeded from the row) and the quote sits in the near band.
#
# **The page is laid out flat, then warped.** The quote is fitted on an
# upright 900x560 sheet at 2x (``fit_quote_balanced``) into three ``"L"``
# masks (prose, phrase, faint), each carried through one bicubic perspective
# transform, box-reduced and thresholded so every ink pixel lands solid. Don't
# warp a finished RGB frame: the resampled glyph edges become a grey fringe
# that the palette snap turns into a ragged stipple.
#
# **Inks.** Prose black, matched phrase blue (fountain-pen ink). The paper is
# white with a yellow stipple warming toward the near corner. The desk is
# black with a red stipple pooled under the lamp, 30% of it yellow (red alone
# reads aubergine). The brass is a blurred luminance field stippled on a
# black-red-yellow-white ramp; the pen's gold is R+Y 5/8:3/8.
#
# **Cost.** The scene is quote-independent and cached for in-process callers,
# keyed on the painters (the ``expanse`` convention) so the decoration fence's
# neutered painters rebuild it. The appliance renders cold, so the smooth
# fields are computed at reduced resolution and the per-pixel passes are
# confined to their bounding boxes.
#
# No clock: ``time_str`` is deleted at entry. Fixed geometry, composed at
# 800x480 and NEAREST-downsampled.

_ESCRITOIRE_SEED = 0x45534352          # ESCR
_ESCRITOIRE_SS = 2                     # supersample for the sheet masks
_ESCRITOIRE_SHEET = (900, 560)         # the upright sheet, in sheet units
# The sheet's corners on the canvas (TL, TR, BR, BL). The near corners run off
# the panel, as a sheet does when it is close enough to write on.
# They are a flat sheet turned 2.5 degrees on the desk, projected through a
# level camera, so the vanishing points of the rows and the sides share one
# horizontal horizon; a freehand quad fans the writing off the paper's edges.
# The page under it is the same sheet turned 2.2 degrees further.
_ESCRITOIRE_QUAD = ((157, 150), (693, 136), (943, 481), (-12, 527))
_ESCRITOIRE_LAMP = (560, 150)          # the light pool's centre on the desk
_ESCRITOIRE_LEFT = 100                 # the writing's left margin, sheet units
_ESCRITOIRE_MEASURE = 600              # the quote's measure, sheet units
_ESCRITOIRE_FAINT_TOP = 62             # the first faint line's baseline
_ESCRITOIRE_FAINT_PITCH = 44
_ESCRITOIRE_BAND = (196, 520)          # the near band the quote is centred in
# (font_max, font_min) per layout, in sheet units. The hero sizes are large on
# purpose: a short quote set at a dense size leaves the near band half empty.
_ESCRITOIRE_SIZES = {"hero": (64, 38), "standard": (50, 30), "dense": (42, 26)}
# The size of last resort. The clock never picks a quote that needs it, but the
# curator previews raw rows of up to ~470 characters, which overflow the band
# at every layout floor; they get smaller rather than running off the page.
_ESCRITOIRE_FLOOR = 18
_ESCRITOIRE_SIG_MAX = 38               # the signature's largest size, sheet units
_ESCRITOIRE_TITLE_MAX = 26             # the title's under it
_ESCRITOIRE_LINE_MULT = 1.36
_ESCRITOIRE_FIELD_SCALE = 4            # the smooth fields' downsampling factor
# The pen, nib tip to cap end, and its half-width at the nib end.
_ESCRITOIRE_PEN = ((262.0, 212.0), (738.0, 102.0), 10.0)
# A second sheet under the letter, turned a few degrees further, so a wedge of
# it shows along the far edge and past the top-right corner: a page of the
# same letter, and the cheapest cue that the sheet lies on a real desk.
_ESCRITOIRE_UNDER_QUAD = ((166, 153), (696, 126), (959, 451), (27, 534))
# The brass beyond the sheet, each a turned piece given as a lathe profile:
# its axis x and (y, half-width) knots down the silhouette, joined linearly.
# A knot pair a few pixels apart is a step in the turning, where a moulding
# line falls. Tops stay on the panel: pieces cut off by the top edge read as
# lit columns, not as things on a desk.
_ESCRITOIRE_BRASS = (
    # The inkwell: a ball finial on a domed lid, a squat body, a stepped foot.
    (560, ((30, 0), (31, 5), (38, 7), (44, 4), (47, 10), (52, 22), (60, 31), (66, 36), (70, 34),
           (74, 38), (132, 38), (136, 43), (146, 44), (150, 40))),
    # The pen cup: a rolled rim, a band at the waist, a flared foot.
    (672, ((40, 30), (46, 30), (48, 27), (94, 27), (96, 30), (102, 30), (104, 27), (136, 28),
           (140, 33), (150, 35), (154, 32))),
    # The sander: a pierced dome, a waisted neck, a bell foot on the desk
    # beyond the sheet's right edge, where its reflection shows.
    (756, ((54, 0), (56, 12), (62, 20), (70, 22), (74, 15), (92, 13), (110, 18), (140, 30),
           (154, 36), (162, 37), (166, 33))),
)
# Lamp glints on the brass, which the blur turns into soft bokeh: (x, y, r).
_ESCRITOIRE_GLINTS = ((546, 30, 4), (543, 58, 5), (545, 100, 5), (657, 44, 4), (659, 116, 4),
                      (746, 66, 4), (742, 150, 5))
# The two pens standing in the cup: where each leaves the rim, and where it
# leaves the panel.
_ESCRITOIRE_CUP_PENS = (((662, 42), (638, -4)), ((684, 42), (706, -4)))
# The pens lying further back on the left: nib tip to cap end, half-width.
_ESCRITOIRE_BACK_PENS = (((330, 120), (64, 150), 9), ((236, 64), (18, 92), 8))
_ESCRITOIRE_SCENE: dict = {}


def _escritoire_solve(a: list, b: list) -> list:
    """Solve a small dense linear system by Gaussian elimination."""
    n = len(a)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


@functools.lru_cache(maxsize=None)
def _escritoire_coeffs(scale: int = 1) -> tuple:
    """Pillow's PERSPECTIVE coefficients mapping the canvas onto the sheet
    (output to input, which is the direction Pillow samples in)."""
    sw, sh = _ESCRITOIRE_SHEET
    sheet = ((0, 0), (sw, 0), (sw, sh), (0, sh))
    a, b = [], []
    for (x, y), (u, v) in zip(_ESCRITOIRE_QUAD, sheet, strict=True):
        x, y, u, v = x * scale, y * scale, u * scale, v * scale
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b += [u, v]
    return tuple(_escritoire_solve(a, b))


def _escritoire_field(size, fn, step: int = _ESCRITOIRE_FIELD_SCALE) -> Image.Image:
    """A smooth ``"L"`` field from ``fn(x, y) -> 0..1``, sampled every
    ``_ESCRITOIRE_FIELD_SCALE`` pixels and scaled up bilinearly. The lamp pool
    and the paper's warmth have no detail finer than tens of pixels, and
    evaluating them per pixel was most of a cold render."""
    width, height = size
    cols, rows = width // step + 2, height // step + 2
    data = bytes(int(255 * min(1.0, max(0.0, fn(x * step, y * step))))
                 for y in range(rows) for x in range(cols))
    small = Image.frombytes("L", (cols, rows), data)
    return small.resize((cols * step, rows * step), Image.Resampling.BILINEAR).crop((0, 0, width, height))


def _escritoire_stipple(density: Image.Image) -> Image.Image:
    """``"L"`` density (0-255) to a 0/255 ordered-dither mask on ``BAYER_8x8``."""
    threshold = _ESCRITOIRE_SCENE.get(("tile", density.size))
    if threshold is None:
        threshold = _bayer_threshold_field(density.size)
        _ESCRITOIRE_SCENE[("tile", density.size)] = threshold
    return ImageChops.subtract(density, threshold).point(lambda v: 255 if v else 0)


def _escritoire_sheet_mask(size, quad=_ESCRITOIRE_QUAD) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon(quad, fill=255)
    return mask


def _escritoire_paper_mask(size) -> Image.Image:
    """Both sheets: everything the brass sits behind."""
    return ImageChops.lighter(_escritoire_sheet_mask(size), _escritoire_sheet_mask(size, _ESCRITOIRE_UNDER_QUAD))


def _escritoire_paint_desk(image: Image.Image) -> None:
    """Mahogany: black with a red stipple pooled under the lamp, a share of
    yellow inside the red, and a grain that wanders.

    Red over black alone reads as aubergine, so a fixed share of every lit run
    is yellow (the print-sepia direction). The share rides the same tile read
    as the red (``tile < d * share`` is a subset of ``tile < d``), so the hue
    holds down the pool's falloff. The grain drifts with x so it does not read
    as ruled lines; it is computed at half resolution, the pool at quarter."""
    width, height = image.size
    lx, ly = _ESCRITOIRE_LAMP
    pool = _escritoire_field(
        (width, height), lambda x, y: max(0.0, 1.0 - math.hypot(x - lx, (y - ly) * 1.6) / 520) ** 1.6)
    grain = _escritoire_field(
        (width, height),
        lambda x, y: (0.24 + 0.09 * (0.5 + 0.5 * math.sin(
            y * 0.55 + 1.8 * math.sin(y * 0.07) + 1.3 * math.sin(x * 0.011 + y * 0.031)))) / 0.33,
        step=2)
    density = ImageChops.multiply(pool, grain).point(lambda v: int(255 * 0.04 + v * 0.33))
    image.paste(SPECTRA6["black"], (0, 0, width, height))
    image.paste(SPECTRA6["red"], (0, 0), _escritoire_stipple(density))
    image.paste(SPECTRA6["yellow"], (0, 0), _escritoire_stipple(density.point(lambda v: v * 30 // 100)))


def _escritoire_paint_shadow(image: Image.Image) -> None:
    """The sheets' shadow, cast down and to the right onto the desk: a soft
    black stipple, painted before the brass so it falls on the desk only.

    The shift must not wrap (hence ``_shift_no_wrap``, not ``ImageChops.offset``):
    the sheet runs off the bottom and right of the panel."""
    paper = _escritoire_paper_mask(image.size)
    shadow = _shift_no_wrap(paper, 6, 9).filter(ImageFilter.GaussianBlur(7))
    image.paste(SPECTRA6["black"], (0, 0), _escritoire_stipple(ImageChops.subtract(shadow, paper)))


def _escritoire_lathe(lp, ap, cx: float, knots, *, gain: float = 1.0, mirror_at: float | None = None,
                      fade: float = 0.0) -> None:
    """Shade one turned brass piece into the ``lum`` / ``alpha`` pixel access
    objects: across each row a cylinder's falloff with a narrow glint left of
    the axis, darkened on the rows where the profile steps (the mouldings).
    With ``mirror_at`` it paints the piece's reflection instead, flipped about
    that y and fading out over ``fade`` pixels."""
    ys = [k[0] for k in knots]
    steps = {round(ys[i]) for i in range(1, len(ys) - 1) if ys[i + 1] - ys[i] <= 6 or ys[i] - ys[i - 1] <= 6}

    def half_width(y):
        for (y0, w0), (y1, w1) in pairwise(knots):
            if y0 <= y <= y1:
                return w0 + (w1 - w0) * (y - y0) / max(1e-6, y1 - y0)
        return 0.0

    top, foot = ys[0], ys[-1]
    rows = range(int(top), int(foot) + 1)
    for y in rows:
        hw = half_width(y)
        if hw < 0.5:
            continue
        ring = 0.72 if any(abs(y - k) <= 1 for k in steps) else 1.0
        if mirror_at is None:
            out_y, a = y, 255
        else:
            out_y = int(2 * mirror_at - y)
            a = int(255 * 0.45 * max(0.0, 1 - (out_y - mirror_at) / fade))
            if a <= 0:
                continue
        if not 0 <= out_y < 480:          # the scene is always composed at 800x480
            continue
        for x in range(max(0, int(cx - hw)), min(800, int(cx + hw) + 1)):
            t = (x - cx) / hw
            if abs(t) > 1:
                continue
            body = math.sqrt(1 - t * t)
            glint = math.exp(-((t + 0.42) / 0.15) ** 2)
            v = int(255 * gain * ring * min(1.0, 0.1 + 0.42 * body + 0.5 * glint))
            if v > lp[x, out_y]:
                lp[x, out_y] = v
            if a > ap[x, out_y]:
                ap[x, out_y] = a


def _escritoire_pen_quad(nx: float, ny: float, ux: float, uy: float,
                         t0: float, t1: float, w0: float, w1: float) -> list[tuple[float, float]]:
    """A band of a pen lying from (nx, ny) along the unit vector (ux, uy): from
    t0 to t1 along the shaft, half-width w0 at one end and w1 at the other."""
    px_, py_ = -uy, ux
    return [(nx + ux * t0 + px_ * w0, ny + uy * t0 + py_ * w0),
            (nx + ux * t1 + px_ * w1, ny + uy * t1 + py_ * w1),
            (nx + ux * t1 - px_ * w1, ny + uy * t1 - py_ * w1),
            (nx + ux * t0 - px_ * w0, ny + uy * t0 - py_ * w0)]


def _escritoire_paint_brass(image: Image.Image) -> None:
    """The out-of-focus things on the far side of the desk: three turned brass
    pieces with their tops on the panel, lamp glints that the blur turns into
    bokeh, reflections on the polished desk, and two pens lying further back.
    All of it is shaded as a luminance field and an alpha field, blurred
    together, then stippled on a black-red-yellow-white ramp."""
    width, height = image.size
    lum = Image.new("L", (width, height), 0)
    alpha = Image.new("L", (width, height), 0)
    lp, ap = gray_pixel_access(lum), gray_pixel_access(alpha)
    for cx, knots in _ESCRITOIRE_BRASS:
        _escritoire_lathe(lp, ap, cx, knots)
        foot = knots[-1][0]
        _escritoire_lathe(lp, ap, cx, knots, gain=0.8, mirror_at=foot, fade=40)
    draw_l, draw_a = ImageDraw.Draw(lum), ImageDraw.Draw(alpha)
    for gx, gy, r in _ESCRITOIRE_GLINTS:
        draw_l.ellipse((gx - r, gy - r, gx + r, gy + r), fill=255)
    # The back pens. Dark barrels vanish on a dark desk, so each is drawn by
    # what the lamp catches: a gold nib and section, a gold cap band and
    # finial, and a bright line along the top of the barrel.
    for (nx, ny), (ex, ey), r in _ESCRITOIRE_BACK_PENS:
        length = math.hypot(ex - nx, ey - ny)
        ux, uy = (ex - nx) / length, (ey - ny) / length
        quad = functools.partial(_escritoire_pen_quad, nx, ny, ux, uy)
        draw_a.polygon(quad(0, length, 1, r), fill=255)
        draw_l.polygon(quad(30, length, r * 0.8, r), fill=8)
        draw_l.polygon(quad(0, 34, 1, r * 0.75), fill=150)                  # nib + section
        draw_l.polygon(quad(length * 0.62, length * 0.62 + 7, r, r), fill=150)  # cap band
        draw_l.polygon(quad(length - 6, length, r, r), fill=150)            # finial
        hl = quad(40, length * 0.92, r * 0.45, r * 0.5)
        draw_l.line([hl[0], hl[1]], fill=235, width=2)
    # Two pens standing in the cup, which is what makes it read as one: dark
    # shafts leaning out of the rim, each drawn by its highlight.
    for (bx, by), (tx, ty) in _ESCRITOIRE_CUP_PENS:
        draw_a.line([(bx, by), (tx, ty)], fill=255, width=7)
        draw_l.line([(bx, by), (tx, ty)], fill=8, width=7)
        draw_l.line([(bx - 2, by), (tx - 2, ty)], fill=225, width=1)
    lum = lum.filter(ImageFilter.GaussianBlur(3))
    alpha = alpha.filter(ImageFilter.GaussianBlur(4))
    # Ramp black < red < yellow < white, two adjacent inks mixed by the tile.
    ramp = (SPECTRA6["black"], SPECTRA6["red"], SPECTRA6["yellow"], SPECTRA6["white"])
    px, lp, ap = pixel_access(image), gray_pixel_access(lum), gray_pixel_access(alpha)
    paper = gray_pixel_access(_escritoire_paper_mask((width, height)))
    bx0, by0, bx1, by1 = alpha.getbbox() or (0, 0, 0, 0)
    for y in range(by0, by1):
        row = BAYER_8x8[y % 8]
        for x in range(bx0, bx1):
            a = ap[x, y]
            if a < 8 or paper[x, y]:
                continue
            rank = row[x % 8]
            if rank >= a / 4:
                continue
            level = lp[x, y] / 255 * 3
            step = min(2, int(level))
            px[x, y] = ramp[step + 1] if rank < (level - step) * 64 else ramp[step]


def _escritoire_paint_sheet(image: Image.Image) -> None:
    """The paper: the page underneath, the letter's shadow falling on it, then
    the letter. Both are white with a yellow stipple warming toward the near,
    shadowed corner and thinning under the lamp; the page underneath carries
    more yellow, so the two separate without an outline."""
    sw, sh = _ESCRITOIRE_SHEET
    a, b, c, d, e, f, g, h = _escritoire_coeffs()

    def warm(x, y):
        den = g * x + h * y + 1
        if den <= 1e-6:
            return 0.0
        u, v = (a * x + b * y + c) / den, (d * x + e * y + f) / den
        return 0.05 + 0.22 * min(1.0, max(0.0, 0.55 * v / sh + 0.45 * (1 - u / sw))) ** 1.3

    warmth = _escritoire_field(image.size, warm)
    under = _escritoire_sheet_mask(image.size, _ESCRITOIRE_UNDER_QUAD)
    sheet = _escritoire_sheet_mask(image.size)
    image.paste(SPECTRA6["white"], (0, 0), under)
    image.paste(SPECTRA6["yellow"], (0, 0),
                ImageChops.multiply(_escritoire_stipple(warmth.point(lambda v: min(255, v + 46))), under))
    # The letter's own shadow, on the page under it.
    shadow = _shift_no_wrap(sheet, 4, 6).filter(ImageFilter.GaussianBlur(4))
    shadow = ImageChops.multiply(ImageChops.subtract(shadow, sheet), under)
    image.paste(SPECTRA6["black"], (0, 0), _escritoire_stipple(shadow.point(lambda v: v * 3 // 4)))
    image.paste(SPECTRA6["white"], (0, 0), sheet)
    image.paste(SPECTRA6["yellow"], (0, 0), ImageChops.multiply(_escritoire_stipple(warmth), sheet))


def _escritoire_scene() -> Image.Image:
    """The desk, its shadow, the brass and the empty sheet: identical for
    every quote. Cached keyed on the painters (see the section comment)."""
    key = (_escritoire_paint_desk, _escritoire_paint_shadow, _escritoire_paint_brass, _escritoire_paint_sheet)
    cached = _ESCRITOIRE_SCENE.get("frame")
    if cached is not None and cached[0] == key:
        return cached[1]
    scene = Image.new("RGB", (800, 480), SPECTRA6["black"])
    _escritoire_paint_desk(scene)
    _escritoire_paint_shadow(scene)
    _escritoire_paint_brass(scene)
    _escritoire_paint_sheet(scene)
    _ESCRITOIRE_SCENE["frame"] = (key, scene)
    return scene


def _escritoire_layout(quote_row: dict) -> dict:
    """Fit the quote and its signature into the near band of the upright
    sheet. Returns the fitted fonts, the wrapped lines, and the block's top and
    bottom in sheet units (``block``)."""
    ss = _ESCRITOIRE_SS
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    text = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    match_text = quote_row.get("matched_text") or ""
    font_max, font_min = _ESCRITOIRE_SIZES[choose_layout(text)]
    band_top, band_bottom = _ESCRITOIRE_BAND
    author = quote_row.get("author") or ""
    title = quote_row.get("title") or fallback_title(quote_row) or ""
    # Room for the signature as it will actually be set: one line per field
    # present, at the capped sizes, plus the gap above it. An upper bound, so
    # the fitted block plus its signature cannot outgrow the band.
    reserve = (int(_ESCRITOIRE_SIG_MAX * 1.15) if author else 0) + (int(_ESCRITOIRE_TITLE_MAX * 1.2) if title else 0)
    if reserve:
        reserve += int(font_max * _ESCRITOIRE_LINE_MULT * 0.3)
    room = (band_bottom - band_top - reserve) * ss

    def fit(floor):
        return fit_quote_balanced(probe, text, match_text, _ESCRITOIRE_MEASURE * ss, room,
                                  font_max * ss, floor * ss, _ESCRITOIRE_LINE_MULT, theme="escritoire")

    reg, bold, wrapped, line_h, size, _ = fit(font_min)
    if len(wrapped) * line_h > room and font_min > _ESCRITOIRE_FLOOR:
        reg, bold, wrapped, line_h, size, _ = fit(_ESCRITOIRE_FLOOR)
    # The signature follows the hand's size but stops short of shouting on a
    # hero quote, and keeps the byline floors legible on a dense one.
    sig_size = min(max(int(size * 0.8), 18 * ss), _ESCRITOIRE_SIG_MAX * ss)
    title_size = min(max(int(size * 0.56), 16 * ss), _ESCRITOIRE_TITLE_MAX * ss)
    sig_h = (int(sig_size * 1.15) if author else 0) + (int(title_size * 1.2) if title else 0)
    gap = int(line_h * 0.3) if sig_h else 0
    total = len(wrapped) * line_h + gap + sig_h
    top = max(band_top * ss, (band_top * ss + band_bottom * ss - total) // 2)
    if top + total > band_bottom * ss:
        # Even the last-resort size overflowed: lift the block into the faint
        # band, which only ever holds filler, rather than off the near edge.
        top = max(_ESCRITOIRE_FAINT_TOP * ss, band_bottom * ss - total)
    return {"regular": reg, "bold": bold, "lines": wrapped, "line_h": line_h, "size": size,
            "author": author, "title": title, "sig_size": sig_size, "title_size": title_size,
            "gap": gap, "top": top, "block": (top / ss, (top + total) / ss)}


def _escritoire_masks(quote_row: dict, layout: dict) -> tuple[Image.Image, Image.Image, Image.Image]:
    """Write the letter onto the upright sheet as (prose, phrase, faint) masks
    at the supersampled resolution."""
    ss = _ESCRITOIRE_SS
    size = (_ESCRITOIRE_SHEET[0] * ss, _ESCRITOIRE_SHEET[1] * ss)
    prose, phrase, faint = (Image.new("L", size, 0) for _ in range(3))
    dp, dph, df = ImageDraw.Draw(prose), ImageDraw.Draw(phrase), ImageDraw.Draw(faint)
    left = _ESCRITOIRE_LEFT * ss
    right = (_ESCRITOIRE_SHEET[0] - 70) * ss

    # The earlier lines of the letter, down to just above the quote.
    rng = random.Random(_ESCRITOIRE_SEED ^ _row_digest(quote_row))
    base = _ESCRITOIRE_FAINT_TOP * ss
    last = layout["top"] - int(layout["line_h"] * 0.55)
    while base + _ESCRITOIRE_FAINT_PITCH * ss <= last:
        x = left + rng.uniform(0, 18) * ss
        _codex_script(df, x, base, right, xh=12 * ss, rng=rng, fill=255, width=ss)
        base += _ESCRITOIRE_FAINT_PITCH * ss
    if base <= last:
        # The paragraph before the quote ends part-way across.
        _codex_script(df, left + rng.uniform(0, 18) * ss, base, right - rng.uniform(140, 320) * ss,
                      xh=12 * ss, rng=rng, fill=255, width=ss)

    y = layout["top"]
    ascent = max(_font_ascent(layout["regular"]), _font_ascent(layout["bold"]))
    for line in layout["lines"]:
        x = left
        for chunk, is_bold in _trim_line(line):
            font = layout["bold"] if is_bold else layout["regular"]
            offset = ascent - _font_ascent(font)
            (dph if is_bold else dp).text((x, y + offset), chunk, font=font, fill=255)
            x += dp.textlength(chunk, font=font)
        y += layout["line_h"]
    y += layout["gap"]
    sig_right = left + _ESCRITOIRE_MEASURE * ss
    if layout["author"]:
        font = load_font(theme_font_candidates("escritoire", "quote_bold"), size=layout["sig_size"])
        author = _metro_ellipsize(dp, layout["author"], font, _ESCRITOIRE_MEASURE * ss)
        dp.text((sig_right - dp.textlength(author, font=font), y), author, font=font, fill=255)
        y += int(layout["sig_size"] * 1.15)
    if layout["title"]:
        font = load_font(theme_font_candidates("escritoire", "quote_regular"), size=layout["title_size"])
        title = _metro_ellipsize(dp, layout["title"], font, _ESCRITOIRE_MEASURE * ss)
        dp.text((sig_right - dp.textlength(title, font=font), y), title, font=font, fill=255)
    return prose, phrase, faint


def _escritoire_warp(mask: Image.Image, threshold: int) -> Image.Image:
    """Carry a supersampled sheet mask onto the canvas: bicubic perspective at
    twice the panel size, a 2:1 box reduce, then a hard threshold so the ink
    lands solid instead of as a grey fringe."""
    ss = _ESCRITOIRE_SS
    big = mask.transform((800 * ss, 480 * ss), Image.Transform.PERSPECTIVE, _escritoire_coeffs(ss),
                         resample=Image.Resampling.BICUBIC)
    return big.reduce(ss).point(lambda v: 255 if v >= threshold else 0)


def _escritoire_paint_letter(image: Image.Image, quote_row: dict) -> None:
    """The letter: faint earlier lines stippled in black, the quote solid
    black, the matched phrase solid blue, all clipped to the paper."""
    layout = _escritoire_layout(quote_row)
    prose, phrase, faint = _escritoire_masks(quote_row, layout)
    paper = _escritoire_sheet_mask(image.size)
    faint = ImageChops.multiply(_escritoire_warp(faint, 110),
                                _escritoire_stipple(Image.new("L", image.size, 104)))
    image.paste(SPECTRA6["black"], (0, 0), ImageChops.multiply(faint, paper))
    image.paste(SPECTRA6["black"], (0, 0), ImageChops.multiply(_escritoire_warp(prose, 120), paper))
    image.paste(SPECTRA6["blue"], (0, 0), ImageChops.multiply(_escritoire_warp(phrase, 120), paper))


def _escritoire_pen_axis() -> tuple:
    (ax, ay), (bx, by), radius = _ESCRITOIRE_PEN
    length = math.hypot(bx - ax, by - ay)
    return ax, ay, (bx - ax) / length, (by - ay) / length, length, radius


def _escritoire_paint_pen(image: Image.Image) -> None:
    """The fountain pen across the far band, nib toward the quote: black
    lacquer, a gold section band, cap ring, clip and finial, a gold nib with its
    slit and breather hole, a dotted highlight along the barrel, a shadow on
    the paper. It tapers a little toward the cap so it recedes with the page."""
    ax, ay, ux, uy, length, r = _escritoire_pen_axis()
    nx, ny = -uy, ux
    black, gold = SPECTRA6["black"], SPECTRA6["green"]     # green is a sentinel for gold

    def taper(t):
        return 1.0 - 0.15 * t / length

    def section(draw, t0, t1, rad, fill):
        draw.polygon([(ax + ux * t + nx * rad * taper(t) * s, ay + uy * t + ny * rad * taper(t) * s)
                      for t, s in ((t0, 1), (t1, 1), (t1, -1), (t0, -1))], fill=fill)

    shadow = Image.new("L", image.size, 0)
    section(ImageDraw.Draw(shadow), 0, length, r + 1, 255)
    shadow = _shift_no_wrap(shadow, 5, 10).filter(ImageFilter.GaussianBlur(5))
    shadow = Image.eval(shadow, lambda v: v * 44 // 64)
    image.paste(black, (0, 0), _escritoire_stipple(shadow))

    draw = ImageDraw.Draw(image)
    draw.polygon([(ax, ay), (ax + ux * 46 + nx * 7, ay + uy * 46 + ny * 7),
                  (ax + ux * 46 - nx * 7, ay + uy * 46 - ny * 7)], fill=gold)
    section(draw, 44, 120, r * 0.8, black)
    section(draw, 120, 134, r * 0.95, gold)
    section(draw, 134, length - 72, r, black)
    section(draw, length - 72, length - 64, r * 1.1, gold)
    section(draw, length - 64, length - 4, r * 1.1, black)
    for t, rad in ((44, r * 0.8), (length - 4, r * 1.1)):
        rr, cx, cy = rad * taper(t), ax + ux * t, ay + uy * t
        draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=black)
    cx, cy = ax + ux * (length - 2), ay + uy * (length - 2)
    draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=gold)
    clip = -(r - 1)
    draw.line([(ax + ux * (length - 60) + nx * clip, ay + uy * (length - 60) + ny * clip),
               (ax + ux * (length - 12) + nx * clip, ay + uy * (length - 12) + ny * clip)], fill=gold, width=3)
    draw.line([(ax + ux * 4, ay + uy * 4), (ax + ux * 34, ay + uy * 34)], fill=black, width=1)
    cx, cy = ax + ux * 34, ay + uy * 34
    draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=black)
    px = pixel_access(image)
    width, height = image.size
    for t in range(50, int(length) - 70, 3):
        off = -(r * taper(t) - 4)
        hx, hy = int(ax + ux * t + nx * off), int(ay + uy * t + ny * off)
        if 0 <= hx < width and 0 <= hy < height:
            px[hx, hy] = SPECTRA6["white"]
    # Gold: 5/8 red, 3/8 yellow, on the ordered tile, over the pen's own box.
    reach = int(r * 1.1) + 6
    x0, x1 = max(0, int(min(ax, ax + ux * length)) - reach), min(width, int(max(ax, ax + ux * length)) + reach + 1)
    y0, y1 = max(0, int(min(ay, ay + uy * length)) - reach), min(height, int(max(ay, ay + uy * length)) + reach + 1)
    for y in range(y0, y1):
        row = BAYER_8x8[y % 8]
        for x in range(x0, x1):
            if px[x, y] == gold:
                px[x, y] = SPECTRA6["yellow"] if row[x % 8] < 24 else SPECTRA6["red"]


def render_escritoire_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A handwritten letter on a writing desk, seen at an angle (see the
    section comment above).

    ``time_str`` is unused by design: the matched phrase carries the time.
    """
    del time_str
    image = _escritoire_scene().copy()
    _escritoire_paint_letter(image, quote_row)
    _escritoire_paint_pen(image)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("escritoire",), render=render_escritoire_frame)
