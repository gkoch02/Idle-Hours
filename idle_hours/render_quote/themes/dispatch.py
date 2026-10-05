"""The ``dispatch`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..fonts import load_font, theme_font_candidates
from ..palette import SPECTRA6, BAYER_4x4, pixel_access
from ..spec import BorderSpec


def draw_dispatch_border(image: Image.Image, colors: dict) -> None:
    """Paint a vintage-office dispatch border: cream-washed ground +
    thin frame + alternating black/sepia tractor-feed perforations +
    maroon rubber-stamp imprint.

    * **Layer 0: sparse cream ground wash.** A 4×4 Bayer dither turns
      ~12.5% of the white ``page_bg`` pixels yellow, which averages to aged
      manila paper. Every pixel stays a pure ink, so palette-snap is a
      no-op and glyph edges stay crisp.
    * **Outer thin black frame**, like a typed memo's letterhead rule.
    * **Tractor-feed perforations**: a column of small dots ~40 px apart
      in each side margin. Every other pair is sepia (red sentinel, half
      flipped to green on parity, R+G 1:1) instead of black, as carbon
      bleed.
    * **Maroon rubber stamp** in the upper right at y≈40–70 (below the
      debug-label band, clear of the opening quote mark and the text):
      two concentric ellipses and four hatch lines, no lettering. Red
      sentinel, half flipped to black on ``(x+y)&1`` (R+K 1:1 maroon).
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    ink = colors["text"]
    page_bg = colors.get("page_bg")
    cream_light = SPECTRA6["yellow"]
    sepia_light = SPECTRA6["green"]
    sentinel_red = SPECTRA6["red"]
    maroon_dark = SPECTRA6["black"]

    # Layer 0: sparse 1-in-8 yellow-on-white Bayer cream wash. Only exact
    # ``page_bg`` pixels are touched, in case a caller painted accents first.
    pixels = pixel_access(image)
    if page_bg is not None:
        for y in range(height):
            row = BAYER_4x4[y & 3]
            for x in range(width):
                if pixels[x, y] == page_bg and row[x & 3] < 2:
                    pixels[x, y] = cream_light

    # Outer thin frame.
    frame_inset = 14
    draw.rectangle(
        (frame_inset, frame_inset, width - 1 - frame_inset, height - 1 - frame_inset),
        outline=ink,
        width=1,
    )

    # Tractor-feed perforations on both side margins. Every other pair is
    # painted in a red sentinel that the post-pass below turns sepia.
    hole_radius = 2
    hole_spacing = 40
    hole_top = 22
    hole_bottom = height - 22
    left_x = 7
    right_x = width - 1 - 7
    sepia_centres: list[tuple[int, int]] = []
    y = hole_top
    pair_idx = 0
    while y <= hole_bottom:
        if pair_idx & 1:
            fill = sentinel_red
            sepia_centres.append((left_x, y))
            sepia_centres.append((right_x, y))
        else:
            fill = ink
        draw.ellipse(
            (left_x - hole_radius, y - hole_radius, left_x + hole_radius, y + hole_radius),
            fill=fill,
        )
        draw.ellipse(
            (right_x - hole_radius, y - hole_radius, right_x + hole_radius, y + hole_radius),
            fill=fill,
        )
        y += hole_spacing
        pair_idx += 1

    # Sepia post-pass on the alternating perforations only.
    for cx, cy in sepia_centres:
        x0 = max(0, cx - hole_radius)
        y0 = max(0, cy - hole_radius)
        x1 = min(width - 1, cx + hole_radius)
        y1 = min(height - 1, cy + hole_radius)
        for py in range(y0, y1 + 1):
            for px in range(x0, x1 + 1):
                if (px + py) & 1 == 0 and pixels[px, py] == sentinel_red:
                    pixels[px, py] = sepia_light

    # Maroon rubber-stamp imprint: two concentric ellipse outlines plus
    # short diagonal hatch lines, painted in red as a sentinel.
    stamp_cx = width - 55
    stamp_cy = 55
    outer_hw, outer_hh = 25, 15
    inner_hw, inner_hh = 19, 10
    draw.ellipse(
        (stamp_cx - outer_hw, stamp_cy - outer_hh, stamp_cx + outer_hw, stamp_cy + outer_hh),
        outline=sentinel_red,
        width=1,
    )
    draw.ellipse(
        (stamp_cx - inner_hw, stamp_cy - inner_hh, stamp_cx + inner_hw, stamp_cy + inner_hh),
        outline=sentinel_red,
        width=1,
    )
    for dx in (-9, -3, 3, 9):
        draw.line(
            (stamp_cx + dx - 3, stamp_cy + 3, stamp_cx + dx + 3, stamp_cy - 3),
            fill=sentinel_red,
            width=1,
        )

    # Maroon post-pass on the stamp's bbox only.
    stamp_x0 = max(0, stamp_cx - outer_hw - 1)
    stamp_y0 = max(0, stamp_cy - outer_hh - 1)
    stamp_x1 = min(width - 1, stamp_cx + outer_hw + 1)
    stamp_y1 = min(height - 1, stamp_cy + outer_hh + 1)
    for py in range(stamp_y0, stamp_y1 + 1):
        for px in range(stamp_x0, stamp_x1 + 1):
            if (px + py) & 1 == 0 and pixels[px, py] == sentinel_red:
                pixels[px, py] = maroon_dark

    # Two-hole filing punch centred in the top margin: two thin black
    # rings at y≈40, below the y=14-29 debug-banner band and above the text
    # (y≥72), clear of the side perforations and the stamp.
    punch_y = 40
    punch_r = 7
    punch_gap = 46
    cx0 = width // 2
    for hole_cx in (cx0 - punch_gap, cx0 + punch_gap):
        draw.ellipse(
            (hole_cx - punch_r, punch_y - punch_r, hole_cx + punch_r, punch_y + punch_r),
            outline=ink,
            width=1,
        )

    # Typed "— FILE COPY —" footer in the theme's typewriter face, centred
    # (clear of the bottom-left attribution) inside the frame below the
    # quote.
    footer_font = load_font(theme_font_candidates("dispatch", "quote_regular"), size=14)
    footer_text = "— FILE COPY —"
    fb = draw.textbbox((0, 0), footer_text, font=footer_font)
    fw = fb[2] - fb[0]
    footer_y = height - 1 - frame_inset - 18
    draw.text((cx0 - fw // 2 - fb[0], footer_y), footer_text, font=footer_font, fill=ink)

    # The accent slot is unused: the stamp and perforations use sentinels.
    accent = colors["accent"]
    del accent


SPEC = BorderSpec(
    themes=("dispatch",),
    paint=draw_dispatch_border,
)
