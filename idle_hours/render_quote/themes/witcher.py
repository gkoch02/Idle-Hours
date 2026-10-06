"""The ``witcher`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .._paths import ARCHIVO_BOLD, ARCHIVONARROW_VARIABLE, BARLOWCOND_BOLD, META_FONT_BOLD_CANDIDATES
from ..fonts import _font_ascent, load_font, normalize_dashes
from ..furniture import _row_digest, fallback_title
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, snap_image_to_palette
from ..primitives import _smooth_noise, _white_noise, paint_hatched_tone
from ..spec import FrameSpec
from ..text import draw_text_dithered, draw_tracked, fit_text_to_width, tracked_width

# ---------------------------------------------------------------------------
# witcher — CD Projekt Red's *The Witcher 3: Wild Hunt* (2015): a bestiary
# page under the meditation dial
# ---------------------------------------------------------------------------
# Geralt's journal: a parchment page in a leather binding, an entry title in
# condensed capitals over a red rule, the quote as its epigraph, and a
# "susceptible to" line of sign icons at the foot. The **meditation dial** is
# the time carrier, with three claw slashes at its hub.
#
# **The dial is hour-only**: two engraved rings, 48 ticks, and one marker on
# the hour's radius, a sun by day and a crescent by night (chosen by the
# 24-hour hour). Pinned byte-identical across the minutes of an hour by
# ``TestWitcherFrame``; nothing prints a digit.
#
# **The hub** carries three claw slashes after the III of the logotype (the
# Wolf School emblem is CD Projekt's mark, and Roman bars read only as a
# numeral): red blades outlined in black, the outer two scaled down and swung
# outward.
#
# **The page** is the ``tarot`` vellum recipe (Y+W cream under sparse R+G
# foxing) inside a deckled edge eaten by seeded noise. The binding is black
# with a sparse red fleck, six-ink dark brown.
#
# **Type**: Barlow Condensed for title, quote and matched phrase (R+Y
# tangerine stipple), Archivo Narrow for labels, attribution and the
# ``WILD HUNT`` mark (see the ``THEME_FONTS`` entry). Labels are solid ink:
# small text in a stipple shreds.
#
# **Susceptible to**: the five signs drawn as icons, the susceptible ones
# (from ``_row_digest``) filled in the sign's own colour. The entry number is
# the row's real Gutenberg ID.
#
# The page is quote- and hour-independent and cached once per process
# (``_WITCHER_PAGE``, keyed on the painters). Composed at 800x480 and
# NEAREST-downsampled (the ``metro`` convention).
# ---------------------------------------------------------------------------
_WITCHER_SEED = 0x3331
_WITCHER_PAGE_RECT = (30, 28, 770, 452)
_WITCHER_RULE_INSET = 12
_WITCHER_HEADER_Y = 48
_WITCHER_HEADER_RULE_Y = 106
_WITCHER_DIAL_CENTRE = (180, 254)
_WITCHER_DIAL_RADIUS = 108
_WITCHER_MEDALLION_RADIUS = 50
_WITCHER_QUOTE_RECT = (330, 124, 742, 362)
_WITCHER_ATTRIBUTION_TOP = 372
_WITCHER_FOOT_Y = 404
_WITCHER_SIGNS_RIGHT = 742
_WITCHER_CREAM_DENSITY = 0.14
_WITCHER_FOXING_DENSITY = 0.03
_WITCHER_PAGE: dict = {}
# The hub device in a 100-unit box: one blade, pointed at both ends, with the
# spike that trails it below the cut; the outer two are the same blade scaled
# down and swung outward about the hub.
_WITCHER_CLAW_BLADE = ((50, 2), (58, 14), (61, 32), (56, 56), (52, 64), (44, 58), (40, 32), (42, 14))
_WITCHER_CLAW_SPIKE = ((54, 68), (52, 84), (50, 98), (46, 80), (45, 64))
_WITCHER_CLAW_PIVOT = (50, 74)
_WITCHER_CLAWS = ((0.0, 1.0, 0), (-0.22, 0.88, -26), (0.22, 0.88, 26))   # (lean, scale, x offset)
_WITCHER_SIGNS = ("AARD", "IGNI", "YRDEN", "QUEN", "AXII")


def _witcher_hour(time_str: str) -> int:
    """The 24-hour hour, 0..23: the dial needs to know night from day."""
    try:
        return int(str(time_str).split(":", 1)[0]) % 24
    except ValueError:
        return 12


def _witcher_label_font(size: int, instance: str = "Bold"):
    """Archivo Narrow — the nearest open face to Bell Gothic — pinned by instance."""
    return load_font([(ARCHIVONARROW_VARIABLE, instance), ARCHIVO_BOLD, *META_FONT_BOLD_CANDIDATES], size=size)


def _witcher_page_mask(size) -> Image.Image:
    """The page's silhouette: the rect with a deckled, seeded edge."""
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle(_WITCHER_PAGE_RECT, fill=255)
    band = ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(9)))
    tear = _smooth_noise(size, (size[0] // 3, size[1] // 3), _WITCHER_SEED)
    torn = ImageChops.multiply(band, tear.point(lambda v: 255 if v < 118 else 0))
    return ImageChops.subtract(mask, torn)


def _witcher_paint_binding(image: Image.Image) -> None:
    """The leather the page sits in: black with a sparse red fleck, which is
    how six inks spell dark brown, and a few yellow glints of the grain."""
    width, height = image.size
    grain = _white_noise(width, height, _WITCHER_SEED + 1)
    image.paste(SPECTRA6["red"], (0, 0), grain.point(lambda v: 255 if v < 18 else 0))
    image.paste(SPECTRA6["yellow"], (0, 0), grain.point(lambda v: 255 if 252 < v else 0))


def _witcher_paint_parchment(image: Image.Image) -> None:
    """The page: cream Y+W under a sparse R+G foxing, inside the deckled mask."""
    width, height = image.size
    page = Image.new("RGB", image.size, SPECTRA6["white"])
    foxing = _white_noise(width, height, _WITCHER_SEED + 2)
    fox_cut = round(_WITCHER_FOXING_DENSITY * 255)
    page.paste(SPECTRA6["red"], (0, 0), foxing.point(lambda v: 255 if v < fox_cut and v & 1 else 0))
    page.paste(SPECTRA6["green"], (0, 0), foxing.point(lambda v: 255 if v < fox_cut and not v & 1 else 0))
    cream = _white_noise(width, height, _WITCHER_SEED + 3)
    page.paste(SPECTRA6["yellow"], (0, 0), cream.point(lambda v: 255 if v < round(_WITCHER_CREAM_DENSITY * 255) else 0))
    image.paste(page, (0, 0), _witcher_page_mask(image.size))


def _witcher_paint_rules(image: Image.Image) -> None:
    """The game's thin-line chrome: an inset rule with notched corners, and the
    header rule with a diamond at each end."""
    draw = ImageDraw.Draw(image)
    black, red = SPECTRA6["black"], SPECTRA6["red"]
    x0, y0, x1, y1 = _WITCHER_PAGE_RECT
    inset = _WITCHER_RULE_INSET
    x0, y0, x1, y1 = x0 + inset, y0 + inset, x1 - inset, y1 - inset
    notch = 14
    for (cx, sx), (cy, sy) in (((x0, 1), (y0, 1)), ((x1, -1), (y0, 1)), ((x0, 1), (y1, -1)), ((x1, -1), (y1, -1))):
        draw.line([(cx + sx * notch, cy), (cx, cy), (cx, cy + sy * notch)], fill=black, width=2)
    draw.line([(x0 + notch + 6, y0), (x1 - notch - 6, y0)], fill=black, width=1)
    draw.line([(x0 + notch + 6, y1), (x1 - notch - 6, y1)], fill=black, width=1)
    draw.line([(x0, y0 + notch + 6), (x0, y1 - notch - 6)], fill=black, width=1)
    draw.line([(x1, y0 + notch + 6), (x1, y1 - notch - 6)], fill=black, width=1)
    ry = _WITCHER_HEADER_RULE_Y
    draw.line([(56, ry), (744, ry)], fill=red, width=2)
    for dx in (56, 744):
        draw.polygon([(dx, ry - 5), (dx + 5, ry), (dx, ry + 5), (dx - 5, ry)], fill=red)


def _witcher_paint_dial(image: Image.Image) -> None:
    """The meditation dial's engraving: two rings and the tick train. The
    hour marker is painted per render by ``_witcher_paint_marker``."""
    draw = ImageDraw.Draw(image)
    black = SPECTRA6["black"]
    cx, cy = _WITCHER_DIAL_CENTRE
    r = _WITCHER_DIAL_RADIUS
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=black, width=2)
    inner = r - 18
    draw.ellipse((cx - inner, cy - inner, cx + inner, cy + inner), outline=black, width=1)
    for k in range(48):
        ang = math.radians(k * 7.5 - 90)
        major = k % 4 == 0
        r0 = r - (13 if major else 7)
        r1 = r - 3
        draw.line([(cx + math.cos(ang) * r0, cy + math.sin(ang) * r0),
                   (cx + math.cos(ang) * r1, cy + math.sin(ang) * r1)], fill=black, width=2 if major else 1)
    # A hatched band between the rings' inner edge and the tick train, so the
    # dial reads as an engraved plate rather than a drawn circle.
    band = inner + 2
    paint_hatched_tone(image, (cx - r, cy - r, cx + r, cy + r),
                       lambda x, y: 0.42 if band < math.hypot(x - cx, y - cy) < r - 14 else 0.0,
                       52.0, 3.0, black, ground=frozenset({SPECTRA6["white"], SPECTRA6["yellow"]}))
    label = _witcher_label_font(13)
    draw_tracked(draw, (cx - tracked_width(draw, "MEDITATION", label, tracking=4) / 2, cy + r + 10),
                 "MEDITATION", label, black, tracking=4)


def _witcher_claw(lean: float, scale: float, dx: float):
    """One slash's polygons: the blade scaled and swung about the pivot, then
    shifted along the hub; returns the blade and its spike in box units."""
    px, py = _WITCHER_CLAW_PIVOT
    ca, sa = math.cos(lean), math.sin(lean)

    def swing(pts):
        return [(px + dx + ((x - px) * ca - (y - py) * sa) * scale, py + ((x - px) * sa + (y - py) * ca) * scale)
                for x, y in pts]

    return swing(_WITCHER_CLAW_BLADE), swing(_WITCHER_CLAW_SPIKE)


def _witcher_paint_medallion(image: Image.Image) -> None:
    """The hub: three claw slashes in red, outlined in black so they hold on
    the cream, after the III of the title."""
    draw = ImageDraw.Draw(image)
    black, red = SPECTRA6["black"], SPECTRA6["red"]
    cx, cy = _WITCHER_DIAL_CENTRE
    r = _WITCHER_MEDALLION_RADIUS
    scale = r * 2 / 100.0
    ox, oy = cx - 50 * scale, cy - 50 * scale

    def place(pts):
        return [(ox + x * scale, oy + y * scale) for x, y in pts]

    for lean, size, dx in _WITCHER_CLAWS:
        for piece in _witcher_claw(lean, size, dx):
            draw.polygon(place(piece), fill=red, outline=black)


def _witcher_page() -> Image.Image:
    """The entry page without its entry: binding, parchment, rules, dial, medallion."""
    key = (_witcher_paint_binding, _witcher_paint_parchment, _witcher_paint_rules,
           _witcher_paint_dial, _witcher_paint_medallion)
    cached = _WITCHER_PAGE.get("frame")
    if cached is not None and cached[0] == key:
        return cached[1]
    image = Image.new("RGB", (800, 480), SPECTRA6["black"])
    _witcher_paint_binding(image)
    _witcher_paint_parchment(image)
    _witcher_paint_rules(image)
    _witcher_paint_dial(image)
    _witcher_paint_medallion(image)
    _WITCHER_PAGE["frame"] = (key, image)
    return image


def _witcher_paint_marker(image: Image.Image, hour: int) -> None:
    """The hour on the dial: a sun by day, a crescent by night, on the hour's
    radius between the medallion and the inner ring, with a pointer on the
    tick train."""
    draw = ImageDraw.Draw(image)
    black, yellow, white = SPECTRA6["black"], SPECTRA6["yellow"], SPECTRA6["white"]
    cx, cy = _WITCHER_DIAL_CENTRE
    ang = math.radians((hour % 12) * 30 - 90)
    # The marker rides between the claws' reach and the inner ring, so the
    # sun's rays never cross a blade tip; the pointer sits on the ring itself.
    rr = _WITCHER_DIAL_RADIUS - 36
    mx, my = cx + math.cos(ang) * rr, cy + math.sin(ang) * rr
    tip = _WITCHER_DIAL_RADIUS - 11
    draw.polygon([(cx + math.cos(ang) * tip, cy + math.sin(ang) * tip),
                  (cx + math.cos(ang + 0.09) * (tip - 9), cy + math.sin(ang + 0.09) * (tip - 9)),
                  (cx + math.cos(ang - 0.09) * (tip - 9), cy + math.sin(ang - 0.09) * (tip - 9))], fill=black)
    if 6 <= hour < 18:
        for k in range(8):
            a = math.radians(k * 45)
            draw.line([(mx + math.cos(a) * 9, my + math.sin(a) * 9), (mx + math.cos(a) * 14, my + math.sin(a) * 14)],
                      fill=black, width=2)
        draw.ellipse((mx - 8, my - 8, mx + 8, my + 8), fill=yellow, outline=black, width=2)
    else:
        draw.polygon(_witcher_crescent(mx, my, 10, (4.5, -2.5), 8.5), fill=yellow, outline=black)
    del white


def _witcher_crescent(cx: float, cy: float, r: float, bite, br: float) -> list:
    """A crescent as one polygon (disc arc outside the bite, then bite arc
    inside the disc), so it can be filled and outlined in one call."""
    bx, by = cx + bite[0], cy + bite[1]
    outer = [(cx + math.cos(t) * r, cy + math.sin(t) * r) for t in (k * math.pi / 36 for k in range(72))]
    outer = [p for p in outer if math.hypot(p[0] - bx, p[1] - by) >= br]
    # Rotate the kept arc so it starts just after the bite.
    d = math.atan2(by - cy, bx - cx)
    outer.sort(key=lambda p: (math.atan2(p[1] - cy, p[0] - cx) - d) % (2 * math.pi))
    inner = [(bx + math.cos(t) * br, by + math.sin(t) * br) for t in (k * math.pi / 36 for k in range(72))]
    inner = [p for p in inner if math.hypot(p[0] - cx, p[1] - cy) <= r]
    inner.sort(key=lambda p: (math.atan2(p[1] - by, p[0] - bx) - d - math.pi) % (2 * math.pi))
    def area(pts):
        return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1], strict=True)))
    a, b = outer + inner, outer + inner[::-1]
    return a if area(a) >= area(b) else b


def _witcher_entry_title(quote_row: dict) -> str:
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "") or "Untitled Entry"
    return title.upper()


def _witcher_paint_header(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """``BESTIARY`` and the entry number over the title in condensed capitals."""
    black, red = SPECTRA6["black"], SPECTRA6["red"]
    x0, x1 = 56, 744
    small = _witcher_label_font(13)
    draw_tracked(draw, (x0, _WITCHER_HEADER_Y - 2), "BESTIARY", small, red, tracking=4)
    source_id = str(quote_row.get("source_id") or "").strip()
    if source_id:
        draw_tracked(draw, (x1, _WITCHER_HEADER_Y - 2), f"ENTRY No. {source_id}", small, black, tracking=3,
                     anchor_right=True)
    title_font, title = fit_text_to_width(draw, _witcher_entry_title(quote_row),
                                          [BARLOWCOND_BOLD, (ARCHIVONARROW_VARIABLE, "Bold"), *META_FONT_BOLD_CANDIDATES],
                                          34, x1 - x0, floor=22, tracking=1)
    draw_tracked(draw, (x0, _WITCHER_HEADER_Y + 16), title, title_font, black, tracking=1)


def _witcher_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The entry's epigraph: Barlow Condensed in black ink, ragged right, the
    matched phrase Bold in the interface's red-orange (R+Y tangerine)."""
    x0, y0, x1, y1 = _WITCHER_QUOTE_RECT
    black, red, yellow = SPECTRA6["black"], SPECTRA6["red"], SPECTRA6["yellow"]
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    quote_font, quote_font_bold, wrapped, line_height, _ = fit_quote(
        draw, display_quote, quote_row.get("matched_text") or "",
        x1 - x0, y1 - y0, font_max=32, font_min=14, line_height_mult=1.28, theme="witcher",
    )
    y = y0
    ascent = _font_ascent(quote_font)
    for line in wrapped:
        x = x0
        for chunk, is_bold in line:
            font = quote_font_bold if is_bold else quote_font
            chunk_y = y + (ascent - _font_ascent(font))
            if is_bold:
                draw_text_dithered(image, (x, chunk_y), chunk, font, red, yellow, light_density=0.375)
            else:
                draw.text((x, chunk_y), chunk, font=font, fill=black)
            x += int(round(draw.textlength(chunk, font=font)))
        y += line_height
    author = (quote_row.get("author") or "").strip()
    if author:
        attribution = _witcher_label_font(15, "Medium")
        draw_tracked(draw, (x0, min(y + 10, _WITCHER_ATTRIBUTION_TOP)), f"— {author.upper()}", attribution, black,
                     tracking=2)


# The signs' colours: Aard blue, Igni red, Yrden's violet as blue with red
# spokes (a two-ink stipple is too small at 16 px), Quen gold, Axii solid red.
_WITCHER_SIGN_INKS = {"AARD": "blue", "IGNI": "red", "YRDEN": "blue", "QUEN": "yellow", "AXII": "red"}


def _witcher_susceptible(quote_row: dict) -> set:
    """The signs this entry is susceptible to: one bit of the digest each,
    at least one always."""
    digest = _row_digest(quote_row)
    susceptible = {name for k, name in enumerate(_WITCHER_SIGNS) if (digest >> k) & 1}
    return susceptible or {_WITCHER_SIGNS[digest % 5]}


def _witcher_sign_icon(draw: ImageDraw.ImageDraw, name: str, cx: float, cy: float, filled: bool) -> None:
    """One of the five signs as a 16 px icon, in its own colour when the entry
    is susceptible to it and a black outline otherwise."""
    black, red = SPECTRA6["black"], SPECTRA6["red"]
    ink = SPECTRA6[_WITCHER_SIGN_INKS[name]] if filled else black
    if name == "AARD":                                          # a blast: three chevrons
        for k in range(3):
            x = cx - 7 + k * 5
            draw.line([(x, cy - 7), (x + 5, cy), (x, cy + 7)], fill=ink, width=2)
    elif name == "IGNI":                                        # a flame
        pts = [(cx, cy - 9), (cx + 6, cy - 1), (cx + 4, cy + 8), (cx - 4, cy + 8), (cx - 6, cy - 1)]
        if filled:
            draw.polygon(pts, fill=ink)
        else:
            draw.polygon(pts, outline=ink, width=2)
        draw.polygon([(cx, cy - 2), (cx + 2, cy + 4), (cx - 2, cy + 4)], fill=SPECTRA6["white"])
    elif name == "YRDEN":                                       # the trap: a circle with three spokes
        draw.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), outline=ink, width=2, fill=ink if filled else None)
        for k in range(3):
            a = math.radians(k * 120 - 90)
            draw.line([(cx, cy), (cx + math.cos(a) * 7, cy + math.sin(a) * 7)], fill=red if filled else ink, width=2)
    elif name == "QUEN":                                        # the shield: a diamond in a diamond
        outer = [(cx, cy - 9), (cx + 8, cy), (cx, cy + 9), (cx - 8, cy)]
        if filled:
            draw.polygon(outer, fill=ink, outline=black)
            draw.polygon([(cx, cy - 4), (cx + 3, cy), (cx, cy + 4), (cx - 3, cy)], fill=black)
        else:
            draw.polygon(outer, outline=ink, width=2)
            draw.polygon([(cx, cy - 4), (cx + 3, cy), (cx, cy + 4), (cx - 3, cy)], outline=ink)
    else:                                                       # AXII: a spiral
        pts = [(cx + math.cos(t) * t * 1.35, cy + math.sin(t) * t * 1.35) for t in [k * 0.25 for k in range(1, 27)]]
        draw.line(pts, fill=ink, width=3 if filled else 2)


def _witcher_paint_foot(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The entry's foot: the ``WILD HUNT`` mark at the left, and the five signs
    at the right, the susceptible ones filled in their own colour."""
    black, red = SPECTRA6["black"], SPECTRA6["red"]
    y = _WITCHER_FOOT_Y
    mark = _witcher_label_font(15)
    draw_tracked(draw, (56, y + 2), "THE WITCHER", mark, black, tracking=3)
    w = tracked_width(draw, "THE WITCHER", mark, tracking=3)
    draw_tracked(draw, (56 + w + 12, y + 2), "WILD HUNT", mark, red, tracking=3)
    label = _witcher_label_font(12, "Medium")
    susceptible = _witcher_susceptible(quote_row)
    x = _WITCHER_SIGNS_RIGHT
    for name in reversed(_WITCHER_SIGNS):
        x -= 24
        _witcher_sign_icon(draw, name, x + 10, y + 10, name in susceptible)
    draw_tracked(draw, (x - 12, y + 4), "SUSCEPTIBLE TO", label, black, tracking=3, anchor_right=True)


def render_witcher_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A bestiary page under the meditation dial (see the section comment above)."""
    hour = _witcher_hour(time_str)
    image = _witcher_page().copy()
    draw = ImageDraw.Draw(image)
    _witcher_paint_marker(image, hour)
    _witcher_paint_header(image, draw, quote_row)
    _witcher_paint_quote(image, draw, quote_row)
    _witcher_paint_foot(image, draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("witcher",), render=render_witcher_frame)
