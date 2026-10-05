"""The ``gothic`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..palette import SPECTRA6, pixel_access
from ..spec import BorderSpec


def draw_gothic_border(image: Image.Image, colors: dict) -> None:
    """Paint a Gothic-tracery border: double rule + maroon quatrefoils + cream mid-edge diamonds.

    An outer red rule and inner white rule (a two-colour doubled
    rubrication, unlike ``illuminated``'s single ink).

    Four corner quatrefoils, each four lobes around a white centre dot.
    Lobes are painted red, then a per-lobe bbox post-pass flips half to
    black on ``(x+y)&1`` parity: the R+K 1:1 maroon recipe (as in
    ``dispatch``'s stamp), read as iron-aged tracery.

    Four mid-edge diamonds in cream: painted yellow, then half flipped to
    white on parity (the Y+W 1:1 recipe). This gives the mid-edges their
    own register, distinct from the corner maroon, and echoes the
    candlelit-rubric matched phrase.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    body = colors["text"]      # white ink
    accent = colors["accent"]  # rubric red

    outer_inset = 14
    inner_inset = 22
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=accent,
        width=1,
    )
    draw.rectangle(
        (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
        outline=body,
        width=1,
    )

    # Corner quatrefoils: four lobes in a + around the corner anchor plus
    # a white centre dot for silhouette legibility. Lobes paint red as a
    # sentinel; the post-pass below makes them maroon.
    lobe_radius = 5
    lobe_offset = 4
    sentinel_red = SPECTRA6["red"]
    sentinel_yellow = SPECTRA6["yellow"]
    maroon_dark = SPECTRA6["black"]
    cream_light = SPECTRA6["white"]
    centres = [
        (outer_inset, outer_inset),
        (width - 1 - outer_inset, outer_inset),
        (outer_inset, height - 1 - outer_inset),
        (width - 1 - outer_inset, height - 1 - outer_inset),
    ]
    lobe_bboxes: list[tuple[int, int, int, int]] = []
    for cx, cy in centres:
        for dx, dy in ((0, -lobe_offset), (lobe_offset, 0), (0, lobe_offset), (-lobe_offset, 0)):
            lx, ly = cx + dx, cy + dy
            draw.ellipse(
                (lx - lobe_radius, ly - lobe_radius, lx + lobe_radius, ly + lobe_radius),
                fill=sentinel_red,
            )
            lobe_bboxes.append((lx - lobe_radius, ly - lobe_radius, lx + lobe_radius, ly + lobe_radius))
        draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=body)

    pixels = pixel_access(image)
    # Maroon post-pass on each lobe bbox — flip half of the red pixels
    # to black per (x+y)&1 parity inside the per-lobe bbox.
    for x0, y0, x1, y1 in lobe_bboxes:
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(width - 1, x1)
        y1 = min(height - 1, y1)
        for py in range(y0, y1 + 1):
            for px in range(x0, x1 + 1):
                if (px + py) & 1 == 0 and pixels[px, py] == sentinel_red:
                    pixels[px, py] = maroon_dark

    # Mid-edge cream diamonds — painted in yellow as a sentinel, then a
    # per-diamond bbox post-pass flips half of the painted pixels to
    # white per parity for the documented Y+W cream recipe.
    diamond = 4
    midpoints = [
        (width // 2, outer_inset),
        (width // 2, height - 1 - outer_inset),
        (outer_inset, height // 2),
        (width - 1 - outer_inset, height // 2),
    ]
    for cx, cy in midpoints:
        draw.polygon(
            [(cx, cy - diamond), (cx + diamond, cy), (cx, cy + diamond), (cx - diamond, cy)],
            fill=sentinel_yellow,
        )
    for cx, cy in midpoints:
        x0 = max(0, cx - diamond)
        y0 = max(0, cy - diamond)
        x1 = min(width - 1, cx + diamond)
        y1 = min(height - 1, cy + diamond)
        for py in range(y0, y1 + 1):
            for px in range(x0, x1 + 1):
                if (px + py) & 1 == 0 and pixels[px, py] == sentinel_yellow:
                    pixels[px, py] = cream_light

    # Head + foot trefoil finials, centred in the top and bottom margins
    # just inside the inner frame. Solid rubric red, not the corners'
    # maroon: red+black nearly vanishes on the black ground. Each lobe
    # gets a white centre dot like the quatrefoils. Centred so the top one
    # clears the right-aligned DEBUG MODE banner and the foot one the
    # bottom-left attribution.
    trefoil_r = 5
    trefoil_spread = 8
    for base_cx, base_cy, point_up in (
        (width // 2, inner_inset + 13, True),
        (width // 2, height - 1 - inner_inset - 13, False),
    ):
        vy = -1 if point_up else 1
        lobes = (
            (0, vy * trefoil_spread),               # apex lobe
            (-trefoil_spread, -vy * 2),             # lower-left lobe
            (trefoil_spread, -vy * 2),              # lower-right lobe
        )
        for dx, dy in lobes:
            lx, ly = base_cx + dx, base_cy + dy
            draw.ellipse(
                (lx - trefoil_r, ly - trefoil_r, lx + trefoil_r, ly + trefoil_r),
                fill=accent,
            )
            draw.ellipse((lx - 1, ly - 1, lx + 1, ly + 1), fill=body)
        # Short stem joining the lobes at the trefoil centre.
        draw.ellipse((base_cx - 2, base_cy - 2, base_cx + 2, base_cy + 2), fill=accent)


SPEC = BorderSpec(
    themes=("gothic",),
    paint=draw_gothic_border,
    # past the TR quatrefoil's right lobe (x=width-6)
    debug_label_inset=30,
)
