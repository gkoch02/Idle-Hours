"""The ``sampler`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..fonts import load_font, normalize_dashes, theme_font_candidates
from ..furniture import fallback_title
from ..layout import strip_underscore_emphasis, tokenize_quote, wrap_styled_text
from ..palette import SPECTRA6, SPECTRA6_PALETTE, gray_pixel_access, pixel_access, snap_image_to_palette
from ..spec import FrameSpec

# ── sampler: counted cross-stitch embroidery ──────────────────────────────────
# Every glyph is cross-stitch "X" marks: text is drawn to a small Silkscreen
# pixel-font mask and each set pixel is stamped as one stitch cell on an Aida
# ground. A stitched floral border and sampler motifs fill the margins. Body
# floss is black, the matched phrase red; HH:MM is never shown. No RNG, so
# re-renders are byte-identical.

# Floss palette — every stitch is one Spectra-6 ink.
_SAMPLER_FLOSS = {
    "K": SPECTRA6["black"],
    "R": SPECTRA6["red"],
    "G": SPECTRA6["green"],
    "B": SPECTRA6["blue"],
    "Y": SPECTRA6["yellow"],
    "W": SPECTRA6["white"],
}
# Stitch-cell sizes tried largest-first by the body fit loop.
_SAMPLER_STITCH_SIZES = (6, 5, 4, 3)
# Quote area, in panel px — clear of the border frame, the alphabet row above,
# and the credits / motif band below. Body layout is computed in mask-pixel
# units (panel px // stitch size) and scaled up at stitch time.
_SAMPLER_BODY_RECT = (96, 90, 704, 300)
# Blank mask rows above the Silkscreen cap line, trimmed from the layout so the
# stitched block isn't top-heavy with empty fabric.
_SAMPLER_TOP_SKIP = 3
# Mask rows allotted per text line (Silkscreen cap height ~5 + descender + gap).
_SAMPLER_LINE_ROWS = 8
_SAMPLER_WEAVE_PITCH = 4  # Aida-cloth thread-crossing grid pitch, in panel px.

# Small motif grids — one character per stitch cell, space = skip. Tiled / placed
# by _sampler_paint_border / _sampler_paint_motifs. Colours are _SAMPLER_FLOSS keys.
_SAMPLER_FLOWER_B = (" B ", "BYB", " B ")          # blue petals, yellow centre
_SAMPLER_FLOWER_Y = (" Y ", "YBY", " Y ")          # yellow petals, blue centre
_SAMPLER_HOUSE = (
    "   R   ",
    "  RRR  ",
    " RRRRR ",
    "RRRRRRR",
    "GYYBYYG",
    "GYYBYYG",
)
_SAMPLER_HEART = ("RR RR", "RRRRR", "RRRRR", " RRR ", "  R  ")
_SAMPLER_BIRD = ("  B  ", " BBBB", "BBBBB", " B B ")
_SAMPLER_TREE = ("  G  ", " GGG ", "GGGGG", " GGG ", "  K  ")


def _sampler_stitch_x(px, cx: int, cy: int, color, width: int, height: int, size: int) -> None:
    """Stamp one cross-stitch ``X`` into a ``size``×``size`` cell at (cx, cy).

    Every ``px[x, y]`` write is bounds-guarded: ``PixelAccess`` raises
    ``IndexError`` out of range, and ``/api/preview`` renders smaller canvases.
    """
    n = size - 1

    def put(x: int, y: int) -> None:
        if 0 <= x < width and 0 <= y < height:
            px[x, y] = color

    # Corner-to-corner diagonals: an inset, 1-px X washes out at small cell
    # sizes. Adjacent cells' arms meet at the corners, as real stitching does.
    for i in range(n + 1):
        put(cx + i, cy + i)
        put(cx + i, cy + (n - i))
    # Thicken each arm by one pixel on cells big enough to carry it.
    if size >= 4:
        for i in range(n):
            put(cx + i + 1, cy + i)
            put(cx + i, cy + (n - i - 1))


def _sampler_stamp_motif(px, motif, ox: int, oy: int, size: int, width: int, height: int) -> None:
    """Stamp a character-grid motif as stitches, top-left at (ox, oy)."""
    for row, line in enumerate(motif):
        for col, ch in enumerate(line):
            color = _SAMPLER_FLOSS.get(ch)
            if color is None:
                continue
            _sampler_stitch_x(px, ox + col * size, oy + row * size, color, width, height, size)


def _sampler_paint_aida(image: Image.Image) -> None:
    """Aida-cloth ground: white with a yellow fleck on a regular weave grid.

    One fleck per ``_SAMPLER_WEAVE_PITCH`` cell (~6% yellow at pitch 4). A
    sparse *regular* grid reads as thread crossings where a Bayer wash would
    read as tint, and keeps the black floss high-contrast.
    """
    width, height = image.size
    px = pixel_access(image)
    white, yellow = SPECTRA6["white"], SPECTRA6["yellow"]
    for y in range(height):
        for x in range(width):
            px[x, y] = white
    for y in range(0, height, _SAMPLER_WEAVE_PITCH):
        for x in range(0, width, _SAMPLER_WEAVE_PITCH):
            px[x, y] = yellow


def _sampler_paint_border(image: Image.Image) -> None:
    """A stitched cross-stitch border: an alternating green-leaf / red-bud vine
    frame with blue + yellow flower motifs at the corners and mid-edges.

    Built entirely from the stitch primitive; deterministic.
    """
    width, height = image.size
    px = pixel_access(image)
    size = 6
    inset = 30
    x0, y0 = inset, inset
    x1, y1 = width - inset - size, height - inset - size
    red, green = SPECTRA6["red"], SPECTRA6["green"]

    def vine(x: int, y: int, i: int) -> None:
        # Pairs of green leaf stitches alternate with pairs of red buds.
        _sampler_stitch_x(px, x, y, green if (i // 2) % 2 == 0 else red, width, height, size)

    i = 0
    for x in range(x0, x1 + 1, size):
        vine(x, y0, i)
        vine(x, y1, i)
        i += 1
    i = 0
    for y in range(y0, y1 + 1, size):
        vine(x0, y, i)
        vine(x1, y, i)
        i += 1

    # Corner + mid-edge flowers (blue / yellow), centred on the frame line.
    mid_x = (x0 + x1) // 2 - size
    mid_y = (y0 + y1) // 2 - size
    fb, fy = _SAMPLER_FLOWER_B, _SAMPLER_FLOWER_Y
    _sampler_stamp_motif(px, fb, x0 - size, y0 - size, size, width, height)
    _sampler_stamp_motif(px, fy, x1 - size, y0 - size, size, width, height)
    _sampler_stamp_motif(px, fy, x0 - size, y1 - size, size, width, height)
    _sampler_stamp_motif(px, fb, x1 - size, y1 - size, size, width, height)
    _sampler_stamp_motif(px, fy, mid_x, y0 - size, size, width, height)
    _sampler_stamp_motif(px, fy, mid_x, y1 - size, size, width, height)
    _sampler_stamp_motif(px, fb, x0 - size, mid_y, size, width, height)
    _sampler_stamp_motif(px, fb, x1 - size, mid_y, size, width, height)


def _sampler_paint_motifs(image: Image.Image) -> None:
    """Classic sampler furniture stitched in the lower margin: a house centred
    with a heart, a bird, and a tree flanking it. Sits below the credits band
    and above the bottom border, clear of the body rect. Deterministic.
    """
    width, height = image.size
    px = pixel_access(image)
    size = 6
    band_y = height - 30 - size - 6 * size  # top of the 6-row motif band
    cx = width // 2
    _sampler_stamp_motif(px, _SAMPLER_HOUSE, cx - (len(_SAMPLER_HOUSE[0]) * size) // 2, band_y, size, width, height)
    _sampler_stamp_motif(px, _SAMPLER_HEART, cx - 150, band_y + size, size, width, height)
    _sampler_stamp_motif(px, _SAMPLER_BIRD, cx + 110, band_y + size, size, width, height)
    _sampler_stamp_motif(px, _SAMPLER_TREE, cx - 230, band_y, size, width, height)
    _sampler_stamp_motif(px, _SAMPLER_TREE, cx + 190, band_y, size, width, height)


def _sampler_stitch_chunk(image, draw, px, chunk, font, x_px, origin_y, size, color, width, height) -> int:
    """Stitch one text chunk in ``color``; return the panel-px advance.

    The chunk is rendered to an ``L`` mask in the pixel font and every set mask
    pixel becomes a stitch cell. The mask keeps the font's full row coordinates
    (no per-chunk vertical crop) so regular and bold chunks share a baseline.
    """
    advance = int(round(draw.textlength(chunk, font=font)))
    if not chunk.strip():  # whitespace: no stitches, just advance the cursor
        return advance * size
    bbox = draw.textbbox((0, 0), chunk, font=font)
    cw = max(advance, bbox[2]) + 1
    ch = bbox[3] + 1
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).text((0, 0), chunk, font=font, fill=255)
    mpx = gray_pixel_access(mask)
    for my in range(ch):
        ty = my - _SAMPLER_TOP_SKIP
        if ty < 0:
            continue
        cell_y = origin_y + ty * size
        for mx in range(cw):
            if mpx[mx, my] >= 128:
                _sampler_stitch_x(px, x_px + mx * size, cell_y, color, width, height, size)
    return advance * size


def _sampler_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> int:
    """Stitch the literary quote, centred in the body rect, body floss in black
    with the matched time-phrase in red floss. Returns the bottom y of the
    stitched block so the credits can sit beneath it.
    """
    width, height = image.size
    bx0, by0, bx1, by1 = _SAMPLER_BODY_RECT
    body_w = bx1 - bx0
    body_h = by1 - by0
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    matched = quote_row.get("matched_text") or ""
    segments = tokenize_quote(display_quote, matched)
    body_color, accent_color = SPECTRA6["black"], SPECTRA6["red"]

    # Fit: pick the largest stitch size whose wrapped block fits the rect.
    chosen_size = _SAMPLER_STITCH_SIZES[-1]
    chosen_lines: list = []
    for size in _SAMPLER_STITCH_SIZES:
        mask_font = load_font(theme_font_candidates("sampler", "quote_regular"), 8)
        mask_bold = load_font(theme_font_candidates("sampler", "quote_bold"), 8)
        max_cols = max(1, body_w // size)
        lines = wrap_styled_text(draw, segments, mask_font, mask_bold, max_cols)
        block_h = len(lines) * _SAMPLER_LINE_ROWS * size
        chosen_size, chosen_lines = size, lines
        if block_h <= body_h:
            break

    mask_font = load_font(theme_font_candidates("sampler", "quote_regular"), 8)
    mask_bold = load_font(theme_font_candidates("sampler", "quote_bold"), 8)
    px = pixel_access(image)
    line_h = _SAMPLER_LINE_ROWS * chosen_size
    block_h = len(chosen_lines) * line_h
    y = by0 + max(0, (body_h - block_h) // 2)
    for line in chosen_lines:
        start = 0
        while start < len(line) and line[start][0].strip() == "":
            start += 1
        end = len(line)
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        drawable = line[start:end]
        line_w = 0
        for chunk, is_bold in drawable:
            font = mask_bold if is_bold else mask_font
            line_w += int(round(draw.textlength(chunk, font=font))) * chosen_size
        x = bx0 + max(0, (body_w - line_w) // 2)
        for chunk, is_bold in drawable:
            font = mask_bold if is_bold else mask_font
            color = accent_color if is_bold else body_color
            x += _sampler_stitch_chunk(image, draw, px, chunk, font, x, y, chosen_size, color, width, height)
        y += line_h
    return y


def _sampler_paint_credits(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict, block_bottom: int) -> None:
    """Stitch the attribution below the quote: author in blue floss, title in
    green. Small fixed stitch size; single truncated lines.
    """
    width, height = image.size
    px = pixel_access(image)
    size = 3
    font = load_font(theme_font_candidates("sampler", "quote_regular"), 8)
    blue, green = SPECTRA6["blue"], SPECTRA6["green"]
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "")
    bx0, _, bx1, _ = _SAMPLER_BODY_RECT
    body_w = bx1 - bx0
    max_cols = max(1, body_w // size)

    def stitch_centred(text: str, y: int, color) -> None:
        while text and int(round(draw.textlength(text, font=font))) > max_cols:
            text = text[:-1]
        if not text:
            return
        line_w = int(round(draw.textlength(text, font=font))) * size
        x = bx0 + max(0, (body_w - line_w) // 2)
        _sampler_stitch_chunk(image, draw, px, text, font, x, y, size, color, width, height)

    y = min(block_bottom + 10, _SAMPLER_BODY_RECT[3] + 12)
    if author:
        stitch_centred(author, y, blue)
        y += _SAMPLER_LINE_ROWS * size + 2
    if title:
        stitch_centred(f"- {title} -", y, green)


def render_sampler_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Counted cross-stitch embroidery sampler (see the module section comment).

    ``time_str`` is unused (the matched phrase carries the time); kept for
    dispatch-signature uniformity.
    """
    del time_str  # see docstring; deliberately unused.
    image = Image.new("RGB", (width, height), color=SPECTRA6["white"])
    draw = ImageDraw.Draw(image)
    _sampler_paint_aida(image)
    _sampler_paint_border(image)
    _sampler_paint_motifs(image)
    block_bottom = _sampler_paint_quote(image, draw, quote_row)
    _sampler_paint_credits(image, draw, quote_row, block_bottom)
    return snap_image_to_palette(image, SPECTRA6_PALETTE)


SPEC = FrameSpec(themes=("sampler",), render=render_sampler_frame)
