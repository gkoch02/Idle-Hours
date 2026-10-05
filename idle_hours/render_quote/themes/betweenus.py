"""The ``betweenus`` and ``betweenus_dark`` themes' border painter and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import collections

from PIL import Image, ImageDraw, ImageFilter

from idle_hours.gutenberg_time_miner import daypart_for_hour

from .._paths import (
    FRAUNCES_ITALIC_VARIABLE,
    FRAUNCES_VARIABLE,
    INTER_VARIABLE,
    META_FONT_BOLD_CANDIDATES,
    META_FONT_CANDIDATES,
    QUOTE_FONT_BOLD_CANDIDATES,
    QUOTE_FONT_SEMIBOLD_CANDIDATES,
)
from ..fonts import load_font
from ..palette import SPECTRA6, BAYER_8x8, gray_pixel_access, pixel_access
from ..primitives import position_noise
from ..spec import BorderSpec

# ---------------------------------------------------------------------------
# betweenus / betweenus_dark — the *Between Us* app's card UI, light and dark.
#
# Between Us (github.com/gkoch02/BetweenUs) is a two-person checklist app whose
# signature gesture — a serif headline with its operative phrase in italic
# terracotta — is exactly what this clock does with a quote, so the app's
# typographic move is the layout's move and the rest of the frame is the app's
# furniture. Full design notes: docs/themes.md (`betweenus`).
#
# Composition (both variants share ``draw_betweenus_border``):
#
# * **Paper** — the app's paper → paper2 gradient as a sparse wash thresholded
#   on ``position_noise`` (light: yellow on white, ~3% → ~9% toward the foot;
#   dark: red on black ~6% → ~2.5% plus a trace of white). Quote-independent,
#   so it is cached per geometry in a bounded LRU.
# * **The card** — the body knockout, a rounded card (radius 18) with a 1 px
#   ``line`` edge, floated on a soft shadow read off a blurred offset
#   silhouette (dark clears the warm specks instead of casting black). The
#   card interior is flat: a speckled ground under body text is noise on eInk.
# * **Brand row** — "Between *Us*" top-left and a daypart pill top-right.
# * **Progress bar** — filled to the fraction of the day elapsed, gold →
#   tangerine. No digits; the registry path (source card, ``--message``) has no
#   time and draws an empty track. The sleep frame goes through ``render`` with
#   a time, so it carries a real track and pill.
# * **Legend** — the app's five answer tiers along the foot, each mapped onto a
#   documented recipe (see ``_BETWEENUS_LEGEND``).
#
# Fraunces' default axis instance is **Black**, so every candidate pins an
# instance by name. The matched phrase is italic, not bold: solid red in
# light (a stipple would shred italic hairlines), the R+Y 1:1 amber reroute in
# dark. The oversized quote marks are skipped (``_THEMES_WITHOUT_ORNAMENT_MARKS``):
# they paint on the paper outside the card, where a ``page_bg`` glyph would
# punch a hole in the wash.

_BETWEENUS_THEMES: frozenset[str] = frozenset({"betweenus", "betweenus_dark"})
# The app's 16 pt screen inset, scaled to the panel.
_BETWEENUS_MARGIN = 28
# The app's 22 pt card corner radius, scaled to the panel.
_BETWEENUS_CARD_RADIUS = 18
# Brand-row text baseline and the progress track's top edge. The card top is
# never above y=54 (dense body at y≥72, padded by 18), so the track fits at
# 44..48 and the app's count row is folded into the pill.
_BETWEENUS_BRAND_BASELINE = 34
_BETWEENUS_BAR_TOP = 44
_BETWEENUS_BAR_HEIGHT = 5
# Where the legend's dot centres sit, measured up from the foot.
_BETWEENUS_LEGEND_RISE = 24
# Drop-shadow geometry: the card silhouette offset down-right, blurred and
# read back as a density. Peak stays well below solid so the shadow keeps
# stipple texture rather than reading as a black bar.
_BETWEENUS_SHADOW_OFFSET = (3, 4)
_BETWEENUS_SHADOW_BLUR = 5
_BETWEENUS_SHADOW_PEAK = 0.45
# Off-palette sentinels for shapes that take a two-ink recipe in a post-pass.
_BETWEENUS_SENTINEL_LINE = (7, 7, 7)
_BETWEENUS_SENTINEL_TRACK = (8, 8, 8)
_BETWEENUS_SENTINEL_FILL = (9, 9, 9)
_BETWEENUS_SENTINEL_DOTS = tuple((10 + i, 10 + i, 10 + i) for i in range(5))

# The five answer tiers. Each recipe is ``(ink_a, ink_b, share_b)``: paint
# ``ink_b`` where the 8x8 Bayer rank is below ``share_b * 64``, ``ink_a``
# elsewhere; ``share_b == 0`` is a solid fill. Light column = the app's light
# tints, dark column = its lightened dark tints.
#
# ``Hard No`` is the app's ``limit`` (issue #257). It is named "slate green"
# but measures #5D6B66, a dark cool *neutral*; solid green reads as plainly
# green, and the nearest mix (K+W gray) is what ``Neutral`` already paints. So
# it takes the achromatic extreme — black on light, white on dark — and stone
# keeps the middle.
_BETWEENUS_LEGEND: tuple[tuple[str, tuple, tuple], ...] = (
    ("Love it", ("red", None, 0.0), ("red", "white", 0.5)),          # deep terracotta → salmon
    ("Like it", ("red", "yellow", 0.375), ("red", "yellow", 0.5)),   # warm terracotta → apricot
    ("Neutral", ("black", "white", 0.5), ("black", "white", 0.5)),   # stone
    ("Curious", ("yellow", "red", 0.375), ("yellow", "white", 0.5)), # ochre → pale gold
    ("Hard No", ("black", None, 0.0), ("white", None, 0.0)),         # slate → ink / bone
)

_BETWEENUS_DAYPART_LABELS = {
    "midnight": "Midnight",
    "night": "Night",
    "dawn": "Dawn",
    "morning": "Morning",
    "noon": "Noon",
    "afternoon": "Afternoon",
    "dusk": "Dusk",
    "evening": "Evening",
}

# The paper wash is cached per canvas geometry, which is caller-controlled
# via the ungated ``/api/preview`` (~1.1 MB per distinct size), so the cache
# is a small LRU: enough for the native panel plus the curator thumbnails.
_BETWEENUS_PAPER_CACHE: "collections.OrderedDict[tuple[int, int, bool], Image.Image]" = collections.OrderedDict()
_BETWEENUS_PAPER_CACHE_MAX = 4


def _betweenus_is_dark(colors: dict) -> bool:
    return colors.get("page_bg") == SPECTRA6["black"]


def _betweenus_paper(width: int, height: int, dark: bool) -> Image.Image:
    """The gradient paper wash, built once per canvas geometry and cached."""
    key = (width, height, dark)
    cached = _BETWEENUS_PAPER_CACHE.get(key)
    if cached is not None:
        _BETWEENUS_PAPER_CACHE.move_to_end(key)
        return cached.copy()
    white = SPECTRA6["white"]
    black = SPECTRA6["black"]
    red = SPECTRA6["red"]
    yellow = SPECTRA6["yellow"]
    paper = Image.new("RGB", (width, height), black if dark else white)
    px = pixel_access(paper)
    span = max(1, height - 1)
    noise = position_noise
    for y in range(height):
        t = y / span
        if dark:
            # Warm at the head, settling toward black at the foot. The white
            # trace uses the opposite end of the noise range so the two specks
            # never coincide.
            red_cut = (0.06 - 0.035 * t) * 256
            white_cut = 256 - (0.012 - 0.008 * t) * 256
            for x in range(width):
                n = noise(x, y)
                if n < red_cut:
                    px[x, y] = red
                elif n >= white_cut:
                    px[x, y] = white
        else:
            # Cream that warms toward the foot.
            cut = (0.03 + 0.06 * t) * 256
            for x in range(width):
                if noise(x, y) < cut:
                    px[x, y] = yellow
    _BETWEENUS_PAPER_CACHE[key] = paper
    while len(_BETWEENUS_PAPER_CACHE) > _BETWEENUS_PAPER_CACHE_MAX:
        _BETWEENUS_PAPER_CACHE.popitem(last=False)
    return paper.copy()


def _betweenus_clamp_rect(rect, width: int, height: int):
    x0, y0, x1, y1 = rect
    x0 = max(0, int(x0))
    y0 = max(0, int(y0))
    x1 = min(width - 1, int(x1))
    y1 = min(height - 1, int(y1))
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _betweenus_post_pass(image: Image.Image, bbox, sentinel, recipe) -> None:
    """Replace every ``sentinel`` pixel inside ``bbox`` with the two-ink
    ``recipe`` on the 8x8 Bayer tile (a 50% share is exactly a checkerboard)."""
    rect = _betweenus_clamp_rect(bbox, *image.size)
    if rect is None:
        return
    x0, y0, x1, y1 = rect
    ink_a = SPECTRA6[recipe[0]]
    ink_b = SPECTRA6[recipe[1]] if recipe[1] else None
    cut = round(recipe[2] * 64)
    px = pixel_access(image)
    for y in range(y0, y1 + 1):
        row = BAYER_8x8[y & 7]
        for x in range(x0, x1 + 1):
            if px[x, y] == sentinel:
                px[x, y] = ink_b if (ink_b is not None and row[x & 7] < cut) else ink_a


def _betweenus_line_outline(image: Image.Image, draw, rect, radius: int, dark: bool) -> None:
    """A 1 px rounded outline in the app's ``line`` token: R+G parity sepia on
    the light paper; on black the red half of that vanishes and the line
    reads as green, so dark uses a 3/8 white hairline — the faint warm-grey
    edge the app's dark ``line`` (#453C31) is."""
    draw.rounded_rectangle(rect, radius=radius, outline=_BETWEENUS_SENTINEL_LINE, width=1)
    recipe = ("black", "white", 0.375) if dark else ("red", "green", 0.5)
    _betweenus_post_pass(image, rect, _BETWEENUS_SENTINEL_LINE, recipe)


def _betweenus_paint_shadow(image: Image.Image, rect, dark: bool) -> None:
    """The card's soft drop shadow: a blurred, offset silhouette read back as a
    Bayer density. Light paints black at that density onto the paper; dark
    clears the paper's warm specks at it, so the halo of clean black *is* the
    shadow. Pixels the card will cover are skipped — the fill lands on top."""
    width, height = image.size
    x0, y0, x1, y1 = rect
    ox, oy = _BETWEENUS_SHADOW_OFFSET
    reach = _BETWEENUS_SHADOW_BLUR * 2 + max(ox, oy) + 2
    band = _betweenus_clamp_rect((x0 - reach, y0 - reach, x1 + reach, y1 + reach), width, height)
    if band is None:
        return
    bx0, by0, bx1, by1 = band
    mw, mh = bx1 - bx0 + 1, by1 - by0 + 1
    mask = Image.new("L", (mw, mh), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (x0 + ox - bx0, y0 + oy - by0, x1 + ox - bx0, y1 + oy - by0),
        radius=_BETWEENUS_CARD_RADIUS,
        fill=255,
    )
    mask = mask.filter(ImageFilter.GaussianBlur(_BETWEENUS_SHADOW_BLUR))
    mp = gray_pixel_access(mask)
    px = pixel_access(image)
    black = SPECTRA6["black"]
    r = _BETWEENUS_CARD_RADIUS
    for y in range(by0, by1 + 1):
        row = BAYER_8x8[y & 7]
        mid_row = y0 + r <= y <= y1 - r
        for x in range(bx0, bx1 + 1):
            # Fully under the card (its rectangle minus the corner cut-outs).
            if x0 <= x <= x1 and (mid_row or (x0 + r <= x <= x1 - r and y0 <= y <= y1)):
                continue
            s = mp[x - bx0, y - by0] / 255.0
            if not s:
                continue
            if dark:
                # Clear the warm specks outright where the silhouette is at
                # least half-strong, then ramp the clearing out through the
                # blur's tail.
                if px[x, y] != black and (s >= 0.5 or row[x & 7] < s * 2 * 64):
                    px[x, y] = black
            elif row[x & 7] < s * _BETWEENUS_SHADOW_PEAK * 64:
                px[x, y] = black


def _betweenus_paint_card(image: Image.Image, draw, colors: dict, rect, dark: bool) -> None:
    """Knock the body region out to a clean rounded card with the app's line
    edge, floated on the shadow."""
    _betweenus_paint_shadow(image, rect, dark)
    draw.rounded_rectangle(rect, radius=_BETWEENUS_CARD_RADIUS, fill=colors["page_bg"])
    _betweenus_line_outline(image, draw, rect, _BETWEENUS_CARD_RADIUS, dark)


def _betweenus_daypart_label(time_str: str | None) -> str | None:
    if not time_str:
        return None
    try:
        hour = int(time_str.split(":")[0])
    except (ValueError, IndexError):
        return None
    return _BETWEENUS_DAYPART_LABELS.get(daypart_for_hour(hour) or "")


def _betweenus_day_fraction(time_str: str | None) -> float:
    """Fraction of the day elapsed at ``time_str`` (0 at midnight), or 0."""
    if not time_str:
        return 0.0
    try:
        hour_text, minute_text = time_str.split(":")[:2]
        minutes = int(hour_text) * 60 + int(minute_text)
    except ValueError:
        return 0.0
    return max(0.0, min(1.0, minutes / 1440.0))


def _betweenus_paint_brand_row(image: Image.Image, draw, colors: dict, dark: bool, label: str | None) -> None:
    """"Between *Us*" top-left; the daypart capsule top-right."""
    width, _ = image.size
    ink = colors["text"]
    baseline = _BETWEENUS_BRAND_BASELINE
    word_font = load_font([(FRAUNCES_VARIABLE, "SemiBold"), *QUOTE_FONT_BOLD_CANDIDATES], size=21)
    us_font = load_font([(FRAUNCES_ITALIC_VARIABLE, "Italic"), *QUOTE_FONT_SEMIBOLD_CANDIDATES], size=21)
    x = _BETWEENUS_MARGIN
    draw.text((x, baseline), "Between ", font=word_font, fill=ink, anchor="ls")
    x += draw.textlength("Between ", font=word_font)
    draw.text((x, baseline), "Us", font=us_font, fill=ink, anchor="ls")
    if not label:
        return
    pill_font = load_font([(INTER_VARIABLE, "Medium"), *META_FONT_CANDIDATES], size=13)
    text_w = draw.textlength(label, font=pill_font)
    pill_h = 24
    pill_w = int(text_w) + 26
    px1 = width - _BETWEENUS_MARGIN
    px0 = px1 - pill_w
    py0 = baseline - 20
    py1 = py0 + pill_h
    if px0 <= x + 12 or py1 <= py0:
        return
    draw.rounded_rectangle((px0, py0, px1, py1), radius=pill_h // 2, fill=colors["page_bg"])
    _betweenus_line_outline(image, draw, (px0, py0, px1, py1), pill_h // 2, dark)
    draw.text(((px0 + px1) / 2, (py0 + py1) / 2 + 1), label, font=pill_font, fill=ink, anchor="mm")


def _betweenus_paint_progress(image: Image.Image, draw, dark: bool, fraction: float) -> None:
    """The app's progress track under the brand row, filled to the fraction of
    the day elapsed with the ``curious → want`` gradient (gold → tangerine)."""
    width, height = image.size
    x0 = _BETWEENUS_MARGIN
    x1 = width - _BETWEENUS_MARGIN
    y0 = _BETWEENUS_BAR_TOP
    y1 = y0 + _BETWEENUS_BAR_HEIGHT - 1
    if x1 - x0 < 12 or y1 >= height:
        return
    draw.rounded_rectangle((x0, y0, x1, y1), radius=2, fill=_BETWEENUS_SENTINEL_TRACK)
    # Track: a faint grey — 25% black on the light paper, 12.5% white on dark.
    _betweenus_post_pass(
        image, (x0, y0, x1, y1), _BETWEENUS_SENTINEL_TRACK,
        ("black", "white", 0.125) if dark else ("white", "black", 0.25),
    )
    if fraction <= 0:
        return
    fx1 = max(x0 + 5, x0 + round((x1 - x0) * fraction))
    draw.rounded_rectangle((x0, y0, fx1, y1), radius=2, fill=_BETWEENUS_SENTINEL_FILL)
    px = pixel_access(image)
    red = SPECTRA6["red"]
    yellow = SPECTRA6["yellow"]
    # Yellow share falls along the fill: Y-major gold at the left end, R-major
    # tangerine at the leading edge. Dark lifts both ends toward apricot.
    left_share, right_share = (0.62, 0.48) if dark else (0.55, 0.30)
    span = max(1, fx1 - x0)
    for y in range(y0, y1 + 1):
        row = BAYER_8x8[y & 7]
        for x in range(x0, fx1 + 1):
            if px[x, y] != _BETWEENUS_SENTINEL_FILL:
                continue
            share = left_share + (right_share - left_share) * ((x - x0) / span)
            px[x, y] = yellow if row[x & 7] < share * 64 else red


def _betweenus_paint_legend(image: Image.Image, draw, colors: dict, dark: bool) -> None:
    """The five answer tiers along the foot, dot + label each."""
    width, height = image.size
    font = load_font([(INTER_VARIABLE, "SemiBold"), *META_FONT_BOLD_CANDIDATES], size=13)
    radius = 4
    dot_gap = 7
    item_gap = 22
    items = []
    for label, light_recipe, dark_recipe in _BETWEENUS_LEGEND:
        items.append((label, dark_recipe if dark else light_recipe, draw.textlength(label, font=font)))
    total = sum(2 * radius + dot_gap + w for _, _, w in items) + item_gap * (len(items) - 1)
    if total > width - 2 * _BETWEENUS_MARGIN:
        return
    cy = height - _BETWEENUS_LEGEND_RISE
    if cy - radius < 0:
        return
    x = (width - total) / 2
    for index, (label, recipe, text_w) in enumerate(items):
        sentinel = _BETWEENUS_SENTINEL_DOTS[index]
        dot = (x, cy - radius, x + 2 * radius, cy + radius)
        draw.ellipse(dot, fill=sentinel)
        _betweenus_post_pass(image, dot, sentinel, recipe)
        draw.text((x + 2 * radius + dot_gap, cy), label, font=font, fill=colors["text"], anchor="lm")
        x += 2 * radius + dot_gap + text_w + item_gap


def draw_betweenus_border(image: Image.Image, colors: dict, clear_rect=None, time_str: str | None = None) -> None:
    """Paint the Between Us page: paper, card, brand row, progress, legend.

    Repaints the whole canvas from the cached paper first, so the two calls
    ``render`` makes (registry, then by name with ``clear_rect`` and
    ``time_str``) compose identically. ``time_str`` is optional for the same
    reason as in ``draw_synoptic_border``.
    """
    width, height = image.size
    dark = _betweenus_is_dark(colors)
    image.paste(_betweenus_paper(width, height, dark))
    draw = ImageDraw.Draw(image)
    card = _betweenus_clamp_rect(clear_rect, width, height) if clear_rect is not None else None
    if card is not None and card[2] - card[0] > 2 * _BETWEENUS_CARD_RADIUS and card[3] - card[1] > 2 * _BETWEENUS_CARD_RADIUS:
        _betweenus_paint_card(image, draw, colors, card, dark)
    _betweenus_paint_brand_row(image, draw, colors, dark, _betweenus_daypart_label(time_str))
    _betweenus_paint_progress(image, draw, dark, _betweenus_day_fraction(time_str))
    _betweenus_paint_legend(image, draw, colors, dark)


SPEC = BorderSpec(
    themes=("betweenus", "betweenus_dark"),
    paint=draw_betweenus_border,
    # The painter lays the paper and floats the body out to a rounded card
    # (radius 18) on a soft shadow; the pad is the app's card padding
    # scaled up, wide enough that the corner arcs never cut into a first
    # or last line. It takes the time for the day-progress bar and the
    # daypart pill.
    clear_rect_pad=(28, 18, 24),
    wants_time=True,
    # betweenus: the daypart pill at y=14..38; the widest label makes a
    # ~100 px pill, so 144 clears it for both variants.
    debug_label_inset=144,
)
