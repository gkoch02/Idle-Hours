"""The ``pulp`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from .._paths import ALFA_SLAB_ONE, META_FONT_BOLD_CANDIDATES, QUOTE_FONT_BOLD_CANDIDATES, SPACEMONO_BOLD
from ..fonts import _font_ascent, load_font, normalize_dashes
from ..furniture import _paint_placed, _place_lines
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, pixel_access, snap_image_to_palette
from ..spec import FrameSpec
from ._shared import _TAROT_ROMAN_NUMERALS

# ---------------------------------------------------------------------------
# pulp — a 1940s lurid paperback front (issue #214).
#
# A *cover*, not a ``comic`` panel: masthead strip, huge title, corner banner,
# price flash and blurb on a saturated yellow ground.
#
# **Misregistration:** ``_pulp_misregistered_text`` paints a red plate at an
# offset under the black one, leaving a red fringe on heavy elements. It needs
# a *fat* face — on a hairline serif the fringe eats the letterform.
#
# The time rides the **issue line**, ``VOL. XII · NO. 30`` (hour as a Roman
# volume, minute as the issue number). It is the most direct time surface in
# the rotation, accepted because a volume/number line is required furniture on
# this object and reads as a serial. The quote still carries the time.
#
# Composition, top to bottom: red masthead (imprint + issue line); the book's
# title, uppercased and fitted; an all-caps byline; the quote as the blurb on
# a knocked-out white band (black on saturated yellow is illegible at
# distance); a starburst price flash; and an angled COMPLETE NOVEL banner.
# ---------------------------------------------------------------------------
_PULP_MASTHEAD_H = 46
_PULP_TITLE_TOP = 58
_PULP_BLURB_RECT = (54, 176, 746, 380)
_PULP_PLATE_OFFSET = (3, 2)    # how far the red plate missed the black one
_PULP_IMPRINT = "IDLE HOURS"
_PULP_BANNER_TEXT = "COMPLETE NOVEL"
_PULP_PRICE = "25¢"
# Centre of the diagonal corner flash: far enough in that the text stays on
# canvas, low enough to clear the blurb band.
_PULP_BANNER_CENTRE = (104, 420)
_PULP_BANNER_SIZE = (186, 30)


def _pulp_issue_line(time_str: str) -> str:
    """``VOL. <roman hour> · NO. <minute>`` — the cover's serial, and the clock."""
    try:
        hour, minute = (int(part) for part in time_str.split(":")[:2])
    except (ValueError, AttributeError):
        hour, minute = 12, 0
    roman = _TAROT_ROMAN_NUMERALS[(hour % 12) or 12]
    return f"VOL. {roman}  ·  NO. {minute:02d}"


def _pulp_misregistered_text(image, draw, xy, text, font, *, anchor=None, offset=None):
    """Paint ``text`` as a black plate with the red plate landing off-register.

    Red goes down first at an offset and black covers most of it, leaving a
    fringe on two edges. Red drawn *after* black would read as a drop shadow.
    """
    dx, dy = offset or _PULP_PLATE_OFFSET
    x, y = xy
    draw.text((x + dx, y + dy), text, font=font, fill=SPECTRA6["red"], anchor=anchor)
    draw.text((x, y), text, font=font, fill=SPECTRA6["black"], anchor=anchor)
    del image


def _pulp_paint_stock(image) -> None:
    """A coarse black screen over the yellow — cheap paper, cheaply printed.

    One dot per 4x4 tile (6.25%): reads as texture without shifting the hue.
    Not a red screen — red over yellow is the R+Y tangerine recipe and would
    change the ground colour rather than dirty it.
    """
    width, height = image.size
    px = pixel_access(image)
    yellow, black = SPECTRA6["yellow"], SPECTRA6["black"]
    for y in range(height):
        if y % 4 != 1:
            continue
        for x in range(1, width, 4):
            if px[x, y] == yellow:
                px[x, y] = black


def _pulp_paint_masthead(image, draw, width, time_str):
    """Red strip across the head: imprint on the left, issue line on the right."""
    red, black, yellow = SPECTRA6["red"], SPECTRA6["black"], SPECTRA6["yellow"]
    draw.rectangle((0, 0, width, _PULP_MASTHEAD_H), fill=red)
    draw.rectangle((0, _PULP_MASTHEAD_H - 4, width, _PULP_MASTHEAD_H), fill=black)
    imprint = load_font([(ALFA_SLAB_ONE, None), *QUOTE_FONT_BOLD_CANDIDATES], size=25)
    serial = load_font([SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=15)
    draw.text((18, _PULP_MASTHEAD_H // 2 - 3), _PULP_IMPRINT, font=imprint, fill=yellow, anchor="lm")
    draw.text((width - 18, _PULP_MASTHEAD_H // 2 - 3), _pulp_issue_line(time_str),
              font=serial, fill=yellow, anchor="rm")


def _pulp_fit_title(draw, title, width):
    """Largest Alfa Slab One size whose uppercased title fits, wrapping to two.

    Shrunk aggressively before it may wrap, and never past two lines — more
    reads as a paragraph, not a cover title.
    """
    text = (title or "").strip().upper() or _PULP_IMPRINT
    budget = width - 72
    for size in range(64, 25, -3):
        font = load_font([(ALFA_SLAB_ONE, None), *QUOTE_FONT_BOLD_CANDIDATES], size=size)
        if draw.textlength(text, font=font) <= budget:
            return font, [text]
    # Still too wide at the floor: break at the space nearest the midpoint.
    words = text.split()
    if len(words) > 1:
        best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(text) // 2))
        pair = [" ".join(words[:best]), " ".join(words[best:])]
        for size in range(48, 19, -3):
            font = load_font([(ALFA_SLAB_ONE, None), *QUOTE_FONT_BOLD_CANDIDATES], size=size)
            if max(draw.textlength(line, font=font) for line in pair) <= budget:
                return font, pair
        return load_font([(ALFA_SLAB_ONE, None), *QUOTE_FONT_BOLD_CANDIDATES], size=20), pair
    return load_font([(ALFA_SLAB_ONE, None), *QUOTE_FONT_BOLD_CANDIDATES], size=26), [text]


def _pulp_paint_title(image, draw, quote_row, width):
    """Cover title (the book) plus an all-caps byline. Returns the next free y."""
    title = (quote_row.get("title") or "").strip() or (quote_row.get("author") or "").strip()
    font, lines = _pulp_fit_title(draw, title, width)
    ascent = _font_ascent(font)
    y = _PULP_TITLE_TOP
    for line in lines:
        _pulp_misregistered_text(image, draw, (width // 2, y), line, font, anchor="ma")
        y += int(ascent * 1.02)
    author = (quote_row.get("author") or "").strip()
    if author:
        byline_font = load_font([SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=16)
        text = f"BY {author.upper()}"
        while text and draw.textlength(text, font=byline_font) > width - 80:
            text = text[:-1]
        draw.text((width // 2, y + 6), text, font=byline_font, fill=SPECTRA6["black"], anchor="ma")
        y += 30
    return y


def _pulp_paint_blurb(image, draw, quote_row, rect):
    """The quote as the cover blurb, on a knocked-out white band.

    Black on saturated yellow is illegible at distance, so the band is wiped
    to white and given a heavy black rule.
    """
    x0, y0, x1, y1 = rect
    white, black, red = SPECTRA6["white"], SPECTRA6["black"], SPECTRA6["red"]
    draw.rectangle((x0, y0, x1, y1), fill=white, outline=black, width=3)
    inner = (x0 + 18, y0 + 14, x1 - 18, y1 - 14)
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    matched = quote_row.get("matched_text") or ""
    quote_font, quote_font_bold, wrapped, line_height, _ = fit_quote(
        draw, display_quote, matched, inner[2] - inner[0], inner[3] - inner[1],
        font_max=27, font_min=12, line_height_mult=1.16, theme="pulp",
    )
    block_h = len(wrapped) * line_height
    y = inner[1] + max(0, ((inner[3] - inner[1]) - block_h) // 2)
    for line in _place_lines(draw, wrapped, x0=inner[0], width=inner[2] - inner[0], top=y,
                             line_height=line_height, regular=quote_font, bold=quote_font_bold):
        _paint_placed(draw, line, black, red)


def _pulp_paint_price_flash(image, draw, width, height):
    """A starburst price badge — the coin-price flash every cover carried."""
    red, black, yellow = SPECTRA6["red"], SPECTRA6["black"], SPECTRA6["yellow"]
    cx, cy, r = width - 72, height - 56, 44
    points = []
    for i in range(24):
        angle = math.pi * 2 * i / 24
        radius = r if i % 2 == 0 else r * 0.72
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    draw.polygon(points, fill=red, outline=black)
    font = load_font([(ALFA_SLAB_ONE, None), *QUOTE_FONT_BOLD_CANDIDATES], size=20)
    draw.text((cx, cy), _PULP_PRICE, font=font, fill=yellow, anchor="mm")


def _pulp_paint_corner_banner(image, draw, width, height):
    """The angled flag across the bottom-left corner.

    Drawn on its own tile and rotated 45°, since PIL cannot set rotated text.
    """
    red, yellow, black = SPECTRA6["red"], SPECTRA6["yellow"], SPECTRA6["black"]
    band_w, band_h = _PULP_BANNER_SIZE
    # Built RGBA and pasted through its own alpha so the rotation's corner fill
    # stays transparent.
    tile = Image.new("RGBA", (band_w, band_h), red + (255,))
    tdraw = ImageDraw.Draw(tile)
    tdraw.rectangle((0, 0, band_w - 1, band_h - 1), outline=black + (255,), width=2)
    font = load_font([SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=13)
    text = _PULP_BANNER_TEXT
    while len(text) > 1 and tdraw.textlength(text, font=font) > band_w - 14:
        text = text[:-1]
    tdraw.text((band_w // 2, band_h // 2), text, font=font, fill=yellow + (255,), anchor="mm")
    # BICUBIC, not NEAREST: NEAREST shreds 13 px glyph stems. The alpha is then
    # hard-thresholded so the band's edges stay crisp instead of leaving an
    # off-palette fringe against the yellow.
    rotated = tile.rotate(45, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0))
    mask = rotated.split()[3].point(lambda v: 255 if v > 127 else 0)
    cx, cy = _PULP_BANNER_CENTRE
    cx = min(cx, max(0, width - 40))
    cy = min(cy, max(0, height - 40))
    image.paste(rotated.convert("RGB"), (cx - rotated.size[0] // 2, cy - rotated.size[1] // 2), mask)
    tile.close()
    rotated.close()


def render_pulp_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A 1940s lurid paperback front (see the module section comment above)."""
    image = Image.new("RGB", (width, height), color=SPECTRA6["yellow"])
    _pulp_paint_stock(image)
    draw = ImageDraw.Draw(image)
    _pulp_paint_masthead(image, draw, width, time_str)
    _pulp_paint_title(image, draw, quote_row, width)
    blurb = (
        max(8, min(_PULP_BLURB_RECT[0], width - 24)),
        max(8, min(_PULP_BLURB_RECT[1], height - 24)),
        max(16, min(_PULP_BLURB_RECT[2], width - 8)),
        max(24, min(_PULP_BLURB_RECT[3], height - 8)),
    )
    if blurb[2] > blurb[0] + 20 and blurb[3] > blurb[1] + 20:
        _pulp_paint_blurb(image, draw, quote_row, blurb)
    _pulp_paint_corner_banner(image, draw, width, height)
    _pulp_paint_price_flash(image, draw, width, height)
    return snap_image_to_palette(image, SPECTRA6_PALETTE)


SPEC = FrameSpec(themes=("pulp",), render=render_pulp_frame)
