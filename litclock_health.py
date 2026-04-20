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
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON summary instead of the human-readable text. Handy for cron/systemd checks.",
    )
    parser.add_argument(
        "--fail-if-no-renders",
        action="store_true",
        help=(
            "Exit 2 if the window contains zero successful renders (default: only fail when "
            "there are errors AND no renders). Use on active appliances where silence itself "
            "indicates a problem."
        ),
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


def find_telemetry_files(base: Path, since: dt.datetime | None = None) -> list[Path]:
    """Return all telemetry files we should read for a given base path.

    ``run_clock.append_telemetry`` rotates by date, writing to
    ``<stem>-YYYYMMDD<suffix>`` in ``base.parent``. This helper globs for
    those siblings plus the legacy unsuffixed file at ``base`` itself (so
    telemetry written before rotation landed still summarises cleanly).

    When ``since`` is provided, date-suffixed files older than ``since`` are
    pruned by filename alone — no need to open and parse a week of old
    JSONL just to discard it.
    """
    candidates: list[Path] = []
    if base.exists() and base.is_file():
        candidates.append(base)
    parent = base.parent
    if not parent.exists():
        return candidates
    stem = base.stem
    suffix = base.suffix or ".jsonl"
    # Filenames use the appliance's local date (append_telemetry uses date.today());
    # `since` is UTC. A timezone east or west of UTC can shift the local date by ±1
    # day relative to the UTC date at any instant, so subtract a full day of slack
    # before pruning. Otherwise west-of-UTC hosts near midnight UTC would prune the
    # currently-active file (e.g. 20:30 local in UTC-7 → UTC date is tomorrow, local
    # filename says today → file_date < cutoff_date → active file dropped → false
    # "0 renders"). The per-entry ts filter in load_entries handles the slack case.
    cutoff_date = (since.date() - dt.timedelta(days=1)) if since is not None else None
    for sibling in sorted(parent.glob(f"{stem}-*{suffix}")):
        if not sibling.is_file():
            continue
        date_part = sibling.stem[len(stem) + 1:]
        try:
            file_date = dt.datetime.strptime(date_part, "%Y%m%d").date()
        except ValueError:
            # Sibling matches the glob (e.g. telemetry-backup.jsonl) but isn't
            # a date-rotated file. Skip it — including it would mean we'd
            # re-parse arbitrary unrelated JSONL on every health check.
            # Operators who want those summarised should point --telemetry-path
            # at the file directly.
            continue
        if cutoff_date is not None and file_date < cutoff_date:
            continue
        candidates.append(sibling)
    return candidates


def load_entries(path: Path, since: dt.datetime) -> list[dict]:
    """Stream JSONL entries with ts >= since across all rotated telemetry files.

    Malformed lines are skipped. Files are read in sorted-filename order so
    callers that care about ordering (e.g. ``last_error``) get deterministic
    behaviour across day boundaries.
    """
    rows: list[dict] = []
    for candidate in find_telemetry_files(path, since=since):
        with candidate.open(encoding="utf-8") as handle:
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


def evaluate_health(summary: dict, *, fail_if_no_renders: bool) -> int:
    """Map a summary dict to a process exit code.

    - ``0``: healthy (there are renders, or nothing unhealthy happened)
    - ``2``: unhealthy — errors but no successful renders, or
      ``--fail-if-no-renders`` was set and the window was silent.
    """
    if summary["error_count"] > 0 and summary["render_count"] == 0:
        return 2
    if fail_if_no_renders and summary["render_count"] == 0:
        return 2
    return 0


def main() -> int:
    args = parse_args()
    path = Path(args.telemetry_path).expanduser()
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=args.hours)
    entries = load_entries(path, since)
    # Absence-of-data is distinct from "silent window": we only report "no telemetry log"
    # when there are genuinely zero candidate files (legacy or rotated) to read.
    if not entries and not find_telemetry_files(path):
        if args.json:
            print(json.dumps({"error": f"No telemetry log at {path}", "hours": args.hours}))
        else:
            print(f"No telemetry log at {path}", file=sys.stderr)
        return 1
    summary = summarise(entries)
    if args.json:
        print(json.dumps({"hours": args.hours, **summary}))
    else:
        print(format_summary(summary, args.hours))
    return evaluate_health(summary, fail_if_no_renders=args.fail_if_no_renders)


if __name__ == "__main__":
    raise SystemExit(main())
