"""The ``izakaya`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from .._paths import ORNAMENT_FONT_CANDIDATES, YUJI_BOKU_REGULAR
from ..fonts import load_font, theme_font_candidates
from ..furniture import _clock_hour12, fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_4x4, snap_image_to_palette
from ..primitives import paint_neon_mask, wrap_quote_into_masks
from ..spec import FrameSpec

# ─── izakaya (neon alley at night) ───────────────────────────────────────────
#
# A Kabukichō / Golden Gai back alley after rain: vertical shop signs glowing
# down both margins, paper lanterns above, the quote as neon tube lettering,
# and wet asphalt throwing every sign back as a vertical smear. Every glow goes
# through ``paint_neon_mask`` (one ink at a falling density).
#
# Ink use:
#   black       the alley itself.
#   blue        the night haze above the roofline, and the body text's bloom.
#   white       the neon tube cores (the glass is the brightest thing in a sign).
#   yellow      the matched phrase's tube core.
#   red         the matched phrase's bloom, the paper lanterns, and two signs.
#   green       two more sign columns.
#
# The hour rides the main lantern as a kanji numeral (一 … 十二), so
# ``time_str`` is used; the matched phrase still carries the readable time.
# Sign words are ordinary alley signage set in Yuji Boku. Deliberately
# kanji-only: katakana would want ー rotated in vertical setting.

_IZAKAYA_SIGN_W = 58
_IZAKAYA_SIGN_COLUMNS = (10, 732)     # left / right sign-board x origins
_IZAKAYA_SIGN_TOP = 34
_IZAKAYA_SIGN_H = 92
_IZAKAYA_SIGN_GAP = 18
_IZAKAYA_STREET_Y = 360               # wet asphalt begins here (below a kerb gap);
                                      # deep so reflections read as smears, not bars
_IZAKAYA_QUOTE_RECT = (108, 146, 692, 316)
_IZAKAYA_HAZE_BOTTOM = 210            # night-haze wash fades out by this row
# (word, glow ink). Six boards, three per side, cycling the chroma inks.
_IZAKAYA_SIGNS = (
    ("居酒屋", "red"),
    ("焼鳥", "green"),
    ("酒", "yellow"),
    ("横丁", "blue"),
    ("喫茶", "green"),
    ("営業中", "red"),
)
_IZAKAYA_HOUR_KANJI = {
    1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六",
    7: "七", 8: "八", 9: "九", 10: "十", 11: "十一", 12: "十二",
}
_IZAKAYA_LANTERNS = ((168, 74, 26, 34), (632, 80, 24, 31))  # (cx, cy, rx, ry) side pair
_IZAKAYA_MAIN_LANTERN = (400, 84, 33, 45)


def _izakaya_ground() -> frozenset:
    """Pixels a bloom is allowed to overwrite: the night ground and its haze.

    Passed as ``paint_neon_mask(ground=...)`` so a later glow cannot eat the
    cores, frames and ribs an earlier pass painted.
    """
    return frozenset({SPECTRA6["black"], SPECTRA6["blue"]})


def _izakaya_paint_night(image: Image.Image) -> None:
    """Black alley under a blue night haze that thins toward the roofline.

    A gradient Bayer wash, densest at the top and gone by
    ``_IZAKAYA_HAZE_BOTTOM``. Kept faint (peak ~2.2/16 ≈ 14%) so the sky never
    outshines the neon. The threshold stays a float: rounding it to an int
    bands the ramp into visible steps.
    """
    px = image.load()
    width, height = image.size
    span = max(1, _IZAKAYA_HAZE_BOTTOM)
    for y in range(min(height, _IZAKAYA_HAZE_BOTTOM)):
        threshold = 2.2 * (1.0 - y / span)
        if threshold <= 0:
            continue
        row = BAYER_4x4[y % 4]
        for x in range(width):
            if row[x % 4] < threshold:
                px[x, y] = SPECTRA6["blue"]


def _izakaya_sign_boxes() -> list[tuple[int, int, int, int, str, str]]:
    """``(x0, y0, x1, y1, word, ink)`` for all six boards, left column first."""
    boxes = []
    for index, (word, ink) in enumerate(_IZAKAYA_SIGNS):
        column = _IZAKAYA_SIGN_COLUMNS[index // 3]
        slot = index % 3
        y0 = _IZAKAYA_SIGN_TOP + slot * (_IZAKAYA_SIGN_H + _IZAKAYA_SIGN_GAP)
        boxes.append((column, y0, column + _IZAKAYA_SIGN_W, y0 + _IZAKAYA_SIGN_H, word, ink))
    return boxes


def _izakaya_paint_signs(image: Image.Image, draw: ImageDraw.ImageDraw, boxes) -> None:
    """Vertical shop boards: a glowing frame with kanji set down the middle.

    One mask per board (frame plus characters) so outline and lettering share
    one bloom; blooming them separately double-exposes where the halos meet.
    """
    ground = _izakaya_ground()
    for x0, y0, x1, y1, word, ink in boxes:
        glow = SPECTRA6[ink]
        mask = Image.new("L", image.size, 0)
        mdraw = ImageDraw.Draw(mask)
        mdraw.rectangle((x0, y0, x1, y1), outline=255, width=2)
        size = 30 if len(word) <= 2 else 24
        font = load_font([YUJI_BOKU_REGULAR, *ORNAMENT_FONT_CANDIDATES], size=size)
        step = size + 4
        cy = (y0 + y1) // 2 - (len(word) - 1) * step // 2
        for i, char in enumerate(word):
            mdraw.text(((x0 + x1) // 2, cy + i * step), char, font=font, fill=255, anchor="mm")
        # The board interior is the shop's own light box: the tube core paints
        # the frame and glyphs white, the gas colour blooms outward from both.
        paint_neon_mask(image, mask, SPECTRA6["white"], glow, radius=5, gamma=2.0, cap=0.62, ground=ground)
        del mdraw
    del draw


def _izakaya_paint_lantern(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    rx: int,
    ry: int,
    text: str | None = None,
) -> None:
    """A red paper lantern (提灯) on a cord, optionally carrying a character.

    Three passes: the silhouette blooms (``core=None``), then the red body with
    black cap, base and ribs (horizontal chords clipped to the ellipse), then
    the character.
    """
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    WHITE = SPECTRA6["white"]

    draw.line((cx, 0, cx, cy - ry - 5), fill=WHITE, width=1)

    silhouette = Image.new("L", image.size, 0)
    ImageDraw.Draw(silhouette).ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
    paint_neon_mask(image, silhouette, None, RED, radius=6, gamma=2.0, cap=0.6, ground=_izakaya_ground())

    draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=RED)
    for ry_off in range(-ry + 4, ry - 2, 6):
        half = int(rx * math.sqrt(max(0.0, 1.0 - (ry_off / float(ry)) ** 2)))
        if half > 1:
            draw.line((cx - half, cy + ry_off, cx + half, cy + ry_off), fill=BLACK, width=1)
    cap_w = int(rx * 0.55)
    draw.rectangle((cx - cap_w, cy - ry - 4, cx + cap_w, cy - ry + 1), fill=BLACK)
    draw.rectangle((cx - cap_w, cy + ry - 1, cx + cap_w, cy + ry + 4), fill=BLACK)

    if text:
        font = load_font([YUJI_BOKU_REGULAR, *ORNAMENT_FONT_CANDIDATES], size=max(12, int(ry * 0.62)))
        step = int(ry * 0.72)
        top = cy - (len(text) - 1) * step // 2
        for i, char in enumerate(text):
            draw.text((cx, top + i * step), char, font=font, fill=BLACK, anchor="mm")


def _izakaya_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> int:
    """The quote as bent neon tube. Returns the block's bottom y for the credits.

    Two masks from ``wrap_quote_into_masks``: cool white/blue for the prose,
    hot yellow/red for the matched phrase. The hot pass runs last and may
    overwrite the cool halo, so the phrase reads as nearer.
    """
    cool, hot, bottom = wrap_quote_into_masks(
        draw, image.size, quote_row, _IZAKAYA_QUOTE_RECT,
        theme="izakaya", line_height_mult=1.42,
    )
    ground = _izakaya_ground()
    paint_neon_mask(image, cool, SPECTRA6["white"], SPECTRA6["blue"], radius=6, gamma=2.0, cap=0.68, ground=ground)
    paint_neon_mask(image, hot, SPECTRA6["yellow"], SPECTRA6["red"], radius=6, gamma=1.9, cap=0.72,
                    ground=ground | {SPECTRA6["blue"]})
    return bottom


def _izakaya_paint_credits(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict, top: int) -> None:
    """author · title beneath the quote, unlit — a printed card, not a sign."""
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or fallback_title(quote_row) or "").strip()
    parts = [p for p in (author, title) if p]
    if not parts:
        return
    text = "  ·  ".join(parts)
    font = load_font(theme_font_candidates("izakaya", "quote_regular"), size=14)
    width = image.size[0]
    # Floor the budget and guard on length, not emptiness: ``text[:-2] + "…"``
    # is a fixed point at the ellipsis, which hangs a thumbnail render.
    max_w = max(40, width - 240)
    while len(text) > 1 and draw.textlength(text, font=font) > max_w:
        text = text[:-2].rstrip(" ·") + "…"
    y = min(max(top + 12, _IZAKAYA_QUOTE_RECT[3] - 4), _IZAKAYA_STREET_Y - 20)
    draw.text((width // 2, y), text, font=font, fill=SPECTRA6["white"], anchor="ma")


def _izakaya_paint_street(image: Image.Image, boxes) -> None:
    """Wet asphalt: each sign column smeared back as a rippled vertical streak.

    Each reflection inherits its board's ink and x-range, fades with depth,
    wobbles horizontally on a sine, and thins where a second sine crests. Both
    sines are phased **per column**: a shared phase breaks every column on the
    same rows, painting horizontal bands. Lanterns reflect at a lower weight.
    """
    px = image.load()
    width, height = image.size
    street = _IZAKAYA_STREET_Y
    if street >= height:
        return
    depth = max(1, height - street)

    columns = [(x0, x1, SPECTRA6[ink], 1.0) for x0, _, x1, _, _, ink in boxes]
    columns += [(cx - rx, cx + rx, SPECTRA6["red"], 0.45) for cx, _, rx, _ in _IZAKAYA_LANTERNS]
    columns.append((_IZAKAYA_MAIN_LANTERN[0] - _IZAKAYA_MAIN_LANTERN[2],
                    _IZAKAYA_MAIN_LANTERN[0] + _IZAKAYA_MAIN_LANTERN[2], SPECTRA6["red"], 0.55))

    # Faint blue sheen first, so the coloured streaks paint over it.
    for y in range(street, height):
        fade = max(0.0, (1.0 - (y - street) / depth) ** 1.6)
        sheen = 1.6 * fade
        if sheen <= 0:
            continue
        row = BAYER_4x4[y % 4]
        for x in range(width):
            if row[x % 4] < sheen and px[x, y] == SPECTRA6["black"]:
                px[x, y] = SPECTRA6["blue"]

    for index, (x0, x1, ink, weight) in enumerate(columns):
        phase = index * 1.7
        for y in range(street, height):
            fade = max(0.0, (1.0 - (y - street) / depth) ** 0.8)
            # Ripple by modulating density, not skipping rows — skipped rows
            # read as stacked horizontal bricks.
            ripple = 0.55 + 0.45 * math.sin(y * 0.42 + phase)
            threshold = 5.5 * fade * weight * ripple
            if threshold <= 0:
                continue
            # Distortion grows with depth: the near water is the most broken up.
            swing = 1.0 + 2.2 * ((y - street) / depth)
            wobble = int(round(swing * (4.0 * math.sin(y * 0.23 + phase) + 2.0 * math.sin(y * 0.61 + phase))))
            row = BAYER_4x4[y % 4]
            for x in range(max(0, x0 + wobble), min(width, x1 + wobble)):
                if row[x % 4] < threshold:
                    px[x, y] = ink


def render_izakaya_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Neon alley at night (see the module section comment above).

    Laid out against the canonical 800×480; smaller canvases (``/api/preview``
    thumbnails) crop rather than reflow. Raw pixel writes are bounds-clipped.
    """
    image = Image.new("RGB", (width, height), color=SPECTRA6["black"])
    _izakaya_paint_night(image)
    draw = ImageDraw.Draw(image)

    boxes = _izakaya_sign_boxes()
    _izakaya_paint_signs(image, draw, boxes)

    for cx, cy, rx, ry in _IZAKAYA_LANTERNS:
        _izakaya_paint_lantern(image, draw, cx, cy, rx, ry)
    mcx, mcy, mrx, mry = _IZAKAYA_MAIN_LANTERN
    _izakaya_paint_lantern(image, draw, mcx, mcy, mrx, mry, text=_IZAKAYA_HOUR_KANJI[_clock_hour12(time_str)])

    block_bottom = _izakaya_paint_quote(image, draw, quote_row)
    _izakaya_paint_credits(image, draw, quote_row, block_bottom)
    _izakaya_paint_street(image, boxes)
    return snap_image_to_palette(image, SPECTRA6_PALETTE)


SPEC = FrameSpec(themes=("izakaya",), render=render_izakaya_frame)
