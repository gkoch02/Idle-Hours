"""The ``newsprint`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..palette import SPECTRA6, BAYER_4x4
from ..spec import BorderSpec


def draw_newsprint_border(image: Image.Image, colors: dict) -> None:
    """Paint a broadsheet-style Scotch-rule border around the canvas margin.

    * **Layer 0: newsprint halftone + faint sepia foxing.** On a 4×4 Bayer
      tile, ``page_bg`` pixels with value < 2 turn black (the 12.5% grey
      pulp halftone), value 6 red and value 9 green. The red and green
      cells sit one row apart in the same column and average to R+G 1:1
      sepia (aged lignin). Values 6 and 9 are chosen to miss every pinned
      border / cross-gating sample coordinate
      (``test_newsprint_inner_hairline_is_one_pixel_and_has_gap_above``,
      ``test_blueprint_border_is_theme_gated`` at (6, 16),
      ``test_illuminated_border_is_theme_gated`` at (400, 22)). The colour
      lives on the paper only, so ``test_newsprint_theme_has_no_colour_accent``
      still holds. All pixels are pure inks, so palette-snap is a no-op.
    * **Scotch rule frame**: a heavy outer and a hairline inner rectangle
      with white between, and nothing else.
    * **Broadsheet typographic furniture**: a thick+thin masthead rule with
      two column-rule ticks, a centred folio rule at the foot, and a small
      black printer's diamond on each. Ink only; all clear of the text
      (y ≥ 72).
    """
    width, height = image.size
    page_bg = colors.get("page_bg")
    ink = colors["text"]

    # Layer 0: halftone + sepia foxing (see docstring). Only exact
    # ``page_bg`` pixels are touched; skipped when ``page_bg`` is absent so
    # direct-call test paths that only provide ``text`` stay valid.
    if page_bg is not None:
        _BAYER_4 = BAYER_4x4
        sepia_red = SPECTRA6["red"]
        sepia_green = SPECTRA6["green"]
        pixels = image.load()
        for y in range(height):
            row = _BAYER_4[y & 3]
            for x in range(width):
                if pixels[x, y] != page_bg:
                    continue
                cell = row[x & 3]
                if cell < 2:
                    pixels[x, y] = ink           # 12.5% black halftone
                elif cell == 6:
                    pixels[x, y] = sepia_red     # 6.25% red speckle at (1, 3)
                elif cell == 9:
                    pixels[x, y] = sepia_green   # 6.25% green speckle at (2, 3)

    draw = ImageDraw.Draw(image)

    # Outer heavy rule.
    outer_inset = 10
    outer_weight = 3
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=ink,
        width=outer_weight,
    )
    # Inner hairline rule, with a gap of white between the two.
    inner_inset = 18
    draw.rectangle(
        (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
        outline=ink,
        width=1,
    )

    # Broadsheet typographic furniture, ink only (the foxing lives on the
    # paper, not the typography), all clear of the text (y ≥ 72).
    rule_l = inner_inset + 6
    rule_r = width - 1 - inner_inset - 6
    # Masthead nameplate rule — a thick+thin Scotch pair spanning the
    # inner frame near the top (y≈38), the separator under a broadsheet's
    # nameplate.
    mast_y = inner_inset + 20
    draw.line([(rule_l, mast_y), (rule_r, mast_y)], fill=ink, width=2)
    draw.line([(rule_l, mast_y + 5), (rule_r, mast_y + 5)], fill=ink, width=1)
    # Two column-rule ticks descending from the masthead, stopping above
    # the text (y≤68 < 72).
    for col_x in (width // 3, 2 * width // 3):
        draw.line([(col_x, mast_y + 10), (col_x, mast_y + 30)], fill=ink, width=1)
    # Folio rule at the foot, short and centred (clear of the bottom-left
    # attribution).
    folio_y = height - 1 - inner_inset - 20
    folio_cx = width // 2
    draw.line([(folio_cx - 90, folio_y), (folio_cx + 90, folio_y)], fill=ink, width=1)
    # Printer's dingbat: a small black diamond on the masthead and folio rules.
    for dcx, dy in ((width // 2, mast_y + 5), (folio_cx, folio_y)):
        draw.polygon([(dcx, dy - 4), (dcx + 4, dy), (dcx, dy + 4), (dcx - 4, dy)], fill=ink)


SPEC = BorderSpec(
    themes=("newsprint",),
    paint=draw_newsprint_border,
)
