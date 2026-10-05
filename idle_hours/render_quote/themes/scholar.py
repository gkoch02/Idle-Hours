"""The ``scholar`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .._paths import META_FONT_BOLD_CANDIDATES
from ..fonts import load_font
from ..text import draw_text


def draw_scholar_border(image: Image.Image, colors: dict) -> None:
    """Paint a restrained academic-journal margin treatment.

    Scholar gets subtle editorial structure rather than loud decoration,
    the vocabulary of a hand-set critical edition:

    * a **double blue frame** (outer + inner rule);
    * **printer's corner brackets** — short L-ticks tucked just inside
      the inner frame's four corners, the way a carefully composed page
      registers its type area;
    * a centred **asterism** (the three-dot ``⁂`` section break) at the
      head and a centred **folio ornament** (a short rule pierced by a
      small red lozenge) at the foot — the traditional academic dingbats;
    * thin **margin ruling lines** down both sides that turn the three
      footnote reference numbers from floating marks into proper hanging
      marginalia, each tagged with a small red tick.

    Everything stays blue + red so the page still reads as a curated
    journal offprint, not one attacked by graduate students.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    body = colors["text"]
    accent = colors["accent"]
    outer_inset = 18
    inner_inset = 26
    draw.rectangle(
        (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
        outline=body,
        width=1,
    )
    draw.rectangle(
        (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
        outline=body,
        width=1,
    )

    # Printer's corner brackets — short right-angle ticks set a few px
    # inside the inner frame at each corner. Reads as the registration
    # marks of a well-composed type area.
    bracket_inset = inner_inset + 6
    bracket_arm = 14
    left = bracket_inset
    right = width - 1 - bracket_inset
    top = bracket_inset
    bottom = height - 1 - bracket_inset
    for cx, cy, hx, vy in (
        (left, top, +1, +1),
        (right, top, -1, +1),
        (left, bottom, +1, -1),
        (right, bottom, -1, -1),
    ):
        draw.line([(cx, cy), (cx + hx * bracket_arm, cy)], fill=body, width=1)
        draw.line([(cx, cy), (cx, cy + vy * bracket_arm)], fill=body, width=1)

    # Side margin ruling lines — define the marginalia columns the
    # footnote numbers hang in. x=40 / width-40 stay clear of the widest
    # (dense, max_width=680 → text left edge 60) quote column.
    rule_x_left = 40
    rule_x_right = width - 1 - 40
    rule_top = inner_inset + 22
    rule_bottom = height - 1 - inner_inset - 22
    for rx in (rule_x_left, rule_x_right):
        draw.line([(rx, rule_top), (rx, rule_bottom)], fill=body, width=1)

    # Hanging footnote reference marks in the ruled margins, each with a
    # small red tick on the outer side so the number reads as an
    # editorial annotation rather than stray ink.
    marker_font = load_font(META_FONT_BOLD_CANDIDATES, size=14)
    for label, y in [("1", 104), ("2", height // 2 - 8), ("3", height - 118)]:
        bbox = draw.textbbox((0, 0), label, font=marker_font)
        xoff = (bbox[2] - bbox[0]) // 2
        draw_text(draw, (52 - xoff, y), label, font=marker_font, fill=accent)
        draw_text(draw, (width - 52 - xoff, y), label, font=marker_font, fill=accent)
        draw.line([(rule_x_left, y + 8), (rule_x_left + 5, y + 8)], fill=accent, width=1)
        draw.line([(rule_x_right - 5, y + 8), (rule_x_right, y + 8)], fill=accent, width=1)

    # Head asterism (⁂) — three small red lozenges in a triangle, the
    # classic typographic section break, centred above the type area.
    acx = width // 2
    acy = 42
    lz = 3  # lozenge half-size
    for px, py in ((acx, acy - 4), (acx - 7, acy + 5), (acx + 7, acy + 5)):
        draw.polygon(
            [(px, py - lz), (px + lz, py), (px, py + lz), (px - lz, py)],
            fill=accent,
        )

    # Foot folio ornament — a short centred blue rule pierced by a small
    # red lozenge, the page-foot dingbat of a printed offprint.
    fy = height - 40
    draw.line([(acx - 34, fy), (acx - 8, fy)], fill=body, width=1)
    draw.line([(acx + 8, fy), (acx + 34, fy)], fill=body, width=1)
    draw.polygon(
        [(acx, fy - 4), (acx + 4, fy), (acx, fy + 4), (acx - 4, fy)],
        fill=accent,
    )
