"""Shared frame furniture: time carriers, quote seeds, quote placement, mount cards and bylines.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .fonts import _font_ascent, normalize_dashes
from .layout import fit_quote, strip_underscore_emphasis
from .palette import SPECTRA6, BAYER_4x4, pixel_access


def _place_quote(draw: ImageDraw.ImageDraw, quote_row: dict, rect, *, theme: str,
                 font_max: int, font_min: int, line_height_mult: float) -> list:
    """Fit the quote into ``rect`` and position every styled chunk, ragged right.

    Returns ``(x, y, chunk, font, is_bold, width, line_height)`` per chunk, with
    ``y`` already baseline-aligned across the regular and bold faces, so a theme
    can draw the text, box the matched phrase, or mark each line from the same
    list. The fitting is ``fit_quote``'s; only the sizing is the theme's.
    """
    x0, y0, x1, y1 = rect
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    regular, bold, wrapped, line_height, _ = fit_quote(
        draw, display_quote, quote_row.get("matched_text") or "",
        x1 - x0, y1 - y0, font_max=font_max, font_min=font_min, line_height_mult=line_height_mult, theme=theme,
    )
    placed = []
    y = y0
    ascent = _font_ascent(regular)
    for line in wrapped:
        x = x0
        for chunk, is_bold in line:
            font = bold if is_bold else regular
            w = int(round(draw.textlength(chunk, font=font)))
            placed.append((x, y + (ascent - _font_ascent(font)), chunk, font, is_bold, w, line_height))
            x += w
        y += line_height
    return placed


def _paint_placed(draw: ImageDraw.ImageDraw, placed, ink, accent) -> None:
    """Draw ``_place_quote`` chunks in solid ``ink``, the matched phrase in ``accent``."""
    for x, y, chunk, font, is_bold, *_ in placed:
        draw.text((x, y), chunk, font=font, fill=accent if is_bold else ink)


# The quote the panel sleeps under, shaped as a corpus row so it goes through
# the entire literary layout — every border painter, custom frame and the
# accent-coloured matched phrase — in whichever theme is active. It lives
# here, below the theme modules, so a theme's own sleep frame can quote it
# too; ``core`` binds the same object for ``render_sleep_frame``.
#
# ``matched_text`` need not be a time phrase: ``resolve_display_match`` tries
# a literal search first, so "sleep" is bolded in the accent like a real hour.
# In ``dark`` this reproduces the bundled ``assets/goodnight.png``.
#
# Deliberately no ``source_id`` / ``line_number``: this row never enters the
# picker or the anti-repeat ledger and must not be confusable with a corpus
# row by anything keyed on that pair.
SLEEP_QUOTE_ROW: dict[str, str] = {
    "display_quote": "To sleep, perchance to dream.",
    "matched_text": "sleep",
    "author": "William Shakespeare",
    "title": "Hamlet",
}


def fallback_title(quote_row: dict) -> str | None:
    source_id = quote_row.get("source_id")
    if source_id:
        return f"Project Gutenberg #{source_id}"
    source_path = quote_row.get("source_path")
    if source_path:
        return Path(source_path).stem
    return None


# ---------------------------------------------------------------------------
# Shared painter helpers
#
# Small primitives that several themes reached for independently and that
# had been copy-pasted under theme-prefixed names (issue #336). One body
# each, so a fix lands everywhere and a new theme finds them by name. The
# time carriers and quote seeds live here; the painting half of that set
# (noise fields, Bayer thresholds, colour stops, halos, soft masks,
# silhouettes, splines) lives in ``primitives``, and ``_PANEL_INKS`` /
# ``_dither_calibrated`` in ``palette``.
# ---------------------------------------------------------------------------


def _clock_hour12(time_str) -> int:
    """The 12-hour clock hour, 1..12, parsed defensively from ``HH:MM``.

    Hour-only time surfaces (a numeral, a camera, a moon phase, a bearing)
    all want the same thing: 00:10 and 12:10 are 12, 13:00 is 1. Preview and
    source-card renders can reach a painter with an odd string or ``None``,
    so a bad parse falls back to 12 rather than raising.
    """
    try:
        hour = int(str(time_str).split(":", 1)[0])
    except ValueError:
        return 12
    return hour % 12 or 12


def _clock_hh_mm(time_str) -> tuple[int, int]:
    """``(hour 0..23, minute 0..59)`` parsed defensively from ``HH:MM``.

    For a painter that needs the minute too (a page number, a tonearm, a line
    diagram). The CLI validates ``--time``, but ``render`` is also called
    in-process, so a malformed or out-of-range time falls back to midnight
    rather than raising: the same 12 o'clock that :func:`_clock_hour12` gives.
    """
    try:
        hour, minute = (int(part) for part in str(time_str).split(":"))
    except ValueError:
        return 0, 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return 0, 0
    return hour, minute


def _row_digest(quote_row: dict) -> int:
    """Stable 32-bit FNV-1a digest of a corpus row's identity.

    The single seam for "seed something from the quote". Never use ``hash()``:
    it is PYTHONHASHSEED-salted, so seeds would differ between processes and
    break the golden fixtures and run_clock's unchanged-quote dedup.

    Walks the UTF-8 bytes (the FNV-1a definition), not ``ord()`` code points.
    """
    basis = f"{quote_row.get('source_id')}:{quote_row.get('line_number')}:{quote_row.get('display_quote')}"
    digest = 0x811C9DC5
    for byte in basis.encode("utf-8", "replace"):
        digest = ((digest ^ byte) * 0x01000193) & 0xFFFFFFFF
    return digest


# ---------------------------------------------------------------------------
# Shared mount furniture for the photographic frames.
#
# ``daguerreotype``, ``autochrome`` and ``photo`` present a plate with the
# quote on a cream card beside it; the card stock, the centred styled-line
# loop and the truncating byline live here. ``pulp``, ``vhs`` and
# ``wrap_quote_into_masks`` keep near copies of the line loop (anchoring,
# mask vs canvas and phrase colouring differ); folding them in would churn
# golden fixtures for no behaviour change.


def paint_mount_card(image: Image.Image, draw: ImageDraw.ImageDraw,
                     rect: tuple[int, int, int, int], ledge: int, *,
                     outline_width: int = 1) -> None:
    """Cream card stock on a drop-shadow ledge, keylined in black.

    The Y+W cream at the aged-paper themes' 12.5% density, over a black
    ledge: without it a light card on a light plate reads as a hole cut in
    the picture. ``outline_width`` defaults to a 1 px keyline; ``photo`` asks
    for 2, since an operator's photograph may be pale right up to the card.
    """
    x0, y0, x1, y1 = rect
    black, white, yellow = SPECTRA6["black"], SPECTRA6["white"], SPECTRA6["yellow"]
    draw.rectangle((x0 + ledge, y0 + ledge, x1 + ledge, y1 + ledge), fill=black)
    draw.rectangle((x0, y0, x1, y1), fill=white)
    px = pixel_access(image)
    for y in range(y0, y1 + 1):
        row = BAYER_4x4[y % 4]
        for x in range(x0, x1 + 1):
            if row[x % 4] < 2:
                px[x, y] = yellow
    draw.rectangle((x0, y0, x1, y1), outline=black, width=outline_width)


def draw_centred_styled_lines(draw: ImageDraw.ImageDraw, wrapped, *, x0: int, x1: int,
                              top: int, line_height: int, regular, bold,
                              fill, accent, min_inset: int = 18) -> int:
    """Draw ``fit_quote``'s wrapped output centred in ``x0..x1``, returning the
    y after the last line.

    Leading and trailing whitespace chunks are trimmed off each line before it
    is measured, or a wrapped line's trailing space shifts the centring; and
    every chunk is aligned on the body font's ascent, so a size difference
    between the regular and bold faces cannot make the matched phrase float.
    """
    body_ascent = _font_ascent(regular)
    y = top
    for line in wrapped:
        start, end = 0, len(line)
        while start < end and line[start][0].strip() == "":
            start += 1
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        segment = line[start:end]
        width_px = sum(draw.textbbox((0, 0), c, font=bold if b else regular)[2]
                       for c, b in segment)
        x = x0 + max(min_inset, ((x1 - x0) - width_px) // 2)
        for chunk, is_bold in segment:
            font = bold if is_bold else regular
            draw.text((x, y + (body_ascent - _font_ascent(font))), chunk,
                      font=font, fill=accent if is_bold else fill)
            x += draw.textbbox((0, 0), chunk, font=font)[2]
        y += line_height
    return y


def _fit_from_title(draw: ImageDraw.ImageDraw, quote_row: dict, font, max_w: int) -> str | None:
    """``— from {Title} —`` shortened to ``max_w`` with a trailing ellipsis.

    ``None`` when the row has no title, or no room for even a stub of one —
    the caller drops the footer. The loop guards on ``title``, the string that
    shrinks, not on the text: that is rebuilt from a template and never
    empties, so guarding on it spins forever when even ``— from … —``
    overflows, hanging the render path.
    """
    title = (quote_row.get("title") or "").strip()
    if not title:
        return None
    text = f"— from {title} —"
    while title and draw.textlength(text, font=font) > max_w:
        title = title[:-1]
        text = f"— from {title.rstrip()}… —"
    return text if title else None


def _fit_dotted_byline(draw: ImageDraw.ImageDraw, quote_row: dict, font, max_w: int):
    """``author · title`` shortened to ``max_w``, title side first.

    Returns ``(text, bbox)`` for the caller to align, or ``None`` when the row
    has neither author nor title. The tail part loses three characters to an
    ellipsis per step until it is six characters or fewer, then is dropped.
    """
    author = quote_row.get("author") or ""
    title = quote_row.get("title") or fallback_title(quote_row)
    parts = [p for p in (author, title) if p]
    if not parts:
        return None
    text = " · ".join(parts)
    bbox = draw.textbbox((0, 0), text, font=font)
    while parts and bbox[2] - bbox[0] > max_w:
        if len(parts[-1]) > 6:
            parts[-1] = parts[-1][:-3] + "…"
        else:
            parts.pop()
        text = " · ".join(parts)
        bbox = draw.textbbox((0, 0), text, font=font)
    return text, bbox


def draw_truncated_centred_byline(draw: ImageDraw.ImageDraw, quote_row: dict, *,
                                  centre: int, baseline: int, max_width: int,
                                  font, fill) -> None:
    """Author and title centred on a baseline, ellipsised to fit.

    ``max_width`` is the panel the byline actually sits in, passed in rather
    than hardcoded.
    """
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or fallback_title(quote_row) or "").strip()
    parts = " — ".join(p for p in (author, title) if p)
    if not parts:
        return
    while draw.textlength(parts, font=font) > max_width and len(parts) > 8:
        parts = parts[:-2].rstrip(" ,.;:") + "…"
    draw.text((centre, baseline), parts, font=font, fill=fill, anchor="ms")
