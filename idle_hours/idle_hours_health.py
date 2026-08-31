#!/usr/bin/env python3
"""Summarise the Idle Hours runtime telemetry log.

``run_clock.py`` writes one JSONL entry per render attempt to
``~/.idle-hours/telemetry.jsonl``. This script reads the last N hours and prints
render counts, error counts, and render-latency percentiles so the appliance can
be inspected without ``journalctl`` spelunking.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

DEFAULT_TELEMETRY_PATH = "~/.idle-hours/telemetry.jsonl"
DEFAULT_HOURS = 24


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarise Idle Hours telemetry.")
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Path to the same TOML config file run_clock uses. Reads "
            "'telemetry_path' from it so the documented appliance deployment "
            "(which relocates telemetry under /var/lib/idle-hours) summarises "
            "without restating the path. An explicit --telemetry-path wins."
        ),
    )
    parser.add_argument(
        "--telemetry-path",
        default=DEFAULT_TELEMETRY_PATH,
        help="JSONL log written by run_clock.py (default: ~/.idle-hours/telemetry.jsonl)",
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
    parser.add_argument(
        "--max-heartbeat-age-minutes",
        type=int,
        default=None,
        help=(
            "Exit 2 if no loop-heartbeat telemetry entry appears within this many minutes. "
            "Heartbeats are emitted once per ~60s by run_clock regardless of whether the "
            "panel is refreshing, so this distinguishes 'idle but alive' from 'wedged'. "
            "Default: disabled."
        ),
    )
    parser.add_argument(
        "--max-render-age-minutes",
        type=int,
        default=None,
        help=(
            "Exit 2 if the panel hasn't rendered within this many minutes. Symmetric with "
            "--max-heartbeat-age-minutes, but answers a different question: a loop stuck in "
            "perpetual dedup-skip or render backoff keeps heartbeating while the panel goes "
            "stale. Pick a cap comfortably above your longest expected quiet window. "
            "Default: disabled."
        ),
    )
    parser.add_argument(
        "--actions-only",
        action="store_true",
        help=(
            "Emit an operator-centric 'what did the user do?' report instead of the full "
            "health summary: action counts by type (skip/theme/quiet/...), press-dropped "
            "count, web_auth_fail count, quiet-window count, and last action timestamp. "
            "Combine with --json for machine-readable output."
        ),
    )
    # Same three-layer precedence run_clock uses (CLI flag > config value >
    # argparse default), and the same mechanism: argparse consults a default
    # only when the flag is absent from argv, so feeding config values through
    # set_defaults gets the ordering right with no bespoke merge layer.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=None)
    pre_args, _ = pre.parse_known_args()
    if pre_args.config:
        from idle_hours import runtime_config
        config = runtime_config.load_config(Path(pre_args.config).expanduser())
        if config.get("telemetry_path"):
            parser.set_defaults(telemetry_path=config["telemetry_path"])
    return parser.parse_args()


def _is_int_metric(value) -> bool:
    """True for a real integer latency value, excluding ``bool``.

    ``bool`` is an ``int`` subclass, so a corrupt/hand-edited telemetry entry
    like ``{"render_ms": true}`` would otherwise pass a bare ``isinstance(...,
    int)`` check and be counted as a render with latency 1, skewing both the
    render count and the percentile latencies.
    """
    return isinstance(value, int) and not isinstance(value, bool)


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
    # Heartbeat entries answer "is the loop alive?" and are counted
    # separately from render/error tallies so a silent-but-alive appliance
    # doesn't look like "0 renders, 0 errors" when it's actually fine.
    heartbeats = [e for e in entries if e.get("type") == "heartbeat"]
    non_heartbeats = [e for e in entries if e.get("type") != "heartbeat"]
    # Operator-activity entries emitted by runtime_actions / _button_render_gate
    # / web_server. Tracked separately so a burst of button presses doesn't
    # inflate render_count and so "what did the user do?" queries have a
    # single source of truth.
    actions = [e for e in non_heartbeats if e.get("mode") == "action"]
    press_dropped = [e for e in non_heartbeats if e.get("mode") == "press_dropped"]
    web_auth_fails = [e for e in non_heartbeats if e.get("mode") == "web_auth_fail"]
    web_errors = [e for e in non_heartbeats if e.get("mode") == "web_error"]
    quiet_enters = [e for e in non_heartbeats if e.get("mode") == "quiet_enter"]
    quiet_exits = [e for e in non_heartbeats if e.get("mode") == "quiet_exit"]
    # Which side of the quiet window are we on? (#232) The loop deliberately
    # renders nothing between ``quiet_enter`` and ``quiet_exit``, so render age
    # is not a meaningful signal there — but the staleness gate had no way to
    # know that and flagged every night of a healthy appliance. Entries are
    # append-ordered, so the *last* quiet marker in the stream decides: an
    # enter means the window is still open. Deciding by position rather than
    # by parsing both timestamps keeps this working on an entry whose ``ts``
    # is malformed.
    last_quiet_mode: str | None = None
    last_quiet_ts: str | None = None
    for entry in non_heartbeats:
        mode = entry.get("mode")
        if mode in ("quiet_enter", "quiet_exit"):
            last_quiet_mode = mode
            last_quiet_ts = entry.get("ts")
    quiet_active = last_quiet_mode == "quiet_enter"
    quiet_since = last_quiet_ts if quiet_active else None
    last_quiet_exit_ts = last_quiet_ts if last_quiet_mode == "quiet_exit" else None
    # Positively identify renders by the ``render_ms`` field — only set by
    # ``run_clock.render_now`` on a successful render subprocess. Defining
    # renders as "anything without an error" miscategorises modes like
    # ``"backoff"`` (emitted by ``_record_render_failure`` without an error
    # field) as successful renders, which would let a wedged appliance
    # report healthy as long as it was tripping the backoff threshold.
    renders = [e for e in non_heartbeats if _is_int_metric(e.get("render_ms"))]
    # Exclude structured action / web / quiet markers from the generic
    # error tally even if they carry an ``error`` field — they have their
    # own dedicated counts below and a failed skip action doesn't mean the
    # render pipeline itself is unhealthy.
    error_modes_excluded = {"action", "web_error", "web_auth_fail"}
    errors = [
        e for e in non_heartbeats
        if "error" in e and e.get("mode") not in error_modes_excluded
    ]
    render_latencies = sorted(e["render_ms"] for e in renders)
    display_latencies = sorted(
        e["display_ms"] for e in renders if _is_int_metric(e.get("display_ms"))
    )
    last_heartbeat_ts: str | None = None
    if heartbeats:
        # Heartbeats are ordered by telemetry-file-then-line, which is wall-clock
        # order since ``append_telemetry`` always appends. The final entry's ts
        # is the most recent heartbeat.
        last_heartbeat_ts = heartbeats[-1].get("ts")
    # Break actions down by verb so the summary reads as
    # "5 theme toggles, 2 skips" instead of a bare "7 actions". Use
    # ``or "unknown"`` so both a missing key and a null value fall into
    # the same bucket (a malformed entry with ``"action": null`` would
    # otherwise produce an ``"None"`` column).
    actions_by_type: dict[str, int] = {}
    for entry in actions:
        name = str(entry.get("action") or "unknown")
        actions_by_type[name] = actions_by_type.get(name, 0) + 1
    last_action_ts = actions[-1].get("ts") if actions else None
    # "When did the panel last actually render?" is the single most
    # operator-relevant timestamp, and it was the one the summary didn't
    # carry: a loop wedged in perpetual dedup-skip or render backoff keeps
    # heartbeating, so heartbeat age reads healthy while the panel goes
    # stale, and a 24h render count is only a coarse proxy. Entries are
    # append-ordered, so the last render's ts is the most recent.
    last_render_ts = renders[-1].get("ts") if renders else None
    return {
        "render_count": len(renders),
        "last_render_ts": last_render_ts,
        "error_count": len(errors),
        "heartbeat_count": len(heartbeats),
        "last_heartbeat_ts": last_heartbeat_ts,
        "render_p50_ms": _percentile(render_latencies, 50),
        "render_p95_ms": _percentile(render_latencies, 95),
        "display_p50_ms": _percentile(display_latencies, 50),
        "display_p95_ms": _percentile(display_latencies, 95),
        "last_error": errors[-1].get("error") if errors else None,
        "action_count": len(actions),
        "actions_by_type": actions_by_type,
        "last_action_ts": last_action_ts,
        "press_dropped_count": len(press_dropped),
        "web_auth_fail_count": len(web_auth_fails),
        "web_error_count": len(web_errors),
        "quiet_enter_count": len(quiet_enters),
        "quiet_exit_count": len(quiet_exits),
        "quiet_active": quiet_active,
        "quiet_since": quiet_since,
        "last_quiet_exit_ts": last_quiet_exit_ts,
    }


def format_summary(summary: dict, hours: int) -> str:
    parts = [
        f"Last {hours}h: {summary['render_count']} renders, {summary['error_count']} errors",
    ]
    if summary.get("last_render_ts"):
        parts.append(f"last render: {summary['last_render_ts']}")
    if summary.get("heartbeat_count"):
        last_hb = summary.get("last_heartbeat_ts") or "?"
        parts.append(f"{summary['heartbeat_count']} heartbeats (last {last_hb})")
    if summary["render_p50_ms"] is not None:
        parts.append(
            f"render latency p50 {summary['render_p50_ms']}ms / p95 {summary['render_p95_ms']}ms"
        )
    if summary["display_p50_ms"] is not None:
        parts.append(
            f"display latency p50 {summary['display_p50_ms']}ms / p95 {summary['display_p95_ms']}ms"
        )
    # Action breakdown: always show the header when any operator activity
    # occurred so silent windows (0 actions) don't pad the summary.
    if summary.get("action_count"):
        actions_by_type = summary.get("actions_by_type") or {}
        breakdown = ", ".join(
            f"{name} {count}" for name, count in sorted(actions_by_type.items())
        ) or "—"
        last_action = summary.get("last_action_ts") or "?"
        parts.append(f"{summary['action_count']} actions ({breakdown}; last {last_action})")
    if summary.get("press_dropped_count"):
        parts.append(f"{summary['press_dropped_count']} presses dropped (render in flight)")
    if summary.get("web_auth_fail_count"):
        parts.append(f"{summary['web_auth_fail_count']} web auth failures")
    if summary.get("web_error_count"):
        parts.append(f"{summary['web_error_count']} web POST errors")
    if summary.get("quiet_active"):
        # Say so explicitly: a reader seeing "0 renders" plus a stale-looking
        # last-render timestamp should be told the appliance is asleep on
        # purpose, not left to infer it from the enter/exit counts below.
        parts.append(f"quiet hours ACTIVE since {summary.get('quiet_since') or '?'}")
    if summary.get("quiet_enter_count") or summary.get("quiet_exit_count"):
        parts.append(
            f"quiet hours: {summary.get('quiet_enter_count', 0)} enters, "
            f"{summary.get('quiet_exit_count', 0)} exits"
        )
    if summary["last_error"]:
        parts.append(f"last error: {summary['last_error']}")
    if summary.get("stale_heartbeat"):
        parts.append("WARNING: heartbeat is stale — loop may be wedged")
    if summary.get("stale_render"):
        parts.append("WARNING: last render is stale — panel may be showing an old frame")
    return "\n".join(parts)


def format_actions_summary(summary: dict, hours: int) -> str:
    """Render the ``--actions-only`` view.

    Operator-centric "what did the user do?" report. Omits render / latency
    fields, which are covered by the default summary. Always prints every
    counter (including zeros) so cron / grep output is shape-stable.
    """
    actions_by_type = summary.get("actions_by_type") or {}
    breakdown = (
        ", ".join(f"{name} {count}" for name, count in sorted(actions_by_type.items()))
        if actions_by_type else "none"
    )
    last_action = summary.get("last_action_ts") or "never"
    return "\n".join([
        f"Last {hours}h — operator activity:",
        f"  actions: {summary.get('action_count', 0)} ({breakdown})",
        f"  last action: {last_action}",
        f"  presses dropped: {summary.get('press_dropped_count', 0)}",
        f"  web auth failures: {summary.get('web_auth_fail_count', 0)}",
        f"  web POST errors: {summary.get('web_error_count', 0)}",
        f"  quiet hours: {summary.get('quiet_enter_count', 0)} enters / "
        f"{summary.get('quiet_exit_count', 0)} exits",
    ])


def _is_stale(
    summary: dict, field: str, max_age_minutes: int, now: dt.datetime | None = None
) -> bool:
    """Return True when ``summary[field]`` is missing, unparseable, or too old.

    A missing timestamp counts as stale: an appliance that has been running
    long enough for the summary window to populate but has recorded no
    heartbeat (or no render) is either running pre-telemetry code or wedged
    before the first emit — same flag, same exit code either way.
    """
    last = summary.get(field)
    if not last:
        return True
    try:
        last_dt = dt.datetime.fromisoformat(last)
    except (TypeError, ValueError):
        return True
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=dt.timezone.utc)
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)
    return (now - last_dt) > dt.timedelta(minutes=max_age_minutes)


def is_heartbeat_stale(summary: dict, max_age_minutes: int, now: dt.datetime | None = None) -> bool:
    """Return True when the most recent heartbeat is older than ``max_age_minutes``."""
    return _is_stale(summary, "last_heartbeat_ts", max_age_minutes, now)


def _parse_ts(value: object) -> dt.datetime | None:
    """Parse an ISO-8601 telemetry timestamp, normalising naive values to UTC."""
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed


def render_staleness_reference(summary: dict) -> str | None:
    """Return the timestamp render age should actually be measured from.

    Normally that's the last render. But the loop is *entitled* not to render
    across a quiet window, so the age clock effectively restarts when the
    window closes: right after a 22:00–06:00 blackout the last render is 8
    hours old through no fault of the appliance, and measuring from it would
    trip the gate for the ~60s until the first post-quiet tick repaints.
    Taking the later of the two closes that gap without blunting the check —
    once a normal render lands, it is the later timestamp again.

    Returns ``None`` when neither timestamp exists, which
    :func:`is_render_stale` treats as stale (the pre-existing "missing counts
    as stale" rule).
    """
    candidates = [
        (_parse_ts(summary.get("last_render_ts")), summary.get("last_render_ts")),
        (_parse_ts(summary.get("last_quiet_exit_ts")), summary.get("last_quiet_exit_ts")),
    ]
    usable = [(parsed, raw) for parsed, raw in candidates if parsed is not None]
    if not usable:
        # Preserve the raw value (possibly unparseable) so _is_stale keeps
        # reporting "missing or unparseable → stale" for the render field.
        return summary.get("last_render_ts")
    return max(usable, key=lambda pair: pair[0])[1]


def is_render_stale(summary: dict, max_age_minutes: int, now: dt.datetime | None = None) -> bool:
    """Return True when the panel has gone too long without a repaint.

    Distinct from heartbeat staleness: the loop can be perfectly alive —
    heartbeating every 60s — while stuck in render backoff or a dedup-skip
    branch that never repaints. That combination is invisible to the
    heartbeat gate and is exactly the "panel is showing an old frame"
    condition an operator wants paged on.

    Quiet hours are the one case where *not* rendering is correct, and this
    gate used to fire right through them (#232): with the shipped 22:00–06:00
    defaults and the documented ``--max-render-age-minutes 90``, a healthy
    appliance failed the check from ~23:30 to 06:00 every single night — and
    an operator who also wired ``--webhook-url`` got paged for it. The
    threshold can't be tuned around that (an 8-hour window would need ~500
    minutes, which defeats the check by day), so the gate consults the
    ``quiet_enter`` / ``quiet_exit`` markers ``runtime_quiet`` already emits
    for exactly this purpose: while the window is open the gate is suppressed,
    and once it closes the age is measured from the later of the last render
    and the window's close.

    A wedge *during* quiet hours is still caught — by ``is_heartbeat_stale``
    while the window is open (heartbeats keep flowing through quiet hours,
    which is the whole point of them), and by this gate once the window closes
    and the appliance fails to resume rendering.
    """
    if summary.get("quiet_active"):
        return False
    reference = render_staleness_reference(summary)
    return _is_stale({"_ref": reference}, "_ref", max_age_minutes, now)


def evaluate_health(
    summary: dict,
    *,
    fail_if_no_renders: bool,
    max_heartbeat_age_minutes: int | None = None,
    max_render_age_minutes: int | None = None,
) -> int:
    """Map a summary dict to a process exit code.

    - ``0``: healthy (there are renders, or nothing unhealthy happened)
    - ``2``: unhealthy — errors but no successful renders;
      ``--fail-if-no-renders`` was set and the window was silent;
      ``--max-heartbeat-age-minutes`` was set and the most recent heartbeat
      is older than the cap (including the "never emitted" case); or
      ``--max-render-age-minutes`` was set and the panel hasn't rendered
      within the cap.

    Both render-related gates stand down while quiet hours are open (#232) —
    a window that lands inside the nightly blackout is *supposed* to be
    silent, and flagging it pages an operator for a working appliance. The
    heartbeat gate is unaffected: heartbeats keep flowing through quiet hours,
    so it remains the live "loop is wedged" signal for the whole window.
    """
    quiet_active = bool(summary.get("quiet_active"))
    if summary["error_count"] > 0 and summary["render_count"] == 0:
        return 2
    if fail_if_no_renders and summary["render_count"] == 0 and not quiet_active:
        return 2
    if max_heartbeat_age_minutes is not None and is_heartbeat_stale(summary, max_heartbeat_age_minutes):
        return 2
    if max_render_age_minutes is not None and is_render_stale(summary, max_render_age_minutes):
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
    if args.max_heartbeat_age_minutes is not None:
        summary["stale_heartbeat"] = is_heartbeat_stale(summary, args.max_heartbeat_age_minutes)
    if args.max_render_age_minutes is not None:
        summary["stale_render"] = is_render_stale(summary, args.max_render_age_minutes)
    if args.json:
        # --actions-only is a human-readability concern; the JSON already
        # contains every field either view consumes, so keep the payload
        # shape stable for scripts regardless of the flag.
        print(json.dumps({"hours": args.hours, **summary}))
    elif args.actions_only:
        print(format_actions_summary(summary, args.hours))
    else:
        print(format_summary(summary, args.hours))
    return evaluate_health(
        summary,
        fail_if_no_renders=args.fail_if_no_renders,
        max_heartbeat_age_minutes=args.max_heartbeat_age_minutes,
        max_render_age_minutes=args.max_render_age_minutes,
    )


if __name__ == "__main__":
    raise SystemExit(main())
