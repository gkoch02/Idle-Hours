"""The ``autochrome`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .._paths import META_FONT_BOLD_CANDIDATES
from ..fonts import load_font, normalize_dashes, theme_font_candidates
from ..furniture import draw_centred_styled_lines, draw_truncated_centred_byline
from ..layout import fit_quote_balanced, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, _load_dithered_plate, snap_image_to_palette
from ..spec import FrameSpec
from ._shared import _AUTOCHROME_PALETTE, AUTOCHROME_PLATE, _autochrome_paint_garden_fallback

# ---------------------------------------------------------------------------
# autochrome — a colour transparency in its lantern-slide mask, the only plate
# dithered against the full six-ink palette. ``time_str`` is del-asserted.
# Design notes: docs/themes.md § autochrome.
_AUTOCHROME_WINDOW = (38, 30, 762, 318)         # the mask's window onto the plate
_AUTOCHROME_WINDOW_RADIUS = 9                   # the cut's rounded corners
_AUTOCHROME_PLATE_FOCUS = (0.5, 0.42)           # sky, hills and the poppy drift
_AUTOCHROME_CAPTION = (58, 332, 742, 442)       # the lettered quote under the window
_AUTOCHROME_THUMB_SPOT = (24, 456, 6)           # centre x, centre y, radius


def _autochrome_window_mask() -> Image.Image:
    x0, y0, x1, y1 = _AUTOCHROME_WINDOW
    mask = Image.new("L", (x1 - x0, y1 - y0), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, x1 - x0 - 1, y1 - y0 - 1),
                                           radius=_AUTOCHROME_WINDOW_RADIUS, fill=255)
    return mask


def _autochrome_paint_plate(image: Image.Image) -> None:
    """The transparency: the committed garden, cover-cropped to the window
    and Floyd-Steinberg-dithered against all six inks."""
    x0, y0, x1, y1 = _AUTOCHROME_WINDOW
    w, h = x1 - x0, y1 - y0
    plate = _load_dithered_plate(AUTOCHROME_PLATE, w, h, palette=_AUTOCHROME_PALETTE,
                                 focus=_AUTOCHROME_PLATE_FOCUS)
    if plate is None:
        plate = Image.new("RGB", (800, 480), SPECTRA6["white"])
        _autochrome_paint_garden_fallback(plate)
        plate = plate.crop((x0, y0, x1, y1))
    image.paste(plate, (x0, y0), _autochrome_window_mask())


def _autochrome_paint_mask(draw: ImageDraw.ImageDraw) -> None:
    """The black paper mask's furniture (the mask itself is the black canvas
    the window was pasted into): a hairline of light where the cut edge meets
    the glass, the process name printed in the top margin, and the
    thumb-spot."""
    white = SPECTRA6["white"]
    x0, y0, x1, y1 = _AUTOCHROME_WINDOW
    r = _AUTOCHROME_WINDOW_RADIUS + 3
    draw.rounded_rectangle((x0 - 3, y0 - 3, x1 + 2, y1 + 2), radius=r, outline=white, width=1)
    draw.text((400, 19), " ".join("AUTOCHROME LUMIÈRE"),
              font=load_font(META_FONT_BOLD_CANDIDATES, size=10), fill=white, anchor="ms")
    cx, cy, rad = _AUTOCHROME_THUMB_SPOT
    draw.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=white)


def _autochrome_paint_caption(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The caption lettered on the mask: Libre Caslon in white, the matched
    phrase in yellow, the byline beneath."""
    x0, y0, x1, y1 = _AUTOCHROME_CAPTION
    white = SPECTRA6["white"]
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    quote_font, quote_font_bold, wrapped, line_height, _, _ = fit_quote_balanced(
        draw, display_quote, quote_row.get("matched_text") or "",
        x1 - x0, y1 - y0, font_max=30, font_min=13,
        line_height_mult=1.28, theme="autochrome",
    )
    block_h = len(wrapped) * line_height
    draw_centred_styled_lines(
        draw, wrapped, x0=x0, x1=x1, top=y0 + max(0, (y1 - y0 - block_h) // 2),
        line_height=line_height, regular=quote_font, bold=quote_font_bold,
        fill=white, accent=SPECTRA6["yellow"], min_inset=0,
    )
    draw_truncated_centred_byline(
        draw, quote_row, centre=400, baseline=464, max_width=600, fill=white,
        font=load_font(theme_font_candidates("autochrome", "quote_regular"), size=14),
    )


def render_autochrome_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """An autochrome lantern slide (``docs/themes.md`` § autochrome)."""
    del time_str  # a photograph carries no clock; see docs/themes.md § autochrome.
    image = Image.new("RGB", (800, 480), color=SPECTRA6["black"])
    _autochrome_paint_plate(image)
    draw = ImageDraw.Draw(image)
    _autochrome_paint_mask(draw)
    _autochrome_paint_caption(draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("autochrome",), render=render_autochrome_frame)
