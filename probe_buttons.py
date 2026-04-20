#!/usr/bin/env python3
"""Standalone GPIO press probe for the Inky Impression.

Run on the Pi and press each physical button in turn. Each press prints a
timestamped line showing which GPIO pin fired, so you can verify the wiring
before blaming ``inky_buttons.BUTTON_GPIO``.

Usage:
    python3 probe_buttons.py
    python3 probe_buttons.py --pins 5 6 16 24 17 13 26  # custom pin set

The default candidate set is the standard Inky Impression pins (5, 6, 16, 24)
plus a handful of common alternates (13, 17, 26) in case your panel variant
wires its buttons somewhere else. Pins actively used by the Inky display
(SPI 8-11, BUSY 17 on some variants, DC/RESET) are deliberately skipped from
the defaults — override with ``--pins`` if you want to probe them anyway.
"""
from __future__ import annotations

import argparse
import datetime as dt
import signal
import sys

DEFAULT_PINS = [5, 6, 16, 24, 13, 26]


def _log(msg: str) -> None:
    print(f"[{dt.datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--pins",
        type=int,
        nargs="+",
        default=DEFAULT_PINS,
        help=f"GPIO BCM pin numbers to probe (default: {DEFAULT_PINS}).",
    )
    parser.add_argument(
        "--pull-down",
        action="store_true",
        help="Attach with pull_up=False (active-high buttons). Default is pull_up=True.",
    )
    parser.add_argument(
        "--bounce",
        type=float,
        default=0.05,
        help="Debounce window in seconds (default: 0.05 — low so the probe is responsive).",
    )
    args = parser.parse_args(argv)

    try:
        from gpiozero import Button
    except ImportError as exc:
        print(f"gpiozero not available: {exc}. Install with `pip install gpiozero` (+ lgpio on Pi 5).", file=sys.stderr)
        return 1

    buttons = []
    for pin in args.pins:
        try:
            btn = Button(pin, pull_up=not args.pull_down, bounce_time=args.bounce)
            btn.when_pressed = lambda p=pin: _log(f"GPIO {p}: PRESSED")
            btn.when_released = lambda p=pin: _log(f"GPIO {p}: released")
            buttons.append(btn)
            _log(f"listening on GPIO {pin}")
        except Exception as exc:
            _log(f"GPIO {pin}: attach FAILED ({exc!r})")

    if not buttons:
        print("No pins attached. Aborting.", file=sys.stderr)
        return 1

    _log("Ready. Press each physical button on the Inky panel. Ctrl-C to quit.")
    try:
        signal.pause()
    except KeyboardInterrupt:
        _log("Exiting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
