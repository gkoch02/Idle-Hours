"""Quiet-hours detection and static-image display bridge.

``in_quiet_hours`` decides whether a given wall-clock time falls in the
configured blackout window (overnight ranges supported). ``_display_quiet_image``
copies a PNG to the output path and optionally pushes it via a display script
— used for quiet hours, the startup frame, and the button-D long-press
shutdown preamble. Extracted from :mod:`run_clock`; the original names are
re-exported from ``run_clock`` so existing tests and callers keep resolving.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from runtime_log import _log

# Resolves to the repo root (same directory as run_clock.py) since all runtime
# modules live alongside each other. Matches run_clock.BASE_DIR exactly.
BASE_DIR = Path(__file__).resolve().parent


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


def _display_quiet_image(
    quiet_image: str,
    output: str,
    display_script: str | None,
    *,
    reason: str = "quiet hours",
) -> None:
    """Copy ``quiet_image`` to ``output`` and optionally push it to the display script.

    ``reason`` is the label prefixed to the log message so the same helper can serve
    the quiet-hours entry, the startup frame, and the button-D long-press
    shutdown preamble without lying about why it ran.
    """
    quiet_path = Path(quiet_image) if Path(quiet_image).is_absolute() else (BASE_DIR / quiet_image).resolve()
    output_resolved = str((BASE_DIR / output).resolve()) if not Path(output).is_absolute() else output
    shutil.copy2(str(quiet_path), output_resolved)
    _log(f"{reason}: {quiet_path.name} -> {output_resolved}")
    if display_script:
        display_path = str((BASE_DIR / display_script).resolve()) if not Path(display_script).is_absolute() else display_script
        subprocess.check_call([sys.executable, display_path, output_resolved])
        _log(f"Displayed {output_resolved} via {display_path}")
