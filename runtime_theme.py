"""Theme resolution: auto-dark window, manual override, midnight reset.

``resolve_effective_theme`` merges the CLI ``--theme`` choice, the wall-clock
(for ``auto``), and the user's button-B manual override into the theme actually
passed to the renderer. ``_maybe_reset_manual_theme_at_midnight`` clears the
manual override on day rollover so ``auto`` resumes. Extracted from
:mod:`run_clock`; the original names are re-exported from ``run_clock`` so
existing call sites and test patches keep resolving.
"""
from __future__ import annotations

import datetime as dt

from runtime_log import _log
from runtime_state import RuntimeState

# Auto-theme: switch to dark theme during this window, default theme otherwise.
# Boundaries chosen to match civil twilight in temperate latitudes; users who want
# a tighter fit can pass --theme default or --theme dark explicitly.
AUTO_DARK_START_HOUR = 18
AUTO_DARK_END_HOUR = 6


def auto_theme_for(time_str: str) -> str:
    """Return 'dark' during the night window, 'default' otherwise."""
    hour = int(time_str.split(":", 1)[0])
    if AUTO_DARK_START_HOUR <= hour or hour < AUTO_DARK_END_HOUR:
        return "dark"
    return "default"


def resolve_effective_theme(theme_arg: str, time_str: str, manual_theme: str | None) -> str:
    """Resolve the theme actually passed to renderer/display.

    ``theme_arg`` is the CLI choice ('default'/'dark'/'auto'). ``manual_theme`` is the
    user's button-B override (set until midnight). When ``theme_arg == 'auto'`` and
    no manual override is active, derive from the wall clock.
    """
    if manual_theme in ("default", "dark"):
        return manual_theme
    if theme_arg == "auto":
        return auto_theme_for(time_str)
    return theme_arg


def _maybe_reset_manual_theme_at_midnight(args, state: RuntimeState) -> None:
    """Clear the manual theme override at the day boundary so 'auto' resumes."""
    import run_clock
    today = dt.date.today()
    with state.lock:
        if state.last_seen_date is None:
            state.last_seen_date = today
            return
        if today != state.last_seen_date and state.theme_arg == "auto" and state.manual_theme is not None:
            _log(f"midnight rollover: clearing manual theme override ({state.manual_theme})")
            state.manual_theme = None
            run_clock.save_runtime_state(args.state_path, state.snapshot_for_persistence())
        state.last_seen_date = today
