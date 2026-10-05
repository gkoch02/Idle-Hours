"""The ``grimdark`` theme's border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from .._paths import BASE_DIR
from ..palette import SPECTRA6, _load_dithered_plate
from ._shared import _GUNMETAL_PALETTE


def _grimdark_cog(draw, cx: int, cy: int, radius: int, teeth_n: int, color, *,
                  tooth_len: int = 4, tooth_w: int = 3, hub: int | None = None,
                  hub_color=None) -> None:
    """Draw an Adeptus-Mechanicus-style toothed cog/gear centred on (cx, cy).

    A filled disc with ``teeth_n`` trapezoidal teeth radiating from the rim,
    plus an optional hollow hub. Pure ``ImageDraw`` (polygons + ellipses) so
    it clips silently at small preview sizes and stays on-palette. Used for
    the bottom cog-skull's gear ring and the bulkhead-seam machinery nodes.
    """
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)
    for i in range(teeth_n):
        a = 2 * math.pi * i / teeth_n
        ca, sa = math.cos(a), math.sin(a)
        nx, ny = -sa, ca  # unit perpendicular, for the tooth's width
        bx, by = cx + ca * (radius - 1), cy + sa * (radius - 1)
        tx, ty = cx + ca * (radius + tooth_len), cy + sa * (radius + tooth_len)
        draw.polygon(
            [
                (round(bx + nx * tooth_w), round(by + ny * tooth_w)),
                (round(bx - nx * tooth_w), round(by - ny * tooth_w)),
                (round(tx - nx * tooth_w), round(ty - ny * tooth_w)),
                (round(tx + nx * tooth_w), round(ty + ny * tooth_w)),
            ],
            fill=color,
        )
    if hub is not None and hub > 0:
        draw.ellipse(
            (cx - hub, cy - hub, cx + hub, cy + hub),
            fill=hub_color if hub_color is not None else SPECTRA6["black"],
        )


def _grimdark_skull(draw, cx: int, cy: int, s: int, bone, void) -> None:
    """Draw a memento-mori skull of half-height ``s`` centred on (cx, cy).

    Parametrised off the s=12 reference design so the same primitive serves
    the big bottom cog-skull and the smaller flanking skulls. Cranium + jaw
    in ``bone``; eye sockets, nasal cavity and (at larger sizes) tooth gaps
    carved back to ``void``. ImageDraw-only, clip-safe, on-palette.
    """
    k = s / 12.0

    def r(v: float) -> int:
        return round(v * k)

    # Cranium + jaw.
    draw.ellipse((cx - r(12), cy - r(14), cx + r(12), cy + r(6)), fill=bone)
    draw.polygon(
        [(cx - r(8), cy + r(3)), (cx + r(8), cy + r(3)), (cx + r(5), cy + r(14)), (cx - r(5), cy + r(14))],
        fill=bone,
    )
    # Eye sockets + nasal cavity carved to the void.
    draw.ellipse((cx - r(9), cy - r(7), cx - r(2), cy + r(1)), fill=void)
    draw.ellipse((cx + r(2), cy - r(7), cx + r(9), cy + r(1)), fill=void)
    draw.polygon([(cx, cy - r(2)), (cx + r(2), cy + r(4)), (cx - r(2), cy + r(4))], fill=void)
    # Tooth gaps only at larger sizes — at small s they muddy into the jaw.
    if s >= 11:
        for tx in (cx - r(4), cx, cx + r(4)):
            draw.line((tx, cy + r(5), tx, cy + r(13)), fill=void, width=1)


# Deterministic seed for grimdark's industrial gunmetal mottle so re-renders
# of a given time stay byte-identical.
_GRIMDARK_MOTTLE_SEED = 0x40_0B


def _grimdark_paint_mottle(image: Image.Image, width: int, height: int) -> None:
    """Layer-0 dark-grey industrial mottle over the black void ground.

    Spectra 6 has no grey, so gunmetal is synthesised by stippling sparse
    white into the black ``page_bg`` (the K+W recipe, ~5-25% white reads as
    charcoal). A faint base gives a uniform tone; seeded blotches then lighten
    (scuffs) or darken (grime) local patches. This is the fallback when the
    gunmetal plate is missing. Only void pixels are flipped and every write is
    bounds-clipped, so it is safe at thumbnail preview sizes.
    """
    pixels = image.load()
    void = SPECTRA6["black"]
    grey_ink = SPECTRA6["white"]

    # Faint base: a ~4.5% hash-scatter of white (film grain; an ordered
    # Bayer grid would read as a dot screen). A different hash constant from
    # the blotches below keeps the two decorrelated.
    base_thresh = round(0.045 * 65535)
    for y in range(height):
        for x in range(width):
            if pixels[x, y] != void:
                continue
            hb = ((x * 374761393) ^ (y * 668265263) ^ ((x + y) * 1274126177)) & 0xFFFF
            if hb < base_thresh:
                pixels[x, y] = grey_ink

    # Weathering blotches: soft discs whose extra density falls from a random
    # peak to nothing at the rim; ~1/3 erode the base back to void (grime),
    # the rest add white (scuffs). An integer hash supplies the scatter.
    rng = random.Random(_GRIMDARK_MOTTLE_SEED)
    blotches = max(6, (width * height) // 9000)
    for _ in range(blotches):
        bx = rng.randint(0, width - 1)
        by = rng.randint(0, height - 1)
        br = rng.randint(18, 58)
        peak = rng.uniform(0.10, 0.24)
        darken = rng.random() < 0.34
        x0 = max(0, bx - br)
        x1 = min(width - 1, bx + br)
        y0 = max(0, by - br)
        y1 = min(height - 1, by + br)
        br2 = br * br
        for y in range(y0, y1 + 1):
            dy = y - by
            for x in range(x0, x1 + 1):
                dx = x - bx
                d2 = dx * dx + dy * dy
                if d2 > br2:
                    continue
                dens = peak * (1.0 - (d2 ** 0.5) / br)
                h = ((x * 2654435761) ^ (y * 40503) ^ ((x * y) & 0xFFFF)) & 0xFFFF
                if h / 65535.0 >= dens:
                    continue
                if darken:
                    if pixels[x, y] == grey_ink:
                        pixels[x, y] = void
                elif pixels[x, y] == void:
                    pixels[x, y] = grey_ink


def draw_grimdark_border(image: Image.Image, colors: dict) -> None:
    """Paint the Imperial Gothic frame: gold + blood doubled trim, an Aquila,
    a Mechanicus cog-skull, riveted bulkhead seams, and corner machinery.

    Every element is solid Spectra-6 ink (gold = yellow, blood = red, bone =
    white, void = black) laid with ``ImageDraw`` primitives, so it stays
    on-palette and clips silently at ``/api/preview`` thumbnail sizes
    (``TestPreviewSizeRendering``). The forge-amber matched-phrase glow is
    painted separately in ``_draw_text_body``.

    Composition:

    * **Layer-0 gunmetal plate** — ``grimdark_gunmetal.png`` dithered to
      white+black at render time, falling back to ``_grimdark_paint_mottle``
      when the asset is missing.
    * **Doubled trim** — thick gold outer rule, thin blood-red inner rule.
    * **Imperial Aquila** — the double-headed eagle, centred in the top
      margin, which keeps it clear of the right-aligned ``DEBUG MODE`` banner
      (so no ``_DEBUG_LABEL_RIGHT_INSET`` entry is needed).
    * **Mechanicus cog-skull** — a bone skull inside a gold toothed cog,
      flanked by two smaller skulls, centred in the bottom margin clear of
      the attribution.
    * **Riveted bulkhead seams** — gold rivets down each side rail with two
      cog nodes per side.
    * **Corner rivets** — gold discs with a blood centre at the inner corners.
    * **Mid-edge studs** — blood diamonds on the gold side rules.
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    gold = SPECTRA6["yellow"]   # imperial gilt trim / Aquila
    blood = SPECTRA6["red"]     # inner rule / rivet cores / studs
    bone = SPECTRA6["white"]    # skull
    void = SPECTRA6["black"]    # ground / skull recesses

    # --- Layer 0: gunmetal plate dithered to white+black, or the synthesised
    # stipple when the asset is unavailable (stripped install).
    plate = _load_dithered_plate(GRIMDARK_PLATE, width, height, palette=_GUNMETAL_PALETTE)
    if plate is not None:
        image.paste(plate, (0, 0))
    else:
        _grimdark_paint_mottle(image, width, height)

    # --- Doubled imperial trim. ImageDraw rectangles clip, but an inverted
    # bbox (inset >= half-dimension) raises, so guard at tiny preview sizes.
    outer_inset = 12
    inner_inset = 19
    if width > 2 * outer_inset and height > 2 * outer_inset:
        draw.rectangle(
            (outer_inset, outer_inset, width - 1 - outer_inset, height - 1 - outer_inset),
            outline=gold,
            width=3,
        )
    if width > 2 * inner_inset and height > 2 * inner_inset:
        draw.rectangle(
            (inner_inset, inner_inset, width - 1 - inner_inset, height - 1 - inner_inset),
            outline=blood,
            width=1,
        )

    cx = width // 2

    # --- Imperial Aquila in the top margin (centred on (cx, ay)). Only paint
    # when the full wingspan fits inside the inner trim — at thumbnail widths
    # there isn't room, and a clipped half-eagle reads as noise.
    ay = 40
    half_span = 40
    if cx - half_span > inner_inset and ay + 18 < height:
        # Torso — a vertical gold diamond.
        draw.polygon(
            [(cx, ay - 14), (cx + 7, ay), (cx, ay + 16), (cx - 7, ay)],
            fill=gold,
        )
        # Twin heads angled outward, each with a downward-hooked beak.
        for sign in (-1, 1):
            hx = cx + sign * 8
            hy = ay - 13
            draw.ellipse((hx - 4, hy - 5, hx + 4, hy + 3), fill=gold)
            draw.polygon(
                [(hx + sign * 4, hy - 1), (hx + sign * 12, hy + 1), (hx + sign * 4, hy + 4)],
                fill=gold,
            )
        # Swept wings: the underside steps back toward the torso in three
        # downward feather points, reading as a heraldic pinion rather than
        # a smooth bat membrane.
        for sign in (-1, 1):
            wing = [
                (cx + sign * 5, ay - 9),            # inner shoulder
                (cx + sign * half_span, ay - 13),   # raised outer tip
                (cx + sign * (half_span - 5), ay + 1),
                (cx + sign * 31, ay - 2),           # notch
                (cx + sign * 27, ay + 9),           # primary feather (down)
                (cx + sign * 21, ay - 1),           # notch
                (cx + sign * 16, ay + 9),           # secondary feather (down)
                (cx + sign * 11, ay + 0),           # notch
                (cx + sign * 7, ay + 6),            # inner covert
            ]
            draw.polygon(wing, fill=gold)

    # --- Mechanicus cog-skull in the bottom margin (centred on (cx, sy)):
    # a gold toothed gear ring with a bone skull set inside it, plus two
    # smaller flanking skulls reading as an ossuary shelf.
    sy = height - 36
    if sy - 24 > inner_inset and cx - 24 > inner_inset:
        # Gear ring behind the skull — the Adeptus Mechanicus cog. Drawn first
        # so the skull paints on top, leaving the toothed rim showing around it.
        _grimdark_cog(draw, cx, sy, 21, 12, gold, tooth_len=4, tooth_w=3)
        draw.ellipse((cx - 16, sy - 16, cx + 16, sy + 16), fill=void)  # hollow the hub
        # Flanking ossuary skulls — small, just inside the side machinery.
        flank = 66
        if cx - flank - 8 > inner_inset:
            for fx in (cx - flank, cx + flank):
                _grimdark_skull(draw, fx, sy + 2, 8, bone, void)
        # Central skull set into the cog.
        _grimdark_skull(draw, cx, sy, 12, bone, void)

    # --- Riveted bulkhead seams down each side rail (x ~ 25, well clear of
    # the quote column): gold rivets plus two cog nodes per side.
    rail_x_left = inner_inset + 6
    rail_x_right = width - 1 - inner_inset - 6
    if rail_x_left + 10 < rail_x_right and height > 160:
        cog_ys = (round(height * 0.30), round(height * 0.70))
        for rail_x in (rail_x_left, rail_x_right):
            for ry in range(inner_inset + 30, height - inner_inset - 24, 40):
                draw.ellipse((rail_x - 3, ry - 3, rail_x + 3, ry + 3), fill=gold)
                draw.ellipse((rail_x - 1, ry - 1, rail_x + 1, ry + 1), fill=void)
            for cy_node in cog_ys:
                _grimdark_cog(draw, rail_x, cy_node, 8, 8, gold, tooth_len=3, tooth_w=2, hub=3, hub_color=void)

    # --- Corner rivets — gold hex-bolt discs with a blood centre, tucked
    # just inside the blood inner rule.
    rivet_r = 4
    rivet_inset = inner_inset + 7
    for rx, ry in (
        (rivet_inset, rivet_inset),
        (width - 1 - rivet_inset, rivet_inset),
        (rivet_inset, height - 1 - rivet_inset),
        (width - 1 - rivet_inset, height - 1 - rivet_inset),
    ):
        if rivet_r <= rx < width - rivet_r and rivet_r <= ry < height - rivet_r:
            draw.ellipse((rx - rivet_r, ry - rivet_r, rx + rivet_r, ry + rivet_r), fill=gold)
            draw.ellipse((rx - 1, ry - 1, rx + 1, ry + 1), fill=blood)

    # --- Mid-edge studs — small blood diamonds riveted onto the gold side
    # rules at the vertical midpoint.
    my = height // 2
    if my - 5 > outer_inset and my + 5 < height - outer_inset:
        for mx in (outer_inset, width - 1 - outer_inset):
            draw.polygon(
                [(mx, my - 5), (mx + 4, my), (mx, my + 5), (mx - 4, my)],
                fill=blood,
            )

# Grimdark's gunmetal plate is greyscale, so it dithers to white+black only,
# keeping chroma out of the void.
GRIMDARK_PLATE = BASE_DIR / "assets" / "grimdark_gunmetal.png"
