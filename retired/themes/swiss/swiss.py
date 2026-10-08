"""The ``swiss`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..layout import SIDE_MARGIN
from ..spec import BorderSpec


def draw_swiss_border(image: Image.Image, colors: dict) -> None:
    """Paint the Swiss International theme's deliberately minimal frame.

    The identity is what's missing: two marks near the top, the
    Müller-Brockmann / Vignelli grid.

    * A 1 px black hairline at ``y = 60``, dividing a small header zone
      from the body: the asymmetric-grid gesture of Swiss poster design.
    * A 6×6 px red square at ``(width - 40, 42)``, the only chromatic
      accent besides the matched phrase.

    No corners, no frame, no second rule, no Layer-0 wash. The rule uses
    ``colors["text"]`` and the square ``colors["accent"]``.
    """
    draw = ImageDraw.Draw(image)
    width, _ = image.size
    ink = colors["text"]
    accent = colors["accent"]
    rule_y = 60
    draw.line((SIDE_MARGIN, rule_y, width - SIDE_MARGIN, rule_y), fill=ink, width=1)
    # The red square sits between the y=14..29 debug-banner band and the
    # y=60 rule, just above the rule so it reads as a tag on it.
    square_x = width - 40
    square_y = 42
    square_size = 6
    draw.rectangle(
        (square_x, square_y, square_x + square_size, square_y + square_size),
        fill=accent,
    )


SPEC = BorderSpec(
    themes=("swiss",),
    paint=draw_swiss_border,
)
