"""The ``imprimatur`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import functools
import math

from PIL import Image, ImageDraw, ImageFilter

from ..fonts import _font_ascent, load_font, normalize_dashes, theme_font_candidates
from ..furniture import fallback_title
from ..layout import _trim_line, justify_flags, strip_underscore_emphasis, tokenize_quote, wrap_styled_text
from ..palette import SPECTRA6, SPECTRA6_PALETTE, snap_image_to_palette
from ..spec import FrameSpec

# ---------------------------------------------------------------------------
# imprimatur — the opening page of a book from the Fell press at Oxford: a
# red-ruled page, a fleuron headpiece, a criblé woodcut initial, Fell roman
# body with the opening line and the rubricated phrase in Fell small capitals.
# Design notes: docs/themes.md § imprimatur.
_IMPRIMATUR_RULE_OUTER = (16, 16, 783, 463)    # the owner's red ruling, 2 px
_IMPRIMATUR_RULE_INNER = (22, 22, 777, 457)    # and its 1 px companion
_IMPRIMATUR_HEADPIECE = (52, 34, 748, 66)      # fleuron band between its rules
_IMPRIMATUR_HEADING_BASELINE = 100
_IMPRIMATUR_HEADING_MAX_W = 600
_IMPRIMATUR_BODY = (70, 128, 730, 398)
_IMPRIMATUR_BYLINE_BASELINE = 422
_IMPRIMATUR_TAILPIECE_Y = 441                  # centre line of the tailpiece
_IMPRIMATUR_LINE_HEIGHT = 1.30
_IMPRIMATUR_FONT_MAX = 46
_IMPRIMATUR_FONT_MIN = 16
_IMPRIMATUR_SUPERSAMPLE = 4                    # ornaments are drawn large, then thresholded
_IMPRIMATUR_CRIBLE_PITCH = 5                   # dot spacing of the initial's punched ground
_OPENING_MARKS = "“‘\"'"


def _imprimatur_leaf(cx: float, cy: float, angle: float, length: float, width: float) -> list[tuple[float, float]]:
    """A pointed leaf from ``(cx, cy)`` along ``angle``: fat near the stem,
    drawn to a point, the shape of a cast type flower's petal."""
    ux, uy = math.cos(angle), math.sin(angle)
    nx, ny = -uy, ux
    left, right = [], []
    steps = 16
    for i in range(steps + 1):
        t = i / steps
        half = width * 0.5 * math.sin(math.pi * t) ** 0.7 * (1.0 - 0.45 * t)
        ax, ay = cx + ux * length * t, cy + uy * length * t
        left.append((ax + nx * half, ay + ny * half))
        right.append((ax - nx * half, ay - ny * half))
    return left + right[::-1]


@functools.cache
def _imprimatur_fleuron(kind: str, size: int) -> Image.Image:
    """A type flower as a 1-bit ``L`` mask ``size`` px square.

    ``rosette``: four petals round a boss, the headpiece's main unit. ``lozenge``: a pierced diamond, the spacer between them.
    Drawn at ``_IMPRIMATUR_SUPERSAMPLE``x and thresholded, so the cut edge is
    crisp after the palette snap instead of a grey fringe.
    """
    s = size * _IMPRIMATUR_SUPERSAMPLE
    big = Image.new("L", (s, s), 0)
    draw = ImageDraw.Draw(big)
    c = s / 2
    if kind == "rosette":
        # four pointed petals on the axes, apart at the boss so each reads
        # alone at 26 px; a seed dot in each diagonal
        for k in range(4):
            a = k * math.pi / 2
            draw.polygon(_imprimatur_leaf(c + math.cos(a) * s * 0.07, c + math.sin(a) * s * 0.07, a,
                                          s * 0.42, s * 0.30), fill=255)
            d = a + math.pi / 4
            px, py, r = c + math.cos(d) * s * 0.30, c + math.sin(d) * s * 0.30, s * 0.05
            draw.ellipse((px - r, py - r, px + r, py + r), fill=255)
        r = s * 0.07
        draw.ellipse((c - r, c - r, c + r, c + r), fill=255)
    elif kind == "lozenge":
        a = s * 0.30
        draw.polygon([(c, c - a), (c + a, c), (c, c + a), (c - a, c)], fill=255)
        b = a * 0.42
        draw.polygon([(c, c - b), (c + b, c), (c, c + b), (c - b, c)], fill=0)
        r = s * 0.06
        for dx in (-a * 1.35, a * 1.35):
            draw.ellipse((c + dx - r, c - r, c + dx + r, c + r), fill=255)
    else:
        raise ValueError(f"unknown fleuron {kind!r}")
    small = big.resize((size, size), Image.Resampling.LANCZOS)
    return small.point(lambda v: 255 if v >= 128 else 0)


def _imprimatur_paint_ruling(draw: ImageDraw.ImageDraw) -> None:
    """The red ruling a careful owner had drawn round every page."""
    draw.rectangle(_IMPRIMATUR_RULE_OUTER, outline=SPECTRA6["red"], width=2)
    draw.rectangle(_IMPRIMATUR_RULE_INNER, outline=SPECTRA6["red"], width=1)


def _imprimatur_paint_headpiece(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """A row of cast type flowers between two rules, rosette and lozenge
    alternating, centred so both ends finish on a rosette."""
    x0, y0, x1, y1 = _IMPRIMATUR_HEADPIECE
    black = SPECTRA6["black"]
    draw.rectangle((x0, y0, x1, y0 + 1), fill=black)
    draw.rectangle((x0, y1 - 1, x1, y1), fill=black)
    cell = (y1 - y0) - 6
    rosette = _imprimatur_fleuron("rosette", cell)
    lozenge = _imprimatur_fleuron("lozenge", cell)
    pitch = cell + 2
    count = ((x1 - x0) - 8) // pitch
    if count % 2 == 0:
        count -= 1
    left = x0 + ((x1 - x0) - count * pitch) // 2 + 1
    top = y0 + 3
    for i in range(count):
        mask = rosette if i % 2 == 0 else lozenge
        image.paste(black, (left + i * pitch, top), mask)


def _imprimatur_tracked(draw: ImageDraw.ImageDraw, text: str, font, tracking: int) -> float:
    """Width of ``text`` letterspaced by ``tracking`` px between characters."""
    if not text:
        return 0.0
    return sum(draw.textlength(ch, font=font) for ch in text) + tracking * (len(text) - 1)


def _imprimatur_draw_tracked(draw: ImageDraw.ImageDraw, text: str, *, centre: int, baseline: int,
                             font, fill, tracking: int) -> None:
    x = centre - _imprimatur_tracked(draw, text, font, tracking) / 2
    for ch in text:
        draw.text((x, baseline), ch, font=font, fill=fill, anchor="ls")
        x += draw.textlength(ch, font=font) + tracking


def _imprimatur_fit_caption(draw: ImageDraw.ImageDraw, text: str, font, tracking: int, max_w: int) -> str:
    while len(text) > 8 and _imprimatur_tracked(draw, text, font, tracking) > max_w:
        text = text[:-2].rstrip(" ,.;:") + "…"
    return text


def _imprimatur_captions(quote_row: dict) -> tuple[str, str]:
    """``(heading, byline)``: the book's title over the page and its author
    under it; with no title the author moves up and the foot stays bare."""
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or fallback_title(quote_row) or "").strip()
    if title:
        return title, author
    return author, ""


def _imprimatur_paint_heading(draw: ImageDraw.ImageDraw, heading: str) -> None:
    """The title in letterspaced Fell small capitals, a short rule under it."""
    black = SPECTRA6["black"]
    if heading:
        font = load_font(theme_font_candidates("imprimatur", "ornament"), size=26)
        text = _imprimatur_fit_caption(draw, heading, font, 2, _IMPRIMATUR_HEADING_MAX_W)
        _imprimatur_draw_tracked(draw, text, centre=400, baseline=_IMPRIMATUR_HEADING_BASELINE,
                                 font=font, fill=black, tracking=2)
    y = _IMPRIMATUR_HEADING_BASELINE + 13
    draw.line((340, y, 388, y), fill=black, width=1)
    draw.line((412, y, 460, y), fill=black, width=1)
    draw.polygon([(400, y - 4), (404, y), (400, y + 4), (396, y)], fill=SPECTRA6["red"])


def _imprimatur_paint_foot(image: Image.Image, draw: ImageDraw.ImageDraw, byline: str) -> None:
    """The author in small capitals, then a red rosette tailpiece between
    two black lozenges."""
    if byline:
        font = load_font(theme_font_candidates("imprimatur", "ornament"), size=22)
        text = _imprimatur_fit_caption(draw, byline, font, 1, 560)
        _imprimatur_draw_tracked(draw, text, centre=400, baseline=_IMPRIMATUR_BYLINE_BASELINE,
                                 font=font, fill=SPECTRA6["black"], tracking=1)
    size = 19
    top = _IMPRIMATUR_TAILPIECE_Y - size // 2
    image.paste(SPECTRA6["red"], (400 - size // 2, top), _imprimatur_fleuron("rosette", size))
    lozenge = _imprimatur_fleuron("lozenge", size)
    for x in (400 - size // 2 - size - 2, 400 + size // 2 + 3):
        image.paste(SPECTRA6["black"], (x, top), lozenge)


def _imprimatur_split_initial(quote_row: dict) -> tuple[str, str, list[tuple[str, bool]]]:
    """``(opening_mark, initial, segments)`` for the page.

    A leading quotation mark comes off to hang in the margin beside the
    initial; the first letter comes off the first segment to be cut as the
    woodcut. The phrase is matched on the text *with* its first letter, so a
    quote that opens on the time ("Ten o'clock …") still finds it. When the
    text does not open on a letter there is no initial, and ``initial`` is
    empty.
    """
    text = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or "")).strip()
    mark = ""
    if text and text[0] in _OPENING_MARKS:
        mark, text = text[0], text[1:].lstrip()
    segments = [s for s in tokenize_quote(text, quote_row.get("matched_text") or "") if s[0]]
    if not segments or not segments[0][0][:1].isalpha():
        return mark, "", segments
    first, is_bold = segments[0]
    initial = first[0].upper()
    rest = first[1:]
    segments = ([(rest, is_bold)] if rest else []) + segments[1:]
    return mark, initial, segments


def _imprimatur_unwrap(lines: list) -> list[tuple[str, bool]]:
    """Wrapped lines back into a segment stream ``wrap_styled_text`` accepts,
    a space restored at each break (a line only ever breaks at whitespace)."""
    out: list[tuple[str, bool]] = []
    for line in lines:
        trimmed = _trim_line(line)
        if not trimmed:
            continue
        if out:
            out.append((" ", out[-1][1] and trimmed[0][1]))
        out.extend(trimmed)
    return out


def _imprimatur_peel(draw, segments, regular, bold, width: int, count: int):
    """Wrap ``segments`` at ``width`` and take the first ``count`` lines;
    returns ``(lines, remaining_segments)``."""
    if not segments or count <= 0:
        return [], segments
    lines = wrap_styled_text(draw, segments, regular, bold, width)
    return lines[:count], _imprimatur_unwrap(lines[count:])


def _imprimatur_set_page(draw: ImageDraw.ImageDraw, segments, *, has_initial: bool, size: int):
    """Set the text at ``size``: ``(lines, drop, box, line_height)``.

    ``lines`` is ``(x0, measure, items, regular)`` per line, where
    ``regular`` is the face the line's unmatched words take: small capitals
    on the opening line, the Fell roman after it. ``drop`` is how many lines
    the initial spans (0 without one) and ``box`` its side in px.
    """
    x0, _, x1, _ = _IMPRIMATUR_BODY
    measure = x1 - x0
    roman = load_font(theme_font_candidates("imprimatur", "quote_regular"), size=size)
    sc = load_font(theme_font_candidates("imprimatur", "quote_bold"), size=size)
    line_height = int(size * _IMPRIMATUR_LINE_HEIGHT)
    ascent = _font_ascent(roman)
    cap = ascent - int(draw.textbbox((0, 0), "H", font=roman, anchor="la")[1])
    best = None
    for drop in ((3, 2) if has_initial else (0,)):
        box = (drop - 1) * line_height + cap if drop else 0
        indent = box + int(size * 0.3) if drop else 0
        lines: list = []
        rest = segments
        head, rest = _imprimatur_peel(draw, rest, sc, sc, measure - indent, 1)
        lines += [(x0 + indent, measure - indent, items, sc) for items in head]
        if drop > 1:
            more, rest = _imprimatur_peel(draw, rest, roman, sc, measure - indent, drop - 1)
            lines += [(x0 + indent, measure - indent, items, roman) for items in more]
        if rest:
            lines += [(x0, measure, items, roman) for items in wrap_styled_text(draw, rest, roman, sc, measure)]
        best = (lines, drop, box, line_height)
        # A three-line initial beside a two-line quote leaves a hole under it.
        if drop != 3 or len(lines) > 3:
            break
    assert best is not None
    return best


def _imprimatur_paint_initial(image: Image.Image, box: tuple[int, int, int, int], letter: str) -> None:
    """A criblé woodcut initial: a black block punched with a ground of white
    dots, a white keyline, and the capital cut white with a clear black
    margin round it so the dots never touch the letter."""
    bx0, by0, bx1, by1 = box
    side = bx1 - bx0
    draw = ImageDraw.Draw(image)
    black, white = SPECTRA6["black"], SPECTRA6["white"]
    draw.rectangle(box, fill=black)
    pitch = _IMPRIMATUR_CRIBLE_PITCH
    for row, y in enumerate(range(by0 + 6, by1 - 5, pitch)):
        offset = (pitch // 2) if row % 2 else 0
        for x in range(bx0 + 6 + offset, bx1 - 5, pitch):
            draw.rectangle((x, y, x + 1, y + 1), fill=white)
    draw.rectangle((bx0 + 3, by0 + 3, bx1 - 3, by1 - 3), outline=white, width=1)
    font = load_font(theme_font_candidates("imprimatur", "ornament"), size=max(12, int(side * 1.02)))
    lb = draw.textbbox((0, 0), letter, font=font, anchor="la")
    lx = bx0 + (side - (lb[2] - lb[0])) / 2 - lb[0]
    ly = by0 + (side - (lb[3] - lb[1])) / 2 - lb[1]
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).text((lx, ly), letter, font=font, fill=255, anchor="la")
    margin = mask.filter(ImageFilter.MaxFilter(7))
    image.paste(black, (0, 0), margin)
    draw.rectangle((bx0 + 3, by0 + 3, bx1 - 3, by1 - 3), outline=white, width=1)
    image.paste(white, (0, 0), mask)


def _imprimatur_paint_body(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The text: initial, opening line in small capitals, Fell roman after,
    the matched phrase in red small capitals; justified where it can be."""
    mark, initial, segments = _imprimatur_split_initial(quote_row)
    x0, y0, x1, y1 = _IMPRIMATUR_BODY
    measure = x1 - x0
    for size in range(_IMPRIMATUR_FONT_MAX, _IMPRIMATUR_FONT_MIN - 1, -2):
        lines, drop, box, line_height = _imprimatur_set_page(draw, segments, has_initial=bool(initial), size=size)
        height = max(len(lines), drop) * line_height
        if height <= y1 - y0:
            break
    sc = load_font(theme_font_candidates("imprimatur", "quote_bold"), size=size)
    roman = load_font(theme_font_candidates("imprimatur", "quote_regular"), size=size)
    ascent = _font_ascent(roman)
    top = y0 + max(0, ((y1 - y0) - height) // 2)

    metrics = []
    for _lx, lw, items, regular in lines:
        trimmed = _trim_line(items)
        ink = sum(draw.textlength(t, font=sc if b else regular) for t, b in trimmed)
        gaps = sum(1 for t, _ in trimmed if t == " ")
        # justify_flags takes one measure; hand it each line's slack against the full one.
        metrics.append((int(ink) + (measure - lw), gaps))
    flags = justify_flags("imprimatur", metrics, measure, size)

    red, black = SPECTRA6["red"], SPECTRA6["black"]
    for index, (lx, _lw, items, regular) in enumerate(lines):
        trimmed = _trim_line(items)
        y = top + index * line_height
        extra: list[float] = []
        gaps = metrics[index][1]
        if flags[index] and gaps:
            slack = measure - metrics[index][0]
            extra = [slack / gaps] * gaps
        x: float = lx
        gap_index = 0
        for text, is_bold in trimmed:
            font = sc if is_bold else regular
            if text == " ":
                x += draw.textlength(" ", font=font) + (extra[gap_index] if extra else 0)
                gap_index += 1
                continue
            draw.text((x, y + (ascent - _font_ascent(font))), text, font=font, fill=red if is_bold else black)
            x += draw.textlength(text, font=font)

    if initial:
        cap_top = top + (drop - 1) * line_height + ascent - box
        _imprimatur_paint_initial(image, (x0, cap_top, x0 + box, cap_top + box), initial)
        if mark:
            draw.text((x0 - 6, cap_top), mark, font=sc, fill=black, anchor="ra")
    elif mark:
        draw.text((x0 - 4, top), mark, font=roman, fill=black, anchor="ra")


def render_imprimatur_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The opening page of a Fell-press book (see the section comment).

    Composed at 800x480 and NEAREST-downsampled otherwise (the ``metro``
    convention): the ornaments are cut to whole pixels.
    """
    del time_str
    image = Image.new("RGB", (800, 480), color=SPECTRA6["white"])
    draw = ImageDraw.Draw(image)
    heading, byline = _imprimatur_captions(quote_row)
    _imprimatur_paint_ruling(draw)
    _imprimatur_paint_headpiece(image, draw)
    _imprimatur_paint_heading(draw, heading)
    _imprimatur_paint_body(image, draw, quote_row)
    _imprimatur_paint_foot(image, draw, byline)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("imprimatur",), render=render_imprimatur_frame)
