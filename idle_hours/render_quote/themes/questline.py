"""The ``questline`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from ..fonts import _font_ascent, load_font, normalize_dashes, theme_font_candidates
from ..furniture import _fit_from_title
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, snap_image_to_palette
from ..primitives import _fill_swatch_stipple
from ..spec import FrameSpec

# ─── questline (pixel RPG dialogue) ──────────────────────────────────────────
#
# An 8/16-bit JRPG presents the quote as NPC dialogue: dithered sky over green
# hills, a hero sprite, sun and clouds, and a bordered dialogue box. The author
# is the speaker on the nameplate, the matched phrase glows yellow, a static ▼
# arrow sits in the corner, and the title runs along the bottom. HH:MM is never
# shown — the matched phrase carries the time.

# 8-wide × 10-tall pixel hero: red cap, white face, blue tunic, black boots.
# Painted as scale×scale blocks; '.' is transparent.
_QUESTLINE_HERO = (
    "..KKKK..",
    ".KRRRRK.",
    ".KWWWWK.",
    ".KWKKWK.",
    ".KWWWWK.",
    ".WBBBBW.",
    ".WBBBBW.",
    ".KBBBBK.",
    ".KB..BK.",
    ".KK..KK.",
)
_QUESTLINE_SPRITE_PALETTE = {
    "K": SPECTRA6["black"],
    "W": SPECTRA6["white"],
    "R": SPECTRA6["red"],
    "B": SPECTRA6["blue"],
    "G": SPECTRA6["green"],
    "Y": SPECTRA6["yellow"],
}

# Vertical bands of the scene (y, 800×480 canvas). The sky/hills are kept
# compact up top so the dialogue box can own the taller lower ~50% — more room
# for a larger, more legible font.
_QUESTLINE_SKY_BOTTOM = 168
_QUESTLINE_HILL_BOTTOM = 224
_QUESTLINE_BOX = (22, 230, 778, 470)  # x0, y0, x1, y1


def _questline_paint_sky(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """Sky-blue (B+W) wash over green hills, with a yellow sun + white clouds.

    The B+W checkerboard reads as a soft daytime sky where solid blue would be
    flat and saturated; the hills carry a forest-green (G+K) lower lip.
    """
    width = image.size[0]
    WHITE = SPECTRA6["white"]
    YELLOW = SPECTRA6["yellow"]
    GREEN = SPECTRA6["green"]
    BLACK = SPECTRA6["black"]
    BLUE = SPECTRA6["blue"]
    # Sky: sky-blue B+W checkerboard.
    _fill_swatch_stipple(image, (0, 0, width, _QUESTLINE_SKY_BOTTOM), dark=BLUE, light=WHITE, light_density=0.5)
    # Hills: solid green, with a forest-green (G+K) lower strip for depth.
    draw.rectangle((0, _QUESTLINE_SKY_BOTTOM, width, _QUESTLINE_HILL_BOTTOM), fill=GREEN)
    _fill_swatch_stipple(
        image, (0, _QUESTLINE_HILL_BOTTOM - 10, width, _QUESTLINE_HILL_BOTTOM),
        dark=GREEN, light=BLACK, light_density=0.5,
    )
    # Sun: yellow disc top-right with eight short rays.
    sun_cx, sun_cy, sun_r = 690, 72, 34
    for k in range(8):
        ang = math.radians(k * 45)
        x0 = sun_cx + int(math.cos(ang) * (sun_r + 6))
        y0 = sun_cy + int(math.sin(ang) * (sun_r + 6))
        x1 = sun_cx + int(math.cos(ang) * (sun_r + 18))
        y1 = sun_cy + int(math.sin(ang) * (sun_r + 18))
        draw.line((x0, y0, x1, y1), fill=YELLOW, width=4)
    draw.ellipse((sun_cx - sun_r, sun_cy - sun_r, sun_cx + sun_r, sun_cy + sun_r), fill=YELLOW)
    # Two white pixel clouds (clusters of overlapping discs).
    for (cx, cy, s) in ((150, 60, 1.0), (340, 110, 0.8)):
        for (dx, dy, r) in ((-28, 6, 16), (-8, -6, 22), (16, 2, 18), (34, 8, 14)):
            draw.ellipse(
                (cx + int(dx * s) - int(r * s), cy + int(dy * s) - int(r * s),
                 cx + int(dx * s) + int(r * s), cy + int(dy * s) + int(r * s)),
                fill=WHITE,
            )


def _questline_paint_sprite(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """The hero sprite standing on the hills, right of the dialogue nameplate."""
    scale = 7
    sprite_h = len(_QUESTLINE_HERO) * scale
    x0 = 656
    y0 = _QUESTLINE_HILL_BOTTOM - sprite_h  # feet rest on the hill line
    for ry, row in enumerate(_QUESTLINE_HERO):
        for rx, ch in enumerate(row):
            color = _QUESTLINE_SPRITE_PALETTE.get(ch)
            if color is None:
                continue
            px = x0 + rx * scale
            py = y0 + ry * scale
            draw.rectangle((px, py, px + scale - 1, py + scale - 1), fill=color)


def _questline_paint_box(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """Navy dialogue box with a white double pixel frame (square corners)."""
    x0, y0, x1, y1 = _QUESTLINE_BOX
    WHITE = SPECTRA6["white"]
    BLUE = SPECTRA6["blue"]
    BLACK = SPECTRA6["black"]
    # Navy fill (blue + black checkerboard) — deep dialogue-box blue.
    _fill_swatch_stipple(image, (x0, y0, x1 + 1, y1 + 1), dark=BLUE, light=BLACK, light_density=0.5)
    # White outer frame, 4 px thick.
    for i in range(4):
        draw.rectangle((x0 + i, y0 + i, x1 - i, y1 - i), outline=WHITE)
    # White inner rule, inset to leave a navy gap → classic double border.
    draw.rectangle((x0 + 10, y0 + 10, x1 - 10, y1 - 10), outline=WHITE)
    draw.rectangle((x0 + 11, y0 + 10, x1 - 11, y1 - 10), outline=WHITE)


def _questline_paint_nameplate(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """Speaker nameplate tab straddling the box top-left: the author's name.

    Falls back to "NARRATOR" when the row has no author, and truncates long
    names so the tab stays clear of the hero sprite.
    """
    WHITE = SPECTRA6["white"]
    YELLOW = SPECTRA6["yellow"]
    BLUE = SPECTRA6["blue"]
    BLACK = SPECTRA6["black"]
    author = (quote_row.get("author") or "").strip()
    name = (author or "NARRATOR").upper()
    if len(name) > 22:
        name = name[:21] + "…"
    font = load_font(theme_font_candidates("questline", "quote_bold"), size=11)
    bbox = draw.textbbox((0, 0), name, font=font)
    text_w = bbox[2] - bbox[0]
    pad_x, pad_y = 12, 7
    box_x0, box_y0 = _QUESTLINE_BOX[0] + 18, _QUESTLINE_BOX[1] - 26
    plate = (box_x0, box_y0, box_x0 + text_w + pad_x * 2, box_y0 + (bbox[3] - bbox[1]) + pad_y * 2)
    _fill_swatch_stipple(image, (plate[0], plate[1], plate[2] + 1, plate[3] + 1), dark=BLUE, light=BLACK, light_density=0.5)
    for i in range(3):
        draw.rectangle((plate[0] + i, plate[1] + i, plate[2] - i, plate[3] - i), outline=WHITE)
    draw.text((plate[0] + pad_x - bbox[0], plate[1] + pad_y - bbox[1]), name, font=font, fill=YELLOW)


def _questline_paint_dialogue(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict, rect: tuple[int, int, int, int]) -> None:
    """The quote as left-aligned NPC speech: white body, yellow matched phrase.

    Uses the shared ``fit_quote`` / ``wrap_styled_text`` pipeline so a dense
    quote shrinks to fit the box. Left-aligned (not centred) so it reads as
    dialogue. Press Start 2P reports descent 0, so a generous line-height
    multiplier supplies the inter-line gap the bitmap cell omits.
    """
    WHITE = SPECTRA6["white"]
    YELLOW = SPECTRA6["yellow"]
    x0, y0, x1, y1 = rect
    box_w = x1 - x0
    box_h = y1 - y0
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    matched = quote_row.get("matched_text") or ""
    quote_font, quote_font_bold, wrapped_quote, line_height, _ = fit_quote(
        draw, display_quote, matched, box_w, box_h,
        font_max=40, font_min=10, line_height_mult=1.6, theme="questline",
    )
    body_ascent = _font_ascent(quote_font)
    y = y0
    for line in wrapped_quote:
        start = 0
        while start < len(line) and line[start][0].strip() == "":
            start += 1
        end = len(line)
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        x = x0
        for chunk, is_bold in line[start:end]:
            font = quote_font_bold if is_bold else quote_font
            chunk_y = y + (body_ascent - _font_ascent(font))
            draw.text((x, chunk_y), chunk, font=font, fill=YELLOW if is_bold else WHITE)
            bbox = draw.textbbox((0, 0), chunk, font=font)
            x += bbox[2] - bbox[0]
        y += line_height


def _questline_paint_arrow(draw: ImageDraw.ImageDraw) -> None:
    """Static ▼ 'press to continue' arrow in the box's bottom-right corner."""
    WHITE = SPECTRA6["white"]
    x1, y1 = _QUESTLINE_BOX[2], _QUESTLINE_BOX[3]
    cx, cy = x1 - 30, y1 - 26
    draw.polygon([(cx - 9, cy - 6), (cx + 9, cy - 6), (cx, cy + 8)], fill=WHITE)


def _questline_paint_footer(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """'— from {Title} —' along the box's bottom inner margin, centred."""
    WHITE = SPECTRA6["white"]
    font = load_font(theme_font_candidates("questline", "quote_regular"), size=8)
    # Keep the footer clear of the continue arrow on the right.
    text = _fit_from_title(draw, quote_row, font, (_QUESTLINE_BOX[2] - _QUESTLINE_BOX[0]) - 120)
    if text is None:
        return
    bbox = draw.textbbox((0, 0), text, font=font)
    cx = (_QUESTLINE_BOX[0] + _QUESTLINE_BOX[2]) // 2
    fx = cx - (bbox[2] - bbox[0]) // 2 - bbox[0]
    fy = _QUESTLINE_BOX[3] - 22 - bbox[1]
    draw.text((fx, fy), text, font=font, fill=WHITE)


def render_questline_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Pixel RPG dialogue scene (see the module section comment above).

    ``time_str`` is unused (the matched phrase carries the time); kept for
    dispatch-signature uniformity.
    """
    del time_str  # see docstring; deliberately unused.
    image = Image.new("RGB", (width, height), color=SPECTRA6["black"])
    draw = ImageDraw.Draw(image)
    _questline_paint_sky(image, draw)
    _questline_paint_sprite(image, draw)
    _questline_paint_box(image, draw)
    _questline_paint_nameplate(image, draw, quote_row)
    # Body text rect: inside the double frame, clear of the nameplate (top) and
    # the footer / continue arrow (bottom).
    bx0, by0, bx1, by1 = _QUESTLINE_BOX
    _questline_paint_dialogue(image, draw, quote_row, (bx0 + 34, by0 + 28, bx1 - 34, by1 - 40))
    _questline_paint_arrow(draw)
    _questline_paint_footer(image, draw, quote_row)
    return snap_image_to_palette(image, SPECTRA6_PALETTE)


SPEC = FrameSpec(themes=("questline",), render=render_questline_frame)
