"""The ``grimoire`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from ..palette import SPECTRA6, BAYER_4x4
from ..spec import BorderSpec


def _draw_grimoire_sun(draw: ImageDraw.ImageDraw, cx: int, cy: int, accent: tuple[int, int, int]) -> None:
    """Solar ☉ (gold / the Sun): outline circle with a filled centre dot."""
    r = 7
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=accent, width=2)
    draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=accent)


def _draw_grimoire_moon(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    accent: tuple[int, int, int],
    page_bg: tuple[int, int, int],
) -> None:
    """Lunar ☽: a red disk carved by a smaller page-bg disk offset right,
    leaving a left-opening crescent (the alchemical lunar convention)."""
    r = 7
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=accent)
    # Carving disk shifted +4 in x; the overlap stays inside the outer
    # disk, so page_bg is never painted outside the symbol footprint.
    inner_r = 6
    offset = 4
    draw.ellipse(
        (cx - inner_r + offset, cy - inner_r, cx + inner_r + offset, cy + inner_r),
        fill=page_bg,
    )


def _draw_grimoire_mars(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, accent: tuple[int, int, int]
) -> None:
    """Martial ♂: outline circle offset down-left, with a diagonal shaft
    and a V-barb arrowhead pointing NE. Barbs are two short strokes meeting
    at the tip so the arrow still reads at mid-edge symbol scale."""
    r = 6
    # Circle centre pushed down-left so the NE arrow has room without
    # the circle bumping the mid-edge anchor.
    bcx, bcy = cx - 3, cy + 3
    draw.ellipse((bcx - r, bcy - r, bcx + r, bcy + r), outline=accent, width=2)
    # Long diagonal shaft from upper-right of circle outward to NE.
    shaft_start = (bcx + 4, bcy - 4)
    tip = (bcx + 11, bcy - 11)
    draw.line((*shaft_start, *tip), fill=accent, width=2)
    # Two barbs at the tip, each perpendicular to the 45° shaft, forming
    # the canonical arrowhead V. The first barb runs horizontal-left
    # from the tip, the second runs vertical-down from the tip — taken
    # together they "open" the arrowhead in the right direction.
    barb = 5
    draw.line((tip[0] - barb, tip[1], tip[0], tip[1]), fill=accent, width=2)
    draw.line((tip[0], tip[1], tip[0], tip[1] + barb), fill=accent, width=2)


def _draw_grimoire_venus(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, accent: tuple[int, int, int]
) -> None:
    """Venusian ♀: outline circle offset up, with a vertical shaft below
    it and a horizontal crossbar (the complement to Mars)."""
    r = 6
    bcx, bcy = cx, cy - 4
    draw.ellipse((bcx - r, bcy - r, bcx + r, bcy + r), outline=accent, width=2)
    # Vertical shaft from circle bottom downward.
    shaft_top = (bcx, bcy + r)
    shaft_bottom = (bcx, bcy + r + 7)
    draw.line((*shaft_top, *shaft_bottom), fill=accent, width=2)
    # Horizontal crossbar across the shaft, ~2/3 of the way down.
    crossbar_y = bcy + r + 4
    draw.line((bcx - 4, crossbar_y, bcx + 4, crossbar_y), fill=accent, width=2)


def draw_grimoire_border(image: Image.Image, colors: dict) -> None:
    """Paint an alchemical-grimoire border: outer rule + four magic-circle
    inscribed pentagrams + four planetary sigils on the mid-edges.

    Shares ``gothic``'s black/white/red palette but not its silhouette: a
    single thin red rule, an inscribed pentagram (star + ring) at each
    corner, and the four classical planetary sigils breaking the
    mid-edges (Sun ☉ top, Moon ☽ bottom, Mars ♂ left, Venus ♀ right).

    **Pentagrams.** Five vertices of a regular pentagon of radius
    ``pent_radius`` joined in skip-one order (``0 → 2 → 4 → 1 → 3 → 0``),
    first vertex at the top (``angle = -π/2``) so the star stands upright,
    inside a ring of radius ``ring_radius`` ~3 px outside the tips so the
    strokes don't merge.

    **Mid-edge sigils.** Drawn from PIL primitives rather than glyphs,
    because font coverage of ``U+2609`` onward varies across the bundled
    faces. They sit on the outer rule and punch through it, as
    ``gothic``'s mid-edge diamonds do.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    accent = colors["accent"]  # rubric red
    page_bg = colors.get("page_bg", SPECTRA6["black"])

    outer_inset = 14
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=accent,
        width=1,
    )

    # Four inscribed pentagrams at the inset corners. ``corner_offset``
    # keeps each ring (radius + 2 px stroke half-width) clear of the
    # outer rule.
    pent_radius = 11
    ring_radius = 14
    corner_offset = ring_radius + 2
    centres = [
        (outer_inset + corner_offset, outer_inset + corner_offset),
        (width - 1 - outer_inset - corner_offset, outer_inset + corner_offset),
        (outer_inset + corner_offset, height - 1 - outer_inset - corner_offset),
        (width - 1 - outer_inset - corner_offset, height - 1 - outer_inset - corner_offset),
    ]
    skip_one = (0, 2, 4, 1, 3, 0)
    for cx, cy in centres:
        vertices = []
        for i in range(5):
            angle = -math.pi / 2 + i * (2 * math.pi / 5)
            vx = cx + pent_radius * math.cos(angle)
            vy = cy + pent_radius * math.sin(angle)
            vertices.append((vx, vy))
        path = [vertices[i] for i in skip_one]
        draw.line(path, fill=accent, width=2)
        # Surrounding ring — the "magic circle" containing the pentacle.
        draw.ellipse(
            (cx - ring_radius, cy - ring_radius, cx + ring_radius, cy + ring_radius),
            outline=accent,
            width=2,
        )

    # Four planetary sigils centred on the mid-edges of the outer rule,
    # each ~14 px tall. The moon carves its crescent with ``page_bg``
    # inside its own footprint.
    #
    # Each planet gets its own stippled colour (post-pass below): Sun →
    # tangerine (R + 3/8 Y at Bayer threshold 6), Moon → sky (blue sentinel,
    # half to white on (x+y)&1), Mars → maroon (R+K 1:1), Venus → violet
    # (R+B 1:1). The ±16 px bboxes overlap no other layer, so the
    # post-passes are safe to bbox-scope.
    mid_top = (width // 2, outer_inset)
    mid_bottom = (width // 2, height - 1 - outer_inset)
    mid_left = (outer_inset, height // 2)
    mid_right = (width - 1 - outer_inset, height // 2)
    moon_disc_blue = SPECTRA6["blue"]
    _draw_grimoire_sun(draw, *mid_top, accent)
    _draw_grimoire_moon(draw, *mid_bottom, moon_disc_blue, page_bg)
    _draw_grimoire_mars(draw, *mid_left, accent)
    _draw_grimoire_venus(draw, *mid_right, accent)

    # Per-planet bbox post-pass. ``sigil_radius`` generously covers the
    # Mars / Venus off-anchor geometry.
    pixels = image.load()
    sigil_radius = 16
    planet_passes = (
        # (centre, sentinel_ink, light_ink, density)
        (mid_top, SPECTRA6["red"], SPECTRA6["yellow"], 0.375),   # ☉ Sun → tangerine
        (mid_bottom, moon_disc_blue, SPECTRA6["white"], 0.5),    # ☽ Moon → sky
        (mid_left, SPECTRA6["red"], SPECTRA6["black"], 0.5),     # ♂ Mars → maroon
        (mid_right, SPECTRA6["red"], SPECTRA6["blue"], 0.5),     # ♀ Venus → violet
    )
    for (cx, cy), dark_ink, light_ink, density in planet_passes:
        bx0 = max(0, cx - sigil_radius)
        by0 = max(0, cy - sigil_radius)
        bx1 = min(width - 1, cx + sigil_radius)
        by1 = min(height - 1, cy + sigil_radius)
        threshold = round(density * 16)
        if density <= 0.25:
            for py in range(by0, by1 + 1):
                for px in range(bx0, bx1 + 1):
                    if (px & 1) == 0 and (py & 1) == 0 and pixels[px, py] == dark_ink:
                        pixels[px, py] = light_ink
        elif density >= 0.5:
            for py in range(by0, by1 + 1):
                for px in range(bx0, bx1 + 1):
                    if (px + py) & 1 == 0 and pixels[px, py] == dark_ink:
                        pixels[px, py] = light_ink
        else:
            for py in range(by0, by1 + 1):
                row = BAYER_4x4[py & 3]
                for px in range(bx0, bx1 + 1):
                    if row[px & 3] < threshold and pixels[px, py] == dark_ink:
                        pixels[px, py] = light_ink

    # "Tria prima" ``∴`` triads (salt · sulfur · mercury) flanking the Sun
    # and Moon: three red dots each side, filling the top / bottom bands
    # (y≈18-40 / y≈440-462) between the corner pentagrams and the sigils,
    # clear of the body block (y≈72-410).
    triad_r = 2
    triad_spread = 6
    for cy, point_up in ((outer_inset + 14, True), (height - 1 - outer_inset - 14, False)):
        vy = -1 if point_up else 1
        for cx in (width // 2 - 60, width // 2 + 60):
            apex = (cx, cy + vy * triad_spread)
            base_l = (cx - triad_spread, cy - vy * triad_spread // 2)
            base_r = (cx + triad_spread, cy - vy * triad_spread // 2)
            for dx, dy in (apex, base_l, base_r):
                draw.ellipse((dx - triad_r, dy - triad_r, dx + triad_r, dy + triad_r), fill=accent)


SPEC = BorderSpec(
    themes=("grimoire",),
    paint=draw_grimoire_border,
    # past the TR pentagram ring (leftmost x=width-46) plus
    # a 4 px gap; the ring's top is inside the label band
    debug_label_inset=50,
)
