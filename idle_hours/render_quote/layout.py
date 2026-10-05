"""Quote layout: layout choice, matched-phrase tokenising, wrapping, fitting, widow balancing and justification.
"""

from __future__ import annotations

import math
import re
from typing import TypedDict

from .fonts import load_font, theme_font_candidates
from .theme_tables import _BOLD_STROKE_BY_THEME, _THEMES_RAGGED_RIGHT

SIDE_MARGIN = 20


class Layout(TypedDict):
    """One entry of ``LAYOUTS``: the measure, size range and spacing for a quote length."""

    max_width: int
    quote_height: int
    font_max: int
    font_min: int
    line_height_mult: float
    mark_scale: float
    mark_min: int
    mark_max: int
    title_size: int
    author_gap: int
    title_gap: int


LAYOUTS: dict[str, Layout] = {
    "hero": {
        "max_width": 640,
        "quote_height": 248,
        "font_max": 66,
        "font_min": 32,
        "line_height_mult": 1.12,
        "mark_scale": 3.0,
        "mark_min": 76,
        "mark_max": 126,
        "title_size": 17,
        "author_gap": 16,
        "title_gap": 4,
    },
    "standard": {
        "max_width": 660,
        "quote_height": 258,
        "font_max": 58,
        "font_min": 28,
        "line_height_mult": 1.14,
        "mark_scale": 2.8,
        "mark_min": 72,
        "mark_max": 118,
        "title_size": 16,
        "author_gap": 14,
        "title_gap": 4,
    },
    "dense": {
        "max_width": 680,
        "quote_height": 276,
        "font_max": 48,
        "font_min": 24,
        "line_height_mult": 1.18,
        "mark_scale": 2.5,
        "mark_min": 64,
        "mark_max": 102,
        "title_size": 15,
        "author_gap": 12,
        "title_gap": 4,
    },
}


def strip_underscore_emphasis(text: str) -> str:
    """Drop Gutenberg's ``_emphasis_`` markers, paired or not (issue #308).

    Paired spans go first; then any single underscore at a word edge (an
    unpaired or mangled marker such as ``_It had run down…`` or
    ``[Stiffly_._]``). Runs of two or more are kept: ``Mr. ____`` is a
    suppressed name, and a dunder like ``__init__`` must not be read as
    ``_init_`` emphasis. A marker standing alone between two spaces takes one
    space with it so no double gap is left.
    """
    if not text or "_" not in text:
        return text or ""
    text = re.sub(r"(?<![A-Za-z0-9_])_([^_\n]+?)_(?![A-Za-z0-9_])", r"\1", text)
    # A lone marker as its own word: drop it and one adjacent space.
    text = re.sub(r"(?:(?<=\s)|^)_(?:[ \t]+|$)", "", text)
    # Only at a word edge, so an in-word ``var_name`` is left alone.
    return re.sub(r"(?<![A-Za-z0-9_])_(?!_)|(?<!_)_(?![A-Za-z0-9_])", "", text)


def choose_layout(text: str) -> str:
    length = len((text or "").strip())
    if length <= 90:
        return "hero"
    if length <= 170:
        return "standard"
    return "dense"


TIME_PHRASE_PREFIXES = [
    "five minutes past",
    "ten minutes past",
    "quarter past",
    "twenty minutes past",
    "twenty-five minutes past",
    "half past",
    "twenty-five minutes to",
    "twenty minutes to",
    "quarter to",
    "ten minutes to",
    "five minutes to",
]

# Pre-compiled longest-first so the first prefix that matches the candidate
# wins ("twenty-five minutes past" beats "minutes past" for the same row).
# Order is load-bearing — keep this list sorted by descending prefix length.
_TIME_PHRASE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        prefix,
        re.compile(
            rf"(?<![A-Za-z0-9])(?<![A-Za-z0-9]-){re.escape(prefix)}"
            rf"(?:[ ,]+[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)?(?![A-Za-z0-9])(?!-[A-Za-z0-9])",
            re.IGNORECASE,
        ),
    )
    for prefix in sorted(TIME_PHRASE_PREFIXES, key=len, reverse=True)
]


def _direct_match_pattern(normalized_match: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?<![A-Za-z0-9])(?<![A-Za-z0-9]-){re.escape(normalized_match)}(?![A-Za-z0-9])(?!-[A-Za-z0-9])",
        re.IGNORECASE,
    )


def resolve_display_match(text: str, match_text: str) -> str:
    normalized_match = " ".join((match_text or "").split()).strip()
    if not normalized_match:
        return ""

    direct = _direct_match_pattern(normalized_match).search(text)
    if direct:
        return direct.group(0)

    lower_match = normalized_match.lower()
    for prefix, pattern in _TIME_PHRASE_PATTERNS:
        if not lower_match.startswith(prefix):
            continue
        for m in pattern.finditer(text):
            candidate = m.group(0).strip(" ,.;:!?")
            if candidate.lower().startswith(lower_match):
                return candidate

    return normalized_match


def tokenize_quote(text: str, match_text: str) -> list[tuple[str, bool]]:
    normalized_match = resolve_display_match(text, match_text)
    if not normalized_match:
        return [(text, False)]
    match = _direct_match_pattern(normalized_match).search(text)
    if not match:
        return [(text, False)]

    idx = match.start()
    match_end = match.end()
    while match_end < len(text) and text[match_end] in '”"\'’.,;:!?':
        match_end += 1

    return [
        (text[:idx], False),
        (text[idx:match_end], True),
        (text[match_end:], False),
    ]


def wrap_styled_text(draw, segments, regular_font, bold_font, max_width, bold_stroke: int = 0):
    """Wrap a tokenised styled segment list into rendered lines.

    ``bold_stroke`` is the faux-bold stroke width applied to bold tokens
    (see ``_BOLD_STROKE_BY_THEME``); bold tokens are measured with it so the
    wrap matches what is painted. Spaces keep their natural advance.

    **A line may only break at whitespace.** ``tokenize_quote`` splits at the
    matched phrase, and that seam can fall mid-word (``"… (at a "`` /
    ``"quarter to seven"`` / ``") with …"``); breaking there would leave a
    dangling ``)`` or a stranded ``(``. Segments are therefore regrouped
    into *words* — non-space pieces glued across segment boundaries — and
    only whole words are placed. Each piece keeps its own style, so
    ``seven)`` still paints ``seven`` bold and ``)`` regular. A word wider
    than ``max_width`` gets a line of its own, intact.
    """
    # Memoised per font object: wrap_styled_text runs many times per render
    # with the same two fonts.
    space_widths: dict[int, int] = {}

    def space_width_for(font) -> int:
        font_id = id(font)
        width = space_widths.get(font_id)
        if width is None:
            bbox = draw.textbbox((0, 0), " ", font=font)
            width = bbox[2] - bbox[0]
            space_widths[font_id] = width
        return width

    # Pass 1: regroup the segments into a flat item stream. An item is either
    # a space token ``(" ", is_bold)`` or a word — a list of styled pieces
    # with no whitespace between them. ``open_word`` is True while the last
    # emitted piece was not followed by a space, so the next piece (even one
    # from a differently-styled segment) extends that word instead of
    # starting a new one.
    items: list = []
    open_word = False
    for text, is_bold in segments:
        parts = text.split(" ")
        for i, part in enumerate(parts):
            if part:
                if open_word:
                    items[-1].append((part, is_bold))
                else:
                    items.append([(part, is_bold)])
                open_word = True
            if i < len(parts) - 1:
                items.append((" ", is_bold))
                open_word = False

    # Pass 2: place whole words, breaking only at the space tokens.
    lines = []
    current: list = []
    current_width = 0
    for item in items:
        if isinstance(item, tuple):
            _, is_bold = item
            font = bold_font if is_bold else regular_font
            space_width = space_width_for(font)
            if current and current_width + space_width > max_width:
                lines.append(current)
                current = []
                current_width = 0
            else:
                current.append(item)
                current_width += space_width
            continue

        word_width = 0
        for piece, is_bold in item:
            font = bold_font if is_bold else regular_font
            stroke = bold_stroke if is_bold else 0
            bbox = draw.textbbox((0, 0), piece, font=font, stroke_width=stroke)
            word_width += bbox[2] - bbox[0]
        if current and current_width + word_width > max_width:
            lines.append(current)
            current = []
            current_width = 0
        current.extend(item)
        current_width += word_width

    if current:
        lines.append(current)
    return lines


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    current = []
    for word in words:
        trial = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def fit_quote(draw, text, match_text, max_width, max_height, font_max, font_min, line_height_mult, theme: str = "default"):
    segments = tokenize_quote(text, match_text)
    regular_candidates = theme_font_candidates(theme, "quote_regular")
    bold_candidates = theme_font_candidates(theme, "quote_bold")
    bold_stroke = _bold_stroke_for_theme(theme)
    for size in range(font_max, font_min - 1, -2):
        regular_font = load_font(regular_candidates, size=size)
        bold_font = load_font(bold_candidates, size=size)
        wrapped = wrap_styled_text(draw, segments, regular_font, bold_font, max_width, bold_stroke=bold_stroke)
        line_height = int(size * line_height_mult)
        total_height = len(wrapped) * line_height
        if total_height <= max_height:
            return regular_font, bold_font, wrapped, line_height, size
    regular_font = load_font(regular_candidates, size=font_min)
    bold_font = load_font(bold_candidates, size=font_min)
    wrapped = wrap_styled_text(draw, segments, regular_font, bold_font, max_width, bold_stroke=bold_stroke)
    return regular_font, bold_font, wrapped, int(font_min * line_height_mult), font_min


# A last line is a widow when it carries a single word or less than this
# fraction of the measure. ``fit_quote_balanced`` then re-wraps on a
# narrower measure (and, failing that, at slightly smaller sizes) without
# adding a line, so a word or two drop down to keep it company.
_WIDOW_MIN_FRACTION = 0.3
_BALANCE_MEASURES = (0.95, 0.90, 0.85, 0.80, 0.75, 0.70)


def _trim_line(line):
    """Drop the leading / trailing space tokens of a wrapped line."""
    start = 0
    while start < len(line) and line[start][0].strip() == "":
        start += 1
    end = len(line)
    while end > start and line[end - 1][0].strip() == "":
        end -= 1
    return line[start:end]


def _line_ink_width(draw, line, regular_font, bold_font, bold_stroke: int = 0) -> int:
    """Pixel width of a wrapped line at its natural spacing, bold tokens
    measured with the theme's faux-bold stroke (the way the renderer
    paints them) and spaces at their natural advance."""
    total = 0
    for chunk, is_bold in _trim_line(line):
        font = bold_font if is_bold else regular_font
        stroke = bold_stroke if (is_bold and chunk.strip()) else 0
        bbox = draw.textbbox((0, 0), chunk, font=font, stroke_width=stroke)
        total += bbox[2] - bbox[0]
    return total


def is_widow_line(draw, line, regular_font, bold_font, measure: int, bold_stroke: int = 0) -> bool:
    """True when ``line`` would strand a widow: one word, or less than
    ``_WIDOW_MIN_FRACTION`` of ``measure`` in ink."""
    trimmed = _trim_line(line)
    gaps = sum(1 for chunk, _ in trimmed if chunk == " ")
    if gaps == 0:
        return True
    return _line_ink_width(draw, trimmed, regular_font, bold_font, bold_stroke) < measure * _WIDOW_MIN_FRACTION


def _min_body_fill(draw, lines, regular_font, bold_font, bold_stroke: int, measure: int) -> float:
    """Fill ratio of the *shortest* non-last line against ``measure`` --
    the block's raggedness in one number (1.0 for a one-line block)."""
    if len(lines) < 2:
        return 1.0
    return min(_line_ink_width(draw, line, regular_font, bold_font, bold_stroke) for line in lines[:-1]) / measure


# ``fit_quote_balanced`` walks 2 px size steps below the largest fitting
# size, down to ``_BALANCE_MIN_SIZE_FRACTION`` of it (never below the
# layout's ``font_min``), before giving the widow up. It never accepts a
# re-wrap whose shortest body line is under ``_BALANCE_MIN_FILL`` of the
# measure (or shorter than the unbalanced wrap's shortest line, if that is
# already shorter): trading a one-word last line for a half-empty middle
# line is not a repair.
_BALANCE_MIN_SIZE_FRACTION = 0.8
_BALANCE_MIN_FILL = 0.55


def fit_quote_balanced(draw, text, match_text, max_width, max_height, font_max, font_min, line_height_mult, theme: str = "default"):
    """``fit_quote`` plus widow control for the literary layout.

    Returns ``(regular_font, bold_font, wrapped, line_height, size,
    wrap_width)``. When the fitted wrap's last line is a widow, the text is
    re-wrapped at the same size on narrower measures (``_BALANCE_MEASURES``)
    until the last line fills out without adding a line or opening a
    half-empty middle line (``_BALANCE_MIN_FILL``). Failing that, the search
    repeats at 2 px smaller sizes down to ``_BALANCE_MIN_SIZE_FRACTION``,
    accepting the first natural wrap with no widow or the first passing
    re-wrap; failing *that*, the original wrap is returned.

    ``wrap_width`` is the measure the lines were wrapped to; the caller must
    justify against it, not ``max_width``, or the slack distribution undoes
    the balancing. The left edge doesn't move, so a balanced block hangs a
    little short of the right margin.
    """
    regular_font, bold_font, wrapped, line_height, size = fit_quote(
        draw, text, match_text, max_width, max_height, font_max, font_min, line_height_mult, theme=theme
    )
    bold_stroke = _bold_stroke_for_theme(theme)
    if len(wrapped) < 2 or not is_widow_line(draw, wrapped[-1], regular_font, bold_font, max_width, bold_stroke):
        return regular_font, bold_font, wrapped, line_height, size, max_width

    segments = tokenize_quote(text, match_text)
    regular_candidates = theme_font_candidates(theme, "quote_regular")
    bold_candidates = theme_font_candidates(theme, "quote_bold")
    smallest = max(font_min, math.ceil(size * _BALANCE_MIN_SIZE_FRACTION))
    for step in range(0, (size - smallest) // 2 + 1):
        candidate_size = size - 2 * step
        if step == 0:
            regular, bold, base = regular_font, bold_font, wrapped
        else:
            regular = load_font(regular_candidates, size=candidate_size)
            bold = load_font(bold_candidates, size=candidate_size)
            base = wrap_styled_text(draw, segments, regular, bold, max_width, bold_stroke=bold_stroke)
        candidate_line_height = int(candidate_size * line_height_mult)
        if len(base) * candidate_line_height > max_height:
            continue
        fill_floor = min(_BALANCE_MIN_FILL, _min_body_fill(draw, base, regular, bold, bold_stroke, max_width))
        if step and not is_widow_line(draw, base[-1], regular, bold, max_width, bold_stroke):
            return regular, bold, base, candidate_line_height, candidate_size, max_width
        for factor in _BALANCE_MEASURES:
            candidate_width = int(max_width * factor)
            candidate = wrap_styled_text(draw, segments, regular, bold, candidate_width, bold_stroke=bold_stroke)
            if len(candidate) != len(base):
                break
            # Judge widow and fill against the candidate's own measure: the
            # eye compares the last line with the lines above it.
            if is_widow_line(draw, candidate[-1], regular, bold, candidate_width, bold_stroke):
                continue
            if _min_body_fill(draw, candidate, regular, bold, bold_stroke, candidate_width) < fill_floor:
                continue
            return regular, bold, candidate, candidate_line_height, candidate_size, candidate_width
    return regular_font, bold_font, wrapped, line_height, size, max_width


def line_width(draw, line, regular_font, bold_font):
    width = 0
    for chunk, is_bold in line:
        font = bold_font if is_bold else regular_font
        bbox = draw.textbbox((0, 0), chunk, font=font)
        width += bbox[2] - bbox[0]
    return width

# Full justification only when it will not open rivers: the line must be at
# least 75% full, carry at least ``_JUSTIFY_MIN_GAPS`` gaps, and stretch each
# gap by under ``_JUSTIFY_MAX_STRETCH_EM`` of the body size. The 75% rule
# alone bounds the slack but not how few gaps it lands on (a three-word hero
# line could take 75 px per gap).
_JUSTIFY_MIN_GAPS = 3
_JUSTIFY_MAX_STRETCH_EM = 0.45


def justify_flags(theme: str, metrics: list[tuple[int, int]], wrap_width: int, font_size: int) -> list[bool]:
    """Decide, per wrapped body line, whether it is fully justified.

    ``metrics`` holds ``(ink_width, gap_count)`` for every line in order;
    ``wrap_width`` is the measure the lines were wrapped to and
    ``font_size`` the body size in pixels. The last line is never
    justified, nor is any line in a ``_THEMES_RAGGED_RIGHT`` theme, nor a
    line less than 75% full (that line alone stays ragged). The remaining
    lines are decided **as a block**: if any one has fewer than
    ``_JUSTIFY_MIN_GAPS`` gaps or would stretch each gap past
    ``_JUSTIFY_MAX_STRETCH_EM`` of the body size, the whole block is ragged,
    since a half-justified paragraph reads as a mistake.
    """
    flags = [False] * len(metrics)
    if theme in _THEMES_RAGGED_RIGHT or len(metrics) < 2:
        return flags
    eligible: list[int] = []
    for index, (ink_width, gap_count) in enumerate(metrics[:-1]):
        slack = wrap_width - ink_width
        if not (0 < slack <= wrap_width * 0.25):
            continue
        if gap_count < _JUSTIFY_MIN_GAPS or slack / gap_count > font_size * _JUSTIFY_MAX_STRETCH_EM:
            return flags
        eligible.append(index)
    for index in eligible:
        flags[index] = True
    return flags


def _bold_stroke_for_theme(theme: str) -> int:
    """Return the per-theme matched-phrase faux-bold stroke width."""
    return _BOLD_STROKE_BY_THEME.get(theme, 0)


def _justify_distribution(space_is_bold: list[bool], slack: int, rigid_match: bool) -> list[int]:
    """Return the per-space slack contribution for a justified line.

    ``space_is_bold`` lists the line's inter-word spaces in visual order,
    each flagged if it sits inside the matched phrase; ``slack`` is the pixel
    width to redistribute. With ``rigid_match``, matched-phrase spaces get 0
    and the slack splits across the body gaps only; otherwise every space is
    equally elastic. The result is parallel to ``space_is_bold``.

    Returns an empty list when no space is elastic; the caller then falls
    through to ragged-right.
    """
    elastic_count = sum(1 for is_bold in space_is_bold if not (rigid_match and is_bold))
    if elastic_count == 0:
        return []
    base = slack // elastic_count
    remainder = slack - base * elastic_count
    distribute: list[int] = []
    elastic_seen = 0
    for is_bold in space_is_bold:
        if rigid_match and is_bold:
            distribute.append(0)
        else:
            distribute.append(base + (1 if elastic_seen < remainder else 0))
            elastic_seen += 1
    return distribute
