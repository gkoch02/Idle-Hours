#!/usr/bin/env python3
"""Summarise the LitClock runtime telemetry log.

``run_clock.py`` writes one JSONL entry per render attempt to
``~/.litclock/telemetry.jsonl``. This script reads the last N hours and prints
render counts, error counts, and render-latency percentiles so the appliance can
be inspected without ``journalctl`` spelunking.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

DEFAULT_TELEMETRY_PATH = "~/.litclock/telemetry.jsonl"
DEFAULT_HOURS = 24


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarise LitClock telemetry.")
    parser.add_argument(
        "--telemetry-path",
        default=DEFAULT_TELEMETRY_PATH,
        help="JSONL log written by run_clock.py (default: ~/.litclock/telemetry.jsonl)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=DEFAULT_HOURS,
        help="Window of recent hours to consider (default: 24)",
    )
    return parser.parse_args()


def _percentile(sorted_values: list[int], p: float) -> int | None:
    """Linear-interpolation percentile over a sorted list. Returns None when empty."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (p / 100) * (len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return int(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac)


def load_entries(path: Path, since: dt.datetime) -> list[dict]:
    """Stream JSONL entries with ts >= since. Malformed lines are skipped."""
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = dt.datetime.fromisoformat(entry["ts"])
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.timezone.utc)
            if ts < since:
                continue
            rows.append(entry)
    return rows


def summarise(entries: list[dict]) -> dict:
    renders = [e for e in entries if "error" not in e]
    errors = [e for e in entries if "error" in e]
    render_latencies = sorted(
        e["render_ms"] for e in renders if isinstance(e.get("render_ms"), int)
    )
    display_latencies = sorted(
        e["display_ms"] for e in renders if isinstance(e.get("display_ms"), int)
    )
    return {
        "render_count": len(renders),
        "error_count": len(errors),
        "render_p50_ms": _percentile(render_latencies, 50),
        "render_p95_ms": _percentile(render_latencies, 95),
        "display_p50_ms": _percentile(display_latencies, 50),
        "display_p95_ms": _percentile(display_latencies, 95),
        "last_error": errors[-1].get("error") if errors else None,
    }


def format_summary(summary: dict, hours: int) -> str:
    parts = [
        f"Last {hours}h: {summary['render_count']} renders, {summary['error_count']} errors",
    ]
    if summary["render_p50_ms"] is not None:
        parts.append(
            f"render latency p50 {summary['render_p50_ms']}ms / p95 {summary['render_p95_ms']}ms"
        )
    if summary["display_p50_ms"] is not None:
        parts.append(
            f"display latency p50 {summary['display_p50_ms']}ms / p95 {summary['display_p95_ms']}ms"
        )
    if summary["last_error"]:
        parts.append(f"last error: {summary['last_error']}")
    return "\n".join(parts)


def main() -> int:
    args = parse_args()
    path = Path(args.telemetry_path).expanduser()
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=args.hours)
    entries = load_entries(path, since)
    if not entries and not path.exists():
        print(f"No telemetry log at {path}", file=sys.stderr)
        return 1
    summary = summarise(entries)
    print(format_summary(summary, args.hours))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
