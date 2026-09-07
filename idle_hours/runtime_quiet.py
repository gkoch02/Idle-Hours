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

from idle_hours import sd_notify
from idle_hours.buckets import bucket_for_time
from idle_hours.path_resolution import resolve_input_path
from idle_hours.runtime_log import _log
from idle_hours.runtime_state import RuntimeState
from idle_hours.runtime_theme import resolve_quiet_theme

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
    # ``quiet_image`` / ``display_script`` are INPUT paths — try CWD first
    # (operator's custom override), fall back to ``BASE_DIR`` for the
    # bundled defaults (``assets/goodnight.png``, ``display_inky.py``).
    # ``output`` is an OUTPUT path — always CWD-relative, never BASE_DIR
    # (which would write the goodnight frame inside the installed package).
    # ``run_clock.main`` also persists the resolved absolute ``args.output``
    # back onto the namespace before this is reached, so in practice
    # ``output`` arrives here already absolute on the loop path; the
    # CWD-resolve is defence in depth for any direct caller.
    quiet_path = resolve_input_path(quiet_image, BASE_DIR)
    output_resolved = str(Path(output).expanduser().resolve())
    shutil.copy2(str(quiet_path), output_resolved)
    _log(f"{reason}: {quiet_path.name} -> {output_resolved}")
    if display_script:
        display_path = str(resolve_input_path(display_script, BASE_DIR))
        try:
            subprocess.run(
                [sys.executable, display_path, output_resolved],
                check=True,
                timeout=DISPLAY_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            sd_notify.notify_watchdog()
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
        # Watchdog ping at the subprocess boundary, mirroring
        # ``run_clock.render_now`` (#236). ``enter_quiet`` holds
        # ``state.render_lock`` across this call, so the main loop can be
        # blocked behind it — without a ping here that wait is a silent gap in
        # the ``WatchdogSec`` budget.
        sd_notify.notify_watchdog()
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
    # ``getattr`` defaults cover programmatic ``argparse.Namespace``
    # constructions (tests, the web server's synthesised args) that predate
    # or omit the quiet flags — the same accommodation
    # ``runtime_theme._auto_theme_kwargs`` documents. The defaults are
    # deliberately the *conservative* direction rather than argparse's:
    # a missing ``quiet_start`` yields ``None``, which ``in_quiet_hours``
    # reads as "quiet hours disabled", so an incomplete Namespace is never
    # spuriously reported as asleep. Real runs always carry all three.
    quiet_off = getattr(args, "quiet_off", False)
    scheduled_quiet = in_quiet_hours(
        time_str,
        None if quiet_off else getattr(args, "quiet_start", None),
        getattr(args, "quiet_end", None),
    )
    return (scheduled_quiet or manual_quiet, manual_quiet and not scheduled_quiet)


def render_quiet_frame(
    args: argparse.Namespace,
    state: RuntimeState,
    time_str: str,
    *,
    manual_only: bool = False,
    reason: str = "quiet hours",
) -> None:
    """Put the sleep frame on the panel. **Caller must hold ``state.render_lock``.**

    The three-way ``--quiet-image`` dispatch, extracted from :func:`enter_quiet`
    so every path that needs a sleep frame shares one definition of what that
    is. Before the extraction only ``enter_quiet`` understood the ``"auto"``
    sentinel: ``runtime_actions.action_quiet`` (button D short-press) and
    ``run_clock``'s button-D long-press shutdown preamble both called
    ``_display_quiet_image(args.quiet_image, ...)`` directly, so on an install
    configured with ``--quiet-image auto`` they tried to *copy a file literally
    named* ``auto`` and raised ``FileNotFoundError``. That was an opt-in
    footgun while the default was a real path; it became the default's problem
    the moment ``--quiet-image`` started defaulting to ``auto``.

    The branches:

    * ``"auto"`` — render the bundled sleep quote through the normal literary
      layout in the resolved quiet theme. ``mode='goodnight'`` tells
      ``render_quote.py`` to use :data:`render_quote.SLEEP_QUOTE_ROW` rather
      than consulting the picker, so there is no corpus row and no history
      append.
    * ``"<path>"`` — copy a static PNG. Ignores the theme entirely, which is
      the point for an operator supplying their own image.
    * ``""`` — render the ``--quiet-start`` corpus quote as the last frame of
      the night, in the quiet theme.

    ``manual_only`` distinguishes a button-D / web toggle from the scheduled
    rising edge, and decides only *which time the rendered frame claims*:
    a scheduled entry renders ``--quiet-start`` (the documented
    "last quote of the night" contract), while a manual toggle must render the
    current time — ``--quiet-start`` is unrelated to the moment the operator
    pressed the button, and using it painted a 22:00 quote onto the panel at
    two in the afternoon. ``or time_str`` covers a ``--quiet-off`` install
    where ``--quiet-start`` is unset entirely.
    """
    from idle_hours import run_clock  # lazy: circular import, and keeps test patches on
                      # run_clock._display_quiet_image / run_clock.render_now working.
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    render_time = time_str if manual_only else (getattr(args, "quiet_start", None) or time_str)
    # The render's telemetry entry must describe the frame we actually
    # painted, so it takes the bucket of ``render_time`` rather than the
    # entry-time bucket the ``quiet_enter`` marker carries. The two coincide
    # on the normal scheduled edge; they diverge when the loop enters quiet
    # late (a restart at 01:00 inside a 22:00–06:00 window) or on a manual
    # toggle.
    render_bucket = bucket_for_time(render_time)

    if args.quiet_image == "auto":
        # ``resolve_quiet_theme`` rather than ``resolve_effective_theme``:
        # ``--quiet-theme`` lets the sleep frame differ from the clock's own
        # theme, and its ``random`` mode rerolls per quiet window rather than
        # per quote change. Falls through to ``resolve_effective_theme`` on
        # the default ``inherit``.
        effective_theme = resolve_quiet_theme(args, state, time_str)
        run_clock.render_now(
            args.render_script, args.output, args.width, args.height, args.display_script,
            "goodnight", effective_theme, time_str=render_time,
            history_path=history_path, history_days=args.history_days,
            telemetry_path=telemetry_path, bucket=render_bucket, quote_id=None,
            **run_clock._corpus_kwargs(args),
        )
    elif args.quiet_image:
        run_clock._display_quiet_image(
            args.quiet_image, args.output, args.display_script,
            reason=reason, telemetry_path=telemetry_path,
        )
    else:
        effective_theme = resolve_quiet_theme(args, state, time_str)
        run_clock.render_now(
            args.render_script, args.output, args.width, args.height, args.display_script,
            args.mode, effective_theme, time_str=render_time,
            history_path=history_path, history_days=args.history_days,
            telemetry_path=telemetry_path, bucket=render_bucket, quote_id=None,
            **run_clock._corpus_kwargs(args),
        )


def enter_quiet(
    args: argparse.Namespace,
    state: RuntimeState,
    time_str: str,
    *,
    manual_only: bool = False,
) -> None:
    """Emit the rising-edge marker and push the sleep frame to the panel.

    Wraps :func:`render_quiet_frame` in ``state.render_lock`` so a racing
    button / web handler can't interleave their own render. A display failure
    is logged, traced, and recorded to the telemetry sidecar as ``mode="quiet"``
    but never propagated — the loop's next tick will retry.

    ``time_str`` is *when we entered quiet* and is what the ``quiet_enter``
    marker records; the frame's own time is decided inside
    :func:`render_quiet_frame`.
    """
    from idle_hours import run_clock  # lazy: see render_quiet_frame.
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
        with state.render_lock:
            render_quiet_frame(args, state, time_str, manual_only=manual_only)
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
        # Drop the ``--quiet-theme random`` pick so the next rising edge
        # rerolls. Harmless when quiet-theme is anything else — only that
        # branch ever sets the field.
        state.quiet_theme = None
