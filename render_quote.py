#!/usr/bin/env python3
"""Render a picked literary clock quote with a centered QOTD-inspired layout."""
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
ACCENT = (220, 40, 30)
ORNAMENT = (94, 109, 122)
SOURCE_BLUE = (45, 90, 170)
TOP_MARGIN = 26
SIDE_MARGIN = 58

QUOTE_FONT_REGULAR_CANDIDATES = [
    str(BASE_DIR / "fonts/PlayfairDisplay-Regular.ttf"),
    "/home/pi/.local/share/fonts/playfair-display/PlayfairDisplay-Regular.ttf",
    "/usr/share/fonts/truetype/playfair-display/PlayfairDisplay-Regular.ttf",
    "/usr/share/fonts/truetype/playfair/PlayfairDisplay-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerif-Regular.ttf",
]
QUOTE_FONT_BOLD_CANDIDATES = [
    str(BASE_DIR / "fonts/PlayfairDisplay-Bold.ttf"),
    "/home/pi/.local/share/fonts/playfair-display/PlayfairDisplay-Bold.ttf",
    "/usr/share/fonts/truetype/playfair-display/PlayfairDisplay-Bold.ttf",
    "/usr/share/fonts/truetype/playfair/PlayfairDisplay-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
]
ORNAMENT_FONT_CANDIDATES = [
    str(BASE_DIR / "fonts/PlayfairDisplay-Bold.ttf"),
    str(BASE_DIR / "fonts/PlayfairDisplay-Regular.ttf"),
    "/home/pi/.local/share/fonts/playfair-display/PlayfairDisplay-Bold.ttf",
    "/home/pi/.local/share/fonts/playfair-display/PlayfairDisplay-Regular.ttf",
    "/usr/share/fonts/truetype/playfair-display/PlayfairDisplay-Bold.ttf",
    "/usr/share/fonts/truetype/playfair-display/PlayfairDisplay-Regular.ttf",
    "/usr/share/fonts/truetype/playfair/PlayfairDisplay-Bold.ttf",
    "/usr/share/fonts/truetype/playfair/PlayfairDisplay-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
]
META_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
]

LAYOUTS = {
    "hero": {
        "max_width": 640,
        "quote_height": 248,
        "font_max": 66,
        "font_min": 32,
        "line_height_mult": 1.12,
        "mark_scale": 3.0,
        "mark_min": 76,
        "mark_max": 126,
        "author_size": 23,
        "title_size": 18,
        "author_gap": 18,
        "title_gap": 8,
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
        "author_size": 21,
        "title_size": 17,
        "author_gap": 16,
        "title_gap": 8,
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
        "author_size": 19,
        "title_size": 16,
        "author_gap": 14,
        "title_gap": 6,
    },
}


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


def choose_layout(text: str) -> str:
    length = len((text or "").strip())
    if length <= 90:
        return "hero"
    if length <= 170:
        return "standard"
    return "dense"


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
        parts = text.split(" ")
        for i, part in enumerate(parts):
            if part:
                tokens.append((part, is_bold))
            if i < len(parts) - 1:
                tokens.append((" ", is_bold))

    lines = []
    current = []
    current_width = 0
    for token, is_bold in tokens:
        font = bold_font if is_bold else regular_font
        bbox = draw.textbbox((0, 0), token, font=font)
        token_width = bbox[2] - bbox[0]
        if current and current_width + token_width > max_width and token != " ":
            lines.append(current)
            current = []
            current_width = 0
            if token == " ":
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


def fit_quote(draw, text, match_text, max_width, max_height, font_max, font_min, line_height_mult):
    segments = tokenize_quote(text, match_text)
    for size in range(font_max, font_min - 1, -2):
        regular_font = load_font(QUOTE_FONT_REGULAR_CANDIDATES, size=size)
        bold_font = load_font(QUOTE_FONT_BOLD_CANDIDATES, size=size)
        wrapped = wrap_styled_text(draw, segments, regular_font, bold_font, max_width)
        line_height = int(size * line_height_mult)
        total_height = len(wrapped) * line_height
        if total_height <= max_height:
            return regular_font, bold_font, wrapped, line_height, size
    regular_font = load_font(QUOTE_FONT_REGULAR_CANDIDATES, size=font_min)
    bold_font = load_font(QUOTE_FONT_BOLD_CANDIDATES, size=font_min)
    wrapped = wrap_styled_text(draw, segments, regular_font, bold_font, max_width)
    return regular_font, bold_font, wrapped, int(font_min * line_height_mult), font_min


def line_width(draw, line, regular_font, bold_font):
    width = 0
    for chunk, is_bold in line:
        font = bold_font if is_bold else regular_font
        bbox = draw.textbbox((0, 0), chunk, font=font)
        width += bbox[2] - bbox[0]
    return width


def draw_text(draw, xy, text, font, fill):
    draw.text(xy, text, font=font, fill=fill)


def render(time_str: str, quote_row: dict, width: int, height: int, mode: str = "debug") -> Image.Image:
    image = Image.new("RGB", (width, height), color=PAGE_BG)
    draw = ImageDraw.Draw(image)

    layout_name = choose_layout(quote_row["display_quote"])
    layout = LAYOUTS[layout_name]

    time_font = load_font(META_FONT_CANDIDATES, size=20)
    debug_font = load_font(META_FONT_CANDIDATES, size=15)
    attribution_font = load_font(QUOTE_FONT_BOLD_CANDIDATES, size=layout["author_size"])
    attribution_title_font = load_font(META_FONT_CANDIDATES, size=layout["title_size"])

    quote_font, quote_font_bold, wrapped_quote, line_height, chosen_size = fit_quote(
        draw,
        quote_row["display_quote"],
        quote_row.get("matched_text") or "",
        layout["max_width"],
        layout["quote_height"],
        layout["font_max"],
        layout["font_min"],
        layout["line_height_mult"],
    )
    quote_block_height = len(wrapped_quote) * line_height

    author_text = quote_row.get("author") or quote_row.get("source_id") or None
    title_text = quote_row.get("title") or quote_row.get("source_path") or None
    author_lines = wrap_text(draw, author_text, attribution_font, width - 160)[:1] if author_text else []
    title_lines = wrap_text(draw, title_text, attribution_title_font, width - 200)[:2] if title_text else []

    attrib_height = 0
    if author_lines:
        attrib_height += layout["author_size"]
    if title_lines:
        attrib_height += layout["author_gap"] + len(title_lines) * layout["title_size"]
        if len(title_lines) > 1:
            attrib_height += (len(title_lines) - 1) * layout["title_gap"]

    total_h = quote_block_height + (layout["author_gap"] if (author_lines or title_lines) else 0) + attrib_height
    block_top = max(72, (height - total_h) // 2)
    block_bottom = block_top + total_h
    quote_top = block_top

    show_debug = mode == "debug"
    if show_debug:
        draw_text(draw, (SIDE_MARGIN, TOP_MARGIN), time_str, font=time_font, fill=SUBTLE)
        subtitle = f"bucket {quote_row['resolved_bucket']}" if quote_row.get("used_fallback") else quote_row["bucket"]
        draw_text(draw, (SIDE_MARGIN, TOP_MARGIN + 24), subtitle, font=debug_font, fill=FAINT)

    mark_size = min(layout["mark_max"], max(layout["mark_min"], int(chosen_size * layout["mark_scale"])))
    mark_font = load_font(ORNAMENT_FONT_CANDIDATES, size=mark_size)

    open_bb = draw.textbbox((0, 0), "“", font=mark_font)
    open_w = open_bb[2] - open_bb[0]
    open_h = open_bb[3] - open_bb[1]
    open_x = SIDE_MARGIN + 18
    open_y = quote_top - open_h // 3
    draw_text(draw, (open_x - open_bb[0], open_y - open_bb[1]), "“", font=mark_font, fill=ORNAMENT)

    y = quote_top
    for line in wrapped_quote:
        lw = line_width(draw, line, quote_font, quote_font_bold)
        x = (width - lw) // 2
        for chunk, is_bold in line:
            font = quote_font_bold if is_bold else quote_font
            fill = ACCENT if is_bold else TEXT
            draw_text(draw, (x, y), chunk, font=font, fill=fill)
            bbox = draw.textbbox((0, 0), chunk, font=font)
            x += bbox[2] - bbox[0]
        y += line_height

    close_bb = draw.textbbox((0, 0), "”", font=mark_font)
    close_w = close_bb[2] - close_bb[0]
    close_h = close_bb[3] - close_bb[1]
    close_x = width - SIDE_MARGIN - 18 - close_w
    close_y = block_bottom - close_h * 2 // 3
    draw_text(draw, (close_x - close_bb[0], close_y - close_bb[1]), "”", font=mark_font, fill=ORNAMENT)

    y = quote_top + quote_block_height + layout["author_gap"]
    if author_lines:
        author_text_line = f"— {author_lines[0]}"
        author_w = draw.textbbox((0, 0), author_text_line, font=attribution_font)[2]
        draw_text(draw, ((width - author_w) // 2, y), author_text_line, font=attribution_font, fill=TEXT)
        y += layout["author_size"] + layout["title_gap"]

    for line in title_lines:
        title_w = draw.textbbox((0, 0), line, font=attribution_title_font)[2]
        draw_text(draw, ((width - title_w) // 2, y), line, font=attribution_title_font, fill=SOURCE_BLUE)
        y += layout["title_size"] + layout["title_gap"]

    if show_debug:
        footer_parts = [f"layout {layout_name}"]
        if quote_row.get("used_fallback"):
            footer_parts.append("fallback")
        if quote_row.get("quality_score") is not None:
            footer_parts.append(f"quality {quote_row['quality_score']}")
        footer_parts.append(f"shown {time_str}")
        footer = " • ".join(footer_parts)
        footer_width = draw.textbbox((0, 0), footer, font=debug_font)[2]
        draw_text(draw, (width - SIDE_MARGIN - footer_width, height - 24), footer, font=debug_font, fill=FAINT)

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
