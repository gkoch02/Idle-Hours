"""The ``fillmore`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from ..palette import SPECTRA6, BAYER_4x4, pixel_access
from ..spec import BorderSpec


def _build_fillmore_blob(cx: int, cy: int, scale: float, seed: int) -> list[tuple[int, int]]:
    """Return an 18-point free-form "melted amoeba" polygon centred on ``(cx, cy)``.

    Deterministic per ``seed``. Nominal radius is ~80×``scale`` px.
    """
    rng = random.Random(seed)
    n = 18
    base_r = 80 * scale
    points: list[tuple[int, int]] = []
    for i in range(n):
        angle = (i / n) * 2 * math.pi
        # Per-vertex radial wobble, ~0.55..1.25 of base_r, keeps it organic.
        wobble = 0.55 + rng.random() * 0.7
        r = base_r * wobble
        x = cx + round(r * math.cos(angle))
        y = cy + round(r * math.sin(angle))
        points.append((x, y))
    return points


def draw_fillmore_border(image: Image.Image, colors: dict) -> None:
    """Paint a 1960s Fillmore poster frame: Layer-0 white wash that
    tempers the saturated-yellow ground, plus corner blob panels in
    diagonal balance, sized to clear the body text area.

    * **Layer 0: sparse 1-in-8 white-on-yellow Bayer wash.** ~2/16 of
      the yellow ``page_bg`` pixels (``BAYER_4x4 < 2``) turn white, the
      cream-wash primitive run in reverse: the saturated yellow softens
      toward sun-faded poster stock without becoming cream. Only exact
      ``page_bg`` pixels flip.
    * **Green blob** in the top-left: a seeded 18-point polygon with a red
      5-point star at its centre, inside the y < 72 top margin.
    * **Blue blob** in the bottom-right, same size, with a yellow disc.

    No outer frame: the corner blobs ground the composition, as on real
    Fillmore posters. Together with the body and matched phrase, all six
    native inks appear on the page.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    green_ink = SPECTRA6["green"]
    blue_ink = SPECTRA6["blue"]
    red_ink = SPECTRA6["red"]
    yellow_ink = SPECTRA6["yellow"]
    page_bg = colors.get("page_bg")

    # Layer 0: sparse 1-in-8 white-on-yellow Bayer wash. Only exact
    # ``page_bg`` pixels flip; skipped when ``page_bg`` is absent so
    # direct-call test paths providing only ``text`` stay valid.
    if page_bg is not None:
        pixels = pixel_access(image)
        for y in range(height):
            row = BAYER_4x4[y & 3]
            for x in range(width):
                if pixels[x, y] == page_bg and row[x & 3] < 2:
                    pixels[x, y] = SPECTRA6["white"]

    # Green blob (TL). At scale=0.4 (base radius 32) this seed spans
    # x≈4..74, y≈8..66, inside the y<72 top margin.
    tl_cx = 38
    tl_cy = 38
    tl_blob = _build_fillmore_blob(tl_cx, tl_cy, scale=0.4, seed=1)
    draw.polygon(tl_blob, fill=green_ink)
    # Small red 5-point star inside the green blob.
    star_r_outer = 12
    star_r_inner = 5
    star_pts: list[tuple[int, int]] = []
    for i in range(10):
        angle = -math.pi / 2 + i * math.pi / 5
        r = star_r_outer if i % 2 == 0 else star_r_inner
        star_pts.append((
            tl_cx + round(r * math.cos(angle)),
            tl_cy + round(r * math.sin(angle)),
        ))
    draw.polygon(star_pts, fill=red_ink)

    # Blue blob (BR), mirrored, same scale.
    br_cx = width - 38
    br_cy = height - 38
    br_blob = _build_fillmore_blob(br_cx, br_cy, scale=0.4, seed=2)
    draw.polygon(br_blob, fill=blue_ink)
    # Small yellow filled circle inside the blue blob.
    inner_r = 12
    draw.ellipse(
        (br_cx - inner_r, br_cy - inner_r, br_cx + inner_r, br_cy + inner_r),
        fill=yellow_ink,
    )


SPEC = BorderSpec(
    themes=("fillmore",),
    paint=draw_fillmore_border,
)
