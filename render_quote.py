#!/usr/bin/env python3
"""Render a picked literary clock quote with a centered QOTD-inspired layout."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import pick_quote as pick_quote_module

BASE_DIR = Path(__file__).resolve().parent
_FONT_FALLBACK_WARNED = False

DEFAULT_WIDTH = 800
DEFAULT_HEIGHT = 480
SPECTRA6 = {
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "red": (255, 0, 0),
    "yellow": (255, 255, 0),
    "blue": (0, 0, 255),
    "green": (0, 255, 0),
}
SPECTRA6_PALETTE = list(SPECTRA6.values())
THEMES = {
    "default": {
        "page_bg": SPECTRA6["white"],
        "text": SPECTRA6["black"],
        "subtle": SPECTRA6["black"],
        "faint": SPECTRA6["black"],
        "accent": SPECTRA6["red"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["black"],
    },
    "dark": {
        "page_bg": SPECTRA6["black"],
        "text": SPECTRA6["white"],
        "subtle": SPECTRA6["white"],
        "faint": SPECTRA6["white"],
        "accent": SPECTRA6["yellow"],
        "ornament_dark": SPECTRA6["black"],
        "ornament_light": SPECTRA6["white"],
        "source": SPECTRA6["white"],
    },
}
SIDE_MARGIN = 20

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
QUOTE_FONT_SEMIBOLD_CANDIDATES = [
    str(BASE_DIR / "fonts/PlayfairDisplay-SemiBold.ttf"),
    "/home/pi/.local/share/fonts/playfair-display/PlayfairDisplay-SemiBold.ttf",
    "/usr/share/fonts/truetype/playfair-display/PlayfairDisplay-SemiBold.ttf",
    "/usr/share/fonts/truetype/playfair/PlayfairDisplay-SemiBold.ttf",
    str(BASE_DIR / "fonts/PlayfairDisplay-Medium.ttf"),
    "/home/pi/.local/share/fonts/playfair-display/PlayfairDisplay-Medium.ttf",
    "/usr/share/fonts/truetype/playfair-display/PlayfairDisplay-Medium.ttf",
    "/usr/share/fonts/truetype/playfair/PlayfairDisplay-Medium.ttf",
    str(BASE_DIR / "fonts/PlayfairDisplay-Bold.ttf"),
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a literary clock quote for a given time.")
    parser.add_argument("--time", required=True, help="Time in HH:MM 24-hour format")
    parser.add_argument("--output", default=None, help="Output PNG path. Defaults to output/render-HHMM.png")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument(
        "--mode",
        choices=["production", "debug"],
        default="debug",
        help="Render mode. Production hides debug UI, debug shows bucket/quality/time metadata.",
    )
    parser.add_argument(
        "--theme",
        choices=sorted(THEMES),
        default="default",
        help="Color theme to use when rendering.",
    )
    return parser.parse_args()


def pick_quote(time_str: str) -> dict:
    return pick_quote_module.select_quote(time_str=time_str)


def load_font(candidates: list[str], size: int):
    global _FONT_FALLBACK_WARNED
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    if not _FONT_FALLBACK_WARNED:
        print(
            "warning: no TrueType font found; falling back to PIL bitmap default. "
            "Install fonts-noto-core or the bundled fonts/ directory.",
            file=sys.stderr,
            flush=True,
        )
        _FONT_FALLBACK_WARNED = True
    return ImageFont.load_default()


def strip_underscore_emphasis(text: str) -> str:
    if not text or "_" not in text:
        return text or ""
    return re.sub(r"(?<![A-Za-z0-9])_([^_\n]+?)_(?![A-Za-z0-9])", r"\1", text)


def normalize_dashes(text: str) -> str:
    if not text or "--" not in text:
        return text or ""
    return re.sub(r"(?<!-)--(?!-)", "\u2014", text)


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


def resolve_display_match(text: str, match_text: str) -> str:
    normalized_match = " ".join((match_text or "").split()).strip()
    if not normalized_match:
        return ""

    direct = re.search(rf"(?<![A-Za-z0-9-]){re.escape(normalized_match)}(?![A-Za-z0-9-])", text, re.IGNORECASE)
    if direct:
        return direct.group(0)

    for prefix in sorted(TIME_PHRASE_PREFIXES, key=len, reverse=True):
        if not normalized_match.lower().startswith(prefix):
            continue
        pattern = re.compile(rf"(?<![A-Za-z0-9-]){re.escape(prefix)}(?:[ ,]+[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)?(?![A-Za-z0-9-])", re.IGNORECASE)
        for m in pattern.finditer(text):
            candidate = m.group(0).strip(" ,.;:!?")
            if candidate.lower().startswith(normalized_match.lower()):
                return candidate

    return normalized_match


def tokenize_quote(text: str, match_text: str) -> list[tuple[str, bool]]:
    normalized_match = resolve_display_match(text, match_text)
    if not normalized_match:
        return [(text, False)]
    pattern = re.compile(rf"(?<![A-Za-z0-9-]){re.escape(normalized_match)}(?![A-Za-z0-9-])", re.IGNORECASE)
    match = pattern.search(text)
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


def wrap_styled_text(draw, segments, regular_font, bold_font, max_width):
    lines = []
    current = []
    current_width = 0

    for text, is_bold in segments:
        if is_bold:
            parts = text.split(" ")
            bold_chunks = []
            for i, part in enumerate(parts):
                if part:
                    bold_chunks.append((part, True))
                if i < len(parts) - 1:
                    bold_chunks.append((" ", True))
            chunk_width = sum(
                draw.textbbox((0, 0), token, font=bold_font)[2] - draw.textbbox((0, 0), token, font=bold_font)[0]
                for token, _ in bold_chunks
            )
            if current and current_width + chunk_width > max_width:
                lines.append(current)
                current = []
                current_width = 0
            current.extend(bold_chunks)
            current_width += chunk_width
            continue

        parts = text.split(" ")
        for i, part in enumerate(parts):
            if part:
                token = part
                font = regular_font
                bbox = draw.textbbox((0, 0), token, font=font)
                token_width = bbox[2] - bbox[0]
                if current and current_width + token_width > max_width:
                    lines.append(current)
                    current = []
                    current_width = 0
                current.append((token, False))
                current_width += token_width
            if i < len(parts) - 1:
                token = " "
                font = regular_font
                bbox = draw.textbbox((0, 0), token, font=font)
                token_width = bbox[2] - bbox[0]
                if current and current_width + token_width > max_width:
                    lines.append(current)
                    current = []
                    current_width = 0
                current.append((token, False))
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
        regular_font = load_font(QUOTE_FONT_SEMIBOLD_CANDIDATES, size=size)
        bold_font = load_font(QUOTE_FONT_BOLD_CANDIDATES, size=size)
        wrapped = wrap_styled_text(draw, segments, regular_font, bold_font, max_width)
        line_height = int(size * line_height_mult)
        total_height = len(wrapped) * line_height
        if total_height <= max_height:
            return regular_font, bold_font, wrapped, line_height, size
    regular_font = load_font(QUOTE_FONT_SEMIBOLD_CANDIDATES, size=font_min)
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


def draw_faux_gray_text(image: Image.Image, xy, text, font, dark=(0, 0, 0), light=(255, 255, 255), pattern_offset=(0, 0)):
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text(xy, text, font=font, fill=255)
    px = image.load()
    mx = mask.load()
    ox, oy = pattern_offset
    for y in range(image.height):
        for x in range(image.width):
            if mx[x, y]:
                px[x, y] = dark if ((x + ox) + (y + oy)) % 2 == 0 else light


def snap_image_to_palette(image: Image.Image, palette: list[tuple[int, int, int]]) -> Image.Image:
    snapped = Image.new("RGB", image.size)
    src = image.load()
    dst = snapped.load()
    for y in range(image.height):
        for x in range(image.width):
            pixel = src[x, y]
            nearest = min(
                palette,
                key=lambda c: (pixel[0] - c[0]) ** 2 + (pixel[1] - c[1]) ** 2 + (pixel[2] - c[2]) ** 2,
            )
            dst[x, y] = nearest
    return snapped


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


def fallback_title(quote_row: dict) -> str | None:
    source_id = quote_row.get("source_id")
    if source_id:
        return f"Project Gutenberg #{source_id}"
    source_path = quote_row.get("source_path")
    if source_path:
        return Path(source_path).stem
    return None


def render(time_str: str, quote_row: dict, width: int, height: int, mode: str = "debug", theme: str = "default") -> Image.Image:
    colors = THEMES[theme]
    image = Image.new("RGB", (width, height), color=colors["page_bg"])
    draw = ImageDraw.Draw(image)

    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row["display_quote"]))
    layout_name = choose_layout(display_quote)
    layout = LAYOUTS[layout_name]

    debug_font = load_font(META_FONT_CANDIDATES, size=15)
    debug_label_font = load_font(QUOTE_FONT_SEMIBOLD_CANDIDATES, size=16)
    quote_font, quote_font_bold, wrapped_quote, line_height, chosen_size = fit_quote(
        draw,
        display_quote,
        quote_row.get("matched_text") or "",
        layout["max_width"],
        layout["quote_height"],
        layout["font_max"],
        layout["font_min"],
        layout["line_height_mult"],
    )
    quote_block_height = len(wrapped_quote) * line_height
    author_size = max(13, int(chosen_size * 0.52))
    source_size = max(13, int(chosen_size * 0.47))
    attribution_font = load_font(QUOTE_FONT_SEMIBOLD_CANDIDATES, size=author_size)
    attribution_title_font = load_font(QUOTE_FONT_SEMIBOLD_CANDIDATES, size=source_size)

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

    show_debug = mode == "debug"

    mark_size = min(layout["mark_max"], max(layout["mark_min"], int(chosen_size * layout["mark_scale"])))
    mark_font = load_font(ORNAMENT_FONT_CANDIDATES, size=mark_size)

    open_bb = draw.textbbox((0, 0), "“", font=mark_font)
    open_h = open_bb[3] - open_bb[1]
    open_x = SIDE_MARGIN + 18
    open_y = quote_top - open_h // 3
    draw_faux_gray_text(
        image,
        (open_x - open_bb[0], open_y - open_bb[1]),
        "“",
        font=mark_font,
        dark=colors["ornament_dark"],
        light=colors["ornament_light"],
        pattern_offset=(0, 0),
    )

    y = quote_top
    total_lines = len(wrapped_quote)
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
            bbox = draw.textbbox((0, 0), chunk, font=font)
            current_width += bbox[2] - bbox[0]

        space_slots = sum(1 for chunk, _ in drawable if chunk == " ")
        is_last = line_index == total_lines - 1
        slack = layout["max_width"] - current_width

        distribute = []
        if not is_last and space_slots > 0 and slack > 0:
            base = slack // space_slots
            remainder = slack - base * space_slots
            distribute = [base + (1 if i < remainder else 0) for i in range(space_slots)]

        x = (width - layout["max_width"]) // 2
        space_idx = 0
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            fill = colors["accent"] if is_bold else colors["text"]
            draw_text(draw, (x, y), chunk, font=font, fill=fill)
            bbox = draw.textbbox((0, 0), chunk, font=font)
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
    draw_faux_gray_text(
        image,
        (close_x - close_bb[0], close_y - close_bb[1]),
        "”",
        font=mark_font,
        dark=colors["ornament_dark"],
        light=colors["ornament_light"],
        pattern_offset=(1, 0),
    )

    y = quote_top + quote_block_height + layout["author_gap"]
    if author_lines:
        author_text_line = author_lines[0]
        author_x = (width - layout["max_width"]) // 2
        draw_text(draw, (author_x, y), author_text_line, font=attribution_font, fill=colors["text"])
        y += author_size + layout["title_gap"]

    for line in title_lines:
        title_x = (width - layout["max_width"]) // 2
        draw_text(draw, (title_x, y), line, font=attribution_title_font, fill=colors["source"])
        y += source_size + layout["title_gap"]

    if show_debug:
        debug_label = "DEBUG MODE"
        label_bbox = draw.textbbox((0, 0), debug_label, font=debug_label_font)
        label_w = label_bbox[2] - label_bbox[0]
        label_h = label_bbox[3] - label_bbox[1]
        label_x = width - SIDE_MARGIN - label_w
        label_y = 14

        draw_text(draw, (label_x, label_y), debug_label, font=debug_label_font, fill=colors["accent"])

        bucket_value = quote_row.get("bucket") or ""
        resolved = quote_row.get("resolved_bucket") or bucket_value
        if quote_row.get("used_fallback") and resolved and bucket_value and resolved != bucket_value:
            bucket_piece = f"{bucket_value} → {resolved}"
        else:
            bucket_piece = resolved or bucket_value

        debug_parts = [time_str]
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

        draw_text(draw, (strip_x, strip_y), debug_strip, font=debug_font, fill=colors["faint"])

    return snap_image_to_palette(image, SPECTRA6_PALETTE)


def main() -> int:
    args = parse_args()
    quote_row = pick_quote(args.time)
    output_path = Path(args.output) if args.output else Path(f"output/render-{args.time.replace(':', '')}.png")
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = render(args.time, quote_row, args.width, args.height, mode=args.mode, theme=args.theme)
    image.save(output_path)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
