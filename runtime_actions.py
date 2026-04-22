"""Button / web action handlers: skip, un-skip, theme toggle, quiet toggle, rerender.

Each action returns a result dict so the curator web server can serialise it
to JSON (``{"ok": True, ...}`` / ``{"ok": False, "error": "busy"}``); button
handlers ignore the return value and rely on internal logging. Every action:

- wraps its work in :func:`_button_render_gate` for coalesced-press semantics
  (a 10–20 s Spectra 6 refresh must not queue up tap-bursts — first wins,
  subsequent presses during the refresh are dropped);
- serialises state mutations via ``state.lock`` and ledger writes via
  ``state.ledger_lock``;
- catches ``Exception`` so a failure in one caller can't kill the listener
  thread or the HTTP server thread.

Extracted from :mod:`run_clock`; the original names are re-exported from
``run_clock`` for backwards compat (``web_server`` and tests reach them as
``run_clock.action_*``). Implementation detail: each action does a local
``import run_clock`` and routes calls to helpers like ``peek_quote_id``,
``_render_unlocked``, ``current_time_str``, ``current_bucket``,
``_display_quiet_image``, ``save_runtime_state``, ``append_telemetry``, and
``pick_quote_module`` through ``run_clock.X`` so tests that patch those names
on ``run_clock`` affect the action's call path (same pattern ``web_server``
uses to dodge circular imports at module load).
"""
from __future__ import annotations

import argparse
import contextlib

from runtime_log import _log
from runtime_quiet import _display_quiet_image
from runtime_state import RuntimeState
from runtime_theme import resolve_effective_theme


@contextlib.contextmanager
def _button_render_gate(state: RuntimeState, name: str):
    """Try-acquire ``state.render_lock`` for a button or web handler.

    Yields ``True`` if the lock was acquired (caller does its work; the gate
    releases on exit) or ``False`` if a render is already in flight, in which
    case the press is logged and dropped. This coalesces a rapid tap-tap-tap
    down to "first wins, rest are no-ops" — without it, gpiozero queues
    subsequent events behind the slow eInk refresh and the user sees
    unpredictable multi-second delays.

    ``name`` is the full caller label (e.g. ``"button A (skip)"`` or
    ``"web (skip)"``) so the log message correctly attributes a dropped press.
    """
    if not state.render_lock.acquire(blocking=False):
        _log(f"{name}: busy (render in flight), press ignored")
        yield False
        return
    try:
        yield True
    finally:
        state.render_lock.release()


def action_skip(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Ban the currently-shown quote and render the next pick.

    Mirrors button A short-press. Returns ``{"ok": True, "new_quote_id": [...]}``,
    ``{"ok": False, "error": "busy"}`` when a render is already in flight, or
    ``{"ok": False, "error": "<repr>"}`` on exception.
    """
    import run_clock
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, f"{label} (skip)") as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        _log(f"{label}: skip")
        try:
            with state.lock:
                previous = state.last_quote_id
            if previous is not None:
                # Ban the currently-shown quote so the next pick filters it out for the week.
                run_clock._append_history_after_render(state, history_path, previous)
                with state.lock:
                    # Remember what we just banned so A long-press / web unskip can reverse it.
                    state.last_skipped = previous
            time_str = run_clock.current_time_str()
            quote_id = run_clock.peek_quote_id(
                time_str, history_path=history_path, history_days=args.history_days,
            )
            run_clock._render_unlocked(args, state, time_str, history_path, quote_id=quote_id)
            if quote_id is not None:
                run_clock._append_history_after_render(state, history_path, quote_id)
            return {"ok": True, "new_quote_id": list(quote_id) if quote_id else None}
        except Exception as exc:
            _log(f"{label} skip failed: {exc!r}", err=True)
            run_clock.append_telemetry(
                telemetry_path, {"bucket": run_clock.current_bucket(), "error": repr(exc), "mode": "skip"},
            )
            return {"ok": False, "error": repr(exc)}


def action_unskip(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Reverse the most recent skip: remove the ledger entry, pick, re-render.

    Mirrors button A long-press. The ledger read-modify-write is serialised
    against the main loop's ``append_history`` via ``state.ledger_lock`` so a
    concurrent append cannot be silently lost.
    """
    import run_clock
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, f"{label} (unskip)") as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        _log(f"{label}: un-skip")
        try:
            with state.lock:
                target = state.last_skipped
                state.last_skipped = None
            if target is None:
                _log("un-skip: no recently-skipped quote recorded")
                return {"ok": True, "restored": None}
            with state.ledger_lock:
                removed = run_clock.pick_quote_module.remove_last_history_entry(
                    history_path, target[0], target[1],
                )
            _log(f"un-skip: removed ledger entry for source={target[0]} line={target[1]} ok={removed}")
            time_str = run_clock.current_time_str()
            quote_id = run_clock.peek_quote_id(
                time_str, history_path=history_path, history_days=args.history_days,
            )
            run_clock._render_unlocked(args, state, time_str, history_path, quote_id=quote_id)
            if quote_id is not None:
                run_clock._append_history_after_render(state, history_path, quote_id)
            return {"ok": True, "restored": list(target)}
        except Exception as exc:
            _log(f"{label} un-skip failed: {exc!r}", err=True)
            run_clock.append_telemetry(
                telemetry_path, {"bucket": run_clock.current_bucket(), "error": repr(exc), "mode": "unskip"},
            )
            return {"ok": False, "error": repr(exc)}


def action_theme(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Toggle default ↔ dark, persist to ``--state-path``, re-render. Mirrors button B."""
    import run_clock
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, f"{label} (theme)") as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        try:
            time_str = run_clock.current_time_str()
            with state.lock:
                current = state.last_effective_theme or resolve_effective_theme(
                    state.theme_arg, time_str, state.manual_theme,
                )
                state.manual_theme = "dark" if current == "default" else "default"
                run_clock.save_runtime_state(args.state_path, state.snapshot_for_persistence())
                new_theme = state.manual_theme
                quote_id = state.last_quote_id
            _log(f"{label}: theme -> {new_theme}")
            run_clock._render_unlocked(args, state, time_str, history_path, quote_id=quote_id)
            return {"ok": True, "theme": new_theme}
        except Exception as exc:
            _log(f"{label} theme toggle failed: {exc!r}", err=True)
            run_clock.append_telemetry(
                telemetry_path, {"bucket": run_clock.current_bucket(), "error": repr(exc), "mode": "theme"},
            )
            return {"ok": False, "error": repr(exc)}


def action_quiet(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Toggle the manual quiet override, persist, display goodnight-or-wake frame.

    Mirrors button D short-press.
    """
    import run_clock
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, f"{label} (quiet)") as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        try:
            with state.lock:
                state.manual_quiet = not state.manual_quiet
                run_clock.save_runtime_state(args.state_path, state.snapshot_for_persistence())
                state.last_bucket = None  # force the loop to repaint on exit
                state.last_quote_id = None
                # Snapshot inside the lock so a concurrent toggle can't flip the
                # branch we take below.
                quiet_now = state.manual_quiet
            _log(f"{label}: manual quiet -> {quiet_now}")
            if quiet_now and args.quiet_image:
                _display_quiet_image(args.quiet_image, args.output, args.display_script)
            elif not quiet_now:
                # Wake to the current time so the user sees something immediately.
                time_str = run_clock.current_time_str()
                quote_id = run_clock.peek_quote_id(
                    time_str, history_path=history_path, history_days=args.history_days,
                )
                run_clock._render_unlocked(args, state, time_str, history_path, quote_id=quote_id)
            return {"ok": True, "manual_quiet": quiet_now}
        except Exception as exc:
            _log(f"{label} quiet toggle failed: {exc!r}", err=True)
            run_clock.append_telemetry(
                telemetry_path, {"bucket": run_clock.current_bucket(), "error": repr(exc), "mode": "quiet"},
            )
            return {"ok": False, "error": repr(exc)}


def action_rerender(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Force a re-render of the current time+bucket. Useful after panel ghosting or override edits."""
    import run_clock
    from buckets import bucket_for_time
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, f"{label} (rerender)") as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        try:
            time_str = run_clock.current_time_str()
            bucket = bucket_for_time(time_str)
            quote_id = run_clock.peek_quote_id(
                time_str, history_path=history_path, history_days=args.history_days,
            )
            run_clock._render_unlocked(args, state, time_str, history_path, bucket=bucket, quote_id=quote_id)
            if quote_id is not None:
                run_clock._append_history_after_render(state, history_path, quote_id)
            _log(f"{label}: rerender bucket={bucket}")
            return {"ok": True, "bucket": bucket, "quote_id": list(quote_id) if quote_id else None}
        except Exception as exc:
            _log(f"{label} rerender failed: {exc!r}", err=True)
            run_clock.append_telemetry(
                telemetry_path, {"bucket": run_clock.current_bucket(), "error": repr(exc), "mode": "rerender"},
            )
            return {"ok": False, "error": repr(exc)}
