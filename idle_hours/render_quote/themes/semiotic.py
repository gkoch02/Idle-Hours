"""The ``semiotic`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import random

from PIL import Image, ImageChops, ImageDraw, ImageFont

from .._paths import BARLOWCOND_BOLD, BARLOWCOND_MEDIUM, BARLOWCOND_SEMIBOLD, BASE_DIR, META_FONT_BOLD_CANDIDATES, OSWALD_VARIABLE
from ..fonts import load_font
from ..furniture import _clock_hour12, _row_digest, fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, snap_image_to_palette
from ..primitives import wrap_quote_into_masks
from ..spec import FrameSpec
from ..text import draw_tracked, fit_text_to_width, tracked_width

# ---------------------------------------------------------------------------
# semiotic — Ron Cobb's Semiotic Standard, the Nostromo signage from *Alien*
# ---------------------------------------------------------------------------
# A custom frame: a black bulkhead between yellow/black hazard stripes, one
# large sign for the hour with three smaller companions, and the quote on a
# crew-notice placard framed the way Cobb framed his signs — white edge, red
# band, white panel, the band broken at the rules.
#
# **The signs are the real set, not redrawn.** ``SEMIOTIC_SIGNS`` is a sprite
# sheet built by ``scripts/ingest_semiotic_signs.py`` from LouH's CC BY 4.0
# vector adaptation (attribution in ``assets/semiotic/README.md``). Its seven
# flat colours each map to one native ink, except the "system" grey, which is
# the K+W 50/50 stipple, so the signs need classification, not dithering.
#
# **Classify after resizing, never before.** Each antialiased tile is resized
# to its painted size, composited onto the black ground, and only then snapped
# by ``quantize`` to the seven source values; snapping first and resizing
# blends inks off-palette. The grey's stipple is phased on absolute canvas
# coordinates so adjacent grey fields share one checkerboard.
#
# **The hour is the section**: the featured sign is the hour's
# (``_SEMIOTIC_HOUR_SIGNS``) and the header reads ``SECTION 07``. Hour only, so
# every minute of an hour renders byte-identically. The three companions and
# the notice's reference number come from ``_row_digest``.
#
# If the sheet is missing the signs degrade to blank red-framed panels.
SEMIOTIC_SIGNS = BASE_DIR / "assets" / "semiotic_signs.png"
_SEMIOTIC_SHEET_COLS = 6
_SEMIOTIC_TILE = (250, 262)
_SEMIOTIC_SHEET_CACHE: dict = {}

# Legend order — must match ``scripts/ingest_semiotic_signs.py``'s ``SIGNS``.
_SEMIOTIC_SIGNS: tuple[tuple[str, str], ...] = (
    ("001", "PRESSURISED AREA"),
    ("002", "PRESSURISED WITH ARTIFICIAL GRAVITY"),
    ("003", "ARTIFICIAL GRAVITY ABSENT"),
    ("004", "CRYOGENIC VAULT"),
    ("005", "AIRLOCK"),
    ("006", "BULKHEAD DOOR"),
    ("007", "NON-PRESSURISED AREA BEYOND"),
    ("008", "PRESSURE SUIT LOCKER"),
    ("009", "PHOTONIC SYSTEM (FIBRE OPTICS)"),
    ("010", "LASER"),
    ("011", "ASTRONIC SYSTEM (ELECTRONICS)"),
    ("012", "HAZARD WARNING"),
    ("013", "ARTIFICIAL GRAVITY AREA, NON-PRESSURISED SUIT REQUIRED"),
    ("014", "NO PRESSURE, GRAVITY SUIT REQUIRED"),
    ("015", "EXHAUST"),
    ("016", "AREA SHIELDED FROM RADIATION"),
    ("017", "RADIATION HAZARD"),
    ("018", "HIGH RADIOACTIVITY"),
    ("019", "REFRIGERATION"),
    ("020", "DIRECTION"),
    ("020A", "DIRECTION"),
    ("020B", "DIRECTION"),
    ("020C", "DIRECTION"),
    ("021", "LIFE SUPPORT SYSTEM"),
    ("022", "GALLEY"),
    ("023", "COFFEE"),
    ("024", "BRIDGE"),
    ("025", "AUTODOC"),
    ("026", "MAINTENANCE"),
    ("027", "LADDERWAY"),
    ("028", "INTERCOM"),
    ("029", "STORAGE, NON-ORGANIC"),
    ("029A", "STORAGE, ORGANIC (FOODSTUFFS)"),
    ("030", "COMPUTER TERMINAL"),
)
_SEMIOTIC_INDEX = {code: i for i, (code, _) in enumerate(_SEMIOTIC_SIGNS)}
_SEMIOTIC_NAMES = dict(_SEMIOTIC_SIGNS)

# One sign per hour, chosen for silhouette variety across the day.
_SEMIOTIC_HOUR_SIGNS = {
    1: "005", 2: "006", 3: "003", 4: "004", 5: "008", 6: "010",
    7: "012", 8: "014", 9: "015", 10: "018", 11: "030", 12: "024",
}
# Companions: every sign except the blank-panel "pressurised area" and the
# four direction chevrons, which read as decoration rather than as places.
_SEMIOTIC_COMPANION_POOL = tuple(
    code for code, _ in _SEMIOTIC_SIGNS if code != "001" and not code.startswith("020")
)

# The adaptation's seven flat values and the ink each lands on (None = the
# K+W stipple). Measured off the upstream PNGs; amber appears as both
# (255, 176, 0) and (255, 170, 0), which one entry covers.
_SEMIOTIC_SOURCE_INKS: tuple[tuple[tuple[int, int, int], tuple[int, int, int] | None], ...] = (
    ((255, 255, 255), SPECTRA6["white"]),
    ((0, 0, 0), SPECTRA6["black"]),
    ((160, 0, 0), SPECTRA6["red"]),
    ((255, 176, 0), SPECTRA6["yellow"]),
    ((10, 10, 112), SPECTRA6["blue"]),
    ((0, 68, 17), SPECTRA6["green"]),
    ((96, 96, 96), None),
)

_SEMIOTIC_FEATURE_BOX = (24, 60, 220, 231)          # x, y, w, h — the 1000:1050 aspect
_SEMIOTIC_COMPANION_Y = 373
_SEMIOTIC_COMPANION_SIZE = (68, 71)
_SEMIOTIC_COMPANION_XS = (24, 100, 176)
_SEMIOTIC_PLACARD = (264, 60, 776, 444)
_SEMIOTIC_HAZARD_BANDS = ((0, 16), (458, 480))
_SEMIOTIC_STRIPE = 14                                  # hazard stripe width, px
_SEMIOTIC_HEADER_RULE_Y = 120
_SEMIOTIC_FOOTER_RULE_Y = 384
_SEMIOTIC_QUOTE_RECT = (306, 132, 734, 374)
_SEMIOTIC_LAMPS = ("blue", "green", "yellow", "red")


def _semiotic_font(weight: str, size: int):
    """Barlow Condensed at a named weight, falling back like the theme chains."""
    path = {"Medium": BARLOWCOND_MEDIUM, "SemiBold": BARLOWCOND_SEMIBOLD, "Bold": BARLOWCOND_BOLD}[weight]
    return load_font([path, (OSWALD_VARIABLE, weight), *META_FONT_BOLD_CANDIDATES], size=size)


def _semiotic_companions(quote_row: dict, featured: str) -> tuple[str, str, str]:
    """Three distinct companion signs for this quote, never the featured one."""
    pool = [code for code in _SEMIOTIC_COMPANION_POOL if code != featured]
    rng = random.Random(_row_digest(quote_row))
    first, second, third = rng.sample(pool, 3)
    return first, second, third


def _semiotic_sheet() -> Image.Image | None:
    """The decoded sprite sheet, memoised per process; ``None`` if missing."""
    key = str(SEMIOTIC_SIGNS)
    if key not in _SEMIOTIC_SHEET_CACHE:
        try:
            with Image.open(SEMIOTIC_SIGNS) as sheet:
                _SEMIOTIC_SHEET_CACHE[key] = sheet.convert("RGBA")
        except (OSError, ValueError):
            _SEMIOTIC_SHEET_CACHE[key] = None
    return _SEMIOTIC_SHEET_CACHE[key]


def _semiotic_palette_image(values) -> Image.Image:
    """A ``P`` image carrying ``values`` (a subset of the source values), for
    ``quantize``.

    Unused slots repeat the first entry; ``_semiotic_classify`` maps indices by
    their palette colour, not their position, so a duplicate can never pick a
    different ink.
    """
    flat = [c for v in values for c in v]
    flat += list(values[0]) * (256 - len(values))
    pal = Image.new("P", (1, 1))
    pal.putpalette(flat)
    return pal


_SEMIOTIC_VALUES_CACHE: dict = {}


def _semiotic_sign_values(code: str, master: Image.Image) -> tuple:
    """The source values this sign actually uses, in ``_SEMIOTIC_SOURCE_INKS`` order.

    Against all seven, an antialiased seam can land on a colour the sign lacks
    (a black/white edge averages close to the dark green). Restricting each
    sign to values covering at least 0.5% of its opaque master keeps edges on
    the inks that meet there. Black is always allowed (the ground).
    """
    if code not in _SEMIOTIC_VALUES_CACHE:
        all_values = [v for v, _ in _SEMIOTIC_SOURCE_INKS]
        opaque = Image.new("RGBA", master.size, SPECTRA6["black"] + (255,))
        opaque.alpha_composite(master)
        indexed = opaque.convert("RGB").quantize(palette=_semiotic_palette_image(all_values),
                                                 dither=Image.Dither.NONE)
        counts = indexed.histogram()
        floor = 0.005 * master.width * master.height
        keep = {all_values[i] for i in range(len(all_values)) if counts[i] >= floor}
        keep.add((0, 0, 0))
        _SEMIOTIC_VALUES_CACHE[code] = tuple(v for v in all_values if v in keep)
    return _SEMIOTIC_VALUES_CACHE[code]


def _semiotic_classify(tile: Image.Image, origin: tuple[int, int], values) -> Image.Image:
    """Snap an RGB tile onto the inks: nearest of ``values``, then grey → the
    K+W checkerboard phased on absolute canvas coordinates."""
    indexed = tile.quantize(palette=_semiotic_palette_image(values), dither=Image.Dither.NONE)
    palette = indexed.getpalette()
    assert palette is not None  # quantize always yields a P image
    table = palette[: 3 * 256]
    lookup: dict[tuple[int, ...], tuple[int, int, int] | None] = {v: ink for v, ink in _SEMIOTIC_SOURCE_INKS}
    grey_index = []
    inks: list[int] = []
    for i in range(256):
        value = tuple(table[3 * i:3 * i + 3]) if 3 * i + 2 < len(table) else (255, 255, 255)
        ink = lookup.get(value, SPECTRA6["white"])
        grey_index.append(255 if value in lookup and ink is None else 0)
        inks.extend(ink if ink is not None else SPECTRA6["white"])
    base = indexed.copy()
    base.putpalette(inks)
    base = base.convert("RGB")
    idx = Image.frombytes("L", indexed.size, indexed.tobytes())
    grey = idx.point(grey_index)
    if grey.getbbox() is not None:
        w, h = tile.size
        ox, oy = origin
        even = bytes(255 if (x + ox) & 1 else 0 for x in range(w + 1))
        rows = b"".join(even[(p := (y + oy) & 1):p + w] for y in range(h))
        checker = Image.frombytes("L", (w, h), rows)
        base.paste(SPECTRA6["black"], (0, 0), ImageChops.multiply(grey, checker))
    return base


def _semiotic_paint_blank_sign(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    """A blank red-framed panel: the missing-sheet stand-in for a sign."""
    x0, y0, w, h = box
    r = max(4, w // 7)
    draw.rounded_rectangle((x0, y0, x0 + w - 1, y0 + h - 1), radius=r, fill=SPECTRA6["white"])
    inset = max(2, w // 40)
    draw.rounded_rectangle((x0 + inset, y0 + inset, x0 + w - 1 - inset, y0 + h - 1 - inset),
                           radius=r - inset, fill=SPECTRA6["red"])
    band = max(4, w // 10)
    draw.rounded_rectangle((x0 + band, y0 + band, x0 + w - 1 - band, y0 + h - 1 - band),
                           radius=max(2, r - band), fill=SPECTRA6["white"])


def _semiotic_paint_sign(image: Image.Image, code: str, box: tuple[int, int, int, int]) -> None:
    """Paint one Standard sign at ``box`` (x, y, w, h) onto the black ground."""
    x0, y0, w, h = box
    sheet = _semiotic_sheet()
    if sheet is None:
        _semiotic_paint_blank_sign(ImageDraw.Draw(image), box)
        return
    i = _SEMIOTIC_INDEX[code]
    tw, th = _SEMIOTIC_TILE
    sx, sy = (i % _SEMIOTIC_SHEET_COLS) * tw, (i // _SEMIOTIC_SHEET_COLS) * th
    full = sheet.crop((sx, sy, sx + tw, sy + th))
    values = _semiotic_sign_values(code, full)
    master = full.resize((w, h), Image.Resampling.LANCZOS)
    ground = Image.new("RGBA", (w, h), SPECTRA6["black"] + (255,))
    ground.alpha_composite(master)
    inked = _semiotic_classify(ground.convert("RGB"), (x0, y0), values)
    mask = master.getchannel("A").point(lambda a: 255 if a > 127 else 0)
    image.paste(inked, (x0, y0), mask)


def _semiotic_paint_hazard(image: Image.Image) -> None:
    """Yellow/black 45-degree hazard stripes across the head and foot."""
    width = image.width
    s = _SEMIOTIC_STRIPE
    for y0, y1 in _SEMIOTIC_HAZARD_BANDS:
        h = y1 - y0
        band = Image.new("RGB", (width, h), SPECTRA6["black"])
        draw = ImageDraw.Draw(band)
        for k in range(-h, width + h, 2 * s):
            draw.polygon([(k, h), (k + s, h), (k + s + h, 0), (k + h, 0)], fill=SPECTRA6["yellow"])
        image.paste(band, (0, y0))


def _semiotic_paint_header(image: Image.Image, draw: ImageDraw.ImageDraw, hour: int) -> None:
    """Standard name left; status lamps and the hour's section right."""
    _semiotic_paint_header_bar(image, draw, "SECTION", f"{hour:02d}", _SEMIOTIC_LAMPS)


def _semiotic_paint_header_bar(image: Image.Image, draw: ImageDraw.ImageDraw, label: str, value: str,
                               lit: tuple[str, ...]) -> None:
    """Standard name left; status lamps, a white label and a yellow value right.

    Lamps not in ``lit`` are drawn dark (black, white rim).
    """
    white, yellow = SPECTRA6["white"], SPECTRA6["yellow"]
    font = _semiotic_font("SemiBold", 17)
    draw_tracked(draw, (24, 25), "SEMIOTIC STANDARD", font, white, tracking=3)
    right = image.width - 24
    draw_tracked(draw, (right, 25), value, _semiotic_font("Bold", 17), yellow, tracking=2, anchor_right=True)
    num_w = tracked_width(draw, value, _semiotic_font("Bold", 17), tracking=2)
    label_w = draw_tracked(draw, (right - num_w - 8, 25), label, font, white, tracking=3, anchor_right=True)
    x = right - num_w - 8 - label_w - 22
    for name in reversed(_SEMIOTIC_LAMPS):
        draw.ellipse((x - 5, 31, x + 5, 41), fill=SPECTRA6[name if name in lit else "black"], outline=white)
        x -= 18


def _semiotic_wrap_name(draw, name: str, max_w: int) -> tuple[list[str], ImageFont.FreeTypeFont]:
    """The featured sign's name in at most two lines, shrinking to fit."""
    for size in (19, 17, 15, 13):
        font = _semiotic_font("Bold", size)
        lines, line = [], ""
        for word in name.split():
            trial = f"{line} {word}".strip()
            if line and tracked_width(draw, trial, font, tracking=1) > max_w:
                lines.append(line)
                line = word
            else:
                line = trial
        lines.append(line)
        if len(lines) <= 2 and all(tracked_width(draw, ln, font, tracking=1) <= max_w for ln in lines):
            return lines, font
    return lines[:2], font


def _semiotic_paint_signs(image: Image.Image, draw: ImageDraw.ImageDraw, hour: int, quote_row: dict) -> None:
    """The hour's sign, its number and name, and three companions below."""
    featured = _SEMIOTIC_HOUR_SIGNS[hour]
    x, y, w, h = _SEMIOTIC_FEATURE_BOX
    _semiotic_paint_sign(image, featured, (x, y, w, h))
    label_y = y + h + 8
    draw_tracked(draw, (x, label_y), f"NO. {featured}", _semiotic_font("SemiBold", 14), SPECTRA6["yellow"], tracking=2)
    lines, font = _semiotic_wrap_name(draw, _SEMIOTIC_NAMES[featured], w)
    ly: float = label_y + 19
    for line in lines:
        draw_tracked(draw, (x, ly), line, font, SPECTRA6["white"], tracking=1)
        ly += font.size + 2
    cw, ch = _SEMIOTIC_COMPANION_SIZE
    for cx, code in zip(_SEMIOTIC_COMPANION_XS, _semiotic_companions(quote_row, featured), strict=True):
        _semiotic_paint_sign(image, code, (cx, _SEMIOTIC_COMPANION_Y, cw, ch))


def _semiotic_paint_placard_frame(draw: ImageDraw.ImageDraw) -> None:
    """The placard's Cobb frame — white edge, red band, white panel — with the
    band broken where the header and footer rules cross it."""
    x0, y0, x1, y1 = _SEMIOTIC_PLACARD
    white, red, black = SPECTRA6["white"], SPECTRA6["red"], SPECTRA6["black"]
    draw.rounded_rectangle((x0, y0, x1, y1), radius=24, fill=white)
    draw.rounded_rectangle((x0 + 6, y0 + 6, x1 - 6, y1 - 6), radius=19, fill=red)
    draw.rounded_rectangle((x0 + 19, y0 + 19, x1 - 19, y1 - 19), radius=8, fill=white)
    for ry in (_SEMIOTIC_HEADER_RULE_Y, _SEMIOTIC_FOOTER_RULE_Y):
        draw.rectangle((x0 + 6, ry - 4, x0 + 19, ry + 4), fill=white)
        draw.rectangle((x1 - 19, ry - 4, x1 - 6, ry + 4), fill=white)
        draw.rectangle((x0 + 19, ry - 1, x1 - 19, ry + 1), fill=black)


def _semiotic_paint_placard(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The crew notice, framed as Cobb framed a sign: white edge, red band
    broken where the header and footer rules cross it, white panel."""
    x0, y0, x1, y1 = _SEMIOTIC_PLACARD
    red, black = SPECTRA6["red"], SPECTRA6["black"]
    _semiotic_paint_placard_frame(draw)

    head = _semiotic_font("Bold", 22)
    draw_tracked(draw, (x0 + 34, 86), "CREW NOTICE", head, black, tracking=3)
    ref = f"REF {_row_digest(quote_row) % 10000:04d}-{_row_digest(quote_row) // 10000 % 100:02d}"
    draw_tracked(draw, (x1 - 34, 91), ref, _semiotic_font("SemiBold", 15), black, tracking=2, anchor_right=True)

    prose, hot, _ = wrap_quote_into_masks(
        draw, image.size, quote_row, _SEMIOTIC_QUOTE_RECT, theme="semiotic",
        font_max=40, font_min=16, line_height_mult=1.16,
    )
    image.paste(black, (0, 0), prose.point(lambda v: 255 if v > 128 else 0))
    image.paste(red, (0, 0), hot.point(lambda v: 255 if v > 128 else 0))
    prose.close()
    hot.close()

    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "")
    byline = " · ".join(part.upper() for part in (author, title) if part)
    if byline:
        candidates = [BARLOWCOND_SEMIBOLD, (OSWALD_VARIABLE, "Medium"), *META_FONT_BOLD_CANDIDATES]
        max_w = (x1 - x0) - 2 * 40
        font, text = fit_text_to_width(draw, byline, candidates, 17, max_w, floor=12, tracking=1)
        text_w = tracked_width(draw, text, font, tracking=1)
        draw_tracked(draw, ((x0 + x1 - text_w) / 2, _SEMIOTIC_FOOTER_RULE_Y + 12), text, font, black, tracking=1)


def render_semiotic_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Cobb's Semiotic Standard on a Nostromo bulkhead (see the section comment)."""
    hour = _clock_hour12(time_str)
    image = Image.new("RGB", (800, 480), color=SPECTRA6["black"])
    draw = ImageDraw.Draw(image)
    _semiotic_paint_hazard(image)
    _semiotic_paint_header(image, draw, hour)
    _semiotic_paint_signs(image, draw, hour, quote_row)
    _semiotic_paint_placard(image, draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


# ---------------------------------------------------------------------------
# The sleep frame: HYPERSLEEP — the crew in stasis, the ship at rest
# ---------------------------------------------------------------------------
# *Alien* opens on the Nostromo's crew waking from hypersleep, so the quiet-
# hours frame is the same bulkhead showing them still under: a status panel,
# not an alarm. The featured sign is Cobb's own **004 CRYOGENIC VAULT**, from
# the sheet like every other sign: it is what the Nostromo's hypersleep vault
# actually carried. (A pod drawn in code stood here first; the real sign is
# truer and keeps the provenance simple.) The companions are calm signs from
# the sheet: 021 LIFE SUPPORT SYSTEM, 025 AUTODOC and 030 COMPUTER TERMINAL,
# MOTHER flying the ship while the crew sleeps. The placard's seven small
# pods, the Nostromo's crew of seven, are an illustration drawn in code, not
# a sign.
_SEMIOTIC_SLEEP_SIGN = "004"
_SEMIOTIC_SLEEP_COMPANIONS = ("021", "025", "030")
_SEMIOTIC_SLEEP_LAMPS = ("blue", "green")
_SEMIOTIC_SLEEP_CREW = 7
_SEMIOTIC_SLEEP_POD_Y = 146
_SEMIOTIC_SLEEP_POD_W = 50


def _semiotic_paint_pod(draw: ImageDraw.ImageDraw, x: int, y: int, w: int) -> int:
    """The hypersleep pod pictogram, ``w`` wide with its top-left at (x, y);
    returns its height.

    Seen side-on: a blue glass lid domed over a black tub on a plinth, and
    under the lid a white figure lying down, Cobb's bar and dot.
    """
    black, blue, white = SPECTRA6["black"], SPECTRA6["blue"], SPECTRA6["white"]
    dome_h = round(0.25 * w)
    tub_h = round(0.2 * w)
    inset = round(0.05 * w)
    draw.rounded_rectangle((x + inset, y, x + w - 1 - inset, y + dome_h), radius=dome_h,
                           fill=blue, corners=(True, True, False, False))
    tub_y = y + dome_h
    draw.rounded_rectangle((x, tub_y, x + w - 1, tub_y + tub_h - 1), radius=tub_h // 2, fill=black)
    draw.rectangle((x, tub_y, x + w - 1, tub_y + tub_h // 2), fill=black)
    bar = max(2, round(0.09 * w))
    dot = max(3, round(0.15 * w))
    cy = tub_y - max(1, round(0.03 * w)) - dot / 2
    bx0, bx1 = x + round(0.2 * w), x + round(0.64 * w)
    draw.rectangle((bx0, round(cy + dot / 2) - bar, bx1, round(cy + dot / 2) - 1), fill=white)
    dx0 = bx1 + max(2, round(0.03 * w))
    draw.ellipse((dx0, round(cy - dot / 2), dx0 + dot - 1, round(cy - dot / 2) + dot - 1), fill=white)
    plinth_h = max(2, round(0.1 * w))
    base_y = tub_y + tub_h
    draw.rectangle((x + round(0.24 * w), base_y, x + w - 1 - round(0.24 * w), base_y + plinth_h - 1), fill=black)
    return dome_h + tub_h + plinth_h


def _semiotic_paint_sleep_signs(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """004 CRYOGENIC VAULT with its legend, as the quote frame features an
    hour's sign, and three calm companions."""
    x, y, w, h = _SEMIOTIC_FEATURE_BOX
    _semiotic_paint_sign(image, _SEMIOTIC_SLEEP_SIGN, (x, y, w, h))
    label_y = y + h + 8
    draw_tracked(draw, (x, label_y), f"NO. {_SEMIOTIC_SLEEP_SIGN}", _semiotic_font("SemiBold", 14),
                 SPECTRA6["yellow"], tracking=2)
    lines, font = _semiotic_wrap_name(draw, _SEMIOTIC_NAMES[_SEMIOTIC_SLEEP_SIGN], w)
    ly: float = label_y + 19
    for line in lines:
        draw_tracked(draw, (x, ly), line, font, SPECTRA6["white"], tracking=1)
        ly += font.size + 2
    cw, ch = _SEMIOTIC_COMPANION_SIZE
    for cx, code in zip(_SEMIOTIC_COMPANION_XS, _SEMIOTIC_SLEEP_COMPANIONS, strict=True):
        _semiotic_paint_sign(image, code, (cx, _SEMIOTIC_COMPANION_Y, cw, ch))


def _semiotic_centred(draw: ImageDraw.ImageDraw, y: float, text: str, font, tracking: float) -> None:
    """One tracked black line centred on the placard."""
    x0, _, x1, _ = _SEMIOTIC_PLACARD
    text_w = tracked_width(draw, text, font, tracking=tracking)
    draw_tracked(draw, ((x0 + x1 - text_w) / 2, y), text, font, SPECTRA6["black"], tracking=tracking)


def _semiotic_paint_sleep_placard(draw: ImageDraw.ImageDraw) -> None:
    """The stasis notice: the crew's pods in a row, the status beneath."""
    x0, _, x1, _ = _SEMIOTIC_PLACARD
    black = SPECTRA6["black"]
    _semiotic_paint_placard_frame(draw)
    draw_tracked(draw, (x0 + 34, 86), "HYPERSLEEP", _semiotic_font("Bold", 22), black, tracking=3)
    draw_tracked(draw, (x1 - 34, 91), "DO NOT DISTURB", _semiotic_font("SemiBold", 15), black,
                 tracking=2, anchor_right=True)
    n, pod_w = _SEMIOTIC_SLEEP_CREW, _SEMIOTIC_SLEEP_POD_W
    qx0, _, qx1, _ = _SEMIOTIC_QUOTE_RECT
    gap = ((qx1 - qx0) - n * pod_w) // (n - 1)
    left = (x0 + x1 + 1 - (n * pod_w + (n - 1) * gap)) // 2
    for i in range(n):
        _semiotic_paint_pod(draw, left + i * (pod_w + gap), _SEMIOTIC_SLEEP_POD_Y, pod_w)
    _semiotic_centred(draw, 214, "CREW IN STASIS", _semiotic_font("Bold", 50), tracking=3)
    _semiotic_centred(draw, 288, "ALL SEVEN CREW ACCOUNTED FOR", _semiotic_font("Medium", 22), tracking=2)
    _semiotic_centred(draw, 320, "LIFE SUPPORT NOMINAL  ·  SHIP AT REST", _semiotic_font("Medium", 22), tracking=2)
    _semiotic_centred(draw, _SEMIOTIC_FOOTER_RULE_Y + 12, "AUTOPILOT ENGAGED  ·  WAKE ON ARRIVAL",
                      _semiotic_font("SemiBold", 17), tracking=1)


def render_semiotic_sleep(time_str: str, width: int, height: int) -> Image.Image:
    """The quiet-hours frame: the Nostromo's crew in hypersleep.

    The same bulkhead, header, sign column and placard as the quote frame;
    only the blue and green lamps are lit. ``time_str`` is unused: nothing on
    the frame tells the time.
    """
    del time_str
    image = Image.new("RGB", (800, 480), color=SPECTRA6["black"])
    draw = ImageDraw.Draw(image)
    _semiotic_paint_hazard(image)
    _semiotic_paint_header_bar(image, draw, "STATUS", "STASIS", _SEMIOTIC_SLEEP_LAMPS)
    _semiotic_paint_sleep_signs(image, draw)
    _semiotic_paint_sleep_placard(draw)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("semiotic",), render=render_semiotic_frame, sleep=render_semiotic_sleep)
