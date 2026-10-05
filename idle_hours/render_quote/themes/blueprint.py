"""The ``blueprint`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .._paths import META_FONT_CANDIDATES
from ..fonts import load_font
from ..palette import SPECTRA6
from ..spec import BorderSpec


def draw_blueprint_border(image: Image.Image, colors: dict, clear_rect: tuple[int, int, int, int] | None = None) -> None:
    """Paint a cyanotype drafting sheet: dithered ground + frame + grid + crosshairs.

    * **Layer 0: 50/50 white-on-blue checkerboard ground.** Every
      ``page_bg`` pixel on one half of a 1-px checkerboard becomes white,
      so the panel's saturated blue averages to a paler cyanotype wash
      (the trick ``atomic`` uses for its green). Painted first so the
      later layers overpaint it; skipped when ``page_bg`` is absent so
      direct-call test paths stay valid.
    * **Outer frame** in the body-text colour (white in production).
    * **Graph-paper grid** at 20px spacing inside the frame. When
      ``clear_rect`` is given the grid skips that window so the quote
      gets a calmer field.
    * **Corner registration crosshairs** in the accent colour, matching
      the matched-phrase highlight.
    """
    width, height = image.size
    page_bg = colors.get("page_bg")
    frame_inset = 16
    frame_color = colors.get("subtle", colors["text"])
    border_color = colors["text"]
    mark_color = colors["accent"]

    # Layer 0: 50/50 white-on-blue checkerboard. Only exact ``page_bg``
    # pixels are touched, in case a caller painted accents first.
    if page_bg is not None:
        dither_light = SPECTRA6["white"]
        pixels = image.load()
        for y in range(height):
            for x in range(width):
                if (x + y) & 1 and pixels[x, y] == page_bg:
                    pixels[x, y] = dither_light

    draw = ImageDraw.Draw(image)

    grid_spacing = 20
    grid_left = frame_inset + 1
    grid_right = width - 2 - frame_inset
    grid_top = frame_inset + 1
    grid_bottom = height - 2 - frame_inset

    if clear_rect is not None:
        clear_left, clear_top, clear_right, clear_bottom = clear_rect
    else:
        clear_left = clear_top = clear_right = clear_bottom = None

    x = frame_inset + grid_spacing
    while x <= grid_right:
        if clear_rect is None or x < clear_left or x > clear_right:
            draw.line((x, grid_top, x, grid_bottom), fill=frame_color, width=1)
        else:
            if grid_top < clear_top:
                draw.line((x, grid_top, x, clear_top), fill=frame_color, width=1)
            if clear_bottom < grid_bottom:
                draw.line((x, clear_bottom, x, grid_bottom), fill=frame_color, width=1)
        x += grid_spacing

    y = frame_inset + grid_spacing
    while y <= grid_bottom:
        if clear_rect is None or y < clear_top or y > clear_bottom:
            draw.line((grid_left, y, grid_right, y), fill=frame_color, width=1)
        else:
            if grid_left < clear_left:
                draw.line((grid_left, y, clear_left, y), fill=frame_color, width=1)
            if clear_right < grid_right:
                draw.line((clear_right, y, grid_right, y), fill=frame_color, width=1)
        y += grid_spacing

    draw.rectangle(
        (frame_inset, frame_inset, width - 1 - frame_inset, height - 1 - frame_inset),
        outline=border_color,
        width=1,
    )

    arm = 8
    centres = [
        (frame_inset, frame_inset),
        (width - 1 - frame_inset, frame_inset),
        (frame_inset, height - 1 - frame_inset),
        (width - 1 - frame_inset, height - 1 - frame_inset),
    ]
    for cx, cy in centres:
        draw.line((cx - arm, cy, cx + arm, cy), fill=mark_color, width=1)
        draw.line((cx, cy - arm, cx, cy + arm), fill=mark_color, width=1)

    # --- Drafting callouts. Both sit in the clear margins, so the quote
    # (never above y=72, attribution bottom-left) overpaints nothing and
    # no _DEBUG_LABEL_RIGHT_INSET entry is needed: the dimension line is at
    # y=40, below the y=14-29 banner band, and the scale bar hugs the
    # bottom-right.
    callout_font = load_font(META_FONT_CANDIDATES, size=12)

    # Top overall-width dimension line: end ticks, a rule broken in the
    # centre for the figure, inward arrowheads. Rule + ticks in the body
    # ink; arrowheads + figure in the accent ink.
    dim_y = 40
    dim_l = 120
    dim_r = width - 1 - 120
    mid = width // 2
    figure = str(width)  # "800" at the panel's reference width
    fb = draw.textbbox((0, 0), figure, font=callout_font)
    fw = fb[2] - fb[0]
    gap = fw // 2 + 8
    draw.line((dim_l, dim_y - 8, dim_l, dim_y + 8), fill=border_color, width=1)
    draw.line((dim_r, dim_y - 8, dim_r, dim_y + 8), fill=border_color, width=1)
    draw.line((dim_l, dim_y, mid - gap, dim_y), fill=border_color, width=1)
    draw.line((mid + gap, dim_y, dim_r, dim_y), fill=border_color, width=1)
    for ax, adir in ((dim_l, 1), (dim_r, -1)):
        draw.polygon(
            [(ax, dim_y), (ax + adir * 6, dim_y - 3), (ax + adir * 6, dim_y + 3)],
            fill=mark_color,
        )
    draw.text((mid - fw // 2, dim_y - (fb[3] - fb[1]) // 2 - fb[1]), figure, font=callout_font, fill=mark_color)

    # Bottom-right graduated scale bar: five 16 px cells alternating
    # filled / outline, "SCALE 1:1" above, clear of the corner crosshair
    # and the bottom-left attribution.
    bar_cells = 5
    cell_w = 16
    bar_w = bar_cells * cell_w
    bar_x = width - 1 - frame_inset - 12 - bar_w
    bar_y = height - 1 - frame_inset - 18
    for i in range(bar_cells):
        x0 = bar_x + i * cell_w
        if i % 2 == 0:
            draw.rectangle((x0, bar_y, x0 + cell_w, bar_y + 6), fill=border_color)
        else:
            draw.rectangle((x0, bar_y, x0 + cell_w, bar_y + 6), outline=border_color, width=1)
    draw.text((bar_x, bar_y - 16), "SCALE 1:1", font=callout_font, fill=border_color)


def _paint_blueprint_knockout(image: Image.Image, colors: dict, clear_rect: tuple[int, int, int, int] | None = None) -> None:
    """``render``'s knockout pass for blueprint: three steps, not one call.

    The sheet is painted whole again, the body rect is wiped to ``page_bg``,
    and the sheet is painted once more with ``clear_rect`` so the grid redraws
    inside the wiped rect while the frame, crosshairs and dimension lines stay
    outside it. With no usable rect only the first paint happens.
    """
    draw_blueprint_border(image, colors)
    if clear_rect is not None:
        ImageDraw.Draw(image).rectangle(clear_rect, fill=colors["page_bg"])
        draw_blueprint_border(image, colors, clear_rect=clear_rect)


SPEC = BorderSpec(
    themes=("blueprint",),
    paint=draw_blueprint_border,
    # The grid repaints inside the rect, so the pad only guards a 1 px stroke.
    clear_rect_pad=(2, 2, 2),
    knockout=_paint_blueprint_knockout,
    # past the TR crosshair arm (frame at 16 + 8px arm)
    debug_label_inset=34,
)
