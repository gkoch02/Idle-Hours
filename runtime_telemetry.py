"""Date-rotated JSONL telemetry sidecar with retention pruning.

``append_telemetry`` writes one JSON line per render/error event to a
date-suffixed sibling of the configured base path so long-running appliances
don't accumulate an unbounded file. ``prune_telemetry`` drops date-suffixed
siblings older than the retention window. Extracted from :mod:`run_clock`;
``run_clock`` re-exports these names.

Note: ``_maybe_prune_telemetry`` (the loop-glue "prune once per local-date
rollover" wrapper that consults ``RuntimeState.last_pruned_date``) stays in
:mod:`run_clock` so test monkeypatching of ``run_clock.prune_telemetry``
flows through the re-exported name.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import re
from pathlib import Path

from runtime_log import _log

DEFAULT_TELEMETRY_PATH = "~/.litclock/telemetry.jsonl"
DEFAULT_TELEMETRY_RETAIN_DAYS = 90
# Matches ``daily_telemetry_path``'s suffix format: stem-YYYYMMDD. We use a
# glob and then a stricter fullmatch regex so an operator pointing --telemetry
# -path at a hand-named file can't accidentally catch unrelated siblings.
_TELEMETRY_DATE_RE = re.compile(r"^(.+)-(\d{8})$")


def daily_telemetry_path(base: Path, today: dt.date | None = None) -> Path:
    """Return the date-suffixed sibling of ``base`` for ``today``.

    Given ``~/.litclock/telemetry.jsonl`` and 2026-04-20, returns
    ``~/.litclock/telemetry-20260420.jsonl``. This is how we rotate telemetry
    by date so a multi-year-running appliance doesn't accumulate a single
    unbounded JSONL file that eventually chokes ``litclock_health.py`` and
    stalls append latency. Local date (not UTC) so an operator's ``grep`` /
    ``ls`` groups entries by their wall-clock day.
    """
    if today is None:
        today = dt.date.today()
    suffix = base.suffix or ".jsonl"
    return base.with_name(f"{base.stem}-{today.strftime('%Y%m%d')}{suffix}")


def append_telemetry(telemetry_path: str | None, entry: dict) -> None:
    """Append one JSON line to today's telemetry log. No-op when disabled.

    Rotates by date: writes to ``<base-stem>-YYYYMMDD<suffix>`` in the base
    path's directory so the file size stays bounded. ``litclock_health.py``
    globs the directory for date-suffixed siblings (plus any legacy
    unsuffixed file) so older entries are still summarised.

    Telemetry is best-effort: an I/O failure here (unwritable path, full
    disk, path is a directory) must never surface to the caller, since this
    is called from the loop's error-recovery path — turning telemetry into
    a fatal failure mode would defeat its purpose.
    """
    if not telemetry_path:
        return
    try:
        base = Path(telemetry_path).expanduser()
        path = daily_telemetry_path(base)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **entry}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
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
