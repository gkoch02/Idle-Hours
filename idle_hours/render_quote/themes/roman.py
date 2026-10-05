"""The ``roman`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import random

from PIL import Image, ImageDraw

from ..fonts import load_font, theme_font_candidates
from ..palette import DEFAULT_HEIGHT, DEFAULT_WIDTH, SPECTRA6


# Deterministic stone-grain speckle layout for ``draw_roman_border``,
# computed once at module scope like ``_SALOON_FOXING`` (byte-identical
# renders). Sparser than saloon's foxing: limestone reads cleaner than pulp
# paper, and heavy stipple fights dense quotes. Only the outer ring is
# speckled; the central face stays clear.
def _build_roman_stone_grain(
    width: int, height: int, density: int, *, seed: int, exclude_inset: int
) -> list[tuple[int, int, int]]:
    """Scatter ``density`` stone-grain speckles in a ring round the canvas
    edge, leaving the central rectangle (``exclude_inset`` from each edge)
    clear.

    Each speckle is ``(x, y, radius)`` with radius 0 (single pixel) or 1
    (3×3), as in ``_build_saloon_foxing_points``.
    """
    rng = random.Random(seed)
    points: list[tuple[int, int, int]] = []
    attempts = 0
    while len(points) < density and attempts < density * 8:
        attempts += 1
        x = rng.randint(2, width - 3)
        y = rng.randint(2, height - 3)
        # Skip points inside the central face, where the quote sits.
        if exclude_inset <= x < width - exclude_inset and exclude_inset <= y < height - exclude_inset:
            continue
        radius = 1 if rng.random() < 0.18 else 0
        points.append((x, y, radius))
    return points


# ~140 speckles in the ring outside an inset-26 exclusion at 800×480: enough
# to read as limestone grain, and the exclusion keeps them off the text. At
# the top and bottom the ring reaches a little inside the tabula's outer
# rule (rect_inset_y=14), but stays outside the text area.
_ROMAN_STONE_GRAIN = _build_roman_stone_grain(
    DEFAULT_WIDTH, DEFAULT_HEIGHT, density=140, seed=0x5C1B, exclude_inset=26
)


def draw_roman_border(image: Image.Image, colors: dict) -> None:
    """Paint a Roman lapidary stone-tablet frame.

    Layers, bottom to top:

    1. **Stone-grain speckles** in the outer ring from
       ``_ROMAN_STONE_GRAIN`` (fixed seed); ~18% are 3×3 darker spots.
    2. **Tabula ansata outline**: a black rectangle with two trapezoidal
       dovetail handles (``ansae``) extending outward from the left and
       right mid-edges, the Roman votive-tablet shape.
    3. **Inner channel rule**: a hairline a few px inside the rectangle,
       the V-cut channel round the inscribed face.
    4. **SPQR cartouche** in red at top centre on the carved face, just
       below the channel rule and above the text (quote_top ≥ 72), with
       red interpunct dots (``·``) between the letters. Centred, so it
       misses the right-aligned ``DEBUG MODE`` banner.
    5. **Mid-edge interpunct dots** in red on the channel rule.
    6. **Laurel sprig** at bottom centre: two short black stems with three
       olive (Y+G 1:1) leaves each and a red berry at the join.
    7. **Carved corner stops**: small red triangles in each channel corner.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    ink = colors["text"]       # black
    accent = colors["accent"]  # red rubrum

    # ------------------------------------------------------------------
    # Layer 1: Stone-grain speckles in the outer ring. ``_ROMAN_STONE_GRAIN``
    # is computed for 800×480; rescale so other sizes (e.g. contact-sheet
    # tiles) keep the same density.
    sx = width / DEFAULT_WIDTH
    sy = height / DEFAULT_HEIGHT
    for px, py, radius in _ROMAN_STONE_GRAIN:
        x = int(px * sx)
        y = int(py * sy)
        if radius == 0:
            draw.point((x, y), fill=ink)
        else:
            draw.rectangle((x - 1, y - 1, x + 1, y + 1), fill=ink)

    # ------------------------------------------------------------------
    # Layer 2: Tabula ansata outline: the rectangle plus two trapezoidal
    # dovetail handles at the left and right mid-edges, narrow side
    # facing out (the Arch of Titus silhouette), about half the
    # rectangle's height so they read as ears, not pegs. Insets are
    # tight so the face has the most room for text; the ansae need the
    # side margin for ``handle_outer_offset``.
    rect_inset_x = 30
    rect_inset_y = 14
    rect_left = rect_inset_x
    rect_right = width - 1 - rect_inset_x
    rect_top = rect_inset_y
    rect_bot = height - 1 - rect_inset_y

    # ``ansa`` dimensions are fixed pixels, not a fraction of the
    # rectangle height: the ratio that reads as a Roman tablet is about
    # 70:40 (inner:outer), and scaling would give ~218 px handles at 800×480.
    handle_outer_offset = 22       # how far the ansa extends past the rectangle
    handle_inner_height = 90       # vertical span where the ansa meets the rectangle
    handle_outer_height = 56       # vertical span at the ansa's outer edge
    rect_mid = (rect_top + rect_bot) // 2

    rule_thick = 3

    # Outer silhouette as one closed polyline, clockwise from the top-left,
    # so the corners join cleanly with no inner cross-rule.
    tabula_outline = [
        # Top edge.
        (rect_left, rect_top),
        (rect_right, rect_top),
        # Right ansa: inner top → outer top → outer bottom → inner bottom.
        (rect_right, rect_mid - handle_inner_height // 2),
        (rect_right + handle_outer_offset, rect_mid - handle_outer_height // 2),
        (rect_right + handle_outer_offset, rect_mid + handle_outer_height // 2),
        (rect_right, rect_mid + handle_inner_height // 2),
        # Bottom edge.
        (rect_right, rect_bot),
        (rect_left, rect_bot),
        # Left ansa: inner bottom → outer bottom → outer top → inner top.
        (rect_left, rect_mid + handle_inner_height // 2),
        (rect_left - handle_outer_offset, rect_mid + handle_outer_height // 2),
        (rect_left - handle_outer_offset, rect_mid - handle_outer_height // 2),
        (rect_left, rect_mid - handle_inner_height // 2),
    ]
    # Close the polygon by repeating the first point.
    draw.line(tabula_outline + [tabula_outline[0]], fill=ink, width=rule_thick)

    # ------------------------------------------------------------------
    # Layer 3: Inner channel rule: a hairline rectangle inside the central
    # rectangle only (not the ansae), the V-cut groove round the
    # inscribed face.
    channel_inset = 8
    draw.rectangle(
        (
            rect_left + channel_inset,
            rect_top + channel_inset,
            rect_right - channel_inset,
            rect_bot - channel_inset,
        ),
        outline=ink,
        width=1,
    )

    # ------------------------------------------------------------------
    # Layer 4: SPQR cartouche at top centre, on the carved face below the
    # channel rule and above quote_top (≈y=72). The channel band is too
    # narrow for legible 18 pt Cinzel, and a real inscription carves SPQR
    # on the face anyway. The theme's ornament chain degrades to a heavy
    # serif if Cinzel is missing.
    cart_font = load_font(theme_font_candidates("roman", "ornament"), size=18)
    cart_letters = ("S", "P", "Q", "R")
    interpunct_r = 2
    letter_gap = 18  # gap between adjacent letter centres' interpunct slots
    # Measure the letters first so the cartouche can be centred.
    letter_widths = []
    letter_height = 0
    for ch in cart_letters:
        bbox = draw.textbbox((0, 0), ch, font=cart_font)
        letter_widths.append(bbox[2] - bbox[0])
        letter_height = max(letter_height, bbox[3] - bbox[1])
    cart_total_w = sum(letter_widths) + (len(cart_letters) - 1) * letter_gap
    cart_start_x = (width - cart_total_w) // 2
    # Letters are drawn from 8 px below the channel rule
    # (rect_top + channel_inset = 22), i.e. from y=30, above the body text.
    cart_band_top = rect_top + channel_inset + 8
    # Draw letters with red interpunct dots between each pair.
    cursor_x = cart_start_x
    for i, ch in enumerate(cart_letters):
        draw.text((cursor_x, cart_band_top), ch, font=cart_font, fill=accent)
        cursor_x += letter_widths[i]
        if i < len(cart_letters) - 1:
            dot_cx = cursor_x + letter_gap // 2
            dot_cy = cart_band_top + letter_height // 2
            draw.ellipse(
                (
                    dot_cx - interpunct_r,
                    dot_cy - interpunct_r,
                    dot_cx + interpunct_r,
                    dot_cy + interpunct_r,
                ),
                fill=accent,
            )
            cursor_x += letter_gap

    # ------------------------------------------------------------------
    # Layer 5: Mid-edge interpunct dots painted over the inner channel
    # rule, breaking its long runs.
    mid_dot_r = 4
    mid_points = (
        (width // 2, rect_top + channel_inset),                    # top
        (width // 2, rect_bot - channel_inset),                    # bottom
        (rect_left + channel_inset, (rect_top + rect_bot) // 2),   # left
        (rect_right - channel_inset, (rect_top + rect_bot) // 2),  # right
    )
    for cx, cy in mid_points:
        draw.ellipse(
            (cx - mid_dot_r, cy - mid_dot_r, cx + mid_dot_r, cy + mid_dot_r),
            fill=accent,
        )

    # ------------------------------------------------------------------
    # Layer 6: Laurel sprig at bottom centre on the face, mirroring the
    # SPQR band: two black stems with three leaves each, angled outward.
    #
    # Leaves are painted yellow and half flipped to green on (x+y)&1 per
    # leaf bbox (the Y+G 1:1 olive recipe, laurel's colour). Stems and the
    # red berry stay solid for contrast.
    laurel_band_y = rect_bot - channel_inset - 8
    laurel_cx = width // 2
    stem_len = 36
    leaf_count = 3
    leaf_a, leaf_b = 5, 2  # leaf ellipse semi-axes (long, short)
    leaf_centres: list[tuple[int, int]] = []
    for sign in (-1, 1):
        # Stem: a short rule slanting slightly up toward the centre, so the
        # two stems converge under the berry.
        stem_x0 = laurel_cx + sign * 6
        stem_y0 = laurel_band_y + 1
        stem_x1 = stem_x0 + sign * stem_len
        stem_y1 = laurel_band_y - 3
        draw.line((stem_x0, stem_y0, stem_x1, stem_y1), fill=ink, width=1)
        # Leaves: three small axis-aligned ellipses along the stem; at this
        # size an unrotated ellipse reads as a leaf.
        for j in range(1, leaf_count + 1):
            t = j / (leaf_count + 1)
            leaf_cx = int(stem_x0 + sign * stem_len * t)
            leaf_cy = int(stem_y0 + (stem_y1 - stem_y0) * t) - 3
            draw.ellipse(
                (leaf_cx - leaf_a, leaf_cy - leaf_b, leaf_cx + leaf_a, leaf_cy + leaf_b),
                fill=SPECTRA6["yellow"],
            )
            leaf_centres.append((leaf_cx, leaf_cy))
    # Olive post-pass on each leaf bbox; only yellow (leaf) pixels flip.
    pixels = image.load()
    olive_light = SPECTRA6["green"]
    sentinel_yellow = SPECTRA6["yellow"]
    for leaf_cx, leaf_cy in leaf_centres:
        x0 = max(0, leaf_cx - leaf_a)
        y0 = max(0, leaf_cy - leaf_b)
        x1 = min(width - 1, leaf_cx + leaf_a)
        y1 = min(height - 1, leaf_cy + leaf_b)
        for py in range(y0, y1 + 1):
            for px in range(x0, x1 + 1):
                if (px + py) & 1 == 0 and pixels[px, py] == sentinel_yellow:
                    pixels[px, py] = olive_light
    # Centre laurel "berry" — a small filled red dot at the join.
    draw.ellipse(
        (laurel_cx - 2, laurel_band_y - 4, laurel_cx + 2, laurel_band_y),
        fill=accent,
    )

    # ------------------------------------------------------------------
    # Layer 7: Carved corner stops: a small red right-triangle in each
    # inner-channel corner, the corner terminal masons cut where two
    # channel rules meet. 10 px legs at ≈(38,22)/(761,457), clear of the
    # text (≈x60-740, y72-410).
    chan_l = rect_left + channel_inset
    chan_r = rect_right - channel_inset
    chan_t = rect_top + channel_inset
    chan_b = rect_bot - channel_inset
    stop_leg = 10
    for corner_x, corner_y, hdir, vdir in (
        (chan_l, chan_t, 1, 1),    # TL
        (chan_r, chan_t, -1, 1),   # TR
        (chan_l, chan_b, 1, -1),   # BL
        (chan_r, chan_b, -1, -1),  # BR
    ):
        draw.polygon(
            [
                (corner_x, corner_y),
                (corner_x + hdir * stop_leg, corner_y),
                (corner_x, corner_y + vdir * stop_leg),
            ],
            fill=accent,
        )
