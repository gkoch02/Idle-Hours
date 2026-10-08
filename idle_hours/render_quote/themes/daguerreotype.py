"""The ``daguerreotype`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from .._paths import BASE_DIR
from ..fonts import load_font, normalize_dashes, theme_font_candidates
from ..furniture import draw_centred_styled_lines, draw_truncated_centred_byline
from ..layout import fit_quote_balanced, strip_underscore_emphasis
from ..palette import (
    SPECTRA6,
    SPECTRA6_PALETTE,
    BAYER_8x8,
    _load_dithered_plate,
    gray_pixel_access,
    pixel_access,
    snap_image_to_palette,
)
from ..primitives import _flow_stroke_hash, _smooth_noise, paint_relief_mask
from ..spec import FrameSpec

# The daguerreotype landscape (scripts/generate_daguerreotype_plate.py) dithers
# against white+black ONLY, with Atkinson diffusion — the plate is the silver
# image itself, and any chroma belongs to the case (brass mat, sepia tarnish,
# velvet lid), painted as primitives around it.
DAGUERREOTYPE_PLATE = BASE_DIR / "assets" / "daguerreotype_plate.png"
_SILVER_PALETTE = [SPECTRA6["white"], SPECTRA6["black"]]


# ---------------------------------------------------------------------------
# daguerreotype — a cased photograph, lying open
#
# An 1850s daguerreotype case opened flat like a book: black leather outside,
# a hinge down the spine, the pressed-velvet pad of the lid on the left and
# the plate on the right behind a brass mat with a portrait-oval window. Full
# design notes: docs/themes.md (``daguerreotype``).
#
# The quote is gold-stamped on the velvet, where a studio stamped its name:
# solid yellow on the red pad, the matched phrase in white. There is no card,
# which is what sets this theme apart from ``autochrome`` and ``photo``.
#
# The plate is a committed continuous-tone landscape
# (``scripts/generate_daguerreotype_plate.py``) cover-cropped to the oval and
# Atkinson-dithered at render time against white+black only (Atkinson's
# discarded error blows highlights to silver and crushes shadows, the
# process's tonal signature), so no chroma scatters into the silver. All
# colour belongs to the case: the brass mat (Y+R gold), the pewter preserver
# (K+W 50/50), an R+G tarnish ring creeping in from the oval's rim that
# doubles as the vignette, and the velvet. The mat's pressed double ring and
# the pad's pressed border are both ``paint_relief_mask``. A missing plate
# degrades to ``_daguerreotype_paint_plate_fallback``.
#
# A photograph carries no clock: ``time_str`` is del-asserted (pinned by
# ``TestDaguerreotypePlate``).
_DAG_LID = (16, 16, 391, 463)                  # the velvet pad, inside the leather
_DAG_BASE = (408, 16, 783, 463)                # the plate side, inside the leather
_DAG_PRESERVER = 8                             # pewter band round the brass mat
_DAG_OVAL = (450, 48, 742, 432)                # the mat's window, bbox
_DAG_RING_GAP = 7                              # pressed ring offset outside the oval
_DAG_PAD_BORDER = 18                           # pressed border inset on the velvet
_DAG_TEXT = (58, 66, 350, 414)                 # the stamped quote's box on the pad
_DAG_TARNISH_START = 0.80                      # radial fraction where tarnish begins
_DAG_GOLD_RED = 0.375                          # Y+R 5/8:3/8 — the documented gold
_DAG_PLATE_FOCUS = (0.8, 0.5)                  # keep the tree inside the portrait oval
_DAG_HINGES = (88, 360)                        # hinge knuckle tops on the spine


def _daguerreotype_oval_radial(x: float, y: float) -> float:
    """Normalised radial position inside the oval window: 0 centre, 1 rim."""
    x0, y0, x1, y1 = _DAG_OVAL
    nx = (x - (x0 + x1) / 2) / ((x1 - x0) / 2)
    ny = (y - (y0 + y1) / 2) / ((y1 - y0) / 2)
    return math.hypot(nx, ny)


def _daguerreotype_paint_case(image: Image.Image) -> None:
    """The open case: black leather everywhere, pewter hinge knuckles on the
    spine between the two halves."""
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 799, 479), fill=SPECTRA6["black"])
    px = pixel_access(image)
    white, black = SPECTRA6["white"], SPECTRA6["black"]
    spine_x0, spine_x1 = _DAG_LID[2] - 2, _DAG_BASE[0] + 2
    for top in _DAG_HINGES:
        for y in range(top, top + 34):
            for x in range(spine_x0, spine_x1 + 1):
                px[x, y] = white if (x + y) & 1 else black
        draw.rectangle((spine_x0, top, spine_x1, top + 33), outline=black, width=1)


def _daguerreotype_paint_velvet(image: Image.Image) -> None:
    """The lid's pad: red velvet whose nap crushes to black in soft drifts and
    falls into shadow toward the pad's padded edges, kept clean behind the
    stamped text so the gold reads."""
    x0, y0, x1, y1 = _DAG_LID
    w, h = x1 - x0 + 1, y1 - y0 + 1
    red, black = SPECTRA6["red"], SPECTRA6["black"]
    nap = gray_pixel_access(_smooth_noise((w, h), (14, 18), seed=1851))
    px = pixel_access(image)
    for y in range(y0, y1 + 1):
        row = BAYER_8x8[y % 8]
        ny = abs((y - (y0 + y1) / 2) / (h / 2))
        for x in range(x0, x1 + 1):
            nx = abs((x - (x0 + x1) / 2) / (w / 2))
            edge = max(nx, ny)
            pillow = max(0.0, (edge - 0.78) / 0.22) ** 1.6 * 0.55
            crush = max(0.0, (nap[x - x0, y - y0] - 150) / 105.0) * 0.10
            cut = 64 * (pillow + crush)
            px[x, y] = black if row[x % 8] < cut else red


def _daguerreotype_paint_pad_border(image: Image.Image) -> None:
    """The pad's pressed border: a double rounded rule debossed into the nap,
    catching gold light on its far wall."""
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    x0, y0, x1, y1 = _DAG_LID
    b = _DAG_PAD_BORDER
    mask_draw.rounded_rectangle((x0 + b, y0 + b, x1 - b, y1 - b), radius=22, outline=255, width=3)
    mask_draw.rounded_rectangle((x0 + b + 9, y0 + b + 9, x1 - b - 9, y1 - b - 9),
                                radius=14, outline=255, width=1)
    paint_relief_mask(image, mask, highlight=SPECTRA6["black"], shadow=SPECTRA6["yellow"],
                      face=SPECTRA6["red"], radius=2, strength=3.0, cap=0.6,
                      ground=frozenset({SPECTRA6["red"], SPECTRA6["black"]}))


def _daguerreotype_paint_mat(image: Image.Image) -> None:
    """The plate side: brass mat field (Y+R gold) inside a pewter preserver
    band (the K+W 50/50 checkerboard, which reads as brushed metal next to
    the brass)."""
    px = pixel_access(image)
    yellow, red, white, black = (SPECTRA6[c] for c in ("yellow", "red", "white", "black"))
    gold_cut = 64 * _DAG_GOLD_RED
    x0, y0, x1, y1 = _DAG_BASE
    p = _DAG_PRESERVER
    for y in range(y0, y1 + 1):
        row = BAYER_8x8[y % 8]
        for x in range(x0, x1 + 1):
            if x < x0 + p or y < y0 + p or x > x1 - p or y > y1 - p:
                px[x, y] = white if (x + y) & 1 else black
            else:
                px[x, y] = red if row[x % 8] < gold_cut else yellow
    draw = ImageDraw.Draw(image)
    draw.rectangle((x0 + p, y0 + p, x1 - p, y1 - p), outline=black, width=1)


def _daguerreotype_paint_plate(image: Image.Image) -> None:
    """The silver image: the committed landscape, cover-cropped to the
    portrait oval and Atkinson-dithered W/K."""
    x0, y0, x1, y1 = _DAG_OVAL
    ow, oh = x1 - x0, y1 - y0
    plate = _load_dithered_plate(DAGUERREOTYPE_PLATE, ow, oh, method="atkinson",
                                 palette=_SILVER_PALETTE, focus=_DAG_PLATE_FOCUS)
    px = pixel_access(image)
    if plate is None:
        _daguerreotype_paint_plate_fallback(image)
        return
    pp = pixel_access(plate)
    for y in range(y0, y1):
        for x in range(x0, x1):
            if _daguerreotype_oval_radial(x, y) <= 1.0:
                px[x, y] = pp[x - x0, y - y0]


def _daguerreotype_paint_plate_fallback(image: Image.Image) -> None:
    """A stripped install still gets a photograph-shaped silver image: sky
    blowing to white, a Bayer-graded mid band, a crushed dark foreground."""
    px = pixel_access(image)
    white, black = SPECTRA6["white"], SPECTRA6["black"]
    x0, y0, x1, y1 = _DAG_OVAL
    for y in range(y0, y1):
        t = (y - y0) / (y1 - y0)
        row = BAYER_8x8[y % 8]
        threshold = 0.0 if t < 0.45 else (t - 0.45) * 150.0
        for x in range(x0, x1):
            if _daguerreotype_oval_radial(x, y) <= 1.0:
                px[x, y] = black if row[x % 8] < threshold else white


def _daguerreotype_paint_tarnish(image: Image.Image) -> None:
    """The sepia bloom creeping in from the oval's rim: R+G on pixel parity
    (the documented sepia), hash-gated at a density that rises toward the
    edge so it is also the plate's vignette."""
    px = pixel_access(image)
    red, green = SPECTRA6["red"], SPECTRA6["green"]
    x0, y0, x1, y1 = _DAG_OVAL
    for y in range(y0, y1):
        for x in range(x0, x1):
            radial = _daguerreotype_oval_radial(x, y)
            if radial > 1.0 or radial < _DAG_TARNISH_START:
                continue
            reach = (radial - _DAG_TARNISH_START) / (1.0 - _DAG_TARNISH_START)
            if _flow_stroke_hash(x, y, 7) < reach * reach * 0.85:
                px[x, y] = red if (x + y) & 1 else green


def _daguerreotype_paint_ring(image: Image.Image) -> None:
    """The mat's pressed double ring, embossing brass around the window under
    the shared upper-left light."""
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    g = _DAG_RING_GAP
    x0, y0, x1, y1 = _DAG_OVAL
    mask_draw.ellipse((x0 - g, y0 - g, x1 + g, y1 + g), outline=255, width=3)
    mask_draw.ellipse((x0 - g - 8, y0 - g - 8, x1 + g + 8, y1 + g + 8), outline=255, width=2)
    paint_relief_mask(image, mask, highlight=SPECTRA6["white"], shadow=SPECTRA6["black"],
                      face=SPECTRA6["yellow"], face_minor=SPECTRA6["red"],
                      face_minor_share=_DAG_GOLD_RED,
                      radius=2, strength=3.4, cap=0.6,
                      ground=frozenset({SPECTRA6["yellow"], SPECTRA6["red"]}))


def _daguerreotype_paint_stamp(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The quote, gold-stamped on the velvet in Libre Caslon: solid yellow,
    the matched phrase in white, the byline under a short gold rule."""
    x0, y0, x1, y1 = _DAG_TEXT
    yellow = SPECTRA6["yellow"]
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    quote_font, quote_font_bold, wrapped, line_height, _, _ = fit_quote_balanced(
        draw, display_quote, quote_row.get("matched_text") or "",
        x1 - x0, y1 - y0 - 64, font_max=28, font_min=14,
        line_height_mult=1.32, theme="daguerreotype",
    )
    block_h = len(wrapped) * line_height
    top = y0 + max(0, (y1 - y0 - 64 - block_h) // 2)
    draw_centred_styled_lines(
        draw, wrapped, x0=x0, x1=x1, top=top, line_height=line_height,
        regular=quote_font, bold=quote_font_bold,
        fill=yellow, accent=SPECTRA6["white"], min_inset=0,
    )
    cx = (x0 + x1) // 2
    draw.line((cx - 28, y1 - 34, cx + 28, y1 - 34), fill=yellow, width=1)
    draw_truncated_centred_byline(
        draw, quote_row, centre=cx, baseline=y1 - 10,
        max_width=x1 - x0, fill=yellow,
        font=load_font(theme_font_candidates("daguerreotype", "quote_regular"), size=14),
    )


def render_daguerreotype_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A cased daguerreotype lying open (see the section comment).

    Composed at 800x480 and NEAREST-downsampled otherwise (the ``metro``
    convention): the case geometry is absolute, and interpolation would
    average the silver stipple into greys the panel cannot print.
    """
    del time_str  # see the section comment; deliberately unused.
    image = Image.new("RGB", (800, 480), color=SPECTRA6["black"])
    _daguerreotype_paint_case(image)
    _daguerreotype_paint_velvet(image)
    _daguerreotype_paint_pad_border(image)
    _daguerreotype_paint_mat(image)
    _daguerreotype_paint_plate(image)
    _daguerreotype_paint_tarnish(image)
    _daguerreotype_paint_ring(image)
    draw = ImageDraw.Draw(image)
    _daguerreotype_paint_stamp(draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("daguerreotype",), render=render_daguerreotype_frame)
