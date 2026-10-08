"""The ``alchemy`` theme's border painter and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from ..palette import SPECTRA6, BAYER_4x4, pixel_access
from ..spec import BorderSpec


def _draw_pentagram(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int, color, line_width: int = 1) -> None:
    """Draw a pentagram (5-pointed star inscribed in a circle).

    First vertex at -90° (12 o'clock), then +72° steps; the star joins every
    second vertex (0→2→4→1→3→0), inside an outline circle.
    """
    # Outer protective circle.
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        outline=color,
        width=line_width,
    )
    # Five outer vertices.
    points = [
        (
            cx + radius * math.cos(math.radians(-90 + i * 72)),
            cy + radius * math.sin(math.radians(-90 + i * 72)),
        )
        for i in range(5)
    ]
    # Pentagram path: every second vertex, one closed path.
    order = [0, 2, 4, 1, 3, 0]
    for i in range(len(order) - 1):
        draw.line(
            [points[order[i]], points[order[i + 1]]],
            fill=color,
            width=line_width,
        )


def _draw_alchemical_triangle(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    radius: int,
    color,
    point_up: bool,
    with_bar: bool,
    line_width: int = 2,
) -> None:
    """Four classical-element triangle glyphs.

    +-----------------+--------------+-------------+
    | ``point_up``    | bare         | bar         |
    +=================+==============+=============+
    | True            | 🜂 Fire       | 🜁 Air        |
    | False           | 🜄 Water      | 🜃 Earth      |
    +-----------------+--------------+-------------+

    The bar marks the "lighter" of each pair (air is light-fire, earth is
    light-water). Drawn as an outlined equilateral triangle inscribed in
    a circle of ``radius``.
    """
    half_base = radius * math.sin(math.radians(60))
    apex_offset = radius
    base_offset = radius * 0.5
    if point_up:
        apex = (cx, cy - apex_offset)
        left = (cx - half_base, cy + base_offset)
        right = (cx + half_base, cy + base_offset)
    else:
        apex = (cx, cy + apex_offset)
        left = (cx - half_base, cy - base_offset)
        right = (cx + half_base, cy - base_offset)
    draw.polygon([apex, right, left], outline=color, width=line_width)

    if with_bar:
        # Horizontal bar at the triangle's mid-height, slightly shorter
        # than the triangle width there so the ends stay inside the outline.
        bar_y = (apex[1] + (left[1] + right[1]) / 2) / 2
        # ``t``: fractional distance from the apex at ``bar_y``.
        if point_up:
            t = (bar_y - apex[1]) / (left[1] - apex[1]) if left[1] != apex[1] else 0
        else:
            t = (apex[1] - bar_y) / (apex[1] - left[1]) if apex[1] != left[1] else 0
        local_half = half_base * t
        bar_half = max(3, local_half - 2)
        draw.line(
            (cx - bar_half, bar_y, cx + bar_half, bar_y),
            fill=color,
            width=line_width,
        )


def draw_alchemy_border(image: Image.Image, colors: dict) -> None:
    """Paint a full transmutation-circle ritual diagram on the panel:
    rectangular ritual boundary + four corner pentagrams + big
    inscribed transmutation circle (double ring + incantation
    tick-band + inscribed pentagram + inner pentagon) + the four
    classical-element glyphs at the outer corners of the inner figure.

    0. **Parchment halftone**: 14 of every 16 yellow ``page_bg`` pixels
       become white on a 4×4 Bayer tile, leaving pale ivory flecked with
       yellow instead of the panel's vivid yellow.
    1. **Outer ritual rule**: a red rectangle, line width 2.
    2. **Four corner pentagrams** in red, radius 22, each in its circle,
       inside the rule.
    3. **Inscribed transmutation circle** centred on the canvas: two
       concentric rings with radial ticks between them (standing in for
       inscribed incantation text), a large inscribed pentagram, and the
       inner pentagon it generates. The body quote overlays it, so the
       whole figure is a 50% blue stipple (dotted hairlines) the black
       serif sits on.
    4. **Four classical-element glyphs** at the outer corners of the
       inner figure, each in its own stippled colour: 🜃 Earth (olive,
       top-left), 🜄 Water (sky, top-right), 🜂 Fire (tangerine,
       bottom-left), 🜁 Air (violet, bottom-right). The heavy downward
       elements sit on top, the light upward ones below; the centre
       positions are left to the circle's arcs.

    The red boundary and corner sigils frame the text; the blue circle
    stands behind it (the red operative / blue philosophical split of
    alchemical manuscripts).
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    rule_color = colors["accent"]               # red ritual boundary
    sigil_color = colors["accent"]              # red corner pentagrams
    hermetic_color = colors["ornament_dark"]    # blue elemental glyphs
    page_bg = colors["page_bg"]                 # yellow — used by the Layer-0 halftone
    stroke = 2

    # ------------------------------------------------------------------
    # Layer 0: Parchment halftone. 14 of every 16 page_bg yellow pixels
    # turn white on a 4×4 Bayer tile, leaving a sparse diagonal pair of
    # yellow flecks per tile that averages to pale ivory. Every pixel is a
    # pure ink, so ``snap_image_to_palette`` is a no-op and glyph edges
    # stay sharp. Painted first so the decoration overpaints it; only
    # exact ``page_bg`` pixels are touched.
    _BAYER_4 = (
        (0, 8, 2, 10),
        (12, 4, 14, 6),
        (3, 11, 1, 9),
        (15, 7, 13, 5),
    )
    halftone_white = SPECTRA6["white"]
    halftone_threshold = 2    # 14 of 16 Bayer cells become white → 87.5% density
    pixels = pixel_access(image)
    for y in range(height):
        row = _BAYER_4[y & 3]
        for x in range(width):
            if pixels[x, y] == page_bg and row[x & 3] >= halftone_threshold:
                pixels[x, y] = halftone_white

    # ------------------------------------------------------------------
    # Layer 1: Outer red ritual boundary.
    outer_inset = 14
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=rule_color,
        width=stroke,
    )

    # ------------------------------------------------------------------
    # Layer 2: Corner pentagrams, offset so each circle (radius 22) sits
    # a few px inside the outer rule, contained by it.
    pent_radius = 22
    pent_offset = outer_inset + 26     # = 40
    pent_centres = [
        (pent_offset, pent_offset),
        (width - 1 - pent_offset, pent_offset),
        (pent_offset, height - 1 - pent_offset),
        (width - 1 - pent_offset, height - 1 - pent_offset),
    ]
    for cx, cy in pent_centres:
        _draw_pentagram(draw, cx, cy, pent_radius, sigil_color, line_width=stroke)

    # ------------------------------------------------------------------
    # Geometry shared by the magic circle and the element glyphs.
    centre_x = width // 2
    centre_y = height // 2
    top_y = pent_offset
    bot_y = height - 1 - pent_offset
    flank_radius = 22               # element glyphs; big enough that bar / no-bar reads under the 4 px stroke
    flank_spacing = 80              # px between centre and outer-corner glyph

    # ------------------------------------------------------------------
    # Layer 3: Inscribed transmutation circle: concentric rings carrying a
    # tick band, an inscribed pentagram and the inner pentagon, all at
    # line width 1 so the body quote stays dominant.
    outer_ring_r = 222
    inner_ring_r = 212

    # The inner figure runs straight through the body text, so it paints
    # in a sentinel and is converted below to a 50% (x+y) parity stipple
    # of blue on the parchment: each hairline becomes a faint dotted
    # construction line the black serif sits on. The red outer rule and
    # corner sigils stay solid; they frame the text and don't cross it.
    solid_hermetic = hermetic_color
    hermetic_color = (5, 5, 5)

    # 3a. Outer + inner concentric rings, the band between them where the
    # incantation would be lettered.
    draw.ellipse(
        (centre_x - outer_ring_r, centre_y - outer_ring_r,
         centre_x + outer_ring_r, centre_y + outer_ring_r),
        outline=hermetic_color, width=1,
    )
    draw.ellipse(
        (centre_x - inner_ring_r, centre_y - inner_ring_r,
         centre_x + inner_ring_r, centre_y + inner_ring_r),
        outline=hermetic_color, width=1,
    )

    # 3b. Incantation tick band: 72 radial dashes between the rings (one
    # per 5°), the rhythm of inscribed letters. Real text along that arc
    # would be sub-pixel on the panel and dither into noise.
    tick_count = 72
    for i in range(tick_count):
        theta = math.radians(i * 360 / tick_count)
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        x0 = centre_x + (inner_ring_r + 1) * cos_t
        y0 = centre_y + (inner_ring_r + 1) * sin_t
        x1 = centre_x + (outer_ring_r - 1) * cos_t
        y1 = centre_y + (outer_ring_r - 1) * sin_t
        draw.line((x0, y0, x1, y1), fill=hermetic_color, width=1)

    # 3c. Inscribed pentagram (0→2→4→1→3→0), vertices a few px inside the
    # inner ring so the star reads as inscribed, not touching.
    inscribed_pent_r = 195
    inscribed_pent_vertices = [
        (
            centre_x + inscribed_pent_r * math.cos(math.radians(-90 + i * 72)),
            centre_y + inscribed_pent_r * math.sin(math.radians(-90 + i * 72)),
        )
        for i in range(5)
    ]
    pent_path_order = [0, 2, 4, 1, 3, 0]
    for i in range(len(pent_path_order) - 1):
        draw.line(
            (inscribed_pent_vertices[pent_path_order[i]],
             inscribed_pent_vertices[pent_path_order[i + 1]]),
            fill=hermetic_color, width=1,
        )

    # 3d. Inner pentagon through the pentagram's five inner intersections:
    # circumradius = pentagram radius / phi² (≈ 2.618), vertices rotated
    # 36° from the outer ones (-54°, 18°, 90°, …). The body quote overlays
    # this "operative chamber".
    phi_squared = (1 + math.sqrt(5)) ** 2 / 4   # ≈ 2.618
    inner_pent_r = inscribed_pent_r / phi_squared
    inner_pentagon_vertices = [
        (
            centre_x + inner_pent_r * math.cos(math.radians(-54 + i * 72)),
            centre_y + inner_pent_r * math.sin(math.radians(-54 + i * 72)),
        )
        for i in range(5)
    ]
    draw.polygon(inner_pentagon_vertices, outline=hermetic_color, width=1)

    figure_x0 = max(0, centre_x - outer_ring_r - 2)
    figure_y0 = max(0, centre_y - outer_ring_r - 2)
    figure_x1 = min(width - 1, centre_x + outer_ring_r + 2)
    figure_y1 = min(height - 1, centre_y + outer_ring_r + 2)
    for py in range(figure_y0, figure_y1 + 1):
        for px in range(figure_x0, figure_x1 + 1):
            if pixels[px, py] == hermetic_color:
                pixels[px, py] = solid_hermetic if (px + py) & 1 == 0 else halftone_white
    hermetic_color = solid_hermetic

    # ------------------------------------------------------------------
    # Layer 4: Four classical-element glyphs at the outer corners of the
    # inner figure: heavy downward elements top-left / top-right, light
    # upward ones bottom-left / bottom-right. The centre positions are
    # left to the circle's arcs.
    #
    # Each element gets its own 2-ink mix: earth → olive (Y+G 1:1), water
    # → sky (B+W 1:1), fire → tangerine (R+Y 5/8:3/8), air → violet
    # (R+B 1:1), with a heavier stroke (``triangle_stroke``) than the
    # ritual rule.
    #
    # Each triangle is painted in a unique off-palette sentinel, and a
    # per-element bbox post-pass converts exactly those pixels. Don't use
    # an on-palette sentinel: Earth's bbox overlaps the Layer-0 yellow
    # flecks, and a yellow sentinel would flip them too (a visible green
    # rectangle round the glyph).
    #
    # Air is 2-ink violet rather than 3-ink lavender because only the
    # rectangle-only ``_fill_swatch_stipple_3way`` does 3-way mixes.
    triangle_stroke = 4
    earth_sentinel = (1, 1, 1)
    water_sentinel = (2, 2, 2)
    fire_sentinel = (3, 3, 3)
    air_sentinel = (4, 4, 4)
    elements = (
        # (cx, cy, point_up, with_bar, sentinel, dark_ink, light_ink, density, label)
        (centre_x - 2 * flank_spacing, top_y, False, True,
         earth_sentinel, SPECTRA6["yellow"], SPECTRA6["green"], 0.5, "🜃 Earth/olive"),
        (centre_x + 2 * flank_spacing, top_y, False, False,
         water_sentinel, SPECTRA6["blue"], SPECTRA6["white"], 0.5, "🜄 Water/sky"),
        (centre_x - 2 * flank_spacing, bot_y, True, False,
         fire_sentinel, SPECTRA6["red"], SPECTRA6["yellow"], 0.375, "🜂 Fire/tangerine"),
        (centre_x + 2 * flank_spacing, bot_y, True, True,
         air_sentinel, SPECTRA6["red"], SPECTRA6["blue"], 0.5, "🜁 Air/violet"),
    )
    for cx, cy, point_up, with_bar, sentinel, dark_ink, light_ink, density, _ in elements:
        _draw_alchemical_triangle(
            draw, cx, cy, flank_radius, sentinel,
            point_up=point_up, with_bar=with_bar, line_width=triangle_stroke,
        )
        # Per-element bbox post-pass, padded 4 px past flank_radius so
        # antialiased corner pixels stay in scope.
        bx0 = max(0, cx - flank_radius - 4)
        by0 = max(0, cy - flank_radius - 4)
        bx1 = min(width - 1, cx + flank_radius + 4)
        by1 = min(height - 1, cy + flank_radius + 4)
        threshold = round(density * 16)
        if density <= 0.25:
            for py in range(by0, by1 + 1):
                for px in range(bx0, bx1 + 1):
                    if pixels[px, py] == sentinel:
                        pixels[px, py] = light_ink if (px & 1) == 0 and (py & 1) == 0 else dark_ink
        elif density >= 0.5:
            for py in range(by0, by1 + 1):
                for px in range(bx0, bx1 + 1):
                    if pixels[px, py] == sentinel:
                        pixels[px, py] = light_ink if (px + py) & 1 == 0 else dark_ink
        else:
            for py in range(by0, by1 + 1):
                bayer_row = BAYER_4x4[py & 3]
                for px in range(bx0, bx1 + 1):
                    if pixels[px, py] == sentinel:
                        pixels[px, py] = light_ink if bayer_row[px & 3] < threshold else dark_ink
    # The element triangles use their own inks; ``hermetic_color`` is done.
    del hermetic_color


SPEC = BorderSpec(
    themes=("alchemy",),
    paint=draw_alchemy_border,
    # past the TR pentagram's circle (leftmost x=width-63)
    # plus a 13 px gap
    debug_label_inset=76,
)
