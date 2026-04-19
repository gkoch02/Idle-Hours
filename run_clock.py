#!/usr/bin/env python3
"""Runtime loop for the literary clock prototype."""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

import pick_quote as pick_quote_module
from buckets import bucket_for_time

BASE_DIR = Path(__file__).resolve().parent


def _log(msg: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    print(f"[{dt.datetime.now().isoformat(timespec='seconds')}] {msg}", file=stream, flush=True)


def _valid_hhmm(value: str) -> str:
    parts = value.split(":")
    try:
        h, m = int(parts[0]), int(parts[1])
        if not (len(parts) == 2 and 0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
    except (ValueError, IndexError):
        raise argparse.ArgumentTypeError(f"{value!r} is not a valid HH:MM time (expected 00:00–23:59)")
    return value


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
    parser.add_argument(
        "--mode",
        choices=["production", "debug"],
        default="debug",
        help="Render mode passed through to render_quote.py",
    )
    parser.add_argument(
        "--theme",
        choices=["default", "dark"],
        default="default",
        help="Render theme passed through to render_quote.py",
    )
    parser.add_argument(
        "--quiet-start",
        metavar="HH:MM",
        default="22:00",
        type=_valid_hhmm,
        help="Start of quiet window in 24-hour time (default: 22:00). Requires --quiet-end.",
    )
    parser.add_argument(
        "--quiet-end",
        metavar="HH:MM",
        default="06:00",
        type=_valid_hhmm,
        help="End of quiet window in 24-hour time (default: 06:00). Requires --quiet-start.",
    )
    parser.add_argument(
        "--quiet-image",
        metavar="PATH",
        default="assets/goodnight.png",
        help="PNG to display when quiet hours begin instead of rendering a corpus quote.",
    )
    parser.add_argument(
        "--quiet-off",
        action="store_true",
        help="Disable quiet hours entirely and render around the clock.",
    )
    args = parser.parse_args()
    if (args.quiet_start is None) != (args.quiet_end is None):
        parser.error("--quiet-start and --quiet-end must be specified together")
    return args


def current_time_str() -> str:
    return dt.datetime.now().strftime("%H:%M")


def current_bucket() -> str:
    return bucket_for_time(current_time_str())


def in_quiet_hours(time_str: str, start: str | None, end: str | None) -> bool:
    """Return True if time_str falls within the [start, end) quiet window.

    Handles overnight ranges (e.g. 22:00–07:00) where start > end.
    Returns False when either bound is None (quiet hours disabled).
    """
    if start is None:
        return False

    def to_mins(t: str) -> int:
        h, m = map(int, t.split(":"))
        return h * 60 + m

    cur, s, e = to_mins(time_str), to_mins(start), to_mins(end)
    return (cur >= s or cur < e) if s > e else (s <= cur < e)


def _display_quiet_image(quiet_image: str, output: str, display_script: str | None) -> None:
    """Copy quiet_image to the output path and optionally push it to the display script."""
    quiet_path = Path(quiet_image) if Path(quiet_image).is_absolute() else (BASE_DIR / quiet_image).resolve()
    output_resolved = str((BASE_DIR / output).resolve()) if not Path(output).is_absolute() else output
    shutil.copy2(str(quiet_path), output_resolved)
    _log(f"quiet hours: {quiet_path.name} -> {output_resolved}")
    if display_script:
        display_path = str((BASE_DIR / display_script).resolve()) if not Path(display_script).is_absolute() else display_script
        subprocess.check_call([sys.executable, display_path, output_resolved])
        _log(f"Displayed {output_resolved} via {display_path}")


def peek_quote_id(time_str: str) -> tuple | None:
    """Return a stable identity tuple for the quote pick_quote would return, or None on failure.

    ``matched_text`` is part of the identity because the renderer uses it to choose which
    phrase is bolded and coloured. Two picks that share (source_id, line_number, display_quote)
    but differ in matched_text (e.g. ``02:50`` vs ``02:55`` landing on the same row) still
    produce visibly different frames, so they must not dedup together.

    ``pick_quote.select_quote`` raises ``SystemExit`` when no candidate survives the quality
    gate in the target bucket or its neighbours; we swallow that alongside ``Exception`` so
    the runtime loop keeps ticking instead of aborting.
    """
    try:
        row = pick_quote_module.select_quote(time_str=time_str)
    except (Exception, SystemExit) as exc:
        _log(f"pick_quote failed for {time_str}: {exc!r}", err=True)
        return None
    return (
        row.get("source_id"),
        row.get("line_number"),
        row.get("display_quote"),
        row.get("matched_text"),
    )


def render_now(render_script: str, output_path: str, width: int, height: int, display_script: str | None = None, mode: str = "debug", theme: str = "default", time_str: str | None = None) -> None:
    if time_str is None:
        time_str = current_time_str()
    python_executable = sys.executable
    render_script_path = str((BASE_DIR / render_script).resolve()) if not Path(render_script).is_absolute() else render_script
    output_path_resolved = str((BASE_DIR / output_path).resolve()) if not Path(output_path).is_absolute() else output_path
    subprocess.check_call(
        [
            python_executable,
            render_script_path,
            "--time",
            time_str,
            "--output",
            output_path_resolved,
            "--width",
            str(width),
            "--height",
            str(height),
            "--mode",
            mode,
            "--theme",
            theme,
        ]
    )
    _log(f"Rendered {time_str} -> {output_path_resolved}")
    if display_script:
        display_script_path = str((BASE_DIR / display_script).resolve()) if not Path(display_script).is_absolute() else display_script
        subprocess.check_call([python_executable, display_script_path, output_path_resolved])
        _log(f"Displayed {output_path_resolved} via {display_script_path}")


def main() -> int:
    args = parse_args()
    output_target = Path(args.output)
    if not output_target.is_absolute():
        output_target = BASE_DIR / output_target
    output_target.expanduser().parent.mkdir(parents=True, exist_ok=True)

    if args.once:
        render_now(args.render_script, args.output, args.width, args.height, args.display_script, args.mode, args.theme)
        return 0

    last_bucket = None
    last_quote_id = None
    _was_quiet = False
    while True:
        time_str = current_time_str()
        now_quiet = in_quiet_hours(time_str, None if args.quiet_off else args.quiet_start, args.quiet_end)

        if now_quiet:
            if not _was_quiet:
                _log(f"quiet hours start ({args.quiet_start}–{args.quiet_end})")
                try:
                    if args.quiet_image:
                        _display_quiet_image(args.quiet_image, args.output, args.display_script)
                    else:
                        render_now(args.render_script, args.output, args.width, args.height, args.display_script, args.mode, args.theme, time_str=args.quiet_start)
                except Exception as exc:
                    _log(f"quiet-hours display failed: {exc!r}", err=True)
                    traceback.print_exc(file=sys.stderr)
                _was_quiet = True
            time.sleep(max(1, args.interval_seconds))
            continue

        if _was_quiet:
            _log("quiet hours end, resuming normal render cycle")
            last_bucket = None
            last_quote_id = None
            _was_quiet = False

        bucket = current_bucket()
        if bucket != last_bucket:
            try:
                quote_id = peek_quote_id(time_str)
                if quote_id is not None and quote_id == last_quote_id:
                    _log(f"bucket {bucket}: quote unchanged, skipping redraw")
                    last_bucket = bucket
                else:
                    render_now(args.render_script, args.output, args.width, args.height, args.display_script, args.mode, args.theme, time_str=time_str)
                    last_bucket = bucket
                    if quote_id is not None:
                        last_quote_id = quote_id
            except Exception as exc:
                # Keep the loop alive so a transient failure (pick_quote crash, Inky I/O,
                # missing corpus row, etc.) does not kill the appliance. last_bucket stays
                # stale so the next tick retries.
                _log(f"render/display failed for bucket {bucket}: {exc!r}", err=True)
                traceback.print_exc(file=sys.stderr)
        time.sleep(max(1, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
