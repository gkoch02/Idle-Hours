"""The ``goya`` theme: Goya's *El Perro* from the *Pinturas negras*, the dog looking up at the time.

Design notes: docs/themes.md § goya
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .._paths import (
    LIBREBASKERVILLE_ITALIC_VARIABLE,
    LIBREBASKERVILLE_VARIABLE,
    LIBRECASLON_VARIABLE,
    META_FONT_BOLD_CANDIDATES,
    META_FONT_CANDIDATES,
)
from ..fonts import load_font
from ..furniture import _place_quote, fallback_title
from ..palette import _PANEL_INKS, SPECTRA6, SPECTRA6_PALETTE, _dither_calibrated, pixel_access, snap_image_to_palette
from ..primitives import _catmull_rom, _lerp_stops, _shade_silhouette, _smooth_noise, _soft_ellipse_mask, paint_craquelure
from ..spec import FrameSpec
from ..text import fit_text_to_width

_GOYA_SEED = 0x474F5941              # GOYA
_GOYA_INKS = ("black", "red", "yellow", "white")
_GOYA_SLOPE_LEFT = 386               # the slope's top edge at x=0 …
_GOYA_SLOPE_RIGHT = 322              # … and at x=800: it rises to the right
_GOYA_DOG_PIVOT = (252, 308)         # the skull's centre; the neck runs down into the slope
_GOYA_GAZE_MIN = math.radians(14)    # a near-level look …
_GOYA_GAZE_MAX = math.radians(44)    # … to a nose well in the air
_GOYA_GAZE_DEFAULT = math.radians(28)  # the painting's own tilt
_GOYA_QUOTE_RECT = (84, 50, 716, 292)
_GOYA_LABEL_RECT = (540, 382, 780, 470)
_GOYA_CRACK_CELL = (30, 19)
# The void, top to foot, in the calibrated space: dark umber at the top, the
# pale ochre passage where the painting's light sits, a deeper ochre above
# the slope, umber again beneath it.
_GOYA_VOID_STOPS = (
    (0, (70, 58, 38)), (64, (108, 92, 50)), (150, (144, 128, 70)), (230, (140, 122, 64)),
    (320, (116, 96, 46)), (400, (82, 64, 38)), (480, (60, 48, 30)),
)
_GOYA_LIGHT = (172, 156, 94)         # the pale passage, pooled upper-centre-left
_GOYA_STAIN = (86, 68, 42)           # the cool stain dragged over the upper right
_GOYA_SLOPE = (42, 34, 28)           # the slope: a warm black
_GOYA_SLOPE_EDGE = (72, 54, 36)      # its brushed upper edge
_GOYA_DOG_BASE = (102, 74, 46)       # the dog: raw umber …
_GOYA_DOG_LIGHT = (118, 90, 58)      # … lit from the upper left …
_GOYA_DOG_DARK = (56, 42, 30)        # … and in shadow toward the slope
_GOYA_DOG_EAR = (62, 46, 32)         # the dropped ear, in the skull's shadow
# The head and neck in a local frame: +x toward the nose, +y down, origin at
# the skull's centre, muzzle level. Rotated about the origin by the gaze; the
# neck runs far enough down to meet the slope at any pitch in range.
_GOYA_HEAD = (
    (-34, -8), (-26, -30), (-8, -42), (16, -38), (30, -30), (40, -22), (56, -16), (72, -10),
    (80, -4), (78, 4), (66, 12), (50, 16), (36, 20), (22, 24), (8, 30), (-4, 40),
    (-10, 56), (-14, 90), (-58, 90), (-54, 56), (-48, 28), (-44, 8),
)
_GOYA_EAR = ((-30, -14), (-44, -2), (-50, 18), (-44, 32), (-32, 28), (-26, 10), (-24, -4))
_GOYA_EYE = (26, -16)
_GOYA_NOSTRIL = (74, -6)
_GOYA_SCENE: dict = {}


def _goya_slope_edge() -> list:
    """The slope's upper edge, x=0..800: a line rising to the right with a
    seeded brush wobble and a swell where the dog stands."""
    rng = random.Random(_GOYA_SEED + 1)
    points = []
    for x in range(0, 801, 25):
        t = x / 800.0
        y = _GOYA_SLOPE_LEFT + (_GOYA_SLOPE_RIGHT - _GOYA_SLOPE_LEFT) * t
        y -= 14 * math.exp(-((x - _GOYA_DOG_PIVOT[0]) / 90.0) ** 2)
        points.append((x, y + rng.uniform(-5, 5)))
    return _catmull_rom(points, closed=False, samples=6)


def _goya_slope_mask(size) -> Image.Image:
    mask = Image.new("L", size, 0)
    edge = _goya_slope_edge()
    ImageDraw.Draw(mask).polygon([(0, size[1])] + [(round(x), round(y)) for x, y in edge] + [(size[0], size[1])],
                                 fill=255)
    return mask


def _goya_paint_void(scene: Image.Image) -> None:
    """The void in continuous tone: the gradient, the pale passage, the
    stain, the dragged strokes and the grain, then the slope."""
    width, height = scene.size
    column = Image.new("RGB", (1, height))
    cp = pixel_access(column)
    for y in range(height):
        cp[0, y] = _lerp_stops(_GOYA_VOID_STOPS, y)
    scene.paste(column.resize((width, height), Image.Resampling.NEAREST), (0, 0))
    light = _soft_ellipse_mask(scene.size, (40, 70, 560, 290), 44).point(lambda v: int(v * 0.58))
    scene.paste(Image.new("RGB", scene.size, _GOYA_LIGHT), (0, 0), light)
    stain = _soft_ellipse_mask(scene.size, (520, -30, 800, 150), 34).point(lambda v: int(v * 0.66))
    scene.paste(Image.new("RGB", scene.size, _GOYA_STAIN), (0, 0), stain)
    # Facture: broad dragged strokes (a noise streaked eight to one) over a
    # finer grain, each centred so it moves the tone both ways.
    for cells, amp, salt in (((10, 44), 13, 2), ((48, 36), 7, 3), ((5, 3), 9, 4)):
        grain = _smooth_noise(scene.size, cells, _GOYA_SEED + salt).point(lambda v, a=amp: v * (2 * a) // 255)
        tint = Image.merge("RGB", (grain, grain, grain))
        scene.paste(ImageChops.subtract(ImageChops.add(scene, tint), Image.new("RGB", scene.size, (amp,) * 3)))
    # The slope: a warm black, its upper edge brushed lighter.
    slope = _goya_slope_mask(scene.size)
    edge = ImageChops.subtract(slope, slope.filter(ImageFilter.MinFilter(9))).filter(ImageFilter.GaussianBlur(3))
    scene.paste(Image.new("RGB", scene.size, _GOYA_SLOPE), (0, 0), slope)
    scene.paste(Image.new("RGB", scene.size, _GOYA_SLOPE_EDGE), (0, 0), edge.point(lambda v: int(v * 0.7)))


def _goya_scene() -> Image.Image:
    """The void and the slope, dithered and crazed. Painted once per process."""
    key = (_goya_paint_void, paint_craquelure)
    cached = _GOYA_SCENE.get("frame")
    if cached is not None and cached[0] == key:
        return cached[1]
    size = (800, 480)
    scene = Image.new("RGB", size, _PANEL_INKS["black"])
    _goya_paint_void(scene)
    image = _dither_calibrated(scene, _GOYA_INKS)
    paint_craquelure(image, Image.new("L", size, 255), seed=_GOYA_SEED + 5, cell=_GOYA_CRACK_CELL,
                     jitter=0.4, drop=0.24, diagonal=0.16, continuity=4,
                     dark=SPECTRA6["black"], light=SPECTRA6["yellow"], light_share=0.08)
    _GOYA_SCENE["frame"] = (key, image)
    return image


def _goya_layout(draw: ImageDraw.ImageDraw, quote_row: dict):
    """The quote's lines in the void, and the positioned bold chunks."""
    return _place_quote(draw, quote_row, _GOYA_QUOTE_RECT, theme="goya",
                        font_max=34, font_min=16, line_height_mult=1.32)


def _goya_gaze(placed) -> float:
    """The head's pitch above level, toward the matched phrase's centroid;
    the painting's own tilt when the quote carries no phrase."""
    bold = [(x + w / 2.0, y + lh / 2.0) for x, y, chunk, font, is_bold, w, lh in placed if is_bold and chunk.strip()]
    if not bold:
        return _GOYA_GAZE_DEFAULT
    cx = sum(p[0] for p in bold) / len(bold)
    cy = sum(p[1] for p in bold) / len(bold)
    px, py = _GOYA_DOG_PIVOT
    angle = math.atan2(py - cy, cx - px) if cx > px else _GOYA_GAZE_MAX
    return max(_GOYA_GAZE_MIN, min(_GOYA_GAZE_MAX, angle))


def _goya_turn(points, gaze: float) -> list:
    """Rotate local head points about the pivot: a positive gaze lifts the nose."""
    px, py = _GOYA_DOG_PIVOT
    c, s = math.cos(gaze), math.sin(gaze)
    return [(px + x * c + y * s, py - x * s + y * c) for x, y in points]


def _goya_paint_dog(image: Image.Image, gaze: float) -> None:
    """The dog: head and neck above the slope at the gaze's pitch, shaded,
    dithered in place against the four inks and crazed; the eye and nostril
    crisp on top."""
    size = image.size
    head = Image.new("L", size, 0)
    hd = ImageDraw.Draw(head)
    hd.polygon([(round(x), round(y)) for x, y in _catmull_rom(_goya_turn(_GOYA_HEAD, gaze), samples=6)], fill=255)
    ear = Image.new("L", size, 0)
    ImageDraw.Draw(ear).polygon([(round(x), round(y)) for x, y in _catmull_rom(_goya_turn(_GOYA_EAR, gaze), samples=6)],
                                fill=255)
    head = ImageChops.lighter(head, ear)
    # Only what stands above the slope is the dog; the rest is the slope.
    head = ImageChops.subtract(head, _goya_slope_mask(size))
    bbox = head.getbbox()
    if bbox is None:
        return
    pad = 6
    box = (max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(size[0], bbox[2] + pad), min(size[1], bbox[3] + pad))
    shaded = _shade_silhouette(head, _GOYA_DOG_BASE, _GOYA_DOG_LIGHT, _GOYA_DOG_DARK, offset=6, blur=4)
    shaded.paste(Image.new("RGB", size, _GOYA_DOG_EAR), (0, 0), ear.filter(ImageFilter.GaussianBlur(1)))
    grain = _smooth_noise(size, (40, 24), _GOYA_SEED + 6).point(lambda v: v * 12 // 255)
    shaded = ImageChops.subtract(ImageChops.add(shaded, Image.merge("RGB", (grain, grain, grain))),
                                 Image.new("RGB", size, (6, 6, 6)))
    dithered = _dither_calibrated(shaded.crop(box), _GOYA_INKS)
    image.paste(dithered, box[:2], head.crop(box))
    crop = image.crop(box)
    paint_craquelure(crop, head.crop(box), seed=_GOYA_SEED + 7, cell=_GOYA_CRACK_CELL, jitter=0.4, drop=0.24,
                     diagonal=0.16, continuity=4, dark=SPECTRA6["black"], light=SPECTRA6["yellow"], light_share=0.08)
    image.paste(crop, box[:2])
    draw = ImageDraw.Draw(image)
    (ex, ey), (nx, ny) = _goya_turn((_GOYA_EYE, _GOYA_NOSTRIL), gaze)
    draw.ellipse((ex - 5, ey - 4, ex + 5, ey + 4), fill=SPECTRA6["black"])
    draw.rectangle((ex - 2, ey - 3, ex - 1, ey - 2), fill=SPECTRA6["white"])
    draw.ellipse((nx - 4, ny - 4, nx + 4, ny + 4), fill=SPECTRA6["black"])
    for m in (head, ear, shaded, dithered, crop):
        m.close()


def _goya_paint_quote(draw: ImageDraw.ImageDraw, placed) -> None:
    """The quote written into the void: black Libre Baskerville, ragged
    right, the matched phrase Bold in the Black Paintings' one red."""
    black, red = SPECTRA6["black"], SPECTRA6["red"]
    for x, y, chunk, font, is_bold, _w, _lh in placed:
        draw.text((x, y), chunk, font=font, fill=red if is_bold else black)


def _goya_label_font(size: int, instance: str = "Regular"):
    """Libre Baskerville, the named instance, for the gallery label."""
    file = LIBREBASKERVILLE_ITALIC_VARIABLE if instance == "Italic" else LIBREBASKERVILLE_VARIABLE
    return load_font([(file, instance), (LIBRECASLON_VARIABLE, "Regular"), *META_FONT_CANDIDATES], size=size)


def _goya_inventory(quote_row: dict) -> str:
    """The Prado's inventory form — ``P000767`` is *El Perro* — from the
    Gutenberg id, or the series' own number when the row has none."""
    source = str(quote_row.get("source_id") or "").strip()
    digits = "".join(ch for ch in source if ch.isdigit())
    return f"P{int(digits) % 1_000_000:06d}" if digits else "P000767"


def _goya_paint_label(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The gallery label: a white card on the slope with the author on the
    artist's line, the title in italic, the medium and the series."""
    x0, y0, x1, y1 = _GOYA_LABEL_RECT
    black, white = SPECTRA6["black"], SPECTRA6["white"]
    draw.rectangle((x0, y0, x1, y1), fill=white)
    pad = 10
    measure = x1 - x0 - 2 * pad
    author = (quote_row.get("author") or "").strip() or "Anónimo"
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "").strip()
    font, text = fit_text_to_width(draw, author, [(LIBREBASKERVILLE_VARIABLE, "SemiBold"),
                                                  (LIBRECASLON_VARIABLE, "Bold"), *META_FONT_BOLD_CANDIDATES],
                                   16, measure, floor=12)
    draw.text((x0 + pad, y0 + 9), text, font=font, fill=black)
    if title:
        font, text = fit_text_to_width(draw, title, [(LIBREBASKERVILLE_ITALIC_VARIABLE, "Italic"),
                                                     (LIBRECASLON_VARIABLE, "Regular"), *META_FONT_CANDIDATES],
                                       14, measure, floor=11)
        draw.text((x0 + pad, y0 + 33), text, font=font, fill=black)
    small = _goya_label_font(11)
    draw.text((x0 + pad, y0 + 55), "Óleo sobre revoco trasladado a lienzo", font=small, fill=black)
    draw.text((x0 + pad, y0 + 70), "Pinturas negras", font=small, fill=black)
    inventory = _goya_inventory(quote_row)
    draw.text((x1 - pad - draw.textlength(inventory, font=small), y0 + 70), inventory, font=small, fill=black)


def render_goya_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """*El Perro*, with the quote in the void and the dog looking at the
    time (see docs/themes.md).

    ``time_str`` is unused by design: a painting carries no clock.
    """
    del time_str
    image = _goya_scene().copy()
    draw = ImageDraw.Draw(image)
    placed = _goya_layout(draw, quote_row)
    _goya_paint_dog(image, _goya_gaze(placed))
    draw = ImageDraw.Draw(image)
    _goya_paint_quote(draw, placed)
    _goya_paint_label(draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("goya",), render=render_goya_frame)
