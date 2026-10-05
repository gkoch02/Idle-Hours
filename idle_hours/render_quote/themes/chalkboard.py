"""The ``chalkboard`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from ..palette import SPECTRA6, pixel_access
from ..spec import BorderSpec


def draw_chalkboard_border(image: Image.Image, colors: dict) -> None:
    """Paint a classroom-chalkboard surround: doubled white wooden frame,
    chalk dust in the bottom-left corner, a green-chalk check-mark in the
    upper-right margin, and coral eraser smudges along the bottom.

    * **Doubled wooden frame**: outer rectangle at inset 8, 3 px, plus an
      inner one at inset 18, 1 px. The ~7 px band between stays unfilled
      so the black ground reads as dark wood rather than a flat strip.
    * **Chalk-dust scatter**: a fixed stipple of 1 px white dots in the
      inner frame's bottom-left corner, where the chalk tray sits.
    * **Green-chalk check-mark**: a ``✓`` in solid Spectra-6 green at the
      upper-right inner margin. At y≈45, below the ``DEBUG MODE`` band
      (y=14-29), so ``chalkboard`` needs no ``_DEBUG_LABEL_RIGHT_INSET``
      entry. Solid, because a stippled green no longer reads as chalk.
    * **Coral eraser-smudge dots**: five small red dots along the bottom
      inner edge, half their pixels flipped to white on parity (the R+W
      1:1 coral recipe, as ``draw_placard_border``'s tacks).
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    frame_color = colors["text"]  # white chalk frame on the black slate
    accent_color = colors["accent"]  # yellow chalk-stick (matched phrase)
    chalk_green = SPECTRA6["green"]
    smudge_red = SPECTRA6["red"]

    # Outer thick wooden surround.
    outer_inset = 8
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=frame_color,
        width=3,
    )
    # Inner thin frame — the inside lip of the wood.
    inner_inset = 18
    draw.rectangle(
        (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
        outline=frame_color,
        width=1,
    )

    # Chalk-dust stipple inside the inner frame's BL corner, in a 40×30 px
    # box. Coordinates are fixed (not RNG'd) so every render is identical.
    bl_x = inner_inset + 4
    bl_y = height - 1 - inner_inset - 4
    chalk_offsets = (
        (0, 0),  (5, -2), (11, 0), (18, -3), (23, 1),
        (3, -8), (9, -7), (16, -9), (22, -7), (28, -10),
        (1, -14), (7, -16), (15, -15), (20, -19), (26, -17),
        (5, -22), (12, -23), (19, -24), (24, -26),
    )
    for dx, dy in chalk_offsets:
        cx = bl_x + dx
        cy = bl_y + dy
        # Single-pixel rectangle, not an ellipse, so PIL doesn't
        # anti-alias the dot into greys for snap_image_to_palette.
        draw.rectangle((cx, cy, cx, cy), fill=frame_color)

    # Green-chalk check-mark: a 5 px down-right stroke joining an 11 px
    # up-right one at the elbow, 2 px wide so it reads as a chalk swipe.
    # Below the debug-banner band, ending at x ≈ width-30 inside the frame.
    tick_elbow_x = width - 1 - inner_inset - 22
    tick_elbow_y = 50
    draw.line(
        ((tick_elbow_x - 5, tick_elbow_y - 5), (tick_elbow_x, tick_elbow_y)),
        fill=chalk_green,
        width=2,
    )
    draw.line(
        ((tick_elbow_x, tick_elbow_y), (tick_elbow_x + 11, tick_elbow_y - 12)),
        fill=chalk_green,
        width=2,
    )

    # Coral eraser smudges: five small circles 110 px apart at
    # y=height-inner-9, just inside the bottom of the inner frame. Painted
    # red; the post-pass below makes them coral (R+W 1:1).
    smudge_radius = 3
    smudge_centres = [
        (180 + i * 110, height - 1 - inner_inset - 9) for i in range(5)
    ]
    for cx, cy in smudge_centres:
        draw.ellipse(
            (cx - smudge_radius, cy - smudge_radius, cx + smudge_radius, cy + smudge_radius),
            fill=smudge_red,
        )

    # Coral post-pass (the ``draw_placard_border`` tack recipe),
    # bbox-scoped per smudge.
    pixels = pixel_access(image)
    for cx, cy in smudge_centres:
        x0 = max(0, cx - smudge_radius)
        y0 = max(0, cy - smudge_radius)
        x1 = min(width - 1, cx + smudge_radius)
        y1 = min(height - 1, cy + smudge_radius)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if (x + y) & 1 == 0 and pixels[x, y] == smudge_red:
                    pixels[x, y] = SPECTRA6["white"]
    # Handwriting practice-guide rule in the top-left margin: solid top,
    # dashed midline, solid baseline, the ruling the Playwrite GB J Guides
    # face is designed around. In white chalk at y≈34-58 (above the y≥72
    # text) and on the left, clear of the right-aligned debug banner.
    guide_x0 = inner_inset + 12
    guide_x1 = guide_x0 + 210
    guide_top = 34
    guide_mid = 46
    guide_base = 58
    draw.line((guide_x0, guide_top, guide_x1, guide_top), fill=frame_color, width=1)
    draw.line((guide_x0, guide_base, guide_x1, guide_base), fill=frame_color, width=1)
    for dash_x in range(guide_x0, guide_x1, 12):  # dashed midline
        draw.line((dash_x, guide_mid, dash_x + 6, guide_mid), fill=frame_color, width=1)

    # Gold-star sticker just left of the check (tick + star): a small
    # five-point star in the accent, in the same y≈50 band, so still no
    # _DEBUG_LABEL_RIGHT_INSET entry.
    star_cx = tick_elbow_x - 40
    star_cy = tick_elbow_y - 4
    star_r = 9
    star_pts = []
    for k in range(10):
        ang = -math.pi / 2 + k * math.pi / 5
        rr = star_r if k % 2 == 0 else star_r * 0.42
        star_pts.append((star_cx + rr * math.cos(ang), star_cy + rr * math.sin(ang)))
    draw.polygon(star_pts, fill=accent_color)

    # The accent is not used past the star.
    del accent_color


SPEC = BorderSpec(
    themes=("chalkboard",),
    paint=draw_chalkboard_border,
)
