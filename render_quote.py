#!/usr/bin/env python3
"""Render a picked literary clock quote to an image with a more editorial layout."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent

DEFAULT_WIDTH = 800
DEFAULT_HEIGHT = 480
PAGE_BG = (250, 247, 238)
TEXT = (28, 28, 32)
SUBTLE = (78, 84, 96)
FAINT = (145, 134, 118)
ACCENT = (167, 54, 43)
ORNAMENT = (94, 109, 122)
TOP_MARGIN = 26
SIDE_MARGIN = 58
QUOTE_COLUMN_WIDTH = 520

QUOTE_FONT_REGULAR_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
]
QUOTE_FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
]
META_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a literary clock quote for a given time.")
    parser.add_argument("--time", required=True, help="Time in HH:MM 24-hour format")
    parser.add_argument("--picker", default="pick_quote.py", help="Path to quote picker script")
    parser.add_argument("--output", default=None, help="Output PNG path. Defaults to output/render-HHMM.png")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument(
        "--mode",
        choices=["production", "debug"],
        default="debug",
        help="Render mode. Production hides debug UI, debug shows bucket/quality/time metadata.",
    )
    return parser.parse_args()


def pick_quote(time_str: str, picker_path: str) -> dict:
    picker = str((BASE_DIR / picker_path).resolve()) if not Path(picker_path).is_absolute() else picker_path
    output = subprocess.check_output(["python3", picker, "--time", time_str], text=True)
    return json.loads(output)


def load_font(candidates: list[str], size: int):
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def tokenize_quote(text: str, match_text: str) -> list[tuple[str, bool]]:
    normalized_match = " ".join((match_text or "").split()).strip()
    if not normalized_match:
        return [(text, False)]
    lowered_text = text.lower()
    lowered_match = normalized_match.lower()
    idx = lowered_text.find(lowered_match)
    if idx == -1:
        return [(text, False)]
    return [
        (text[:idx], False),
        (text[idx:idx + len(normalized_match)], True),
        (text[idx + len(normalized_match):], False),
    ]


def wrap_styled_text(draw, segments, regular_font, bold_font, max_width):
    tokens = []
    for text, is_bold in segments:
        parts = text.split(' ')
        for i, part in enumerate(parts):
            if part:
                tokens.append((part, is_bold))
            if i < len(parts) - 1:
                tokens.append((' ', is_bold))

    lines = []
    current = []
    current_width = 0
    for token, is_bold in tokens:
        font = bold_font if is_bold else regular_font
        token_width = draw.textbbox((0, 0), token, font=font)[2]
        if current and current_width + token_width > max_width and token != ' ':
            lines.append(current)
            current = []
            current_width = 0
            if token == ' ':
                continue
        current.append((token, is_bold))
        current_width += token_width
    if current:
        lines.append(current)
    return lines


def wrap_text(draw, text, font, max_width):
    words = text.split()
    lines = []
    current = []
    for word in words:
        trial = " ".join(current + [word])
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def fit_quote(draw, text, match_text, max_width, max_height):
    segments = tokenize_quote(text, match_text)
    for size in range(38, 21, -2):
        regular_font = load_font(QUOTE_FONT_REGULAR_CANDIDATES, size=size)
        bold_font = load_font(QUOTE_FONT_BOLD_CANDIDATES, size=size)
        wrapped = wrap_styled_text(draw, segments, regular_font, bold_font, max_width)
        line_height = int(size * 1.42)
        total_height = len(wrapped) * line_height
        if total_height <= max_height:
            return regular_font, bold_font, wrapped, line_height
    regular_font = load_font(QUOTE_FONT_REGULAR_CANDIDATES, size=22)
    bold_font = load_font(QUOTE_FONT_BOLD_CANDIDATES, size=22)
    wrapped = wrap_styled_text(draw, segments, regular_font, bold_font, max_width)
    return regular_font, bold_font, wrapped, int(22 * 1.42)


def render(time_str: str, quote_row: dict, width: int, height: int, mode: str = "debug") -> Image.Image:
    image = Image.new("RGB", (width, height), color=PAGE_BG)
    draw = ImageDraw.Draw(image)

    time_font = load_font(META_FONT_CANDIDATES, size=20)
    debug_font = load_font(META_FONT_CANDIDATES, size=15)
    attribution_font = load_font(META_FONT_CANDIDATES, size=18)
    attribution_title_font = load_font(META_FONT_CANDIDATES, size=16)
    ornament_font = load_font(QUOTE_FONT_REGULAR_CANDIDATES, size=72)

    column_x = (width - QUOTE_COLUMN_WIDTH) // 2
    quote_max_height = 250

    quote_font, quote_font_bold, wrapped_quote, line_height = fit_quote(
        draw,
        quote_row['display_quote'],
        quote_row.get('matched_text') or '',
        QUOTE_COLUMN_WIDTH,
        quote_max_height,
    )
    quote_block_height = len(wrapped_quote) * line_height

    author_text = quote_row.get('author') or quote_row.get('source_id') or None
    title_text = quote_row.get('title') or quote_row.get('source_path') or None
    author_lines = wrap_text(draw, author_text, attribution_font, QUOTE_COLUMN_WIDTH)[:1] if author_text else []
    title_lines = wrap_text(draw, title_text, attribution_title_font, QUOTE_COLUMN_WIDTH - 18)[:2] if title_text else []
    attrib_height = 0
    if author_lines:
        attrib_height += 24
    if title_lines:
        attrib_height += len(title_lines) * 20

    block_height = quote_block_height + 28 + attrib_height
    quote_top = max(96, (height - block_height) // 2)

    show_debug = mode == "debug"
    if show_debug:
        draw.text((SIDE_MARGIN, TOP_MARGIN), time_str, font=time_font, fill=SUBTLE)
        subtitle = f"bucket {quote_row['resolved_bucket']}" if quote_row.get('used_fallback') else quote_row['bucket']
        draw.text((SIDE_MARGIN, TOP_MARGIN + 24), subtitle, font=debug_font, fill=FAINT)

    ornament_bbox = draw.textbbox((0, 0), "“", font=ornament_font)
    ornament_width = ornament_bbox[2] - ornament_bbox[0]
    draw.text((column_x - ornament_width - 12, quote_top - 18), "“", font=ornament_font, fill=ORNAMENT)

    y = quote_top
    for line in wrapped_quote:
        x = column_x
        for chunk, is_bold in line:
            font = quote_font_bold if is_bold else quote_font
            fill = ACCENT if is_bold else TEXT
            draw.text((x, y), chunk, font=font, fill=fill)
            x += draw.textbbox((0, 0), chunk, font=font)[2]
        y += line_height

    quote_end_y = y - line_height + 4
    closing_bbox = draw.textbbox((0, 0), "”", font=ornament_font)
    closing_width = closing_bbox[2] - closing_bbox[0]
    draw.text((column_x + QUOTE_COLUMN_WIDTH - closing_width + 8, quote_end_y - 6), "”", font=ornament_font, fill=ORNAMENT)

    if author_lines or title_lines:
        y += 20
        if author_lines:
            draw.text((column_x, y), f"— {author_lines[0]}", font=attribution_font, fill=SUBTLE)
            y += 24
        for line in title_lines:
            draw.text((column_x + 18, y), line, font=attribution_title_font, fill=FAINT)
            y += 20

    if show_debug:
        footer_parts = []
        if quote_row.get('used_fallback'):
            footer_parts.append("fallback")
        if quote_row.get('quality_score') is not None:
            footer_parts.append(f"quality {quote_row['quality_score']}")
        footer_parts.append(f"shown {time_str}")
        footer = " • ".join(footer_parts)
        if footer:
            footer_width = draw.textbbox((0, 0), footer, font=debug_font)[2]
            draw.text((width - SIDE_MARGIN - footer_width, height - 24), footer, font=debug_font, fill=FAINT)

    return image


def main() -> int:
    args = parse_args()
    quote_row = pick_quote(args.time, args.picker)
    output_path = Path(args.output) if args.output else Path(f"output/render-{args.time.replace(':', '')}.png")
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = render(args.time, quote_row, args.width, args.height, mode=args.mode)
    image.save(output_path)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
