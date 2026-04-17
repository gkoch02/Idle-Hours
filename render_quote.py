#!/usr/bin/env python3
"""Render a picked literary clock quote to a grayscale image."""
from __future__ import annotations

import argparse
import json
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = Path(__file__).resolve().parent


DEFAULT_WIDTH = 800
DEFAULT_HEIGHT = 480
MARGIN_X = 48
MARGIN_Y = 36
QUOTE_FONT_PATH = "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf"
QUOTE_FONT_BOLD_PATH = "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf"
META_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a literary clock quote for a given time.")
    parser.add_argument("--time", required=True, help="Time in HH:MM 24-hour format")
    parser.add_argument(
        "--picker",
        default="pick_quote.py",
        help="Path to quote picker script",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output PNG path. Defaults to output/render-HHMM.png",
    )
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    return parser.parse_args()


def pick_quote(time_str: str, picker_path: str) -> dict:
    picker = str((BASE_DIR / picker_path).resolve()) if not Path(picker_path).is_absolute() else picker_path
    output = subprocess.check_output(["python3", picker, "--time", time_str], text=True)
    return json.loads(output)


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


def wrap_styled_text(draw: ImageDraw.ImageDraw, segments: list[tuple[str, bool]], regular_font: ImageFont.FreeTypeFont, bold_font: ImageFont.FreeTypeFont, max_width: int) -> list[list[tuple[str, bool]]]:
    tokens: list[tuple[str, bool]] = []
    for text, is_bold in segments:
        parts = text.split(' ')
        for i, part in enumerate(parts):
            if part:
                tokens.append((part, is_bold))
            if i < len(parts) - 1:
                tokens.append((' ', is_bold))

    lines: list[list[tuple[str, bool]]] = []
    current: list[tuple[str, bool]] = []
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


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
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


def fit_quote(draw: ImageDraw.ImageDraw, text: str, match_text: str, max_width: int, max_height: int) -> tuple[ImageFont.FreeTypeFont, ImageFont.FreeTypeFont, list[list[tuple[str, bool]]], int]:
    segments = tokenize_quote(text, match_text)
    for size in range(34, 19, -2):
        regular_font = ImageFont.truetype(QUOTE_FONT_PATH, size=size)
        bold_font = ImageFont.truetype(QUOTE_FONT_BOLD_PATH, size=size)
        wrapped = wrap_styled_text(draw, segments, regular_font, bold_font, max_width)
        line_height = int(size * 1.45)
        total_height = len(wrapped) * line_height
        if total_height <= max_height:
            return regular_font, bold_font, wrapped, line_height
    regular_font = ImageFont.truetype(QUOTE_FONT_PATH, size=20)
    bold_font = ImageFont.truetype(QUOTE_FONT_BOLD_PATH, size=20)
    wrapped = wrap_styled_text(draw, segments, regular_font, bold_font, max_width)
    return regular_font, bold_font, wrapped, int(20 * 1.45)


def render(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    image = Image.new("L", (width, height), color=245)
    draw = ImageDraw.Draw(image)

    title_font = ImageFont.truetype(META_FONT_PATH, size=22)
    quote_font_bold = ImageFont.truetype(QUOTE_FONT_BOLD_PATH, size=26)
    meta_font = ImageFont.truetype(META_FONT_PATH, size=18)

    draw.text((MARGIN_X, MARGIN_Y), time_str, font=quote_font_bold, fill=10)

    subtitle = f"bucket: {quote_row['resolved_bucket']}" if quote_row.get('used_fallback') else quote_row['bucket']
    draw.text((MARGIN_X, MARGIN_Y + 34), subtitle, font=meta_font, fill=90)

    quote_top = MARGIN_Y + 88
    quote_max_width = width - (MARGIN_X * 2)
    quote_max_height = height - quote_top - 90
    quote_font, quote_font_bold, wrapped_quote, line_height = fit_quote(
        draw,
        quote_row['display_quote'],
        quote_row.get('matched_text') or '',
        quote_max_width,
        quote_max_height,
    )

    y = quote_top
    for line in wrapped_quote:
        x = MARGIN_X
        for chunk, is_bold in line:
            font = quote_font_bold if is_bold else quote_font
            draw.text((x, y), chunk, font=font, fill=20)
            x += draw.textbbox((0, 0), chunk, font=font)[2]
        y += line_height

    attribution_parts = []
    if quote_row.get('author'):
        attribution_parts.append(quote_row['author'])
    if quote_row.get('title'):
        attribution_parts.append(quote_row['title'])
    attribution = " — ".join(attribution_parts) if attribution_parts else None
    if attribution:
        attrib_wrapped = wrap_text(draw, attribution, meta_font, width - (MARGIN_X * 2))
        attrib_y = height - 62
        for line in attrib_wrapped[:2]:
            draw.text((MARGIN_X, attrib_y), line, font=meta_font, fill=80)
            attrib_y += 20

    source_bits = []
    if quote_row.get('used_fallback'):
        source_bits.append("fallback")
    if quote_row.get('quality_score') is not None:
        source_bits.append(f"quality {quote_row['quality_score']}")
    footer = " • ".join(source_bits)
    if footer:
        draw.text((width - MARGIN_X - draw.textbbox((0, 0), footer, font=meta_font)[2], height - 28), footer, font=meta_font, fill=110)

    return image


def main() -> int:
    args = parse_args()
    quote_row = pick_quote(args.time, args.picker)
    output_path = Path(args.output) if args.output else Path(f"output/render-{args.time.replace(':', '')}.png")
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = render(args.time, quote_row, args.width, args.height)
    image.save(output_path)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
