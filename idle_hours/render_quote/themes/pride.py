"""The ``pride`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import bisect
import math

from PIL import Image, ImageDraw

from ..fonts import _font_ascent, load_font, normalize_dashes, theme_font_candidates
from ..furniture import fallback_title
from ..layout import _trim_line, fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, pixel_access, snap_image_to_palette
from ..spec import FrameSpec
from ..text import draw_text_dithered

# ---------------------------------------------------------------------------
# pride — the Progress Pride flag, flying.
#
# Eleven bands, all on-palette: native red / yellow / green / blue / white /
# black, plus documented two-ink recipes for orange (R+Y 5/8:3/8), violet
# (R+B 1:1), pink (R+W), light blue (B+W 1:1) and brown (R+G 1:1).
#
# The cloth is *lit*: a low-density white overlay on faces turned toward the
# light and a black one on faces turned away, riding the wave that displaces
# the stripes. Two constraints:
#
#   1. **Displacement and shading are 90 degrees apart.** The stripes displace
#      by the height field ``h``; the light sees the tilt ``dh/dx``. Shading the
#      crest instead of the slope reads as a corrugated roof, which is why
#      ``_pride_wave`` returns both from one pass.
#   2. **One sine reads as corrugation.** Two incommensurate frequencies
#      billow; the phases drift with ``y`` so the folds lean.
#
# The stripe lookup is clamped, so the frame reads as a crop of a larger flag.
# The chevron is resolved against the same wave-displaced row, so it rides the
# cloth rather than sitting on it like a decal.
#
# The quote sits in a white cartouche with a black drop-shadow ledge, in the
# rainbow field RIGHT of the chevron's point (a centred card would swallow the
# arrow). Body type is Jost; the matched phrase is in the flag's own violet.
# HH:MM is never shown.
#
# Deliberately *not* done: nothing encodes the hour in the bands. Their count
# and order carry meaning that is not a designer's to spend on a clock gimmick.
# ---------------------------------------------------------------------------
_PRIDE_STRIPES = 6
# (dark ink, light ink, light density) per stripe, top to bottom: red, orange,
# yellow, green, blue, violet. A ``None`` light ink means the stripe is a native
# Spectra 6 ink and paints solid.
_PRIDE_STRIPE_INKS: tuple[tuple[str, str | None, float], ...] = (
    ("red", None, 0.0),
    ("red", "yellow", 0.375),   # tangerine — the documented R+Y 5/8:3/8 recipe
    ("yellow", None, 0.0),
    ("green", None, 0.0),
    ("blue", None, 0.0),
    ("red", "blue", 0.5),       # violet — the documented R+B 1:1 recipe
)
# The Progress chevron, in the same (dark, light, light density) form, ordered
# from the innermost band outward. The order was measured off a reference image
# (published descriptions disagree); don't reorder it from memory.
#
# Brown is the R+G 1:1 sepia, which reads as true dark brown on the panel's
# muted inks (olive only in an RGB preview). It is not darkened with black:
# it sits against the black band and must stay distinguishable from it.
_PRIDE_CHEVRON_INKS: tuple[tuple[str, str | None, float], ...] = (
    ("white", None, 0.0),
    ("white", "red", 0.375),    # pink — R+W, white-dominant for the pale rose
    ("white", "blue", 0.5),     # light blue — the documented B+W 1:1 sky blue
    ("red", "green", 0.5),      # brown — the documented R+G 1:1 sepia
    ("black", None, 0.0),
)
# Depth of each chevron band's vertex as a fraction of canvas width, measured
# off the reference flag (band boundaries at 0.148 / 0.223 / 0.303 / 0.383 /
# 0.465 of the flag's width). The innermost white is a filled arrow rather than
# a band, which is why its depth is not simply one fifth.
_PRIDE_CHEVRON_DEPTHS: tuple[float, ...] = (0.148, 0.223, 0.303, 0.383, 0.465)
# The size of the flag those depths were measured from. The depths are
# fractions of WIDTH while an arm's travel is vertical, so the vertical term is
# scaled by the aspect ratio (``_pride_arm_slope``); a literal 45-degree arm at
# 800x480 would put the top-left corner in light blue instead of brown.
_PRIDE_REFERENCE_SIZE = (1008, 658)
# Clear space between the chevron's point and the quote card.
_PRIDE_FIELD_GAP = 18
# Wave terms as (amplitude px, angular frequency per px, y-lean, phase). Two
# incommensurate frequencies so the cloth billows instead of corrugating.
_PRIDE_WAVE: tuple[tuple[float, float, float, float], ...] = (
    (17.0, 0.0182, 0.0016, 0.7),
    (8.0, 0.0331, -0.0027, 2.4),
)
# Peak overlay densities for the lit and shadowed faces: well below 0.5 so the
# overlay models light on a colour rather than mixing a new one, but above ~0.2,
# below which the folds vanish at viewing distance.
_PRIDE_LIGHT_PEAK = 0.22
_PRIDE_SHADE_PEAK = 0.20
# The lighting is a *partition* of the Bayer tile, not an overlay painted over
# the stripe stipple. Any two reads of one Bayer tile are perfectly correlated,
# so pick-ink-then-overwrite skews the stripe's mix on each face of a fold (a
# hue shift masquerading as shading). Instead one read of ``BAYER_8x8`` ranks
# each pixel: the lowest ``round(density * 64)`` cells take the lighting ink and
# the rest split between the stripe's inks in its own ratio. 8x8 rather than 4x4
# because 17 levels band the folds into hard contours. A solid stripe is the
# degenerate case. ``TestPrideStripeInkRatios`` fences this.
# The card is sized to its contents, bounded by ``_PRIDE_TEXT_MAX`` and
# ``_PRIDE_CARD_MIN`` (a card much smaller than its own corner radius stops
# reading as a card). It lives right of the chevron's point, which is why the
# text maximum is narrow; the fit loop absorbs that by wrapping and shrinking.
_PRIDE_TEXT_MAX = (322, 316)
_PRIDE_CARD_MIN = (220, 120)
_PRIDE_PAD_X = 30
_PRIDE_PAD_TOP = 24
_PRIDE_PAD_BOTTOM = 20
_PRIDE_CREDIT_GAP = 16
_PRIDE_CARTOUCHE_RADIUS = 10
_PRIDE_SHADOW_OFFSET = 4
# Smallest byline the panel renders as readable text rather than a smudge.
_PRIDE_CREDIT_MIN_SIZE = 7


def _pride_wave(x: float, y: float) -> tuple[float, float]:
    """Return ``(displacement_px, tilt)`` for the cloth at ``(x, y)``.

    ``displacement`` shifts the stripe boundaries; ``tilt`` is the derivative of
    the same height field and drives the lighting, so light lands on the slopes
    of each fold, not its crest.
    """
    displacement = 0.0
    tilt = 0.0
    for amp, freq, lean, phase in _PRIDE_WAVE:
        angle = freq * x + lean * y + phase
        displacement += amp * math.sin(angle)
        tilt += amp * freq * math.cos(angle)
    return displacement, tilt


def _pride_metrics(width: int, height: int) -> dict:
    """Card geometry and type sizes for this canvas.

    The constants are native-panel (800x480) values scaled by the smaller axis
    ratio, capped at 1, so the native render is unaffected and thumbnails get a
    proportionally smaller card and type.
    """
    scale = min(1.0, width / 800.0, height / 480.0)

    def down(value: float, floor: int) -> int:
        return max(floor, round(value * scale))

    pad_x, pad_top, pad_bottom = down(_PRIDE_PAD_X, 4), down(_PRIDE_PAD_TOP, 3), down(_PRIDE_PAD_BOTTOM, 3)
    shadow = down(_PRIDE_SHADOW_OFFSET, 1)
    margin = shadow + down(4, 1)
    max_card_w = max(8, width - 2 * margin)
    max_card_h = max(8, height - 2 * margin)
    # Prefer the clear rainbow field right of the chevron; fall back to the full
    # canvas when the field is too narrow to hold a card at all.
    field_left = _pride_chevron_tip(width) + down(_PRIDE_FIELD_GAP, 2)
    card_min_w = min(down(_PRIDE_CARD_MIN[0], 40), max_card_w)
    field_w = width - margin - field_left
    if field_w >= card_min_w:
        max_card_w = min(max_card_w, field_w)
    return {
        "scale": scale,
        "pad_x": pad_x, "pad_top": pad_top, "pad_bottom": pad_bottom,
        "gap": down(_PRIDE_CREDIT_GAP, 2),
        "shadow": shadow, "radius": down(_PRIDE_CARTOUCHE_RADIUS, 0), "margin": margin,
        "field_left": field_left,
        "max_card": (max_card_w, max_card_h),
        "card_min": (card_min_w, min(down(_PRIDE_CARD_MIN[1], 30), max_card_h)),
        "text_max": (
            max(16, min(down(_PRIDE_TEXT_MAX[0], 16), max_card_w - 2 * pad_x)),
            max(16, min(down(_PRIDE_TEXT_MAX[1], 16), max_card_h - pad_top - pad_bottom)),
        ),
        "font": (max(8, down(34, 8)), max(6, down(14, 6))),
        "credits": (max(5, down(14, 5)), max(5, down(13, 5))),
        # Below this the byline is a smudge, so small thumbnails drop the
        # credits and give the quote the room.
        "show_credits": down(14, 5) >= _PRIDE_CREDIT_MIN_SIZE,
    }


def _pride_arm_slope(width: int, height: int) -> float:
    """Vertical-distance multiplier that keeps the chevron aspect-correct."""
    ref_w, ref_h = _PRIDE_REFERENCE_SIZE
    return (width / max(1, height)) * (ref_h / ref_w)


def _pride_chevron_tip(width: int) -> int:
    """x of the chevron's point — the left edge of the clear rainbow field."""
    return int(_PRIDE_CHEVRON_DEPTHS[-1] * width)


def _pride_paint_flag(image: Image.Image) -> None:
    """Paint the full-bleed waving flag: chevron over rainbow.

    Walks the canvas once, resolving each pixel to a band (via the wave-
    displaced row) and then to an ink through the three-way Bayer partition.
    The stripe index is clamped, so the frame is a crop of a larger flag.
    """
    width, height = image.size
    px = pixel_access(image)
    white = SPECTRA6["white"]
    black = SPECTRA6["black"]
    # A solid band is the degenerate partition: its "light" ink is its own ink
    # and its share is zero, so the same three-way branch below covers both.
    def _resolve(table):
        out = []
        for dark, light, density in table:
            dark_ink = SPECTRA6[dark]
            out.append((dark_ink, SPECTRA6[light] if light else dark_ink, density))
        return out

    inks = _resolve(_PRIDE_STRIPE_INKS)
    chevron = _resolve(_PRIDE_CHEVRON_INKS)
    depths = [d * width for d in _PRIDE_CHEVRON_DEPTHS]
    bands = len(depths)
    stripe_h = height / _PRIDE_STRIPES
    centre = height / 2.0
    arm_slope = _pride_arm_slope(width, height)
    # Normalise the tilt so the steepest fold reaches the configured peak
    # density rather than whatever the amplitude/frequency product happens to be.
    max_tilt = sum(amp * freq for amp, freq, _, _ in _PRIDE_WAVE) or 1.0
    tile = len(BAYER_8x8)
    scale = tile * tile
    for y in range(height):
        row = BAYER_8x8[y % tile]
        for x in range(width):
            displacement, tilt = _pride_wave(x, y)
            # The chevron is resolved against the wave-displaced row too. The
            # arms are straight, so one distance term places a pixel in the
            # whole nest of Vs; the slope carries the aspect correction.
            shifted = y - displacement
            reach = x + abs(shifted - centre) * arm_slope
            band = bisect.bisect_left(depths, reach)
            if band < bands:
                dark, light, light_density = chevron[band]
            else:
                index = int(shifted / stripe_h)
                dark, light, light_density = inks[max(0, min(_PRIDE_STRIPES - 1, index))]
            level = tilt / max_tilt
            if level >= 0.0:
                lighting, cells = white, round(level * _PRIDE_LIGHT_PEAK * scale)
            else:
                lighting, cells = black, round(-level * _PRIDE_SHADE_PEAK * scale)
            cell = row[x % tile]
            if cell < cells:
                px[x, y] = lighting
                continue
            px[x, y] = light if cell < cells + round(light_density * (scale - cells)) else dark


def _pride_layout(draw: ImageDraw.ImageDraw, quote_row: dict, width: int, height: int) -> dict:
    """Measure the quote and credits before anything is painted.

    Measured against the largest text area the card may occupy; the card is
    then cut to fit. Returns the fonts, the wrapped lines, the measured block
    size, and the rendered credit lines.
    """
    metrics = _pride_metrics(width, height)
    max_w, max_h = metrics["text_max"]
    font_max, font_min = metrics["font"]

    # Credits are measured first and the quote gets the remaining vertical
    # budget; fitting the quote first pushes the byline off a thumbnail.
    credits = []
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "")
    for text, key, size in ((author.upper(), "quote_bold", metrics["credits"][0]),
                            (title, "quote_regular", metrics["credits"][1])):
        if not text or not metrics["show_credits"]:
            continue
        font = load_font(theme_font_candidates("pride", key), size=size)
        while len(text) > 1 and draw.textlength(text, font=font) > max_w:
            text = text[:-1]
        credits.append((text, font, draw.textbbox((0, 0), text, font=font)))
    credits_h = sum(bbox[3] - bbox[1] + 5 for _, _, bbox in credits) - 5 if credits else 0

    quote_budget = max(16, max_h - (credits_h + metrics["gap"] if credits else 0))
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    matched = quote_row.get("matched_text") or ""
    quote_font, quote_font_bold, wrapped, line_height, _ = fit_quote(
        draw, display_quote, matched, max_w, quote_budget,
        font_max=font_max, font_min=font_min, line_height_mult=1.24, theme="pride",
    )
    lines = []
    block_w: float = 0
    for line in wrapped:
        drawable = _trim_line(line)
        widths = []
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            bbox = draw.textbbox((0, 0), chunk, font=font)
            widths.append(bbox[2] - bbox[0])
        block_w = max(block_w, sum(widths))
        lines.append((drawable, widths, sum(widths)))

    for _, _, bbox in credits:
        block_w = max(block_w, bbox[2] - bbox[0])

    return {
        "metrics": metrics,
        "quote_font": quote_font,
        "quote_font_bold": quote_font_bold,
        "lines": lines,
        "line_height": line_height,
        "quote_h": len(lines) * line_height,
        "credits": credits,
        "credits_h": credits_h,
        "block_w": block_w,
    }


def _pride_card_rect(layout: dict, width: int, height: int) -> tuple[int, int, int, int]:
    """Cut the card to fit the measured block, centred and clamped to canvas."""
    m = layout["metrics"]
    content_h = layout["quote_h"] + (m["gap"] + layout["credits_h"] if layout["credits"] else 0)
    card_w = max(m["card_min"][0], layout["block_w"] + 2 * m["pad_x"])
    card_h = max(m["card_min"][1], content_h + m["pad_top"] + m["pad_bottom"])
    # Backstop: the measured block can exceed its budget when even the minimum
    # font overflows.
    card_w = min(card_w, m["max_card"][0])
    card_h = min(card_h, m["max_card"][1])
    # Centre it in the rainbow field right of the chevron's point. On a canvas
    # too narrow for that the clamp wins and the card overlaps the chevron.
    right_limit = width - m["margin"] - card_w
    x0 = max(m["margin"], min(m["field_left"] + max(0, (right_limit - m["field_left"]) // 2), right_limit))
    x0 = max(0, x0)
    y0 = max(0, (height - card_h) // 2)
    return x0, y0, x0 + card_w, y0 + card_h


def _pride_paint_cartouche(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], metrics: dict) -> None:
    """Knock a white card out of the cloth, lifted off it by a shadow ledge.

    The shadow is a black rounded rectangle offset down and right; without it
    the card reads as a hole cut in the flag.
    """
    x0, y0, x1, y1 = rect
    radius = max(0, min(metrics["radius"], (x1 - x0) // 2, (y1 - y0) // 2))
    offset = metrics["shadow"]
    draw.rounded_rectangle((x0 + offset, y0 + offset, x1 + offset, y1 + offset), radius=radius, fill=SPECTRA6["black"])
    draw.rounded_rectangle(rect, radius=radius, fill=SPECTRA6["white"], outline=SPECTRA6["black"], width=1)


def _pride_paint_text(image: Image.Image, draw: ImageDraw.ImageDraw, layout: dict, rect) -> None:
    """Quote then credits on the card, the matched phrase in the flag's violet.

    The time phrase is the R+B 1:1 stipple of the flag's sixth stripe; on the
    white card an even mix holds (no blue ground to melt into).
    """
    black = SPECTRA6["black"]
    red = SPECTRA6["red"]
    blue = SPECTRA6["blue"]
    m = layout["metrics"]
    x0, y0, x1, y1 = rect
    inner_w = x1 - x0
    content_h = layout["quote_h"] + (m["gap"] + layout["credits_h"] if layout["credits"] else 0)
    y = y0 + max(m["pad_top"], ((y1 - y0) - content_h) // 2)
    ascent = _font_ascent(layout["quote_font"])
    for drawable, widths, line_w in layout["lines"]:
        x = x0 + (inner_w - line_w) // 2
        for (chunk, is_bold), chunk_w in zip(drawable, widths, strict=True):
            font = layout["quote_font_bold"] if is_bold else layout["quote_font"]
            chunk_y = y + (ascent - _font_ascent(font))
            if is_bold and chunk.strip():
                draw_text_dithered(image, (x, chunk_y), chunk, font, dark=red, light=blue)
            else:
                draw.text((x, chunk_y), chunk, font=font, fill=black)
            x += chunk_w
        y += layout["line_height"]
    if not layout["credits"]:
        return
    y += m["gap"]
    for text, font, bbox in layout["credits"]:
        x = x0 + (inner_w - (bbox[2] - bbox[0])) // 2 - bbox[0]
        draw.text((x, y - bbox[1]), text, font=font, fill=black)
        y += (bbox[3] - bbox[1]) + 5


def render_pride_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The Progress Pride flag, flying (see the module section comment above).

    ``time_str`` is unused (the matched phrase carries the time); kept for
    dispatch-signature uniformity.
    """
    del time_str
    image = Image.new("RGB", (width, height), color=SPECTRA6["white"])
    _pride_paint_flag(image)
    draw = ImageDraw.Draw(image)
    layout = _pride_layout(draw, quote_row, width, height)
    rect = _pride_card_rect(layout, width, height)
    _pride_paint_cartouche(draw, rect, layout["metrics"])
    pad_x = layout["metrics"]["pad_x"]
    inner = (rect[0] + pad_x, rect[1], rect[2] - pad_x, rect[3])
    _pride_paint_text(image, draw, layout, inner)
    return snap_image_to_palette(image, SPECTRA6_PALETTE)


SPEC = FrameSpec(themes=("pride",), render=render_pride_frame)
