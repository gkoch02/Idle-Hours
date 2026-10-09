"""The ``control`` theme's frame: the Astral Plane of Remedy's *Control* (2019)
as a title card.

Design notes: docs/themes.md § control
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .._paths import ARCHIVO_BOLD, BASE_DIR, META_FONT_BOLD_CANDIDATES, OSWALD_VARIABLE
from ..fonts import load_font
from ..furniture import fallback_title
from ..palette import (
    SPECTRA6,
    SPECTRA6_PALETTE,
    BAYER_8x8,
    _load_dithered_plate,
    gray_pixel_access,
    pixel_access,
    snap_image_to_palette,
)
from ..primitives import paint_neon_mask, position_noise, wrap_quote_into_masks
from ..spec import FrameSpec
from ..text import draw_tracked, fit_text_to_width
from ._shared import _GUNMETAL_PALETTE

# control: board-formed concrete for the plinth, dithered to white+black at
# render time (scripts/generate_control_plate.py). 800x88, the plinth band.
CONTROL_PLATE = BASE_DIR / "assets" / "control_concrete.png"
# The concrete plate dithers to the same K+W pair as the gunmetal: one constant,
# so the two achromatic plates cannot drift apart.
_CONCRETE_PALETTE = _GUNMETAL_PALETTE



# Everything is absolute panel coordinates: composed at 800x480 and
# NEAREST-downsampled for other sizes (the ``metro`` convention).
_CONTROL_QUOTE_RECT = (130, 100, 670, 372)
_CONTROL_PLINTH_Y = 392
_CONTROL_SIGN_RECT = (40, 418, 760, 462)
_CONTROL_SEAL_CENTRE = (74, 440)
_CONTROL_SEAL_RADIUS = 14
# The Board: an inverted pyramid hanging from the top edge, apex down.
_CONTROL_BOARD = ((338, 0), (462, 0), (400, 84))
# Floating blocks as (top_vertex_x, top_vertex_y, side, height), clear of the
# quote rect; the four small ones are distant blocks beside the pyramid.
_CONTROL_BLOCKS = (
    (70, 18, 36, 36),
    (24, 108, 16, 18),
    (736, 26, 40, 40),
    (700, 146, 14, 14),
    (58, 232, 28, 30),
    (748, 250, 24, 48),
    (94, 322, 30, 30),
    (712, 316, 34, 34),
    (200, 34, 8, 8),
    (590, 24, 10, 10),
    (296, 46, 9, 9),
    (516, 50, 9, 9),
)
_CONTROL_ISO = (0.866, 0.5)          # isometric axis: (cos 30°, sin 30°)
_CONTROL_LIT_FACE = 0.25             # black density on the face toward the light
_CONTROL_SHADE_FACE = 0.56           # black density on the face away from it
_CONTROL_BOARD_FACE = 0.68           # the Board's lit face: darker than any block
_CONTROL_CONCRETE = (0.30, 0.46)     # black density at the plinth's top / bottom
_CONTROL_CONCRETE_JITTER = 12        # ± ranks of positional jitter on the 8x8 tile
_CONTROL_TIE_HOLES_Y = 404
_CONTROL_SEAMS_X = (200, 400, 600)
_CONTROL_HISS_RADIUS = 6
_CONTROL_HISS_CAP = 0.62
_CONTROL_HISS_GAMMA = 1.6
_CONTROL_TRACKING = 2
_CONTROL_SIGN_GAP = 24          # clear space between the name run and the credit column
_CONTROL_CREDIT_SIZE = 12
_CONTROL_CREDIT_FLOOR = 10      # below this a credit is ellipsised rather than shrunk further
# Hiss resonance: thin bands of the phrase echoed sideways as a half-density
# red stipple — (band top as a fraction of the phrase height, band height px,
# shift px). Echoes only; the phrase itself stays whole and legible.
_CONTROL_RESONANCE = ((0.18, 3, 9), (0.47, 2, -7), (0.74, 3, 6))
_CONTROL_RESONANCE_DENSITY = 0.5


def _control_fill_polygon(image: Image.Image, polygon, density: float) -> None:
    """Fill a polygon with a K+W ordered stipple at ``density`` black.

    A 1-bit polygon mask clips the fill (the ``_vitrail_fill_polygon`` shape),
    and the rank is read off ``BAYER_8x8`` at absolute coordinates so adjacent
    faces share one phase. Unjittered on purpose — see the section comment.
    """
    xs = [int(p[0]) for p in polygon]
    ys = [int(p[1]) for p in polygon]
    w, h = image.size
    x0, y0 = max(0, min(xs)), max(0, min(ys))
    x1, y1 = min(w, max(xs) + 1), min(h, max(ys) + 1)
    if x1 <= x0 or y1 <= y0:
        return
    mask = Image.new("1", (x1 - x0, y1 - y0), 0)
    ImageDraw.Draw(mask).polygon([(int(px) - x0, int(py) - y0) for px, py in polygon], fill=1)
    mp = pixel_access(mask)
    px = pixel_access(image)
    black, white = SPECTRA6["black"], SPECTRA6["white"]
    cut = density * 64
    for yy in range(y1 - y0):
        ay = y0 + yy
        row = BAYER_8x8[ay % 8]
        for xx in range(x1 - x0):
            if mp[xx, yy]:
                ax = x0 + xx
                px[ax, ay] = black if row[ax % 8] < cut else white


def _control_block_faces(top_x: int, top_y: int, side: int, height: int):
    """The three visible faces of an isometric block whose highest vertex is
    ``(top_x, top_y)``: top rhombus, left (lit) face, right (shadow) face."""
    ux, uy = _CONTROL_ISO
    dx, dy = side * ux, side * uy
    top = (top_x, top_y)
    right = (top_x + dx, top_y + dy)
    left = (top_x - dx, top_y + dy)
    near = (top_x, top_y + 2 * dy)
    top_face = [top, right, near, left]
    left_face = [left, near, (near[0], near[1] + height), (left[0], left[1] + height)]
    right_face = [near, right, (right[0], right[1] + height), (near[0], near[1] + height)]
    return top_face, left_face, right_face


def _control_outline(draw: ImageDraw.ImageDraw, polygon, width: int = 2) -> None:
    pts = [(int(round(x)), int(round(y))) for x, y in polygon]
    draw.line(pts + [pts[0]], fill=SPECTRA6["black"], width=width, joint="curve")


def _control_paint_blocks(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """The Astral Plane's floating stone: isometric blocks in the margins.

    Each block is painted (white top, light and dark stipple sides) then
    outlined, so overlapping blocks stay distinct.
    """
    for top_x, top_y, side, height in _CONTROL_BLOCKS:
        top_face, left_face, right_face = _control_block_faces(top_x, top_y, side, height)
        draw.polygon([(int(round(x)), int(round(y))) for x, y in top_face], fill=SPECTRA6["white"])
        _control_fill_polygon(image, left_face, _CONTROL_LIT_FACE)
        _control_fill_polygon(image, right_face, _CONTROL_SHADE_FACE)
        stroke = 1 if side < 12 else 2
        for face in (top_face, left_face, right_face):
            _control_outline(draw, face, width=stroke)


def _control_paint_board(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """The Board: an inverted black pyramid hanging from the top of the void.

    Two faces meet on a vertical edge under the apex (lit face a dense
    stipple, shadow face solid black), so it reads as a solid.
    """
    (ax, ay), (bx, by), (cx, cy) = _CONTROL_BOARD
    _control_fill_polygon(image, [(ax, ay), (cx, ay), (cx, cy)], _CONTROL_BOARD_FACE)
    draw.polygon([(cx, ay), (bx, by), (cx, cy)], fill=SPECTRA6["black"])
    _control_outline(draw, [(ax, ay), (bx, by), (cx, cy)], width=2)
    draw.line([(cx, ay), (cx, cy)], fill=SPECTRA6["black"], width=2)


def _control_paint_concrete_stipple(image: Image.Image, top: int) -> None:
    """Fallback plinth texture when the concrete plate asset is missing.

    Hash-jittered ordered dither (the ``bakelite`` moulding recipe) at a
    density that deepens toward the bottom edge. Reads as cast stone at a
    glance; the committed plate carries the board grain this cannot.
    """
    width, height = image.size
    px = pixel_access(image)
    black = SPECTRA6["black"]
    span = max(1, height - top)
    d0, d1 = _CONTROL_CONCRETE
    jitter = _CONTROL_CONCRETE_JITTER
    for y in range(top, height):
        cut = (d0 + (d1 - d0) * (y - top) / span) * 64
        row = BAYER_8x8[y % 8]
        for x in range(width):
            rank = row[x % 8] + (position_noise(x, y) % (2 * jitter + 1)) - jitter
            if rank < cut:
                px[x, y] = black


def _control_paint_plinth(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """The Oldest House: a band of board-formed concrete across the foot.

    Prefers the committed continuous-tone plate (``CONTROL_PLATE``), dithered
    to white+black at render time; falls back to the jittered stipple when the
    asset is missing. Formwork seams and tie-holes go on top either way.
    """
    width, height = image.size
    black = SPECTRA6["black"]
    top = _CONTROL_PLINTH_Y
    if height > top:
        plate = _load_dithered_plate(CONTROL_PLATE, width, height - top, palette=_CONCRETE_PALETTE)
        if plate is not None:
            image.paste(plate, (0, top))
        else:
            _control_paint_concrete_stipple(image, top)
    draw.line([(0, top), (width, top)], fill=black, width=2)
    for sx in _CONTROL_SEAMS_X:
        draw.line([(sx, top), (sx, height)], fill=black, width=1)
    for hx in range(100, width, 200):
        draw.ellipse((hx - 3, _CONTROL_TIE_HOLES_Y - 3, hx + 3, _CONTROL_TIE_HOLES_Y + 3), fill=black)


def _control_paint_seal(draw: ImageDraw.ImageDraw) -> None:
    """The Bureau's device on the sign: a ring around an inverted triangle."""
    cx, cy = _CONTROL_SEAL_CENTRE
    r = _CONTROL_SEAL_RADIUS
    white = SPECTRA6["white"]
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=white, width=2)
    tri = [(cx - 8, cy - 6), (cx + 8, cy - 6), (cx, cy + 8)]
    draw.polygon(tri, outline=white, fill=None)
    draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=white)


def _control_board_lines(quote_row: dict) -> list[str]:
    """Attribution in the Board's paired diction — labels only; values are the row's."""
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "")
    lines = []
    if author:
        lines.append(f"AUTHOR/ORIGIN: {author.upper()}")
    if title:
        lines.append(f"WORK/VESSEL: {title.upper()}")
    return lines


def _control_paint_sign(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The black wayfinding sign on the plinth: Bureau device and name at the
    left, the Board's attribution pairs right-aligned."""
    x0, y0, x1, y1 = _CONTROL_SIGN_RECT
    white = SPECTRA6["white"]
    draw.rectangle((x0, y0, x1, y1), fill=SPECTRA6["black"])
    _control_paint_seal(draw)
    # The sign is UI: Archivo stands in for the game's Akzidenz-Grotesk cut.
    name_font = load_font([ARCHIVO_BOLD, (OSWALD_VARIABLE, "Bold"), *META_FONT_BOLD_CANDIDATES], size=16)
    # Bold at 10 px too: Archivo Regular's hairlines shred on the black sign.
    sub_font = load_font([ARCHIVO_BOLD, (OSWALD_VARIABLE, "Medium"), *META_FONT_BOLD_CANDIDATES], size=10)
    text_x = _CONTROL_SEAL_CENTRE[0] + _CONTROL_SEAL_RADIUS + 12
    name_w = draw_tracked(draw, (text_x, y0 + 5), "FEDERAL BUREAU OF CONTROL", name_font, white,
                          tracking=_CONTROL_TRACKING)
    draw_tracked(draw, (text_x, y0 + 29), "THE OLDEST HOUSE", sub_font, white, tracking=3)

    # Budget the credit column off the name run actually painted, not a
    # constant: a face change would otherwise let long titles overprint it.
    credit_candidates = [ARCHIVO_BOLD, (OSWALD_VARIABLE, "Medium"), *META_FONT_BOLD_CANDIDATES]
    right = x1 - 14
    limit = right - (text_x + name_w + _CONTROL_SIGN_GAP)
    lines = _control_board_lines(quote_row)
    y = y0 + 6 if len(lines) > 1 else y0 + 14
    for text in lines:
        font, text = fit_text_to_width(draw, text, credit_candidates, _CONTROL_CREDIT_SIZE, limit,
                                       floor=_CONTROL_CREDIT_FLOOR, tracking=1)
        draw_tracked(draw, (right, y), text, font, white, tracking=1, anchor_right=True)
        y += 17


def _control_paint_resonance(image: Image.Image, hot: Image.Image) -> None:
    """The Hiss's signal tearing: a few thin bands of the matched phrase echoed
    sideways as a half-density red stipple.

    An *echo*, not a tear: moving the band would cut the time phrase. Only
    white pixels are written, so the echo never overwrites prose, the phrase
    or its bloom.
    """
    bbox = hot.getbbox()
    if bbox is None:
        return
    x0, y0, x1, y1 = bbox
    span = y1 - y0
    width, height = image.size
    hp, px = gray_pixel_access(hot), pixel_access(image)
    red, white = SPECTRA6["red"], SPECTRA6["white"]
    cut = _CONTROL_RESONANCE_DENSITY * 64
    for frac, band_h, shift in _CONTROL_RESONANCE:
        by0 = y0 + int(frac * span)
        for y in range(by0, min(height, by0 + band_h)):
            row = BAYER_8x8[y % 8]
            for x in range(x0, x1):
                if hp[x, y] <= 128:
                    continue
                tx = x + shift
                if 0 <= tx < width and px[tx, y] == white and row[tx % 8] < cut:
                    px[tx, y] = red


def _control_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """Black prose in the void; the matched phrase in Hiss red with a coral
    bloom stippled into the white around it."""
    prose, hot, _ = wrap_quote_into_masks(
        draw, image.size, quote_row, _CONTROL_QUOTE_RECT, theme="control",
        font_max=40, font_min=16, line_height_mult=1.22,
    )
    # Threshold the prose mask: a mid-grey antialiased edge would snap to red.
    image.paste(SPECTRA6["black"], (0, 0), prose.point(lambda v: 255 if v > 128 else 0))
    paint_neon_mask(
        image, hot, SPECTRA6["red"], SPECTRA6["red"],
        radius=_CONTROL_HISS_RADIUS, gamma=_CONTROL_HISS_GAMMA, cap=_CONTROL_HISS_CAP,
        ground=frozenset({SPECTRA6["white"]}), tile=BAYER_8x8,
    )
    _control_paint_resonance(image, hot)
    prose.close()
    hot.close()


def render_control_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The Astral Plane title card (see the module section comment above).

    ``time_str`` is unused by design: the matched phrase carries the time.
    """
    del time_str
    image = Image.new("RGB", (800, 480), color=SPECTRA6["white"])
    draw = ImageDraw.Draw(image)
    _control_paint_plinth(image, draw)
    _control_paint_board(image, draw)
    _control_paint_blocks(image, draw)
    _control_paint_quote(image, draw, quote_row)
    _control_paint_sign(image, draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("control",), render=render_control_frame)
