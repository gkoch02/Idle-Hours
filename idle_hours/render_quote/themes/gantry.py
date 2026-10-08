"""The ``gantry`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import random

from PIL import Image, ImageChops, ImageDraw

from .._paths import BARLOWCOND_BOLD, BARLOWCOND_SEMIBOLD, META_FONT_BOLD_CANDIDATES
from ..fonts import load_font
from ..furniture import _clock_hour12, _row_digest, fallback_title
from ..layout import strip_underscore_emphasis, tokenize_quote
from ..palette import (
    SPECTRA6,
    SPECTRA6_PALETTE,
    BAYER_8x8,
    _dither_calibrated,
    gray_pixel_access,
    pixel_access,
    snap_image_to_palette,
)
from ..primitives import _soft_ellipse_mask, _white_noise, paint_neon_mask
from ..spec import FrameSpec
from ..text import fit_text_to_width
from ._shared import _gantry_dot, _gantry_glyph, _gantry_tokens

# ---------------------------------------------------------------------------
# gantry — an overhead highway message sign at night.
#
# The quote runs on a full-matrix LED sign hung from a steel truss over a
# motorway, shot as a long exposure: amber dots in their own bloom, the
# matched phrase lit white, tail-light streaks running off under the sign
# toward the vanishing point, and the source posted on a green guide sign at
# the roadside with the hour as its exit number.
#
# **The font is read as dots, not outlines.** Lumen is a 5x7 matrix on a
# strict grid one tenth of an em apart, so ``_gantry_glyph`` renders each
# character once, supersampled, and reads the grid centres back as a set of
# lit cells. Every LED is then drawn by the theme on ONE lattice that covers
# the whole sign face, lit or not, the way a real sign is built: the dot
# pitch is chosen per quote (big dots for short quotes, a tight grid for long
# ones) and the glyphs always land on it. Drawing the outlines at an
# arbitrary size instead would put each line's dots on its own grid.
#
# Letters are packed proportionally (ink columns plus one blank column), as
# real sign fonts are, and the matched phrase is set bold the matrix way: the
# glyph ORed with itself one column over.
# ---------------------------------------------------------------------------

_GANTRY_CABINET = (14, 30, 786, 354)
_GANTRY_FACE = (30, 44, 770, 340)
# Dot pitches tried largest first; the first that fits the quote wins.
_GANTRY_PITCHES = (9, 8, 7, 6, 5, 4, 3)
_GANTRY_LINE_ROWS = (10, 9)  # row pitch of a text line, in LED rows: roomy, then tight
_GANTRY_GLYPH_ROWS = 11      # rows a glyph can touch: accents 0-1, caps 2-8, descenders 9-10
_GANTRY_WORD_GAP = 3         # blank columns between words
_GANTRY_MODULE = 16          # LEDs per side of one module of the face
_GANTRY_DEAD_LEDS = 2

# The scene.
_GANTRY_HORIZON = 380
_GANTRY_VANISH_X = 330
_GANTRY_GUIDE = (520, 392, 772, 466)
_GANTRY_HORIZON_SEED = 0x6A47
_GANTRY_GRAIN_SEED = 0x6A48


# --- the dot-matrix engine -------------------------------------------------

def _gantry_segment_words(segments) -> list[list[tuple[str, bool]]]:
    """``(text, is_matched)`` segments as words of ``(glyph, is_matched)``."""
    words: list[list[tuple[str, bool]]] = []
    current: list[tuple[str, bool]] = []
    for segment, matched in segments:
        for token in _gantry_tokens(segment):
            if token.isspace():
                if current:
                    words.append(current)
                current = []
                continue
            current.append((token, matched))
    if current:
        words.append(current)
    return words


def _gantry_words(quote_row: dict) -> list[list[tuple[str, bool]]]:
    """The quote as words of ``(glyph, is_matched)``."""
    text = strip_underscore_emphasis(quote_row.get("display_quote") or "")
    return _gantry_segment_words(tokenize_quote(text, quote_row.get("matched_text") or ""))


def _gantry_advance(ch: str, bold: bool) -> int:
    width, _ = _gantry_glyph(ch)
    return max(1, width + (1 if bold else 0))


def _gantry_word_width(word) -> int:
    return sum(_gantry_advance(ch, bold) for ch, bold in word) + len(word) - 1


def _gantry_wrap(words, measure: int) -> list[list]:
    """Greedy wrap to ``measure`` columns; an over-long word is broken."""
    lines: list[list] = []
    line: list = []
    width = 0
    for word in words:
        while _gantry_word_width(word) > measure and len(word) > 1:
            cut = len(word) - 1
            while cut > 1 and _gantry_word_width(word[:cut]) > measure:
                cut -= 1
            if line:
                lines.append(line)
                line, width = [], 0
            lines.append([word[:cut]])
            word = word[cut:]
        w = _gantry_word_width(word)
        if line and width + _GANTRY_WORD_GAP + w > measure:
            lines.append(line)
            line, width = [], 0
        width = w if not line else width + _GANTRY_WORD_GAP + w
        line.append(word)
    if line:
        lines.append(line)
    return lines


def _gantry_line_width(line) -> int:
    return sum(_gantry_word_width(w) for w in line) + _GANTRY_WORD_GAP * (len(line) - 1)


def _gantry_tall(line) -> bool:
    """True when a glyph on ``line`` reaches the accent rows (0-1)."""
    return any(r < 2 for word in line for ch, _ in word for _, r in _gantry_glyph(ch)[1])


def _gantry_fit(words, face_w: int, face_h: int, *, fixed=None):
    """``(pitch, cols, rows, line_rows, lines)``: the largest dot pitch the
    text fits at, and the row pitch of its lines.

    Each dot pitch tries the roomy line pitch first, then the tight one, where
    a descender (rows 9-10) sits directly over the next line's caps (row 2):
    a bigger dot on tight lines reads better than a smaller one on loose
    lines. Tight is refused when a line below the first reaches the accent
    rows, which a descender above would overprint.

    Wrapped lines are balanced (the narrowest measure that keeps the line
    count), which is how a sign centres a message. ``fixed`` lines are set as
    they are and only the pitches are chosen (the sleep frame's message).
    """
    for pitch in _GANTRY_PITCHES:
        cols, rows = face_w // pitch, face_h // pitch
        measure = cols - 2
        lines = fixed if fixed is not None else _gantry_wrap(words, measure)
        fits_wide = all(_gantry_line_width(line) <= measure for line in lines)
        for line_rows in _GANTRY_LINE_ROWS:
            max_lines = (rows - _GANTRY_GLYPH_ROWS) // line_rows + 1
            if line_rows < _GANTRY_GLYPH_ROWS - 1 and any(_gantry_tall(line) for line in lines[1:]):
                continue
            if fits_wide and len(lines) <= max_lines:
                break
        else:
            continue
        break
    if fixed is None:
        count = len(lines)
        while measure > 8:
            tighter = _gantry_wrap(words, measure - 1)
            if len(tighter) > count:
                break
            measure -= 1
            lines = tighter
    return pitch, cols, rows, line_rows, lines[:max_lines]


def _gantry_lit_cells(lines, cols: int, rows: int, line_rows: int):
    """``(body cells, matched cells)`` on the sign's lattice, lines centred."""
    body: set[tuple[int, int]] = set()
    lit: set[tuple[int, int]] = set()
    count = len(lines)
    # Centre on the cap band (rows 2-8 of the first line to the last).
    block = (count - 1) * line_rows + 7
    top = max(0, min(rows - ((count - 1) * line_rows + _GANTRY_GLYPH_ROWS), (rows - block) // 2 - 2))
    for index, line in enumerate(lines):
        x = (cols - _gantry_line_width(line)) // 2
        y = top + index * line_rows
        for word_index, word in enumerate(line):
            if word_index:
                x += _GANTRY_WORD_GAP
            for char_index, (ch, bold) in enumerate(word):
                if char_index:
                    x += 1
                width, cells = _gantry_glyph(ch)
                target = lit if bold else body
                for c, r in cells:
                    target.add((x + c, y + r))
                    if bold:
                        target.add((x + c + 1, y + r))
                x += max(1, width + (1 if bold else 0))
    body -= lit
    return body, lit


def _gantry_paint_face(image: Image.Image, words=None, *, fixed=None, seed: int = 0) -> None:
    """The sign face: every LED of the lattice, the lit ones in their bloom.

    ``seed`` picks the sign's dead LEDs (a lit cell left dark); ``fixed``
    lines bypass the wrap (see ``_gantry_fit``).
    """
    fx0, fy0, fx1, fy1 = _GANTRY_FACE
    face_w, face_h = fx1 - fx0, fy1 - fy0
    pitch, cols, rows, line_rows, lines = _gantry_fit(words or [], face_w, face_h, fixed=fixed)
    body, lit = _gantry_lit_cells(lines, cols, rows, line_rows)
    # Every sign in service has a few dead LEDs; which ones is fixed per quote.
    rng = random.Random(seed)
    for _ in range(_GANTRY_DEAD_LEDS):
        if body:
            body.discard(rng.choice(sorted(body)))
    face = Image.new("RGB", (face_w, face_h), SPECTRA6["black"])
    ox = (face_w - cols * pitch) // 2
    oy = (face_h - rows * pitch) // 2
    diameter = max(2, pitch - 1)
    dot = _gantry_dot(diameter)
    black, red, yellow, white, blue = (SPECTRA6[k] for k in ("black", "red", "yellow", "white", "blue"))
    px = pixel_access(face)
    # The face is built from LED modules; the seams between them show as a
    # faint dotted line in the gap between two columns or rows of LEDs.
    if pitch >= 4:
        for c in range(_GANTRY_MODULE, cols, _GANTRY_MODULE):
            x = ox + c * pitch - 1
            for y in range(oy, oy + rows * pitch, 4):
                px[x, y] = blue
        for r in range(_GANTRY_MODULE, rows, _GANTRY_MODULE):
            y = oy + r * pitch - 1
            for x in range(ox, ox + cols * pitch, 4):
                px[x, y] = blue
    # Dark LEDs: the lens of an unlit LED catches a point of light.
    if pitch >= 5:
        mid = diameter // 2
        for r in range(rows):
            for c in range(cols):
                if (c, r) not in body and (c, r) not in lit:
                    px[ox + c * pitch + mid, oy + r * pitch + mid] = blue
    masks = {}
    for name, cells in (("body", body), ("lit", lit)):
        mask = Image.new("L", (face_w, face_h), 0)
        mp = gray_pixel_access(mask)
        for c, r in cells:
            x, y = ox + c * pitch, oy + r * pitch
            for dx, dy in dot:
                mp[x + dx, y + dy] = 255
        masks[name] = mask
    radius = max(1.2, pitch * 0.55)
    ground = frozenset({black, blue})
    paint_neon_mask(face, masks["body"], None, red, radius=radius, cap=0.55, ground=ground)
    # The white phrase blooms mostly white: its bold doubles the columns, and
    # a yellow bloom in the 1 px gaps between them speckles the inside of the
    # letters. A third of it stays yellow, the warm edge of a white LED.
    paint_neon_mask(face, masks["lit"], None, white, radius=radius, cap=0.5, ground=ground | {red},
                    glow_minor=yellow, glow_minor_share=0.35, tile=BAYER_8x8)
    for cells, core in ((body, yellow), (lit, white)):
        for c, r in cells:
            x, y = ox + c * pitch, oy + r * pitch
            for dx, dy in dot:
                px[x + dx, y + dy] = core
    image.paste(face, (fx0, fy0))


# --- the scene --------------------------------------------------------------

def _gantry_paint_backdrop(image: Image.Image) -> None:
    """Night sky and asphalt in continuous tone, dithered to the dark inks.

    Kept dark on purpose: the light in this frame is the sign and the
    traffic, and a lit road surface drowns the trails in dither.
    """
    width, height = image.size
    scene = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(scene)
    hz = _GANTRY_HORIZON
    for y in range(height):
        if y < hz:
            t = (y / hz) ** 2.4
            colour = (int(31 + 14 * t), int(34 + 8 * t), int(38 + 40 * t))
        else:
            t = (y - hz) / (height - hz)
            colour = (int(36 - 5 * t), int(40 - 6 * t), int(52 - 14 * t))
        draw.line((0, y, width, y), fill=colour)
    # Sodium skyglow along the horizon.
    glow = Image.new("RGB", (width, height), (90, 48, 44))
    scene.paste(glow, (0, 0), _soft_ellipse_mask((width, height), (-100, hz - 22, width + 100, hz + 8), 12)
                .point(lambda v: v // 2))
    # Grain before the dither: Floyd-Steinberg over a smooth ramp settles into
    # a regular dot lattice, and a little noise breaks it up into film grain.
    grain = _white_noise(width, height, _GANTRY_GRAIN_SEED).point(lambda v: 128 + (v - 128) // 10)
    scene = ImageChops.add(scene, Image.merge("RGB", (grain, grain, grain)), offset=-128)
    image.paste(_dither_calibrated(scene, ("black", "blue", "red")))


def _gantry_road_x(bottom_x: float, y: float) -> float:
    """x of a road line through ``bottom_x`` at the frame foot, at height ``y``."""
    t = (y - _GANTRY_HORIZON) / (480 - _GANTRY_HORIZON)
    return _GANTRY_VANISH_X + (bottom_x - _GANTRY_VANISH_X) * t


def _gantry_trail_mask(size, bottoms, max_width: float) -> Image.Image:
    """Long-exposure light trails along road lines, thickening toward us."""
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    hz = _GANTRY_HORIZON
    for bottom_x in bottoms:
        for y in range(hz + 1, 480, 2):
            t = (y - hz) / (480 - hz)
            draw.line((_gantry_road_x(bottom_x, y), y, _gantry_road_x(bottom_x, y + 2), y + 2),
                      fill=255, width=max(1, round(max_width * t)))
    return mask


def _gantry_paint_road(image: Image.Image, *, traffic: bool = True) -> None:
    """Lane markings, the median, the horizon's lights, and the traffic's
    light trails (left off for the small hours: ``traffic=False``)."""
    draw = ImageDraw.Draw(image)
    black, white, yellow, red = (SPECTRA6[k] for k in ("black", "white", "yellow", "red"))
    hz = _GANTRY_HORIZON
    # Lane markings in perspective: dashes between the lanes, solid edges.
    for bottom_x, dashed in ((40, False), (300, True), (560, True), (840, False)):
        y = float(hz + 3)
        index = 0
        while y < 480:
            step = 1.5 + (y - hz) * 0.28
            y_end = min(480.0, y + step)
            if not dashed or index % 2 == 0:
                t = (y - hz) / (480 - hz)
                draw.line((_gantry_road_x(bottom_x, y), y, _gantry_road_x(bottom_x, y_end), y_end),
                          fill=white, width=max(1, round(1 + 3 * t)))
            y = y_end
            index += 1
    # The median barrier: a dark wedge with its lit top edge.
    draw.polygon([(_gantry_road_x(-60, hz), hz), (_gantry_road_x(-60, 480), 480),
                  (_gantry_road_x(0, 480), 480), (_gantry_road_x(0, hz), hz)], fill=black)
    draw.line((_gantry_road_x(0, hz), hz, _gantry_road_x(0, 480), 480), fill=white)
    # Tail lights receding in our three lanes (a pair of lamps per car), head
    # lights coming the other way beyond the median.
    if traffic:
        tails = _gantry_trail_mask(image.size, (150, 186, 412, 452, 664, 708), 3.2)
        heads = _gantry_trail_mask(image.size, (-330, -290, -190), 3.2)
        ground = frozenset({black, SPECTRA6["blue"], red})
        # A tail-light core is red run hot: a quarter of it stippled white
        # reads as the pink centre a long exposure burns into the streak.
        paint_neon_mask(image, tails, red, red, radius=2.5, cap=0.45, ground=ground,
                        core_minor=white, core_minor_share=0.25)
        paint_neon_mask(image, heads, white, yellow, radius=2.5, cap=0.45, ground=ground)
    # Distant lights strung along the horizon.
    rng = random.Random(_GANTRY_HORIZON_SEED)
    px = pixel_access(image)
    for _ in range(70):
        x = rng.randrange(40, 760)
        y = hz - rng.randrange(0, 5)
        px[x, y] = rng.choice((yellow, yellow, white, red))


def _gantry_paint_steel(image: Image.Image) -> None:
    """The truss overhead, the two uprights, and the catwalk.

    Steel at night is a silhouette: black members picked out by a hairline of
    blue where the skyglow catches an edge, and a white glint on the top
    chord.
    """
    draw = ImageDraw.Draw(image)
    black, blue, white = SPECTRA6["black"], SPECTRA6["blue"], SPECTRA6["white"]
    # Truss: top and bottom chords with a Warren web between them.
    for x in range(-28, 830, 28):
        draw.line((x, 9, x + 14, 26), fill=black, width=3)
        draw.line((x + 14, 26, x + 28, 9), fill=black, width=3)
        draw.line((x + 1, 9, x + 15, 26), fill=blue)
        draw.line((x + 15, 26, x + 29, 9), fill=blue)
    draw.rectangle((0, 5, 800, 9), fill=black)
    draw.line((0, 5, 800, 5), fill=white)
    draw.line((0, 9, 800, 9), fill=blue)
    draw.rectangle((0, 25, 800, 30), fill=black)
    draw.line((0, 25, 800, 25), fill=blue)
    # Uprights: box columns with cross bracing, rim-lit on the road side.
    for x0, x1, rim in ((0, 22, 21), (778, 800, 778)):
        draw.rectangle((x0, 0, x1 - 1, 480), fill=black)
        for y in range(4, 480, 30):
            draw.line((x0 + 3, y, x1 - 4, y + 26), fill=blue)
            draw.line((x0 + 3, y + 26, x1 - 4, y), fill=blue)
            draw.line((x0, y + 28, x1 - 1, y + 28), fill=black, width=3)
        draw.line((x0 + 2, 0, x0 + 2, 480), fill=blue)
        draw.line((x1 - 3, 0, x1 - 3, 480), fill=blue)
        draw.line((rim, 0, rim, 480), fill=white)
    # Catwalk along the foot of the cabinet: grating, toe board, hand rail.
    cx0, _, cx1, cy1 = _GANTRY_CABINET
    draw.rectangle((cx0, cy1, cx1 - 1, cy1 + 13), fill=black)
    for x in range(cx0 + 2, cx1 - 2, 4):
        draw.line((x, cy1 + 6, x, cy1 + 11), fill=blue)
    draw.line((cx0, cy1 + 4, cx1 - 1, cy1 + 4), fill=white)
    draw.line((cx0, cy1 + 12, cx1 - 1, cy1 + 12), fill=blue)
    for x in range(cx0 + 30, cx1, 62):
        draw.line((x, cy1 + 13, x - 10, cy1 + 24), fill=black, width=3)
        draw.line((x + 1, cy1 + 13, x - 9, cy1 + 24), fill=blue)


def _gantry_paint_cabinet(image: Image.Image, *, beacons_lit: bool = True) -> None:
    """The sign's housing: a steel box, the recessed face, and two beacons."""
    draw = ImageDraw.Draw(image)
    black, blue, white, yellow, red = (SPECTRA6[k] for k in ("black", "blue", "white", "yellow", "red"))
    x0, y0, x1, y1 = _GANTRY_CABINET
    draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=black)
    # Bevel: a glint along the top edge, the near side in shadow.
    draw.line((x0, y0, x1 - 1, y0), fill=white)
    draw.line((x0 + 1, y0 + 2, x1 - 2, y0 + 2), fill=blue)
    draw.line((x0, y0, x0, y1 - 1), fill=blue)
    draw.line((x1 - 1, y0, x1 - 1, y1 - 1), fill=blue)
    # Panel seams down the housing's border, and the access-door hinges.
    fx0, fy0, fx1, fy1 = _GANTRY_FACE
    for x in range(x0 + 128, x1 - 64, 128):
        draw.line((x, y0 + 3, x, fy0 - 5), fill=blue)
        draw.line((x, fy1 + 5, x, y1 - 2), fill=blue)
    # The face sits in a recess: blue keyline outside, a visor's shadow along
    # the top inside.
    draw.rectangle((fx0 - 4, fy0 - 4, fx1 + 3, fy1 + 3), outline=blue)
    draw.rectangle((fx0 - 2, fy0 - 2, fx1 + 1, fy1 + 1), outline=black)
    for x in range(x0 + 8, x1 - 4, 40):
        for y in (y0 + 8, y1 - 8):
            draw.point((x, y), fill=white)
            draw.point((x + 1, y + 1), fill=blue)
    # Amber beacons on the top corners, hooded, mid-flash.
    for cx in (x0 + 46, x1 - 46):
        draw.rectangle((cx - 8, y0 - 4, cx + 8, y0), fill=black)
        draw.line((cx - 8, y0 - 4, cx + 8, y0 - 4), fill=blue)
        if beacons_lit:
            lamp = Image.new("L", image.size, 0)
            ImageDraw.Draw(lamp).ellipse((cx - 6, y0 - 17, cx + 6, y0 - 5), fill=255)
            paint_neon_mask(image, lamp, yellow, yellow, radius=4, cap=0.5, glow_minor=red, glow_minor_share=0.5,
                            ground=frozenset({black, blue}))
        else:
            draw.ellipse((cx - 6, y0 - 17, cx + 6, y0 - 5), fill=black, outline=blue)
        # The hood: a short visor over the lens.
        draw.line((cx - 8, y0 - 19, cx + 8, y0 - 19), fill=black, width=2)
        draw.line((cx - 8, y0 - 20, cx + 8, y0 - 20), fill=blue)
        draw.point((cx - 3, y0 - 14), fill=white)
        draw.point((cx - 2, y0 - 14), fill=white)


def _gantry_paint_guide(image: Image.Image, title: str, subtitle: str, tab: str) -> None:
    """A green guide sign at the roadside: ``title`` as the destination,
    ``subtitle`` under it, and ``tab`` on the exit tab above."""
    draw = ImageDraw.Draw(image)
    green, white, black = SPECTRA6["green"], SPECTRA6["white"], SPECTRA6["black"]
    x0, y0, x1, y1 = _GANTRY_GUIDE
    for px_ in (x0 + 40, x1 - 40):
        draw.rectangle((px_ - 3, y1, px_ + 3, 480), fill=black)
        draw.line((px_ - 3, y1, px_ - 3, 480), fill=SPECTRA6["blue"])
    tab_font = load_font([BARLOWCOND_BOLD, *META_FONT_BOLD_CANDIDATES], size=17)
    tab_w = int(draw.textlength(tab, font=tab_font)) + 18
    draw.rounded_rectangle((x0 + 10, y0 - 22, x0 + 10 + tab_w, y0 + 4), radius=4, fill=green)
    draw.rounded_rectangle((x0 + 12, y0 - 20, x0 + 8 + tab_w, y0 + 4), radius=3, outline=white, width=1)
    draw.text((x0 + 10 + tab_w // 2, y0 - 9), tab, font=tab_font, fill=white, anchor="mm")
    draw.rounded_rectangle((x0, y0, x1, y1), radius=6, fill=green)
    draw.rounded_rectangle((x0 + 3, y0 + 3, x1 - 3, y1 - 3), radius=4, outline=white, width=2)
    inner = x1 - x0 - 26
    if title:
        font, text = fit_text_to_width(draw, title, [BARLOWCOND_SEMIBOLD, *META_FONT_BOLD_CANDIDATES], 28, inner, floor=18)
        draw.text(((x0 + x1) // 2, y0 + 25), text, font=font, fill=white, anchor="mm")
    if subtitle:
        font, text = fit_text_to_width(draw, subtitle, [BARLOWCOND_SEMIBOLD, *META_FONT_BOLD_CANDIDATES], 20, inner, floor=15)
        draw.text(((x0 + x1) // 2, y0 + 54), text, font=font, fill=white, anchor="mm")


def render_gantry_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """An overhead highway message sign at night (see the section comment).

    Composed at the canonical 800x480 and NEAREST-downsampled for other
    sizes (``metro`` convention).
    """
    image = Image.new("RGB", (800, 480), SPECTRA6["black"])
    _gantry_paint_backdrop(image)
    _gantry_paint_road(image)
    _gantry_paint_steel(image)
    _gantry_paint_cabinet(image)
    _gantry_paint_face(image, _gantry_words(quote_row), seed=_row_digest(quote_row))
    # The source is the destination; the hour is the exit number, the
    # theme's one time surface besides the matched phrase.
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "")
    _gantry_paint_guide(image, title, (quote_row.get("author") or "").strip(), f"EXIT {_clock_hour12(time_str)}")
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


# The sleep frame: the small hours on the same motorway. The traffic has
# gone, the beacons are dark, and the sign has been set to the message every
# highway authority runs at three in the morning.
_GANTRY_SLEEP_MESSAGE = (("TIRED?", True), ("REST AREA", False), ("NEXT EXIT ->", False))


def render_gantry_sleep(time_str: str, width: int, height: int) -> Image.Image:
    """The quiet-hours frame (see the comment above). ``time_str`` is unused:
    the rest area has no exit number, so nothing on the frame tells the time."""
    del time_str
    image = Image.new("RGB", (800, 480), SPECTRA6["black"])
    _gantry_paint_backdrop(image)
    _gantry_paint_road(image, traffic=False)
    _gantry_paint_steel(image)
    _gantry_paint_cabinet(image, beacons_lit=False)
    lines = [_gantry_segment_words([(text, lit)]) for text, lit in _GANTRY_SLEEP_MESSAGE]
    _gantry_paint_face(image, fixed=lines)
    _gantry_paint_guide(image, "Rest Area", "Next Right", "EXIT")
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("gantry",), render=render_gantry_frame, sleep=render_gantry_sleep)
