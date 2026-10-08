"""The ``placard`` theme's border painter, a hand-painted shop sign: a weathered doubled
frame, coral thumbtacks, dividers and hanging price tags.

Design notes: docs/themes.md § placard
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..palette import SPECTRA6, pixel_access
from ..spec import BorderSpec


def draw_placard_border(image: Image.Image, colors: dict) -> None:
    """Paint a hand-painted shop-sign / sandwich-board surround: doubled
    sign-painter's frame (sepia outer + black inner) plus four red
    thumbtack corner accents.

    * **Sepia outer frame**: rectangle at inset 14, painted red, then half
      its perimeter pixels flipped to green on ``(x+y)&1`` parity (the R+G
      1:1 rust-brown recipe ``saloon``'s foxing uses), weathered wood.
    * **Inner black frame**: inset 18, 1 px, ``colors["text"]``. The ~3 px
      gap reads as a doubled brush stroke.
    * **Coral thumbtack corner accents**: four small ``colors["accent"]``
      circles just inside each corner, half flipped to white on parity
      (R+W 1:1 coral): faded sign red.
    * **Sign-painter header + footer dividers**: a short centred black rule
      carrying a small coral diamond. Header at y≈34 (above the y≥72 text);
      footer centred, clear of the bottom-left attribution.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    frame_color = colors["text"]
    accent_color = colors["accent"]

    # Outer frame painted red as a sentinel, so the post-pass below can
    # find its pixels without coordinate bookkeeping; the green flip turns
    # it sepia.
    outer_inset = 14
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=SPECTRA6["red"],
        width=1,
    )
    inner_inset = 18
    draw.rectangle(
        (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
        outline=frame_color,
        width=1,
    )

    # Sepia post-pass: walk the outer frame's perimeter only (a bbox walk
    # would touch interior pixels) and flip red→green on (x+y)&1.
    pixels = pixel_access(image)
    outer_x0, outer_y0 = outer_inset, outer_inset
    outer_x1, outer_y1 = width - 1 - outer_inset, height - 1 - outer_inset
    for x in range(outer_x0, outer_x1 + 1):
        for y in (outer_y0, outer_y1):
            if (x + y) & 1 == 0 and pixels[x, y] == SPECTRA6["red"]:
                pixels[x, y] = SPECTRA6["green"]
    for y in range(outer_y0 + 1, outer_y1):
        for x in (outer_x0, outer_x1):
            if (x + y) & 1 == 0 and pixels[x, y] == SPECTRA6["red"]:
                pixels[x, y] = SPECTRA6["green"]
    # ``frame_color`` (black) was only needed for the inner rule.
    del frame_color

    # Red thumbtacks at the inner corners. Centre y=38, radius 4 → bbox
    # y=34-42, so the TR tack sits fully below the y=14-29 debug-label band.
    tack_radius = 4
    tack_inset = 38
    tack_centres = [
        (tack_inset, tack_inset),
        (width - 1 - tack_inset, tack_inset),
        (tack_inset, height - 1 - tack_inset),
        (width - 1 - tack_inset, height - 1 - tack_inset),
    ]
    for cx, cy in tack_centres:
        draw.ellipse(
            (cx - tack_radius, cy - tack_radius, cx + tack_radius, cy + tack_radius),
            fill=accent_color,
        )

    # Weathered-paint post-pass: flip ~50% of each tack's red pixels to
    # white on a 1×1 checkerboard (R+W coral). Bbox-scoped per tack.
    pixels = pixel_access(image)
    for cx, cy in tack_centres:
        x0 = max(0, cx - tack_radius)
        y0 = max(0, cy - tack_radius)
        x1 = min(width - 1, cx + tack_radius)
        y1 = min(height - 1, cy + tack_radius)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if (x + y) & 1 == 0 and pixels[x, y] == accent_color:
                    pixels[x, y] = SPECTRA6["white"]

    # Header + footer dividers (see docstring): black rules plus a red
    # diamond the coral post-pass below weathers to match the tacks.
    ink = colors["text"]
    div_cx = width // 2
    head_y = inner_inset + 16
    foot_y = height - 1 - inner_inset - 16
    new_red_centres = []
    for dy in (head_y, foot_y):
        draw.line([(div_cx - 80, dy), (div_cx - 10, dy)], fill=ink, width=1)
        draw.line([(div_cx + 10, dy), (div_cx + 80, dy)], fill=ink, width=1)
        draw.polygon([(div_cx, dy - 4), (div_cx + 4, dy), (div_cx, dy + 4), (div_cx - 4, dy)], fill=accent_color)
        new_red_centres.append((div_cx, dy))

    # Coral post-pass on the new divider diamonds (R+W checkerboard, the
    # same weathered-coral recipe the corner tacks use).
    for cx, cy in new_red_centres:
        for y in range(cy - 5, cy + 6):
            for x in range(cx - 6, cx + 7):
                if 0 <= x < width and 0 <= y < height and (x + y) & 1 == 0 and pixels[x, y] == accent_color:
                    pixels[x, y] = SPECTRA6["white"]

    # Side-margin hanging price tags: a short black rule dropping to a
    # small coral diamond at each left/right mid-edge, carrying the
    # divider vocabulary into the side margins. At x≈inner_inset+10 /
    # width-inner_inset-10, clear of the body (dense layout starts x≥60).
    side_tag_centres = []
    cy_mid = height // 2
    for edge_x, _hdir in ((inner_inset + 10, 1), (width - 1 - inner_inset - 10, -1)):
        # Short vertical rule from above the diamond down to it.
        draw.line([(edge_x, cy_mid - 20), (edge_x, cy_mid - 5)], fill=ink, width=1)
        draw.polygon(
            [(edge_x, cy_mid - 5), (edge_x + 5, cy_mid), (edge_x, cy_mid + 5), (edge_x - 5, cy_mid)],
            fill=accent_color,
        )
        side_tag_centres.append((edge_x, cy_mid))
    # Coral post-pass on the side-tag diamonds (same R+W recipe).
    for cx, cy in side_tag_centres:
        for y in range(cy - 6, cy + 7):
            for x in range(cx - 7, cx + 8):
                if 0 <= x < width and 0 <= y < height and (x + y) & 1 == 0 and pixels[x, y] == accent_color:
                    pixels[x, y] = SPECTRA6["white"]


SPEC = BorderSpec(
    themes=("placard",),
    paint=draw_placard_border,
)
