"""The ``cardcatalog`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import random

from PIL import Image, ImageDraw

from .._paths import META_FONT_BOLD_CANDIDATES, META_FONT_CANDIDATES, SPACEMONO_BOLD, SPACEMONO_REGULAR, SPECIALELITE_REGULAR
from ..fonts import load_font
from ..furniture import _place_quote, _row_digest, fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_4x4, snap_image_to_palette
from ..spec import FrameSpec
from ..text import draw_text_dithered

# ---------------------------------------------------------------------------
# cardcatalog — a library catalogue card with a date-due stamp grid
# ---------------------------------------------------------------------------
# A manila catalogue card: call number, typed author/title header, the quote
# as the card's annotation, and a grid of date-due stamps down the right
# margin. The panel's 5:3 ratio is a 3x5 index card, so the page is the card
# face at full bleed.
#
# A custom frame, not a border painter with a ``clear_rect`` knockout (as
# #210 proposed): at 800x480 the shared layout's body rect leaves no right
# margin, and the stamp column is both the composition and the time carrier.
#
# The time carrier is the freshest stamp. Earlier impressions are faded and
# askew with varying ink density; the current one is crisp, square, spans both
# columns and reads ``DUE`` over the hour (reserve collections ran two-hour
# loans). The minute stays with the matched phrase. Distinct from ``dispatch``
# despite sharing Special Elite: manila and violet library ink, not a white
# dossier with one maroon stamp.
# ---------------------------------------------------------------------------
_CARDCATALOG_EDGE = 12
_CARDCATALOG_CALL_X = 36
_CARDCATALOG_COL_X = 168              # annotation column left edge
_CARDCATALOG_COL_RIGHT = 556          # annotation column right edge
_CARDCATALOG_DIVIDER_X = 568          # rule between annotation and stamps
_CARDCATALOG_HEADER_TOP = 44
_CARDCATALOG_HEADER_RULE = 118
_CARDCATALOG_BODY = (168, 136, 556, 374)
_CARDCATALOG_STAMP_X = (582, 770)
_CARDCATALOG_STAMP_TOP = 84
_CARDCATALOG_STAMP_SIZE = (88, 34)
_CARDCATALOG_STAMP_STEP = 42
_CARDCATALOG_STAMP_ROWS = 7
_CARDCATALOG_PUNCH = (400, 452, 10)   # centre x, centre y, radius
# Foxing density on the manila: 2 hits per modulus, ~1.2% of the card —
# sparser than ``tarot``'s vellum. See ``_cardcatalog_paint_manila`` for why
# the sampling lattice must not alias with the 4-pixel Bayer cream tile.
_CARDCATALOG_FOXING_MOD = 167


def _cardcatalog_paint_manila(image: Image.Image) -> None:
    """Cream base wash plus a sparse sepia foxing scatter — aged card stock.

    The two-layer aged-paper recipe ``tarot`` uses (Y+W cream under R+G sepia),
    run lighter. Both passes only touch white ground pixels, so the painter is
    idempotent and cannot re-tint furniture drawn over it.
    """
    width, height = image.size
    px = image.load()
    white, yellow, red, green = (
        SPECTRA6["white"], SPECTRA6["yellow"], SPECTRA6["red"], SPECTRA6["green"],
    )
    for y in range(height):
        row = BAYER_4x4[y % 4]
        for x in range(width):
            if px[x, y] == white and row[x % 4] < 2:
                px[x, y] = yellow
    # Sepia foxing: adjacent red and green flecks average to rust-brown at
    # panel distance (the ``newsprint`` / ``tarot`` R+G recipe), painted over
    # the cream too — oxidation does not dodge the paper's tone.
    #
    # The sampling lattice must stay coprime with the 4-pixel Bayer period: a
    # lattice that forces ``x % 4 == y % 4`` lands only on cells the cream
    # wash already claimed and paints nothing.
    for y in range(height):
        for x in range(width):
            if (x * 31 + y * 17) % _CARDCATALOG_FOXING_MOD >= 2:
                continue
            if px[x, y] not in (white, yellow):
                continue
            px[x, y] = red if (x * 5 + y * 3) % 7 < 4 else green


def _cardcatalog_call_number(quote_row: dict) -> list[str]:
    """The call-number block: a Dewey class, a cutter, a date, a copy mark.

    Derived from the row digest so it is stable for a given book. Dewey
    800-819 keeps it inside literature.
    """
    digest = _row_digest(quote_row)
    author = (quote_row.get("author") or "").strip()
    surname = author.split(",")[0].split()[-1] if author else "ANON"
    cutter = "".join(ch for ch in surname.upper() if ch.isalpha())[:3] or "ANO"
    dewey = 800 + digest % 20
    decimal = (digest >> 6) % 100
    year = 1890 + (digest >> 12) % 40
    copy = 1 + (digest >> 20) % 3
    return [f"{dewey}.{decimal:02d}", cutter, str(year), f"c.{copy}"]


def _cardcatalog_header(quote_row: dict) -> tuple[str, str]:
    """``(author in catalogue inversion, title)``.

    Catalogue cards file on the surname, so the main entry is inverted:
    "L. M. Montgomery" is filed as "Montgomery, L. M." An author already stored
    inverted (containing a comma) is passed through untouched.
    """
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "")
    if author and "," not in author:
        parts = author.split()
        if len(parts) > 1:
            author = f"{parts[-1]}, {' '.join(parts[:-1])}"
    return author or "Anonymous", title


def _cardcatalog_stamp_mask(size: tuple[int, int], lines: list[tuple[str, int]],
                            *, boxed: bool) -> Image.Image:
    """An ``L`` mask of one stamp impression: optional box rule plus its lines."""
    w, h = size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    if boxed:
        draw.rectangle((0, 0, w - 1, h - 1), outline=255, width=2)
    total = sum(size for _, size in lines) + 2 * (len(lines) - 1)
    y = max(0, (h - total) // 2)
    for text, font_size in lines:
        font = load_font([SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=font_size)
        draw.text((w // 2, y), text, font=font, fill=255, anchor="ma")
        y += font_size + 2
    return mask


def _cardcatalog_stamp(image: Image.Image, origin: tuple[int, int],
                       mask: Image.Image, *, angle: float, coverage: float,
                       rng: random.Random) -> None:
    """Paste one impression in violet library ink at a given angle and density.

    Violet is R+B 1:1 (the Tyrian recipe); library date stamps were purple.
    ``coverage`` drops a different fraction of each impression's ink, so the
    older stamps read as a history from a drying pad. The rotated mask is
    binary-thresholded so no antialiased fringe is left for the final snap.
    """
    if angle:
        mask = mask.rotate(angle, resample=Image.BICUBIC, expand=True)
    mp = mask.load()
    px = image.load()
    width, height = image.size
    red, blue = SPECTRA6["red"], SPECTRA6["blue"]
    ox, oy = origin
    for my in range(mask.size[1]):
        iy = oy + my
        if not 0 <= iy < height:
            continue
        for mx in range(mask.size[0]):
            ix = ox + mx
            if not 0 <= ix < width:
                continue
            if mp[mx, my] < 128:
                continue
            if coverage < 1.0 and rng.random() > coverage:
                continue
            px[ix, iy] = red if (ix + iy) & 1 else blue


def _cardcatalog_paint_stamps(image: Image.Image, quote_row: dict, time_str: str) -> None:
    """The date-due grid: a faded borrowing history, then today's impression."""
    months = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
    digest = _row_digest(quote_row)
    rng = random.Random(digest)
    left, right = _CARDCATALOG_STAMP_X
    sw, sh = _CARDCATALOG_STAMP_SIZE
    col_step = (right - left) // 2
    # Leave at least one whole row for the current impression, which spans both
    # columns, so a long history can never push it off the card.
    history = 3 + digest % (2 * (_CARDCATALOG_STAMP_ROWS - 1) - 2)
    year = 1948 + (digest >> 8) % 30
    for index in range(history):
        row, col = divmod(index, 2)
        month = months[(digest >> (index % 12)) % 12]
        day = 1 + (digest >> (index + 3)) % 28
        mask = _cardcatalog_stamp_mask(
            (sw, sh), [(f"{month} {day:2d}", 13), (f"{year + row}", 12)], boxed=False,
        )
        _cardcatalog_stamp(
            image,
            (left + col * col_step + rng.randint(-3, 3),
             _CARDCATALOG_STAMP_TOP + row * _CARDCATALOG_STAMP_STEP + rng.randint(-2, 2)),
            mask,
            angle=rng.uniform(-4.5, 4.5),
            coverage=rng.uniform(0.62, 0.92),
            rng=rng,
        )
    # The current impression: crisp, square to the card, spanning both columns,
    # and carrying the hour. This is the theme's time carrier.
    row = (history + 1) // 2
    hour, meridiem = _cardcatalog_due_hour(time_str)
    mask = _cardcatalog_stamp_mask(
        (right - left, sh + 20), [("DUE", 12), (f"{hour} {meridiem}", 26)], boxed=True,
    )
    _cardcatalog_stamp(
        image,
        (left, _CARDCATALOG_STAMP_TOP + row * _CARDCATALOG_STAMP_STEP),
        mask, angle=0.0, coverage=1.0, rng=rng,
    )


def _cardcatalog_due_hour(time_str: str) -> tuple[int, str]:
    """``(1..12, "AM"|"PM")`` parsed defensively from ``HH:MM``.

    Only the hour reaches the stamp (a reserve-desk loan was due on the hour);
    the minute stays with the matched phrase.
    """
    try:
        hour = int((time_str or "").split(":")[0]) % 24
    except (ValueError, IndexError):
        hour = 12
    meridiem = "PM" if hour >= 12 else "AM"
    return (hour % 12) or 12, meridiem


def _cardcatalog_paint_chrome(image: Image.Image, draw: ImageDraw.ImageDraw,
                              quote_row: dict, width: int, height: int) -> None:
    """Card edge, call number, typed header, column rule, and the rod hole."""
    black, red = SPECTRA6["black"], SPECTRA6["red"]
    edge = _CARDCATALOG_EDGE
    draw.rectangle((edge, edge, width - edge - 1, height - edge - 1), outline=black, width=1)

    call = load_font([SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=15)
    y = _CARDCATALOG_HEADER_TOP
    for line in _cardcatalog_call_number(quote_row):
        draw.text((_CARDCATALOG_CALL_X, y), line, font=call, fill=black)
        y += 20

    author, title = _cardcatalog_header(quote_row)
    column = _CARDCATALOG_COL_RIGHT - _CARDCATALOG_COL_X
    main = load_font([SPECIALELITE_REGULAR, *META_FONT_BOLD_CANDIDATES], size=19)
    sub = load_font([SPECIALELITE_REGULAR, *META_FONT_CANDIDATES], size=16)
    y = _CARDCATALOG_HEADER_TOP
    for text, font in ((author, main), (title, sub)):
        if not text:
            continue
        while len(text) > 1 and draw.textlength(text, font=font) > column:
            text = text[:-2] + "…"
        draw.text((_CARDCATALOG_COL_X, y), text, font=font, fill=black)
        y += 30
    # Rule under the main entry, and the column rule holding the stamps off the
    # annotation — both are ruled on real card stock, not decoration.
    draw.line((_CARDCATALOG_COL_X, _CARDCATALOG_HEADER_RULE,
               _CARDCATALOG_COL_RIGHT, _CARDCATALOG_HEADER_RULE), fill=black, width=1)
    draw.line((_CARDCATALOG_DIVIDER_X, _CARDCATALOG_HEADER_TOP - 8,
               _CARDCATALOG_DIVIDER_X, height - 56), fill=black, width=1)

    heading = load_font([SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=13)
    centre = (_CARDCATALOG_STAMP_X[0] + _CARDCATALOG_STAMP_X[1]) // 2
    draw.text((centre, _CARDCATALOG_HEADER_TOP), "DATE DUE", font=heading, fill=black, anchor="ma")
    draw.line((_CARDCATALOG_STAMP_X[0], _CARDCATALOG_HEADER_TOP + 22,
               _CARDCATALOG_STAMP_X[1], _CARDCATALOG_HEADER_TOP + 22), fill=black, width=1)

    # The rod hole every drawer card is punched for: filled black with a red
    # rim (the torn fibre), so it reads as a hole rather than a printed dot.
    cx, cy, r = _CARDCATALOG_PUNCH
    if cy + r < height:
        draw.ellipse((cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1), outline=red, width=1)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=black)


def _cardcatalog_paint_annotation(image: Image.Image, draw: ImageDraw.ImageDraw,
                                  quote_row: dict) -> None:
    """The quote, typed into the card's annotation column.

    The matched phrase takes the stamps' violet, tying the readable time to
    the stamped one.
    """
    x0, y0, x1, y1 = _CARDCATALOG_BODY
    if x1 - x0 < 40 or y1 - y0 < 40:
        return
    black, red, blue = SPECTRA6["black"], SPECTRA6["red"], SPECTRA6["blue"]
    # Top-aligned, not centred: a card's annotation begins directly under the
    # main-entry rule; the tracing block fills the foot.
    placed = _place_quote(draw, quote_row, _CARDCATALOG_BODY, theme="cardcatalog",
                          font_max=26, font_min=12, line_height_mult=1.34)
    for x, y, chunk, font, is_bold, *_ in placed:
        if is_bold:
            draw_text_dithered(image, (x, y), chunk, font, red, blue)
        else:
            draw.text((x, y), chunk, font=font, fill=black)


def _cardcatalog_paint_tracing(draw: ImageDraw.ImageDraw, quote_row: dict, height: int) -> None:
    """The added-entries tracing and accession mark at the foot of the card.

    Invents nothing: a title added entry exists for every work, the holding
    collection is this appliance, and the accession number is the row's real
    Gutenberg ID. Don't add subject headings — that would fabricate
    bibliographic data about a real book.
    """
    black = SPECTRA6["black"]
    x0 = _CARDCATALOG_COL_X
    x1 = _CARDCATALOG_COL_RIGHT
    y = height - 96
    draw.line((x0, y, x0 + 120, y), fill=black, width=1)
    body = load_font([SPECIALELITE_REGULAR, *META_FONT_CANDIDATES], size=14)
    draw.text((x0, y + 10), "I. Title.   II. Idle Hours Collection.", font=body, fill=black)
    source_id = str(quote_row.get("source_id") or "").strip()
    if source_id:
        mono = load_font([SPACEMONO_REGULAR, *META_FONT_CANDIDATES], size=12)
        draw.text((x1, y + 12), f"ACC. PG-{source_id}", font=mono, fill=black, anchor="ra")


def render_cardcatalog_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A library catalogue card (see the section comment above).

    Every rectangle is a fixed panel coordinate, so the card is composed at
    800x480 and NEAREST-downsampled otherwise (the ``metro`` convention); a
    direct small render would put the stamp column off the canvas. NEAREST
    because the manila stipple would average to off-palette colours.
    """
    image = Image.new("RGB", (800, 480), color=SPECTRA6["white"])
    _cardcatalog_paint_manila(image)
    draw = ImageDraw.Draw(image)
    _cardcatalog_paint_chrome(image, draw, quote_row, 800, 480)
    _cardcatalog_paint_annotation(image, draw, quote_row)
    _cardcatalog_paint_tracing(draw, quote_row, 480)
    _cardcatalog_paint_stamps(image, quote_row, time_str)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("cardcatalog",), render=render_cardcatalog_frame)
