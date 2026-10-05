"""The ``saloon`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import random

from PIL import Image, ImageDraw

from ..palette import DEFAULT_HEIGHT, DEFAULT_WIDTH, SPECTRA6, pixel_access
from ..spec import BorderSpec


# Deterministic foxing-speckle layout for ``draw_saloon_border``, computed
# once at module load with a fixed seed so every render is byte-identical
# (the golden suite, contact sheet and pick-equivalence tests rely on it).
def _build_saloon_foxing_points(
    width: int, height: int, density: int, *, seed: int
) -> list[tuple[int, int, int]]:
    """Scatter ``density`` foxing speckles across a (width × height) field.

    Each speckle is ``(x, y, radius)``: radius 0 is a single pixel, radius
    1 a 3×3 darker spot (~15%). Exactly ``density`` points are returned.
    """
    rng = random.Random(seed)
    points: list[tuple[int, int, int]] = []
    for _ in range(density):
        x = rng.randint(2, width - 3)
        y = rng.randint(2, height - 3)
        # ~85% single pixel (subtle), ~15% 3×3 cluster (darker spot).
        radius = 1 if rng.random() < 0.15 else 0
        points.append((x, y, radius))
    return points


# ~360 speckles at 800×480 reads as aged paper at viewing distance; text
# painted on top hides them except in the gaps, so legibility holds.
_SALOON_FOXING = _build_saloon_foxing_points(
    DEFAULT_WIDTH, DEFAULT_HEIGHT, density=360, seed=0xB2A1
)


def draw_saloon_border(image: Image.Image, colors: dict) -> None:
    """Paint a 19th-century saloon-broadside / wanted-poster background.

    A layered ground that reads as aged hand-printed paper, painted bottom
    to top:

    1. **Foxing speckles** from ``_SALOON_FOXING`` (fixed seed, so every
       render is byte-identical), half red and half green (R+G sepia).
       Text painted on top hides them except in the gaps.
    2. **Top + bottom banner bands**: a thick and a hairline black rule
       sandwiching a row of alternating red diamonds and black dashes. They
       live in the header / footer zones (y < ~58, y > height-58) where no
       body text lands.
    3. **Double-rule frame**: a 3 px sepia outer rule and a 1 px black
       inner rule.
    4. **Corner fleurons**: a black diamond at each outer corner with two
       red triangular wings along the edges.
    5. **Mid-edge red diamonds** punched into the outer rule.
    6. **Side-margin drop pendants** hanging from the left / right
       mid-edge diamonds.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    ink = colors["text"]       # black
    accent = colors["accent"]  # red (foxing, ornaments, fleuron wings)
    bg = colors["page_bg"]

    # The banner / frame rules inset 40 px from each side, so at width ≤ 80
    # (the /api/preview minimum) the rectangles invert and PIL raises
    # ValueError. Skip the decoration there; only width can invert.
    if width <= 80:
        return

    # ------------------------------------------------------------------
    # Layer 1: Foxing speckles. ``_SALOON_FOXING`` is computed for
    # 800×480; other canvas sizes (e.g. contact-sheet tiles) rescale the
    # coordinates to keep the same density. Single pixels and 3×3 spots mix.
    #
    # Half the speckles are green on (px+py) parity, so red+green averages
    # to rust-brown (the R+G 1:1 sepia recipe). Parity keys off the source
    # (px, py), not the rescaled (x, y), so the colour choice is the same
    # at every canvas size.
    sx = width / DEFAULT_WIDTH
    sy = height / DEFAULT_HEIGHT
    foxing_alt = SPECTRA6["green"]
    for px, py, radius in _SALOON_FOXING:
        x = int(px * sx)
        y = int(py * sy)
        speckle_fill = foxing_alt if (px + py) & 1 == 0 else accent
        if radius == 0:
            draw.point((x, y), fill=speckle_fill)
        else:
            draw.rectangle((x - 1, y - 1, x + 1, y + 1), fill=speckle_fill)

    # ------------------------------------------------------------------
    # Layer 2: Top + bottom decorative banner bands: a thick outer rule
    # and a hairline inner rule sandwiching a row of red diamonds and
    # black dashes, read as a typeset divider.
    #
    # Y-positions clear the debug chrome: the ``DEBUG MODE`` banner is
    # y≈14-29, so the top thick rule starts at y=34; the bottom dotted
    # rule is at y=443 and its text at y=451-466, so the bottom thick rule
    # ends at y=440. Body text starts around y=72, 14 px below the top
    # hairline at y=58.
    band_outer_y_top = 34
    band_inner_y_top = 58
    band_outer_y_bot = height - 1 - 39
    band_inner_y_bot = height - 1 - 63
    band_rule_thick = 3
    band_rule_thin = 1

    # Top: thick rule (outer), hairline rule (inner).
    draw.rectangle(
        (40, band_outer_y_top, width - 1 - 40, band_outer_y_top + band_rule_thick - 1),
        fill=ink,
    )
    draw.rectangle(
        (40, band_inner_y_top, width - 1 - 40, band_inner_y_top + band_rule_thin - 1),
        fill=ink,
    )
    # Bottom: hairline rule (inner), thick rule (outer).
    draw.rectangle(
        (40, band_inner_y_bot - band_rule_thin + 1, width - 1 - 40, band_inner_y_bot),
        fill=ink,
    )
    draw.rectangle(
        (40, band_outer_y_bot - band_rule_thick + 1, width - 1 - 40, band_outer_y_bot),
        fill=ink,
    )

    # Banner ornaments: alternating red diamonds and short black dashes
    # between the rules. The strip is below the debug label, so no
    # _DEBUG_LABEL_RIGHT_INSET entry is needed for it.
    diamond_size = 5
    dash_len = 14
    ornament_step = 36
    band_mid_y_top = (band_outer_y_top + band_rule_thick + band_inner_y_top) // 2
    band_mid_y_bot = (band_inner_y_bot + band_outer_y_bot - band_rule_thick) // 2
    n_ornaments = (width - 160) // ornament_step
    start_x = (width - n_ornaments * ornament_step) // 2 + ornament_step // 2
    for i in range(n_ornaments):
        cx = start_x + i * ornament_step
        if i % 2 == 0:
            # Red diamond.
            for cy in (band_mid_y_top, band_mid_y_bot):
                draw.polygon(
                    [
                        (cx, cy - diamond_size),
                        (cx + diamond_size, cy),
                        (cx, cy + diamond_size),
                        (cx - diamond_size, cy),
                    ],
                    fill=accent,
                )
        else:
            # Short black dash.
            for cy in (band_mid_y_top, band_mid_y_bot):
                draw.line(
                    (cx - dash_len // 2, cy, cx + dash_len // 2, cy),
                    fill=ink,
                    width=2,
                )

    # ------------------------------------------------------------------
    # Layer 3: Outer + inner double-rule frame. Tight insets leave the
    # foxing between the page edge and the frame visible.
    #
    # The 3 px outer rule is painted in a red sentinel; the post-pass walks
    # its four edge strips and flips half to green on (x+y)&1 (R+G sepia,
    # as the foxing), a rusted-iron frame. The red-pixel guard tolerates
    # PIL's edge rounding.
    outer_inset = 12
    inner_inset = 18
    outer_rule_width = 3
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=SPECTRA6["red"],
        width=outer_rule_width,
    )
    pixels = pixel_access(image)
    outer_x0, outer_y0 = outer_inset, outer_inset
    outer_x1, outer_y1 = width - 1 - outer_inset, height - 1 - outer_inset
    sepia_light = SPECTRA6["green"]
    sentinel_red = SPECTRA6["red"]
    # Top edge strip — 3 rows.
    for y in range(outer_y0, outer_y0 + outer_rule_width):
        for x in range(outer_x0, outer_x1 + 1):
            if (x + y) & 1 == 0 and pixels[x, y] == sentinel_red:
                pixels[x, y] = sepia_light
    # Bottom edge strip — 3 rows.
    for y in range(outer_y1 - outer_rule_width + 1, outer_y1 + 1):
        for x in range(outer_x0, outer_x1 + 1):
            if (x + y) & 1 == 0 and pixels[x, y] == sentinel_red:
                pixels[x, y] = sepia_light
    # Left edge strip, 3 columns, skipping the rows the top/bottom strips
    # covered so the corner cells are flipped once.
    for x in range(outer_x0, outer_x0 + outer_rule_width):
        for y in range(outer_y0 + outer_rule_width, outer_y1 - outer_rule_width + 1):
            if (x + y) & 1 == 0 and pixels[x, y] == sentinel_red:
                pixels[x, y] = sepia_light
    # Right edge strip — 3 columns, same exclusion as the left strip.
    for x in range(outer_x1 - outer_rule_width + 1, outer_x1 + 1):
        for y in range(outer_y0 + outer_rule_width, outer_y1 - outer_rule_width + 1):
            if (x + y) & 1 == 0 and pixels[x, y] == sentinel_red:
                pixels[x, y] = sepia_light

    draw.rectangle(
        (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
        outline=ink,
        width=1,
    )

    # ------------------------------------------------------------------
    # Layer 4: Corner fleurons: a black diamond on each outer-rule corner
    # with two short red triangular wings along the adjacent edges.
    diamond_corner = 9
    wing_len = 14
    wing_w = 5
    corners = (
        # (cx, cy, dx_along_top_or_bot, dy_along_side)
        (outer_inset, outer_inset, 1, 1),                              # TL
        (width - 1 - outer_inset, outer_inset, -1, 1),                 # TR
        (outer_inset, height - 1 - outer_inset, 1, -1),                # BL
        (width - 1 - outer_inset, height - 1 - outer_inset, -1, -1),   # BR
    )
    for cx, cy, dx, dy in corners:
        # Black filled diamond on the corner anchor.
        draw.polygon(
            [
                (cx, cy - diamond_corner),
                (cx + diamond_corner, cy),
                (cx, cy + diamond_corner),
                (cx - diamond_corner, cy),
            ],
            fill=ink,
        )
        # Red wing along the horizontal edge.
        draw.polygon(
            [
                (cx + dx * (diamond_corner + 2), cy - wing_w),
                (cx + dx * (diamond_corner + 2 + wing_len), cy),
                (cx + dx * (diamond_corner + 2), cy + wing_w),
            ],
            fill=accent,
        )
        # Red wing along the vertical edge.
        draw.polygon(
            [
                (cx - wing_w, cy + dy * (diamond_corner + 2)),
                (cx, cy + dy * (diamond_corner + 2 + wing_len)),
                (cx + wing_w, cy + dy * (diamond_corner + 2)),
            ],
            fill=accent,
        )

    # ------------------------------------------------------------------
    # Layer 5: Mid-edge red diamonds painted over the outer rule, so they
    # read as punched ornaments that break up the long rules.
    mid_diamond = 7
    midpoints = (
        (width // 2, outer_inset),
        (width // 2, height - 1 - outer_inset),
        (outer_inset, height // 2),
        (width - 1 - outer_inset, height // 2),
    )
    for cx, cy in midpoints:
        draw.polygon(
            [
                (cx, cy - mid_diamond),
                (cx + mid_diamond, cy),
                (cx, cy + mid_diamond),
                (cx - mid_diamond, cy),
            ],
            fill=accent,
        )

    # ------------------------------------------------------------------
    # Layer 6: Side-margin drop pendants: two diminishing red diamonds
    # joined by a thin tick, hanging inward from each left/right mid-edge
    # diamond into the empty side margins (x≈12 / x≈787, outside the
    # body's x 60–740). Solid red, not sepia, so they read as printed
    # ornament rather than foxing.
    pendant_sizes = (5, 3)
    pendant_gap = 7
    for edge_x in (outer_inset, width - 1 - outer_inset):
        cy = height // 2
        offset = mid_diamond + pendant_gap
        for size in pendant_sizes:
            dcy = cy + offset
            draw.line((edge_x, dcy - offset + mid_diamond, edge_x, dcy - size), fill=accent, width=1)
            draw.polygon(
                [
                    (edge_x, dcy - size),
                    (edge_x + size, dcy),
                    (edge_x, dcy + size),
                    (edge_x - size, dcy),
                ],
                fill=accent,
            )
            offset += size + pendant_gap

    # ``bg`` is unused.
    del bg


SPEC = BorderSpec(
    themes=("saloon",),
    paint=draw_saloon_border,
    # past the TR fleuron's wing tip (x=width-38) plus a gap
    debug_label_inset=44,
)
