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


def _metro_paint_network(image: Image.Image) -> None:
    """Paint a schematic network with genuine 45-degree route geometry."""
    draw = ImageDraw.Draw(image)
    # Sparse coordinate dots give the white stock a printed-map texture
    # without turning it into graph paper or competing with the route lines.
    for y in range(64, 480, 32):
        for x in range(20, 800, 40):
            draw.point((x, y), fill=SPECTRA6["black"])
    # White gaps break the grid beneath each route, mimicking the casing used
    # on real diagram maps; the chromatic stroke then sits cleanly on top.
    for ink, points in _METRO_ROUTES:
        draw.line(points, fill=SPECTRA6["white"], width=15, joint="curve")
        draw.line(points, fill=ink, width=9, joint="curve")
        for x, y in points[1:-1]:
            draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=SPECTRA6["white"], outline=SPECTRA6["black"], width=2)

    # Four interchanges: a black outer ring and white centre are legible over
    # every route ink, and the paired nodes read as transfers rather than dots.
    for x, y in ((188, 222), (318, 196), (482, 196), (612, 222)):
        draw.ellipse((x - 12, y - 12, x + 12, y + 12), fill=SPECTRA6["white"], outline=SPECTRA6["black"], width=4)
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=SPECTRA6["black"])


def _metro_paint_chrome(image: Image.Image, time_str: str) -> None:
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 800, 48), fill=SPECTRA6["black"])
    label_font = load_font(theme_font_candidates("metro", "ornament"), 19)
    small_font = load_font(theme_font_candidates("metro", "ornament"), 14)
    draw.text((26, 13), "IDLE HOURS METROPOLITAN", font=label_font, fill=SPECTRA6["white"])
    draw.text((625, 16), "LITERARY LINE", font=small_font, fill=SPECTRA6["yellow"])

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


def _metro_paint_quote_card(image: Image.Image, quote_row: dict) -> None:
    draw = ImageDraw.Draw(image)
    card = (116, 100, 684, 388)
    # Offset shadow + black keyline give the legend the physical hierarchy of
    # a pasted service notice, not a white hole accidentally left in the map.
    draw.rectangle((124, 108, 692, 396), fill=SPECTRA6["black"])
    draw.rectangle(card, fill=SPECTRA6["white"], outline=SPECTRA6["black"], width=4)
    draw.rectangle((116, 100, 684, 126), fill=SPECTRA6["black"])
    tab_font = load_font(theme_font_candidates("metro", "ornament"), 14)
    draw.text((132, 107), "CENTRAL INTERCHANGE  •  ALL STORIES CONNECT", font=tab_font, fill=SPECTRA6["white"])

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
        for (chunk, is_bold), chunk_w in zip(line, widths):
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


SPEC = FrameSpec(themes=("metro",), render=render_metro_frame)
