"""The ``mucha`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from ..palette import SPECTRA6, BAYER_4x4
from ..spec import BorderSpec


def _draw_mucha_vine(
    draw: ImageDraw.ImageDraw,
    pixels,
    width: int,
    height: int,
    cx: int,
    cy: int,
    direction: int,
    stem_ink,
    leaf_ink,
    leaf_other,
    berry_sentinel,
) -> tuple[int, int, int, int]:
    """Paint one S-shaped vine with three trefoil leaves and a berry at the tip.

    ``direction`` is ``+1`` for a vine running down-right from ``(cx, cy)``
    (top-left corner) and ``-1`` for the mirror running up-left
    (bottom-right corner). Returns the ornament's bbox for the caller's
    post-passes.
    """
    # S-shaped stem as a 7-point polyline over 110 px (PIL has no curve
    # primitive; ``atomic``'s orbits use the same trick).
    stem_pts: list[tuple[int, int]] = []
    for i in range(7):
        t = i / 6.0
        # Two-lobe S: x swings ~18 px round the centre while y advances
        # linearly along ``direction``.
        x_off = round(18 * math.sin(t * math.pi * 1.6) * direction)
        y_off = round(direction * t * 110)
        stem_pts.append((cx + x_off, cy + y_off))
    draw.line(stem_pts, fill=stem_ink, width=2)

    # Three trefoil leaves sprouting along the stem at t = 1/4, 1/2, 3/4.
    leaf_centres: list[tuple[int, int]] = []
    for t_frac in (0.25, 0.5, 0.75):
        idx = round(t_frac * (len(stem_pts) - 1))
        sx, sy = stem_pts[idx]
        # Leaves alternate left / right of the stem.
        side = direction if t_frac == 0.5 else -direction
        leaf_centres.append((sx + side * 16, sy + (8 if t_frac < 0.5 else -6) * direction))

    leaf_radii = (9, 5)  # lobe offset from the leaf centre / lobe radius
    for lcx, lcy in leaf_centres:
        # Each trefoil is three overlapping circles fanning from the
        # attachment point, in the leaf sentinel for the olive post-pass.
        for angle_deg in (-30, 0, 30):
            angle = math.radians(angle_deg)
            ex = lcx + round(leaf_radii[0] * math.cos(angle) * direction)
            ey = lcy + round(leaf_radii[0] * math.sin(angle))
            draw.ellipse(
                (ex - leaf_radii[1], ey - leaf_radii[1], ex + leaf_radii[1], ey + leaf_radii[1]),
                fill=leaf_ink,
            )

    # Berry at the stem tip in ``berry_sentinel``; the caller does the
    # R+Y tangerine post-pass.
    tip_x, tip_y = stem_pts[-1]
    berry_radius = 5
    draw.ellipse(
        (tip_x - berry_radius, tip_y - berry_radius, tip_x + berry_radius, tip_y + berry_radius),
        fill=berry_sentinel,
    )

    # Ornament bbox, padded so the trefoils and berry are inside.
    xs = [p[0] for p in stem_pts] + [lc[0] for lc in leaf_centres] + [tip_x]
    ys = [p[1] for p in stem_pts] + [lc[1] for lc in leaf_centres] + [tip_y]
    bx0 = max(0, min(xs) - leaf_radii[0] - 2)
    by0 = max(0, min(ys) - leaf_radii[0] - 2)
    bx1 = min(width - 1, max(xs) + leaf_radii[0] + 2 + berry_radius)
    by1 = min(height - 1, max(ys) + leaf_radii[0] + 2 + berry_radius)
    return (bx0, by0, bx1, by1)


def draw_mucha_border(image: Image.Image, colors: dict) -> None:
    """Paint an Art Nouveau / Mucha frame: cream Layer-0 wash + thin
    teal rule + organic vine ornaments at two diagonal corners.

    * **Layer 0: cream ground wash**, the Y+W Bayer recipe of
      ``illuminated`` / ``dispatch``: aged ivory poster stock.
    * **Thin teal rule** at inset 18: painted green, then half its
      perimeter flipped to blue on ``(x+y) & 1`` (G+B cyan), matching the
      cyan matched phrase from ``_draw_text_body``.
    * **Vines at the top-left and bottom-right corners**: an S-shaped
      stem (red sentinel → R+K maroon, as the body), trefoil leaves
      (yellow sentinel → Y+G olive, as ``roman``'s laurel) and a berry
      blossom at the tip (→ R+Y 5/8:3/8 tangerine on ``BAYER_4x4``, as
      ``deco``). The other two corners stay bare on purpose: Mucha
      composes asymmetrically.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    page_bg = colors.get("page_bg")
    cream_light = SPECTRA6["yellow"]
    # Sentinels are on-palette inks; each is post-passed to the second ink
    # of its recipe straight after painting.
    stem_sentinel = SPECTRA6["red"]
    stem_other = SPECTRA6["black"]
    leaf_sentinel = SPECTRA6["yellow"]
    leaf_other = SPECTRA6["green"]
    berry_sentinel = SPECTRA6["red"]
    berry_other = SPECTRA6["yellow"]
    rule_sentinel = SPECTRA6["green"]
    rule_other = SPECTRA6["blue"]

    pixels = image.load()
    # Layer 0: sparse 1-in-8 yellow-on-white cream wash.
    if page_bg is not None:
        for y in range(height):
            row = BAYER_4x4[y & 3]
            for x in range(width):
                if pixels[x, y] == page_bg and row[x & 3] < 2:
                    pixels[x, y] = cream_light

    rule_inset = 18
    # Outer rule in the green sentinel, post-passed to cyan.
    draw.rectangle(
        (rule_inset, rule_inset, width - 1 - rule_inset, height - 1 - rule_inset),
        outline=rule_sentinel,
        width=1,
    )
    # Perimeter post-pass: flip half the green pixels to blue → cyan.
    for x in range(rule_inset, width - rule_inset):
        for y in (rule_inset, height - 1 - rule_inset):
            if pixels[x, y] == rule_sentinel and (x + y) & 1:
                pixels[x, y] = rule_other
    for y in range(rule_inset, height - rule_inset):
        for x in (rule_inset, width - 1 - rule_inset):
            if pixels[x, y] == rule_sentinel and (x + y) & 1:
                pixels[x, y] = rule_other

    # Top-left vine.
    tl_bbox = _draw_mucha_vine(
        draw, pixels, width, height,
        cx=rule_inset + 22, cy=rule_inset + 22, direction=+1,
        stem_ink=stem_sentinel, leaf_ink=leaf_sentinel,
        leaf_other=leaf_other, berry_sentinel=berry_sentinel,
    )
    # Bottom-right vine.
    br_bbox = _draw_mucha_vine(
        draw, pixels, width, height,
        cx=width - 1 - rule_inset - 22, cy=height - 1 - rule_inset - 22, direction=-1,
        stem_ink=stem_sentinel, leaf_ink=leaf_sentinel,
        leaf_other=leaf_other, berry_sentinel=berry_sentinel,
    )

    # Stem post-pass: R+K 1:1 maroon, stem sentinel only, so the yellow
    # leaves are left for their own pass.
    for bbox in (tl_bbox, br_bbox):
        bx0, by0, bx1, by1 = bbox
        for py in range(by0, by1 + 1):
            for px in range(bx0, bx1 + 1):
                if pixels[px, py] == stem_sentinel and (px + py) & 1:
                    pixels[px, py] = stem_other
    # Leaf post-pass: Y+G 1:1 olive.
    for bbox in (tl_bbox, br_bbox):
        bx0, by0, bx1, by1 = bbox
        for py in range(by0, by1 + 1):
            for px in range(bx0, bx1 + 1):
                if pixels[px, py] == leaf_sentinel and (px + py) & 1:
                    pixels[px, py] = leaf_other
    # Berry post-pass: R+Y 5/8:3/8 → tangerine. The berry shares the
    # stem's red sentinel, so it is redone in a small radius round each tip.
    for bbox, direction in ((tl_bbox, +1), (br_bbox, -1)):
        bx0, by0, bx1, by1 = bbox
        # The stem pass turned half the berry's red pixels black, so the
        # tip region is repainted tangerine. The tip isn't returned by the
        # helper; it is recovered from the bbox.
        if direction == +1:
            tip_x = bx1 - 7
            tip_y = by1 - 7
        else:
            tip_x = bx0 + 7
            tip_y = by0 + 7
        # Five-petal blossom at the tip, in the berry sentinel so the
        # tangerine pass below picks it up.
        petal_r = 4
        petal_dist = 7
        for k in range(5):
            ang = -math.pi / 2 + k * (2 * math.pi / 5)
            px_c = tip_x + round(petal_dist * math.cos(ang))
            py_c = tip_y + round(petal_dist * math.sin(ang))
            draw.ellipse(
                (px_c - petal_r, py_c - petal_r, px_c + petal_r, py_c + petal_r),
                fill=berry_sentinel,
            )
        core_radius = 6   # central berry: repaint every pixel
        halo_radius = 14  # petal ring: repaint only sentinel petal pixels
        core_sq = core_radius * core_radius
        halo_sq = halo_radius * halo_radius
        for py in range(max(0, tip_y - halo_radius), min(height - 1, tip_y + halo_radius) + 1):
            row = BAYER_4x4[py & 3]
            for px in range(max(0, tip_x - halo_radius), min(width - 1, tip_x + halo_radius) + 1):
                dx = px - tip_x
                dy = py - tip_y
                d_sq = dx * dx + dy * dy
                if d_sq <= core_sq:
                    # Central berry: repaint the whole disc (overwriting the
                    # stem pass's blacks) at threshold 6/16 → tangerine.
                    pixels[px, py] = berry_other if row[px & 3] < 6 else berry_sentinel
                elif d_sq <= halo_sq and pixels[px, py] == berry_sentinel:
                    # Petal ring: only the petal pixels flip; the ground
                    # between petals stays, so five petals read, not a disc.
                    pixels[px, py] = berry_other if row[px & 3] < 6 else berry_sentinel


SPEC = BorderSpec(
    themes=("mucha",),
    paint=draw_mucha_border,
)
