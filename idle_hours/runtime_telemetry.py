"""Date-rotated JSONL telemetry sidecar with retention pruning.

``append_telemetry`` writes one JSON line per render/error event to a
date-suffixed sibling of the configured base path so long-running appliances
don't accumulate an unbounded file. ``prune_telemetry`` drops date-suffixed
siblings older than the retention window. Extracted from :mod:`run_clock`.

``_maybe_prune_telemetry`` (the loop glue that prunes once per local-date
rollover, gated on ``RuntimeState.last_pruned_date``) stays in :mod:`run_clock`.
Callers read these names through this module, so a test patches
``runtime_telemetry.prune_telemetry`` or ``runtime_telemetry.append_telemetry``.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
from pathlib import Path

from idle_hours import runtime_webhook
from idle_hours.runtime_log import _log

DEFAULT_TELEMETRY_PATH = "~/.idle-hours/telemetry.jsonl"
DEFAULT_TELEMETRY_RETAIN_DAYS = 90
# Matches ``daily_telemetry_path``'s suffix format: stem-YYYYMMDD. We use a
# glob and then a stricter fullmatch regex so an operator pointing --telemetry
# -path at a hand-named file can't accidentally catch unrelated siblings.
_TELEMETRY_DATE_RE = re.compile(r"^(.+)-(\d{8})$")


def daily_telemetry_path(base: Path, today: dt.date | None = None) -> Path:
    """Return the date-suffixed sibling of ``base`` for ``today``.

    Given ``~/.idle-hours/telemetry.jsonl`` and 2026-04-20, returns
    ``~/.idle-hours/telemetry-20260420.jsonl``. This is how we rotate telemetry
    by date so a multi-year-running appliance doesn't accumulate a single
    unbounded JSONL file that eventually chokes ``idle_hours_health.py`` and
    stalls append latency. Local date (not UTC) so an operator's ``grep`` /
    ``ls`` groups entries by their wall-clock day.
    """
    if today is None:
        today = dt.date.today()
    suffix = base.suffix or ".jsonl"
    return base.with_name(f"{base.stem}-{today.strftime('%Y%m%d')}{suffix}")


def append_heartbeat(telemetry_path: str | None, *, quiet: bool | None = None) -> None:
    """Emit a ``type="heartbeat"`` liveness marker, without fsync or webhook.

    Heartbeats answer "is the loop alive?", so the health summariser keeps
    them out of ``render_count`` / ``error_count``. They fire about once a
    minute: losing the last few to a power cut is recoverable, so they skip
    the fsync that bounds SD-card wear, and alerting on each would be spam.
    ``quiet`` stamps whether the loop was in its quiet window, which keeps
    "asleep" legible in a health window narrower than the blackout; ``None``
    omits the field. See docs/runtime.md (telemetry, quiet-hours health).
    """
    entry: dict = {"type": "heartbeat"}
    if quiet is not None:
        entry["quiet"] = bool(quiet)
    _append_entry(telemetry_path, entry, fsync=False)


def append_telemetry(telemetry_path: str | None, entry: dict) -> None:
    """Append one fsync'd JSON line to today's date-rotated telemetry file.

    Best-effort: it runs on the loop's error-recovery path, so an I/O
    failure is logged and dropped, never raised. The fsync is what keeps
    the last render or error entry readable by ``idle_hours_health`` after
    a power cut. An entry that passes ``runtime_webhook``'s alert filter is
    also POSTed, on a daemon thread, when a webhook is configured. Rotation,
    fsync and retention: docs/runtime.md.
    """
    # Stamp ``ts`` once so the file line and the webhook payload carry the
    # same timestamp (issue #281).
    # An explicit ``ts`` on the caller's entry wins, as it does in the file.
    entry = {"ts": _now_ts(), **entry}
    _append_entry(telemetry_path, entry, fsync=True)
    url, all_events = runtime_webhook.get_config()
    if url:
        runtime_webhook.post_event(url, entry, send_all=all_events)


def _now_ts() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _append_entry(telemetry_path: str | None, entry: dict, *, fsync: bool) -> None:
    if not telemetry_path:
        return
    try:
        base = Path(telemetry_path).expanduser()
        path = daily_telemetry_path(base)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"ts": _now_ts(), **entry}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            if fsync:
                handle.flush()
                os.fsync(handle.fileno())
    except (OSError, TypeError, ValueError) as exc:
        _log(f"telemetry write to {telemetry_path!r} failed, dropping entry: {exc!r}", err=True)


def prune_telemetry(telemetry_path: str | None, retain_days: int, today: dt.date | None = None) -> int:
    """Delete date-rotated telemetry siblings older than ``retain_days``. Returns count deleted.

    ``daily_telemetry_path`` rotates per local date so each file stays bounded,
    but without a retention sweep the directory grows unbounded over months.
    We glob the base path's directory for ``<stem>-YYYYMMDD<suffix>`` siblings
    (using a stricter regex than the glob so a hand-named file with a numeric
    stem isn't mistaken for rotation output), parse the date suffix, and
    ``unlink`` anything older than today minus ``retain_days``.

    Defensive: swallows every per-file exception so one unreadable sibling
    can't block pruning of the rest; returns the count of successful unlinks
    for observability. A zero-or-negative retain_days disables pruning.
    """
    if not telemetry_path or retain_days <= 0:
        return 0
    if today is None:
        today = dt.date.today()
    cutoff = today - dt.timedelta(days=retain_days)
    try:
        base = Path(telemetry_path).expanduser()
        parent = base.parent
        if not parent.exists():
            return 0
        stem = base.stem
        suffix = base.suffix or ".jsonl"
        pattern = f"{stem}-*{suffix}"
        removed = 0
        for candidate in parent.glob(pattern):
            match = _TELEMETRY_DATE_RE.fullmatch(candidate.stem)
            if match is None or match.group(1) != stem:
                continue
            try:
                file_date = dt.datetime.strptime(match.group(2), "%Y%m%d").date()
            except ValueError:
                continue
            if file_date < cutoff:
                with contextlib.suppress(OSError):
                    candidate.unlink()
                    removed += 1
        return removed
    except OSError as exc:
        _log(f"telemetry prune failed for {telemetry_path!r}: {exc!r}", err=True)
        return 0
