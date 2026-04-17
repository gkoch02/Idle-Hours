#!/usr/bin/env python3
"""Runtime loop for the literary clock prototype."""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the literary clock render loop.")
    parser.add_argument(
        "--render-script",
        default="projects/author-clock/render_quote.py",
        help="Path to render script.",
    )
    parser.add_argument(
        "--output",
        default="projects/author-clock/output/current.png",
        help="Output image path to refresh in place.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Render once and exit.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=60,
        help="Refresh interval in seconds.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=800,
        help="Render width.",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=480,
        help="Render height.",
    )
    return parser.parse_args()


def current_time_str() -> str:
    return dt.datetime.now().strftime("%H:%M")


def render_now(render_script: str, output_path: str, width: int, height: int) -> None:
    time_str = current_time_str()
    subprocess.check_call(
        [
            "python3",
            render_script,
            "--time",
            time_str,
            "--output",
            output_path,
            "--width",
            str(width),
            "--height",
            str(height),
        ]
    )
    print(f"Rendered {time_str} -> {output_path}")


def main() -> int:
    args = parse_args()
    Path(args.output).expanduser().parent.mkdir(parents=True, exist_ok=True)

    if args.once:
        render_now(args.render_script, args.output, args.width, args.height)
        return 0

    last_minute = None
    while True:
        now = dt.datetime.now()
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        if minute_key != last_minute:
            render_now(args.render_script, args.output, args.width, args.height)
            last_minute = minute_key
        time.sleep(max(1, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
