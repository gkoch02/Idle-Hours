"""The ``vhs`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import random

from PIL import Image, ImageDraw

from .._paths import ANTONIO_VARIABLE, META_FONT_BOLD_CANDIDATES, META_FONT_CANDIDATES, PIXELIFYSANS_VARIABLE
from ..fonts import _font_ascent, load_font, normalize_dashes
from ..furniture import _row_digest, fallback_title
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, pixel_access, snap_image_to_palette
from ..spec import FrameSpec
from ..text import draw_text_chroma_shift

# ---------------------------------------------------------------------------
# vhs — a camcorder OSD over a degraded tape (issue #211).
#
# The identity is ``draw_text_chroma_shift``: red ghost left, blue ghost right,
# white core on top, so every glyph fringes like bled composite video.
#
# Four layers of wear, all deterministic:
#
#   * **Video noise**, denser toward the foot (the head sweep).
#   * **Tracking tears** — row bands shifted sideways. A real row-shift of the
#     painted pixels, applied AFTER the text, so whatever a tear crosses comes
#     apart with it.
#   * **Scanlines**, fainter than ``nightvision``'s (tape, not a terminal).
#   * **Dropout flecks** — sparse short white dashes; more read as snow.
#
# **The time carrier is a camcorder burn-in** — the one theme where HH:MM
# digits are authentic, since a camcorder OSD is a clock. Wall time, not a
# tape-position counter.
#
# The **date** stamp is NOT today's date (that would make the frame
# clock-dependent); it is derived from the quote via ``_row_digest`` — the
# date the tape was *recorded*.
# ---------------------------------------------------------------------------
_VHS_CHROMA_OFFSET = 2
_VHS_QUOTE_RECT = (86, 96, 714, 372)
_VHS_CREDIT_GAP = 20
_VHS_NOISE_SEED = 0x5648
_VHS_NOISE_COUNT = 2600
_VHS_TEAR_SEED = 0x7EA2
_VHS_TEARS = 3
# Tear magnitude is bounded well below the body cap height so a tear looks like
# the picture slipping, not the quote being deleted.
_VHS_TEAR_BAND = (2, 8)
_VHS_TEAR_SHIFT = (5, 17)
# Head-switching noise: the torn band of static across the last few scanlines,
# where the video heads swap mid-field. Always at the very bottom, so painted
# deterministically rather than left to the random tear pool.
_VHS_HEAD_SWITCH_H = 9
_VHS_DROPOUT_COUNT = 26
_VHS_SCANLINE_STEP = 4
# Tape-recorded date pool, indexed from the quote (see the section comment).
_VHS_TAPE_YEARS = (1984, 1987, 1989, 1991, 1993, 1996, 1998)


def _vhs_tape_date(quote_row: dict) -> str:
    """``JUN 14 1991`` — the date this tape was recorded, stable per quote."""
    months = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
    seed = _row_digest(quote_row)
    year = _VHS_TAPE_YEARS[seed % len(_VHS_TAPE_YEARS)]
    month = months[(seed >> 4) % 12]
    day = 1 + (seed >> 8) % 28
    return f"{month} {day:02d} {year}"


def _vhs_paint_tape(image: Image.Image) -> None:
    """Near-black ground, scanlines, and noise rising toward the head sweep."""
    width, height = image.size
    px = pixel_access(image)
    black, blue, white = SPECTRA6["black"], SPECTRA6["blue"], SPECTRA6["white"]
    # Faint scanline modulation, softer than nightvision's.
    for y in range(0, height, _VHS_SCANLINE_STEP):
        for x in range(0, width, 2):
            px[x, y] = blue if (x + y) % 8 == 0 else black
    rng = random.Random(_VHS_NOISE_SEED)
    for _ in range(_VHS_NOISE_COUNT):
        # Bias toward the foot: two samples, keep the lower. Uniform noise
        # reads as a clean digital dither, not worn tape.
        y = max(rng.randrange(height), rng.randrange(height))
        x = rng.randrange(width)
        px[x, y] = white if rng.random() < 0.35 else blue


def _vhs_paint_dropouts(image: Image.Image) -> None:
    """Short white dashes where the oxide has shed off the tape."""
    width, height = image.size
    px = pixel_access(image)
    white = SPECTRA6["white"]
    rng = random.Random(_VHS_NOISE_SEED ^ 0xD0)
    for _ in range(_VHS_DROPOUT_COUNT):
        y = max(rng.randrange(height), rng.randrange(height))
        x = rng.randrange(max(1, width - 40))
        for dx in range(rng.randrange(6, 34)):
            if x + dx < width:
                px[x + dx, y] = white


def _vhs_apply_tears(image: Image.Image) -> None:
    """Shift bands of rows sideways — the tracking error the theme is named for.

    Applied *after* everything else, on the painted pixels, so a tear cuts
    through the quote and the OSD as well as the ground.
    """
    width, height = image.size
    px = pixel_access(image)
    black = SPECTRA6["black"]

    def shift_row(y: int, shift: int) -> None:
        row = [px[x, y] for x in range(width)]
        for x in range(width):
            src = x - shift
            px[x, y] = row[src] if 0 <= src < width else black

    rng = random.Random(_VHS_TEAR_SEED)
    for _ in range(_VHS_TEARS):
        top = rng.randrange(height)
        band = rng.randrange(*_VHS_TEAR_BAND)
        shift = rng.choice((-1, 1)) * rng.randrange(*_VHS_TEAR_SHIFT)
        for y in range(top, min(height, top + band)):
            shift_row(y, shift)

    # Head-switching noise: repaint the band as bright static first (shifting
    # the existing noise alone changes nothing visible), then tear each row by
    # a different amount.
    white, blue = SPECTRA6["white"], SPECTRA6["blue"]
    for index, y in enumerate(range(max(0, height - _VHS_HEAD_SWITCH_H), height)):
        for x in range(width):
            roll = rng.random()
            if roll < 0.34:
                px[x, y] = white
            elif roll < 0.6:
                px[x, y] = blue
            elif roll < 0.66:
                px[x, y] = black
        shift_row(y, rng.randrange(8, 30) * (1 if index % 2 else -1))


def _vhs_credit_lines(quote_row: dict) -> list[tuple[str, int]]:
    """Author + title, uppercased author first, at their chrome sizes."""
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "")
    return [(text, size) for text, size in ((author.upper(), 17), (title, 15)) if text]


def _vhs_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> int:
    """The quote as chroma-bled OSD text; returns the block's bottom edge.

    The matched phrase gets a wider chroma offset rather than a different
    colour — on tape, what stands out is what has degraded most.

    Quote and credits are centred *together* between the two OSD strips,
    which is why this returns a y rather than painting to a fixed rect.
    """
    x0, y0, x1, y1 = _VHS_QUOTE_RECT
    if x1 - x0 < 40 or y1 - y0 < 40:
        return y0
    white, red, blue = SPECTRA6["white"], SPECTRA6["red"], SPECTRA6["blue"]
    ground = frozenset({SPECTRA6["black"], blue, white, red})
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    matched = quote_row.get("matched_text") or ""

    credits = _vhs_credit_lines(quote_row)
    credit_h = sum(size + 6 for _, size in credits)
    budget = (y1 - y0) - (credit_h + _VHS_CREDIT_GAP if credits else 0)

    quote_font, quote_font_bold, wrapped, line_height, _ = fit_quote(
        draw, display_quote, matched, x1 - x0, budget,
        font_max=34, font_min=14, line_height_mult=1.26, theme="vhs",
    )
    block_h = len(wrapped) * line_height
    total = block_h + (credit_h + _VHS_CREDIT_GAP if credits else 0)
    y = y0 + max(0, ((y1 - y0) - total) // 2)
    ascent = _font_ascent(quote_font)
    for line in wrapped:
        start, end = 0, len(line)
        while start < end and line[start][0].strip() == "":
            start += 1
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        drawable = line[start:end]
        widths = []
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            box = draw.textbbox((0, 0), chunk, font=font)
            widths.append(box[2] - box[0])
        start_x = x0 + max(0, ((x1 - x0) - sum(widths)) // 2)
        # Two passes over the line: every ghost, then every core. Per-chunk
        # ghost-then-core lets the next chunk's left ghost land on the previous
        # chunk's core (from an offset of about 5), and the ``ground`` guard
        # cannot catch it since it lists the white core too.
        for pass_core in (False, True):
            x = start_x
            for (chunk, is_bold), chunk_w in zip(drawable, widths):
                font = quote_font_bold if is_bold else quote_font
                chunk_y = y + (ascent - _font_ascent(font))
                draw_text_chroma_shift(
                    image, (x, chunk_y), chunk, font,
                    core=white if pass_core else None,
                    left=None if pass_core else red,
                    right=None if pass_core else blue,
                    offset=_VHS_CHROMA_OFFSET + (1 if is_bold else 0),
                    ground=ground,
                )
                x += chunk_w
        y += line_height
    return y


def _vhs_paint_osd(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict,
                   width: int, height: int, time_str: str) -> None:
    """Camcorder chrome: REC indicator, tape date, and the time burn-in.

    Set in Pixelify Sans, a pixel face like a real OSD character generator.
    The burn-in is the theme's time carrier (a camcorder OSD is a clock).
    """
    if width < 200 or height < 120:
        return
    white, red = SPECTRA6["white"], SPECTRA6["red"]
    chrome = load_font([(PIXELIFYSANS_VARIABLE, "Bold"), *META_FONT_BOLD_CANDIDATES], size=17)
    small = load_font([(PIXELIFYSANS_VARIABLE, "Regular"), *META_FONT_CANDIDATES], size=15)
    # REC + a solid red dot, top-left.
    draw.text((30, 26), "REC", font=chrome, fill=white)
    dot = draw.textlength("REC", font=chrome)
    draw.ellipse((30 + dot + 8, 30, 30 + dot + 20, 42), fill=red)
    # SP is the standard-play tape speed every camcorder stamped in the corner.
    draw.text((width - 30, 26), "SP", font=chrome, fill=white, anchor="ra")
    draw.text((30, height - 52), _vhs_tape_date(quote_row), font=small, fill=white)
    burn = (time_str or "").strip() or "00:00"
    draw.text((width - 30, height - 54), f"{burn}:00", font=chrome, fill=white, anchor="ra")


def _vhs_paint_credits(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict,
                       width: int, top: int) -> None:
    """Author + title below the quote, bled like the body but at chrome size."""
    white, red, blue = SPECTRA6["white"], SPECTRA6["red"], SPECTRA6["blue"]
    ground = frozenset({SPECTRA6["black"], blue, white, red})
    y = top + _VHS_CREDIT_GAP
    for text, size in _vhs_credit_lines(quote_row):
        font = load_font([(ANTONIO_VARIABLE, "Bold"), *META_FONT_BOLD_CANDIDATES], size=size)
        while len(text) > 1 and draw.textlength(text, font=font) > width - 140:
            text = text[:-1]
        box = draw.textbbox((0, 0), text, font=font)
        draw_text_chroma_shift(
            image, ((width - (box[2] - box[0])) // 2 - box[0], y - box[1]), text, font,
            core=white, left=red, right=blue, offset=1, ground=ground,
        )
        y += size + 6


def render_vhs_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A camcorder OSD over a worn tape (see the module section comment above).

    Composed at the canonical 800x480 (fixed panel coordinates) and
    NEAREST-downsampled for other sizes (``metro`` convention); an
    interpolating filter would average the stipples into off-palette colours.
    """
    image = Image.new("RGB", (800, 480), color=SPECTRA6["black"])
    _vhs_paint_tape(image)
    draw = ImageDraw.Draw(image)
    block_bottom = _vhs_paint_quote(image, draw, quote_row)
    _vhs_paint_credits(image, draw, quote_row, 800, block_bottom)
    _vhs_paint_osd(image, draw, quote_row, 800, 480, time_str)
    _vhs_paint_dropouts(image)
    # Tears go last, over the finished picture — see _vhs_apply_tears.
    _vhs_apply_tears(image)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("vhs",), render=render_vhs_frame)
