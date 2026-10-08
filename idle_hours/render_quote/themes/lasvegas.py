"""The ``lasvegas`` theme: the dead Las Vegas of *Blade Runner 2049*, with K's LAPD archive pane.

Design notes: docs/themes.md § lasvegas
"""

from __future__ import annotations

import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .._paths import BARLOWCOND_MEDIUM, BARLOWCOND_SEMIBOLD, META_FONT_CANDIDATES, SHARETECHMONO_REGULAR
from ..fonts import load_font
from ..furniture import _clock_hour12, _paint_placed, _place_quote, _row_digest, fallback_title
from ..palette import _PANEL_INKS, SPECTRA6, SPECTRA6_PALETTE, _dither_calibrated, snap_image_to_palette
from ..primitives import _catmull_rom, _lerp_stops, _smooth_noise, _soft_ellipse_mask
from ..spec import FrameSpec
from ..text import draw_tracked, fit_text_to_width

_LASVEGAS_SEED = 0x32303439        # "2049"
_LASVEGAS_INKS = ("red", "yellow", "black", "white")
_LASVEGAS_PANE = (24, 34, 432, 418)
_LASVEGAS_HEADER_H = 24
_LASVEGAS_QUOTE_RECT = (46, 80, 410, 290)
_LASVEGAS_BYLINE_Y = 304
_LASVEGAS_DNA_RECT = (46, 334, 410, 364)
_LASVEGAS_CELL_BAND = (46, 378, 410, 400)
_LASVEGAS_CELL_GAP = 3
_LASVEGAS_HORIZON = 428
_LASVEGAS_SUN = (706, 116, 22)       # centre x, centre y, radius
_LASVEGAS_K_FOOT = (498, 462)       # K's feet: centre x, ground y
_LASVEGAS_HIVES = (448, 432, 476, 462)
_LASVEGAS_SCAN_RECT = (440, 404, 538, 472)
_LASVEGAS_SCENE: dict = {}


def _lasvegas_mix(r: float = 0.0, y: float = 0.0, k: float = 0.0, w: float = 0.0) -> tuple[int, int, int]:
    """A blend of the measured inks: what the dither will make of a field
    of this colour, as the eye averages it on the panel."""
    total = r + y + k + w
    return tuple(round((r * _PANEL_INKS["red"][c] + y * _PANEL_INKS["yellow"][c] + k * _PANEL_INKS["black"][c]
                        + w * _PANEL_INKS["white"][c]) / total) for c in range(3))  # type: ignore[return-value]


# The haze from the top of the frame to the ground. Darker overhead, palest
# at the horizon, where the dust is lit edge-on; the ground falls to rust.
_LASVEGAS_SKY = (
    (0, _lasvegas_mix(r=0.78, y=0.08, k=0.14)),
    (150, _lasvegas_mix(r=0.70, y=0.30)),
    (330, _lasvegas_mix(r=0.62, y=0.38)),
    (_LASVEGAS_HORIZON, _lasvegas_mix(r=0.54, y=0.40, w=0.06)),
    (_LASVEGAS_HORIZON + 2, _lasvegas_mix(r=0.66, y=0.24, k=0.10)),
    (480, _lasvegas_mix(r=0.58, y=0.04, k=0.38)),
)
def _lasvegas_font(size: int, path: str = BARLOWCOND_MEDIUM):
    return load_font([path, *META_FONT_CANDIDATES], size=size)


def _lasvegas_paint_haze(scene: Image.Image) -> None:
    """The sky and ground gradient, the sun and its bloom, the dust bands."""
    size = scene.size
    w, h = size
    column = Image.new("RGB", (1, h))
    for y in range(h):
        column.putpixel((0, y), _lerp_stops(_LASVEGAS_SKY, y))
    scene.paste(column.resize(size, Image.Resampling.NEAREST), (0, 0))
    column.close()
    sky = Image.new("L", size, 0)
    ImageDraw.Draw(sky).rectangle((0, 0, w, _LASVEGAS_HORIZON), fill=255)
    sx, sy, sr = _LASVEGAS_SUN
    # The sun is a smear in the dust, not a disc against a sky: a wide warm
    # bloom, a paler inner one, the disc itself barely edged.
    for box, blur, tone, strength in (
        ((sx - 260, sy - 200, sx + 260, sy + 240), 90, _lasvegas_mix(r=0.46, y=0.54), 0.85),
        ((sx - 80, sy - 72, sx + 80, sy + 80), 30, _lasvegas_mix(r=0.24, y=0.64, w=0.12), 0.95),
        ((sx - sr, sy - sr, sx + sr, sy + sr), 2, _lasvegas_mix(y=0.45, w=0.55), 1.0),
    ):
        glow = _soft_ellipse_mask(size, box, blur).point(lambda v, s=strength: int(v * s))
        glow = ImageChops.multiply(glow, sky)
        scene.paste(Image.new("RGB", size, tone), (0, 0), glow)
        glow.close()
    # Dust: long horizontal bands drifting through the haze, darker and
    # paler, thinning toward the ground where the air is thickest.
    dark = _smooth_noise(size, (4, 14), _LASVEGAS_SEED + 1).point(lambda v: max(0, v - 140))
    pale = _smooth_noise(size, (3, 12), _LASVEGAS_SEED + 2).point(lambda v: max(0, v - 150))
    scene.paste(Image.new("RGB", size, _lasvegas_mix(r=0.80, k=0.20)), (0, 0), ImageChops.multiply(dark, sky))
    scene.paste(Image.new("RGB", size, _lasvegas_mix(r=0.36, y=0.64)), (0, 0), ImageChops.multiply(pale, sky))
    sky.close()


def _lasvegas_paint_far(scene: Image.Image) -> None:
    """The dead casino towers along the horizon, barely darker than the haze."""
    size = scene.size
    rng = random.Random(_LASVEGAS_SEED + 3)
    # Two ranks: the farther fainter and taller, the nearer squat and a
    # shade darker, so the skyline has depth rather than a bar chart's.
    for rank, (heights, strength, blur) in enumerate((((60, 150), 0.34, 3), ((24, 80), 0.56, 2))):
        towers = Image.new("L", size, 0)
        draw = ImageDraw.Draw(towers)
        x = 436 + rank * 14
        while x < 820:
            width = rng.randint(14, 30)
            top = _LASVEGAS_HORIZON - rng.randint(*heights)
            # A broken crown: the roofline slopes where a floor fell in.
            drop = rng.choice((0, 0, rng.randint(6, 18)))
            draw.polygon(((x, _LASVEGAS_HORIZON), (x, top + drop), (x + width, top),
                          (x + width, _LASVEGAS_HORIZON)), fill=255)
            if rng.random() < 0.3:      # a mast
                draw.rectangle((x + width // 2, top - rng.randint(10, 26), x + width // 2 + 2, top), fill=255)
            x += width + rng.randint(10, 44)
        if rank == 0:
            # The pyramid on the far left, the one the Wallace tower echoes.
            draw.polygon(((444, _LASVEGAS_HORIZON), (498, _LASVEGAS_HORIZON - 58),
                          (552, _LASVEGAS_HORIZON)), fill=255)
        towers = towers.filter(ImageFilter.GaussianBlur(blur)).point(lambda v, s=strength: int(v * s))
        scene.paste(Image.new("RGB", size, _lasvegas_mix(r=0.70, y=0.10, k=0.20)), (0, 0), towers)
        towers.close()


def _lasvegas_paint_ground(scene: Image.Image) -> None:
    """Dune ridges below the horizon: soft darker crests in the rust."""
    size = scene.size
    w, h = size
    ridges = Image.new("L", size, 0)
    draw = ImageDraw.Draw(ridges)
    rng = random.Random(_LASVEGAS_SEED + 4)
    for y in range(_LASVEGAS_HORIZON + 8, h + 20, 14):
        pts = [(x, y + rng.randint(-5, 5)) for x in range(-40, w + 80, 60)]
        draw.line(_catmull_rom(pts, closed=False, samples=8), fill=200, width=3)
    ridges = ridges.filter(ImageFilter.GaussianBlur(3))
    scene.paste(Image.new("RGB", size, _lasvegas_mix(r=0.45, k=0.55)), (0, 0), ridges)
    ridges.close()


def _lasvegas_scene() -> Image.Image:
    """Everything the hour and the quote do not touch, dithered. Painted
    once per process."""
    key = (_lasvegas_paint_haze, _lasvegas_paint_far, _lasvegas_paint_ground)
    cached = _LASVEGAS_SCENE.get("frame")
    if cached is not None and cached[0] == key:
        return cached[1]
    size = (800, 480)
    scene = Image.new("RGB", size, _LASVEGAS_SKY[2][1])
    _lasvegas_paint_haze(scene)
    _lasvegas_paint_far(scene)
    _lasvegas_paint_ground(scene)
    image = _dither_calibrated(scene, _LASVEGAS_INKS)
    scene.close()
    _LASVEGAS_SCENE["frame"] = (key, image)
    return image


def _lasvegas_paint_figures(image: Image.Image) -> None:
    """K in his long coat, one hand held out to the bees, and the hive stack
    beside him. Solid black, on top of the dither."""
    draw = ImageDraw.Draw(image)
    black = SPECTRA6["black"]
    fx, gy = _LASVEGAS_K_FOOT
    # The coat: high collar, shoulders, flaring to a hem below the knee.
    coat = [(fx - 6, gy - 44), (fx + 6, gy - 44), (fx + 8, gy - 38), (fx + 9, gy - 26), (fx + 12, gy - 12),
            (fx + 9, gy - 10), (fx - 9, gy - 10), (fx - 12, gy - 12), (fx - 8, gy - 30), (fx - 8, gy - 40)]
    draw.polygon(coat, fill=black)
    draw.ellipse((fx - 4, gy - 53, fx + 4, gy - 44), fill=black)      # head
    draw.rectangle((fx - 5, gy - 10, fx - 2, gy), fill=black)          # legs
    draw.rectangle((fx + 2, gy - 10, fx + 5, gy), fill=black)
    draw.line((fx + 6, gy - 37, fx + 16, gy - 28, fx + 22, gy - 29), fill=black, width=3)   # the held-out arm
    draw.rectangle((fx - 8, gy, fx + 8, gy + 1), fill=black)          # shadow underfoot
    # The hives: three stacked boxes, each lid proud of its box, a red
    # slot of haze for the entrance.
    hx0, hy0, hx1, hy1 = _LASVEGAS_HIVES
    step = (hy1 - hy0) // 3
    for i in range(3):
        top = hy0 + i * step
        draw.rectangle((hx0 - 2, top, hx1 + 2, top + 2), fill=black)
        draw.rectangle((hx0, top + 3, hx1, top + step - 1), fill=black)
        draw.rectangle((hx0 + 9, top + step - 4, hx1 - 9, top + step - 3), fill=SPECTRA6["red"])
    draw.rectangle((hx0 + 1, hy1, hx0 + 3, hy1 + 3), fill=black)          # the stand's feet
    draw.rectangle((hx1 - 3, hy1, hx1 - 1, hy1 + 3), fill=black)
    # K's rim: the sun is behind and to his right, so his right edge and
    # the top of his arm catch it.
    yellow = SPECTRA6["yellow"]
    draw.line((fx + 7, gy - 41, fx + 8, gy - 37, fx + 9, gy - 26, fx + 11, gy - 13), fill=yellow, width=1)
    draw.line((fx + 3, gy - 52, fx + 4, gy - 48), fill=yellow, width=1)
    # The bees: a seeded cloud about the hand and the hives.
    rng = random.Random(_LASVEGAS_SEED + 5)
    for _ in range(22):
        if rng.random() < 0.55:
            x, y = fx + 22 + rng.gauss(0, 7), gy - 30 + rng.gauss(0, 6)
        else:
            x, y = (hx0 + hx1) / 2 + rng.gauss(0, 16), hy0 - 6 + rng.gauss(0, 8)
        draw.rectangle((round(x), round(y), round(x) + 1, round(y) + 1), fill=black)


def _lasvegas_tag(draw: ImageDraw.ImageDraw, xy, text: str, *, fill=None, ink=None, anchor_right=False) -> tuple:
    """A scanner tag: tracked condensed capitals on a solid black chip."""
    font = _lasvegas_font(11, BARLOWCOND_SEMIBOLD)
    fill = fill or SPECTRA6["black"]
    ink = ink or SPECTRA6["white"]
    width = round(sum(draw.textlength(ch, font=font) for ch in text) + 2 * (len(text) - 1))
    x, y = xy
    if anchor_right:
        x -= width + 8
    box = (x, y, x + width + 8, y + 15)
    draw.rectangle(box, fill=fill)
    draw_tracked(draw, (x + 4, y + 1), text, font, ink, tracking=2)
    return box


def _lasvegas_paint_scanner(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The spinner's overlay on the vista: corner brackets on K and the hives,
    a bio-signature tag, and the radiation readout under the sun."""
    white, black, yellow = SPECTRA6["white"], SPECTRA6["black"], SPECTRA6["yellow"]
    x0, y0, x1, y1 = _LASVEGAS_SCAN_RECT
    arm = 8
    for (x, y), (dx, dy) in (((x0, y0), (1, 1)), ((x1, y0), (-1, 1)), ((x0, y1), (1, -1)), ((x1, y1), (-1, -1))):
        draw.line((x, y, x + arm * dx, y), fill=white, width=2)
        draw.line((x, y, x, y + arm * dy), fill=white, width=2)
    _lasvegas_tag(draw, (x0, y0 - 18), "BIO SIGNATURE")
    rng = random.Random(_LASVEGAS_SEED ^ _row_digest(quote_row))
    _lasvegas_tag(draw, (776, 16), "LAS VEGAS  ·  EXCLUSION ZONE", anchor_right=True)
    # Radiation: five bars, the reading seeded from the quote.
    bx, by = 776 - 5 * 9, 36
    level = rng.randint(2, 4)
    draw.rectangle((bx - 40, by, 776, by + 13), fill=black)
    draw_tracked(draw, (bx - 36, by), "RAD", _lasvegas_font(11, BARLOWCOND_SEMIBOLD), white, tracking=2)
    for i in range(5):
        draw.rectangle((bx + i * 9, by + 3, bx + i * 9 + 5, by + 10), fill=yellow if i < level else None,
                       outline=yellow)


def _lasvegas_paint_pane(draw: ImageDraw.ImageDraw) -> None:
    """The archive pane: black, a yellow hairline, a chamfered corner, and
    the yellow header bar."""
    black, yellow = SPECTRA6["black"], SPECTRA6["yellow"]
    x0, y0, x1, y1 = _LASVEGAS_PANE
    cut = 14
    outline = [(x0, y0), (x1, y0), (x1, y1 - cut), (x1 - cut, y1), (x0, y1)]
    draw.polygon(outline, fill=black)
    draw.line([*outline, outline[0]], fill=yellow, width=1)
    draw.rectangle((x0, y0, x1, y0 + _LASVEGAS_HEADER_H), fill=yellow)
    font = _lasvegas_font(14, BARLOWCOND_SEMIBOLD)
    draw_tracked(draw, (x0 + 12, y0 + 4), "LAPD  ·  REPLICANT DETECTION", font, black, tracking=3)
    draw_tracked(draw, (x1 - 12, y0 + 4), "KD6-3.7", font, black, tracking=3, anchor_right=True)
    # Registration ticks down the left margin, as on the archive's screens.
    for y in range(_LASVEGAS_QUOTE_RECT[1], _LASVEGAS_QUOTE_RECT[3], 12):
        draw.line((x0 + 8, y, x0 + 11, y), fill=yellow, width=1)
    draw.line((_LASVEGAS_QUOTE_RECT[0], _LASVEGAS_DNA_RECT[1] - 10, x1 - 22, _LASVEGAS_DNA_RECT[1] - 10),
              fill=yellow, width=1)


def _lasvegas_paint_dna(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """Two lines of base pairs seeded from the quote, a few of them matched
    in yellow, as on the archive's DNA readout."""
    white, yellow = SPECTRA6["white"], SPECTRA6["yellow"]
    rng = random.Random(_LASVEGAS_SEED ^ _row_digest(quote_row) ^ 0x444E41)
    font = load_font([SHARETECHMONO_REGULAR, *META_FONT_CANDIDATES], size=12)
    x0, y0, x1, y1 = _LASVEGAS_DNA_RECT
    advance = draw.textlength("A", font=font) + 1
    count = int((x1 - x0) // advance)
    for row in range(2):
        y = y0 + row * 15
        for i in range(count):
            base = rng.choice("ACGT")
            lit = rng.random() < 0.06
            draw.text((x0 + i * advance, y), base, font=font, fill=yellow if lit else white)


def _lasvegas_cell_rects() -> list:
    x0, y0, x1, y1 = _LASVEGAS_CELL_BAND
    width = (x1 - x0 - 11 * _LASVEGAS_CELL_GAP) // 12
    return [(x0 + i * (width + _LASVEGAS_CELL_GAP), y0, x0 + i * (width + _LASVEGAS_CELL_GAP) + width, y1)
            for i in range(12)]


def _lasvegas_paint_cells(draw: ImageDraw.ImageDraw, hour: int) -> None:
    """The twelve archive drawers along the pane's foot, the hour's lit."""
    white, black, yellow = SPECTRA6["white"], SPECTRA6["black"], SPECTRA6["yellow"]
    font = _lasvegas_font(12, BARLOWCOND_SEMIBOLD)
    for i, (x0, y0, x1, y1) in enumerate(_lasvegas_cell_rects()):
        active = i + 1 == hour
        draw.rectangle((x0, y0, x1, y1), fill=yellow if active else black, outline=yellow if active else white)
        label = f"{i + 1:02d}"
        draw.text((x0 + (x1 - x0 - draw.textlength(label, font=font)) / 2, y0 + 3), label, font=font,
                  fill=black if active else white)


def _lasvegas_layout(draw: ImageDraw.ImageDraw, quote_row: dict):
    return _place_quote(draw, quote_row, _LASVEGAS_QUOTE_RECT, theme="lasvegas",
                        font_max=32, font_min=17, line_height_mult=1.3)


def _lasvegas_paint_byline(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "").strip()
    parts = [p.upper() for p in (author, title) if p]
    if not parts:
        return
    x0, _, x1, _ = _LASVEGAS_QUOTE_RECT
    font, text = fit_text_to_width(draw, "  ·  ".join(parts), [BARLOWCOND_MEDIUM, *META_FONT_CANDIDATES],
                                   16, x1 - x0, floor=13, tracking=2)
    draw_tracked(draw, (x0, _LASVEGAS_BYLINE_Y), text, font, SPECTRA6["yellow"], tracking=2)


def render_lasvegas_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The dead Las Vegas with K's archive pane (see docs/themes.md)."""
    hour = _clock_hour12(time_str)
    image = _lasvegas_scene().copy()
    _lasvegas_paint_figures(image)
    draw = ImageDraw.Draw(image)
    _lasvegas_paint_scanner(draw, quote_row)
    _lasvegas_paint_pane(draw)
    _paint_placed(draw, _lasvegas_layout(draw, quote_row), SPECTRA6["white"], SPECTRA6["yellow"])
    _lasvegas_paint_byline(draw, quote_row)
    _lasvegas_paint_dna(draw, quote_row)
    _lasvegas_paint_cells(draw, hour)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("lasvegas",), render=render_lasvegas_frame)
