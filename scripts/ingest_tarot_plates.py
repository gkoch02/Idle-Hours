#!/usr/bin/env python3
"""Turn a folder of Tarot de Marseille card scans into the tarot theme's
emblem sprite sheet.

A Marseille card is FLAT COLOUR woodcut -- heavy black line over solid
red/yellow/blue/green -- so it carries no continuous tone and the render-time
dithering path (``dither_image_to_palette``) is the wrong tool: there is
nothing for an error diffusion to preserve. What it wants is an ink
SEPARATION, which is also sharper at this size.

Separation order is load-bearing. The red flat on a Dodal card is about as
dark as the line ink (measured on the fixture: red ~(176,52,40), ink
~(28,24,20)), so a luminance threshold alone fuses them into one black
mass. Classify by SATURATION and HUE first, darkness only as the
tie-breaker:

    saturated + red hue      -> red
    unsaturated + dark       -> black          (the line work)
    saturated + other hue    -> white in 3-ink mode, own ink in 5-ink
    everything else          -> white          (the paper)

Resize happens BEFORE classification, never after: downsampling an
already-separated image blends inks and lands off-palette.

Usage:
    python3 ingest_tarot_plates.py --input scans/ --output plates.png
    python3 ingest_tarot_plates.py --input scans/ --inks 5 --contact contact.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageFilter

TILE_W, TILE_H = 220, 290          # the theme's illustration panel
COLS, ROWS = 3, 4                  # sprite sheet layout, hours 1..12

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)
YELLOW = (255, 255, 0)
BLUE = (0, 0, 255)
GREEN = (0, 255, 0)


def _saturation(r: int, g: int, b: int) -> float:
    mx = max(r, g, b)
    return 0.0 if mx == 0 else (mx - min(r, g, b)) / mx


def _hue_bucket(r: int, g: int, b: int) -> str:
    """Coarse hue name. Deliberately coarse -- a woodcut has four flats,
    not a spectrum, and a fine hue model just makes noise pixels dance."""
    if r >= g and r >= b:
        return "yellow" if g > b and g > r * 0.62 else "red"
    if g >= r and g >= b:
        return "green"
    return "blue"


def card_bbox(img: Image.Image, *, margin_tol: int = 150) -> tuple[int, int, int, int]:
    """Locate the card within the scan sheet by its printed frame.

    A scan is not registered to the pixel -- the fixture jitters margins by
    10-40 px and rotates by up to ~1 degree, and real scans are worse. The
    printed border is the darkest thing near the sheet edge, so the bbox of
    'dark enough' pixels finds the card without needing deskew: the crop
    insets are generous enough to absorb a degree of rotation.
    """
    g = img.convert("L")
    mask = g.point(lambda v: 255 if v < margin_tol else 0)
    box = mask.getbbox()
    return box or (0, 0, img.width, img.height)


def illustration_rect(box, top_frac: float, bottom_frac: float, side_frac: float):
    """Drop the head band (Roman numeral), the foot band (French title),
    and the printed frame down both sides.

    The theme paints its OWN Roman hour at the head and the matched phrase
    as the card name at the foot, so a scan that keeps its printed numeral
    and title puts two numerals on the card and a title that contradicts
    the quote. The side inset matters for the same reason the bands do:
    ``card_bbox`` locks onto the printed border, so without it every tile
    carries two black rules the theme's own keyline then duplicates.
    """
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    return (x0 + int(w * side_frac), y0 + int(h * top_frac),
            x1 - int(w * side_frac), y1 - int(h * bottom_frac))


def separate(img: Image.Image, *, inks: int, sat_min: float, ink_max: int,
             edge_max: int, red_light_max: int) -> tuple[Image.Image, dict]:
    """Classify every pixel to one ink. Returns (image, histogram)."""
    out = Image.new("RGB", img.size)
    src, dst = img.load(), out.load()
    hist: dict = {}
    for y in range(img.height):
        for x in range(img.width):
            r, g, b = src[x, y]
            lum = (r * 299 + g * 587 + b * 114) // 1000
            sat = _saturation(r, g, b)
            if lum <= ink_max:
                # Tier 1 -- unconditionally ink. Set BELOW the darkest
                # flat on the card, because a single cut above it turns
                # every blue robe solid black: a scan's lighting falloff
                # drags the darkest flat down toward the line work (the
                # fixture's blue measures 81 flat, but under the vignette
                # it reaches the 70s), so the two bands overlap and no
                # single luminance can split them.
                ink = BLACK
            elif sat >= sat_min:
                # Tier 2 -- saturated, so it is a colour field, however
                # dark the scanner rendered it.
                hue = _hue_bucket(r, g, b)
                if hue == "red" and lum <= red_light_max:
                    ink = RED
                elif inks == 5:
                    ink = {"yellow": YELLOW, "blue": BLUE, "green": GREEN}.get(hue, WHITE)
                else:
                    # Blue or green in 3-ink mode. White, not black --
                    # black turns every colour field into a solid blob
                    # and buries the line work that is the point of a
                    # woodcut.
                    ink = WHITE
            elif lum <= edge_max:
                # Tier 3 -- unsaturated and mid-dark: the antialiased
                # skirt of a contour. Gating this on saturation is what
                # keeps it from eating the flats.
                ink = BLACK
            else:
                ink = WHITE
            dst[x, y] = ink
            hist[ink] = hist.get(ink, 0) + 1
    return out, hist


def trim_to_content(img: Image.Image, *, sat_min: float, edge_max: int,
                    pad_frac: float = 0.03) -> Image.Image:
    """Crop away the illustration's own paper margin.

    Without this the figure is fitted against the scan's whitespace rather
    than against itself, and a card whose woodcut sits in a generous margin
    renders small in the middle of the panel while its neighbour fills it --
    the set reads as inconsistently scaled even though every tile is the
    same size. Content is "dark or saturated", the same two tests the
    separation uses, so trim and separation agree on what counts as ink.
    """
    px = img.load()
    mask = Image.new("L", img.size, 0)
    mp = mask.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b = px[x, y]
            lum = (r * 299 + g * 587 + b * 114) // 1000
            if lum <= edge_max or _saturation(r, g, b) >= sat_min:
                mp[x, y] = 255
    box = mask.getbbox()
    if not box:
        return img
    px_pad = int(min(img.width, img.height) * pad_frac)
    x0, y0, x1, y1 = box
    return img.crop((max(0, x0 - px_pad), max(0, y0 - px_pad),
                     min(img.width, x1 + px_pad), min(img.height, y1 + px_pad)))


def fit_tile(img: Image.Image) -> Image.Image:
    """Letterbox into the panel tile, preserving aspect. Resize happens on
    the CONTINUOUS image, before separation, so this is called first."""
    scale = min(TILE_W / img.width, TILE_H / img.height)
    w, h = max(1, round(img.width * scale)), max(1, round(img.height * scale))
    tile = Image.new("RGB", (TILE_W, TILE_H), (255, 255, 255))
    tile.paste(img.resize((w, h), Image.LANCZOS), ((TILE_W - w) // 2, (TILE_H - h) // 2))
    return tile


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", type=Path, required=True,
                   help="directory of trump_01..trump_12 scans (jpg/png)")
    p.add_argument("--output", type=Path, default=Path("tarot_plates.png"))
    p.add_argument("--contact", type=Path, default=None,
                   help="also write a contact sheet for eyeballing all 12 crops")
    p.add_argument("--inks", type=int, choices=(3, 5), default=3,
                   help="3 = theme's white/black/red; 5 adds yellow/blue/green")
    p.add_argument("--top", type=float, default=0.14,
                   help="fraction of card height to drop for the numeral band")
    p.add_argument("--bottom", type=float, default=0.14,
                   help="fraction to drop for the title band")
    p.add_argument("--side", type=float, default=0.07,
                   help="fraction of card width to drop for the printed frame")
    p.add_argument("--no-trim", action="store_true",
                   help="skip trimming the illustration's own paper margin")
    p.add_argument("--no-despeckle", action="store_true",
                   help="skip the 3x3 median pass applied before separation")
    p.add_argument("--sat-min", type=float, default=0.34)
    p.add_argument("--ink-max", type=int, default=48,
                   help="at or below this luminance a pixel is ink regardless of "
                        "hue; must sit BELOW the darkest flat on the card")
    p.add_argument("--edge-max", type=int, default=132,
                   help="unsaturated pixels at or below this are contour skirt")
    p.add_argument("--red-light-max", type=int, default=190)
    a = p.parse_args(argv)

    sheet = Image.new("RGB", (COLS * TILE_W, ROWS * TILE_H), (255, 255, 255))
    contact = Image.new("RGB", (COLS * TILE_W, ROWS * TILE_H), (255, 255, 255)) if a.contact else None
    missing = []
    for hour in range(1, 13):
        hits = [q for ext in ("jpg", "jpeg", "png")
                for q in a.input.glob(f"*{hour:02d}.{ext}")]
        if not hits:
            missing.append(hour)
            continue
        raw = Image.open(hits[0]).convert("RGB")
        rect = illustration_rect(card_bbox(raw), a.top, a.bottom, a.side)
        crop = raw.crop(rect)
        if not a.no_despeckle:
            # Before the resize, not after: sensor grain and JPEG ringing
            # want removing while they are still single pixels.
            crop = crop.filter(ImageFilter.MedianFilter(3))
        if not a.no_trim:
            crop = trim_to_content(crop, sat_min=a.sat_min, edge_max=a.edge_max)
        tile = fit_tile(crop)
        if contact is not None:
            contact.paste(tile, ((hour - 1) % COLS * TILE_W, (hour - 1) // COLS * TILE_H))
        flat, hist = separate(tile, inks=a.inks, sat_min=a.sat_min,
                              ink_max=a.ink_max, edge_max=a.edge_max,
                              red_light_max=a.red_light_max)
        total = TILE_W * TILE_H
        parts = " ".join(f"{n}={hist.get(c,0)/total:5.1%}" for n, c in
                         (("K", BLACK), ("R", RED), ("W", WHITE)))
        print(f"  hour {hour:>2}  {hits[0].name:<16} crop={rect}  {parts}")
        sheet.paste(flat, ((hour - 1) % COLS * TILE_W, (hour - 1) // COLS * TILE_H))

    if missing:
        print(f"missing scans for hours: {missing}", file=sys.stderr)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(a.output)
    print(f"wrote {a.output} ({COLS * TILE_W}x{ROWS * TILE_H}, {a.inks}-ink)")
    if contact is not None:
        contact.save(a.contact)
        print(f"wrote {a.contact} (pre-separation crops, for eyeballing)")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
