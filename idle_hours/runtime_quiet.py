"""Quiet-hours detection and state machine.

``in_quiet_hours`` decides whether a given wall-clock time falls in the
configured blackout window (overnight ranges supported). ``_display_quiet_image``
copies a PNG to the output path and optionally pushes it via a display script
— used for quiet hours, the startup frame, and the button-D long-press
shutdown preamble.

``compute_quiet`` / ``enter_quiet`` / ``exit_quiet`` are the three-step state
machine the main loop drives each tick. They were extracted out of the
``run_clock`` main loop body (and out of the inline ``last_bucket = None``
clear in ``runtime_actions.action_quiet``) so both code paths share one
definition of "what it means to enter / leave quiet hours".

``enter_quiet`` routes its ``_display_quiet_image`` and ``render_now`` calls
through ``run_clock.X`` (lazy ``import run_clock``) so the main-loop tests
that patch ``run_clock._display_quiet_image`` / ``run_clock.render_now``
continue to intercept the calls — same pattern ``runtime_actions`` uses.

Extracted from :mod:`run_clock`; the original names (``in_quiet_hours``,
``_display_quiet_image``) are re-exported from ``run_clock`` so existing tests
and callers keep resolving.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

from idle_hours.buckets import bucket_for_time
from idle_hours.runtime_log import _log
from idle_hours.runtime_state import RuntimeState
from idle_hours.runtime_theme import _auto_theme_kwargs, resolve_effective_theme

# Resolves to the repo root (same directory as run_clock.py) since all runtime
# modules live alongside each other. Matches run_clock.BASE_DIR exactly.
BASE_DIR = Path(__file__).resolve().parent

# Safety net on the Inky display push, mirroring ``run_clock.DISPLAY_TIMEOUT_SECONDS``.
# Kept local instead of imported because ``run_clock`` imports this module, so
# the dependency has to flow one way. If you change one, change the other —
# both bound the same external command (``display_inky.py``).
DISPLAY_TIMEOUT_SECONDS = 60


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
    telemetry_path: str | None = None,
) -> None:
    """Copy ``quiet_image`` to ``output`` and optionally push it to the display script.

    ``reason`` is the label prefixed to the log message so the same helper can serve
    the quiet-hours entry, the startup frame, and the button-D long-press
    shutdown preamble without lying about why it ran.

    ``telemetry_path``, when provided, is used to record a ``mode="display_timeout"``
    entry if the display subprocess exceeds ``DISPLAY_TIMEOUT_SECONDS`` — matches the
    contract the render/display paths in ``run_clock.render_now`` follow so operators
    can see quiet-image wedges in ``idle_hours_health.py`` summaries.
    """
    quiet_path = Path(quiet_image) if Path(quiet_image).is_absolute() else (BASE_DIR / quiet_image).resolve()
    output_resolved = str((BASE_DIR / output).resolve()) if not Path(output).is_absolute() else output
    shutil.copy2(str(quiet_path), output_resolved)
    _log(f"{reason}: {quiet_path.name} -> {output_resolved}")
    if display_script:
        display_path = str((BASE_DIR / display_script).resolve()) if not Path(display_script).is_absolute() else display_script
        try:
            subprocess.run(
                [sys.executable, display_path, output_resolved],
                check=True,
                timeout=DISPLAY_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            # ``subprocess.run`` killed the child before re-raising; surface
            # the timeout loudly but do not re-raise — the caller (quiet-hours
            # entry, startup frame, shutdown pre-frame) logs and moves on so
            # a wedged display doesn't prevent the rest of those flows.
            _log(f"{reason}: display push timed out after {DISPLAY_TIMEOUT_SECONDS}s: {exc!r}", err=True)
            # Lazy import so the telemetry helper stays a run_clock-visible
            # name for tests that patch run_clock.append_telemetry.
            from idle_hours import run_clock
            run_clock.append_telemetry(
                telemetry_path,
                {
                    "error": repr(exc),
                    "mode": "display_timeout",
                    "timeout_seconds": DISPLAY_TIMEOUT_SECONDS,
                    "reason": reason,
                },
            )
            return
        _log(f"Displayed {output_resolved} via {display_path}")


def compute_quiet(args: argparse.Namespace, state: RuntimeState, time_str: str) -> tuple[bool, bool]:
    """Return ``(now_quiet, manual_only)`` for the current tick.

    ``now_quiet`` is the OR of the scheduled-window check and
    ``state.manual_quiet``. ``manual_only`` is True when quiet comes purely
    from the manual toggle (used only to label the "quiet hours start" log
    line so the operator can tell a manual override apart from the normal
    22:00–06:00 window).
    """
    with state.lock:
        manual_quiet = state.manual_quiet
    scheduled_quiet = in_quiet_hours(
        time_str,
        None if args.quiet_off else args.quiet_start,
        args.quiet_end,
    )
    return (scheduled_quiet or manual_quiet, manual_quiet and not scheduled_quiet)


def enter_quiet(
    args: argparse.Namespace,
    state: RuntimeState,
    time_str: str,
    *,
    manual_only: bool = False,
) -> None:
    """Push the quiet-image (or fallback quiet-start render) to the panel.

    Wraps the push in ``state.render_lock`` so a racing button / web handler
    can't interleave their own render. A display failure is logged, traced,
    and recorded to the telemetry sidecar as ``mode="quiet"`` but never
    propagated — the loop's next tick will retry.
    """
    from idle_hours import run_clock  # lazy: avoids circular import, and keeps test patches on
                      # run_clock._display_quiet_image / run_clock.render_now working.
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    # bucket_for_time(time_str) rather than current_bucket() so tests that
    # only patch current_time_str don't also have to patch the wall clock.
    quiet_bucket = bucket_for_time(time_str)
    trigger = "manual" if manual_only else f"{args.quiet_start}–{args.quiet_end}"
    _log(f"quiet hours start ({trigger})")
    # Structured rising-edge marker so idle_hours_health can tell
    # "silent window because quiet" apart from "silent window because wedged";
    # the falling-edge marker is emitted by the main loop after exit_quiet.
    run_clock.append_telemetry(
        telemetry_path, {"mode": "quiet_enter", "manual": manual_only, "bucket": quiet_bucket},
    )
    try:
        if args.quiet_image == "auto":
            # On-the-fly goodnight frame in the operator's active theme. The
            # static assets/goodnight.png is dark-only, so themed installs
            # opt into this sentinel to keep the entire-display palette
            # consistent at the rising edge of quiet hours. ``mode='goodnight'``
            # tells render_quote.py to skip pick_quote and paint a centred
            # message instead — no quote, no history append.
            effective_theme = resolve_effective_theme(
                state.theme_arg, time_str, state.manual_theme,
                current_random_theme=state.current_random_theme,
                **_auto_theme_kwargs(args),
            )
            with state.render_lock:
                run_clock.render_now(
                    args.render_script, args.output, args.width, args.height, args.display_script,
                    "goodnight", effective_theme, time_str=args.quiet_start,
                    history_path=history_path, history_days=args.history_days,
                    telemetry_path=telemetry_path, bucket=quiet_bucket, quote_id=None,
                )
        elif args.quiet_image:
            with state.render_lock:
                run_clock._display_quiet_image(
                    args.quiet_image, args.output, args.display_script,
                    telemetry_path=telemetry_path,
                )
        else:
            effective_theme = resolve_effective_theme(
                state.theme_arg, time_str, state.manual_theme,
                current_random_theme=state.current_random_theme,
                **_auto_theme_kwargs(args),
            )
            with state.render_lock:
                run_clock.render_now(
                    args.render_script, args.output, args.width, args.height, args.display_script,
                    args.mode, effective_theme, time_str=args.quiet_start,
                    history_path=history_path, history_days=args.history_days,
                    telemetry_path=telemetry_path, bucket=quiet_bucket, quote_id=None,
                )
    except Exception as exc:
        _log(f"quiet-hours display failed: {exc!r}", err=True)
        traceback.print_exc(file=sys.stderr)
        run_clock.append_telemetry(
            telemetry_path, {"bucket": quiet_bucket, "error": repr(exc), "mode": "quiet"},
        )


def exit_quiet(state: RuntimeState) -> None:
    """Clear the render-dedup fields so the next normal tick repaints.

    Called by the main loop on scheduled quiet-exit, and by
    ``runtime_actions.action_quiet`` after the manual-quiet toggle flips in
    either direction — either case needs the loop to bypass the
    "bucket unchanged" dedup and push a fresh frame.
    """
    with state.lock:
        state.last_bucket = None
        state.last_quote_id = None
