#!/usr/bin/env python3
"""Hash every theme's frames so a refactor can prove it changed no pixels.

The golden suite tolerates 0.1% of differing pixels per frame, which is the
right bar for a deliberate theme change and the wrong one for a pure code move:
a move that nudges a few hundred pixels passes it. This script is the stricter
check for moves such as splitting ``render_quote`` into a package (issue #335).
It renders a fixed set of frames for every registered theme and records a
sha256 of each frame's raw pixels. Two runs, one on ``main`` and one on the
branch, must produce identical files.

Each theme renders three quote lengths (hero / standard / dense) at two times,
in production and debug mode. It also renders a half-size thumbnail (the
NEAREST downsample path of the fixed-geometry frames), the sleep frame, the
button-C source card (``mode="card"``, a separate code path) and a debug frame
of a row with no author or title that was served from a fallback bucket. That
row exercises the attribution-skipped layout and the footer's arrow form. The wall
clock, the ``diags`` system strip and ``IDLE_HOURS_PHOTO_PATH`` are pinned the
same way ``generate_theme_previews.py`` pins them, so the output depends only
on the code.

Usage::

    python3 scripts/render_fingerprint.py --output /tmp/before.json   # on main
    python3 scripts/render_fingerprint.py --output /tmp/after.json    # on the branch
    python3 scripts/render_fingerprint.py --compare /tmp/before.json  # diff against a saved run

Exit codes: ``0`` written or identical, ``2`` from ``--compare`` when any frame
differs or the frame set changed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from idle_hours import path_resolution  # noqa: E402
from idle_hours import render_quote as rq  # noqa: E402

FROZEN_NOW = datetime.datetime(2026, 5, 19, 10, 0, 0)
DIAGS_STUB_SYSTEM_INFO = {"host": "idle-hours", "ip": "192.0.2.42", "uptime": "6d 4h 12m"}

QUOTES = {
    "hero": ("It was five minutes to nine.", "five minutes to nine"),
    "standard": (
        "At five minutes to nine the bell rang, and the whole house, which had been "
        "waiting for it since breakfast, went quiet at once.",
        "five minutes to nine",
    ),
    "dense": (
        "It was five minutes to nine when she came down at last, and the room, which "
        "had been arguing about the weather and the war and the price of coal for "
        "the better part of an hour, fell silent; nobody could afterwards say why, "
        "only that the clock seemed louder than it had any right to be.",
        "five minutes to nine",
    ),
}
TIMES = ("08:55", "00:05")
MODES = ("production", "debug")


def _row(display_quote: str, matched_text: str, **overrides) -> dict:
    row = {
        "display_quote": display_quote,
        "matched_text": matched_text,
        "author": "Jane Austen",
        "title": "Mansfield Park",
        "bucket": "h9_five_to",
        "resolved_bucket": "h9_five_to",
        "used_fallback": False,
        "quality_score": 80,
        "source_id": "141",
        "line_number": 482,
    }
    row.update(overrides)
    return row


@contextlib.contextmanager
def _pinned_inputs():
    original_now = rq.clock.now
    original_diags = rq._diags_system_info
    original_photo = os.environ.pop(path_resolution.PHOTO_PATH_ENV, None)
    rq.clock.now = lambda: FROZEN_NOW
    rq._diags_system_info = lambda: dict(DIAGS_STUB_SYSTEM_INFO)
    try:
        yield
    finally:
        rq.clock.now = original_now
        rq._diags_system_info = original_diags
        if original_photo is not None:
            os.environ[path_resolution.PHOTO_PATH_ENV] = original_photo


def _digest(image) -> str:
    image = image.convert("RGB")
    head = f"{image.size[0]}x{image.size[1]}:".encode()
    return hashlib.sha256(head + image.tobytes()).hexdigest()


def fingerprint_theme(theme: str) -> dict[str, str]:
    """Every frame hash for one theme, keyed by a stable scenario name."""
    out: dict[str, str] = {}
    with _pinned_inputs():
        for length, (quote, match) in QUOTES.items():
            for time_str in TIMES:
                for mode in MODES:
                    image = rq.render(time_str, _row(quote, match), 800, 480, mode=mode, theme=theme)
                    out[f"{theme}/{length}/{time_str}/{mode}"] = _digest(image)
        quote, match = QUOTES["standard"]
        image = rq.render("08:55", _row(quote, match), 400, 240, mode="production", theme=theme)
        out[f"{theme}/thumbnail"] = _digest(image)
        out[f"{theme}/sleep"] = _digest(rq.render_sleep_frame("22:00", 800, 480, theme=theme))
        image = rq.render("08:55", _row(quote, match), 800, 480, mode="card", theme=theme)
        out[f"{theme}/card"] = _digest(image)
        bare = _row(quote, match, author="", title="", bucket="h9_five_to",
                    resolved_bucket="h9_ten_to", used_fallback=True)
        image = rq.render("08:55", bare, 800, 480, mode="debug", theme=theme)
        out[f"{theme}/fallback-no-metadata"] = _digest(image)
    return out


def fingerprint(themes: list[str], jobs: int) -> dict[str, str]:
    result: dict[str, str] = {}
    if jobs <= 1:
        for theme in themes:
            result.update(fingerprint_theme(theme))
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as pool:
            for part in pool.map(fingerprint_theme, themes):
                result.update(part)
    return dict(sorted(result.items()))


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hash every theme's frames to prove a refactor is pixel-identical.")
    parser.add_argument("--theme", action="append", metavar="NAME", help="Theme to hash; repeatable. Defaults to all.")
    parser.add_argument("--output", help="Write the hashes to this JSON file.")
    parser.add_argument("--compare", metavar="JSON", help="Compare against a saved run instead of writing one.")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="Worker processes (default: CPU count).")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    themes = args.theme or sorted(rq.THEMES)
    unknown = sorted(set(themes) - set(rq.THEMES))
    if unknown:
        print(f"unknown theme(s): {', '.join(unknown)}", file=sys.stderr)
        return 1
    hashes = fingerprint(themes, args.jobs)

    if args.compare:
        with open(args.compare, encoding="utf-8") as handle:
            saved = json.load(handle)
        if args.theme:
            saved = {key: value for key, value in saved.items() if key.split("/", 1)[0] in themes}
        changed = sorted(key for key in hashes.keys() & saved.keys() if hashes[key] != saved[key])
        added = sorted(hashes.keys() - saved.keys())
        removed = sorted(saved.keys() - hashes.keys())
        for label, keys in (("changed", changed), ("new", added), ("missing", removed)):
            for key in keys:
                print(f"{label}: {key}")
        if changed or added or removed:
            return 2
        print(f"identical: {len(hashes)} frames across {len(themes)} themes")
        return 0

    text = json.dumps(hashes, indent=1, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"wrote {len(hashes)} frame hashes for {len(themes)} themes to {args.output}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
