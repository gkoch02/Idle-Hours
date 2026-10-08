"""The ``platform`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..furniture import _clock_hh_mm, fallback_title
from ..layout import strip_underscore_emphasis, tokenize_quote
from ..palette import SPECTRA6, SPECTRA6_PALETTE, gray_pixel_access, snap_image_to_palette
from ..primitives import paint_neon_mask
from ..spec import FrameSpec
from ._shared import _gantry_dot, _gantry_glyph, _gantry_tokens

# ---------------------------------------------------------------------------
# platform — a railway departure board, hung from a station canopy at night.
#
# The board is the classic amber dot-matrix platform indicator: the next
# train's time and destination across the top ("via" its author underneath),
# the quote as the "Calling at:" message, and the station clock at the foot.
#
# **Weight is dot size.** Lumen's Round instances differ only in how big each
# dot is, so the body is set in Round Medium (airy dots, 66% of the cell) and
# the matched phrase in Round Bold (86%): the time phrase stands out the way
# a heavier weight does on a real board, with no change of colour.
#
# The dots are placed from the face's own grid (the Lumen reader shared with
# ``gantry``) and drawn at the diameters measured from those two instances,
# because drawing the outlines straight onto the panel put each dot's centre
# between pixels and rendered the same dot two different sizes. Unlike
# ``gantry``'s single lattice, every element here picks its own pitch, so the
# clock and destination run bigger than the message, and an unlit dot is not
# drawn at all: a dot-matrix board in a dark station is black where it is off.
#
# **A departure board is a clock,** so this is one of the themes that prints
# HH:MM: the departure time of the 1st train and the station clock under it.
# ---------------------------------------------------------------------------

_PLATFORM_BOARD = (14, 30, 786, 472)
_PLATFORM_WINDOW = (30, 46, 770, 456)
_PLATFORM_INSET = 16                 # text margin inside the window
# Dot diameter as a share of the pitch, measured from the face: a dot of the
# Round Medium instance spans 66 of its 100-unit cell, Round Bold 86.
_PLATFORM_MEDIUM_DOT = 0.66
_PLATFORM_BOLD_DOT = 0.86
# Row pitches of the furniture, and the dot pitches the message may take.
_PLATFORM_HEAD_PITCH = 4
_PLATFORM_VIA_PITCH = 3
_PLATFORM_CLOCK_PITCH = 6
_PLATFORM_SECONDS_PITCH = 4
_PLATFORM_MESSAGE_PITCHES = (7, 6, 5, 4, 3)
_PLATFORM_LINE_ROWS = (10, 9)
_PLATFORM_GLYPH_ROWS = 11
_PLATFORM_WORD_GAP = 3
# Where each band sits, as the top of its glyph cells (row 0) in pixels.
_PLATFORM_HEAD_TOP = 52
_PLATFORM_VIA_TOP = 96
_PLATFORM_LABEL_TOP = 130           # the "Calling at:" label, at the via pitch
_PLATFORM_MESSAGE = (164, 392)       # top and bottom of the message band
_PLATFORM_CLOCK_TOP = 392


def _platform_diameter(pitch: int, bold: bool) -> int:
    """The dot a Round Medium or Round Bold glyph has at ``pitch``.

    Medium rounds down and Bold to nearest, so the two always differ by at
    least a pixel: at 4 px both would round to 3, and a 3 px dot one pixel
    from its neighbour reads as a grid of squares. (Dropping its corners was
    tried; up close the board read as cross-stitch.)
    """
    if bold:
        return max(2, round(_PLATFORM_BOLD_DOT * pitch))
    return max(1, int(_PLATFORM_MEDIUM_DOT * pitch + 0.3))


def _platform_words(text: str, bold: bool = False) -> list[list[tuple[str, bool]]]:
    """Plain ``text`` as words of ``(glyph, is_bold)``."""
    return _platform_segment_words([(text, bold)])


def _platform_segment_words(segments) -> list[list[tuple[str, bool]]]:
    words: list[list[tuple[str, bool]]] = []
    current: list[tuple[str, bool]] = []
    for segment, bold in segments:
        for token in _gantry_tokens(segment):
            if token.isspace():
                if current:
                    words.append(current)
                current = []
                continue
            current.append((token, bold))
    if current:
        words.append(current)
    return words


def _platform_word_width(word) -> int:
    return sum(max(1, _gantry_glyph(ch)[0]) for ch, _ in word) + len(word) - 1


def _platform_line_width(line) -> int:
    return sum(_platform_word_width(w) for w in line) + _PLATFORM_WORD_GAP * max(0, len(line) - 1)


def _platform_wrap(words, measure: int) -> list[list]:
    """Greedy, ragged-right wrap to ``measure`` columns, as a board sets it;
    an over-long word is broken."""
    lines: list[list] = []
    line: list = []
    width = 0
    for word in words:
        while _platform_word_width(word) > measure and len(word) > 1:
            cut = len(word) - 1
            while cut > 1 and _platform_word_width(word[:cut]) > measure:
                cut -= 1
            if line:
                lines.append(line)
                line, width = [], 0
            lines.append([word[:cut]])
            word = word[cut:]
        w = _platform_word_width(word)
        if line and width + _PLATFORM_WORD_GAP + w > measure:
            lines.append(line)
            line, width = [], 0
        width = w if not line else width + _PLATFORM_WORD_GAP + w
        line.append(word)
    if line:
        lines.append(line)
    return lines


def _platform_truncate(words, measure: int) -> list:
    """One line of ``words`` cut to ``measure`` columns, ending in dots when
    something had to go (a board truncates a long destination)."""
    line: list = []
    for word in words:
        if _platform_line_width([*line, word]) <= measure:
            line.append(word)
            continue
        ellipsis = [(".", word[0][1])] * 3
        partial: list = []
        for glyph in word:
            if _platform_line_width([*line, [*partial, glyph, *ellipsis]]) > measure:
                break
            partial.append(glyph)
        if partial:
            line.append([*partial, *ellipsis])
        elif line:
            line[-1] = [*line[-1], *ellipsis]
            while line and _platform_line_width(line) > measure:
                last = line[-1]
                line[-1] = [*last[:-4], *ellipsis] if len(last) > 4 else ellipsis
                if len(last) <= 4:
                    break
        break
    return line


def _platform_cells(line, x0: int = 0, y0: int = 0) -> list[tuple[int, int, bool]]:
    """``(col, row, is_bold)`` for every lit dot of ``line``, from ``(x0, y0)``."""
    cells = []
    x = x0
    for word_index, word in enumerate(line):
        if word_index:
            x += _PLATFORM_WORD_GAP
        for char_index, (ch, bold) in enumerate(word):
            if char_index:
                x += 1
            width, glyph = _gantry_glyph(ch)
            cells.extend((x + c, y0 + r, bold) for c, r in glyph)
            x += max(1, width)
    return cells


def _platform_paint_dots(masks, cells, left: int, top: int, pitch: int) -> None:
    """Paint ``cells`` as round dots on a ``pitch`` grid whose cell ``(0, 0)``
    has its corner at ``(left, top)``: Medium dots into ``masks[False]``, Bold
    into ``masks[True]``."""
    access = {bold: gray_pixel_access(mask) for bold, mask in masks.items()}
    width, height = masks[False].size
    for c, r, bold in cells:
        diameter = min(pitch, _platform_diameter(pitch, bold))
        inset = (pitch - diameter) // 2
        x, y = left + c * pitch + inset, top + r * pitch + inset
        mp = access[bold]
        for dx, dy in _gantry_dot(diameter):
            if 0 <= x + dx < width and 0 <= y + dy < height:
                mp[x + dx, y + dy] = 255


def _platform_fit_message(words, width: int, height: int):
    """``(pitch, line_rows, lines)``: the largest pitch the message fits."""
    for pitch in _PLATFORM_MESSAGE_PITCHES:
        cols, rows = width // pitch, height // pitch
        lines = _platform_wrap(words, cols)
        for line_rows in _PLATFORM_LINE_ROWS:
            max_lines = (rows - _PLATFORM_GLYPH_ROWS) // line_rows + 1
            if len(lines) <= max_lines:
                return pitch, line_rows, lines
    return pitch, line_rows, lines[:max_lines]


def _platform_message_words(quote_row: dict) -> list[list[tuple[str, bool]]]:
    """The quote as the board's message, the matched phrase in Round Bold."""
    text = strip_underscore_emphasis(quote_row.get("display_quote") or "")
    return _platform_segment_words(tokenize_quote(text, quote_row.get("matched_text") or ""))


# --- the board --------------------------------------------------------------

def _platform_paint_station(image: Image.Image) -> None:
    """The canopy overhead, the two hangers, and the board's housing."""
    draw = ImageDraw.Draw(image)
    black, blue, white = SPECTRA6["black"], SPECTRA6["blue"], SPECTRA6["white"]
    # Canopy: an I-beam and the purlins running back into the dark.
    draw.rectangle((0, 0, 800, 12), fill=black)
    draw.line((0, 12, 800, 12), fill=blue)
    draw.line((0, 3, 800, 3), fill=blue)
    for x in range(20, 800, 96):
        draw.line((x, 12, x + 10, 22), fill=blue)
    x0, y0, x1, y1 = _PLATFORM_BOARD
    # Hangers: drop rods with a clamp at each end.
    for hx in (x0 + 120, x1 - 120):
        draw.rectangle((hx - 2, 12, hx + 2, y0), fill=black)
        draw.line((hx - 2, 12, hx - 2, y0), fill=blue)
        draw.line((hx + 2, 12, hx + 2, y0), fill=white)
        for cy in (12, y0 - 6):
            draw.rectangle((hx - 6, cy, hx + 6, cy + 5), fill=black, outline=blue)
    # Housing: a dark steel case with a glint on its top edge.
    draw.rounded_rectangle((x0, y0, x1, y1), radius=8, fill=black, outline=blue)
    draw.line((x0 + 8, y0, x1 - 8, y0), fill=white)
    wx0, wy0, wx1, wy1 = _PLATFORM_WINDOW
    draw.rectangle((wx0 - 3, wy0 - 3, wx1 + 2, wy1 + 2), outline=blue)
    for cx, cy in ((x0 + 8, y0 + 8), (x1 - 9, y0 + 8), (x0 + 8, y1 - 9), (x1 - 9, y1 - 9)):
        draw.rectangle((cx - 1, cy - 1, cx + 1, cy + 1), fill=blue)
        draw.point((cx - 1, cy - 1), fill=white)


def _platform_paint_dots_lit(image: Image.Image, masks) -> None:
    """The lit dots in amber. The Bold ones sit in a faint red bloom, kept
    inside the display window; the Medium ones get none, since a bloom round
    a dot that small only muddies the black between them."""
    wx0, wy0, _, _ = _PLATFORM_WINDOW
    window = image.crop(_PLATFORM_WINDOW)
    paint_neon_mask(window, masks[True].crop(_PLATFORM_WINDOW), SPECTRA6["yellow"], SPECTRA6["red"],
                    radius=1.6, cap=0.4, ground=frozenset({SPECTRA6["black"]}))
    window.paste(SPECTRA6["yellow"], (0, 0), masks[False].crop(_PLATFORM_WINDOW))
    image.paste(window, (wx0, wy0))


def _platform_paint_board(image: Image.Image, *, head, via=(), via_indent: int = 0, status=(), label=(),
                          message=(), clock: str | None = None) -> None:
    """Every lit dot on the board, each argument a list of words.

    ``head`` is the top row (the departure and destination); ``via`` sits
    under it, ``via_indent`` pixels in so it lines up with the destination,
    with ``status`` right-aligned on the same row; ``label`` heads the
    ``message``; ``clock`` is the station clock's HH:MM (``None`` leaves the
    clock dark).
    """
    masks = {bold: Image.new("L", image.size, 0) for bold in (False, True)}
    wx0, _, wx1, _ = _PLATFORM_WINDOW
    left = wx0 + _PLATFORM_INSET
    inner = wx1 - wx0 - 2 * _PLATFORM_INSET
    hp, vp = _PLATFORM_HEAD_PITCH, _PLATFORM_VIA_PITCH
    _platform_paint_dots(masks, _platform_cells(_platform_truncate(head, inner // hp)), left, _PLATFORM_HEAD_TOP, hp)
    status_w = _platform_line_width(status) if status else 0
    if status:
        _platform_paint_dots(masks, _platform_cells(status, inner // vp - status_w), left, _PLATFORM_VIA_TOP, vp)
    if via:
        room = (inner - via_indent) // vp - status_w - 6
        _platform_paint_dots(masks, _platform_cells(_platform_truncate(via, room)), left + via_indent, _PLATFORM_VIA_TOP, vp)
    # The label is fixed small: set at the message's pitch, a short quote
    # made it a headline.
    if label:
        _platform_paint_dots(masks, _platform_cells(label), left, _PLATFORM_LABEL_TOP, vp)
    # The message, left-aligned and centred in its band.
    if message:
        top, bottom = _PLATFORM_MESSAGE
        pitch, line_rows, lines = _platform_fit_message(message, inner, bottom - top)
        used = (len(lines) - 1) * line_rows + _PLATFORM_GLYPH_ROWS
        y = top + max(0, ((bottom - top) // pitch - used) // 2) * pitch
        for index, line in enumerate(lines):
            _platform_paint_dots(masks, _platform_cells(line, 0, index * line_rows), left, y, pitch)
    # Station clock: HH:MM big, the seconds small on the same baseline.
    if clock is not None:
        big = _platform_words(clock, bold=True)
        small = _platform_words(":00", bold=True)
        cp, sp = _PLATFORM_CLOCK_PITCH, _PLATFORM_SECONDS_PITCH
        big_w = _platform_line_width(big) * cp
        small_w = _platform_line_width(small) * sp
        cx = (wx0 + wx1 - big_w - small_w - sp) // 2
        _platform_paint_dots(masks, _platform_cells(big), cx, _PLATFORM_CLOCK_TOP, cp)
        # The baselines meet: row 9 of each grid.
        _platform_paint_dots(masks, _platform_cells(small), cx + big_w + sp, _PLATFORM_CLOCK_TOP + 9 * (cp - sp), sp)
    _platform_paint_dots_lit(image, masks)


def _platform_frame(paint) -> Image.Image:
    image = Image.new("RGB", (800, 480), SPECTRA6["black"])
    _platform_paint_station(image)
    paint(image)
    return snap_image_to_palette(image, SPECTRA6_PALETTE)


def _platform_finish(image: Image.Image, width: int, height: int) -> Image.Image:
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


def render_platform_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A railway departure board (see the section comment).

    Composed at the canonical 800x480 and NEAREST-downsampled for other
    sizes (``metro`` convention).
    """
    hour, minute = _clock_hh_mm(time_str)
    clock = f"{hour:02d}:{minute:02d}"
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "")
    author = (quote_row.get("author") or "").strip()
    lead = [*_platform_words("1st"), *_platform_words(clock, bold=True)]
    head = [*lead, *_platform_words(title, bold=True)]
    # "via" lines up under the destination, past "1st HH:MM".
    via_indent = (_platform_line_width(lead) + _PLATFORM_WORD_GAP) * _PLATFORM_HEAD_PITCH
    via = _platform_words(f"via {author}") if author else []

    def paint(image: Image.Image) -> None:
        _platform_paint_board(image, head=head, via=via, via_indent=via_indent, status=_platform_words("On time"),
                              label=_platform_words("Calling at:"), message=_platform_message_words(quote_row),
                              clock=clock)

    return _platform_finish(_platform_frame(paint), width, height)


# The sleep frame: the board after the last train. "Good night." takes the
# Round Bold the matched phrase has by day; the clock is left dark, so nothing
# on the frame tells the time.
_PLATFORM_SLEEP_HEAD = "No further departures"
_PLATFORM_SLEEP_VIA = "from this platform"
_PLATFORM_SLEEP_MESSAGE = (("Good night.", True),
                           (" The last train has gone. Services resume in the morning.", False))


def render_platform_sleep(time_str: str, width: int, height: int) -> Image.Image:
    """The quiet-hours frame (see the comment above). ``time_str`` is unused."""
    del time_str

    def paint(image: Image.Image) -> None:
        _platform_paint_board(image, head=_platform_words(_PLATFORM_SLEEP_HEAD, bold=True),
                              via=_platform_words(_PLATFORM_SLEEP_VIA),
                              message=_platform_segment_words(_PLATFORM_SLEEP_MESSAGE))

    return _platform_finish(_platform_frame(paint), width, height)


SPEC = FrameSpec(themes=("platform",), render=render_platform_frame, sleep=render_platform_sleep)
