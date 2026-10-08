"""The ``nightvision`` theme's border painter and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .._paths import META_FONT_CANDIDATES
from ..fonts import load_font
from ..palette import SPECTRA6, BAYER_4x4, pixel_access
from ..spec import BorderSpec
from ..text import draw_text


def draw_nightvision_border(image: Image.Image, colors: dict) -> None:
    """Paint a HUD-style nightvision field without closing the outer frame."""
    draw = ImageDraw.Draw(image)
    width, height = image.size
    body = colors["text"]
    accent = colors.get("accent", body)
    subtle = colors.get("subtle", body)

    margin = 12
    arm = 26
    thickness = 2
    right_x = width - 1 - margin
    bottom_y = height - 1 - margin

    # Corner brackets only; the outer frame stays open.
    draw.rectangle((margin, margin, margin + arm, margin + thickness - 1), fill=body)
    draw.rectangle((margin, margin, margin + thickness - 1, margin + arm), fill=body)
    draw.rectangle((right_x - arm, margin, right_x, margin + thickness - 1), fill=body)
    draw.rectangle((right_x - thickness + 1, margin, right_x, margin + arm), fill=body)
    draw.rectangle((margin, bottom_y - thickness + 1, margin + arm, bottom_y), fill=body)
    draw.rectangle((margin, bottom_y - arm, margin + thickness - 1, bottom_y), fill=body)
    draw.rectangle((right_x - arm, bottom_y - thickness + 1, right_x, bottom_y), fill=body)
    draw.rectangle((right_x - thickness + 1, bottom_y - arm, right_x, bottom_y), fill=body)

    # Faint scanlines contained inside the page, leaving the bracket gaps intact.
    for y in range(margin + 18, bottom_y - 6, 14):
        draw.line((margin + 30, y, right_x - 30, y), fill=subtle, width=1)

    # Sage post-pass on the scanlines only: flip ~25% of their green
    # pixels to white (``BAYER_4x4`` cells 0-3), the W+G 3:1 pale-sage
    # recipe, so they read as ambient glow rather than crisp CRT lines.
    # Limited to the scanline x range, so the corner brackets stay solid.
    if subtle == SPECTRA6["green"]:
        pixels = pixel_access(image)
        sage_light = SPECTRA6["white"]
        for scan_y in range(margin + 18, bottom_y - 6, 14):
            row = BAYER_4x4[scan_y & 3]
            for sx in range(margin + 30, right_x - 30):
                if row[sx & 3] < 4 and pixels[sx, scan_y] == subtle:
                    pixels[sx, scan_y] = sage_light

    # Mid-edge targeting ticks that float inside the canvas rather than joining the frame.
    tick = 12
    cx = width // 2
    cy = height // 2
    top_y = margin + 20
    bottom_tick_y = bottom_y - 20
    left_x = margin + 20
    right_tick_x = right_x - 20
    draw.line((cx - 48, top_y, cx - 48 + tick, top_y), fill=accent, width=2)
    draw.line((cx + 48 - tick, top_y, cx + 48, top_y), fill=accent, width=2)
    draw.line((cx - 48, bottom_tick_y, cx - 48 + tick, bottom_tick_y), fill=accent, width=2)
    draw.line((cx + 48 - tick, bottom_tick_y, cx + 48, bottom_tick_y), fill=accent, width=2)
    draw.line((left_x, cy - 32, left_x, cy - 32 + tick), fill=accent, width=2)
    draw.line((left_x, cy + 32 - tick, left_x, cy + 32), fill=accent, width=2)
    draw.line((right_tick_x, cy - 32, right_tick_x, cy - 32 + tick), fill=accent, width=2)
    draw.line((right_tick_x, cy + 32 - tick, right_tick_x, cy + 32), fill=accent, width=2)

    # Tiny corner telemetry, kept clear of the debug-banner region.
    meta_font = load_font(META_FONT_CANDIDATES, size=12)
    draw_text(draw, (24, 20), 'SIG 92%', font=meta_font, fill=accent)
    draw_text(draw, (24, height - 34), 'GAIN AUTO', font=meta_font, fill=accent)
    draw_text(draw, (width - 122, 40), 'AZ 041  EL 17', font=meta_font, fill=accent)

    # HUD bearing-scale ruler along the bottom inner margin: graduated
    # ticks, a taller one every fourth, and a yellow centre caret, between
    # the corner brackets and below GAIN AUTO, clear of the quote.
    scale_y = bottom_y - 3
    scale_l = margin + 110
    scale_r = right_x - 110
    for i, sx in enumerate(range(scale_l, scale_r + 1, 22)):
        notch = 8 if i % 4 == 0 else 4
        draw.line((sx, scale_y, sx, scale_y - notch), fill=body, width=1)
    # Centre index caret — a small downward yellow triangle over the tape.
    draw.polygon(
        [(cx, scale_y - 10), (cx - 4, scale_y - 16), (cx + 4, scale_y - 16)],
        fill=accent,
    )

    # Rangefinder ladder notches on the two bottom brackets' vertical arms.
    # Bottom brackets only, so the top stays clear of the debug band.
    for arm_x, arm_dir in ((margin, +1), (right_x, -1)):
        for step in (8, 14, 20):
            ny = bottom_y - step
            draw.line(
                (arm_x + arm_dir * (thickness + 1), ny, arm_x + arm_dir * (thickness + 5), ny),
                fill=body,
                width=1,
            )


SPEC = BorderSpec(
    themes=("nightvision",),
    paint=draw_nightvision_border,
    # The look is the composite of two paints (issue #361).
    paints_twice=True,
)
