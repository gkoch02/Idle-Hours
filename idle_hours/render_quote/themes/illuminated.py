"""The ``illuminated`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..palette import SPECTRA6, BAYER_4x4
from ..spec import BorderSpec


def draw_illuminated_border(image: Image.Image, colors: dict) -> None:
    """Paint a manuscript-style border: cream-washed vellum + double
    rubricated rule + plum corner cabochons.

    * **Layer 0: sparse cream ground wash.** A 4×4 Bayer dither flips
      ~12.5% of the white ``page_bg`` pixels (cells < 2) to yellow, which
      averages to a faint aged-vellum tone (the threshold ``dispatch``'s
      Layer 0 uses).
    * **Double rubricated rule**: two thin red rectangles with a narrow
      blank band between them.
    * **Plum corner cabochons**: each gem is painted in a sentinel, then
      a per-jewel bbox post-pass assigns red / blue / black through a
      3-way 4×4 Bayer partition (cells 0-4 / 5-9 / 10-15), the R+B+K
      deep-plum recipe in ``spectra6_color_recipes.md``.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    body = colors["text"]       # rubricated red
    accent = colors["accent"]   # lapis blue; selects the plum-jewel branch below
    page_bg = colors.get("page_bg")
    cream_light = SPECTRA6["yellow"]

    # Layer 0: sparse 1-in-8 yellow-on-white cream wash. Only exact
    # ``page_bg`` pixels are flipped, so palette-mismatch test paths stay valid.
    pixels = image.load()
    if page_bg is not None:
        for y in range(height):
            row = BAYER_4x4[y & 3]
            for x in range(width):
                if pixels[x, y] == page_bg and row[x & 3] < 2:
                    pixels[x, y] = cream_light

    outer_inset = 14
    inner_inset = 22
    # Outer rule.
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=body,
        width=1,
    )
    # Inner rule — the "doubled" rubrication line.
    draw.rectangle(
        (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
        outline=body,
        width=1,
    )

    jewel_radius = 5
    centres = [
        (outer_inset, outer_inset),
        (width - 1 - outer_inset, outer_inset),
        (outer_inset, height - 1 - outer_inset),
        (width - 1 - outer_inset, height - 1 - outer_inset),
    ]
    # Plum cabochons only for the standard palette (accent = lapis blue).
    # A direct caller with a non-standard accent gets a solid jewel in that
    # accent, so ``uses_theme_colours_not_hardcoded_rgb`` still holds.
    if accent == SPECTRA6["blue"]:
        jewel_sentinel = (1, 1, 1)
        for cx, cy in centres:
            draw.ellipse(
                (cx - jewel_radius, cy - jewel_radius, cx + jewel_radius, cy + jewel_radius),
                fill=jewel_sentinel,
            )
        # 3-way Bayer translation: cells 0-4 → red, 5-9 → blue, 10-15 → black.
        ink_red = SPECTRA6["red"]
        ink_blue = SPECTRA6["blue"]
        ink_black = SPECTRA6["black"]
        for cx, cy in centres:
            x0 = max(0, cx - jewel_radius - 1)
            y0 = max(0, cy - jewel_radius - 1)
            x1 = min(width - 1, cx + jewel_radius + 1)
            y1 = min(height - 1, cy + jewel_radius + 1)
            for py in range(y0, y1 + 1):
                row = BAYER_4x4[py & 3]
                for px in range(x0, x1 + 1):
                    if pixels[px, py] == jewel_sentinel:
                        cell = row[px & 3]
                        if cell < 5:
                            pixels[px, py] = ink_red
                        elif cell < 10:
                            pixels[px, py] = ink_blue
                        else:
                            pixels[px, py] = ink_black
    else:
        for cx, cy in centres:
            draw.ellipse(
                (cx - jewel_radius, cy - jewel_radius, cx + jewel_radius, cy + jewel_radius),
                fill=accent,
            )

    # Head ornament: three red lozenges in the "⁂" section-break
    # triangle, each with a blue centre dot (rubric + lapis). At y≈42,
    # below the y=14-29 debug-banner band and above the text (y >= 72).
    hcx = width // 2
    hy = 42
    lz = 4  # lozenge half-size
    for px, py in ((hcx, hy - 5), (hcx - 11, hy + 5), (hcx + 11, hy + 5)):
        draw.polygon(
            [(px, py - lz), (px + lz, py), (px, py + lz), (px - lz, py)],
            fill=body,
        )
        draw.point((px, py), fill=accent)

    # Foot line-filler: a centred red rule pierced by a red lozenge and
    # flanked by two blue ones, the filler scribes ran to the end of a
    # short line. Centred, clear of the bottom-left attribution.
    fy = height - 1 - outer_inset - 14
    draw.line((hcx - 44, fy, hcx - 8, fy), fill=body, width=1)
    draw.line((hcx + 8, fy, hcx + 44, fy), fill=body, width=1)
    draw.polygon([(hcx, fy - lz), (hcx + lz, fy), (hcx, fy + lz), (hcx - lz, fy)], fill=body)
    for fx in (hcx - 50, hcx + 50):
        draw.polygon(
            [(fx, fy - 3), (fx + 3, fy), (fx, fy + 3), (fx - 3, fy)],
            fill=accent,
        )


SPEC = BorderSpec(
    themes=("illuminated",),
    paint=draw_illuminated_border,
    # past the TR jewel (frame at 14, radius 5 → x=width-9)
    debug_label_inset=28,
)
