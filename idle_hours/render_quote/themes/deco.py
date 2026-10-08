"""The ``deco`` theme's border painter, a 1930s art-deco poster: doubled hairline
rules, stepped corners, chevrons and a rising sun in synthesised tangerine.

Design notes: docs/themes.md § deco
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from ..palette import SPECTRA6, BAYER_4x4, pixel_access
from ..spec import BorderSpec


def draw_deco_border(image: Image.Image, colors: dict) -> None:
    """Paint an art-deco poster frame: doubled hairline rule + stepped
    skyscraper-step corner ornaments + a top-centre rising-sun fan, then
    synthesise tangerine from the red accent.

    The final pass flips ~3/8 of the red ``accent`` pixels to yellow on
    ``BAYER_4x4`` (cells < 6), matching ``draw_text_dithered``'s
    ``light_density=0.375`` threshold and phase so border and matched phrase
    share one orange. It runs only when ``accent`` is Spectra-6 red;
    custom-palette direct calls keep a solid accent. Design notes:
    docs/themes.md § deco.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    frame_color = colors["text"]
    accent_color = colors["accent"]

    outer_inset = 14
    inner_inset = 22
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=frame_color,
        width=1,
    )
    draw.rectangle(
        (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
        outline=frame_color,
        width=1,
    )

    # Stepped skyscraper-corner ornaments: three concentric L-shapes
    # inside the inner frame, vertex at the inner-frame corner, arms
    # along the two adjacent sides, growing 12 / 18 / 24 px.
    corner_origins = [
        # (corner_x, corner_y, dx, dy) — corner anchor (inner-frame corner)
        # plus the unit-vector pair pointing inward along the two sides.
        (inner_inset + 1, inner_inset + 1, +1, +1),                       # top-left
        (width - 2 - inner_inset, inner_inset + 1, -1, +1),                # top-right
        (inner_inset + 1, height - 2 - inner_inset, +1, -1),               # bottom-left
        (width - 2 - inner_inset, height - 2 - inner_inset, -1, -1),       # bottom-right
    ]
    for step in (1, 2, 3):
        step_length = 6 + step * 6  # 12 / 18 / 24
        step_offset = step * 2       # 2 / 4 / 6 px gap between concentric L's
        for cx, cy, dx, dy in corner_origins:
            ax = cx + dx * step_offset
            ay = cy + dy * step_offset
            # Horizontal arm along the top/bottom edge of the L.
            draw.line(
                [(ax, ay), (ax + dx * step_length, ay)],
                fill=accent_color,
                width=1,
            )
            # Vertical arm along the left/right edge of the L.
            draw.line(
                [(ax, ay), (ax, ay + dy * step_length)],
                fill=accent_color,
                width=1,
            )

    # Top-centre rising-sun fan: a dot on the inner frame's top edge with
    # five rays fanning up through the y ∈ [14, 22] band between the
    # rules. Rays cap at y = outer_inset + 1 so they never touch the outer
    # hairline.
    fan_cx = width // 2
    fan_cy = inner_inset
    fan_dot_r = 2
    draw.ellipse(
        (fan_cx - fan_dot_r, fan_cy - fan_dot_r, fan_cx + fan_dot_r, fan_cy + fan_dot_r),
        fill=accent_color,
    )
    ray_top_y = outer_inset + 1
    ray_height = fan_cy - ray_top_y
    # Five rays spread across a 90° arc centred straight up (-π/2),
    # symmetric about the vertical axis: angles -π/2 ± k·(π/8).
    for k in (-2, -1, 0, 1, 2):
        angle = -math.pi / 2 + k * (math.pi / 8)
        end_x = fan_cx + math.cos(angle) * ray_height / max(abs(math.sin(angle)), 0.001) \
                if k != 0 else fan_cx
        end_y = ray_top_y
        # Clamp end_x to the fan footprint (~ray_height) so the side rays
        # don't streak off to the canvas edge for small |sin(angle)|.
        max_dx = ray_height
        if end_x < fan_cx - max_dx:
            end_x = fan_cx - max_dx
        elif end_x > fan_cx + max_dx:
            end_x = fan_cx + max_dx
        draw.line(
            [(fan_cx, fan_cy), (end_x, end_y)],
            fill=accent_color,
            width=1,
        )

    # Mid-edge stepped chevrons: three nested chevrons at the left and
    # right mid-edges opening toward the page centre, echoing the corner
    # steps. Painted in the accent *before* the tangerine pass so they get
    # the same orange. Each is 5 px further in and 4 px taller.
    mid_y = height // 2
    for edge_x, dir_in in ((inner_inset + 1, +1), (width - 2 - inner_inset, -1)):
        for step in (0, 1, 2):
            ax = edge_x + dir_in * step * 5
            arm = 6 + step * 4
            # Two arms meeting at a point on the frame side, opening inward.
            draw.line([(ax, mid_y - arm), (ax + dir_in * arm, mid_y)], fill=accent_color, width=1)
            draw.line([(ax, mid_y + arm), (ax + dir_in * arm, mid_y)], fill=accent_color, width=1)

    # Final pass: synthesise orange (see docstring). Threshold (6) and
    # phase match ``draw_text_dithered``'s ``light_density=0.375`` branch.
    if accent_color == SPECTRA6["red"]:
        light = SPECTRA6["yellow"]
        threshold = 6  # round(0.375 * 16) — keep in sync with _draw_text_body
        pixels = pixel_access(image)
        for y in range(image.height):
            row = BAYER_4x4[y % 4]
            for x in range(image.width):
                if row[x % 4] < threshold and pixels[x, y] == accent_color:
                    pixels[x, y] = light

        # Cream core on the fan rays: in the inner band (y ∈ [fan_cy-5,
        # fan_cy], where the rays converge) the remaining red pixels flip
        # to white on (x+y)&1, giving ~3/8 Y + 5/16 W + 5/16 R that fades
        # into tangerine at the tips, a sunburst with a bright centre.
        # Bbox-scoped to x ∈ [fan_cx ± ray_height] so the corner steps
        # stay tangerine.
        cream_band_top = max(0, fan_cy - 5)
        cream_band_bot = min(image.height - 1, fan_cy)
        cream_x_lo = max(0, fan_cx - ray_height)
        cream_x_hi = min(image.width - 1, fan_cx + ray_height)
        cream_light = SPECTRA6["white"]
        for y in range(cream_band_top, cream_band_bot + 1):
            for x in range(cream_x_lo, cream_x_hi + 1):
                if (x + y) & 1 == 0 and pixels[x, y] == accent_color:
                    pixels[x, y] = cream_light


SPEC = BorderSpec(
    themes=("deco",),
    paint=draw_deco_border,
)
