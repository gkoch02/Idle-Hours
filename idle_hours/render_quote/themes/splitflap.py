"""The ``splitflap`` theme: a split-flap message board on a wall.

Design notes: docs/themes.md § splitflap
"""

from __future__ import annotations

import functools
import random
import unicodedata

from PIL import Image, ImageDraw

from ..fonts import load_font, theme_font_candidates
from ..furniture import _row_digest, fallback_title
from ..layout import strip_underscore_emphasis, tokenize_quote
from ..palette import SPECTRA6, SPECTRA6_PALETTE, pixel_access, snap_image_to_palette
from ..primitives import _fill_swatch_stipple, position_noise
from ..spec import FrameSpec

_SPLITFLAP_COLS = 32
_SPLITFLAP_ROWS = 12
_SPLITFLAP_PITCH = (23, 36)                 # tile pitch, x and y
_SPLITFLAP_TILE = (21, 33)                  # one tile; the rest is the gap between tiles
_SPLITFLAP_HINGE = 16                       # y of the gap between a tile's two flaps
_SPLITFLAP_ORIGIN = ((800 - _SPLITFLAP_COLS * 23) // 2, (480 - _SPLITFLAP_ROWS * 36) // 2 + 2)
_SPLITFLAP_QUOTE_ROWS = 9                   # the quote's rows; a blank row, then the byline
_SPLITFLAP_LETTER_SIZE = 29                 # Bebas Neue at a 21 px cap height
_SPLITFLAP_FLIPS = 2
# The board's character set (a Vestaboard's), and what a character outside it
# becomes. Anything else with no stand-in is dropped: a flap board can show
# only what is printed on its flaps.
_SPLITFLAP_CHARSET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$()-+&=;:'\"%,./?°")
_SPLITFLAP_STANDINS = {
    "‘": "'", "’": "'", "“": '"', "”": '"', "′": "'", "″": '"',
    "—": "-", "–": "-", "…": "...", "[": "(", "]": ")", "{": "(", "}": ")",
    "Œ": "OE", "Æ": "AE", "£": "L", "ß": "SS",
}
# Colour tiles: the panel's own inks, and orange and violet stippled.
_SPLITFLAP_RAINBOW = ("red", "orange", "yellow", "green", "blue", "violet")


# --- the message on the grid -------------------------------------------------

def _splitflap_chars(ch: str) -> str:
    """``ch`` as the characters the board's flaps carry ('' when none)."""
    up = ch.upper()
    if up in _SPLITFLAP_CHARSET or up == " ":
        return up
    if up in _SPLITFLAP_STANDINS:
        return _SPLITFLAP_STANDINS[up]
    base = unicodedata.normalize("NFKD", up).encode("ascii", "ignore").decode("ascii")
    return "".join(c for c in base if c in _SPLITFLAP_CHARSET)


def _splitflap_words(segments) -> list[list[tuple[str, bool]]]:
    """``(text, is_matched)`` segments as words of ``(char, is_matched)``."""
    words: list[list[tuple[str, bool]]] = []
    current: list[tuple[str, bool]] = []
    for text, matched in segments:
        for ch in text:
            if ch.isspace():
                if current:
                    words.append(current)
                current = []
                continue
            current.extend((c, matched) for c in _splitflap_chars(ch))
    if current:
        words.append(current)
    return words


def _splitflap_wrap(words, cols: int) -> list[list[tuple[str, bool]]]:
    """Words wrapped to ``cols`` tiles, a space tile between words; a word
    longer than a row is broken across rows."""
    lines: list[list[tuple[str, bool]]] = []
    line: list[tuple[str, bool]] = []
    for word in words:
        while len(word) > cols:
            if line:
                lines.append(line)
                line = []
            lines.append(word[:cols])
            word = word[cols:]
        if line and len(line) + 1 + len(word) > cols:
            lines.append(line)
            line = []
        if line:
            # The space between two words takes the phrase's colour only
            # when both sides of it are in the phrase.
            line.append((" ", line[-1][1] and word[0][1]))
        line.extend(word)
    if line:
        lines.append(line)
    return lines


def _splitflap_byline(quote_row: dict, cols: int) -> list[tuple[str, bool]]:
    """``-AUTHOR, TITLE`` for the bottom row, the title dropped first and the
    author cut short last when the row is too narrow."""
    author = "".join(_splitflap_chars(c) for c in (quote_row.get("author") or "").strip())
    title = "".join(_splitflap_chars(c) for c in
                    ((quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "")))
    for text in (f"-{author}, {title}" if author and title else "", f"-{author}" if author else "", f"-{title}"):
        if text and len(text) <= cols:
            return [(c, False) for c in text]
    return [(c, False) for c in (f"-{author or title}")[:cols]]


def _splitflap_layout(quote_row: dict) -> dict[tuple[int, int], tuple[str, bool]]:
    """``{(col, row): (char, is_matched)}`` for every character tile: the
    quote centred line by line in its rows, the byline right-aligned on the
    bottom row."""
    text = strip_underscore_emphasis(quote_row.get("display_quote") or "")
    words = _splitflap_words(tokenize_quote(text, quote_row.get("matched_text") or ""))
    lines = _splitflap_wrap(words, _SPLITFLAP_COLS)[:_SPLITFLAP_QUOTE_ROWS]
    tiles: dict[tuple[int, int], tuple[str, bool]] = {}
    top = (_SPLITFLAP_QUOTE_ROWS - len(lines)) // 2
    for index, line in enumerate(lines):
        left = (_SPLITFLAP_COLS - len(line)) // 2
        for offset, glyph in enumerate(line):
            tiles[(left + offset, top + index)] = glyph
    room = _SPLITFLAP_COLS - len(_SPLITFLAP_RAINBOW) - 2
    byline = _splitflap_byline(quote_row, room)
    for offset, glyph in enumerate(byline):
        tiles[(_SPLITFLAP_COLS - len(byline) + offset, _SPLITFLAP_ROWS - 1)] = glyph
    return tiles


# --- tiles ------------------------------------------------------------------

def _splitflap_font():
    return load_font(theme_font_candidates("splitflap", "quote_regular"), size=_SPLITFLAP_LETTER_SIZE)


@functools.lru_cache(maxsize=256)
def _splitflap_letter_mask(ch: str) -> Image.Image:
    """``ch`` as a hard-edged mask the size of one tile, centred on its cap
    height (a threshold, since antialiased edges would snap to stray inks)."""
    w, h = _SPLITFLAP_TILE
    mask = Image.new("L", (w, h), 0)
    if ch.strip():
        font = _splitflap_font()
        draw = ImageDraw.Draw(mask)
        cap = draw.textbbox((0, 0), "H", font=font)
        box = draw.textbbox((0, 0), ch, font=font)
        x = (w - (box[2] - box[0])) // 2 - box[0]
        y = (h - (cap[3] - cap[1])) // 2 - cap[1] + 1
        draw.text((x, y), ch, font=font, fill=255)
    return mask.point(lambda v: 255 if v > 110 else 0)


def _splitflap_paint_ground(tile: Image.Image, colour: str) -> None:
    """A tile's face: charcoal for a letter tile, else a colour tile."""
    w, h = tile.size
    rect = (0, 0, w, h)
    if colour == "orange":
        _fill_swatch_stipple(tile, rect, SPECTRA6["red"], SPECTRA6["yellow"], 0.375)
    elif colour == "violet":
        _fill_swatch_stipple(tile, rect, SPECTRA6["red"], SPECTRA6["blue"], 0.5)
    elif colour == "charcoal":
        # Black, with a dotted sheen along the top edge so each tile reads
        # against the black gaps between tiles. (A blue scatter over the
        # whole face lined up into diagonal hatching across the board.)
        px = pixel_access(tile)
        for x in range(1, w - 1, 2):
            px[x, 0] = SPECTRA6["blue"]
    else:
        tile.paste(SPECTRA6[colour], rect)


def _splitflap_paint_hinge(tile: Image.Image) -> None:
    """The gap between the two flaps, and the sheen on the lower flap's edge
    and the tile's top edge."""
    draw = ImageDraw.Draw(tile)
    w, _ = tile.size
    draw.line((0, _SPLITFLAP_HINGE, w - 1, _SPLITFLAP_HINGE), fill=SPECTRA6["black"])
    draw.line((0, _SPLITFLAP_HINGE + 1, w - 1, _SPLITFLAP_HINGE + 1), fill=SPECTRA6["black"])
    # Axle pins either side of the hinge.
    draw.point((0, _SPLITFLAP_HINGE), fill=SPECTRA6["white"])
    draw.point((w - 1, _SPLITFLAP_HINGE), fill=SPECTRA6["white"])


@functools.lru_cache(maxsize=512)
def _splitflap_tile(ch: str, colour: str, ink: str) -> Image.Image:
    """One tile: ``ch`` in ``ink`` on a ``colour`` face, split by the hinge."""
    tile = Image.new("RGB", _SPLITFLAP_TILE, SPECTRA6["black"])
    _splitflap_paint_ground(tile, colour)
    tile.paste(SPECTRA6[ink], (0, 0), _splitflap_letter_mask(ch))
    _splitflap_paint_hinge(tile)
    return tile


def _splitflap_flip_tile(new: str, old: str) -> Image.Image:
    """A tile caught mid-flip: the top half already ``new``, the bottom half
    still ``old``, and the falling flap seen edge-on at the hinge, a dark
    sliver a pixel wider than the tile either side.

    A foreshortened half-letter on the falling flap was tried: at this tile
    size it read as an underline under a crossbar.
    """
    w, h = _SPLITFLAP_TILE
    hinge = _SPLITFLAP_HINGE
    tile = Image.new("RGB", (w + 2, h), SPECTRA6["black"])
    tile.paste(_splitflap_tile(new, "charcoal", "white"), (1, 0))
    tile.paste(_splitflap_tile(old, "charcoal", "white").crop((0, hinge, w, h)), (1, hinge))
    draw = ImageDraw.Draw(tile)
    # The flap's edge is dark with a blue glint: a white edge crossed the
    # letter at mid-height and read as a strikethrough.
    draw.rectangle((0, hinge, w + 1, hinge + 3), fill=SPECTRA6["black"])
    draw.line((0, hinge + 3, w + 1, hinge + 3), fill=SPECTRA6["blue"])
    return tile


def _splitflap_tile_xy(col: int, row: int) -> tuple[int, int]:
    ox, oy = _SPLITFLAP_ORIGIN
    return ox + col * _SPLITFLAP_PITCH[0], oy + row * _SPLITFLAP_PITCH[1]


# --- the board ---------------------------------------------------------------

def _splitflap_paint_wall(image: Image.Image) -> None:
    """A pale wall, the board's black frame on it, and the frame's shadow."""
    width, height = image.size
    # Warm off-white: a 1-in-16 yellow scatter. A 1-in-4 lattice read as a
    # mustard wall on the panel's greenish yellow.
    px = pixel_access(image)
    for y in range(height):
        for x in range(width):
            px[x, y] = SPECTRA6["yellow"] if position_noise(x, y) < 16 else SPECTRA6["white"]
    draw = ImageDraw.Draw(image)
    ox, oy = _SPLITFLAP_ORIGIN
    x1 = ox + _SPLITFLAP_COLS * _SPLITFLAP_PITCH[0]
    y1 = oy + _SPLITFLAP_ROWS * _SPLITFLAP_PITCH[1]
    frame = (ox - 12, oy - 12, x1 + 10, y1 + 9)
    draw.rectangle((frame[0] + 4, frame[1] + 4, frame[2] + 4, frame[3] + 4), fill=SPECTRA6["black"])
    draw.rectangle(frame, fill=SPECTRA6["black"])
    draw.rectangle((frame[0] + 3, frame[1] + 3, frame[2] - 3, frame[3] - 3), outline=SPECTRA6["blue"])


def _splitflap_paint_tiles(image: Image.Image, tiles, colours, flips=()) -> None:
    """Every tile of the grid. ``tiles`` maps ``(col, row)`` to ``(char,
    is_matched)``; ``colours`` maps a position to a colour tile; ``flips``
    maps a position to the old character a mid-flip tile is leaving."""
    flips = dict(flips)
    falling = []
    for row in range(_SPLITFLAP_ROWS):
        for col in range(_SPLITFLAP_COLS):
            x, y = _splitflap_tile_xy(col, row)
            if (col, row) in colours:
                image.paste(_splitflap_tile(" ", colours[(col, row)], "white"), (x, y))
                continue
            ch, matched = tiles.get((col, row), (" ", False))
            if (col, row) in flips:
                falling.append((_splitflap_flip_tile(ch, flips[(col, row)]), x - 1, y))
            elif matched:
                image.paste(_splitflap_tile(ch, "yellow", "black"), (x, y))
            else:
                image.paste(_splitflap_tile(ch, "charcoal", "white"), (x, y))
    # Mid-flip tiles go on last: the falling flap overhangs the tile.
    for tile, x, y in falling:
        image.paste(tile, (x, y))


def _splitflap_flips(tiles, seed: int) -> dict[tuple[int, int], str]:
    """Two letter tiles outside the matched phrase, caught mid-flip, and the
    letter each is leaving; which tiles is fixed per quote."""
    candidates = sorted(pos for pos, (ch, matched) in tiles.items()
                        if ch.isalpha() and not matched and pos[1] < _SPLITFLAP_QUOTE_ROWS)
    chosen = random.Random(seed).sample(candidates, min(_SPLITFLAP_FLIPS, len(candidates)))
    # Flaps turn in order, so the letter a tile is leaving is the one before.
    letters = "ZABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return {pos: letters[letters.index(tiles[pos][0], 1) - 1] for pos in chosen}


def _splitflap_finish(image: Image.Image, width: int, height: int) -> Image.Image:
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


def render_splitflap_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A split-flap message board (see docs/themes.md).

    Composed at the canonical 800x480 and NEAREST-downsampled for other
    sizes (``metro`` convention). Nothing reads the time: the matched phrase
    carries it.
    """
    del time_str
    image = Image.new("RGB", (800, 480), SPECTRA6["white"])
    _splitflap_paint_wall(image)
    tiles = _splitflap_layout(quote_row)
    colours = {(col, _SPLITFLAP_ROWS - 1): name for col, name in enumerate(_SPLITFLAP_RAINBOW)}
    _splitflap_paint_tiles(image, tiles, colours, _splitflap_flips(tiles, _row_digest(quote_row)))
    return _splitflap_finish(image, width, height)


# The sleep frame: tile art, the way people decorate a real board. A crescent
# moon in yellow tiles and a scatter of white star tiles over GOOD NIGHT / SEE
# YOU IN THE MORNING; nothing tells the time.
_SPLITFLAP_SLEEP_LINES = ((6, "GOOD NIGHT"), (8, "SEE YOU IN THE MORNING"))
_SPLITFLAP_MOON = ((26, 1), (27, 1), (25, 2), (26, 2), (25, 3), (26, 3), (26, 4), (27, 4))
_SPLITFLAP_STARS = ((3, 1), (9, 0), (14, 3), (19, 1), (30, 2), (6, 4), (21, 10), (29, 9))


def render_splitflap_sleep(time_str: str, width: int, height: int) -> Image.Image:
    """The quiet-hours frame (see the comment above). ``time_str`` is unused."""
    del time_str
    image = Image.new("RGB", (800, 480), SPECTRA6["white"])
    _splitflap_paint_wall(image)
    tiles = {}
    for row, text in _SPLITFLAP_SLEEP_LINES:
        left = (_SPLITFLAP_COLS - len(text)) // 2
        for offset, ch in enumerate(text):
            tiles[(left + offset, row)] = (ch, False)
    colours = {pos: "yellow" for pos in _SPLITFLAP_MOON}
    colours.update({pos: "white" for pos in _SPLITFLAP_STARS})
    _splitflap_paint_tiles(image, tiles, colours)
    return _splitflap_finish(image, width, height)


SPEC = FrameSpec(themes=("splitflap",), render=render_splitflap_frame, sleep=render_splitflap_sleep)
