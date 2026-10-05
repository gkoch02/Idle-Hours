"""The ``anna_atkins`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from .._paths import BASE_DIR, DANCINGSCRIPT_VARIABLE, ORNAMENT_FONT_CANDIDATES, PINYONSCRIPT_REGULAR
from ..fonts import load_font
from ..palette import SPECTRA6, BAYER_4x4, _load_dithered_plate
from ..spec import BorderSpec


def _anna_atkins_fern(draw: ImageDraw.ImageDraw, x0: float, y0: float, length: float,
                      angle: float, scale: float, curl: float, ink) -> None:
    """A single white fern frond: a curving rachis with paired pinnate
    leaflets tapering to the tip, as 1 px line art over the plate."""
    pts = []
    x, y, a = x0, y0, angle
    n = max(4, int(length))
    for i in range(n):
        a += curl
        x += math.cos(a)
        y += math.sin(a)
        pts.append((x, y))
    for i in range(1, len(pts)):
        draw.line((pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1]), fill=ink, width=1)
    # Pinnate leaflets along the rachis.
    for i in range(2, len(pts) - 1, 3):
        px, py = pts[i]
        t = i / len(pts)
        span = max(3.0, (1 - t) * 14.0 * scale)
        # local tangent → perpendicular leaflet direction
        tx, ty = pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]
        plen = math.hypot(tx, ty) or 1.0
        nx, ny = -ty / plen, tx / plen
        lean = 0.5  # leaflets sweep toward the tip
        dx, dy = tx / plen, ty / plen
        for side in (-1, 1):
            ex = px + (nx * side + dx * lean) * span
            ey = py + (ny * side + dy * lean) * span
            draw.line((px, py, ex, ey), fill=ink, width=1)
    # A tiny terminal flourish.
    tipx, tipy = pts[-1]
    draw.ellipse((tipx - 1, tipy - 1, tipx + 1, tipy + 1), fill=ink)


def _anna_atkins_ferns(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    """White fern sprigs in the corner margins, clear of the quote. Fixed
    positions so both border-painter passes render identically."""
    ink = SPECTRA6["white"]
    # (x0, y0, length, angle, scale, curl) — anchored in the margins.
    sprigs = [
        (40, 150, 80, -1.35, 0.9, 0.03),     # left edge, reaching up
        (44, 330, 70, -1.7, 0.8, -0.025),    # lower-left
        (width - 44, 360, 78, -1.45, 0.9, -0.03),  # lower-right
        (width - 60, 150, 64, -1.9, 0.75, 0.03),   # upper-right
    ]
    for x0, y0, length, angle, scale, curl in sprigs:
        _anna_atkins_fern(draw, x0, y0, length, angle, scale, curl, ink)


def _anna_atkins_handwrite(image: Image.Image, text: str, cx: int, cy: int,
                           font, angle: float) -> None:
    """Stamp a slightly rotated white handwritten label.

    The rotated mask is pasted as solid white where it is opaque — a binary
    stamp, so antialiased edges can't leave a blue halo after palette snap."""
    tmp = Image.new("L", (1, 1), 0)
    bbox = ImageDraw.Draw(tmp).textbbox((0, 0), text, font=font)
    tw, th = max(1, bbox[2] - bbox[0]), max(1, bbox[3] - bbox[1])
    pad = 6
    mask = Image.new("L", (tw + 2 * pad, th + 2 * pad), 0)
    ImageDraw.Draw(mask).text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=255)
    if angle:
        mask = mask.rotate(angle, expand=True, resample=Image.BICUBIC)
    mw, mh = mask.size
    px0, py0 = cx - mw // 2, cy - mh // 2
    base = image.load()
    mpx = mask.load()
    white = SPECTRA6["white"]
    for my in range(mh):
        ay = py0 + my
        if ay < 0 or ay >= image.height:
            continue
        for mx in range(mw):
            ax = px0 + mx
            if 0 <= ax < image.width and mpx[mx, my] >= 128:
                base[ax, ay] = white


def _anna_atkins_labels(image: Image.Image, draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    """Handwritten white Latin species labels in copperplate, in the
    margins beside the specimens."""
    font = load_font([PINYONSCRIPT_REGULAR, DANCINGSCRIPT_VARIABLE, *ORNAMENT_FONT_CANDIDATES], size=26)
    # (text, cx, cy, angle) — kept in the corners, clear of the centred panel.
    labels = [
        ("Cystoseira fibrosa", 96, 408, 4),
        ("Ptilota plumosa", width - 96, 96, -5),
        ("Dictyota dichotoma", width - 104, 432, 3),
    ]
    for text, cx, cy, angle in labels:
        _anna_atkins_handwrite(image, text, cx, cy, font, angle)


def draw_anna_atkins_border(image: Image.Image, colors: dict) -> None:
    """Anna Atkins 1843 botanical cyanotype plate (see the THEMES entry).

    Layers, deepest → shallowest:

    * **Layer 0 — dithered cyanotype photogram.** The committed plate
      (``assets/anna_atkins_cyanotype.png``) Floyd–Steinberg-dithered to the
      inks via ``dither_image_to_palette``: deep blues break into a
      blue/black stipple, specimen edges into a blue+white haze. If the asset
      is missing, the flat blue ground is deepened with a blue→black Bayer
      stipple instead.
    * **White fern sprigs** in the corner margins.
    * **Handwritten Latin labels** (Pinyon Script), rotated and stamped
      binary.
    * **Thin white plate rule** at inset 12.

    There is deliberately no body-text knockout: the quote sits directly on
    the photogram, and ``_draw_text_body`` stamps a per-glyph black halo
    under the text for legibility over bright fronds.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    page_bg = colors.get("page_bg")
    pixels = image.load()
    WHITE = SPECTRA6["white"]
    BLACK = SPECTRA6["black"]

    # Layer 0 — dithered photogram (or Prussian-deepened flat ground fallback).
    plate = _load_dithered_plate(ANNA_ATKINS_PLATE, width, height, palette=_CYANOTYPE_PALETTE)
    if plate is not None:
        image.paste(plate, (0, 0))
    elif page_bg is not None:
        for y in range(height):
            row = BAYER_4x4[y & 3]
            for x in range(width):
                if pixels[x, y] == page_bg and row[x & 3] < 6:
                    pixels[x, y] = BLACK

    _anna_atkins_ferns(draw, width, height)
    _anna_atkins_labels(image, draw, width, height)

    draw.rectangle((12, 12, width - 13, height - 13), outline=WHITE, width=1)


# ---------------------------------------------------------------------------
# Theme plates: committed continuous-tone PNGs, dithered down to the inks at
# render time through ``palette.dither_image_to_palette`` for photographic
# tonal fidelity. Any theme can drop a plate into ``assets/`` and route it
# through there.
ANNA_ATKINS_PLATE = BASE_DIR / "assets" / "anna_atkins_cyanotype.png"
# The cyanotype dithers against only white, black and blue: error diffusion
# over all six inks scatters stray red/green specks into the deep blues. A
# strict subset of SPECTRA6, so the final ``snap_image_to_palette`` is a no-op.
_CYANOTYPE_PALETTE = [SPECTRA6["white"], SPECTRA6["black"], SPECTRA6["blue"]]


SPEC = BorderSpec(
    themes=("anna_atkins",),
    paint=draw_anna_atkins_border,
    # No clear_rect_pad, deliberately: the white / sky-blue text is drawn
    # straight onto the cyanotype plate with a subtle per-glyph black halo
    # (see ``_draw_text_body``) instead of a knockout panel, so the whole
    # photogram stays visible behind the quote.
)
