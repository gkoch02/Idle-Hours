"""The ``daguerreotype`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from .._paths import BASE_DIR
from ..fonts import load_font, normalize_dashes, theme_font_candidates
from ..furniture import draw_centred_styled_lines, draw_truncated_centred_byline, paint_mount_card
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, _load_dithered_plate, pixel_access, snap_image_to_palette
from ..primitives import _flow_stroke_hash, paint_relief_mask
from ..spec import FrameSpec

# The daguerreotype landscape (scripts/generate_daguerreotype_plate.py) dithers
# against white+black ONLY, with Atkinson diffusion — the plate is the silver
# image itself, and any chroma belongs to the case (brass mat, sepia tarnish),
# painted as primitives on top.
DAGUERREOTYPE_PLATE = BASE_DIR / "assets" / "daguerreotype_plate.png"
_SILVER_PALETTE = [SPECTRA6["white"], SPECTRA6["black"]]


# ---------------------------------------------------------------------------
# daguerreotype — a cased monochrome photograph
#
# An 1850s cased daguerreotype: brass mat, oval window, a silvered plate, and
# the quote on a cream caption slip. Full design notes: docs/themes.md
# (``daguerreotype``).
#
# The plate is a committed continuous-tone landscape
# (``scripts/generate_daguerreotype_plate.py``) Atkinson-dithered at render
# time against white+black only (``dither_image_to_palette``: Atkinson's
# discarded error blows highlights to silver and crushes shadows, the
# process's tonal signature), so no chroma scatters into the silver. All
# colour belongs to the case: the brass mat (Y+R gold), the pewter rim (K+W
# 50/50), and an R+G tarnish ring creeping in from the oval's rim that
# doubles as the vignette. The mat's pressed double ring is
# ``paint_relief_mask``. A missing plate degrades to
# ``_daguerreotype_paint_plate_fallback``.
#
# A photograph carries no clock: ``time_str`` is del-asserted (pinned by
# ``TestDaguerreotypePlate``). The matched phrase is solid red on the slip —
# R+K maroon shreds at caption size and gold on cream goes pale.
_DAG_OVAL = (58, 40, 482, 440)                 # the mat's window, bbox
_DAG_RING_GAP = 7                              # pressed ring offset outside the oval
_DAG_RIM = 16                                  # pewter case band width
_DAG_SLIP = (508, 86, 766, 394)                # the caption slip
_DAG_TARNISH_START = 0.80                      # radial fraction where tarnish begins
_DAG_GOLD_RED = 0.375                          # Y+R 5/8:3/8 — the documented gold


def _daguerreotype_oval_radial(x: float, y: float) -> float:
    """Normalised radial position inside the oval window: 0 centre, 1 rim."""
    x0, y0, x1, y1 = _DAG_OVAL
    nx = (x - (x0 + x1) / 2) / ((x1 - x0) / 2)
    ny = (y - (y0 + y1) / 2) / ((y1 - y0) / 2)
    return math.hypot(nx, ny)


def _daguerreotype_paint_mat(image: Image.Image) -> None:
    """The case: brass mat field (Y+R gold) inside a pewter rim (the K+W
    50/50 checkerboard, which reads as brushed metal next to the brass)."""
    px = pixel_access(image)
    yellow, red, white, black = (SPECTRA6[c] for c in ("yellow", "red", "white", "black"))
    gold_cut = 64 * _DAG_GOLD_RED
    for y in range(480):
        row = BAYER_8x8[y % 8]
        for x in range(800):
            if x < _DAG_RIM or y < _DAG_RIM or x >= 800 - _DAG_RIM or y >= 480 - _DAG_RIM:
                px[x, y] = white if (x + y) & 1 else black
            else:
                px[x, y] = red if row[x % 8] < gold_cut else yellow
    draw = ImageDraw.Draw(image)
    draw.rectangle((_DAG_RIM, _DAG_RIM, 799 - _DAG_RIM, 479 - _DAG_RIM),
                   outline=black, width=1)


def _daguerreotype_paint_plate(image: Image.Image) -> None:
    """The silver image: the committed landscape, Atkinson-dithered W/K,
    clipped to the oval window."""
    x0, y0, x1, y1 = _DAG_OVAL
    ow, oh = x1 - x0, y1 - y0
    plate = _load_dithered_plate(DAGUERREOTYPE_PLATE, ow, oh,
                                 method="atkinson", palette=_SILVER_PALETTE)
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
    """The mat's pressed double ring: ``paint_relief_mask``'s second consumer,
    embossing brass around the window under the shared upper-left light."""
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


def _daguerreotype_paint_slip(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The caption slip: cream stock lifted on a shadow ledge, the quote in
    Libre Caslon with the matched phrase in the studio's red ink."""
    x0, y0, x1, y1 = _DAG_SLIP
    black = SPECTRA6["black"]
    paint_mount_card(image, draw, _DAG_SLIP, ledge=3)

    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    quote_font, quote_font_bold, wrapped, line_height, _ = fit_quote(
        draw, display_quote, quote_row.get("matched_text") or "",
        x1 - x0 - 36, y1 - y0 - 88, font_max=26, font_min=14,
        line_height_mult=1.32, theme="daguerreotype",
    )
    draw_centred_styled_lines(
        draw, wrapped, x0=x0, x1=x1, top=y0 + 26, line_height=line_height,
        regular=quote_font, bold=quote_font_bold,
        fill=black, accent=SPECTRA6["red"],
    )
    draw_truncated_centred_byline(
        draw, quote_row, centre=(x0 + x1) // 2, baseline=y1 - 20,
        max_width=x1 - x0 - 30, fill=black,
        font=load_font(theme_font_candidates("daguerreotype", "quote_regular"), size=13),
    )


def render_daguerreotype_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A cased daguerreotype (see the section comment).

    Composed at 800x480 and NEAREST-downsampled otherwise (the ``metro``
    convention): the case geometry is absolute, and interpolation would
    average the silver stipple into greys the panel cannot print.
    """
    del time_str  # see the section comment; deliberately unused.
    image = Image.new("RGB", (800, 480), color=SPECTRA6["white"])
    _daguerreotype_paint_mat(image)
    _daguerreotype_paint_plate(image)
    _daguerreotype_paint_tarnish(image)
    _daguerreotype_paint_ring(image)
    draw = ImageDraw.Draw(image)
    _daguerreotype_paint_slip(image, draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("daguerreotype",), render=render_daguerreotype_frame)
