"""The ``kanagawa`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..palette import SPECTRA6, BAYER_4x4
from ..spec import BorderSpec

_KANAGAWA_BIRD_ANCHORS: tuple[tuple[float, float, int, int, int], ...] = (
    # (cx_frac, cy_frac, wingspan, left_droop, right_droop): distant
    # ink-stroke birds in the upper sky, well above the text. Two strokes
    # each with asymmetric droop so the five read as distinct birds;
    # 18-26 px wingspans at 2 px stroke stay visible on the sky wash.
    (0.20, 0.06, 22,  6,  9),    # banking right
    (0.34, 0.04, 18,  4,  4),    # gliding level
    (0.52, 0.08, 26, 10,  4),    # banking left
    (0.66, 0.05, 20,  5,  8),    # banking right
    (0.82, 0.07, 18,  6,  3),    # banking left
)


# Seigaiha (青海波 / "blue ocean waves") tile radius: mid-way between a dense
# woven-fabric look (smaller) and a graphic tile motif (larger).
_SEIGAIHA_TILE_RADIUS = 28
# Concentric white arcs in each tile. With row overlap radius // 2 = 14,
# each tile shows a 14 px crescent: room for three arcs ~5 px apart.
_SEIGAIHA_RING_RADII: tuple[int, ...] = (23, 18, 13)


def _draw_seigaiha_band(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    band_top_y: int,
    band_bottom_y: int,
    blue_ink: tuple[int, int, int],
    white_ink: tuple[int, int, int],
    black_ink: tuple[int, int, int],
    *,
    radius: int = _SEIGAIHA_TILE_RADIUS,
) -> None:
    """Fill the horizontal band ``(0, band_top_y) – (width, band_bottom_y)``
    with the seigaiha (青海波 / "blue ocean waves") tile pattern.

    Each tile is an indigo upper half-disk (pie slice 180°–360°) with three
    thin white arcs at ``_SEIGAIHA_RING_RADII``. Rows are ``radius // 2``
    apart, so each row overpaints the lower half of the one above and only
    a 14 px crescent per scale shows. Alternate rows shift by half the
    column spacing so the scales interlock, and the tiling overshoots the
    band edges so no border shows.

    The deepest rows get a navy stipple (B+K 1:1, the recipe of the
    kanagawa matched phrase), so the sea darkens toward the bottom.
    """
    width = image.size[0]
    row_spacing = max(8, radius // 2)
    col_spacing = radius

    # Top of the "deepest" rows, post-passed to navy after the tiles.
    deepest_band_top = max(band_top_y, band_bottom_y - row_spacing * 2)

    y = band_top_y
    row = 0
    while y <= band_bottom_y + row_spacing:
        x_offset = (col_spacing // 2) if row % 2 == 1 else 0
        x = -col_spacing + x_offset
        while x <= width + col_spacing:
            # Filled upper half-disk (the scale body) in indigo.
            draw.pieslice(
                (x - radius, y - radius, x + radius, y + radius),
                180, 360, fill=blue_ink,
            )
            # Three concentric white arc stripes inside the scale.
            for ring_r in _SEIGAIHA_RING_RADII:
                draw.arc(
                    (x - ring_r, y - ring_r, x + ring_r, y + ring_r),
                    180, 360, fill=white_ink, width=1,
                )
            x += col_spacing
        y += row_spacing
        row += 1

    # Navy depth post-pass on the deepest rows: half the blue pixels flip
    # to black on (x+y)&1 (B+K 1:1). Bounds are clamped to the canvas,
    # because PIL's PixelAccess raises on negative indices instead of
    # clipping like the drawing primitives.
    pixels = image.load()
    py_start = max(0, deepest_band_top)
    py_end = min(image.size[1] - 1, band_bottom_y)
    for py in range(py_start, py_end + 1):
        for px in range(width):
            if pixels[px, py] == blue_ink and ((px + py) & 1) == 0:
                pixels[px, py] = black_ink


def draw_kanagawa_border(
    image: Image.Image,
    colors: dict,
    clear_rect: tuple[int, int, int, int] | None = None,
) -> None:
    """Paint a stylised Japanese seascape: graduated sky-blue Bayer wash,
    five ink-stroke birds, a stippled horizon, the seigaiha (青海波) tile
    band at the bottom, and a maroon hanko seal in the bottom-right. No
    outer frame: ukiyo-e prints have none (as ``fillmore``).

    * **Layer 0: graduated sky wash.** Only ``page_bg`` pixels above the
      horizon (y ≈ 0.55 × height) are touched; the Bayer threshold tapers
      from ~5/16 blue at the top to 0 at the horizon: morning haze.
    * **Distant birds** from ``_KANAGAWA_BIRD_ANCHORS``: black two-stroke
      Vs in the upper sky.
    * **Horizon line**: a sparse stippled blue line at y ≈ 0.62 × height.
    * **Seigaiha band** (bottom ~34%): see ``_draw_seigaiha_band``.
    * **Hanko seal** (~32×38 px): a red rounded rectangle half flipped to
      black on ``(x+y)&1`` (R+K maroon), with a stylised 川 ("river") in
      2 px white strokes painted after the post-pass so they stay solid.

    When ``clear_rect`` is given (the standard render path, as for
    ``blueprint``), the body rect becomes a cream paper card over the
    textile, so the band can run up to the text without hurting
    legibility.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    page_bg = colors.get("page_bg")
    white_ink = SPECTRA6["white"]
    black_ink = SPECTRA6["black"]
    red_ink = SPECTRA6["red"]
    blue_ink = SPECTRA6["blue"]

    pixels = image.load()

    # ------------------------------------------------------------------
    # Layer 0: vertically graduated sky-blue Bayer wash.
    horizon_y = round(height * 0.55)
    if page_bg is not None:
        for y in range(horizon_y):
            thr = max(0, round(5 * (1 - y / max(1, horizon_y))))
            if thr == 0:
                continue
            row = BAYER_4x4[y & 3]
            for x in range(width):
                if pixels[x, y] == page_bg and row[x & 3] < thr:
                    pixels[x, y] = blue_ink

    # ------------------------------------------------------------------
    # Distant birds in the upper sky.
    for cx_frac, cy_frac, wingspan, left_droop, right_droop in _KANAGAWA_BIRD_ANCHORS:
        bx = round(cx_frac * width)
        by = round(cy_frac * height)
        wing = wingspan // 2
        draw.line((bx - wing, by - left_droop, bx, by), fill=black_ink, width=2)
        draw.line((bx, by, bx + wing, by - right_droop), fill=black_ink, width=2)

    # ------------------------------------------------------------------
    # Horizon line just above the seigaiha band, two rows. Bounds-guarded
    # so y+1 can't run off the canvas on tiny previews (80x60).
    horizon_line_y = round(height * 0.62)
    if page_bg is not None and 0 <= horizon_line_y < height:
        horizon_row = BAYER_4x4[horizon_line_y & 3]
        for px in range(width):
            if pixels[px, horizon_line_y] == page_bg and horizon_row[px & 3] < 4:
                pixels[px, horizon_line_y] = blue_ink
        next_y = horizon_line_y + 1
        if next_y < height:
            next_row = BAYER_4x4[next_y & 3]
            for px in range(width):
                if pixels[px, next_y] == page_bg and next_row[px & 3] < 4:
                    pixels[px, next_y] = blue_ink

    # ------------------------------------------------------------------
    # Seigaiha tile band from y = 0.66 × height to the bottom (~163 px at
    # 480, about 12 rows).
    band_top_y = round(height * 0.66)
    _draw_seigaiha_band(
        image, draw, band_top_y, height - 1, blue_ink, white_ink, black_ink
    )

    # ------------------------------------------------------------------
    # Hanko seal (bottom-right): a red rounded rectangle softened to
    # oxblood by a maroon post-pass (R+K 1:1, as ``dispatch`` and
    # ``chanbara``), then a stylised 川 in 2 px white strokes. 32×38 px
    # gives the strokes room; smaller reads as scratches.
    seal_w = 32
    seal_h = 38
    seal_margin = 26
    seal_x0 = width - seal_margin - seal_w
    seal_y0 = height - seal_margin - seal_h
    seal_x1 = seal_x0 + seal_w
    seal_y1 = seal_y0 + seal_h
    # ``rounded_rectangle`` clips out-of-bounds coordinates, so on a tiny
    # canvas (the 80x60 preview, ``seal_y0`` = -4) it paints what fits.
    draw.rounded_rectangle((seal_x0, seal_y0, seal_x1, seal_y1), radius=3, fill=red_ink)
    # Maroon post-pass, bounds clamped first: PixelAccess raises on
    # negative indices. Skipped when the seal is fully off-canvas.
    seal_px0 = max(0, seal_x0)
    seal_py0 = max(0, seal_y0)
    seal_px1 = min(width - 1, seal_x1)
    seal_py1 = min(height - 1, seal_y1)
    if seal_px0 <= seal_px1 and seal_py0 <= seal_py1:
        for py in range(seal_py0, seal_py1 + 1):
            for px in range(seal_px0, seal_px1 + 1):
                if pixels[px, py] == red_ink and ((px + py) & 1) == 0:
                    pixels[px, py] = black_ink
    # Stylised 川: three vertical white strokes, the leftmost kinked at the
    # top like a brush entering down-right. 2 px matches a hanko's weight.
    stroke_inset_x = 7
    stroke_inset_y = 6
    sx0 = seal_x0 + stroke_inset_x
    sx1 = seal_x1 - stroke_inset_x
    sxm = (seal_x0 + seal_x1) // 2
    sy0 = seal_y0 + stroke_inset_y
    sy1 = seal_y1 - stroke_inset_y
    # Left stroke — kinked at the top (brush-down motion).
    draw.line((sx0 + 3, sy0, sx0, sy0 + 4), fill=white_ink, width=2)
    draw.line((sx0, sy0 + 4, sx0, sy1), fill=white_ink, width=2)
    # Middle stroke — slightly shorter than the flanking strokes.
    draw.line((sxm, sy0 + 5, sxm, sy1 - 3), fill=white_ink, width=2)
    # Right stroke.
    draw.line((sx1, sy0, sx1, sy1), fill=white_ink, width=2)

    # ------------------------------------------------------------------
    # Body-text knockout: a cream rounded paper card. Inside clear_rect,
    # a white rounded rectangle (radius 12) with a 2 px drop shadow and a
    # 1 px outline, then a sparse yellow stipple. Rounded corners read as
    # a pressed paper card laid on the textile; the corners outside the
    # arc stay seigaiha, which is safe because the kanagawa clear-rect pad
    # keeps the text well inside the card.
    if clear_rect is not None and page_bg is not None:
        cx0, cy0, cx1, cy1 = clear_rect
        cx0 = max(0, cx0)
        cy0 = max(0, cy0)
        cx1 = min(width - 1, cx1)
        cy1 = min(height - 1, cy1)
    # Skip the knockout if the clamped rect collapsed: ``rounded_rectangle``
    # raises ``ValueError`` when ``x1 < x0`` or ``y1 < y0``, which the
    # 80x60 preview can produce.
    if (
        clear_rect is not None
        and page_bg is not None
        and cx1 > cx0
        and cy1 > cy0
    ):
        # Drop shadow: a black rounded rect offset 2 px right and down; the
        # card covers all but a 2 px ledge, read as a lifted paper edge.
        # Deeper would cast a hard shadow.
        draw.rounded_rectangle(
            (cx0 + 2, cy0 + 2, cx1 + 2, cy1 + 2),
            radius=12, fill=black_ink,
        )
        draw.rounded_rectangle((cx0, cy0, cx1, cy1), radius=12, fill=white_ink)
        # 1 px black outline round the card (follows the rounded corners).
        draw.rounded_rectangle(
            (cx0, cy0, cx1, cy1), radius=12, outline=black_ink, width=1,
        )
        # Cream stipple: a yellow dot at four fixed (x, y) positions per
        # 8×8 tile, ~6.25% density. The off-grid anchors avoid the
        # period-4 lattice a 4×4 Bayer pattern shows against the indigo;
        # W + Y averages to warm vellum.
        yellow_ink = SPECTRA6["yellow"]
        cream_anchors = frozenset({(1, 3), (5, 6), (2, 7), (6, 2)})
        for py in range(cy0, cy1 + 1):
            y8 = py & 7
            for px in range(cx0, cx1 + 1):
                x8 = px & 7
                if pixels[px, py] == white_ink and (x8, y8) in cream_anchors:
                    pixels[px, py] = yellow_ink


SPEC = BorderSpec(
    themes=("kanagawa",),
    paint=draw_kanagawa_border,
    # Wide enough to clear the seigaiha crescents. One knockout call: the
    # painter resets the body rect to page_bg at the end, with no grid to
    # re-add inside it (unlike blueprint).
    clear_rect_pad=(14, 6, 6),
)
