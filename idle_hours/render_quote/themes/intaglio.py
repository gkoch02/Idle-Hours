"""The ``intaglio`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from .._paths import (
    META_FONT_BOLD_CANDIDATES,
    META_FONT_CANDIDATES,
    ORNAMENT_FONT_CANDIDATES,
    PINYONSCRIPT_REGULAR,
    SPACEMONO_BOLD,
    SPACEMONO_REGULAR,
)
from ..fonts import _font_ascent, load_font, normalize_dashes, theme_font_candidates
from ..furniture import _clock_hour12, _row_digest, fallback_title
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, pixel_access, snap_image_to_palette
from ..primitives import paint_hatched_tone
from ..spec import FrameSpec

# ---------------------------------------------------------------------------
# intaglio — a banknote face, engraved
#
# A promissory note rendering tone as **line-work** (``paint_hatched_tone``):
# engraved parallel lines whose weight carries the grey at constant pitch,
# plus guilloché roulettes. Both read as drawing at panel distance, where a
# stipple reads as tone. No committed plate: guilloché is parametric, so the
# face is procedural and exact. Full design notes: docs/themes.md
# (``intaglio``).
#
# **Three plates, three inks.** Black is the intaglio plate (masthead, quote,
# rules, medallion hubs), green the tint plate (lathework band, rosettes,
# safety tint, the matched-phrase ribbon), red the numbering press (serial
# only). White is the paper. Nothing is synthesised.
#
# **The time carrier is the denomination**: the corner medallions spell the
# hour as a face value (SEVEN, TWELVE), pinned by ``TestIntaglioEngraving``.
# The minute stays with the matched phrase, bold black over a green lathework
# ribbon — not green glyphs, which read pale at body size. The serial comes
# from ``_row_digest``, never the clock: it must not put readable digits of
# the time on the panel.
#
# **Moiré is the risk the constants manage.** The final snap is nearest-ink,
# so the only beats are hatch-vs-pixel-grid: spacing stays >= 4 (chosen 5) and
# the two hatch families sit at 33/123 degrees — off the axes, off 45, and 90
# apart so their interference is a stable lattice. The cartouche interior is
# pure white with no wash beneath. Guilloché polylines keep segments under
# ~1.5 px (coarser leaves dotted gaps on shallow arcs), and each closed curve
# is ONE ``draw.line`` call, because per-segment calls drop corner pixels at
# width 1.
_INTAGLIO_BORDER = (14, 14, 786, 466)          # outer rule of the lathework frame
_INTAGLIO_INNER = (44, 44, 756, 436)           # inner rule; the band lies between
_INTAGLIO_MEDALLION_R = 34
_INTAGLIO_ROSETTE = (400, 250, 190)            # cx, cy, R of the ground rosette
_INTAGLIO_CARTOUCHE = (128, 148, 672, 372)
_INTAGLIO_QUOTE_RECT = (162, 168, 638, 314)
_INTAGLIO_HATCH_ANGLES = (33.0, 123.0)         # off-axis, off-45; families 90 apart
_INTAGLIO_HATCH_SPACING = 5.0
_INTAGLIO_TINT_PERIOD = 14                     # safety-tint wave pitch
_INTAGLIO_HOUR_WORDS = {
    1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR", 5: "FIVE", 6: "SIX",
    7: "SEVEN", 8: "EIGHT", 9: "NINE", 10: "TEN", 11: "ELEVEN", 12: "TWELVE",
}


def _intaglio_serial(quote_row: dict) -> str:
    """Numbering-press serial: prefix letter, seven digits, suffix letter.

    Derived from ``_row_digest`` so it is stable per quote and carries no trace
    of the clock — see the section comment for why it must not.
    """
    digest = _row_digest(quote_row)
    prefix = chr(65 + digest % 26)
    suffix = chr(65 + (digest >> 8) % 26)
    return f"{prefix} {(digest >> 5) % 10_000_000:07d} {suffix}"


def _intaglio_roulette_points(cx: float, cy: float, big_r: int, small_r: int, pen_d: float,
                              *, phase: float = 0.0, squash: float = 1.0) -> list[tuple[float, float]]:
    """Sample one closed hypotrochoid — the spirograph curve of a rose lathe.

    ``x = (R-r)cos t + d cos(((R-r)/r) t)``, ``y = (R-r)sin t - d sin(...)``.
    The curve closes after ``q`` revolutions where ``(R-r)/r = p/q`` in lowest
    terms, so both radii are ints and the closure is computed, not eyeballed.
    Step count is scaled to the curve's arc-length estimate so no polyline
    segment exceeds ~1.5 px — the anti-gap discipline the section comment
    describes. ``squash`` flattens y for the oval medallion hubs.
    """
    g = math.gcd(big_r - small_r, small_r)
    revolutions = small_r // g
    t_max = 2 * math.pi * revolutions
    # The divisor is the target segment length; the pen's own epicycle makes
    # the true arc longer than t_max * reach, so it errs on the dense side.
    reach = (big_r - small_r) + pen_d
    steps = max(64, int(t_max * reach))
    k = (big_r - small_r) / small_r
    points = []
    for i in range(steps + 1):
        t = t_max * i / steps
        x = (big_r - small_r) * math.cos(t) + pen_d * math.cos(k * t)
        y = (big_r - small_r) * math.sin(t) - pen_d * math.sin(k * t)
        c, s = math.cos(phase), math.sin(phase)
        points.append((cx + x * c - y * s, cy + (x * s + y * c) * squash))
    return points


def _intaglio_cartouche_tone(x: int, y: int) -> float:
    """The engraved pillow: 0 across the cartouche's interior, rising through
    a thin rim band at its edge.

    Clipped to a superellipse (exponent 4) so the hatch never escapes onto the
    rosette, but graded by straight distance-to-edge so the band is a uniform
    ~26 px on every side. The peak is shallow (0.55) so it reads as an
    engraved bevel and leaves the legend's outer words clear.
    """
    x0, y0, x1, y1 = _INTAGLIO_CARTOUCHE
    nx = abs((x - (x0 + x1) / 2) / ((x1 - x0) / 2))
    ny = abs((y - (y0 + y1) / 2) / ((y1 - y0) / 2))
    if (nx ** 4 + ny ** 4) ** 0.25 > 1.0:
        return 0.0
    edge = min(x - x0, x1 - x, y - y0, y1 - y)
    return 0.55 * max(0.0, 1.0 - edge / 26.0) ** 1.3


def _intaglio_paint_tint(image: Image.Image) -> None:
    """The protectographic safety tint: faint green waves across the paper.

    Half-density along each wave (every other pixel) so the field reads as a
    tint rather than as ruling; everything later paints over it.
    """
    px = pixel_access(image)
    green = SPECTRA6["green"]
    x0, y0, x1, y1 = _INTAGLIO_INNER
    row = y0 + _INTAGLIO_TINT_PERIOD // 2
    band = 0
    while row < y1 - 2:
        for x in range(x0, x1):
            y = int(row + 3.0 * math.sin(x * 0.05 + band * 1.7))
            if y0 <= y < y1 and x % 3 == 0:
                px[x, y] = green
        row += _INTAGLIO_TINT_PERIOD
        band += 1


def _intaglio_paint_lathework_band(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """The border frame: black rules enclosing a woven green cycloid band.

    Two mirrored sinusoid trains per edge — the braid a straight-line lathe
    cuts — with the corner miters covered by the medallions painted after.
    """
    black, green = SPECTRA6["black"], SPECTRA6["green"]
    draw.rectangle(_INTAGLIO_BORDER, outline=black, width=2)
    draw.rectangle(_INTAGLIO_INNER, outline=black, width=1)
    bx0, by0, bx1, by1 = _INTAGLIO_BORDER
    mid_top = (by0 + _INTAGLIO_INNER[1]) // 2
    mid_bottom = (by1 + _INTAGLIO_INNER[3]) // 2
    mid_left = (bx0 + _INTAGLIO_INNER[0]) // 2
    mid_right = (bx1 + _INTAGLIO_INNER[2]) // 2
    amp = 9.0
    freq = 0.22
    for sign in (1.0, -1.0):
        for mid, horizontal in ((mid_top, True), (mid_bottom, True)):
            pts: list[tuple[float, float]] = [(x, mid + sign * amp * math.sin(x * freq)) for x in range(bx0 + 2, bx1 - 1)]
            draw.line(pts, fill=green, width=1)
        for mid in (mid_left, mid_right):
            pts = [(mid + sign * amp * math.sin(y * freq), y) for y in range(by0 + 2, by1 - 1)]
            draw.line(pts, fill=green, width=1)


def _intaglio_paint_rosette(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """The ground rosette: one large faint guilloché rose behind the cartouche.

    Petal spacing stays >= 6 px so black text over its exposed ring never loses
    a stroke to a green line crossing it.
    """
    cx, cy, big_r = _INTAGLIO_ROSETTE
    green = SPECTRA6["green"]
    draw.line(_intaglio_roulette_points(cx, cy, big_r, 130, 52.0), fill=green, width=1)
    draw.line(_intaglio_roulette_points(cx, cy, big_r - 26, 112, 40.0, phase=0.26), fill=green, width=1)
    draw.line(_intaglio_roulette_points(cx, cy, big_r - 10, 144, 34.0, phase=0.55), fill=green, width=1)


def _intaglio_paint_medallions(image: Image.Image, draw: ImageDraw.ImageDraw, hour: int) -> None:
    """Corner denomination medallions: a dense rosette, an oval hub, the word.

    The hub is wiped white before the word goes down — a real medallion's
    centre is burnished clear so the counter can overprint the value — and the
    word shrinks to fit the oval, since SEVEN and TWELVE differ by half.
    """
    black, green, white = SPECTRA6["black"], SPECTRA6["green"], SPECTRA6["white"]
    word = _INTAGLIO_HOUR_WORDS[hour]
    ix0, iy0, ix1, iy1 = _INTAGLIO_INNER
    for cx, cy in ((ix0, iy0), (ix1, iy0), (ix0, iy1), (ix1, iy1)):
        draw.line(_intaglio_roulette_points(cx, cy, _INTAGLIO_MEDALLION_R, 10, 8.0), fill=green, width=1)
        draw.line(_intaglio_roulette_points(cx, cy, _INTAGLIO_MEDALLION_R, 12, 10.0, phase=0.4), fill=green, width=1)
        hub = (cx - 27, cy - 12, cx + 27, cy + 12)
        draw.ellipse(hub, fill=white, outline=black, width=1)
        for size in (11, 10, 9, 8):
            font = load_font(theme_font_candidates("intaglio", "ornament"), size=size)
            if draw.textlength(word, font=font) <= 48:
                break
        draw.text((cx, cy - 1), word, font=font, fill=black, anchor="mm")


def _intaglio_paint_cartouche(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """The quote panel: a white superellipse pillow shaded by engraved hatching.

    The capability showcase. One family carries the full tone, the second lays
    cross-hatch only into the deepest half — see ``paint_hatched_tone`` for why
    that split is the engraver's own — and both stop below saturation so paper
    always shows between the lines.
    """
    x0, y0, x1, y1 = _INTAGLIO_CARTOUCHE
    white, black = SPECTRA6["white"], SPECTRA6["black"]
    px = pixel_access(image)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            nx = abs((x - (x0 + x1) / 2) / ((x1 - x0) / 2))
            ny = abs((y - (y0 + y1) / 2) / ((y1 - y0) / 2))
            if (nx ** 4 + ny ** 4) ** 0.25 <= 1.0:
                px[x, y] = white
    # The panel's own fine frame: the superellipse contour as a polyline.
    # Parametrised as X = a*sgn(cos)|cos|^(1/2) (the exponent-4 curve's exact
    # parameter form), dense enough that no segment gaps at 1 px.
    a, b = (x1 - x0) / 2, (y1 - y0) / 2
    ccx, ccy = (x0 + x1) / 2, (y0 + y1) / 2
    outline = []
    for i in range(721):
        t = 2 * math.pi * i / 720
        c, s = math.cos(t), math.sin(t)
        outline.append((ccx + a * math.copysign(abs(c) ** 0.5, c),
                        ccy + b * math.copysign(abs(s) ** 0.5, s)))
    draw.line(outline, fill=black, width=1)
    pad = (x0 - 2, y0 - 2, x1 + 2, y1 + 2)
    paint_hatched_tone(image, pad, _intaglio_cartouche_tone,
                       _INTAGLIO_HATCH_ANGLES[0], _INTAGLIO_HATCH_SPACING, black,
                       ground=frozenset({white}))
    paint_hatched_tone(image, pad,
                       lambda x, y: max(0.0, _intaglio_cartouche_tone(x, y) - 0.5) * 2.0,
                       _INTAGLIO_HATCH_ANGLES[1], _INTAGLIO_HATCH_SPACING, black,
                       ground=frozenset({white}))


def _intaglio_paint_masthead(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """Bank-title chrome: letterspaced Cinzel caps over a script promise line."""
    black = SPECTRA6["black"]
    title_font = load_font(theme_font_candidates("intaglio", "ornament"), size=27)
    title = "THE IDLE HOURS"
    tracking = 5.0
    width_px = sum(draw.textlength(ch, font=title_font) for ch in title) + tracking * (len(title) - 1)
    x = (800 - width_px) / 2
    for ch in title:
        draw.text((x, 52), ch, font=title_font, fill=black)
        x += draw.textlength(ch, font=title_font) + tracking
    script_font = load_font([PINYONSCRIPT_REGULAR, *ORNAMENT_FONT_CANDIDATES], size=21)
    draw.text((400, 108), "Promises to pay the bearer on demand", font=script_font,
              fill=black, anchor="mm")


def _intaglio_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The engraved legend: solid black prose, bold matched phrase over a
    green lathework ribbon.

    Draws text directly rather than through the mask pipeline: drawn text
    keeps its antialiased edges through the palette snap. The ribbon is two
    phase-mirrored sinusoids under each bold run, the border band's braid, so
    the phrase reads as a security feature rather than an underline.
    """
    x0, y0, x1, y1 = _INTAGLIO_QUOTE_RECT
    box_w, box_h = x1 - x0, y1 - y0
    black, green = SPECTRA6["black"], SPECTRA6["green"]
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    quote_font, quote_font_bold, wrapped, line_height, _ = fit_quote(
        draw, display_quote, quote_row.get("matched_text") or "", box_w, box_h,
        font_max=30, font_min=15, line_height_mult=1.3, theme="intaglio",
    )
    y = y0 + max(0, (box_h - len(wrapped) * line_height) // 2)
    body_ascent = _font_ascent(quote_font)
    for line in wrapped:
        start, end = 0, len(line)
        while start < end and line[start][0].strip() == "":
            start += 1
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        segment = line[start:end]
        width_px = sum(draw.textbbox((0, 0), c, font=quote_font_bold if b else quote_font)[2]
                       for c, b in segment)
        x = x0 + max(0, (box_w - width_px) // 2)
        for chunk, is_bold in segment:
            font = quote_font_bold if is_bold else quote_font
            draw.text((x, y + (body_ascent - _font_ascent(font))), chunk, font=font, fill=black)
            advance = draw.textbbox((0, 0), chunk, font=font)[2]
            if is_bold and chunk.strip():
                ry = y + body_ascent + 4
                for sign in (1.0, -1.0):
                    pts = [(rx, ry + sign * 1.6 * math.sin(rx * 0.55))
                           for rx in range(int(x), int(x + advance))]
                    if len(pts) >= 2:
                        draw.line(pts, fill=green, width=1)
            x += advance
        y += line_height


def _intaglio_paint_microprint_rule(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """The rule under the legend is microprint: IDLEHOURS· repeated at 6 px.

    Reads as a hairline at panel distance and resolves as text at arm's length
    — the canonical security feature, essentially free to print.
    """
    font = load_font([SPACEMONO_REGULAR, *META_FONT_CANDIDATES], size=6)
    unit = "IDLEHOURS·"
    x0, x1 = _INTAGLIO_CARTOUCHE[0] + 60, _INTAGLIO_CARTOUCHE[2] - 60
    text = unit * (int((x1 - x0) / max(1.0, draw.textlength(unit, font=font))) + 1)
    while text and draw.textlength(text, font=font) > (x1 - x0):
        text = text[:-1]
    draw.text((x0, 322), text, font=font, fill=SPECTRA6["black"])


def _intaglio_paint_serial(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The numbering press: the same red serial twice, as on a real note."""
    serial = _intaglio_serial(quote_row)
    font = load_font([SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=15)
    red = SPECTRA6["red"]
    draw.text((62, 54), serial, font=font, fill=red, anchor="la")
    draw.text((738, 408), serial, font=font, fill=red, anchor="ra")


def _intaglio_paint_attribution(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """Attribution as the note's imprint line, letterspaced inside the panel."""
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or fallback_title(quote_row) or "").strip()
    parts = " — ".join(p for p in (author, title) if p)
    if not parts:
        return
    font = load_font(theme_font_candidates("intaglio", "quote_regular"), size=14)
    while draw.textlength(parts, font=font) > 480 and len(parts) > 8:
        parts = parts[:-2].rstrip(" ,.;:") + "…"
    draw.text((400, 334), parts, font=font, fill=SPECTRA6["black"], anchor="ma")


def render_intaglio_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A banknote face in engraved line-work (see the section comment).

    Composed at 800x480 and NEAREST-downsampled otherwise (the ``metro``
    convention): the geometry and hatch pitch are absolute, and interpolation
    would average the line-work into greys the panel cannot print.
    """
    image = Image.new("RGB", (800, 480), color=SPECTRA6["white"])
    draw = ImageDraw.Draw(image)
    _intaglio_paint_tint(image)
    _intaglio_paint_lathework_band(image, draw)
    _intaglio_paint_rosette(image, draw)
    _intaglio_paint_medallions(image, draw, _clock_hour12(time_str))
    _intaglio_paint_cartouche(image, draw)
    _intaglio_paint_masthead(image, draw)
    _intaglio_paint_quote(image, draw, quote_row)
    _intaglio_paint_microprint_rule(image, draw)
    _intaglio_paint_serial(image, draw, quote_row)
    _intaglio_paint_attribution(image, draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("intaglio",), render=render_intaglio_frame)
