"""The ``culture`` theme's frame: a Mind's signal beside the Orbital it concerns,
after Iain M. Banks's Culture novels.

Design notes: docs/themes.md § culture
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from .._paths import (
    JURA_BOLD,
    JURA_SEMIBOLD,
    META_FONT_BOLD_CANDIDATES,
    META_FONT_CANDIDATES,
    SHARETECHMONO_REGULAR,
    SPACEMONO_REGULAR,
)
from ..fonts import load_font
from ..furniture import fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, pixel_access, snap_image_to_palette
from ..primitives import paint_neon_mask, wrap_quote_into_masks
from ..spec import FrameSpec
from ..text import fit_text_to_width
from ._culture_common import _culture_clock, _culture_face_ink, _culture_signal, _marain_code, _marain_draw_glyph


def _marain_glyph_count(rows) -> int:
    return sum(code is not None for row in rows for code in row)


def _marain_layout(text: str, max_cols: int) -> list[list[int | None]]:
    """Break ``text`` into rows of glyph codes, wrapping only at word gaps.

    Hyphens count as word gaps: the script has no hyphen glyph, so
    "five-and-twenty" would otherwise fuse into one thirteen-letter word
    that no row can hold. A word still longer than a row is cut to it —
    callers that must not lose glyphs check with ``_marain_glyph_count``.
    """
    words = [[_marain_code(c) for c in w if _marain_code(c) is not None]
             for w in text.replace("-", " ").split()]
    words = [w for w in words if w]
    rows: list[list[int | None]] = []
    row: list[int | None] = []
    for word in words:
        need = len(word) + (1 if row else 0)
        if row and len(row) + need > max_cols:
            rows.append(row)
            row = []
        if row:
            row.append(None)
        row.extend(word[:max_cols])
    if row:
        rows.append(row)
    return rows


# -- culture: the Mind signal ---------------------------------------------------
_CULTURE_TEXT_X = (34, 462)
_CULTURE_HEADER_Y = 28
_CULTURE_RULE_Y = 104
_CULTURE_QUOTE_RECT = (34, 120, 462, 396)
_CULTURE_FOOTER_Y = 424
_CULTURE_ORBITAL = (632, 168, 156)       # centre x, centre y, radius
_CULTURE_ORBITAL_K = 0.42                # minor/major axis = sin(view elevation)
_CULTURE_ORBITAL_TILT = -0.14            # screen rotation of the ring, radians
_CULTURE_ORBITAL_W = 24                  # band thickness on screen, px
# Ring angle of the plate at local noon: the middle of the far arc, so the
# visible inner face holds exactly the plates between 06:00 and 18:00.
_CULTURE_NOON = math.radians(-90)
_CULTURE_MARAIN_RECT = (494, 338, 780, 446)
_CULTURE_MARAIN_PITCH = 7
_CULTURE_MARAIN_MIN_PITCH = 3
_CULTURE_MARAIN_HEAD = 28               # label band above the glyphs, px
_CULTURE_STAR_SEED = 0xBA4C5
# Ships as (nose-left x, centreline y, length, half-girth): the GSV, then escorts.
_CULTURE_SHIPS = ((520, 34, 84, 4), (618, 52, 22, 2), (656, 30, 14, 1))
_CULTURE_STAR_COUNT = 260


def _culture_ground() -> frozenset:
    return frozenset({SPECTRA6["black"]})


def _culture_paint_stars(image: Image.Image) -> None:
    """A sparse seeded star field, kept off the text column."""
    rng = random.Random(_CULTURE_STAR_SEED)
    px = pixel_access(image)
    width, height = image.size
    white, yellow, blue = SPECTRA6["white"], SPECTRA6["yellow"], SPECTRA6["blue"]
    x0, _, x1, _ = _CULTURE_QUOTE_RECT
    for _ in range(_CULTURE_STAR_COUNT):
        x, y = rng.randrange(width), rng.randrange(height)
        roll = rng.random()
        if x0 - 6 <= x <= x1 + 6:
            continue
        px[x, y] = yellow if roll < 0.08 else blue if roll < 0.22 else white


def _culture_ring_uv(dx: float, dy: float) -> tuple[float, float]:
    c, s = math.cos(_CULTURE_ORBITAL_TILT), math.sin(_CULTURE_ORBITAL_TILT)
    return dx * c + dy * s, -dx * s + dy * c


def _culture_ring_xy(u: float, v: float) -> tuple[float, float]:
    c, s = math.cos(_CULTURE_ORBITAL_TILT), math.sin(_CULTURE_ORBITAL_TILT)
    cx, cy, _ = _CULTURE_ORBITAL
    return cx + u * c - v * s, cy + u * s + v * c


def _culture_ring_point(theta: float, across: float = 0.5) -> tuple[float, float]:
    """Screen position of ring angle ``theta`` at fraction ``across`` of the band."""
    _, _, radius = _CULTURE_ORBITAL
    u = radius * math.cos(theta)
    v = radius * _CULTURE_ORBITAL_K * math.sin(theta) - across * _CULTURE_ORBITAL_W
    return _culture_ring_xy(u, v)


def _culture_paint_orbital(image: Image.Image) -> None:
    """The Orbital, per pixel: far arc shows the inner face, near arc the hull.

    For a screen pixel the ring coordinates follow in closed form. With the
    ring's centreline an ellipse of half-height ``h = R k sin`` at ``u`` and the
    band stacked ``W`` px above it, a pixel is on the far arc when ``v`` lies in
    ``[-h - W, -h]`` and on the near arc when it lies in ``[h - W, h]``. The near
    arc is tested first, so where the two overlap at the ends of the ellipse the
    hull correctly passes in front of the face.
    """
    cx, cy, radius = _CULTURE_ORBITAL
    k, band = _CULTURE_ORBITAL_K, _CULTURE_ORBITAL_W
    px = pixel_access(image)
    width, height = image.size
    black, white, blue = SPECTRA6["black"], SPECTRA6["white"], SPECTRA6["blue"]
    pad = band + 6
    for y in range(max(0, int(cy - radius * 0.5 - pad)), min(height, int(cy + radius * 0.5 + pad))):
        row = BAYER_8x8[y % 8]
        for x in range(max(0, cx - radius - pad), min(width, cx + radius + pad)):
            u, v = _culture_ring_uv(x - cx, y - cy)
            if abs(u) >= radius:
                continue
            s = math.sqrt(1.0 - (u / radius) ** 2)
            h = radius * k * s
            rank = row[x % 8]
            if h - band <= v <= h:
                # Near arc: the hull, lit where it faces the sun.
                theta = math.atan2(s, u / radius)
                across = (h - v) / band
                lit = -math.cos(theta - _CULTURE_NOON)
                edge = across < 0.09 or across > 0.91
                if edge:
                    px[x, y] = white if lit > 0.05 else blue
                    continue
                seam = int(theta * radius / 9.0) != int((theta * radius + 1.0) / 9.0)
                if lit > 0 and not seam and rank < lit * 0.42 * 64:
                    px[x, y] = white
                else:
                    px[x, y] = black
                continue
            if -h - band <= v <= -h:
                # Far arc: the inner face, the habitable surface looking back.
                theta = math.atan2(-s, u / radius)
                across = (-h - v) / band
                day = math.cos(theta - _CULTURE_NOON)
                if across < 0.07 or across > 0.93:
                    # The rim walls: lit bright on the day side, faint at night.
                    px[x, y] = white if day > 0 else blue
                    continue
                px[x, y] = _culture_face_ink(rank, x, y, theta * radius, across, day)


def _culture_plate_theta(clock: float) -> float:
    """Ring angle of the plate whose local time is ``clock`` (fraction of a day)."""
    return _CULTURE_NOON + (clock - 0.5) * 2.0 * math.pi


def _culture_paint_marker(image: Image.Image, draw: ImageDraw.ImageDraw,
                          clock: float, plate: str) -> tuple[int, int]:
    """Mark the plate whose local time is now, with a leader out to its name.

    Returns the marker's screen position (used by the tests). The leader runs
    radially away from the ring's centre so it never crosses the band.
    """
    cx, cy, _ = _CULTURE_ORBITAL
    theta = _culture_plate_theta(clock)
    mx, my = _culture_ring_point(theta)
    dx, dy = mx - cx, my - cy
    norm = math.hypot(dx, dy) or 1.0
    ux, uy = dx / norm, dy / norm
    if mx + ux * 30 < _CULTURE_TEXT_X[1] + 10:
        # Near the left end the radial leader would point into the quote, so
        # it drops straight down instead and the label hangs below the ring.
        ux, uy = 0.0, 1.0
    ex, ey = mx + ux * 30, my + uy * 30
    yellow, black = SPECTRA6["yellow"], SPECTRA6["black"]
    draw.line([(mx, my), (ex, ey)], fill=yellow, width=1)
    draw.ellipse((mx - 5, my - 5, mx + 5, my + 5), outline=black, width=3)
    draw.ellipse((mx - 4, my - 4, mx + 4, my + 4), outline=yellow, width=2)
    font = load_font([SHARETECHMONO_REGULAR, SPACEMONO_REGULAR, *META_FONT_CANDIDATES], size=12)
    label = plate.upper()
    tw = draw.textlength(label, font=font)
    lx = ex - tw / 2 if ux == 0.0 else (ex + 4 if dx >= 0 else ex - 4 - tw)
    # Never into the signal column: near the ring's left end the leader points
    # at the quote, so the label is held at the column's edge instead.
    lx = max(_CULTURE_TEXT_X[1] + 12, min(image.size[0] - 8 - tw, lx))
    ly = ey if ux == 0.0 else ey - 7
    draw.rectangle((lx - 2, ly, lx + tw + 2, ly + 14), fill=black)
    draw.text((lx, ly), label, font=font, fill=yellow)
    return round(mx), round(my)


def _culture_paint_ships(image: Image.Image) -> None:
    """A GSV and two escorts crossing the dark above the Orbital.

    Pale tapered hulls inside a blue field bloom; one mask, so hull and field
    share one halo.
    """
    mask = Image.new("L", image.size, 0)
    md = ImageDraw.Draw(mask)
    for (x0, y0, length, girth) in _CULTURE_SHIPS:
        md.polygon([(x0, y0), (x0 + girth * 2, y0 - girth), (x0 + length - girth * 3, y0 - girth),
                    (x0 + length, y0), (x0 + length - girth * 3, y0 + girth), (x0 + girth * 2, y0 + girth)],
                   fill=255)
    paint_neon_mask(image, mask, SPECTRA6["white"], SPECTRA6["blue"],
                    radius=3, gamma=1.5, cap=0.55, ground=_culture_ground())
    mask.close()


def _culture_marain_fit(phrase: str) -> tuple[int, int, int, list[list[int | None]]]:
    """``(pitch, step, row_step, rows)`` for the largest glyphs that hold the
    whole phrase in the Marain block.

    Steps the grid pitch down rather than dropping rows: the last row of a
    long phrase is usually the hour itself. Spacing scales with the pitch.
    Only a phrase too long even at the floor pitch is cut; no committed corpus
    row is (``TestCultureFrame`` sweeps them).
    """
    x0, y0, x1, y1 = _CULTURE_MARAIN_RECT
    avail_h = y1 - (y0 + _CULTURE_MARAIN_HEAD)
    want = _marain_glyph_count(_marain_layout(phrase, len(phrase) + 1))
    for pitch in range(_CULTURE_MARAIN_PITCH, _CULTURE_MARAIN_MIN_PITCH - 1, -1):
        glyph = pitch * 2
        step = glyph + round(pitch * 10 / 7)
        row_step = glyph + round(pitch * 16 / 7)
        cols = max(1, (x1 - x0 - glyph) // step + 1)
        rows = _marain_layout(phrase, cols)
        if (len(rows) * row_step - (row_step - glyph) <= avail_h
                and _marain_glyph_count(rows) == want):
            return pitch, step, row_step, rows
    max_rows = max(1, (avail_h - glyph) // row_step + 1)
    return pitch, step, row_step, rows[:max_rows]


def _culture_paint_marain(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The matched phrase written out again, in Marain, under the Orbital."""
    x0, y0, x1, y1 = _CULTURE_MARAIN_RECT
    white, blue = SPECTRA6["white"], SPECTRA6["blue"]
    small = load_font([SHARETECHMONO_REGULAR, SPACEMONO_REGULAR, *META_FONT_CANDIDATES], size=12)
    label = "THE HOUR, IN MARAIN"
    draw.text((x0, y0), label, font=small, fill=white)
    draw.line([(x0 + draw.textlength(label, font=small) + 8, y0 + 8), (x1, y0 + 8)], fill=blue, width=1)
    phrase = (quote_row.get("matched_text") or "").strip()
    if not phrase:
        return
    pitch, step, row_step, rows = _culture_marain_fit(phrase)
    glyph = pitch * 2
    top = y0 + _CULTURE_MARAIN_HEAD
    mask = Image.new("L", image.size, 0)
    md = ImageDraw.Draw(mask)
    block_h = len(rows) * row_step - (row_step - glyph)
    top += max(0, (y1 - top - block_h) // 2)
    stroke, dot = (3, 2) if pitch >= 6 else (2, 2) if pitch >= 5 else (2, 1)
    for r, codes in enumerate(rows):
        width_px = (len(codes) - 1) * step + glyph
        x = x0 + max(0, (x1 - x0 - width_px) // 2)
        for code in codes:
            if code is not None:
                _marain_draw_glyph(md, x, top + r * row_step, code, pitch, 255, stroke=stroke, dot=dot)
            x += step
    paint_neon_mask(image, mask, white, blue, radius=3, gamma=1.5, cap=0.6,
                    ground=_culture_ground())
    mask.close()


def _culture_paint_signal(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The signal header, the quote as its body, and the relay line.

    Chrome text is white or yellow, never blue: small type in panel blue on
    black disappears. Blue is kept for rules and blooms.
    """
    white, yellow, green, blue, black = (SPECTRA6[n] for n in ("white", "yellow", "green", "blue", "black"))
    sig = _culture_signal(quote_row)
    x0, x1 = _CULTURE_TEXT_X
    mono = [SHARETECHMONO_REGULAR, SPACEMONO_REGULAR, *META_FONT_CANDIDATES]
    y = _CULTURE_HEADER_Y
    font, text = fit_text_to_width(
        draw, f"[{sig['channel']}, {sig['level']}, tra. @{sig['stamp']}]", mono, 15, x1 - x0, floor=11)
    draw.text((x0, y), text, font=font, fill=white)
    y += 24
    for prefix, name, ink in (("x", sig["from"], yellow), ("o", sig["to"], white)):
        font, text = fit_text_to_width(draw, prefix + name, mono, 19, x1 - x0, floor=12)
        draw.text((x0, y), text, font=font, fill=ink)
        y += 25
    draw.line([(x0, _CULTURE_RULE_Y), (x0 + 64, _CULTURE_RULE_Y)], fill=blue, width=2)

    prose, hot, _ = wrap_quote_into_masks(
        draw, image.size, quote_row, _CULTURE_QUOTE_RECT, theme="culture",
        font_max=34, font_min=14, line_height_mult=1.3, align="left",
    )
    image.paste(white, (0, 0), prose.point(lambda v: 255 if v > 128 else 0))
    # The drone's aura: a yellow core wrapped in a green field. Only ever lands
    # on black, so the prose beside it is never eaten.
    paint_neon_mask(image, hot, yellow, green, radius=3, gamma=1.7, cap=0.55,
                    ground=frozenset({black}), tile=BAYER_8x8)
    prose.close()
    hot.close()

    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or fallback_title(quote_row) or "").strip()
    credit = " · ".join(p for p in (author, title) if p)
    draw.line([(x0, _CULTURE_FOOTER_Y - 8), (x0 + 64, _CULTURE_FOOTER_Y - 8)], fill=blue, width=2)
    small = load_font(mono, size=12)
    if not credit:
        draw.text((x0, _CULTURE_FOOTER_Y), "[signal ends]", font=small, fill=white)
        return
    draw.text((x0, _CULTURE_FOOTER_Y), "RELAYED FROM THE ARCHIVE", font=small, fill=yellow)
    body = [JURA_SEMIBOLD, *META_FONT_BOLD_CANDIDATES]
    font, text = fit_text_to_width(draw, credit, body, 17, x1 - x0, floor=11)
    draw.text((x0, _CULTURE_FOOTER_Y + 16), text, font=font, fill=white)


def _culture_paint_chrome(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The Orbital's name, set under the ring."""
    sig = _culture_signal(quote_row)
    white, yellow = SPECTRA6["white"], SPECTRA6["yellow"]
    cx, cy, radius = _CULTURE_ORBITAL
    small = load_font([SHARETECHMONO_REGULAR, SPACEMONO_REGULAR, *META_FONT_CANDIDATES], size=12)
    name = load_font([JURA_BOLD, *META_FONT_BOLD_CANDIDATES], size=18)
    y = cy + int(radius * _CULTURE_ORBITAL_K) + 42
    draw.text((cx, y), f"{sig['orbital']} Orbital", font=name, fill=white, anchor="ma")
    draw.text((cx, y + 24), "ONE ROTATION PER DAY", font=small, fill=yellow, anchor="ma")


def render_culture_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A Mind's signal beside the Orbital it concerns (see the section comment)."""
    clock = _culture_clock(time_str)
    image = Image.new("RGB", (800, 480), color=SPECTRA6["black"])
    draw = ImageDraw.Draw(image)
    _culture_paint_stars(image)
    _culture_paint_ships(image)
    _culture_paint_orbital(image)
    _culture_paint_marker(image, draw, clock, _culture_signal(quote_row)["plate"])
    _culture_paint_chrome(draw, quote_row)
    _culture_paint_marain(image, draw, quote_row)
    _culture_paint_signal(image, draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("culture",), render=render_culture_frame)
