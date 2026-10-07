"""The ``redacted`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import random
import re
from typing import Any

from PIL import Image, ImageDraw

from .._paths import ARCHIVO_BOLD, META_FONT_BOLD_CANDIDATES
from ..fonts import load_font, theme_font_candidates
from ..furniture import _place_quote, _row_digest, fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, gray_pixel_access, pixel_access, snap_image_to_palette
from ..primitives import position_noise
from ..spec import FrameSpec
from ..text import draw_tracked, fit_text_to_width

# ---------------------------------------------------------------------------
# redacted — a declassified Bureau document, after Remedy's *Control* (2019)
# ---------------------------------------------------------------------------
# The quote as one of the collectible documents the Federal Bureau of Control
# leaves lying around the Oldest House: a typed memo under the Bureau's
# letterhead, a red DECLASSIFIED stamp, and black bars over words the
# censor decided you were not cleared for. ``control`` is the game's title
# card; this is its paperwork.
#
# **The censor never touches the time.** Bars land only on non-phrase words
# of four letters or more that are not function words or time words
# (``_REDACTED_SPARED``), so the matched phrase and anything that reads as
# part of a time stay legible. Which words go is seeded from the quote
# (``_row_digest``): an unchanged quote never redraws differently.
#
# **Bars are a felt marker, not a rectangle tool.** Each row of a bar's ends
# wanders a pixel, and neighbouring redactions on a line join into one bar
# across the space between them, as a censor's stroke does.
#
# **The phrase is red**, the bichrome-ribbon shift ``dispatch`` uses: Special
# Elite ships one weight, so colour alone carries the difference.
#
# **No time surface beyond the matched phrase.** The file number, document
# type and clearance level are seeded from the quote, never the clock.
#
# Composed at the canonical 800x480 and NEAREST-downsampled for other sizes
# (``metro`` convention): everything is absolute panel coordinates.
# ---------------------------------------------------------------------------
_REDACTED_SEAL_CENTRE = (52, 44)
_REDACTED_SEAL_RADIUS = 22
_REDACTED_RULE_Y = 80
_REDACTED_FIELDS_Y = 92
_REDACTED_QUOTE_RECT = (64, 134, 736, 396)
_REDACTED_FOOT_RULE_Y = 410
_REDACTED_FOOT_Y = 426
_REDACTED_STAMP_CENTRE = (648, 44)
_REDACTED_TRACKING = 2
_REDACTED_LABEL_SIZE = 11
_REDACTED_VALUE_SIZE = 16
# Share of eligible words the censor takes, and the cap as a share of all
# eligible words, so a short quote is never blacked out whole.
_REDACTED_RATE = 0.32
_REDACTED_CAP = 0.45
_REDACTED_MIN_LETTERS = 4
_REDACTED_DOC_TYPES = (
    "RESEARCH NOTE",
    "MEMO",
    "INCIDENT REPORT",
    "INTERVIEW TRANSCRIPT",
    "CORRESPONDENCE",
    "AWE CASE FILE",
    "FIELD RECORDING",
)
_REDACTED_CLEARANCE_LEVELS = 7
# The sleep frame: a Standby Order from the Director's office with every word
# blacked out but "lights", early in the first line, and "out", partway along
# the last. Nobody reads the text under the bars, but its wording decides where
# those two words land, and ``TestRedactedSleepFrame`` pins that placement.
_REDACTED_SLEEP_ROW = {
    "display_quote": "The lights of the Oldest House are dimmed floor by floor, the Hotline is left to ring, "
                     "the Board falls silent, and the janitor walks each corridor until the last lamp is "
                     "put out for the night.",
    "matched_text": "",
    "author": "Office of the Director",
    "title": "Standby Order",
}
_REDACTED_SLEEP_FIELDS = ("STANDBY ORDER", "FBC-00000", "LEVEL 7")
_REDACTED_SLEEP_STAMP = "SUSPENDED"
_REDACTED_SLEEP_KEEP = ("lights", "out")
# Share of word gaps a censor's stroke carries straight across, so the bars
# read as hand-drawn runs rather than one block per word.
_REDACTED_SLEEP_JOIN = 0.35
_REDACTED_SLEEP_SEED = 0x5EE9

# Words the censor leaves alone: function words (blacking out "would" reads as
# a layout bug, not a secret) and anything that could be part of a time.
_REDACTED_SPARED = frozenset("""
    about above after again against along also among another around because been before being below
    between both cannot could does doing down during each either else even ever every from further
    have having here hers herself himself however into itself just like many might more most much must
    myself never none once only other ought ours ourselves over same shall should since some such than
    that their theirs them themselves then there these they this those though through thus till under
    unless until upon very want were what whatever when where whether which while whom whose with within
    without would your yours yourself yourselves said says shall will
    clock oclock hour hours minute minutes second seconds noon midnight morning evening night tonight
    afternoon dawn dusk twilight sunrise sunset half quarter past before till time times today
    o'clock o’clock one two three four five six seven eight nine ten eleven twelve thirteen fourteen
    fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty
    """.split())
_REDACTED_EDGE_PUNCT = "\"'“”‘’.,;:!?()[]—–-…*"
_WORD_RE = re.compile(r"\S+")


def _redacted_is_spared(core: str) -> bool:
    """Whether the censor leaves ``core`` alone: the word itself or any part
    of a compound is spared, so ``FORTY-SEVEN`` and ``half-past`` read as the
    times they are."""
    lower = core.lower()
    return lower in _REDACTED_SPARED or any(part in _REDACTED_SPARED for part in re.split(r"[-–—/]", lower))


def _redacted_doc_fields(quote_row: dict) -> tuple[str, str, str]:
    """``(document type, file number, clearance level)`` seeded from the quote."""
    digest = _row_digest(quote_row)
    doc_type = _REDACTED_DOC_TYPES[digest % len(_REDACTED_DOC_TYPES)]
    file_no = f"FBC-{(digest >> 4) % 90000 + 10000:05d}"
    clearance = f"LEVEL {(digest >> 20) % _REDACTED_CLEARANCE_LEVELS + 1}"
    return doc_type, file_no, clearance


def _redacted_candidates(draw: ImageDraw.ImageDraw, placed) -> list[tuple[int, int, int, int]]:
    """Every word the censor may take, as ``(line_index, x0, x1, y)``.

    ``x0..x1`` spans the word with its edge punctuation trimmed off, so a
    trailing comma survives beside the bar, as it does on a real document.
    A word glued to the matched phrase (``seven)``'s ``)`` side) is skipped:
    a bar there would butt against the time.
    """
    out = []
    line_ys: list[int] = []
    for i, (x, y, chunk, font, is_bold, _w, _lh) in enumerate(placed):
        if is_bold:
            continue
        line = len(line_ys) if y not in line_ys else line_ys.index(y)
        if y not in line_ys:
            line_ys.append(y)
        for m in _WORD_RE.finditer(chunk):
            word = m.group(0)
            core = word.strip(_REDACTED_EDGE_PUNCT)
            letters = sum(c.isalpha() for c in core)
            if letters < _REDACTED_MIN_LETTERS or _redacted_is_spared(core):
                continue
            touches_left = m.start() == 0 and i > 0 and placed[i - 1][4] and placed[i - 1][1] == y
            touches_right = (m.end() == len(chunk) and i + 1 < len(placed)
                             and placed[i + 1][4] and placed[i + 1][1] == y)
            if touches_left or touches_right:
                continue
            lead = len(word) - len(word.lstrip(_REDACTED_EDGE_PUNCT))
            start = m.start() + lead
            x0 = x + draw.textlength(chunk[:start], font=font)
            x1 = x0 + draw.textlength(core, font=font)
            out.append((line, int(round(x0)), int(round(x1)), y))
    return out


def _redacted_choose(candidates, quote_row: dict) -> list[tuple[int, int, int, int]]:
    """Seeded pick of the words to black out: at least one when any qualify,
    never more than ``_REDACTED_CAP`` of them."""
    if not candidates:
        return []
    rng = random.Random(_row_digest(quote_row))
    chosen = [c for c in candidates if rng.random() < _REDACTED_RATE]
    cap = max(1, int(len(candidates) * _REDACTED_CAP))
    if not chosen:
        chosen = [candidates[rng.randrange(len(candidates))]]
    return chosen[:cap]


def _redacted_bars(chosen, placed) -> list[tuple[int, int, int, int]]:
    """Merge chosen words into bars ``(x0, y0, x1, y1)``.

    Two chosen words next to each other in the candidate order on one line
    become a single bar across the gap between them, unless a spared word sat
    between them (the gap would then swallow it).
    """
    if not chosen:
        return []
    font = placed[0][3]
    top, bottom = font.getbbox("Hgjy|")[1], font.getbbox("Hgjy|")[3]
    pad_x = max(1, font.size // 14)
    space = font.getlength(" ")
    bars: list[list[int]] = []
    for line, x0, x1, y in sorted(chosen):
        if bars and bars[-1][0] == line and x0 - bars[-1][2] <= space * 2.2:
            bars[-1][2] = x1
            continue
        bars.append([line, x0, x1, y])
    return [(x0 - pad_x, y + top - 2, x1 + pad_x, y + bottom + 1) for _, x0, x1, y in bars]


def _redacted_paint_bars(image: Image.Image, bars, quote_row: dict) -> None:
    """Black marker bars: each row's ends wander a pixel either way."""
    rng = random.Random(_row_digest(quote_row) ^ 0x5EC2E7)
    px = pixel_access(image)
    width, height = image.size
    black = SPECTRA6["black"]
    for x0, y0, x1, y1 in bars:
        left, right = x0, x1
        for y in range(max(0, y0), min(height, y1 + 1)):
            left = min(x0 + 2, max(x0 - 2, left + rng.randint(-1, 1)))
            right = min(x1 + 2, max(x1 - 2, right + rng.randint(-1, 1)))
            for x in range(max(0, left), min(width, right + 1)):
                px[x, y] = black


def _redacted_paint_seal(draw: ImageDraw.ImageDraw) -> None:
    """The Bureau's device, in black on the letterhead: a ring around an
    inverted triangle with a dot at its heart."""
    cx, cy = _REDACTED_SEAL_CENTRE
    r = _REDACTED_SEAL_RADIUS
    black = SPECTRA6["black"]
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=black, width=3)
    draw.polygon([(cx - 12, cy - 9), (cx + 12, cy - 9), (cx, cy + 12)], outline=black, width=2)
    draw.ellipse((cx - 3, cy - 4, cx + 3, cy + 2), fill=black)


def _redacted_paint_letterhead(draw: ImageDraw.ImageDraw) -> None:
    """Seal, Bureau name and the Oldest House under it, then a double rule."""
    black = SPECTRA6["black"]
    _redacted_paint_seal(draw)
    candidates = [ARCHIVO_BOLD, *META_FONT_BOLD_CANDIDATES]
    x = _REDACTED_SEAL_CENTRE[0] + _REDACTED_SEAL_RADIUS + 16
    draw_tracked(draw, (x, 20), "FEDERAL BUREAU OF CONTROL", load_font(candidates, size=22), black,
                 tracking=_REDACTED_TRACKING)
    draw_tracked(draw, (x, 50), "THE OLDEST HOUSE", load_font(candidates, size=11), black, tracking=4)
    draw.line([(24, _REDACTED_RULE_Y), (776, _REDACTED_RULE_Y)], fill=black, width=3)
    draw.line([(24, _REDACTED_RULE_Y + 5), (776, _REDACTED_RULE_Y + 5)], fill=black, width=1)


def _redacted_paint_fields(draw: ImageDraw.ImageDraw, fields: tuple[str, str, str]) -> None:
    """The document's form fields ``(type, file number, clearance)`` — labels
    in the letterhead's grotesque, values typed."""
    black = SPECTRA6["black"]
    label_font = load_font([ARCHIVO_BOLD, *META_FONT_BOLD_CANDIDATES], size=_REDACTED_LABEL_SIZE)
    value_font = load_font(theme_font_candidates("redacted", "quote_regular"), size=_REDACTED_VALUE_SIZE)
    doc_type, file_no, clearance = fields
    for x, label, value in ((40, "DOCUMENT TYPE", doc_type), (380, "FILE NO.", file_no),
                            (590, "CLEARANCE", clearance)):
        w = draw_tracked(draw, (x, _REDACTED_FIELDS_Y + 4), label, label_font, black, tracking=1)
        draw.text((x + w + 8, _REDACTED_FIELDS_Y), value, font=value_font, fill=black)


def _redacted_paint_stamp(image: Image.Image, quote_row: dict, text: str = "DECLASSIFIED") -> None:
    """The red rubber stamp, double-bordered, tipped a few degrees and worn:
    the rubber's ink misses in a seeded scatter of pinholes."""
    font = load_font([ARCHIVO_BOLD, *META_FONT_BOLD_CANDIDATES], size=28)
    probe = ImageDraw.Draw(image)
    tracking = 2
    tw = int(probe.textlength(text, font=font)) + tracking * (len(text) - 1)
    pad = 12
    mask = Image.new("L", (tw + 2 * pad, 56), 0)
    md = ImageDraw.Draw(mask)
    md.rectangle((0, 0, mask.width - 1, mask.height - 1), outline=255, width=3)
    md.rectangle((5, 5, mask.width - 6, mask.height - 6), outline=255, width=1)
    x: float = pad
    for ch in text:
        md.text((x, 12), ch, font=font, fill=255)
        x += md.textlength(ch, font=font) + tracking
    angle = 4 + _row_digest(quote_row) % 4
    mask = mask.rotate(angle, resample=Image.Resampling.NEAREST, expand=True)
    cx, cy = _REDACTED_STAMP_CENTRE
    ox, oy = cx - mask.width // 2, cy - mask.height // 2
    mp, px = gray_pixel_access(mask), pixel_access(image)
    red = SPECTRA6["red"]
    width, height = image.size
    for y in range(mask.height):
        for x in range(mask.width):
            ax, ay = ox + x, oy + y
            if mp[x, y] > 128 and 0 <= ax < width and 0 <= ay < height and position_noise(ax, ay) >= 40:
                px[ax, ay] = red


def _redacted_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The typed body, ragged right, the phrase in red; then the censor."""
    placed = _place_quote(draw, quote_row, _REDACTED_QUOTE_RECT, theme="redacted",
                          font_max=34, font_min=16, line_height_mult=1.45)
    if not placed:
        return
    # Centre the block vertically in the body rect.
    x0, y0, x1, y1 = _REDACTED_QUOTE_RECT
    block_h = (placed[-1][1] - placed[0][1]) + placed[0][6]
    dy = max(0, (y1 - y0 - block_h) // 2)
    placed = [(x, y + dy, *rest) for x, y, *rest in placed]
    black, red = SPECTRA6["black"], SPECTRA6["red"]
    for x, y, chunk, font, is_bold, *_ in placed:
        draw.text((x, y), chunk, font=font, fill=red if is_bold else black)
    chosen = _redacted_choose(_redacted_candidates(draw, placed), quote_row)
    _redacted_paint_bars(image, _redacted_bars(chosen, placed), quote_row)


def _redacted_paint_foot(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The source line, typed, and an authorising signature the censor took."""
    black = SPECTRA6["black"]
    draw.line([(24, _REDACTED_FOOT_RULE_Y), (776, _REDACTED_FOOT_RULE_Y)], fill=black, width=1)
    label_font = load_font([ARCHIVO_BOLD, *META_FONT_BOLD_CANDIDATES], size=_REDACTED_LABEL_SIZE)
    y = _REDACTED_FOOT_Y
    w = draw_tracked(draw, (40, y + 4), "SOURCE", label_font, black, tracking=1)
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "")
    source = ", ".join(p for p in (author, title) if p)
    sig_label_x = 560
    if source:
        font, source = fit_text_to_width(draw, source, theme_font_candidates("redacted", "quote_regular"),
                                         _REDACTED_VALUE_SIZE, sig_label_x - 24 - (40 + w + 8), floor=12)
        draw.text((40 + w + 8, y), source, font=font, fill=black)
    w = draw_tracked(draw, (sig_label_x, y + 4), "AUTHORIZED", label_font, black, tracking=1)
    bar_x0 = sig_label_x + int(w) + 10
    _redacted_paint_bars(image, [(bar_x0, y + 1, 760, y + 17)], quote_row)


def render_redacted_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A declassified Bureau document (see the module section comment above).

    ``time_str`` is unused by design: the matched phrase carries the time.
    """
    del time_str
    image = Image.new("RGB", (800, 480), color=SPECTRA6["white"])
    draw = ImageDraw.Draw(image)
    _redacted_paint_letterhead(draw)
    _redacted_paint_stamp(image, quote_row)
    _redacted_paint_fields(draw, _redacted_doc_fields(quote_row))
    _redacted_paint_quote(image, draw, quote_row)
    _redacted_paint_foot(image, draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


def _redacted_sleep_words(draw: ImageDraw.ImageDraw, placed) -> list[tuple[int, str, float, float, int, Any]]:
    """Every word of a laid-out block as ``(line, word, x0, x1, y, font)``."""
    line_ys = sorted({p[1] for p in placed})
    words = []
    for x, y, chunk, font, *_ in placed:
        for m in _WORD_RE.finditer(chunk):
            x0 = x + draw.textlength(chunk[:m.start()], font=font)
            words.append((line_ys.index(y), m.group(0), x0, x0 + draw.textlength(m.group(0), font=font), y, font))
    return words


def _redacted_sleep_kept(words) -> tuple[int, int]:
    """Indices of the two words the censor leaves: the first ``lights``, then
    the first ``out`` after it."""
    first, second = _REDACTED_SLEEP_KEEP
    i = next(i for i, w in enumerate(words) if w[1].strip(_REDACTED_EDGE_PUNCT).lower() == first)
    j = next(j for j, w in enumerate(words) if j > i and w[1].strip(_REDACTED_EDGE_PUNCT).lower() == second)
    return i, j


def _redacted_sleep_layout(draw: ImageDraw.ImageDraw):
    """The Standby Order laid out in the body rect, centred vertically.

    Fitted from a larger ceiling than a quote (40 against 34) and with more
    leading, because only two words are ever read and the bars want air.
    """
    placed = _place_quote(draw, _REDACTED_SLEEP_ROW, _REDACTED_QUOTE_RECT, theme="redacted",
                          font_max=40, font_min=16, line_height_mult=1.6)
    x0, y0, x1, y1 = _REDACTED_QUOTE_RECT
    block_h = (placed[-1][1] - placed[0][1]) + placed[0][6]
    dy = max(0, (y1 - y0 - block_h) // 2)
    return [(x, y + dy, *rest) for x, y, *rest in placed]


def render_redacted_sleep(time_str: str, width: int, height: int) -> Image.Image:
    """The quiet-hours frame: a Standby Order, SUSPENDED, with every word
    blacked out but "lights … out" in red.

    The same letterhead, stamp, fields and foot as the quote frame. Bars sit
    just inside each word so the gaps between words survive, and a seeded
    share of gaps is carried straight across. ``time_str`` is unused: nothing
    on the frame tells the time.
    """
    del time_str
    image = Image.new("RGB", (800, 480), color=SPECTRA6["white"])
    draw = ImageDraw.Draw(image)
    row = _REDACTED_SLEEP_ROW
    _redacted_paint_letterhead(draw)
    _redacted_paint_stamp(image, row, text=_REDACTED_SLEEP_STAMP)
    _redacted_paint_fields(draw, _REDACTED_SLEEP_FIELDS)

    words = _redacted_sleep_words(draw, _redacted_sleep_layout(draw))
    kept = _redacted_sleep_kept(words)
    black, red = SPECTRA6["black"], SPECTRA6["red"]
    for i, (_line, word, x0, _x1, y, font) in enumerate(words):
        draw.text((x0, y), word, font=font, fill=red if i in kept else black)
    rng = random.Random(_REDACTED_SLEEP_SEED)
    runs: list[list] = []
    for i, (line, _word, x0, x1, y, _font) in enumerate(words):
        if i in kept:
            continue
        if runs and runs[-1][0] == line and runs[-1][4] == i - 1 and rng.random() < _REDACTED_SLEEP_JOIN:
            runs[-1][2], runs[-1][4] = x1, i
        else:
            runs.append([line, x0, x1, y, i])
    font = words[0][5]
    top, bottom = font.getbbox("Hgjy|")[1], font.getbbox("Hgjy|")[3]
    bars = [(int(x0) + 1, y + top - 1, int(x1) - 1, y + bottom) for _l, x0, x1, y, _i in runs]
    _redacted_paint_bars(image, bars, row)

    _redacted_paint_foot(image, draw, row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("redacted",), render=render_redacted_frame, sleep=render_redacted_sleep)
