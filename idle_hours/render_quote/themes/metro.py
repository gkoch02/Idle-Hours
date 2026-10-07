"""The ``metro`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from ..fonts import _font_ascent, load_font, normalize_dashes, theme_font_candidates
from ..furniture import _clock_hh_mm, fallback_title
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, snap_image_to_palette
from ..spec import FrameSpec
from ._shared import _metro_ellipsize

_METRO_ROUTES: tuple[tuple[tuple[int, int, int], tuple[tuple[int, int], ...]], ...] = (
    (SPECTRA6["red"], ((-20, 82), (122, 82), (210, 170), (590, 170), (686, 74), (820, 74))),
    (SPECTRA6["blue"], ((84, -20), (84, 118), (188, 222), (612, 222), (716, 326), (716, 500))),
    (SPECTRA6["green"], ((-20, 402), (132, 402), (238, 296), (560, 296), (662, 398), (820, 398))),
    (SPECTRA6["yellow"], ((238, -20), (238, 116), (318, 196), (482, 196), (562, 116), (562, -20))),
)
_METRO_INTERCHANGES: tuple[tuple[int, int], ...] = ((188, 222), (318, 196), (482, 196), (612, 222))


def _metro_paint_grid(draw: ImageDraw.ImageDraw) -> None:
    """Sparse coordinate dots: the white stock's printed-map texture."""
    for y in range(64, 480, 32):
        for x in range(20, 800, 40):
            draw.point((x, y), fill=SPECTRA6["black"])


def _metro_paint_interchanges(draw: ImageDraw.ImageDraw) -> None:
    """Four interchanges: a black outer ring and white centre are legible over
    every route ink, and the paired nodes read as transfers rather than dots."""
    for x, y in _METRO_INTERCHANGES:
        draw.ellipse((x - 12, y - 12, x + 12, y + 12), fill=SPECTRA6["white"], outline=SPECTRA6["black"], width=4)
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=SPECTRA6["black"])


def _metro_paint_network(image: Image.Image) -> None:
    """Paint a schematic network with genuine 45-degree route geometry."""
    draw = ImageDraw.Draw(image)
    # Sparse coordinate dots give the white stock a printed-map texture
    # without turning it into graph paper or competing with the route lines.
    _metro_paint_grid(draw)
    # White gaps break the grid beneath each route, mimicking the casing used
    # on real diagram maps; the chromatic stroke then sits cleanly on top.
    for ink, points in _METRO_ROUTES:
        draw.line(points, fill=SPECTRA6["white"], width=15, joint="curve")
        draw.line(points, fill=ink, width=9, joint="curve")
        for x, y in points[1:-1]:
            draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=SPECTRA6["white"], outline=SPECTRA6["black"], width=2)

    _metro_paint_interchanges(draw)


def _metro_paint_masthead(draw: ImageDraw.ImageDraw, right_label: str, right_x: int) -> None:
    """The black agency bar: the network name left, a service label right."""
    draw.rectangle((0, 0, 800, 48), fill=SPECTRA6["black"])
    label_font = load_font(theme_font_candidates("metro", "ornament"), 19)
    small_font = load_font(theme_font_candidates("metro", "ornament"), 14)
    draw.text((26, 13), "IDLE HOURS METROPOLITAN", font=label_font, fill=SPECTRA6["white"])
    draw.text((right_x, 16), right_label, font=small_font, fill=SPECTRA6["yellow"])


def _metro_paint_chrome(image: Image.Image, time_str: str) -> None:
    draw = ImageDraw.Draw(image)
    _metro_paint_masthead(draw, "LITERARY LINE", 625)
    small_font = load_font(theme_font_candidates("metro", "ornament"), 14)

    hour, minute = _clock_hh_mm(time_str)
    hour = hour % 12 or 12
    # The clock becomes station furniture: hour is the line number and minute
    # is the stop. It is explicit, but read first as transit nomenclature.
    draw.ellipse((25, 398, 91, 464), fill=SPECTRA6["red"], outline=SPECTRA6["black"], width=4)
    code_font = load_font(theme_font_candidates("metro", "ornament"), 25)
    code = f"{hour:02d}"
    box = draw.textbbox((0, 0), code, font=code_font)
    draw.text((58 - (box[2] - box[0]) // 2, 411), code, font=code_font, fill=SPECTRA6["white"])
    draw.rectangle((98, 414, 202, 450), fill=SPECTRA6["black"])
    draw.text((110, 423), f"STOP {minute:02d}", font=small_font, fill=SPECTRA6["white"])

    # Route key along the bottom edge uses all four chromatic native inks.
    names = (("EXPRESS", SPECTRA6["red"]), ("NIGHT", SPECTRA6["blue"]), ("GARDEN", SPECTRA6["green"]), ("CIRCLE", SPECTRA6["yellow"]))
    x = 312
    for name, ink in names:
        draw.line((x, 448, x + 22, 448), fill=ink, width=7)
        draw.text((x + 29, 439), name, font=small_font, fill=SPECTRA6["black"])
        x += 119


def _metro_fit_metadata(draw, author: str, title: str, author_font, title_font) -> tuple[str, str]:
    """Fit the two metadata labels into their shared 174..658 pixel row."""
    available = 658 - 174 - 12  # keep a visible gutter between the labels
    author_width = draw.textlength(author, font=author_font)
    title_width = draw.textlength(title, font=title_font)
    if author_width + title_width <= available:
        return author, title

    half = available // 2
    if author_width < half:
        author_budget = int(author_width)
        title_budget = available - author_budget
    elif title_width < half:
        title_budget = int(title_width)
        author_budget = available - title_budget
    else:
        author_budget = half
        title_budget = available - half
    return (
        _metro_ellipsize(draw, author, author_font, author_budget),
        _metro_ellipsize(draw, title, title_font, title_budget),
    )


def _metro_paint_card_shell(
    draw: ImageDraw.ImageDraw, tab_text: str, card: tuple[int, int, int, int] = (116, 100, 684, 388)
) -> None:
    """The pasted notice card: offset shadow, keyline and black tab."""
    x0, y0, x1, y1 = card
    # Offset shadow + black keyline give the legend the physical hierarchy of
    # a pasted service notice, not a white hole accidentally left in the map.
    draw.rectangle((x0 + 8, y0 + 8, x1 + 8, y1 + 8), fill=SPECTRA6["black"])
    draw.rectangle(card, fill=SPECTRA6["white"], outline=SPECTRA6["black"], width=4)
    draw.rectangle((x0, y0, x1, y0 + 26), fill=SPECTRA6["black"])
    tab_font = load_font(theme_font_candidates("metro", "ornament"), 14)
    draw.text((x0 + 16, y0 + 7), tab_text, font=tab_font, fill=SPECTRA6["white"])


def _metro_paint_quote_card(image: Image.Image, quote_row: dict) -> None:
    draw = ImageDraw.Draw(image)
    _metro_paint_card_shell(draw, "CENTRAL INTERCHANGE  •  ALL STORIES CONNECT")

    quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    regular, bold, lines, line_height, _ = fit_quote(
        draw, quote, quote_row.get("matched_text") or "", 500, 170, 34, 18, 1.16, theme="metro"
    )
    total_h = len(lines) * line_height
    y = 145 + max(0, (172 - total_h) // 2)
    for line in lines:
        widths = []
        for chunk, is_bold in line:
            font = bold if is_bold else regular
            box = draw.textbbox((0, 0), chunk, font=font)
            widths.append(box[2] - box[0])
        x = 400 - sum(widths) // 2
        body_ascent = _font_ascent(regular)
        for (chunk, is_bold), chunk_w in zip(line, widths, strict=True):
            font = bold if is_bold else regular
            fill = SPECTRA6["red"] if is_bold else SPECTRA6["black"]
            draw.text((x, y + body_ascent - _font_ascent(font)), chunk, font=font, fill=fill)
            x += chunk_w
        y += line_height

    author = quote_row.get("author") or "UNKNOWN AUTHOR"
    title = quote_row.get("title") or fallback_title(quote_row)
    meta_font = load_font(theme_font_candidates("metro", "quote_regular"), 16)
    meta_bold = load_font(theme_font_candidates("metro", "quote_bold"), 16)
    draw.line((142, 338, 658, 338), fill=SPECTRA6["black"], width=2)
    draw.rectangle((142, 348, 164, 370), fill=SPECTRA6["blue"])
    author_text, title_text = _metro_fit_metadata(
        draw, str(author).upper(), str(title), meta_bold, meta_font
    )
    draw.text((174, 349), author_text, font=meta_bold, fill=SPECTRA6["black"])
    title_width = draw.textlength(title_text, font=meta_font)
    draw.text((658 - title_width, 350), title_text, font=meta_font, fill=SPECTRA6["black"])


def render_metro_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Render the literary clock as a full-palette metropolitan route map."""
    image = Image.new("RGB", (800, 480), color=SPECTRA6["white"])
    _metro_paint_network(image)
    _metro_paint_quote_card(image, quote_row)
    _metro_paint_chrome(image, time_str)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


# The night line is the route the day key already calls NIGHT; every other
# route is a day line, suspended until the morning.
_METRO_NIGHT_INK = SPECTRA6["blue"]
_METRO_DOT_PITCH = 17   # px of route between night-line dot centres
_METRO_DOT_RADIUS = 6
_METRO_NOTICE_CARD = (116, 244, 684, 402)


def _metro_paint_suspended_route(draw: ImageDraw.ImageDraw, ink, points) -> None:
    """A day line drawn hollow: two thin rails of its own ink, white between.

    The map convention for a line that exists but is not running (closed, or
    under construction), so the route still reads as part of the network and
    keeps its colour, but with none of the weight of a running line.
    """
    draw.line(points, fill=SPECTRA6["white"], width=15, joint="curve")
    draw.line(points, fill=ink, width=10, joint="curve")
    draw.line(points, fill=SPECTRA6["white"], width=4, joint="curve")
    for x, y in points[1:-1]:
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=SPECTRA6["white"], outline=ink, width=2)


def _metro_dotted_points(points) -> list[tuple[float, float]]:
    """Dot centres at an even pitch along a polyline, measured continuously
    across its corners so a joint never bunches or gaps the dots."""
    dots: list[tuple[float, float]] = []
    carry = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        d = carry
        while d <= length:
            t = d / length
            dots.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
            d += _METRO_DOT_PITCH
        carry = d - length
    return dots


def _metro_paint_night_route(draw: ImageDraw.ImageDraw, points) -> None:
    """The one line still running: a white casing carrying round blue dots,
    the night-bus convention, laid over every suspended day line."""
    draw.line(points, fill=SPECTRA6["white"], width=17, joint="curve")
    r = _METRO_DOT_RADIUS
    for x, y in _metro_dotted_points(points):
        draw.ellipse((round(x) - r, round(y) - r, round(x) + r, round(y) + r), fill=_METRO_NIGHT_INK)
    for x, y in points[1:-1]:
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=SPECTRA6["white"], outline=SPECTRA6["black"], width=2)


def _metro_paint_night_network(image: Image.Image) -> None:
    """The same network after the last day train: day routes hollow, the
    night route dotted and on top, interchanges unchanged."""
    draw = ImageDraw.Draw(image)
    _metro_paint_grid(draw)
    for ink, points in _METRO_ROUTES:
        if ink != _METRO_NIGHT_INK:
            _metro_paint_suspended_route(draw, ink, points)
    for ink, points in _METRO_ROUTES:
        if ink == _METRO_NIGHT_INK:
            _metro_paint_night_route(draw, points)
    _metro_paint_interchanges(draw)


def _metro_centred(draw: ImageDraw.ImageDraw, y: int, text: str, font, fill) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    draw.text((400 - (box[2] - box[0]) // 2 - box[0], y), text, font=font, fill=fill)


def _metro_paint_notice_card(image: Image.Image) -> None:
    """The service notice, pasted lower and shorter than the day's quote card
    so the suspended network above it stays in view."""
    draw = ImageDraw.Draw(image)
    _metro_paint_card_shell(draw, "SERVICE NOTICE  •  NIGHT TIMETABLE IN EFFECT", _METRO_NOTICE_CARD)
    head = load_font(theme_font_candidates("metro", "quote_bold"), 44)
    body = load_font(theme_font_candidates("metro", "quote_regular"), 25)
    _metro_centred(draw, 280, "Night Service", head, SPECTRA6["black"])
    # A run of night-line dots under the headline ties the notice to the map.
    for x, y in _metro_dotted_points(((272, 346), (528, 346))):
        draw.ellipse((round(x) - 5, y - 5, round(x) + 5, y + 5), fill=_METRO_NIGHT_INK)
    _metro_centred(draw, 360, "Day lines resume in the morning.", body, SPECTRA6["black"])


def _metro_paint_night_chrome(image: Image.Image) -> None:
    """Masthead, a night-line roundel in place of the hour, and a key that
    shows which lines are running."""
    draw = ImageDraw.Draw(image)
    _metro_paint_masthead(draw, "NIGHT SERVICE", 628)
    small_font = load_font(theme_font_candidates("metro", "ornament"), 14)
    code_font = load_font(theme_font_candidates("metro", "ornament"), 25)

    draw.ellipse((25, 398, 91, 464), fill=_METRO_NIGHT_INK, outline=SPECTRA6["black"], width=4)
    box = draw.textbbox((0, 0), "N", font=code_font)
    draw.text((58 - (box[2] - box[0]) // 2 - box[0], 411), "N", font=code_font, fill=SPECTRA6["white"])
    draw.rectangle((98, 414, 202, 450), fill=SPECTRA6["black"])
    draw.text((110, 423), "ALL NIGHT", font=small_font, fill=SPECTRA6["white"])

    # Key: the night line dotted and RUNNING, the day lines hollow and RESTING.
    x = 232
    for dx in (0, 11, 22):
        draw.ellipse((x + dx - 4, 444, x + dx + 4, 452), fill=_METRO_NIGHT_INK)
    draw.text((x + 34, 439), "NIGHT · RUNNING", font=small_font, fill=SPECTRA6["black"])
    x = 430
    for ink, _points in _METRO_ROUTES:
        if ink == _METRO_NIGHT_INK:
            continue
        draw.line((x, 448, x + 26, 448), fill=ink, width=10)
        draw.line((x, 448, x + 26, 448), fill=SPECTRA6["white"], width=4)
        x += 34
    draw.text((x + 4, 439), "DAY LINES · RESTING", font=small_font, fill=SPECTRA6["black"])


def render_metro_sleep(time_str: str, width: int, height: int) -> Image.Image:
    """The quiet-hours frame: the same map on its night timetable.

    Day routes are drawn hollow (suspended, not erased), the night route runs
    dotted on top, and a service notice replaces the quote card. ``time_str``
    is unused: the frame prints no time, and the renderer does not know when
    quiet hours end.
    """
    del time_str
    image = Image.new("RGB", (800, 480), color=SPECTRA6["white"])
    _metro_paint_night_network(image)
    _metro_paint_notice_card(image)
    _metro_paint_night_chrome(image)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("metro",), render=render_metro_frame, sleep=render_metro_sleep)
