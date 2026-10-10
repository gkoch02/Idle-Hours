"""The ``pourjudgment`` theme's border painter and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import collections

from PIL import Image, ImageDraw

from .._paths import BODONIMODA_SEMIBOLD, JOST_VARIABLE, META_FONT_CANDIDATES, QUOTE_FONT_BOLD_CANDIDATES
from ..fonts import load_font
from ..furniture import _clock_hh_mm
from ..palette import SPECTRA6, BAYER_8x8, pixel_access
from ..primitives import position_noise
from ..spec import BorderSpec

# ---------------------------------------------------------------------------
# pourjudgment — the *Pour Judgment* app's Home screen in its dark
# appearance: leather, brass and the claret verdict card. Square corners,
# hairline rules, no shadows. Design notes: docs/themes.md § pourjudgment.

# The app's 24 pt page margin, scaled to the panel.
_POURJUDGMENT_MARGIN = 28
# Masthead baseline, then the DoubleRule: a 2 px bar, a 3 px gap, a hairline.
_POURJUDGMENT_TITLE_BASELINE = 33
_POURJUDGMENT_RULE_TOP = 41
# The card never rises above the rule, whatever the layout asks for.
_POURJUDGMENT_CARD_TOP_MIN = 54
# ``render`` pads the body by this much above the first line; the card's
# eyebrow row lives in it when the card is not clamped down onto the text.
_POURJUDGMENT_PAD_TOP = 36
_POURJUDGMENT_EYEBROW_ROOM = 25
# The tab bar's hairline and label baseline, measured up from the foot.
_POURJUDGMENT_TAB_RULE_RISE = 36
_POURJUDGMENT_TAB_BASELINE_RISE = 13
# The app's five "How full" steps and their words, emptiest first.
_POURJUDGMENT_FILL_WORDS = ("Fumes", "A quarter", "Half gone", "Mostly full", "Unopened")
_POURJUDGMENT_STEP = (13, 10)
_POURJUDGMENT_STEP_GAP = 4
# The drawn tab bar: glyph and label, Home selected as on the app's Home.
_POURJUDGMENT_TABS = (("diamond", "Home"), ("bars", "Cellar"), ("dot", "Cocktails"), ("ledger", "My Recipes"))

# The leather (#17100D): red on black at this share, a hash scatter.
_POURJUDGMENT_LEATHER_SHARE = 0.04
# The app's dark tokens on panel inks. Type is solid: ``ink`` (#F4EADA) is
# white, and small brass type is solid yellow, since a stipple shreds it. Brass
# *surfaces* (#D8B25C / #C8A44D) take yellow with a quarter red, which pulls
# the panel's lemon yellow (~#C1BB1E) toward the app's warm gold.
_POURJUDGMENT_INKS = {
    "ink": SPECTRA6["white"],
    "accent": SPECTRA6["yellow"],
}

# The ground is cached per canvas geometry, which is caller-controlled via
# the ungated ``/api/preview``, so the cache is a small LRU (the
# ``betweenus`` paper lesson).
_POURJUDGMENT_GROUND_CACHE: "collections.OrderedDict[tuple[int, int], Image.Image]" = collections.OrderedDict()
_POURJUDGMENT_GROUND_CACHE_MAX = 4


def _pourjudgment_ground(width: int, height: int) -> Image.Image:
    """Leather: a red hash scatter on black, built once per geometry and
    cached."""
    key = (width, height)
    cached = _POURJUDGMENT_GROUND_CACHE.get(key)
    if cached is not None:
        _POURJUDGMENT_GROUND_CACHE.move_to_end(key)
        return cached.copy()
    ground = Image.new("RGB", (width, height), SPECTRA6["black"])
    px = pixel_access(ground)
    red = SPECTRA6["red"]
    cut = _POURJUDGMENT_LEATHER_SHARE * 256
    for y in range(height):
        for x in range(width):
            if position_noise(x, y) < cut:
                px[x, y] = red
    _POURJUDGMENT_GROUND_CACHE[key] = ground
    while len(_POURJUDGMENT_GROUND_CACHE) > _POURJUDGMENT_GROUND_CACHE_MAX:
        _POURJUDGMENT_GROUND_CACHE.popitem(last=False)
    return ground.copy()


def _pourjudgment_clamp_rect(rect, width: int, height: int):
    x0, y0, x1, y1 = rect
    x0 = max(0, int(x0))
    y0 = max(0, int(y0))
    x1 = min(width - 1, int(x1))
    y1 = min(height - 1, int(y1))
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _pourjudgment_hairline(image: Image.Image, x0: int, x1: int, y: int, vertical: bool = False) -> None:
    """The app's brass ``LineStrong`` (#C8A44D at 34% on leather): along a
    1 px line, yellow on every fourth pixel and red two after it, leather
    between — a dim warm brass rather than a bright dotted yellow."""
    width, height = image.size
    px = pixel_access(image)
    yellow = SPECTRA6["yellow"]
    red = SPECTRA6["red"]
    for t in range(min(x0, x1), max(x0, x1) + 1):
        x, yy = (y, t) if vertical else (t, y)
        if not (0 <= x < width and 0 <= yy < height):
            continue
        phase = t & 3
        if phase == 0:
            px[x, yy] = yellow
        elif phase == 2:
            px[x, yy] = red


def _pourjudgment_brass(image: Image.Image, rect, share: float = 1.0) -> None:
    """Fill ``rect`` with brass: yellow with one red pixel per 2x2 tile, at
    ``share`` of full strength (the rest left as the ground) on the 8x8
    Bayer tile."""
    clamped = _pourjudgment_clamp_rect(rect, *image.size)
    if clamped is None:
        return
    x0, y0, x1, y1 = clamped
    px = pixel_access(image)
    yellow = SPECTRA6["yellow"]
    red = SPECTRA6["red"]
    cut = round(share * 64)
    for y in range(y0, y1 + 1):
        row = BAYER_8x8[y & 7]
        for x in range(x0, x1 + 1):
            if row[x & 7] < cut:
                px[x, y] = red if (x & 1 and y & 1) else yellow


def _pourjudgment_fill_steps(time_str: str | None) -> int:
    """How many of the five steps are full: the bottle drains with the day,
    unopened at midnight, fumes in the last fifth before the next."""
    if not time_str:
        return 5
    hour, minute = _clock_hh_mm(time_str)
    fraction = max(0.0, min(1.0, (hour * 60 + minute) / 1440.0))
    return max(1, 5 - int(fraction * 5))


def _pourjudgment_tracked(draw, xy, text: str, font, fill, tracking: float, measure_only: bool = False) -> float:
    """Draw ``text`` left-aligned on baseline ``xy`` with ``tracking`` em of
    letterspacing; return its advance."""
    x, y = xy
    em = font.size
    advance = 0.0
    for i, char in enumerate(text):
        if not measure_only:
            draw.text((x + advance, y), char, font=font, fill=fill, anchor="ls")
        advance += draw.textlength(char, font=font)
        if i < len(text) - 1:
            advance += tracking * em
    return advance


def _pourjudgment_caps_font(size: int):
    return load_font([(JOST_VARIABLE, "Medium"), *META_FONT_CANDIDATES], size=size)


def _pourjudgment_paint_masthead(image: Image.Image, draw, inks: dict, steps: int) -> None:
    """"Pour Judgment" in Bodoni SemiBold, the "How full" gauge right, and
    the DoubleRule under both."""
    width, _ = image.size
    title_font = load_font([BODONIMODA_SEMIBOLD, *QUOTE_FONT_BOLD_CANDIDATES], size=27)
    draw.text((_POURJUDGMENT_MARGIN, _POURJUDGMENT_TITLE_BASELINE), "Pour Judgment", font=title_font, fill=inks["ink"], anchor="ls")
    title_right = _POURJUDGMENT_MARGIN + draw.textlength("Pour Judgment", font=title_font)

    sw, sh = _POURJUDGMENT_STEP
    gauge_w = 5 * sw + 4 * _POURJUDGMENT_STEP_GAP
    gx1 = width - _POURJUDGMENT_MARGIN
    gx0 = gx1 - gauge_w
    caps = _pourjudgment_caps_font(12)
    word = _POURJUDGMENT_FILL_WORDS[steps - 1].upper()
    word_w = _pourjudgment_tracked(draw, (0, 0), word, caps, None, 0.18, measure_only=True)
    word_x = gx0 - 12 - word_w
    if word_x > title_right + 16:
        _pourjudgment_tracked(draw, (word_x, _POURJUDGMENT_TITLE_BASELINE - 5), word, caps, inks["accent"], 0.18)
        top = _POURJUDGMENT_TITLE_BASELINE - 5 - sh
        for i in range(5):
            x0 = gx0 + i * (sw + _POURJUDGMENT_STEP_GAP)
            box = (x0, top, x0 + sw - 1, top + sh - 1)
            if i < steps:
                # The app's full step: a 1 px accent border round an 18%
                # accent fill.
                _pourjudgment_brass(image, (box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1), share=0.25)
                draw.rectangle(box, outline=inks["accent"], width=1)
            else:
                # An empty step is outlined in ``LineStrong`` only.
                for yy in (box[1], box[3]):
                    _pourjudgment_hairline(image, box[0], box[2], yy)
                for xx in (box[0], box[2]):
                    _pourjudgment_hairline(image, box[1], box[3], xx, vertical=True)

    y = _POURJUDGMENT_RULE_TOP
    _pourjudgment_brass(image, (_POURJUDGMENT_MARGIN, y, width - 1 - _POURJUDGMENT_MARGIN, y + 1))
    _pourjudgment_hairline(image, _POURJUDGMENT_MARGIN, width - 1 - _POURJUDGMENT_MARGIN, y + 5)


def _pourjudgment_paint_card(image: Image.Image, draw, rect, first_line_top: int | None, inks: dict) -> None:
    """The claret verdict card: flat red, square, a hairline edge, and "The House Recommends" in gold when there is room
    above the first line."""
    x0, y0, x1, y1 = rect
    # Flat claret: the panel's red already measures claret (#62201E), and the
    # app's fall to claretDeep, stippled in black, shreds the small Bodoni of
    # the attribution that sits over it.
    draw.rectangle(rect, fill=SPECTRA6["red"])
    px = pixel_access(image)
    for yy in (y0, y1):
        _pourjudgment_hairline(image, x0, x1, yy)
    for xx in (x0, x1):
        _pourjudgment_hairline(image, y0, y1, xx, vertical=True)

    if first_line_top is None or first_line_top - y0 < _POURJUDGMENT_EYEBROW_ROOM:
        return
    caps = _pourjudgment_caps_font(11)
    baseline = y0 + 17
    ex = x0 + 22
    advance = _pourjudgment_tracked(draw, (ex, baseline), "THE HOUSE RECOMMENDS", caps, SPECTRA6["yellow"], 0.2)
    # Parchment at 22%: white on every fourth pixel of the red.
    rule_y = baseline - 4
    for x in range(int(ex + advance + 10), x1 - 21):
        if x & 3 == 0:
            px[x, rule_y] = SPECTRA6["white"]


def _pourjudgment_paint_glyph(draw, kind: str, cx: float, cy: float, fill) -> None:
    if kind == "diamond":
        draw.polygon(((cx, cy - 5), (cx + 5, cy), (cx, cy + 5), (cx - 5, cy)), outline=fill, width=1)
    elif kind == "bars":
        draw.line((cx - 2, cy - 5, cx - 2, cy + 5), fill=fill, width=1)
        draw.line((cx + 2, cy - 5, cx + 2, cy + 5), fill=fill, width=1)
    elif kind == "dot":
        draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=fill)
    else:  # ledger
        draw.rectangle((cx - 5, cy - 5, cx + 5, cy + 5), outline=fill, width=1)
        for dy in (-2, 1):
            draw.line((cx - 5, cy + dy, cx + 5, cy + dy), fill=fill, width=1)


def _pourjudgment_paint_tabs(image: Image.Image, draw, inks: dict, card_bottom: int | None) -> None:
    """The drawn tab bar along the foot: glyph and tracked word, the Home
    glyph in the accent."""
    width, height = image.size
    rule_y = height - _POURJUDGMENT_TAB_RULE_RISE
    if card_bottom is not None and card_bottom >= rule_y - 2:
        return
    _pourjudgment_hairline(image, _POURJUDGMENT_MARGIN, width - 1 - _POURJUDGMENT_MARGIN, rule_y)
    caps = _pourjudgment_caps_font(11)
    baseline = height - _POURJUDGMENT_TAB_BASELINE_RISE
    items = []
    for glyph, label in _POURJUDGMENT_TABS:
        text = label.upper()
        items.append((glyph, text, 16 + _pourjudgment_tracked(draw, (0, 0), text, caps, None, 0.14, measure_only=True)))
    slot = (width - 2 * _POURJUDGMENT_MARGIN) / len(items)
    for i, (glyph, text, item_w) in enumerate(items):
        x = _POURJUDGMENT_MARGIN + slot * i + (slot - item_w) / 2
        _pourjudgment_paint_glyph(draw, glyph, x + 5, baseline - 4, inks["accent"] if i == 0 else inks["ink"])
        _pourjudgment_tracked(draw, (x + 16, baseline), text, caps, inks["ink"], 0.14)


def draw_pourjudgment_border(image: Image.Image, colors: dict, clear_rect=None, time_str: str | None = None) -> None:
    """Paint the Pour Judgment page: ground, masthead, verdict card, tab bar.

    Repaints the whole canvas from the cached ground, so ``render``'s two
    calls compose identically. Without a ``clear_rect`` (the source card, the
    static message) the card takes a fixed rect; without a time the bottle
    reads unopened.
    """
    del colors
    width, height = image.size
    inks = _POURJUDGMENT_INKS
    image.paste(_pourjudgment_ground(width, height))
    draw = ImageDraw.Draw(image)
    _pourjudgment_paint_masthead(image, draw, inks, _pourjudgment_fill_steps(time_str))
    first_line_top = None
    if clear_rect is None:
        card = _pourjudgment_clamp_rect(
            (_POURJUDGMENT_MARGIN, 62, width - 1 - _POURJUDGMENT_MARGIN, height - _POURJUDGMENT_TAB_RULE_RISE - 14), width, height
        )
    else:
        x0, y0, x1, y1 = clear_rect
        if y0 > 0:
            first_line_top = y0 + _POURJUDGMENT_PAD_TOP
        card = _pourjudgment_clamp_rect((x0, max(y0, _POURJUDGMENT_CARD_TOP_MIN), x1, y1), width, height)
    if card is not None:
        _pourjudgment_paint_card(image, draw, card, first_line_top, inks)
    _pourjudgment_paint_tabs(image, draw, inks, card[3] if card is not None else None)


SPEC = BorderSpec(
    themes=("pourjudgment",),
    paint=draw_pourjudgment_border,
    # The body sits on the claret card; the top pad holds the card's
    # eyebrow row, the sides and foot are the app's card padding. The time
    # drains the "How full" gauge.
    clear_rect_pad=(28, _POURJUDGMENT_PAD_TOP, 22),
    wants_time=True,
    # The gauge and its fill word sit in the debug banner's band.
    debug_label_inset=230,
)
