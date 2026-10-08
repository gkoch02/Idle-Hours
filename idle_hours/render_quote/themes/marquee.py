"""The ``marquee`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .._paths import ANTONIO_VARIABLE, META_FONT_BOLD_CANDIDATES
from ..fonts import _font_ascent, load_font, normalize_dashes, theme_font_candidates
from ..furniture import fallback_title
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, snap_image_to_palette
from ..spec import FrameSpec

# ─── marquee (1930s movie-palace facade) ─────────────────────────────────────
# A black theatre facade at night: a yellow/red bulb-light border, the book
# title at the top as the chunky Bungee Shade "feature title", the quote below
# as the feature copy in white Cardo Italic with a red matched-phrase accent,
# and WRITTEN BY credit chrome along the bottom. (A Solari split-flap board
# was tried for this slot; its wayfinding register fought the literary
# content.)

_MARQUEE_BULB_INSET = 16
_MARQUEE_BULB_RADIUS = 5
_MARQUEE_BULB_SPACING = 32


def _marquee_paint_facade(image: Image.Image) -> None:
    """Solid black ground — the theater facade at night."""
    image.paste(SPECTRA6["black"], (0, 0, image.width, image.height))


def _marquee_paint_bulb_border(image: Image.Image, draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    """Yellow + red bulb-light border around the entire perimeter.

    Bulbs alternate yellow and red around the perimeter (a vintage
    coloured-bulb marquee rather than a uniform lamp row), each with a
    small white highlight so it reads as lit glass.
    """
    YELLOW = SPECTRA6["yellow"]
    RED = SPECTRA6["red"]
    WHITE = SPECTRA6["white"]
    r = _MARQUEE_BULB_RADIUS
    inset = _MARQUEE_BULB_INSET
    spacing = _MARQUEE_BULB_SPACING
    # Walk the perimeter and emit a bulb at each step.
    bulbs: list[tuple[int, int]] = []
    # Top edge: left → right.
    for x in range(inset, width - inset + 1, spacing):
        bulbs.append((x, inset))
    # Right edge: top → bottom (skip first to avoid double-tap of corner).
    for y in range(inset + spacing, height - inset + 1, spacing):
        bulbs.append((width - inset, y))
    # Bottom edge: right → left.
    for x in range(width - inset - spacing, inset - 1, -spacing):
        bulbs.append((x, height - inset))
    # Left edge: bottom → top.
    for y in range(height - inset - spacing, inset, -spacing):
        bulbs.append((inset, y))
    for i, (cx, cy) in enumerate(bulbs):
        bulb_colour = YELLOW if i % 2 == 0 else RED
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=bulb_colour)
        # White highlight near the bulb's top-left.
        draw.ellipse((cx - 1, cy - 2, cx + 1, cy), fill=WHITE)


def _marquee_paint_label_band(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    width: int,
    y_top: int,
    text: str,
    *,
    size: int = 14,
    colour: tuple[int, int, int] | None = None,
) -> None:
    """Centred chrome label (Antonio Bold) — the NOW SHOWING / ONE NIGHT ONLY taglines."""
    if colour is None:
        colour = SPECTRA6["yellow"]
    # Antonio Bold rather than Bungee Shade: the 3D-blocked Bungee Shade
    # muddies into noise at small label sizes.
    font = load_font([(ANTONIO_VARIABLE, "Bold"), *META_FONT_BOLD_CANDIDATES], size=size)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    cx = width // 2
    draw.text((cx - tw // 2 - bbox[0], y_top - bbox[1]), text, font=font, fill=colour)


def _marquee_paint_feature_title(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    width: int,
    quote_row: dict,
    cy: int,
) -> None:
    """The book title as big white Bungee Shade "feature title" chrome.

    Centred on ``width`` and ``cy``, uppercased (the marquee convention) and
    shrunk to fit from 72pt down to 32pt; if it still overflows it wraps at
    the space nearest the midpoint and a fresh size sweep fits both lines.

    Falls back to the author, then the literal ``"IDLE HOURS"`` — never the
    wall-clock HH:MM, since the matched phrase is the time signal.
    """
    WHITE = SPECTRA6["white"]
    title = (quote_row.get("title") or fallback_title(quote_row) or "").strip()
    author = (quote_row.get("author") or "").strip()
    text = title.upper() or author.upper() or "IDLE HOURS"
    if not text:
        return
    max_text_width = width - 100  # 50 px inset each side

    # Try single-line fit first, biggest size down.
    chain = theme_font_candidates("marquee", "ornament")
    for size in (72, 64, 56, 50, 44, 38, 32):
        font = load_font(chain, size=size)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        if tw <= max_text_width:
            th = bbox[3] - bbox[1]
            draw.text(
                (width // 2 - tw // 2 - bbox[0], cy - th // 2 - bbox[1]),
                text, font=font, fill=WHITE,
            )
            return

    # Wrap to two lines at the space nearest the midpoint.
    mid = len(text) // 2
    left_break = text.rfind(" ", 0, mid + 4)
    right_break = text.find(" ", mid)
    candidates = [b for b in (left_break, right_break) if b > 0]
    if not candidates:
        # No space at all — render at the smallest size and let it overflow.
        font = load_font(chain, size=28)
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(
            (width // 2 - tw // 2 - bbox[0], cy - th // 2 - bbox[1]),
            text, font=font, fill=WHITE,
        )
        return
    split_at = min(candidates, key=lambda b: abs(b - mid))
    line1, line2 = text[:split_at].strip(), text[split_at + 1:].strip()

    for size in (54, 48, 42, 36, 32, 28, 24):
        font = load_font(chain, size=size)
        bbox1 = draw.textbbox((0, 0), line1, font=font)
        bbox2 = draw.textbbox((0, 0), line2, font=font)
        tw1 = bbox1[2] - bbox1[0]
        tw2 = bbox2[2] - bbox2[0]
        if tw1 <= max_text_width and tw2 <= max_text_width:
            break

    th = bbox1[3] - bbox1[1]
    line_gap = 10
    block_h = th * 2 + line_gap
    top_y = cy - block_h // 2
    # Line 1.
    draw.text(
        (width // 2 - (bbox1[2] - bbox1[0]) // 2 - bbox1[0], top_y - bbox1[1]),
        line1, font=font, fill=WHITE,
    )
    # Line 2.
    draw.text(
        (width // 2 - (bbox2[2] - bbox2[0]) // 2 - bbox2[0],
         top_y + th + line_gap - bbox2[1]),
        line2, font=font, fill=WHITE,
    )


def _marquee_paint_divider(image: Image.Image, draw: ImageDraw.ImageDraw, width: int, cy: int) -> None:
    """Decorative double rule between the title and the quote body.

    A thicker yellow upper rule and a thin red lower rule with a small red
    diamond between them, like a proscenium / poster divider.
    """
    YELLOW = SPECTRA6["yellow"]
    RED = SPECTRA6["red"]
    x_left = 80
    x_right = width - 80
    draw.line((x_left, cy - 4, x_right, cy - 4), fill=YELLOW, width=2)
    draw.line((x_left, cy + 4, x_right, cy + 4), fill=RED, width=1)
    # Centred red diamond between the rules.
    cx = width // 2
    draw.polygon([(cx, cy - 5), (cx + 5, cy), (cx, cy + 5), (cx - 5, cy)], fill=RED)


def _marquee_paint_body(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    quote_row: dict,
    rect: tuple[int, int, int, int],
) -> None:
    """Quote body in white Cardo Italic with a red matched-phrase accent.

    Centred line-by-line within ``rect``; ``fit_quote`` shrinks a dense
    quote to fit.
    """
    WHITE = SPECTRA6["white"]
    RED = SPECTRA6["red"]
    x0, y0, x1, y1 = rect
    width = x1 - x0
    height = y1 - y0
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    matched = quote_row.get("matched_text") or ""

    quote_font, quote_font_bold, wrapped_quote, line_height, _ = fit_quote(
        draw,
        display_quote,
        matched,
        width,
        height,
        font_max=30,
        font_min=18,
        line_height_mult=1.22,
        theme="marquee",
    )
    quote_block_height = len(wrapped_quote) * line_height
    block_top = y0 + max(0, (height - quote_block_height) // 2)
    body_ascent = _font_ascent(quote_font)
    y = block_top
    for line in wrapped_quote:
        start = 0
        while start < len(line) and line[start][0].strip() == "":
            start += 1
        end = len(line)
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        drawable = line[start:end]
        line_w: float = 0
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            bbox = draw.textbbox((0, 0), chunk, font=font)
            line_w += bbox[2] - bbox[0]
        x: float = x0 + max(0, (width - line_w) // 2)
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            chunk_y = y + (body_ascent - _font_ascent(font))
            fill = RED if is_bold else WHITE
            draw.text((x, chunk_y), chunk, font=font, fill=fill)
            bbox = draw.textbbox((0, 0), chunk, font=font)
            x += bbox[2] - bbox[0]
        y += line_height


def _marquee_paint_credits(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    quote_row: dict,
    width: int,
    y_top: int,
) -> None:
    """WRITTEN BY [AUTHOR] credit chrome.

    Yellow Antonio Bold "WRITTEN BY" plus the author in white Cardo Italic,
    centred. Not the movie-poster ``STARRING``: the author wrote the book
    rather than performing in it, so the credit line is where the literary
    register wins.
    """
    YELLOW = SPECTRA6["yellow"]
    WHITE = SPECTRA6["white"]
    author = (quote_row.get("author") or "").strip()
    if not author:
        return
    cx = width // 2
    label_font = load_font([(ANTONIO_VARIABLE, "Bold"), *META_FONT_BOLD_CANDIDATES], size=14)
    name_font = load_font(theme_font_candidates("marquee", "quote_regular"), size=20)
    label = "WRITTEN BY"
    label_bbox = draw.textbbox((0, 0), label, font=label_font)
    label_w = label_bbox[2] - label_bbox[0]
    name_bbox = draw.textbbox((0, 0), author, font=name_font)
    name_w = name_bbox[2] - name_bbox[0]
    gap = 14
    total_w = label_w + gap + name_w
    line_x = cx - total_w // 2
    draw.text((line_x - label_bbox[0], y_top - label_bbox[1]), label, font=label_font, fill=YELLOW)
    draw.text(
        (line_x + label_w + gap - name_bbox[0], y_top - name_bbox[1] - 2),
        author, font=name_font, fill=WHITE,
    )


def render_marquee_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """1930s movie-palace marquee.

    Black ground; alternating yellow/red bulb border; a "NOW SHOWING"
    tagline; the book title as Bungee Shade feature-title chrome (wrapped to
    two lines when long); the quote in white Cardo Italic with a red matched
    phrase; WRITTEN BY [AUTHOR] credits; "ONE NIGHT ONLY" above the bottom
    bulbs.

    ``time_str`` is never rendered — the matched phrase carries the time. It
    stays on the signature shared by the custom-frame painters.
    """
    del time_str  # see docstring; deliberately unused.
    image = Image.new("RGB", (width, height), color=SPECTRA6["black"])
    _marquee_paint_facade(image)
    draw = ImageDraw.Draw(image)
    _marquee_paint_bulb_border(image, draw, width, height)

    # Top "NOW SHOWING" tagline, just below the top bulb row.
    _marquee_paint_label_band(image, draw, width, y_top=40, text="—  NOW SHOWING  —", size=14)

    # Big chrome — the book title as the feature display.
    _marquee_paint_feature_title(image, draw, width, quote_row, cy=112)

    # Decorative double-rule dividing the title from the quote body.
    _marquee_paint_divider(image, draw, width, cy=180)

    # Literary quote body — centred between the divider and the credits.
    body_rect = (60, 200, width - 60, 360)
    _marquee_paint_body(image, draw, quote_row, body_rect)

    # Credits chrome — WRITTEN BY [AUTHOR] only (the title is at the top).
    _marquee_paint_credits(image, draw, quote_row, width, y_top=384)

    # "ONE NIGHT ONLY" tagline just above the bottom bulb row.
    _marquee_paint_label_band(image, draw, width, y_top=448, text="—  ONE NIGHT ONLY  —", size=12)

    return snap_image_to_palette(image, SPECTRA6_PALETTE)


# ─── sleep frame: the house is closed for the night ─────────────────────────
# The facade keeps its bulbs lit (a dark marquee reads as a dead panel) and the
# changeable-letter board, backlit white, spells the closing notice in block
# capitals, one letter per fixed-pitch tile on black track rails.

_MARQUEE_SLEEP_BOARD = (64, 92, 736, 388)
_MARQUEE_SLEEP_LINES = (
    # (text, cap height px, colour key, row centre y)
    ("CLOSED", 104, "red", 194),
    ("SEE YOU TOMORROW", 48, "black", 320),
)
_MARQUEE_SLEEP_TOP = "—  GOOD NIGHT  —"
_MARQUEE_SLEEP_FOOT = "—  THANK YOU FOR COMING  —"


def _marquee_board_font(cap_height: int):
    """Antonio Bold sized so its capitals stand ``cap_height`` px tall."""
    chain = [(ANTONIO_VARIABLE, "Bold"), *META_FONT_BOLD_CANDIDATES]
    size = cap_height
    for _ in range(4):
        font = load_font(chain, size=size)
        bbox = font.getbbox("H")
        measured = bbox[3] - bbox[1]
        if measured <= 0:
            return font
        size = max(8, round(size * cap_height / measured))
    return load_font(chain, size=size)


def _marquee_paint_letter_board(draw: ImageDraw.ImageDraw) -> None:
    """The backlit letter board: a yellow trim, a black reveal, a white face."""
    x0, y0, x1, y1 = _MARQUEE_SLEEP_BOARD
    draw.rectangle((x0, y0, x1, y1), fill=SPECTRA6["yellow"])
    draw.rectangle((x0 + 6, y0 + 6, x1 - 6, y1 - 6), fill=SPECTRA6["black"])
    draw.rectangle((x0 + 10, y0 + 10, x1 - 10, y1 - 10), fill=SPECTRA6["white"])


def _marquee_paint_board_line(draw: ImageDraw.ImageDraw, text: str, cap: int, colour: tuple[int, int, int], cy: int) -> None:
    """One row of changeable letters, centred on the board at ``cy``.

    Letters are set one at a time with wide tracking, as loose marquee
    letters slotted onto a track are, and the row's capitals shrink until
    the line clears the board's face with a margin. The track rails run
    just above and below the capitals across the whole face.
    """
    x0, _y0, x1, _y1 = _MARQUEE_SLEEP_BOARD
    face_l, face_r = x0 + 10, x1 - 10
    room = face_r - face_l - 48
    while True:
        font = _marquee_board_font(cap)
        tracking = max(4, cap // 4)
        space = cap // 2
        advances = [space if ch == " " else int(draw.textlength(ch, font=font)) + tracking for ch in text]
        total = sum(advances) - tracking
        if total <= room or cap <= 16:
            break
        cap -= 2
    x = (face_l + face_r) // 2 - total // 2
    top = cy - cap // 2
    black = SPECTRA6["black"]
    rail = max(2, cap // 24)
    gap = max(6, cap // 8)
    for ry in (top - gap - rail, top + cap + gap):
        draw.rectangle((face_l, ry, face_r, ry + rail - 1), fill=black)
    cap_top = font.getbbox("H")[1]
    for ch, adv in zip(text, advances, strict=True):
        if ch != " ":
            draw.text((x, top - cap_top), ch, font=font, fill=colour)
        x += adv


def render_marquee_sleep(time_str: str, width: int, height: int) -> Image.Image:
    """The quiet-hours frame: the house is closed for the night.

    The quote frame's facade and lit bulb border around a backlit letter
    board reading CLOSED (red) over SEE YOU TOMORROW (black), between a
    GOOD NIGHT tagline and a THANK YOU FOR COMING one. Composed at 800×480
    and NEAREST-downsampled for any other size. ``time_str`` is unused:
    nothing on the frame tells the time.
    """
    del time_str
    image = Image.new("RGB", (800, 480), color=SPECTRA6["black"])
    _marquee_paint_facade(image)
    draw = ImageDraw.Draw(image)
    _marquee_paint_bulb_border(image, draw, 800, 480)
    _marquee_paint_label_band(image, draw, 800, y_top=48, text=_MARQUEE_SLEEP_TOP, size=22)
    _marquee_paint_letter_board(draw)
    for text, cap, colour, cy in _MARQUEE_SLEEP_LINES:
        _marquee_paint_board_line(draw, text, cap, SPECTRA6[colour], cy)
    _marquee_paint_label_band(image, draw, 800, y_top=408, text=_MARQUEE_SLEEP_FOOT, size=22)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("marquee",), render=render_marquee_frame, sleep=render_marquee_sleep)
