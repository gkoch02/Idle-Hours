"""Timestamped stdout/stderr logger shared by the runtime modules.

Extracted from :mod:`run_clock` so telemetry, state, theme, quiet-hours, and
action helpers can emit log lines without pulling the whole orchestrator in.
``run_clock._log`` is preserved as a re-export for backwards compatibility
(tests and ``web_server`` reference that spelling).
"""
from __future__ import annotations

import datetime as dt
import sys


def _log(msg: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    print(f"[{dt.datetime.now().isoformat(timespec='seconds')}] {msg}", file=stream, flush=True)
