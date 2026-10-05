"""The ``bauhaus`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..palette import SPECTRA6
from ..spec import BorderSpec


def draw_bauhaus_border(image: Image.Image, colors: dict) -> None:
    """Paint a Bauhaus-inspired geometric frame around the canvas margin.

    A thin black outer rectangle plus four corner accents in the Bauhaus
    primaries: red circles (TL + BR), a blue square (TR) and a yellow
    triangle (BL).

    Yellow is hardcoded from ``SPECTRA6`` (as ``draw_comic_corner_stripes``
    and ``draw_marker_border`` do) because the bauhaus ``THEMES`` entry has
    only three accent slots; adding a fourth would re-pin every cross-theme
    invariant test for one glyph.

    The corner shapes sit tangent to the canvas edges and overlap the
    outer rectangle's corners. None reaches past x=30, well outside the
    quote block (``SIDE_MARGIN + 18`` is the innermost text feature).
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    frame_inset = 14
    frame_color = colors["text"]
    accent_color = colors["accent"]
    ornament_color = colors["ornament_dark"]
    yellow_primary = SPECTRA6["yellow"]

    # Outer rectangle outline.
    draw.rectangle(
        (frame_inset, frame_inset, width - 1 - frame_inset, height - 1 - frame_inset),
        outline=frame_color,
        width=2,
    )

    corner_size = 22
    corner_margin = 6
    # Top-left: red filled circle.
    draw.ellipse(
        (corner_margin, corner_margin,
         corner_margin + corner_size, corner_margin + corner_size),
        fill=ornament_color,
    )
    # Top-right: blue filled square.
    draw.rectangle(
        (width - corner_margin - corner_size, corner_margin,
         width - corner_margin, corner_margin + corner_size),
        fill=accent_color,
    )
    # Bottom-left: yellow filled triangle, right angle at the corner and
    # hypotenuse rising to the top-right, so it points in at the quote.
    bl_left = corner_margin
    bl_top = height - corner_margin - corner_size
    bl_right = corner_margin + corner_size
    bl_bottom = height - corner_margin
    draw.polygon(
        [(bl_left, bl_bottom), (bl_right, bl_bottom), (bl_right, bl_top)],
        fill=yellow_primary,
    )
    # Bottom-right: red filled circle, mirroring the top-left and completing
    # the diagonal colour balance.
    draw.ellipse(
        (width - corner_margin - corner_size, height - corner_margin - corner_size,
         width - corner_margin, height - corner_margin),
        fill=ornament_color,
    )

    # Concentric outline ring around the two corner circles (a Kandinsky
    # concentric-circle study), radius corner_size/2 + 6 in the frame
    # colour; only a quarter-arc stays on canvas. Pure outline, clear of
    # the filled discs.
    half = corner_size // 2
    ring_pad = 6
    for ccx, ccy in (
        (corner_margin + half, corner_margin + half),
        (width - corner_margin - half, height - corner_margin - half),
    ):
        draw.ellipse(
            (ccx - half - ring_pad, ccy - half - ring_pad,
             ccx + half + ring_pad, ccy + half + ring_pad),
            outline=frame_color,
            width=1,
        )

    # Off-centre primary semicircles bulging inward from the top and
    # bottom frames — the playful punctuation of a Bauhaus poster edge.
    # Deliberately set away from the frame midpoints (x=0.68w / 0.32w,
    # never x=width//2) so the composition stays asymmetric and the
    # sampled top/bottom frame-midpoint pixels keep their frame colour.
    semi_r = 14
    top_sx = int(width * 0.68)
    draw.pieslice(
        (top_sx - semi_r, frame_inset - semi_r, top_sx + semi_r, frame_inset + semi_r),
        start=0, end=180, fill=accent_color,
    )
    bot_sx = int(width * 0.32)
    bot_y = height - 1 - frame_inset
    draw.pieslice(
        (bot_sx - semi_r, bot_y - semi_r, bot_sx + semi_r, bot_y + semi_r),
        start=180, end=360, fill=yellow_primary,
    )

    # Two floating primary elements drifting in the otherwise-empty side
    # margins (x≈32 / width-32, well clear of the dense-layout text column
    # at x 60–740) — a small red square on the left and a small blue disc
    # on the right, echoing the corner shapes' forms. Vertically offset
    # from the side-frame midpoints (y=0.34h / 0.66h, never y=height//2)
    # so the sampled left/right frame-midpoint pixels stay frame-coloured.
    sq = 12
    lx, ly = 32, int(height * 0.34)
    draw.rectangle((lx - sq // 2, ly - sq // 2, lx + sq // 2, ly + sq // 2), fill=ornament_color)
    rcx, rcy = width - 32, int(height * 0.66)
    draw.ellipse((rcx - 6, rcy - 6, rcx + 6, rcy + 6), fill=accent_color)


SPEC = BorderSpec(
    themes=("bauhaus",),
    paint=draw_bauhaus_border,
    # past the 6+22px TR filled square
    debug_label_inset=38,
)
