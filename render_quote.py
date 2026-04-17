#!/usr/bin/env python3
"""Render a picked literary clock quote to a grayscale image."""
from __future__ import annotations

import argparse
import json
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


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
        default="projects/author-clock/pick_quote.py",
        help="Path to quote picker script",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output PNG path. Defaults to projects/author-clock/output/render-HHMM.png",
    )
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    return parser.parse_args()


def pick_quote(time_str: str, picker_path: str) -> dict:
    output = subprocess.check_output(["python3", picker_path, "--time", time_str], text=True)
    return json.loads(output)


def fit_quote(draw: ImageDraw.ImageDraw, text: str, max_width: int, max_height: int) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    for size in range(34, 19, -2):
        font = ImageFont.truetype(QUOTE_FONT_PATH, size=size)
        wrapped = wrap_text(draw, text, font, max_width)
        line_height = int(size * 1.45)
        total_height = len(wrapped) * line_height
        if total_height <= max_height:
            return font, wrapped, line_height
    font = ImageFont.truetype(QUOTE_FONT_PATH, size=20)
    wrapped = wrap_text(draw, text, font, max_width)
    return font, wrapped, int(20 * 1.45)


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
    quote_font, wrapped_quote, line_height = fit_quote(draw, quote_row['display_quote'], quote_max_width, quote_max_height)

    y = quote_top
    for line in wrapped_quote:
        draw.text((MARGIN_X, y), line, font=quote_font, fill=20)
        y += line_height

    source_bits = []
    if quote_row.get('source_id'):
        source_bits.append(f"source {quote_row['source_id']}")
    if quote_row.get('used_fallback'):
        source_bits.append("fallback")
    if quote_row.get('quality_score') is not None:
        source_bits.append(f"quality {quote_row['quality_score']}")
    footer = " • ".join(source_bits)
    if footer:
        draw.text((MARGIN_X, height - 36), footer, font=meta_font, fill=110)

    return image


def main() -> int:
    args = parse_args()
    quote_row = pick_quote(args.time, args.picker)
    output_path = Path(args.output) if args.output else Path(f"projects/author-clock/output/render-{args.time.replace(':', '')}.png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = render(args.time, quote_row, args.width, args.height)
    image.save(output_path)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
