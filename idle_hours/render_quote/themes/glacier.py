"""The ``glacier`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..palette import SPECTRA6, BAYER_4x4
from ..spec import BorderSpec


def draw_glacier_border(image: Image.Image, colors: dict) -> None:
    """Paint an icy / aurora border: thin outer rule + four corner
    frost-crystal clusters + four mid-edge snowflake-tick stars.

    * **Outer frame**: one rectangle at inset 14, 1 px, ``colors["text"]``
      (blue).
    * **Frost-crystal clusters**: three filled triangles fanning out from
      each corner along the adjacent sides, two blue and the longest
      tipped in ``colors["accent"]`` (green, the aurora). ~8–14 px, well
      outside the quote block (the layout always leaves ≥30 px of corner).
    * **Mid-edge snowflake ticks**: a small four-armed star (radius ~6 px)
      at each edge midpoint, a filled diamond plus a thin cross.

    The top-right cluster (x ≥ width-30, y ≤ 30) overlaps the default
    ``DEBUG MODE`` label band, so ``glacier`` has an entry in
    ``_DEBUG_LABEL_RIGHT_INSET``.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    body_color = colors["text"]
    accent_color = colors["accent"]

    outer_inset = 14
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=body_color,
        width=1,
    )

    # Frost-edge wash: sparse sky-blue frost in the top and bottom
    # margins, densest at the frame edge and tapering inward (a gradient
    # Bayer threshold), like ice creeping across a window. Bands stay in
    # the ≤44 px margins (text never starts before y=72) and flip only
    # *white* ground pixels, so the blue body text stays legible. Skipped
    # on non-white grounds (the unit-test sentinel render).
    pixels = image.load()
    band_depth = 44
    inner_l = outer_inset + 1
    inner_r = width - 1 - outer_inset
    white = SPECTRA6["white"]
    for band_top, grad_dir in ((outer_inset + 1, +1), (height - 1 - outer_inset - band_depth, -1)):
        for row in range(band_depth):
            y = band_top + row
            if y < 0 or y >= height:
                continue
            # Distance from the frame edge (0 at edge → band_depth at inner lip).
            edge_dist = row if grad_dir > 0 else band_depth - 1 - row
            # Peak ~5/16 frost at the edge, fading linearly to bare.
            thresh = max(0, 5 - (edge_dist * 5) // band_depth)
            if thresh <= 0:
                continue
            for x in range(inner_l, inner_r):
                if BAYER_4x4[y % 4][x % 4] < thresh and pixels[x, y] == white:
                    pixels[x, y] = body_color

    # Frost-crystal clusters: from each corner a spray of shards fans into
    # the page: four slim blue splinters (horizontal, vertical, two
    # intermediate) plus the longest diagonal one in the accent, with two
    # dendrite barbs like hoar-frost side-arms, and a blue hub dot.
    corner_anchors = [
        # (anchor_x, anchor_y, dx, dy) — inner-frame corner plus the
        # unit-vector pair pointing into the page.
        (outer_inset + 2, outer_inset + 2, +1, +1),                       # top-left
        (width - 3 - outer_inset, outer_inset + 2, -1, +1),                # top-right
        (outer_inset + 2, height - 3 - outer_inset, +1, -1),               # bottom-left
        (width - 3 - outer_inset, height - 3 - outer_inset, -1, -1),       # bottom-right
    ]
    short_arm = 9
    mid_arm = 12
    long_arm = 16
    base_half = 3  # half-width of each shard's base near the corner
    for ax, ay, dx, dy in corner_anchors:
        # Horizontal shard — tip along the top/bottom edge.
        tip_h = (ax + dx * short_arm, ay)
        draw.polygon([tip_h, (ax, ay - base_half * dy), (ax, ay + base_half * dy)], fill=body_color)
        # Vertical shard — tip along the left/right edge.
        tip_v = (ax, ay + dy * short_arm)
        draw.polygon([tip_v, (ax - base_half * dx, ay), (ax + base_half * dx, ay)], fill=body_color)
        # Two intermediate blue shards filling the 45° fan, offset toward
        # each edge so the spray reads as a crystalline spread.
        tip_m1 = (ax + dx * mid_arm, ay + dy * (mid_arm // 2))
        draw.polygon([tip_m1, (ax + dx * base_half, ay), (ax, ay + dy * base_half)], fill=body_color)
        tip_m2 = (ax + dx * (mid_arm // 2), ay + dy * mid_arm)
        draw.polygon([tip_m2, (ax, ay + dy * base_half), (ax + dx * base_half, ay)], fill=body_color)
        # Diagonal shard — the longest, tipped in accent for aurora.
        tip_d = (ax + dx * long_arm, ay + dy * long_arm)
        draw.polygon(
            [tip_d, (ax + dx * base_half, ay - dy * base_half), (ax - dx * base_half, ay + dy * base_half)],
            fill=accent_color,
        )
        # Dendrite barbs feathering off the diagonal shard (accent, so
        # the sky-blue post-pass below lifts them with the main spine).
        mid_d = (ax + dx * (long_arm - 5), ay + dy * (long_arm - 5))
        draw.line([mid_d, (mid_d[0] + dx * 4, mid_d[1])], fill=accent_color, width=1)
        draw.line([mid_d, (mid_d[0], mid_d[1] + dy * 4)], fill=accent_color, width=1)
        # Hub dot.
        draw.ellipse([ax - 1, ay - 1, ax + 1, ay + 1], fill=body_color)

    # Mid-edge snowflake ticks: six-armed frost stars (three spokes at
    # 0°/60°/120° with a forked barb at each tip) on a filled blue hub
    # diamond, in body colour so they read as frost, not an accent.
    star_r = 7
    midpoints = [
        (width // 2, outer_inset),               # top
        (width // 2, height - 1 - outer_inset),  # bottom
        (outer_inset, height // 2),              # left
        (width - 1 - outer_inset, height // 2),  # right
    ]
    diamond_r = 3
    # Unit directions for three spokes (and their negatives → six arms).
    spokes = [(1.0, 0.0), (0.5, 0.866), (-0.5, 0.866)]
    for mx, my in midpoints:
        draw.polygon(
            [(mx, my - diamond_r), (mx + diamond_r, my), (mx, my + diamond_r), (mx - diamond_r, my)],
            fill=body_color,
        )
        for ux, uy in spokes:
            ex, ey = mx + ux * star_r, my + uy * star_r
            nx, ny = mx - ux * star_r, my - uy * star_r
            draw.line([(nx, ny), (ex, ey)], fill=body_color, width=1)
            # Forked barbs at both tips.
            for tip_x, tip_y, sgn in ((ex, ey, -1), (nx, ny, +1)):
                bx, by = tip_x + sgn * ux * 3, tip_y + sgn * uy * 3
                draw.line([(tip_x, tip_y), (bx - uy * 2, by + ux * 2)], fill=body_color, width=1)
                draw.line([(tip_x, tip_y), (bx + uy * 2, by - ux * 2)], fill=body_color, width=1)

    # Aurora-on-ice post-pass: flip ~50% of the accent (green) shard pixels
    # to white on a 1×1 checkerboard (the G+W 1:1 mint recipe), lifting the
    # long shard into a highlight while the blue shards stay solid.
    # Bbox-scoped: the shards reach at most long_arm+2 px from each anchor.
    pixels = image.load()
    for ax, ay, dx, dy in corner_anchors:
        x0 = min(ax + dx * (long_arm + 2), ax - base_half - 1)
        x1 = max(ax + dx * (long_arm + 2), ax + base_half + 1)
        y0 = min(ay + dy * (long_arm + 2), ay - base_half - 1)
        y1 = max(ay + dy * (long_arm + 2), ay + base_half + 1)
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(width - 1, x1)
        y1 = min(height - 1, y1)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if (x + y) & 1 == 0 and pixels[x, y] == accent_color:
                    pixels[x, y] = SPECTRA6["white"]


SPEC = BorderSpec(
    themes=("glacier",),
    paint=draw_glacier_border,
    # past the TR frost crystal (~x=width-32) plus a ~4 px gap
    debug_label_inset=37,
)
