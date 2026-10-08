"""The ``herbarium`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .._paths import IMFELLENGLISH_ITALIC, IMFELLENGLISH_REGULAR, META_FONT_CANDIDATES
from ..fonts import load_font
from ..palette import SPECTRA6, BAYER_4x4, pixel_access
from ..spec import BorderSpec


def draw_herbarium_border(image: Image.Image, colors: dict) -> None:
    """Paint a 19th-century pressed-plant specimen-sheet frame.

    * **Layer 0: sparse 1-in-8 yellow-on-white cream wash** (the Y+W
      Bayer-threshold-2 recipe of ``illuminated`` / ``dispatch``). Only
      exact ``page_bg`` pixels flip, so non-standard test palettes stay
      valid.
    * **Engraver's hairline rule** at inset 14 px, single and black; a
      double rule would compete with the specimen.
    * **Pressed leaf** in the bottom-right: an ~84×42 px oval painted in
      a yellow sentinel and half flipped to green on ``(x+y) & 1`` (Y+G
      olive, dried-leaf colour), with a solid green midrib and three
      pairs of veins. Painted before the text, so text sits on top.
    * **Specimen cartouche** in the bottom-left, the leaf's diagonal
      counterweight: a ~140×32 px black outline holding ``"Tempus fugit"``
      in small IM Fell English italic (META_FONT chain fallback).
    * **Four pinhole dots** at the inner corners of the rule, where the
      specimen would be pinned.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    ink = colors["text"]
    page_bg = colors.get("page_bg")
    cream_light = SPECTRA6["yellow"]
    olive_sentinel = cream_light
    olive_other = SPECTRA6["green"]

    pixels = pixel_access(image)
    if page_bg is not None:
        for y in range(height):
            row = BAYER_4x4[y & 3]
            for x in range(width):
                if pixels[x, y] == page_bg and row[x & 3] < 2:
                    pixels[x, y] = cream_light

    outer_inset = 14
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=ink,
        width=1,
    )

    # Pressed leaf (bottom-right): a horizontal ellipse in the olive
    # sentinel (yellow), half flipped to green below.
    leaf_w = 84
    leaf_h = 42
    leaf_inset = 38
    leaf_cx = width - 1 - leaf_inset - leaf_w // 2
    leaf_cy = height - 1 - leaf_inset - leaf_h // 2
    leaf_left = leaf_cx - leaf_w // 2
    leaf_right = leaf_cx + leaf_w // 2
    leaf_top = leaf_cy - leaf_h // 2
    leaf_bot = leaf_cy + leaf_h // 2
    draw.ellipse((leaf_left, leaf_top, leaf_right, leaf_bot), fill=olive_sentinel)
    # Stem extending up-right from the leaf, same olive sentinel.
    stem_x0 = leaf_right - 4
    stem_y0 = leaf_cy
    stem_x1 = stem_x0 + 18
    stem_y1 = stem_y0 - 14
    draw.line((stem_x0, stem_y0, stem_x1, stem_y1), fill=olive_sentinel, width=2)
    # Midrib in solid green, which the post-pass leaves alone.
    draw.line((leaf_left + 6, leaf_cy, leaf_right - 6, leaf_cy), fill=olive_other, width=1)
    # Three pairs of side veins fanning outward from the midrib.
    for offset in (-12, 0, 12):
        vx = leaf_cx + offset
        draw.line((vx, leaf_cy, vx - 8, leaf_top + 6), fill=olive_other, width=1)
        draw.line((vx, leaf_cy, vx + 8, leaf_bot - 6), fill=olive_other, width=1)
    # Olive post-pass: flip half the yellow sentinel pixels to green.
    bx0 = max(0, leaf_left - 1)
    by0 = max(0, leaf_top - 16)  # cover the stem too
    bx1 = min(width - 1, max(leaf_right, stem_x1) + 1)
    by1 = min(height - 1, leaf_bot + 1)
    for py in range(by0, by1 + 1):
        for px in range(bx0, bx1 + 1):
            if pixels[px, py] == olive_sentinel and (px + py) & 1:
                pixels[px, py] = olive_other

    # Specimen cartouche (bottom-left). Outline rectangle + small Latin tag.
    label_w = 140
    label_h = 32
    label_inset = 32
    label_x0 = label_inset
    label_y0 = height - 1 - label_inset - label_h
    label_x1 = label_x0 + label_w
    label_y1 = label_y0 + label_h
    draw.rectangle((label_x0, label_y0, label_x1, label_y1), outline=ink, width=1)
    # IM Fell italic at 14 px so the label reads as a tag, not a heading;
    # the META chain guarantees it renders.
    label_text = "Tempus fugit"
    label_font_candidates = [
        IMFELLENGLISH_ITALIC,
        IMFELLENGLISH_REGULAR,
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
        *META_FONT_CANDIDATES,
    ]
    label_font = load_font(label_font_candidates, size=14)
    bbox = draw.textbbox((0, 0), label_text, font=label_font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    tx = label_x0 + (label_w - text_w) // 2
    ty = label_y0 + (label_h - text_h) // 2 - bbox[1]
    draw.text((tx, ty), label_text, font=label_font, fill=ink)
    # A writing rule under the tag, so the box reads as a specimen label.
    draw.line((label_x0 + 8, label_y1 - 6, label_x1 - 8, label_y1 - 6), fill=ink, width=1)

    # Four pinhole dots at the inner corners of the engraver's rule.
    pinhole_offset = 3
    pinhole_radius = 1
    for cx, cy in (
        (outer_inset + pinhole_offset, outer_inset + pinhole_offset),
        (width - 1 - outer_inset - pinhole_offset, outer_inset + pinhole_offset),
        (outer_inset + pinhole_offset, height - 1 - outer_inset - pinhole_offset),
        (width - 1 - outer_inset - pinhole_offset, height - 1 - outer_inset - pinhole_offset),
    ):
        draw.ellipse(
            (cx - pinhole_radius, cy - pinhole_radius, cx + pinhole_radius, cy + pinhole_radius),
            fill=ink,
        )

    # Second specimen: a small fern frond in the top-left margin,
    # counterweighting the bottom-right leaf; same olive recipe.
    fern_x = 54
    fern_top = 34
    fern_bot = 108
    draw.line((fern_x, fern_top, fern_x, fern_bot), fill=olive_sentinel, width=2)
    for fy in range(fern_top + 8, fern_bot, 11):
        span = max(4, (fern_bot - fy) // 6)  # leaflets taper toward the tip
        draw.line((fern_x, fy, fern_x - 10, fy - span), fill=olive_sentinel, width=1)
        draw.line((fern_x, fy, fern_x + 10, fy - span), fill=olive_sentinel, width=1)
    for py in range(fern_top - 2, fern_bot + 2):
        for px in range(fern_x - 12, fern_x + 12):
            if 0 <= px < width and 0 <= py < height and pixels[px, py] == olive_sentinel and (px + py) & 1:
                pixels[px, py] = olive_other

    # Gummed linen tape strips holding the main leaf flat.
    for ty_strip in (leaf_cy - 18, leaf_cy + 16):
        draw.rectangle(
            (leaf_cx - 22, ty_strip - 3, leaf_cx + 22, ty_strip + 3),
            fill=SPECTRA6["white"],
            outline=ink,
        )


SPEC = BorderSpec(
    themes=("herbarium",),
    paint=draw_herbarium_border,
    # past the TR pinhole dot (x=width-19) plus a 4 px gap
    debug_label_inset=24,
    # The look is the composite of two paints (issue #361).
    paints_twice=True,
)
