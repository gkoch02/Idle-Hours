#!/usr/bin/env python3
"""Runtime loop for the literary clock prototype."""
from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the literary clock render loop.")
    parser.add_argument(
        "--render-script",
        default="render_quote.py",
        help="Path to render script.",
    )
    parser.add_argument(
        "--output",
        default="output/current.png",
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
    parser.add_argument(
        "--display-script",
        default=None,
        help="Optional script to push the rendered image to hardware, e.g. display_inky.py",
    )
    return parser.parse_args()


def current_time_str() -> str:
    return dt.datetime.now().strftime("%H:%M")


def render_now(render_script: str, output_path: str, width: int, height: int, display_script: str | None = None) -> None:
    time_str = current_time_str()
    render_script_path = str((BASE_DIR / render_script).resolve()) if not Path(render_script).is_absolute() else render_script
    output_path_resolved = str((BASE_DIR / output_path).resolve()) if not Path(output_path).is_absolute() else output_path
    subprocess.check_call(
        [
            "python3",
            render_script_path,
            "--time",
            time_str,
            "--output",
            output_path_resolved,
            "--width",
            str(width),
            "--height",
            str(height),
        ]
    )
    print(f"Rendered {time_str} -> {output_path_resolved}")
    if display_script:
        display_script_path = str((BASE_DIR / display_script).resolve()) if not Path(display_script).is_absolute() else display_script
        subprocess.check_call(["python3", display_script_path, output_path_resolved])
        print(f"Displayed {output_path_resolved} via {display_script_path}")


def main() -> int:
    args = parse_args()
    output_target = Path(args.output)
    if not output_target.is_absolute():
        output_target = BASE_DIR / output_target
    output_target.expanduser().parent.mkdir(parents=True, exist_ok=True)

    if args.once:
        render_now(args.render_script, args.output, args.width, args.height, args.display_script)
        return 0

    last_minute = None
    while True:
        now = dt.datetime.now()
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        if minute_key != last_minute:
            render_now(args.render_script, args.output, args.width, args.height, args.display_script)
            last_minute = minute_key
        time.sleep(max(1, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
