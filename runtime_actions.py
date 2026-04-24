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
``save_runtime_state``, ``append_telemetry``, ``_append_history_after_render``,
and ``pick_quote_module`` through ``run_clock.X`` so tests that patch those
names on ``run_clock`` affect the action's call path (same pattern
``web_server`` uses to dodge circular imports at module load).
``_display_quiet_image`` is imported *directly* from :mod:`runtime_quiet` —
the through-``run_clock`` indirection earned no coupling benefit for a leaf
helper, and the direct import makes the ownership obvious.
"""
from __future__ import annotations

import argparse
import contextlib

from runtime_log import _log
from runtime_quiet import _display_quiet_image, exit_quiet
from runtime_state import RuntimeState
from runtime_theme import resolve_effective_theme


def _theme_cycle() -> tuple[str, ...]:
    """Return the cycle order for button-B / web theme advancement.

    Resolved lazily against ``render_quote.THEME_ORDER`` so this module keeps
    its PIL-free import graph. Falls back to the original binary pair if
    ``render_quote`` is unavailable, matching ``runtime_state._known_theme_names``.
    """
    try:
        from render_quote import THEME_ORDER
    except Exception:
        return ("default", "dark")
    return tuple(THEME_ORDER)


def _next_theme(current: str) -> str:
    """Return the next theme in the cycle after ``current``.

    If ``current`` is outside the cycle (e.g. a persisted theme that a newer
    build dropped), restart at the first entry so the user is never stranded
    on an unrecognised value.
    """
    order = _theme_cycle()
    if not order:
        return current
    try:
        idx = order.index(current)
    except ValueError:
        return order[0]
    return order[(idx + 1) % len(order)]


@contextlib.contextmanager
def _button_render_gate(
    state: RuntimeState,
    label: str,
    action: str,
    *,
    telemetry_path: str | None = None,
):
    """Try-acquire ``state.render_lock`` for a button or web handler.

    Yields ``True`` if the lock was acquired (caller does its work; the gate
    releases on exit) or ``False`` if a render is already in flight, in which
    case the press is logged, telemetrised as ``mode="press_dropped"``, and
    dropped. This coalesces a rapid tap-tap-tap down to "first wins, rest are
    no-ops" — without it, gpiozero queues subsequent events behind the slow
    eInk refresh and the user sees unpredictable multi-second delays.

    ``label`` is the source (``"button A"``, ``"web"``) and ``action`` is the
    verb (``"skip"``, ``"theme"``…); they appear together in the log line and
    as separate fields in the telemetry entry so a health summary can break
    drops down by both source and action.
    """
    name = f"{label} ({action})"
    if not state.render_lock.acquire(blocking=False):
        _log(f"{name}: busy (render in flight), press ignored")
        # Structured drop marker so operators can see "I mashed during a 20 s
        # refresh and nothing happened" in the telemetry sidecar — the log
        # line alone is easy to miss in journald under load.
        import run_clock  # lazy import matches the action-body pattern below
        run_clock.append_telemetry(
            telemetry_path,
            {"mode": "press_dropped", "label": label, "action": action, "reason": "render_in_flight"},
        )
        yield False
        return
    try:
        yield True
    finally:
        state.render_lock.release()


def _emit_action(telemetry_path: str | None, action: str, label: str, *, ok: bool, error: str | None = None) -> None:
    """Write one structured ``mode="action"`` telemetry entry.

    Extracted so each ``action_*`` body has a single call site for success /
    failure emission (the busy-drop case is handled by ``_button_render_gate``
    and records ``mode="press_dropped"`` instead, so the two never double-count).
    """
    import run_clock  # lazy: keeps test patches on run_clock.append_telemetry effective
    payload: dict = {"mode": "action", "action": action, "label": label, "ok": ok}
    if error is not None:
        payload["error"] = error
    run_clock.append_telemetry(telemetry_path, payload)


def action_skip(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Ban the currently-shown quote and render the next pick.

    Mirrors button A short-press. Returns ``{"ok": True, "new_quote_id": [...]}``,
    ``{"ok": False, "error": "busy"}`` when a render is already in flight, or
    ``{"ok": False, "error": "<repr>"}`` on exception.
    """
    import run_clock
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, label, "skip", telemetry_path=telemetry_path) as acquired:
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
            _emit_action(telemetry_path, "skip", label, ok=True)
            return {"ok": True, "new_quote_id": list(quote_id) if quote_id else None}
        except Exception as exc:
            _log(f"{label} skip failed: {exc!r}", err=True)
            _emit_action(telemetry_path, "skip", label, ok=False, error=repr(exc))
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
    with _button_render_gate(state, label, "unskip", telemetry_path=telemetry_path) as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        _log(f"{label}: un-skip")
        try:
            with state.lock:
                target = state.last_skipped
                state.last_skipped = None
            if target is None:
                _log("un-skip: no recently-skipped quote recorded")
                _emit_action(telemetry_path, "unskip", label, ok=True)
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
            _emit_action(telemetry_path, "unskip", label, ok=True)
            return {"ok": True, "restored": list(target)}
        except Exception as exc:
            _log(f"{label} un-skip failed: {exc!r}", err=True)
            _emit_action(telemetry_path, "unskip", label, ok=False, error=repr(exc))
            return {"ok": False, "error": repr(exc)}


def action_theme(
    args: argparse.Namespace,
    state: RuntimeState,
    *,
    label: str = "web",
    target: str | None = None,
) -> dict:
    """Advance the theme (button B cycle) or jump to ``target`` (web dropdown).

    When ``target`` is ``None`` (button B / fire-and-forget web POST), cycle
    to the next theme in ``render_quote.THEME_ORDER``. When ``target`` is a
    known theme name, jump directly to it — lets the curator UI expose a
    dropdown without forcing the operator to mash B four times to reach
    ``nightvision``. An unknown ``target`` returns 400-equivalent
    ``{"ok": False, "error": "unknown_theme"}`` without touching state.

    Order-of-operations matters: flip the in-memory ``manual_theme`` so the
    render reads the new value, push the display, and only *then* persist —
    if the render raises (missing font, subprocess timeout, Inky disconnect)
    we roll the flip back so ``state.json`` and the panel stay in sync.
    The alternative "persist first, then display" leaves ``state.json``
    claiming a theme the panel doesn't show after a transient I/O failure.

    Persist failures AFTER a successful render are NOT grounds for rollback:
    the panel already shows the new theme, so reverting in-memory state would
    just cause the next loop tick to undo the user's action. We log and keep
    running (same pattern as ``_persist_state_after_render`` for the main
    loop); the in-memory theme will be re-persisted on the next successful
    render commit.
    """
    import run_clock
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    # Validate ``target`` BEFORE the render-gate so a typo'd POST doesn't
    # burn a lock acquire / release cycle and doesn't emit a misleading
    # "busy" reply when the problem is the input, not contention.
    if target is not None and target not in _theme_cycle():
        _log(f"{label}: unknown theme {target!r}", err=True)
        _emit_action(telemetry_path, "theme", label, ok=False, error=f"unknown_theme:{target}")
        return {"ok": False, "error": "unknown_theme", "target": target}
    with _button_render_gate(state, label, "theme", telemetry_path=telemetry_path) as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        with state.lock:
            previous_theme = state.manual_theme
            time_str = run_clock.current_time_str()
            current = state.last_effective_theme or resolve_effective_theme(
                state.theme_arg, time_str, previous_theme,
            )
            new_theme = target if target is not None else _next_theme(current)
            state.manual_theme = new_theme
            quote_id = state.last_quote_id
        _log(f"{label}: theme {current} -> {new_theme}")
        try:
            run_clock._render_unlocked(args, state, time_str, history_path, quote_id=quote_id)
        except Exception as exc:
            with state.lock:
                state.manual_theme = previous_theme
            _log(f"{label} theme change failed: {exc!r} (rolled back to {previous_theme!r})", err=True)
            _emit_action(telemetry_path, "theme", label, ok=False, error=repr(exc))
            return {"ok": False, "error": repr(exc), "rolled_back": True}
        # Render succeeded; the panel is now authoritative. A persist failure
        # from here on must NOT roll back — the in-memory flip matches what
        # the operator sees.
        try:
            with state.lock:
                run_clock.save_runtime_state(args.state_path, state.snapshot_for_persistence())
        except Exception as exc:
            _log(f"{label} theme change: persist after render failed: {exc!r} (keeping in-memory flip)", err=True)
        _emit_action(telemetry_path, "theme", label, ok=True)
        return {"ok": True, "theme": new_theme, "previous": current}


def action_quiet(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Toggle the manual quiet override, display goodnight-or-wake frame, persist on success.

    Mirrors button D short-press. See :func:`action_theme` for the ordering
    rationale: the flip happens in RAM first, then we push the display (quiet
    image going in, fresh render coming out), then persist. A raise during the
    display push rolls the flip back so ``state.json`` cannot claim "quiet"
    while the panel still shows a quote (or vice versa).

    Persist failures AFTER the display/render succeeded are logged but do
    NOT trigger rollback — the panel is already the source of truth, so
    reverting ``manual_quiet`` would let the next loop tick immediately
    counteract the user action.
    """
    import run_clock
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, label, "quiet", telemetry_path=telemetry_path) as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        with state.lock:
            previous_quiet = state.manual_quiet
            state.manual_quiet = not previous_quiet
            quiet_now = state.manual_quiet
        # Shared with the main loop's scheduled-exit path: clear render-dedup
        # state so the next tick repaints in whichever direction we flipped.
        exit_quiet(state)
        _log(f"{label}: manual quiet -> {quiet_now}")
        try:
            if quiet_now and args.quiet_image:
                _display_quiet_image(
                    args.quiet_image, args.output, args.display_script,
                    telemetry_path=args.telemetry_path or None,
                )
            elif not quiet_now:
                # Wake to the current time so the user sees something immediately.
                time_str = run_clock.current_time_str()
                quote_id = run_clock.peek_quote_id(
                    time_str, history_path=history_path, history_days=args.history_days,
                )
                run_clock._render_unlocked(args, state, time_str, history_path, quote_id=quote_id)
        except Exception as exc:
            with state.lock:
                state.manual_quiet = previous_quiet
            _log(f"{label} quiet toggle failed: {exc!r} (rolled back to {previous_quiet!r})", err=True)
            _emit_action(telemetry_path, "quiet", label, ok=False, error=repr(exc))
            return {"ok": False, "error": repr(exc), "rolled_back": True}
        # Display/render succeeded; persist best-effort (see docstring).
        try:
            with state.lock:
                run_clock.save_runtime_state(args.state_path, state.snapshot_for_persistence())
        except Exception as exc:
            _log(f"{label} quiet toggle: persist after display failed: {exc!r} (keeping in-memory flip)", err=True)
        _emit_action(telemetry_path, "quiet", label, ok=True)
        return {"ok": True, "manual_quiet": quiet_now}


def action_rerender(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Force a re-render of the current time+bucket. Useful after panel ghosting or override edits."""
    import run_clock
    from buckets import bucket_for_time
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, label, "rerender", telemetry_path=telemetry_path) as acquired:
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
            _emit_action(telemetry_path, "rerender", label, ok=True)
            return {"ok": True, "bucket": bucket, "quote_id": list(quote_id) if quote_id else None}
        except Exception as exc:
            _log(f"{label} rerender failed: {exc!r}", err=True)
            _emit_action(telemetry_path, "rerender", label, ok=False, error=repr(exc))
            return {"ok": False, "error": repr(exc)}
