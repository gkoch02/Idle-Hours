"""The ``atomic`` theme's border painter and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from ..palette import SPECTRA6, BAYER_4x4, pixel_access
from ..spec import BorderSpec


def draw_atomic_border(image: Image.Image, colors: dict) -> None:
    """Atomic-age decorative border: dithered ground + rounded frame + atom + starbursts.

    * **Layer 0: sparse 1-in-4 white-on-green dither ground.** The
      top-left pixel of every 2×2 tile that matches ``page_bg`` becomes
      white; the 25/75 mix reads as a softer Sputnik green, greener than
      a 50/50 checkerboard. Painted first so the decoration overpaints it.
      Every pixel stays a pure ink, so ``snap_image_to_palette`` is a
      no-op and glyph edges stay sharp (the ``alchemy`` halftone trick).
    * **Rounded-corner outer frame** in red, Googie curve language.
    * **Atom symbol** centred at the top: three ellipse orbits (0°, 60°,
      120°) and a red nucleus. PIL can't rotate an ellipse, so each orbit
      is a 64-point polyline rotated by hand. At y=44 with semi-major 24,
      it fits above the text (block_top ≥ 72); centred, it misses the
      right-aligned ``DEBUG MODE`` banner.
    * **Twin starbursts** at the left and right mid-edges: eight rays from
      a small dot, outside the centred text block.

    Decoration uses the theme's ``accent`` (red), except the starbursts and
    bottom boomerang, which are stippled to tangerine.
    """
    width, height = image.size
    page_bg = colors["page_bg"]
    accent = colors["accent"]

    # Layer 0: sparse 1-in-4 white-on-green dither (one white pixel per
    # 2×2 tile). Only exact ``page_bg`` pixels are touched.
    dither_light = SPECTRA6["white"]
    pixels = pixel_access(image)
    for y in range(height):
        for x in range(width):
            if (x & 1) == 0 and (y & 1) == 0 and pixels[x, y] == page_bg:
                pixels[x, y] = dither_light

    draw = ImageDraw.Draw(image)

    # Rounded outer frame.
    frame_inset = 14
    frame_radius = 24
    draw.rounded_rectangle(
        (frame_inset, frame_inset, width - 1 - frame_inset, height - 1 - frame_inset),
        radius=frame_radius,
        outline=accent,
        width=2,
    )

    # Atom symbol: three rotated ellipse outlines + nucleus.
    atom_cx = width // 2
    atom_cy = 44
    orbit_a = 24  # semi-major axis (fits below frame at y=14, above quote_top ≥ 72)
    orbit_b = 8
    n_points = 64
    for angle_deg in (0, 60, 120):
        angle = math.radians(angle_deg)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        points = []
        for i in range(n_points + 1):
            t = 2.0 * math.pi * i / n_points
            x_unrot = orbit_a * math.cos(t)
            y_unrot = orbit_b * math.sin(t)
            px = atom_cx + x_unrot * cos_a - y_unrot * sin_a
            py = atom_cy + x_unrot * sin_a + y_unrot * cos_a
            points.append((px, py))
        draw.line(points, fill=accent, width=1)
    # Nucleus.
    nucleus_r = 4
    draw.ellipse(
        (atom_cx - nucleus_r, atom_cy - nucleus_r, atom_cx + nucleus_r, atom_cy + nucleus_r),
        fill=accent,
    )

    # Twin starbursts at the mid-edges, painted in a red sentinel; the
    # post-pass below flips ~3/8 to yellow (R+Y 5/8:3/8 tangerine, as
    # ``deco``'s matched phrase). The atom stays solid red: solid orbits
    # against warm-stippled rays.
    starburst_outer = 11
    starburst_inner = 4
    centres = ((34, height // 2), (width - 34, height // 2))
    for star_cx, star_cy in centres:
        for angle_deg in range(0, 360, 45):
            angle = math.radians(angle_deg)
            cos_a = math.cos(angle)
            sin_a = math.sin(angle)
            x1 = star_cx + starburst_inner * cos_a
            y1 = star_cy + starburst_inner * sin_a
            x2 = star_cx + starburst_outer * cos_a
            y2 = star_cy + starburst_outer * sin_a
            draw.line((x1, y1, x2, y2), fill=SPECTRA6["red"], width=1)
        # Centre dot.
        draw.ellipse(
            (star_cx - 2, star_cy - 2, star_cx + 2, star_cy + 2),
            fill=SPECTRA6["red"],
        )

    # Tangerine post-pass, bbox-scoped per starburst; only sentinel-red
    # pixels flip, so the green ground and its white flecks pass through.
    sentinel_red = SPECTRA6["red"]
    flip_yellow = SPECTRA6["yellow"]
    for star_cx, star_cy in centres:
        x0 = max(0, star_cx - starburst_outer)
        y0 = max(0, star_cy - starburst_outer)
        x1 = min(width - 1, star_cx + starburst_outer)
        y1 = min(height - 1, star_cy + starburst_outer)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if BAYER_4x4[y & 3][x & 3] < 6 and pixels[x, y] == sentinel_red:
                    pixels[x, y] = flip_yellow

    # Atomic "boomerang" centred in the bottom margin (the Googie / Formica
    # kidney motif): a chevron polygon of two tapered wings with an
    # electron dot off one tip. Red sentinel + the starbursts' tangerine
    # post-pass. Centred (clear of the bottom-left attribution) at
    # y≈height-40, below the quote.
    boom_cx = width // 2
    boom_cy = height - 40
    boomerang = [
        (boom_cx - 38, boom_cy - 6),   # left tip (top edge)
        (boom_cx - 6, boom_cy + 6),    # elbow inner
        (boom_cx + 38, boom_cy - 6),   # right tip (top edge)
        (boom_cx + 30, boom_cy + 2),   # right tip (bottom edge)
        (boom_cx, boom_cy + 13),       # elbow outer
        (boom_cx - 30, boom_cy + 2),   # left tip (bottom edge)
    ]
    draw.polygon(boomerang, fill=sentinel_red)
    # Orbiting-electron dot off the right tip.
    draw.ellipse((boom_cx + 44, boom_cy - 10, boom_cx + 50, boom_cy - 4), fill=sentinel_red)
    bx0 = max(0, boom_cx - 50)
    by0 = max(0, boom_cy - 12)
    bx1 = min(width - 1, boom_cx + 52)
    by1 = min(height - 1, boom_cy + 15)
    for y in range(by0, by1 + 1):
        for x in range(bx0, bx1 + 1):
            if BAYER_4x4[y & 3][x & 3] < 6 and pixels[x, y] == sentinel_red:
                pixels[x, y] = flip_yellow


SPEC = BorderSpec(
    themes=("atomic",),
    paint=draw_atomic_border,
)
