"""The ``risograph`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..palette import SPECTRA6, BAYER_4x4


def draw_risograph_border(image: Image.Image, colors: dict, clear_rect: tuple[int, int, int, int] | None = None) -> None:
    """Paint a lively risograph-inspired print frame.

    ``clear_rect`` is the body-text rectangle ``render`` threads through
    (see ``_CLEAR_RECT_PADS``). When given, the bars and overprint circles
    are painted first, then the rect is knocked back to the paper and
    framed with a misregistered red-over-blue double rule, so the quote
    sits on a pasted-up label with the print-test shapes behind it.

    The look is deliberate misregistration: a primary frame in the text
    colour, a shifted duplicate in the accent colour, crop / register
    marks and a few chunky side blocks, like a print test sheet.

    The shifted registration crosses are painted in a sentinel and
    bbox-post-passed through a 3-way Bayer partition into lavender
    (R + B + W at ~1/3 each), the paler tone where two plates wash
    together. Lavender pulls no black, so the theme's no-black-ink
    invariant holds.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    base = colors["text"]
    accent = colors["accent"]
    shadow = colors.get("subtle", base)

    outer = 20
    inner = 34
    dx, dy = 5, 3

    # Skip any frame rule that would invert (y1 < y0) on a small preview canvas:
    # the curator /api/preview path renders below the native 800×480, and an
    # inverted box raises ValueError in PIL's draw_rectangle.
    if width > 2 * outer and height > 2 * outer:
        draw.rectangle((outer + dx, outer + dy, width - 1 - outer + dx, height - 1 - outer + dy), outline=accent, width=2)
        draw.rectangle((outer, outer, width - 1 - outer, height - 1 - outer), outline=base, width=2)
    if width > 2 * inner and height > 2 * inner:
        draw.rectangle((inner, inner, width - 1 - inner, height - 1 - inner), outline=shadow, width=1)

    # Chunky print bars.
    draw.rectangle((42, 54, 74, 170), fill=accent)
    draw.rectangle((56, 68, 88, 184), outline=base, width=2)
    draw.rectangle((width - 88, height - 184, width - 56, height - 68), fill=base)
    draw.rectangle((width - 102, height - 198, width - 70, height - 82), outline=accent, width=2)

    # Overprint-style circles.
    draw.ellipse((width - 118, 58, width - 54, 122), outline=base, width=2)
    draw.ellipse((width - 112 + dx, 64 + dy, width - 48 + dx, 128 + dy), outline=accent, width=2)
    draw.ellipse((54, height - 128, 118, height - 64), outline=accent, width=2)
    draw.ellipse((48 + dx, height - 122 + dy, 112 + dx, height - 58 + dy), outline=base, width=2)

    # Registration / crop marks.
    def cross(cx: int, cy: int, color: tuple[int, int, int]) -> None:
        draw.line((cx - 10, cy, cx + 10, cy), fill=color, width=1)
        draw.line((cx, cy - 10, cx, cy + 10), fill=color, width=1)
        draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), outline=color, width=1)

    marks = [
        (outer, outer),
        (width - outer, outer),
        (outer, height - outer),
        (width - outer, height - outer),
    ]
    lavender_sentinel = (1, 1, 1)
    for cx, cy in marks:
        cross(cx, cy, base)
        cross(cx + dx, cy + dy, lavender_sentinel)

    # 3-way Bayer post-pass on the sentinel crosses: cells 0-4 → red,
    # cells 5-9 → blue, cells 10-15 → white (~1/3 each, the documented
    # lavender R+B+W recipe). Bbox-scoped per cross.
    pixels = image.load()
    ink_red = SPECTRA6["red"]
    ink_blue = SPECTRA6["blue"]
    ink_white = SPECTRA6["white"]
    for cx, cy in marks:
        sx, sy = cx + dx, cy + dy
        x0 = max(0, sx - 12)
        y0 = max(0, sy - 12)
        x1 = min(width - 1, sx + 12)
        y1 = min(height - 1, sy + 12)
        for py in range(y0, y1 + 1):
            row = BAYER_4x4[py & 3]
            for px in range(x0, x1 + 1):
                if pixels[px, py] == lavender_sentinel:
                    cell = row[px & 3]
                    if cell < 5:
                        pixels[px, py] = ink_red
                    elif cell < 10:
                        pixels[px, py] = ink_blue
                    else:
                        pixels[px, py] = ink_white

    # Colour-registration bar centred in the top margin: the ink-density
    # strip a print shop runs at the sheet edge. Red, blue, lavender
    # (sentinel + post-pass, as for the crosses), red, blue. It sits in
    # the band between the shifted frame's top rule (y=23-24) and the
    # inner rule (y=34), clear of the y=22 gap the illuminated
    # cross-gating test samples at (400, 22). No black ink.
    swatch_w = 22
    swatch_h = 8
    swatch_gap = 4
    bar_kinds = ("red", "blue", "lavender", "red", "blue")
    bar_total = len(bar_kinds) * swatch_w + (len(bar_kinds) - 1) * swatch_gap
    bar_x0 = (width - bar_total) // 2
    bar_y = 24
    lavender_bboxes: list[tuple[int, int, int, int]] = []
    for i, kind in enumerate(bar_kinds):
        sx0 = bar_x0 + i * (swatch_w + swatch_gap)
        sx1 = sx0 + swatch_w
        sy1 = bar_y + swatch_h
        if kind == "red":
            draw.rectangle((sx0, bar_y, sx1, sy1), fill=ink_red)
        elif kind == "blue":
            draw.rectangle((sx0, bar_y, sx1, sy1), fill=ink_blue)
        else:  # lavender overprint swatch
            draw.rectangle((sx0, bar_y, sx1, sy1), fill=lavender_sentinel)
            lavender_bboxes.append((sx0, bar_y, sx1, sy1))
    for x0, y0, x1, y1 in lavender_bboxes:
        for py in range(max(0, y0), min(height, y1 + 1)):
            row = BAYER_4x4[py & 3]
            for px in range(max(0, x0), min(width, x1 + 1)):
                if pixels[px, py] == lavender_sentinel:
                    cell = row[px & 3]
                    if cell < 5:
                        pixels[px, py] = ink_red
                    elif cell < 10:
                        pixels[px, py] = ink_blue
                    else:
                        pixels[px, py] = ink_white

    if clear_rect is not None:
        x0, y0, x1, y1 = clear_rect
        draw.rectangle((x0, y0, x1, y1), fill=colors["page_bg"])
        # Two plates, one slightly off: the base (red) rule on the label's
        # edge and the accent (blue) pass shifted by the same (dx, dy) the
        # outer frame uses, so the label is misregistered like the rest
        # of the sheet. Both rules sit inside the clear-rect pad, clear of
        # the first and last text lines.
        draw.rectangle((x0, y0, x1, y1), outline=base, width=2)
        draw.rectangle((x0 + dx, y0 + dy, x1 + dx, y1 + dy), outline=accent, width=2)
