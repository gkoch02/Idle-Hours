#!/usr/bin/env python3
"""Render all 144 fuzzy-bucket frames as a 12x12 contact sheet.

For each ``h{1..12}_{state}`` bucket this calls ``pick_quote.select_quote``
at the bucket's canonical time, renders the full 800x480 frame via
``render_quote.render``, then downscales it into a grid cell. The resulting
PNG is a visual audit of the whole corpus: you can spot layout regressions,
repeated authors, empty-bucket fallbacks, and weird ``matched_text`` picks
at a glance.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

import pick_quote as pick_quote_module
import render_quote as render_quote_module
from buckets import BUCKET_ORDER, DEFAULT_BUCKET_MINUTES

BASE_DIR = Path(__file__).resolve().parent
ROWS = 12
COLS = 12


def bucket_to_time(bucket: str) -> str:
    """Return canonical ``HH:MM`` for a bucket. ``h12_*`` maps to the 00:MM side."""
    hour_part, state = bucket.split("_", 1)
    hour = int(hour_part[1:])
    hour24 = 0 if hour == 12 else hour
    minute = DEFAULT_BUCKET_MINUTES[state]
    return f"{hour24:02d}:{minute:02d}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a 12x12 contact sheet of all fuzzy buckets.")
    parser.add_argument("--output", default="output/contact-sheet.png", help="Output PNG path.")
    parser.add_argument("--tile-width", type=int, default=200, help="Tile width in pixels (downscaled from 800).")
    parser.add_argument("--tile-height", type=int, default=120, help="Tile height in pixels (downscaled from 480).")
    parser.add_argument("--caption-height", type=int, default=18, help="Caption strip under each tile.")
    parser.add_argument("--margin", type=int, default=6, help="Gap between cells, in pixels.")
    parser.add_argument("--theme", choices=sorted(render_quote_module.THEMES), default="default")
    parser.add_argument(
        "--mode",
        choices=["production", "debug"],
        default="production",
        help="Render mode. Defaults to production so the debug footer does not dominate small tiles.",
    )
    return parser.parse_args()


def _placeholder_tile(time_str: str, tile_w: int, tile_h: int, theme: str, message: str) -> Image.Image:
    colors = render_quote_module.THEMES[theme]
    image = Image.new("RGB", (tile_w, tile_h), color=colors["page_bg"])
    draw = ImageDraw.Draw(image)
    font = render_quote_module.load_font(render_quote_module.META_FONT_CANDIDATES, size=14)
    draw.rectangle([(0, 0), (tile_w - 1, tile_h - 1)], outline=colors["accent"], width=2)
    msg = f"{time_str}\n(no candidate)"
    _ = message  # surfaced via log(); not drawn, tile is too small
    draw.multiline_text((6, 6), msg, fill=colors["accent"], font=font, spacing=2)
    return image


def render_tile(
    time_str: str,
    tile_w: int,
    tile_h: int,
    theme: str,
    mode: str,
    rows: list[dict] | None = None,
    overrides: dict | None = None,
) -> Image.Image:
    """Render at native 800x480 then downscale; layout matches the real clock."""
    try:
        # history=disabled on purpose: the sheet is a full-corpus snapshot.
        quote_row = pick_quote_module.select_quote(
            time_str=time_str,
            history_path=None,
            history_days=0,
            rows=rows,
            overrides=overrides,
        )
    except SystemExit as exc:
        return _placeholder_tile(time_str, tile_w, tile_h, theme, str(exc))
    full = render_quote_module.render(time_str, quote_row, 800, 480, mode=mode, theme=theme)
    return full.resize((tile_w, tile_h), Image.LANCZOS)


def build_cell(
    time_str: str,
    bucket: str,
    tile_w: int,
    tile_h: int,
    caption_h: int,
    theme: str,
    mode: str,
    rows: list[dict] | None = None,
    overrides: dict | None = None,
) -> Image.Image:
    cell_h = tile_h + caption_h
    colors = render_quote_module.THEMES[theme]
    cell = Image.new("RGB", (tile_w, cell_h), color=colors["page_bg"])
    tile = render_tile(time_str, tile_w, tile_h, theme, mode, rows=rows, overrides=overrides)
    cell.paste(tile, (0, 0))
    if caption_h > 0:
        draw = ImageDraw.Draw(cell)
        font_size = max(10, caption_h - 4)
        font = render_quote_module.load_font(render_quote_module.META_FONT_CANDIDATES, size=font_size)
        caption = f"{time_str}  {bucket}"
        draw.text((4, tile_h + 2), caption, fill=colors["text"], font=font)
    return cell


def build_sheet(
    tile_w: int,
    tile_h: int,
    caption_h: int,
    margin: int,
    theme: str,
    mode: str,
    log=print,
) -> Image.Image:
    cell_w = tile_w
    cell_h = tile_h + caption_h
    sheet_w = COLS * cell_w + (COLS + 1) * margin
    sheet_h = ROWS * cell_h + (ROWS + 1) * margin
    colors = render_quote_module.THEMES[theme]
    sheet = Image.new("RGB", (sheet_w, sheet_h), color=colors["page_bg"])
    # Load corpus + overrides once; 144 tiles would otherwise re-parse both per call.
    rows = pick_quote_module.load_rows(pick_quote_module.resolve_path("assets/candidates-attributed.jsonl"))
    overrides = pick_quote_module.load_overrides(pick_quote_module.resolve_path("assets/selection_overrides.json"))
    total = ROWS * COLS
    for row_idx, hour in enumerate(range(1, 13)):
        for col_idx, state in enumerate(BUCKET_ORDER):
            bucket = f"h{hour}_{state}"
            time_str = bucket_to_time(bucket)
            n = row_idx * COLS + col_idx + 1
            log(f"[{n:3d}/{total}] {bucket} -> {time_str}")
            cell = build_cell(time_str, bucket, tile_w, tile_h, caption_h, theme, mode, rows=rows, overrides=overrides)
            x = margin + col_idx * (cell_w + margin)
            y = margin + row_idx * (cell_h + margin)
            sheet.paste(cell, (x, y))
    return sheet


def main() -> int:
    args = parse_args()
    sheet = build_sheet(
        args.tile_width,
        args.tile_height,
        args.caption_height,
        args.margin,
        args.theme,
        args.mode,
        log=lambda msg: print(msg, file=sys.stderr, flush=True),
    )
    output = Path(args.output)
    if not output.is_absolute():
        output = BASE_DIR / output
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    print(f"Wrote {output} ({sheet.size[0]}x{sheet.size[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
