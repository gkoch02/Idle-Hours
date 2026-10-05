"""The ``marker`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..palette import SPECTRA6
from ..spec import BorderSpec

# Cycle of marker-ink colours used by ``draw_marker_border``. Hardcoded
# (like ``_COMIC_STRIPE_PALETTE``) because the marker theme's THEMES entry
# has no yellow or green slot, and extending the schema would re-pin every
# cross-theme invariant test. The theme's point is to use every ink.
_MARKER_BORDER_PALETTE = (
    SPECTRA6["red"],
    SPECTRA6["blue"],
    SPECTRA6["green"],
    SPECTRA6["yellow"],
    SPECTRA6["black"],
)


def draw_marker_border(image: Image.Image, colors: dict) -> None:
    """Paint a fridge-doodle marker frame: multi-colour dashed perimeter,
    asterisk sparkles at every corner, and mid-edge filled marker dots.

    The brief is "use the full capabilities of the display", so the border
    uses all five non-white inks:

    * **Perimeter dashed scribble.** 3 px marker dashes around all four
      edges at a thin inset, cycling ``_MARKER_BORDER_PALETTE``; the
      corners stay empty for the asterisks.
    * **Corner asterisks.** Eight rays (horizontal, vertical, two
      diagonals) round a filled dot: red TL, blue TR, green BL, yellow BR.
      The TR one overlaps the debug-banner band, so
      ``_DEBUG_LABEL_RIGHT_INSET`` pushes the label inward past it.
    * **Mid-edge marker dots.** Two stippled circles hugging the dashes:
      mint (G+W 1:1) on the left, violet (R+B 1:1) on the right.

    ``colors`` is unused but kept so the signature matches the other
    border painters.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size

    # Perimeter dashed scribble. ``inset`` is the edge-to-centre-line
    # distance; ``corner_clear`` keeps dashes off the corners. Dash / gap
    # lengths give ~10–14 dashes per edge, about two palette cycles.
    inset = 12
    corner_clear = 36
    dash_len = 18
    gap_len = 10
    stride = dash_len + gap_len
    thickness = 3

    palette = _MARKER_BORDER_PALETTE
    palette_len = len(palette)
    dash_index = 0

    def _next_colour() -> tuple[int, int, int]:
        nonlocal dash_index
        col = palette[dash_index % palette_len]
        dash_index += 1
        return col

    # Top edge — left to right.
    x = corner_clear
    while x + dash_len <= width - corner_clear:
        draw.line((x, inset, x + dash_len, inset), fill=_next_colour(), width=thickness)
        x += stride
    # Right edge — top to bottom.
    y = corner_clear
    while y + dash_len <= height - corner_clear:
        draw.line(
            (width - 1 - inset, y, width - 1 - inset, y + dash_len),
            fill=_next_colour(),
            width=thickness,
        )
        y += stride
    # Bottom edge — right to left.
    x = width - corner_clear
    while x - dash_len >= corner_clear:
        draw.line((x - dash_len, height - 1 - inset, x, height - 1 - inset), fill=_next_colour(), width=thickness)
        x -= stride
    # Left edge — bottom to top.
    y = height - corner_clear
    while y - dash_len >= corner_clear:
        draw.line((inset, y - dash_len, inset, y), fill=_next_colour(), width=thickness)
        y -= stride

    # Corner asterisks: horizontal + vertical + two diagonals round a
    # filled centre dot, clear of the dashes so the corner doesn't blot.
    aster_inset = 24
    ray = 11
    centre_radius = 3
    corners = (
        (aster_inset, aster_inset, SPECTRA6["red"]),
        (width - 1 - aster_inset, aster_inset, SPECTRA6["blue"]),
        (aster_inset, height - 1 - aster_inset, SPECTRA6["green"]),
        (width - 1 - aster_inset, height - 1 - aster_inset, SPECTRA6["yellow"]),
    )
    for cx, cy, ink in corners:
        # Cardinal arms.
        draw.line((cx - ray, cy, cx + ray, cy), fill=ink, width=2)
        draw.line((cx, cy - ray, cx, cy + ray), fill=ink, width=2)
        # Diagonal arms — slightly shorter so the asterisk reads as
        # a hand-drawn star rather than a pinwheel.
        diag = int(ray * 0.78)
        draw.line((cx - diag, cy - diag, cx + diag, cy + diag), fill=ink, width=2)
        draw.line((cx - diag, cy + diag, cx + diag, cy - diag), fill=ink, width=2)
        # Filled centre dot.
        draw.ellipse(
            (cx - centre_radius, cy - centre_radius, cx + centre_radius, cy + centre_radius),
            fill=ink,
        )

    # Mid-edge marker dots in two stippled mixes: left mint (G+W 1:1, a
    # highlighter wash), right violet (R+B 1:1, a blue pass over red).
    # Each is painted in a sentinel and half flipped to its companion ink
    # on a checkerboard. The dashes and asterisks keep the five solid inks.
    dot_radius = 7
    mid_dots = (
        # (cx, cy, sentinel_dark, light_ink, label)
        (inset + 2, height // 2, SPECTRA6["green"], SPECTRA6["white"], "mint highlighter"),
        (width - 1 - inset - 2, height // 2, SPECTRA6["red"], SPECTRA6["blue"], "violet overlap"),
    )
    pixels = image.load()
    for cx, cy, dark_ink, light_ink, _ in mid_dots:
        draw.ellipse(
            (cx - dot_radius, cy - dot_radius, cx + dot_radius, cy + dot_radius),
            fill=dark_ink,
        )
        bx0 = max(0, cx - dot_radius)
        by0 = max(0, cy - dot_radius)
        bx1 = min(width - 1, cx + dot_radius)
        by1 = min(height - 1, cy + dot_radius)
        for py in range(by0, by1 + 1):
            for px in range(bx0, bx1 + 1):
                if (px + py) & 1 == 0 and pixels[px, py] == dark_ink:
                    pixels[px, py] = light_ink

    # Doodle "twinkle" sparkles in the top + bottom centre margins: a
    # tapered four-point star plus a tiny companion, red at the top and
    # blue at the bottom. The top one (x=width//2-70) clears the
    # right-aligned DEBUG MODE banner and the bottom one the attribution,
    # so marker's TR-asterisk inset entry is still enough.
    def _twinkle(tx: int, ty: int, ink: tuple[int, int, int]) -> None:
        draw.line((tx, ty - 7, tx, ty + 7), fill=ink, width=2)
        draw.line((tx - 7, ty, tx + 7, ty), fill=ink, width=2)
        for ddx, ddy in ((-3, -3), (3, -3), (-3, 3), (3, 3)):
            draw.point((tx + ddx, ty + ddy), fill=ink)
        # Tiny companion sparkle.
        draw.line((tx + 14, ty - 4, tx + 14, ty + 1), fill=ink, width=1)
        draw.line((tx + 12, ty - 2, tx + 17, ty - 2), fill=ink, width=1)
    _twinkle(width // 2 - 70, 26, SPECTRA6["red"])
    _twinkle(width // 2 + 60, height - 1 - 24, SPECTRA6["blue"])


SPEC = BorderSpec(
    themes=("marker",),
    paint=draw_marker_border,
    # past the TR asterisk (rightmost arm x=width-14) plus a gap
    debug_label_inset=44,
)
