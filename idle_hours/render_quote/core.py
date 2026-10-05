#!/usr/bin/env python3
"""``render`` and what calls it: the source card, the static message, the sleep
frame and the command line.

What stayed of the original 34,000-line module once issue #335 moved the
shared layers and every theme out. ``render`` dispatches a frame theme to its
renderer and lays every other theme out on the shared literary layout, painting
a border theme through its spec.
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from idle_hours import atomic_io
from idle_hours import pick_quote as pick_quote_module
from idle_hours.path_resolution import PHOTO_PATH_ENV

from . import clock
from ._paths import (
    META_FONT_BOLD_CANDIDATES,
    META_FONT_CANDIDATES,
)
from .fonts import _font_ascent, apply_theme_glyph_fallbacks, load_font, normalize_dashes, theme_font_candidates
from .furniture import (
    fallback_title,
)
from .layout import (
    LAYOUTS,
    SIDE_MARGIN,
    _bold_stroke_for_theme,
    _justify_distribution,
    _line_ink_width,
    _trim_line,
    choose_layout,
    fit_quote_balanced,
    justify_flags,
    strip_underscore_emphasis,
    wrap_text,
)
from .palette import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    SPECTRA6_PALETTE,
    snap_image_to_palette,
)
from .registry import _DEBUG_LABEL_RIGHT_INSET, BORDER_SPECS, FRAME_SPECS
from .text import (
    _draw_text_body,
    _paint_ornament_mark,
    draw_text,
)
from .theme_tables import _THEMES_RIGID_MATCH_SPACING, THEMES
from .themes.photo import _PHOTO_CACHE, _PHOTO_WARNED


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a literary clock quote for a given time.")
    parser.add_argument(
        "--time",
        default=None,
        type=pick_quote_module._cli_time,
        help="Time in HH:MM 24-hour format. Required unless --mode goodnight.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output PNG path. Defaults to output/current.png (overwritten on every "
            "run) so repeated ad-hoc invocations don't leak one file per HH:MM into "
            "output/. Pass an explicit path when you want a persistent per-time "
            "artifact. run_clock.py always passes --output explicitly, so the "
            "runtime loop is unaffected by this default."
        ),
    )
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument(
        "--mode",
        choices=["production", "debug", "card", "goodnight"],
        default="debug",
        help=(
            "Render mode. 'production' hides debug UI; 'debug' shows bucket/quality/time "
            "metadata; 'card' draws a centered source card (title/author/Gutenberg ID/"
            "matched phrase) instead of the full quote — used by the source-card button. "
            "'goodnight' draws the sleep frame in the active theme — used by "
            "--quiet-image=auto and --startup-image=auto. By default that is the "
            "bundled sleep quote rendered through the normal literary layout; pass "
            "--message to draw a bare centered headline instead."
        ),
    )
    parser.add_argument(
        "--message",
        default=None,
        help=(
            "Draw this headline for --mode goodnight instead of the bundled sleep "
            "quote. A headline has no attribution line and no accent-coloured "
            "phrase, so the default (omitting this flag) is what reproduces the "
            "'To sleep, perchance to dream.' frame in the active theme. "
            "Ignored outside --mode goodnight."
        ),
    )
    parser.add_argument(
        "--theme",
        choices=sorted(THEMES),
        default="default",
        help="Color theme to use when rendering.",
    )
    parser.add_argument(
        "--history-path",
        default=pick_quote_module.DEFAULT_HISTORY_PATH,
        help="Path to the anti-repeat display history JSONL. Pass an empty string to disable.",
    )
    parser.add_argument(
        "--history-days",
        type=int,
        default=pick_quote_module.DEFAULT_HISTORY_DAYS,
        help="Number of days of history to consider when filtering repeats. 0 disables.",
    )
    # Corpus / sidecar locations. run_clock forwards its resolved values so
    # the render subprocess reads exactly the files the curator UI writes
    # (under the systemd sandbox, the writable state dir). Defaults point a
    # bare ``render_quote.py --time HH:MM`` at the bundled assets.
    parser.add_argument(
        "--database",
        default=pick_quote_module.DEFAULT_DATABASE_PATH,
        help="Baked display-ready quote database (output of bake_quote_database.py).",
    )
    parser.add_argument(
        "--input",
        default=pick_quote_module.DEFAULT_INPUT_PATH,
        help="Raw attributed corpus, used as the fallback when --database is missing.",
    )
    parser.add_argument(
        "--overrides",
        default=pick_quote_module.DEFAULT_OVERRIDES_PATH,
        help="Selection-overrides sidecar (bans / boosts / preferred buckets).",
    )
    parser.add_argument(
        "--pin-quote",
        default=None,
        metavar="SOURCE_ID:LINE",
        help=(
            "Render this exact corpus row instead of picking one. Used by "
            "run_clock for theme-change repaints so the panel keeps showing "
            "the same quote the anti-repeat filter would otherwise exclude. "
            "Falls back to a normal pick when the row no longer exists; a "
            "malformed value is ignored with a warning."
        ),
    )
    parser.add_argument(
        "--pin-matched-text",
        default=None,
        metavar="TEXT",
        help=(
            "Disambiguator for --pin-quote. One source line can carry several "
            "time phrases, so SOURCE_ID:LINE is not a unique row key; passing "
            "the peeked matched_text alongside it pins the exact row the "
            "caller chose instead of whichever duplicate comes first on disk. "
            "A row that matches the key but not this text is skipped, and the "
            "render falls back to a normal pick."
        ),
    )
    parser.add_argument(
        "--photo-path",
        default=None,
        metavar="PATH",
        help=(
            "Image file or directory for the `photo` theme. Sets "
            f"{PHOTO_PATH_ENV} for this process. run_clock never passes this "
            "flag to the render subprocess — it exports the environment "
            "variable instead, so an operator's own --render-script cannot be "
            "broken by an unrecognised argument (see _corpus_render_args)."
        ),
    )
    args = parser.parse_args()
    if args.mode != "goodnight" and not args.time:
        parser.error("--time is required unless --mode goodnight")
    return args


def pick_quote(
    time_str: str,
    history_path: str | None = None,
    history_days: int = pick_quote_module.DEFAULT_HISTORY_DAYS,
    database_path: str | None = None,
    input_path: str | None = None,
    overrides_path: str | None = None,
    pin_key: tuple | None = None,
) -> dict:
    """Pick the quote to render.

    The three corpus/sidecar paths default to the bundled assets but are
    overridable so ``run_clock`` can point the render subprocess at the
    operator's writable copies — the ones the curator UI mutates. Threading
    ``overrides_path`` through is what makes a UI-issued ban reach the panel.
    """
    return pick_quote_module.select_quote(
        time_str=time_str,
        history_path=history_path,
        history_days=history_days,
        database_path=database_path or pick_quote_module.DEFAULT_DATABASE_PATH,
        input_path=input_path or pick_quote_module.DEFAULT_INPUT_PATH,
        overrides_path=overrides_path or pick_quote_module.DEFAULT_OVERRIDES_PATH,
        pin_key=pin_key,
    )


def parse_pin_quote(value: str | None, matched_text: str | None = None) -> tuple | None:
    """Parse a ``SOURCE_ID:LINE`` --pin-quote value; None/malformed → None.

    ``matched_text`` (from ``--pin-matched-text``) is appended as a third
    element when supplied. It is required for correctness whenever the pin has
    to survive a corpus with duplicate ``(source_id, line_number)`` keys — see
    the pin block in ``pick_quote.select_quote``.

    Fail-open: a malformed pin must degrade to a normal pick with a stderr
    warning, never kill the render subprocess mid-loop.
    """
    if not value:
        return None
    source_id, sep, line = value.partition(":")
    if sep and source_id:
        try:
            key = (source_id, int(line))
        except ValueError:
            pass
        else:
            return key if matched_text is None else (*key, matched_text)
    print(f"warning: ignoring malformed --pin-quote {value!r}", file=sys.stderr)
    return None


def _paint_theme_border(image: Image.Image, theme: str, colors: dict) -> None:
    """Paint ``theme``'s border, if it has one: the plain first pass.

    The seam ``render``, ``render_source_card`` and ``render_static_message``
    share. ``render`` follows it with the spec's knockout pass once the quote
    is laid out; see ``spec.BorderSpec``.
    """
    spec = BORDER_SPECS.get(theme)
    if spec is not None:
        spec.paint(image, colors)




def debug_quote_id(quote_row: dict) -> str | None:
    source_id = quote_row.get("source_id")
    source_path = quote_row.get("source_path") or ""
    line_number = quote_row.get("line_number")

    parts = []
    if source_id:
        parts.append(str(source_id))
    elif source_path:
        parts.append(Path(source_path).stem)

    if line_number is not None:
        parts.append(f"L{line_number}")

    if not parts and source_path:
        return Path(source_path).name
    return ":".join(parts) if parts else None


def render_source_card(quote_row: dict, width: int, height: int, theme: str = "default") -> Image.Image:
    """Render a centered metadata card for the current quote.

    Shown for a few seconds by the Inky button-C handler, then the loop
    repaints the frame. Reuses the theme palette and fonts.
    """
    colors = THEMES[theme]
    image = Image.new("RGB", (width, height), color=colors["page_bg"])
    _paint_theme_border(image, theme, colors)
    draw = ImageDraw.Draw(image)

    title_text = (quote_row.get("title") or fallback_title(quote_row) or "Unknown source").strip()
    author_text = (quote_row.get("author") or "").strip()
    source_id = quote_row.get("source_id")
    source_id_text = f"Project Gutenberg #{source_id}" if source_id else ""
    matched_text = (quote_row.get("matched_text") or "").strip()
    matched_text = normalize_dashes(strip_underscore_emphasis(matched_text))

    label_font = load_font(META_FONT_CANDIDATES, size=18)
    # ``card_quote_bold`` falls through to ``quote_bold`` unless a theme
    # overrides it: a seam for a theme whose bold face is ASCII-only to route
    # the card's title and phrase through a unicode-safe face.
    title_font = load_font(theme_font_candidates(theme, "card_quote_bold"), size=44)
    author_font = load_font(theme_font_candidates(theme, "quote_regular"), size=28)
    id_font = load_font(META_FONT_CANDIDATES, size=18)
    phrase_font = load_font(theme_font_candidates(theme, "card_quote_bold"), size=28)

    max_text_width = width - 2 * SIDE_MARGIN - 40
    title_lines = wrap_text(draw, title_text, title_font, max_text_width)[:3]
    author_lines = wrap_text(draw, f"by {author_text}", author_font, max_text_width)[:1] if author_text else []
    phrase_lines = wrap_text(draw, f"\u201c{matched_text}\u201d", phrase_font, max_text_width)[:2] if matched_text else []

    label_text = "Now showing"
    label_bbox = draw.textbbox((0, 0), label_text, font=label_font)
    label_h = label_bbox[3] - label_bbox[1]

    title_h = sum((draw.textbbox((0, 0), line, font=title_font)[3] - draw.textbbox((0, 0), line, font=title_font)[1]) + 6 for line in title_lines)
    author_h = sum((draw.textbbox((0, 0), line, font=author_font)[3] - draw.textbbox((0, 0), line, font=author_font)[1]) + 4 for line in author_lines)
    phrase_h = sum((draw.textbbox((0, 0), line, font=phrase_font)[3] - draw.textbbox((0, 0), line, font=phrase_font)[1]) + 4 for line in phrase_lines)
    id_bbox = draw.textbbox((0, 0), source_id_text, font=id_font) if source_id_text else (0, 0, 0, 0)
    id_h = (id_bbox[3] - id_bbox[1]) if source_id_text else 0

    block_h = label_h + 18 + title_h + (12 + author_h if author_lines else 0) + (24 + phrase_h if phrase_lines else 0) + (20 + id_h if source_id_text else 0)
    y = max(40, (height - block_h) // 2)

    def _draw_centered(text: str, font, fill):
        nonlocal y
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        _draw_text_body(image, draw, ((width - w) // 2, y), text, font=font, fill=fill, theme=theme)
        y += h

    _draw_centered(label_text, label_font, colors["accent"])
    y += 18
    for line in title_lines:
        _draw_centered(line, title_font, colors["text"])
        y += 6
    if author_lines:
        y += 6
        for line in author_lines:
            _draw_centered(line, author_font, colors["text"])
            y += 4
    if phrase_lines:
        y += 18
        for line in phrase_lines:
            _draw_centered(line, phrase_font, colors["accent"])
            y += 4
    if source_id_text:
        y += 14
        _draw_centered(source_id_text, id_font, colors["source"])

    return snap_image_to_palette(image, SPECTRA6_PALETTE)


def render_static_message(message: str, width: int, height: int, theme: str = "default") -> Image.Image:
    """Render a centered headline message in the active theme.

    The opt-in ``--mode goodnight --message TEXT`` path (the ``auto`` sleep
    and startup frames use :func:`render_sleep_frame`). Reuses the theme
    palette, border and fonts but never a custom frame, so a custom-frame
    theme contributes only its ``THEMES`` palette.
    """
    colors = THEMES[theme]
    image = Image.new("RGB", (width, height), color=colors["page_bg"])
    _paint_theme_border(image, theme, colors)
    draw = ImageDraw.Draw(image)

    max_text_width = width - 2 * SIDE_MARGIN - 40
    headline_candidates = theme_font_candidates(theme, "quote_bold")
    line_gap = 12
    for size in range(96, 35, -4):
        font = load_font(headline_candidates, size=size)
        lines = wrap_text(draw, message, font, max_text_width)
        line_heights = [
            draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1]
            for line in lines
        ]
        block_h = sum(line_heights) + max(0, len(lines) - 1) * line_gap
        if block_h <= height - 80:
            break

    y = max(40, (height - block_h) // 2)
    for line, h in zip(lines, line_heights):
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        _draw_text_body(image, draw, ((width - w) // 2, y), line, font=font, fill=colors["text"], theme=theme)
        y += h + line_gap

    return snap_image_to_palette(image, SPECTRA6_PALETTE)


# The quote the panel sleeps under, shaped as a corpus row so it goes through
# the entire literary layout — every border painter, custom frame and the
# accent-coloured matched phrase — in whichever theme is active.
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


def render_sleep_frame(
    time_str: str | None, width: int, height: int, theme: str = "default"
) -> Image.Image:
    """Render :data:`SLEEP_QUOTE_ROW` through the normal literary layout.

    The themed replacement for the static ``assets/goodnight.png``. Always
    ``mode="production"``.

    ``time_str`` is the moment quiet hours began, passed through because many
    themes surface the hour in their furniture (``tarot``'s numeral,
    ``lieder``'s time signature, ``abyssal``'s depth gauge …) and the entry
    time is the honest value there. ``None`` falls back to the wall clock so a
    bare ``render_quote.py --mode goodnight`` still renders.
    """
    if time_str is None:
        time_str = clock.now().strftime("%H:%M")
    # Hand out a copy: this module-level row is shared across every render
    # in a process (contact sheet, ``/api/preview``), so a painter that ever
    # mutated its row would corrupt later renders.
    return render(time_str, dict(SLEEP_QUOTE_ROW), width, height, mode="production", theme=theme)


def clear_photo_cache() -> None:
    """Drop the decoded-frame cache and the warning latch.

    Public because a test asserting on a warning must not be silenced by a
    previous one, the same contract ``pick_quote.clear_corpus_cache`` keeps.
    """
    _PHOTO_CACHE.clear()
    _PHOTO_WARNED.clear()




def render(time_str: str, quote_row: dict, width: int, height: int, mode: str = "debug", theme: str = "default") -> Image.Image:
    # Swap characters the theme's text faces cannot draw for ASCII stand-ins
    # before any layout or frame dispatch, so custom frames get it too.
    quote_row = apply_theme_glyph_fallbacks(quote_row, theme)
    if mode == "card":
        return render_source_card(quote_row, width, height, theme=theme)
    frame = FRAME_SPECS.get(theme)
    if frame is not None:
        return frame.render(time_str, quote_row, width, height)
    colors = THEMES[theme]
    image = Image.new("RGB", (width, height), color=colors["page_bg"])
    _paint_theme_border(image, theme, colors)
    draw = ImageDraw.Draw(image)

    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row["display_quote"]))
    layout_name = choose_layout(display_quote)
    layout = LAYOUTS[layout_name]

    debug_font = load_font(META_FONT_CANDIDATES, size=15)
    debug_label_font = load_font(META_FONT_BOLD_CANDIDATES, size=15)
    quote_font, quote_font_bold, wrapped_quote, line_height, chosen_size, wrap_width = fit_quote_balanced(
        draw,
        display_quote,
        quote_row.get("matched_text") or "",
        layout["max_width"],
        layout["quote_height"],
        layout["font_max"],
        layout["font_min"],
        layout["line_height_mult"],
        theme=theme,
    )
    bold_stroke = _bold_stroke_for_theme(theme)
    quote_block_height = len(wrapped_quote) * line_height
    # Floors of 18 / 16 px: the byline is read from across a room. Above the
    # floor it still scales with the body.
    author_size = max(18, int(chosen_size * 0.52))
    source_size = max(16, int(chosen_size * 0.47))
    attribution_font = load_font(theme_font_candidates(theme, "quote_regular"), size=author_size)
    attribution_title_font = load_font(theme_font_candidates(theme, "quote_regular"), size=source_size)

    author_text = quote_row.get("author") or None
    title_text = quote_row.get("title") or fallback_title(quote_row)
    author_lines = wrap_text(draw, author_text, attribution_font, width - 160)[:1] if author_text else []
    title_lines = wrap_text(draw, title_text, attribution_title_font, width - 200)[:2] if title_text else []

    attrib_height = 0
    if author_lines:
        attrib_height += author_size
    if title_lines:
        attrib_height += layout["author_gap"] + len(title_lines) * source_size
        if len(title_lines) > 1:
            attrib_height += (len(title_lines) - 1) * layout["title_gap"]

    total_h = quote_block_height + (layout["author_gap"] if (author_lines or title_lines) else 0) + attrib_height
    block_top = max(72, (height - total_h) // 2)
    block_bottom = block_top + total_h
    quote_top = block_top

    line_metrics = [
        (
            _line_ink_width(draw, line, quote_font, quote_font_bold, bold_stroke),
            sum(1 for chunk, _ in _trim_line(line) if chunk == " "),
        )
        for line in wrapped_quote
    ]
    justify = justify_flags(theme, line_metrics, wrap_width, chosen_size)

    quote_line_boxes = []
    quote_left_edge = width
    quote_right_edge = 0
    y_probe = quote_top
    for line_index, line in enumerate(wrapped_quote):
        start = 0
        while start < len(line) and line[start][0].strip() == "":
            start += 1
        end = len(line)
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        drawable = line[start:end]

        current_width = 0
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            # Match ``wrap_styled_text``: stroke only widens non-space
            # tokens; inter-word spaces stay at their natural advance so
            # the rendered line width here matches the wrap decision.
            stroke = bold_stroke if (is_bold and chunk.strip()) else 0
            bbox = draw.textbbox((0, 0), chunk, font=font, stroke_width=stroke)
            current_width += bbox[2] - bbox[0]

        space_slots = sum(1 for chunk, _ in drawable if chunk == " ")
        slack = wrap_width - current_width
        distribute = []
        if justify[line_index] and space_slots:
            base = slack // space_slots
            remainder = slack - base * space_slots
            distribute = [base + (1 if i < remainder else 0) for i in range(space_slots)]

        line_x = (width - layout["max_width"]) // 2
        line_left = None
        line_right = line_x
        space_idx = 0
        for chunk, is_bold in drawable:
            if line_left is None and chunk.strip():
                line_left = line_x
            font = quote_font_bold if is_bold else quote_font
            stroke = bold_stroke if (is_bold and chunk.strip()) else 0
            bbox = draw.textbbox((0, 0), chunk, font=font, stroke_width=stroke)
            line_x += bbox[2] - bbox[0]
            if chunk.strip():
                line_right = line_x
            if distribute and chunk == " ":
                line_x += distribute[space_idx]
                space_idx += 1
        if line_left is not None:
            quote_line_boxes.append((line_left, y_probe, line_right, y_probe + line_height))
            quote_left_edge = min(quote_left_edge, line_left)
            quote_right_edge = max(quote_right_edge, line_right)
        y_probe += line_height

    # The knockout rect must cover the attribution as well as the quote
    # lines, or a long title runs out of the cleared panel into the border
    # decoration (#328).
    attribution_left = (width - layout["max_width"]) // 2
    for line, font in [(author_line, attribution_font) for author_line in author_lines] + [
        (title_line, attribution_title_font) for title_line in title_lines
    ]:
        bbox = draw.textbbox((0, 0), line, font=font)
        quote_left_edge = min(quote_left_edge, attribution_left)
        quote_right_edge = max(quote_right_edge, attribution_left + bbox[2] - bbox[0])

    clear_rect = None
    border = BORDER_SPECS.get(theme)
    # The knockout rect: the quote and attribution block, grown by the
    # theme's ``clear_rect_pad`` so its framing decoration clears the text.
    if border is not None and border.clear_rect_pad is not None and quote_line_boxes:
        clear_pad_x, clear_pad_top, clear_pad_bottom = border.clear_rect_pad
        clear_top = max(0, quote_line_boxes[0][1] - clear_pad_top)
        clear_bottom = min(height - 1, block_bottom + clear_pad_bottom)
        clear_rect = (
            max(0, quote_left_edge - clear_pad_x),
            clear_top,
            min(width - 1, quote_right_edge + clear_pad_x),
            clear_bottom,
        )
        # Drop a degenerate rect (x1 < x0 or y1 < y0): on a small preview
        # canvas the layout can land partly off-screen and invert the box,
        # which would raise in the knockout / border painters. None means "no
        # body-region knockout", which every knockout painter accepts.
        if clear_rect[2] < clear_rect[0] or clear_rect[3] < clear_rect[1]:
            clear_rect = None

    # The knockout pass: every border theme is painted again now the quote is
    # laid out, with the knockout rect (and the time) when its spec asks.
    if border is not None:
        border.paint_knockout(image, colors, clear_rect, time_str)

    draw = ImageDraw.Draw(image)
    show_debug = mode == "debug"

    mark_size = min(layout["mark_max"], max(layout["mark_min"], int(chosen_size * layout["mark_scale"])))
    mark_font = load_font(theme_font_candidates(theme, "ornament"), size=mark_size)

    # The mark hangs at a fixed x with its lower two thirds level with the
    # first line, so on the standard and dense measures it runs under the
    # first word. Deliberate (a pull-quote mark behind the text): don't shrink
    # it to clear the gutter — small marks lose the gesture.
    open_bb = draw.textbbox((0, 0), "“", font=mark_font)
    open_h = open_bb[3] - open_bb[1]
    open_x = SIDE_MARGIN + 18
    open_y = quote_top - open_h // 3
    _paint_ornament_mark(
        image,
        (open_x - open_bb[0], open_y - open_bb[1]),
        "“",
        font=mark_font,
        theme=theme,
        colors=colors,
        pattern_offset=(0, 0),
    )

    y = quote_top
    for line_index, line in enumerate(wrapped_quote):
        start = 0
        while start < len(line) and line[start][0].strip() == "":
            start += 1
        end = len(line)
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        drawable = line[start:end]

        current_width = 0
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            # See the layout pass above: spaces stay at natural advance.
            stroke = bold_stroke if (is_bold and chunk.strip()) else 0
            bbox = draw.textbbox((0, 0), chunk, font=font, stroke_width=stroke)
            current_width += bbox[2] - bbox[0]

        # Themes in ``_THEMES_RIGID_MATCH_SPACING`` exclude the
        # bold-internal inter-word gaps from slack distribution so the
        # matched phrase keeps its face's natural rhythm on a justified
        # line. Default for every other theme: all inter-word spaces
        # are equally elastic.
        space_is_bold = [is_bold for chunk, is_bold in drawable if chunk == " "]
        rigid_match = theme in _THEMES_RIGID_MATCH_SPACING
        slack = wrap_width - current_width

        distribute: list[int] = []
        # Full justification only where it will not open rivers -- see
        # ``justify_flags`` for the block-level decision.
        if justify[line_index] and space_is_bold:
            distribute = _justify_distribution(space_is_bold, slack, rigid_match)

        x = (width - layout["max_width"]) // 2
        space_idx = 0
        # PIL's default anchor "la" puts ``y`` at the top of each font's
        # ascent band, not on a shared baseline. When the body and bold faces
        # come from different families (gothic: EB Garamond + UnifrakturMaguntia)
        # the phrase would float, so each chunk is shifted by
        # ``body_ascent - chunk_ascent``.
        body_ascent = _font_ascent(quote_font)
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            fill = colors["accent"] if is_bold else colors["text"]
            chunk_y = y + (body_ascent - _font_ascent(font))
            # See the layout pass above: spaces stay at natural advance.
            stroke = bold_stroke if (is_bold and chunk.strip()) else 0
            _draw_text_body(image, draw, (x, chunk_y), chunk, font=font, fill=fill, theme=theme)
            bbox = draw.textbbox((0, 0), chunk, font=font, stroke_width=stroke)
            x += bbox[2] - bbox[0]
            if distribute and chunk == " ":
                x += distribute[space_idx]
                space_idx += 1
        y += line_height

    close_bb = draw.textbbox((0, 0), "”", font=mark_font)
    close_w = close_bb[2] - close_bb[0]
    close_h = close_bb[3] - close_bb[1]
    close_x = width - SIDE_MARGIN - 18 - close_w
    close_y = block_bottom - close_h * 2 // 3
    _paint_ornament_mark(
        image,
        (close_x - close_bb[0], close_y - close_bb[1]),
        "”",
        font=mark_font,
        theme=theme,
        colors=colors,
        pattern_offset=(1, 0),
    )

    y = quote_top + quote_block_height + layout["author_gap"]
    if author_lines:
        author_text_line = author_lines[0]
        author_x = (width - layout["max_width"]) // 2
        _draw_text_body(image, draw, (author_x, y), author_text_line, font=attribution_font, fill=colors["text"], theme=theme)
        y += author_size + layout["title_gap"]

    for line in title_lines:
        title_x = (width - layout["max_width"]) // 2
        _draw_text_body(image, draw, (title_x, y), line, font=attribution_title_font, fill=colors["source"], theme=theme)
        y += source_size + layout["title_gap"]

    if show_debug:
        debug_label = "DEBUG MODE"
        label_bbox = draw.textbbox((0, 0), debug_label, font=debug_label_font)
        label_w = label_bbox[2] - label_bbox[0]
        # Themes that paint a decorative top-right corner element push the
        # debug label inward past the graphic so it isn't clipped. Keep in
        # sync with the border helpers (``draw_bauhaus_border`` /
        # ``draw_blueprint_border``) — inset is measured past the outer edge
        # of the corner graphic with a small breathing gap.
        label_right_inset = _DEBUG_LABEL_RIGHT_INSET.get(theme, SIDE_MARGIN)
        label_x = width - label_right_inset - label_w
        label_y = 14

        draw_text(draw, (label_x, label_y), debug_label, font=debug_label_font, fill=colors["accent"])

        bucket_value = quote_row.get("bucket") or ""
        resolved = quote_row.get("resolved_bucket") or bucket_value
        if quote_row.get("used_fallback") and resolved and bucket_value and resolved != bucket_value:
            bucket_piece = f"{bucket_value} → {resolved}"
        else:
            bucket_piece = resolved or bucket_value

        debug_parts = [time_str or "--:--"]
        if bucket_piece:
            debug_parts.append(bucket_piece)
        debug_parts.append(f"layout {layout_name}")
        if quote_row.get("quality_score") is not None:
            debug_parts.append(f"quality {quote_row['quality_score']}")
        quote_id = debug_quote_id(quote_row)
        if quote_id:
            debug_parts.append(f"id {quote_id}")
        debug_strip = " · ".join(debug_parts)

        strip_bbox = draw.textbbox((0, 0), debug_strip, font=debug_font)
        strip_w = strip_bbox[2] - strip_bbox[0]
        strip_h = strip_bbox[3] - strip_bbox[1]
        strip_y = height - 14 - strip_h
        strip_x = (width - strip_w) // 2

        rule_y = strip_y - 8
        rule_left = max(SIDE_MARGIN, (width - strip_w) // 2 - 24)
        rule_right = min(width - SIDE_MARGIN, (width + strip_w) // 2 + 24)
        for x in range(rule_left, rule_right, 5):
            draw.point((x, rule_y), fill=colors["faint"])

        _draw_text_body(image, draw, (strip_x, strip_y), debug_strip, font=debug_font, fill=colors["faint"], theme=theme)

    return snap_image_to_palette(image, SPECTRA6_PALETTE)


def main() -> int:
    args = parse_args()
    if args.photo_path:
        os.environ[PHOTO_PATH_ENV] = args.photo_path
    # Output is a runtime artifact: resolve relative paths against CWD, not
    # ``BASE_DIR``, which lives inside the installed package.
    output_path = Path(args.output) if args.output else Path("output/current.png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if args.mode == "goodnight":
        # --message is the opt-in override, not the default: a bare headline
        # cannot carry the attribution stack or the accent-coloured phrase the
        # sleep quote wants, so the unflagged path goes through the full
        # literary layout instead. ``args.time`` is optional in this mode, and
        # render_sleep_frame falls back to the wall clock when it is absent.
        if args.message is not None:
            image = render_static_message(args.message, args.width, args.height, theme=args.theme)
        else:
            image = render_sleep_frame(args.time, args.width, args.height, theme=args.theme)
    else:
        quote_row = pick_quote(
            args.time,
            history_path=args.history_path,
            history_days=args.history_days,
            database_path=args.database,
            input_path=args.input,
            overrides_path=args.overrides,
            pin_key=parse_pin_quote(args.pin_quote, args.pin_matched_text),
        )
        image = render(args.time, quote_row, args.width, args.height, mode=args.mode, theme=args.theme)
    try:
        # Encode to an in-memory buffer first so a mid-save exception can't leave
        # ``output/current.png`` truncated — display_inky.py loads that path every
        # tick, and a torn PNG there blocks the panel until the next bucket change.
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        atomic_io.atomic_write_bytes(output_path, buffer.getvalue())
    finally:
        image.close()
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
