"""The ``astrarium`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import datetime
import math
import random

from PIL import Image, ImageDraw

from .. import clock
from .._paths import META_FONT_BOLD_CANDIDATES, META_FONT_CANDIDATES
from ..fonts import _font_ascent, load_font, normalize_dashes, theme_font_candidates
from ..furniture import fallback_title
from ..layout import fit_quote, strip_underscore_emphasis, wrap_text
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_4x4, pixel_access, snap_image_to_palette
from ..spec import FrameSpec
from ..text import draw_text_dithered
from ._shared import _astrarium_paint_cream_wash


def _astrarium_paint_ring_quadrant(
    image: Image.Image,
    cx: int,
    cy: int,
    r_outer: int,
    r_inner: int,
    angle_start_deg: float,
    angle_end_deg: float,
    dark: tuple[int, int, int],
    light: tuple[int, int, int],
    light_density: float,
) -> None:
    """Fill an annular pie-slice with a two-ink Bayer stipple.

    The dial's quadrants: R+Y tangerine top-right, R+G sepia bottom-right,
    G+B teal bottom-left, solid black top-left (with a constellation
    speckle painted separately). The density branches mirror
    ``draw_text_dithered`` so the ring reads as the same hue a body-text
    recipe would.
    """
    px = pixel_access(image)
    w, h = image.size
    r_outer_sq = r_outer * r_outer
    r_inner_sq = r_inner * r_inner
    a0 = math.radians(angle_start_deg)
    a1 = math.radians(angle_end_deg)
    threshold = round(light_density * 16)
    y0 = max(0, cy - r_outer - 1)
    y1 = min(h, cy + r_outer + 2)
    x0 = max(0, cx - r_outer - 1)
    x1 = min(w, cx + r_outer + 2)
    for y in range(y0, y1):
        dy = y - cy
        for x in range(x0, x1):
            dx = x - cx
            d_sq = dx * dx + dy * dy
            if d_sq < r_inner_sq or d_sq > r_outer_sq:
                continue
            # Clock-face angle: 0° up, increasing clockwise, normalised to
            # [0, 2π) so the span check works when the start crosses 0.
            angle = math.atan2(dx, -dy)  # -π..π, 0 at top
            if angle < 0:
                angle += 2 * math.pi
            if not (a0 <= angle < a1):
                continue
            if light_density <= 0.25:
                px[x, y] = light if (x % 2 == 0 and y % 2 == 0) else dark
            elif light_density >= 0.5:
                px[x, y] = dark if (x + y) % 2 == 0 else light
            else:
                px[x, y] = light if BAYER_4x4[y % 4][x % 4] < threshold else dark


def _astrarium_paint_constellation_field(
    image: Image.Image,
    cx: int,
    cy: int,
    r_outer: int,
    r_inner: int,
    angle_start_deg: float,
    angle_end_deg: float,
    seed: int,
) -> None:
    """Paint a sparse white star speckle inside an annular sector (the
    dial's black top-left quadrant). Seeded, so the speckle is stable
    across renders."""
    rng = random.Random(seed)
    px = pixel_access(image)
    w, h = image.size
    a0 = math.radians(angle_start_deg)
    a1 = math.radians(angle_end_deg)
    n_stars = 22
    for _ in range(n_stars):
        # Sample uniformly inside the annular sector by inverse CDF on r².
        r = math.sqrt(rng.uniform(r_inner * r_inner, r_outer * r_outer))
        angle = rng.uniform(a0, a1)
        # Convert back to screen-space cartesian (0° = up, clockwise).
        sx = cx + int(r * math.sin(angle))
        sy = cy - int(r * math.cos(angle))
        if 0 <= sx < w and 0 <= sy < h:
            px[sx, sy] = SPECTRA6["white"]
            # A 4-pointed micro-star for ~35% of them.
            if rng.random() < 0.35:
                for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nx, ny = sx + ox, sy + oy
                    if 0 <= nx < w and 0 <= ny < h:
                        px[nx, ny] = SPECTRA6["white"]


def _astrarium_paint_dial(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    time_str: str,
    now: datetime.datetime,
) -> None:
    """Paint the astronomical-clock dial centred at (cx, cy).

    Layered outside-in:
    1. Outer minute-tick ring (60 ticks, long every 5)
    2. Halftone quadrant ring (tangerine / sepia / teal / black with a
       constellation speckle)
    3. Minute numerals ("60" / "15" / "30" / "45")
    4. Inner rule
    5. Centre disc with the wall-clock date and weekday — the panel only
       repaints on a bucket change, so an HH:MM readout would be stale most
       of the time; the date isn't.
    """
    BLACK = SPECTRA6["black"]
    WHITE = SPECTRA6["white"]
    RED = SPECTRA6["red"]
    YELLOW = SPECTRA6["yellow"]
    BLUE = SPECTRA6["blue"]
    GREEN = SPECTRA6["green"]

    r_outer = 168
    r_ring_outer = 150
    r_ring_inner = 128
    r_inner_rule = 108

    # Layer 1: outer hairline circle + 60 minute ticks.
    draw.ellipse((cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer), outline=BLACK, width=1)
    for tick in range(60):
        angle = math.radians(tick * 6)
        is_major = tick % 5 == 0
        tick_len = 8 if is_major else 4
        x_inner = cx + int((r_outer - tick_len) * math.sin(angle))
        y_inner = cy - int((r_outer - tick_len) * math.cos(angle))
        x_outer = cx + int(r_outer * math.sin(angle))
        y_outer = cy - int(r_outer * math.cos(angle))
        draw.line((x_inner, y_inner, x_outer, y_outer), fill=BLACK, width=1 if is_major else 1)

    # Layer 2: four halftone ring quadrants (0° = up, clockwise, so 0–90°
    # is top-right).
    _astrarium_paint_ring_quadrant(
        image, cx, cy, r_ring_outer, r_ring_inner, 0, 90,
        dark=RED, light=YELLOW, light_density=0.375,  # tangerine TR
    )
    _astrarium_paint_ring_quadrant(
        image, cx, cy, r_ring_outer, r_ring_inner, 90, 180,
        dark=RED, light=GREEN, light_density=0.5,  # sepia/brown BR (R+G)
    )
    _astrarium_paint_ring_quadrant(
        image, cx, cy, r_ring_outer, r_ring_inner, 180, 270,
        dark=GREEN, light=BLUE, light_density=0.5,  # teal BL (G+B → cyan)
    )
    # TL solid black + constellation speckle on top.
    _astrarium_paint_ring_quadrant(
        image, cx, cy, r_ring_outer, r_ring_inner, 270, 360,
        dark=BLACK, light=BLACK, light_density=0.5,
    )
    _astrarium_paint_constellation_field(
        image, cx, cy, r_ring_outer - 2, r_ring_inner + 2, 270, 360, seed=2026
    )

    # Crisp up the ring edges the per-pixel painters leave slightly jagged.
    draw.ellipse((cx - r_ring_outer, cy - r_ring_outer, cx + r_ring_outer, cy + r_ring_outer), outline=BLACK, width=1)
    draw.ellipse((cx - r_ring_inner, cy - r_ring_inner, cx + r_ring_inner, cy + r_ring_inner), outline=BLACK, width=1)
    # Quadrant separator lines (faint).
    for deg in (0, 90, 180, 270):
        angle = math.radians(deg)
        x0 = cx + int(r_ring_inner * math.sin(angle))
        y0 = cy - int(r_ring_inner * math.cos(angle))
        x1 = cx + int(r_ring_outer * math.sin(angle))
        y1 = cy - int(r_ring_outer * math.cos(angle))
        draw.line((x0, y0, x1, y1), fill=BLACK, width=1)

    # Layer 3: minute numerals at the 60 / 15 / 30 / 45 positions.
    numeral_font = load_font(META_FONT_BOLD_CANDIDATES, size=11)
    for label, deg in (("60", 0), ("15", 90), ("30", 180), ("45", 270)):
        angle = math.radians(deg)
        r_label = r_outer - 18
        nx = cx + int(r_label * math.sin(angle))
        ny = cy - int(r_label * math.cos(angle))
        bbox = draw.textbbox((0, 0), label, font=numeral_font)
        w_lbl = bbox[2] - bbox[0]
        h_lbl = bbox[3] - bbox[1]
        # Erase a small disc so the ticks don't run through the digits.
        bg_pad = 3
        draw.ellipse(
            (nx - w_lbl // 2 - bg_pad, ny - h_lbl // 2 - bg_pad,
             nx + w_lbl // 2 + bg_pad, ny + h_lbl // 2 + bg_pad),
            fill=WHITE,
        )
        draw.text((nx - w_lbl // 2 - bbox[0], ny - h_lbl // 2 - bbox[1]), label, font=numeral_font, fill=BLACK)

    # Layer 4: inner rule.
    draw.ellipse((cx - r_inner_rule, cy - r_inner_rule, cx + r_inner_rule, cy + r_inner_rule), outline=BLACK, width=1)

    # Layer 5: centre disc, filled explicitly because the constellation
    # speckle can spill into the inner area.
    draw.ellipse((cx - r_inner_rule + 2, cy - r_inner_rule + 2, cx + r_inner_rule - 2, cy + r_inner_rule - 2), fill=WHITE)

    # Text is centred with anchor="mm" rather than bbox maths, because bbox
    # centring drifts vertically between dates with and without descenders.
    #
    # The disc shows the wall-clock date, not ``time_str`` (see the
    # docstring). ``now`` is captured once per frame and shared with the
    # header and datum strip, so a render straddling midnight can't disagree
    # with itself.
    date_text = now.strftime("%b %d")
    weekday_text = now.strftime("%A").upper()

    header_font = load_font(META_FONT_CANDIDATES, size=10)
    draw.text((cx, cy - 50), "TODAY", font=header_font, fill=BLACK, anchor="mm")

    # Big date (e.g. "May 19"), centred on the dial axis.
    date_font = load_font(theme_font_candidates("astrarium", "quote_bold"), size=54)
    draw.text((cx, cy), date_text, font=date_font, fill=BLACK, anchor="mm")

    # Day of week beneath the date, at cy+46 so the 54 pt date's descenders
    # ("Sep", "Aug") clear it.
    weekday_font = load_font(META_FONT_CANDIDATES, size=12)
    draw.text((cx, cy + 46), weekday_text, font=weekday_font, fill=BLACK, anchor="mm")
    del time_str  # kept for signature symmetry; the disc reads the shared ``now``

    # Tiny sun glyph below "TODAY", above the date: red sentinel, then the
    # bbox post-pass below flips Bayer ranks >= 6 (10/16) to yellow.
    sun_cx = cx
    sun_cy = cy - 38
    sun_r = 4
    draw.ellipse((sun_cx - sun_r, sun_cy - sun_r, sun_cx + sun_r, sun_cy + sun_r), fill=RED)
    for ang_deg in range(0, 360, 45):
        ang = math.radians(ang_deg)
        x0 = sun_cx + int((sun_r + 2) * math.sin(ang))
        y0 = sun_cy - int((sun_r + 2) * math.cos(ang))
        x1 = sun_cx + int((sun_r + 6) * math.sin(ang))
        y1 = sun_cy - int((sun_r + 6) * math.cos(ang))
        draw.line((x0, y0, x1, y1), fill=RED, width=1)
    # Post-pass the sun's bbox to tangerine.
    px = pixel_access(image)
    bb_x0 = sun_cx - sun_r - 8
    bb_y0 = sun_cy - sun_r - 8
    bb_x1 = sun_cx + sun_r + 8
    bb_y1 = sun_cy + sun_r + 8
    for y in range(max(0, bb_y0), min(image.height, bb_y1)):
        for x in range(max(0, bb_x0), min(image.width, bb_x1)):
            if px[x, y] == RED and BAYER_4x4[y % 4][x % 4] >= 6:
                px[x, y] = YELLOW


def _astrarium_paint_header(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    width: int,
    time_str: str,
    now: datetime.datetime,
) -> None:
    """Top-strip dashboard chrome — brand on the left, date stack on the
    right, dotted rule beneath. ``now`` is shared with the dial so the two
    dates can't disagree across midnight."""
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]

    brand_bold = load_font(META_FONT_BOLD_CANDIDATES, size=14)
    brand_regular = load_font(META_FONT_CANDIDATES, size=14)
    chrome_bold = load_font(META_FONT_BOLD_CANDIDATES, size=10)

    # Brand line: "IDLE HOURS // ASTRARIUM"
    x: float = 24
    y = 22
    draw.text((x, y), "IDLE HOURS", font=brand_bold, fill=BLACK)
    bbox = draw.textbbox((0, 0), "IDLE HOURS", font=brand_bold)
    x += bbox[2] - bbox[0] + 10
    draw.text((x, y), "//", font=brand_regular, fill=BLACK)
    bbox = draw.textbbox((0, 0), "//", font=brand_regular)
    x += bbox[2] - bbox[0] + 8
    draw.text((x, y), "ASTRARIUM", font=brand_bold, fill=RED)

    # Right-side date stack — bold SOL/year line on top, red day label
    # beneath. Anchored directly to the right margin.
    day_label = now.strftime("%a · %b %d").upper()
    sol = f"SOL {now.timetuple().tm_yday} · YR {now.year}"

    date_right = width - 24
    sol_bbox = draw.textbbox((0, 0), sol, font=chrome_bold)
    day_bbox = draw.textbbox((0, 0), day_label, font=chrome_bold)
    draw.text((date_right - (sol_bbox[2] - sol_bbox[0]) - sol_bbox[0], 16 - sol_bbox[1]), sol, font=chrome_bold, fill=BLACK)
    draw.text((date_right - (day_bbox[2] - day_bbox[0]) - day_bbox[0], 32 - day_bbox[1]), day_label, font=chrome_bold, fill=RED)

    # Hairline dashed rule under the header — dotted every 4px.
    rule_y = 50
    for x in range(24, width - 24, 4):
        draw.point((x, rule_y), fill=BLACK)
    del time_str  # kept for signature symmetry; the strip reads the shared ``now``


def _astrarium_paint_quote_panel(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    quote_row: dict,
    panel_left: int,
    panel_right: int,
    panel_top: int,
    panel_bottom: int,
) -> None:
    """Lay the quote, matched-phrase tangerine accent, and attribution
    into the right column."""
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    YELLOW = SPECTRA6["yellow"]

    panel_width = panel_right - panel_left
    max_text_width = panel_width - 16

    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    matched = quote_row.get("matched_text") or ""

    # Small four-pointed star ornament above the body, green post-passed
    # to G+B teal.
    star_cx = panel_left + panel_width // 2
    star_cy = panel_top + 18
    star_r = 12
    draw.line((star_cx - star_r, star_cy, star_cx + star_r, star_cy), fill=SPECTRA6["green"], width=1)
    draw.line((star_cx, star_cy - star_r, star_cx, star_cy + star_r), fill=SPECTRA6["green"], width=1)
    for s in range(-star_r // 2, star_r // 2 + 1):
        if -star_r // 2 <= s <= star_r // 2:
            draw.point((star_cx + s, star_cy + s), fill=SPECTRA6["green"])
            draw.point((star_cx + s, star_cy - s), fill=SPECTRA6["green"])
    draw.ellipse((star_cx - 2, star_cy - 2, star_cx + 2, star_cy + 2), fill=SPECTRA6["green"])
    px = pixel_access(image)
    for y in range(max(0, star_cy - star_r - 2), min(image.height, star_cy + star_r + 2)):
        for x in range(max(0, star_cx - star_r - 2), min(image.width, star_cx + star_r + 2)):
            if px[x, y] == SPECTRA6["green"] and (x + y) & 1:
                px[x, y] = SPECTRA6["blue"]

    # Body block: the panel is narrower than the standard layout, hence the
    # smaller font range. +36 / −38 reserve room for the star ornament
    # above and the closing mark + attribution below.
    body_top = panel_top + 36
    body_bottom = panel_bottom - 38
    body_height = body_bottom - body_top
    quote_font, quote_font_bold, wrapped_quote, line_height, chosen_size = fit_quote(
        draw,
        display_quote,
        matched,
        max_text_width,
        body_height,
        font_max=38,
        font_min=18,
        line_height_mult=1.14,
        theme="astrarium",
    )
    quote_block_height = len(wrapped_quote) * line_height

    # Vertically centre the wrapped quote inside its panel.
    block_top = body_top + max(0, (body_height - quote_block_height) // 2)
    y = block_top

    # Oversized opening quotation mark in tangerine, anchored above the
    # first body line near the left edge of the panel.
    mark_size = max(48, int(chosen_size * 1.6))
    mark_font = load_font(theme_font_candidates("astrarium", "ornament"), size=mark_size)
    open_mark = "“"
    open_bbox = draw.textbbox((0, 0), open_mark, font=mark_font)
    open_h = open_bbox[3] - open_bbox[1]
    open_x = panel_left + 4
    open_y = block_top - open_h // 4
    draw_text_dithered(
        image,
        (open_x - open_bbox[0], open_y - open_bbox[1]),
        open_mark,
        font=mark_font,
        dark=RED,
        light=YELLOW,
        light_density=0.375,
    )

    for line in wrapped_quote:
        # Trim leading/trailing whitespace tokens (as ``render`` does).
        start = 0
        while start < len(line) and line[start][0].strip() == "":
            start += 1
        end = len(line)
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        drawable = line[start:end]
        pen_x: float = panel_left + 8
        body_ascent = _font_ascent(quote_font)
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            chunk_y = y + (body_ascent - _font_ascent(font))
            if is_bold:
                # Tangerine matched phrase (R+Y 5/8:3/8, as ``deco``).
                draw_text_dithered(
                    image,
                    (pen_x, chunk_y),
                    chunk,
                    font=font,
                    dark=RED,
                    light=YELLOW,
                    light_density=0.375,
                )
            else:
                draw.text((pen_x, chunk_y), chunk, font=font, fill=BLACK)
            bbox = draw.textbbox((0, 0), chunk, font=font)
            pen_x += bbox[2] - bbox[0]
        y += line_height

    # Closing quotation mark, mirrored to the bottom-right of the panel.
    close_mark = "”"
    close_bbox = draw.textbbox((0, 0), close_mark, font=mark_font)
    close_w = close_bbox[2] - close_bbox[0]
    close_h = close_bbox[3] - close_bbox[1]
    close_x = panel_right - close_w - 4
    close_y = y - close_h // 3
    if close_y + close_h > panel_bottom:
        close_y = panel_bottom - close_h - 2
    draw_text_dithered(
        image,
        (close_x - close_bbox[0], close_y - close_bbox[1]),
        close_mark,
        font=mark_font,
        dark=RED,
        light=YELLOW,
        light_density=0.375,
        pattern_offset=(1, 0),
    )

    # Attribution in the dashboard's sans, not the body's Cormorant: its
    # hairline serifs break up after palette snapping at byline sizes.
    author = quote_row.get("author") or None
    title = quote_row.get("title") or fallback_title(quote_row)
    author_font = load_font(META_FONT_BOLD_CANDIDATES, size=13)
    title_font = load_font(META_FONT_CANDIDATES, size=12)
    attrib_y = max(y + 6, close_y + close_h - 18)
    attrib_y = min(attrib_y, panel_bottom - 32)
    if author:
        draw.text((panel_left + 8, attrib_y), author, font=author_font, fill=BLACK)
        attrib_y += 15
    if title:
        title_lines = wrap_text(draw, title, title_font, max_text_width)[:1]
        if title_lines:
            draw.text((panel_left + 8, attrib_y), title_lines[0], font=title_font, fill=BLACK)


def _astrarium_paint_datum_strip(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    time_str: str,
    now: datetime.datetime,
) -> None:
    """Paint the bottom datum strip: two cells (solar elevation, lunar
    phase) under the left-half dial, derived from the clock rather than
    pretending to be sensor readings. The right half, under the quote, is
    deliberately left open."""
    BLACK = SPECTRA6["black"]

    strip_top = height - 44
    strip_bottom = height - 8
    # Top dotted rule across the full inner width, separating the quote
    # panel from the strip even where the right half has no cells.
    inner_left = 24
    inner_right = width // 2
    for x in range(24, width - 24, 4):
        draw.point((x, strip_top), fill=BLACK)

    label_font = load_font(META_FONT_BOLD_CANDIDATES, size=9)
    value_font = load_font(META_FONT_BOLD_CANDIDATES, size=14)
    unit_font = load_font(META_FONT_CANDIDATES, size=9)

    try:
        hh, mm = time_str.split(":")
        hour24 = int(hh)
        minute = int(mm)
    except (ValueError, AttributeError):
        hour24, minute = 0, 0
    # Toy solar-elevation model (peaks at noon), not real astronomy — the
    # furniture only needs to vary with the time of day.
    minute_of_day = hour24 * 60 + minute
    solar_norm = math.sin(math.pi * minute_of_day / (24 * 60))
    solar_elevation = max(0.0, solar_norm) * 75.0

    # Lunar phase: day-of-year modulo 30, from the shared ``now``.
    doy = now.timetuple().tm_yday
    moon_phase_pct = (doy % 30) / 30.0 * 100

    panels: list[tuple[str, str, str, tuple[int, int, int]]] = [
        ("SOLAR ELEVATION", f"{solar_elevation:.1f}", "°", BLACK),
        ("LUNAR PHASE", f"{int(moon_phase_pct)}", "%", BLACK),
    ]

    inner_width = inner_right - inner_left
    panel_w = inner_width // len(panels)
    for i, (label, value, unit, value_color) in enumerate(panels):
        px0 = inner_left + i * panel_w
        # Vertical separator between panels.
        if i > 0:
            for y in range(strip_top + 4, strip_bottom, 2):
                draw.point((px0, y), fill=BLACK)
        # Label on top.
        lbl_y = strip_top + 4
        draw.text((px0 + 4, lbl_y), label, font=label_font, fill=BLACK)
        # Value + unit on a tight baseline to fit the 36 px band.
        val_bbox = draw.textbbox((0, 0), value, font=value_font)
        val_y = strip_top + 18
        draw.text((px0 + 4 - val_bbox[0], val_y - val_bbox[1]), value, font=value_font, fill=value_color)
        val_w = val_bbox[2] - val_bbox[0]
        unit_bbox = draw.textbbox((0, 0), unit, font=unit_font)
        draw.text(
            (px0 + 4 + val_w + 4 - unit_bbox[0], val_y + (val_bbox[3] - val_bbox[1]) - (unit_bbox[3] - unit_bbox[1]) - unit_bbox[1]),
            unit, font=unit_font, fill=BLACK,
        )

    # Closing vertical rule, in line with the dial/quote divider drawn in
    # render (``div_x = int(width * 0.5)``).
    for y in range(strip_top + 4, strip_bottom, 2):
        draw.point((inner_right, y), fill=BLACK)


def render_astrarium_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Render the astrarium-theme dashboard frame.

    Composition (designed at the canonical 800×480; other sizes use the
    same layout proportions so contact-sheet and curator-preview renders
    still produce a recognisable thumbnail):

      ┌────────────────────────────────────────────────────────────────┐
      │ IDLE HOURS // ASTRARIUM         SAT · MAY 19  | S6 │ 800×480   │
      │ ─────────────────────────────────────────────────────────────  │
      │                                                                │
      │         ╭──────────╮                  ★                        │
      │       60│   ┌──┐   │15                                          │
      │         │   │  │   │     “It was at  ten o'clock                │
      │         │   └──┘   │      today that the first                  │
      │       45│  May 19  │30    of all Time Machines                  │
      │         │ TUESDAY  │      began its career.                     │
      │         ╰──────────╯                                             │
      │                                                                │
      │ ─────────────────────────────────────────────────────────────  │
      │ SOLAR ELEVATION │ LUNAR PHASE │                                │
      │      53.2°      │     18%     │                                │
      └────────────────────────────────────────────────────────────────┘

    Fully on-palette: the ring quadrants are two-ink Bayer stipples
    (tangerine / sepia / teal) or solid black, so the closing
    ``snap_image_to_palette`` is a no-op on the painted regions.
    """
    image = Image.new("RGB", (width, height), color=SPECTRA6["white"])
    # Layer 0: cream wash background.
    _astrarium_paint_cream_wash(image)
    draw = ImageDraw.Draw(image)

    # Capture the wall clock once and share it across the header / dial /
    # datum strip, so a render straddling midnight can't show two dates
    # (which would persist until the next bucket change).
    now = clock.now()

    # Top-strip dashboard chrome.
    _astrarium_paint_header(image, draw, width, time_str, now)
    # Dial centred in the left half, positioned proportionally so
    # thumbnails still work. The 50 px reserve covers the datum strip.
    # strip (height − 44, plus a small breathing gap).
    dial_zone_w = int(width * 0.5)
    dial_cx = dial_zone_w // 2 + 8
    dial_cy = 64 + (height - 64 - 50) // 2
    _astrarium_paint_dial(image, draw, dial_cx, dial_cy, time_str, now)
    # Quote panel in the right half: 12 px right of the divider (plus the
    # panel's own 4–8 px padding), between the header rule (y=50) and the
    # datum strip (y=height−44).
    # two horizontal rules without crowding either of them.
    panel_left = int(width * 0.5) + 12
    panel_right = width - 24
    panel_top = 54
    panel_bottom = height - 46
    _astrarium_paint_quote_panel(image, draw, quote_row, panel_left, panel_right, panel_top, panel_bottom)
    # Dotted vertical divider between the dial and the quote panel.
    # (a faint dotted line, similar to the dashed header rule).
    div_x = int(width * 0.5)
    for y in range(64, height - 48, 4):
        draw.point((div_x, y), fill=SPECTRA6["black"])

    # Bottom datum strip.
    _astrarium_paint_datum_strip(image, draw, width, height, time_str, now)

    return snap_image_to_palette(image, SPECTRA6_PALETTE)


SPEC = FrameSpec(themes=("astrarium",), render=render_astrarium_frame)
