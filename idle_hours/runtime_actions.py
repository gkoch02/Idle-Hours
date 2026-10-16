"""Button / web action handlers: next / ban theme, next / ban quote, undo ban, un-skip, quiet toggle, rerender.

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

Extracted from :mod:`run_clock`. Helpers from sibling modules are read through
their module (``runtime_render.render_now(...)``, ``runtime_quiet.compute_quiet(...)``),
so a test patches a name where it is defined and every caller sees the patch
(issue #353). Nothing here imports ``run_clock``.
"""
from __future__ import annotations

import argparse
import contextlib
from collections.abc import Collection
from pathlib import Path

from idle_hours import pick_quote as pick_quote_module
from idle_hours import runtime_quiet, runtime_render, runtime_store, runtime_telemetry, runtime_theme
from idle_hours.runtime_log import _log
from idle_hours.runtime_state import RuntimeState
from idle_hours.theme_names import theme_cycle as _theme_cycle


def _next_theme(current: str, banned: Collection[str] = ()) -> str:
    """Return the next theme in the cycle after ``current``, stepping over ``banned`` ones.

    If ``current`` is outside the cycle (e.g. a persisted theme that a newer
    build dropped), restart at the first entry so the user is never stranded
    on an unrecognised value. ``current`` may itself be banned (button A's
    long-press bans the theme on the panel, then advances from it). Bans that
    would leave nothing are ignored (``runtime_theme.without_banned``).
    """
    order = _theme_cycle()
    if not order:  # pragma: no cover - defensive; theme_cycle always returns ≥2 entries
        return current
    eligible = set(runtime_theme.without_banned(order, banned))
    idx = order.index(current) if current in order else -1
    for step in range(1, len(order) + 1):
        candidate = order[(idx + step) % len(order)]
        if candidate in eligible:
            return candidate
    return current  # pragma: no cover - eligible is never empty


# Stamped on the frame painted right after a ban or an undo, and gone at the
# next repaint (``path_resolution.NOTICE_ENV``). The ban notices name the undo
# because a long press is otherwise invisible: this is how someone who did not
# know the gesture learns what just happened and how to take it back.
QUOTE_BANNED_NOTICE = "Quote banned · hold C to undo"


def theme_banned_notice(theme: str) -> str:
    return f"Theme banned: {theme} · hold C to undo"


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
        runtime_telemetry.append_telemetry(
            telemetry_path,
            {"mode": "press_dropped", "label": label, "action": action, "reason": "render_in_flight"},
        )
        yield False
        return
    try:
        yield True
    finally:
        state.render_lock.release()


def _emit_action(
    telemetry_path: str | None, action: str, label: str, *, ok: bool, error: str | None = None, **fields,
) -> None:
    """Write one structured ``mode="action"`` telemetry entry.

    Extracted so each ``action_*`` body has a single call site for success /
    failure emission (the busy-drop case is handled by ``_button_render_gate``
    and records ``mode="press_dropped"`` instead, so the two never double-count).
    ``fields`` carries an action's own detail, e.g. the banned theme.
    """
    payload: dict = {"mode": "action", "action": action, "label": label, "ok": ok, **fields}
    if error is not None:
        payload["error"] = error
    runtime_telemetry.append_telemetry(telemetry_path, payload)


def _quote_length(quote_id: tuple | None) -> int | None:
    """Character count of the quote ``quote_id`` names, for ban telemetry.

    A ban event records it so a later look at the bans can tell "this theme
    is disliked" from "this theme fails on long quotes".
    """
    if quote_id is None or len(quote_id) < 3 or not isinstance(quote_id[2], str):
        return None
    return len(quote_id[2])


def _quiet_active(args: argparse.Namespace, state: RuntimeState, time_str: str) -> bool:
    """Is the panel currently asleep?

    Thin wrapper over :func:`runtime_quiet.compute_quiet` that keeps only the
    first element — action handlers care whether the panel is showing a sleep
    frame, not whether the cause was the schedule or a manual toggle.
    """
    now_quiet, _manual_only = runtime_quiet.compute_quiet(args, state, time_str)
    return now_quiet


def _refuse_while_asleep(
    args: argparse.Namespace, state: RuntimeState, action: str, label: str, telemetry_path: str | None,
) -> dict | None:
    """``{"ok": False, "error": "asleep"}`` when the panel shows the sleep frame, else ``None``.

    Skip and un-skip re-pick and paint a *quote*; while the panel is asleep
    that would paint a clock frame that stays frozen until the window ends,
    because the main loop's quiet branch never ticks the clock
    (issue #278). Neither action means anything against a sleep frame — the
    quote it would ban is not on the panel — so both are refused the way a
    busy render is, and the operator wakes the panel first (button D / web
    wake) if they want the clock back. The web layer maps the error to 409.
    """
    if not _quiet_active(args, state, runtime_render.current_time_str()):
        return None
    _log(f"{label}: {action} ignored, panel is asleep (wake it first)")
    _emit_action(telemetry_path, action, label, ok=False, error="asleep")
    return {"ok": False, "error": "asleep"}


def action_skip(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Move to the next quote: hold the shown one out for ``--history-days`` and render the next pick.

    Mirrors button B short-press. The hold-out is the anti-repeat ledger, so
    it lapses; :func:`action_ban_quote` is the permanent version. Returns ``{"ok": True, "new_quote_id": [...]}``,
    ``{"ok": False, "error": "busy"}`` when a render is already in flight,
    ``{"ok": False, "error": "asleep"}`` while the panel shows the sleep
    frame (see :func:`_refuse_while_asleep`), or
    ``{"ok": False, "error": "<repr>"}`` on exception.
    """
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, label, "skip", telemetry_path=telemetry_path) as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        refused = _refuse_while_asleep(args, state, "skip", label, telemetry_path)
        if refused is not None:
            return refused
        _log(f"{label}: skip")
        try:
            with state.lock:
                previous = state.last_quote_id
            if previous is not None:
                # Ban the currently-shown quote so the next pick filters it out for the week.
                runtime_render._append_history_after_render(state, history_path, previous)
                with state.lock:
                    # Remember what we just banned so the web un-skip can reverse it.
                    state.last_skipped = previous
            quote_id = _show_next_quote_unlocked(args, state, previous)
            _emit_action(telemetry_path, "skip", label, ok=True)
            return {"ok": True, "new_quote_id": list(quote_id) if quote_id else None}
        except Exception as exc:
            _log(f"{label} skip failed: {exc!r}", err=True)
            _emit_action(telemetry_path, "skip", label, ok=False, error=repr(exc))
            return {"ok": False, "error": repr(exc)}


def _show_next_quote_unlocked(
    args: argparse.Namespace, state: RuntimeState, previous: tuple | None, *, notice: str | None = None,
) -> tuple | None:
    """Pick the quote for now, render it, and record it on the ledger. The caller holds ``render_lock``.

    Shared by skip and ban. In ``--theme random`` the new quote draws a new
    theme too, as every quote change does. ``previous`` is the quote that was
    on the panel: when a sparse bucket falls back to that same row it is not
    appended a second time, which keeps the ledger an honest
    one-entry-per-display log.
    """
    history_path = args.history_path or None
    time_str = runtime_render.current_time_str()
    quote_id = runtime_render.peek_quote_id(
        time_str, history_path=history_path, history_days=args.history_days,
        **runtime_render._corpus_kwargs(args),
    )
    runtime_render._maybe_pick_random_theme(state, quote_id)
    runtime_render._render_unlocked(args, state, time_str, history_path, quote_id=quote_id, notice=notice)
    if quote_id is not None and (previous is None or quote_id[:2] != previous[:2]):
        runtime_render._append_history_after_render(state, history_path, quote_id)
    return quote_id


def action_ban_quote(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Ban the quote on the panel permanently, then move to the next quote.

    Mirrors button B long-press. The ban is a ``"<source_id>:<line_number>"``
    key in the selection-overrides sidecar's ``ban_quote_keys``, the same file
    and the same lock as the curator UI's "Ban this quote", so it reaches the
    row's textual twins and is lifted in the overrides editor. The panel must
    be awake (the quote it would ban is not on a sleep frame). A sidecar that
    is not a readable document is refused (``overrides_invalid``) rather than
    replaced, as the web ban does.
    """
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, label, "quote_ban", telemetry_path=telemetry_path) as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        refused = _refuse_while_asleep(args, state, "quote_ban", label, telemetry_path)
        if refused is not None:
            return refused
        with state.lock:
            previous = state.last_quote_id
            theme = state.last_effective_theme
        if previous is None:
            _log(f"{label}: quote ban ignored, no quote on the panel yet")
            _emit_action(telemetry_path, "quote_ban", label, ok=False, error="no_quote")
            return {"ok": False, "error": "no_quote"}
        key = f"{previous[0]}:{previous[1]}"
        overrides_path = Path(runtime_render._corpus_kwargs(args)["overrides_path"]).expanduser()
        try:
            with pick_quote_module.OVERRIDES_WRITE_LOCK:
                already, _written = pick_quote_module.append_ban_quote_key(overrides_path, key)
        except (OSError, ValueError) as exc:
            _log(f"{label}: quote ban refused, {overrides_path} is unreadable or invalid: {exc!r}", err=True)
            _emit_action(telemetry_path, "quote_ban", label, ok=False, error="overrides_invalid", key=key)
            return {"ok": False, "error": "overrides_invalid", "key": key}
        _log(f"{label}: banned quote {key}" + (" (already banned)" if already else ""))
        if not already:
            with state.lock:
                state.last_ban = {
                    "kind": "quote", "key": key, "quote_id": previous,
                    "bucket": state.last_bucket, "theme": theme,
                }
        try:
            quote_id = _show_next_quote_unlocked(args, state, previous, notice=QUOTE_BANNED_NOTICE)
        except Exception as exc:
            # The ban stands (it is on disk and is what the operator asked
            # for); only the repaint failed, and the next tick retries it.
            _log(f"{label} quote ban: next quote failed: {exc!r}", err=True)
            _emit_action(telemetry_path, "quote_ban", label, ok=False, error=repr(exc), key=key)
            return {"ok": False, "error": repr(exc), "key": key, "banned": True}
        _emit_action(
            telemetry_path, "quote_ban", label, ok=True,
            key=key, theme=theme, quote_length=_quote_length(previous),
        )
        return {
            "ok": True, "key": key, "already_banned": already,
            "new_quote_id": list(quote_id) if quote_id else None,
        }


def action_unskip(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Reverse the most recent skip: remove the ledger entry, pick, re-render.

    Web only: button A became the theme button. The ledger read-modify-write is serialised
    against the main loop's ``append_history`` via ``state.ledger_lock`` so a
    concurrent append cannot be silently lost.
    """
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, label, "unskip", telemetry_path=telemetry_path) as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        refused = _refuse_while_asleep(args, state, "unskip", label, telemetry_path)
        if refused is not None:
            return refused
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
                # Remove EVERY entry for the key: the skip left both the
                # original render append and the ban append, and a single
                # removal would leave the quote history-filtered (#183).
                removed = pick_quote_module.remove_history_entries(
                    history_path, target[0], target[1],
                )
            _log(f"un-skip: removed {removed} ledger entries for source={target[0]} line={target[1]}")
            time_str = runtime_render.current_time_str()
            quote_id = runtime_render.peek_quote_id(
                time_str, history_path=history_path, history_days=args.history_days,
                **runtime_render._corpus_kwargs(args),
            )
            runtime_render._maybe_pick_random_theme(state, quote_id)
            runtime_render._render_unlocked(args, state, time_str, history_path, quote_id=quote_id)
            if quote_id is not None:
                runtime_render._append_history_after_render(state, history_path, quote_id)
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
    """Move to the next theme (button A) or jump to ``target`` (web dropdown).

    When ``target`` is ``None`` (button A / fire-and-forget web POST), move
    to the next theme: in ``--theme random`` with the panel awake, the next
    random draw (:func:`_reroll_random_theme_unlocked`, which stays in random
    mode); otherwise the next theme in ``theme_names.theme_cycle()`` that is
    not banned, set as the manual override. When ``target`` is a
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
        return _change_theme_unlocked(args, state, label, target)


def _change_theme_unlocked(
    args: argparse.Namespace, state: RuntimeState, label: str, target: str | None, *,
    notice: str | None = None, keep_on_failure: bool = False,
) -> dict:
    """The body of :func:`action_theme`. The caller holds ``render_lock``; ``target`` is already validated.

    ``keep_on_failure`` is for the ban: a failed repaint keeps the move to the
    next theme instead of rolling back to the banned one, so the main loop,
    seeing an effective theme that differs from the panel's, retries it.
    """
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    time_str = runtime_render.current_time_str()
    # Both of these take ``state.lock`` internally, so they must run
    # BEFORE the ``with state.lock`` block below — it is not reentrant.
    quiet_now = _quiet_active(args, state, time_str)
    if target is None and not quiet_now and state.theme_arg == "random":
        return _reroll_random_theme_unlocked(
            args, state, label, time_str, notice=notice, keep_on_failure=keep_on_failure,
        )
    # What is actually on the panel right now. While the panel is asleep
    # that is NOT ``state.last_effective_theme``: quiet frames render
    # through ``render_quiet_frame`` → ``render_now`` rather than
    # ``_render_unlocked``, so they deliberately never reach
    # ``commit_render_result`` and the field still describes the
    # pre-sleep *clock* frame. Deriving ``current`` from it during quiet
    # hours got both consumers below wrong: an explicit apply of the
    # clock theme (say ``newsprint``, while the sleep frame shows
    # ``nightvision``) matched the stale value and was dropped as a
    # no-op, and a button-A cycle advanced from ``newsprint`` rather than
    # from the ``nightvision`` the operator can see. Resolving through
    # ``resolve_quiet_theme`` asks the same function the frame itself
    # used, so "current" means "displayed" in both states.
    #
    # Calling it here cannot roll a stray ``--quiet-theme random`` pick:
    # that branch memoises on ``state.quiet_theme``, which ``enter_quiet``
    # has already populated by the time the panel is asleep, and in the
    # narrow window before the loop's first quiet tick the pick it rolls
    # is the very one the frame will use.
    displayed = runtime_theme.resolve_quiet_theme(args, state, time_str) if quiet_now else None
    with state.lock:
        previous_theme = state.manual_theme
        current = displayed or state.last_effective_theme or runtime_theme.resolve_effective_theme(
            state.theme_arg, time_str, previous_theme,
            current_random_theme=state.current_random_theme,
            **runtime_theme._auto_theme_kwargs(args),
        )
        new_theme = target if target is not None else _next_theme(current, state.banned_themes)
        # Guard against "Apply" on an unchanged dropdown selection. The
        # web UI pre-selects the active theme, so clicking Apply without
        # changing it would burn a 10–20 s Spectra 6 refresh. Worse, if
        # ``manual_theme`` was ``None`` (auto mode) we'd silently set it
        # to whatever the dropdown had pre-selected and pin auto off.
        # Only applies to explicit targets — a button-A cycle call
        # always advances, so ``target is None`` never trips this.
        if target is not None and new_theme == current:
            quote_id_noop = state.last_quote_id
            noop_manual = state.manual_theme
            _log(f"{label}: theme already {new_theme}, no-op (manual_theme={noop_manual!r})")
            _emit_action(telemetry_path, "theme", label, ok=True)
            return {
                "ok": True, "theme": new_theme, "previous": current,
                "noop": True, "quote_id": list(quote_id_noop) if quote_id_noop else None,
            }
        state.manual_theme = new_theme
        quote_id = state.last_quote_id
    _log(f"{label}: theme {current} -> {new_theme}")
    try:
        if quiet_now:
            # Repaint the SLEEP frame in the new theme, not a quote.
            # ``_render_unlocked`` has no quiet awareness, so a button-A
            # press during the blackout used to paint a corpus quote onto
            # a sleeping panel — and because the main loop only calls
            # ``enter_quiet`` on the rising edge, nothing put the sleep
            # frame back until the following night. Latent before
            # ``--quiet-theme``; unmissable once the sleep frame has a
            # theme worth changing.
            runtime_quiet.render_quiet_frame(args, state, time_str, manual_only=True)
        else:
            runtime_render._render_unlocked(args, state, time_str, history_path, quote_id=quote_id, notice=notice)
    except Exception as exc:
        if keep_on_failure:
            return _keep_theme_move_after_failure(args, state, label, exc)
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
            runtime_store.save_runtime_state(args.state_path, state.snapshot_for_persistence())
    except Exception as exc:
        _log(f"{label} theme change: persist after render failed: {exc!r} (keeping in-memory flip)", err=True)
    _emit_action(telemetry_path, "theme", label, ok=True)
    return {"ok": True, "theme": new_theme, "previous": current}

def _reroll_random_theme_unlocked(
    args: argparse.Namespace, state: RuntimeState, label: str, time_str: str, *,
    notice: str | None = None, keep_on_failure: bool = False,
) -> dict:
    """Button A in ``--theme random``: repaint the quote on the panel in the next random theme.

    Draws from the same shuffled bag as the per-quote pick, so a reroll
    respects the recent-window guard and the bans, and it stays in random
    mode: a manual override (from the web dropdown) is cleared rather than
    advanced, so a tap never turns random off until midnight. The caller
    holds ``render_lock`` and has checked the panel is awake. On a failed
    render the draw is rolled back, the same contract as the cycle path.
    """
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with state.lock:
        saved = (
            state.manual_theme, state.current_random_theme,
            list(state.random_theme_bag), list(state.random_theme_recent),
        )
        current = state.last_effective_theme or state.current_random_theme
        state.manual_theme = None
        new_theme = runtime_render._draw_random_theme_locked(state)
        quote_id = state.last_quote_id
    _log(f"{label}: random theme {current} -> {new_theme}")
    try:
        runtime_render._render_unlocked(args, state, time_str, history_path, quote_id=quote_id, notice=notice)
    except Exception as exc:
        if keep_on_failure:
            return _keep_theme_move_after_failure(args, state, label, exc)
        with state.lock:
            (
                state.manual_theme, state.current_random_theme,
                state.random_theme_bag, state.random_theme_recent,
            ) = saved
        _log(f"{label} random theme change failed: {exc!r} (rolled back)", err=True)
        _emit_action(telemetry_path, "theme", label, ok=False, error=repr(exc))
        return {"ok": False, "error": repr(exc), "rolled_back": True}
    if saved[0] is not None:
        # The manual override was cleared; persist that, best-effort.
        try:
            with state.lock:
                runtime_store.save_runtime_state(args.state_path, state.snapshot_for_persistence())
        except Exception as exc:
            _log(f"{label} random theme change: persist after render failed: {exc!r}", err=True)
    _emit_action(telemetry_path, "theme", label, ok=True)
    return {"ok": True, "theme": new_theme, "previous": current, "random": True}


def _keep_theme_move_after_failure(
    args: argparse.Namespace, state: RuntimeState, label: str, exc: Exception,
) -> dict:
    """A ban's repaint failed: keep the move off the banned theme and persist it.

    Rolling back, as a plain theme change does, would leave the panel on the
    theme just banned with nothing to move it: the loop would resolve the
    restored theme, match the frame on the panel and never repaint. Kept,
    the effective theme differs from ``last_effective_theme`` and the next
    tick retries the repaint (without the notice).
    """
    telemetry_path = args.telemetry_path or None
    try:
        with state.lock:
            runtime_store.save_runtime_state(args.state_path, state.snapshot_for_persistence())
    except Exception as persist_exc:
        _log(f"{label} theme change: persist failed: {persist_exc!r}", err=True)
    _log(f"{label} theme change failed: {exc!r} (kept; the next tick retries the repaint)", err=True)
    _emit_action(telemetry_path, "theme", label, ok=False, error=repr(exc))
    return {"ok": False, "error": repr(exc), "rolled_back": False}


def action_ban_theme(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Ban the theme on the panel permanently, then move to the next theme.

    Mirrors button A long-press. The ban goes on ``state.banned_themes`` and
    is persisted before the repaint, so it stands even if the repaint fails;
    from then on the theme is left out of random draws and of the cycle (an
    explicit ``--theme`` or dropdown choice still shows it). The move is
    exactly a button-A short press: the next random theme in ``--theme
    random``, otherwise the next theme in the cycle. Refused while the panel
    is asleep, like the quote actions: the theme to ban is the clock frame's,
    and that is not what a sleep frame shows. Lift a ban in the curator UI
    (:func:`action_unban_theme`).
    """
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, label, "theme_ban", telemetry_path=telemetry_path) as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        refused = _refuse_while_asleep(args, state, "theme_ban", label, telemetry_path)
        if refused is not None:
            return refused
        time_str = runtime_render.current_time_str()
        with state.lock:
            theme = state.last_effective_theme or runtime_theme.resolve_effective_theme(
                state.theme_arg, time_str, state.manual_theme,
                current_random_theme=state.current_random_theme,
                **runtime_theme._auto_theme_kwargs(args),
            )
            already = theme in state.banned_themes
            if not already:
                state.banned_themes.append(theme)
                # What button C's long-press undoes. A repeat ban of an
                # already-banned theme is not a new decision, so it leaves the
                # last real one in place.
                state.last_ban = {"kind": "theme", "theme": theme}
            quote_id = state.last_quote_id
            try:
                runtime_store.save_runtime_state(args.state_path, state.snapshot_for_persistence())
            except Exception as exc:
                # Kept in memory: the ban applies until a restart either way.
                _log(f"{label} theme ban: persist failed: {exc!r}", err=True)
        _log(f"{label}: banned theme {theme}" + (" (already banned)" if already else ""))
        _emit_action(
            telemetry_path, "theme_ban", label, ok=True,
            theme=theme, quote_length=_quote_length(quote_id),
        )
        result = _change_theme_unlocked(
            args, state, label, None, notice=theme_banned_notice(theme), keep_on_failure=True,
        )
        return {**result, "banned": theme, "already_banned": already}


def action_unban_theme(args: argparse.Namespace, state: RuntimeState, theme: str, *, label: str = "web") -> dict:
    """Lift a theme ban. No repaint: the theme simply rejoins random draws and the cycle.

    Takes only ``state.lock``, not the render gate, because nothing is
    painted. An unknown name is ``unknown_theme``; a theme that is not banned
    is a no-op success.
    """
    telemetry_path = args.telemetry_path or None
    if theme not in _theme_cycle():
        return {"ok": False, "error": "unknown_theme", "target": theme}
    with state.lock:
        was_banned = theme in state.banned_themes
        if state.last_ban == {"kind": "theme", "theme": theme}:
            state.last_ban = None
        if was_banned:
            state.banned_themes.remove(theme)
            try:
                runtime_store.save_runtime_state(args.state_path, state.snapshot_for_persistence())
            except Exception as exc:
                _log(f"{label} theme unban: persist failed: {exc!r}", err=True)
        banned = list(state.banned_themes)
    _log(f"{label}: unbanned theme {theme}" + ("" if was_banned else " (was not banned)"))
    _emit_action(telemetry_path, "theme_unban", label, ok=True, theme=theme)
    return {"ok": True, "theme": theme, "was_banned": was_banned, "banned_themes": banned}

def action_quiet(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Toggle the panel between asleep and awake, display the matching frame, persist on success.

    Mirrors button D short-press. The toggle is relative to what the panel is
    *showing*, not to the ``manual_quiet`` flag alone (issue #278); toggling
    the flag alone would leave a woken panel frozen inside the scheduled
    window, where the main loop neither re-enters quiet nor ticks the clock:

    * asleep → **wake**: ``manual_quiet`` is cleared and, if the window is
      the reason the panel was asleep, ``state.manual_awake`` is set so
      ``compute_quiet`` keeps the clock ticking until the window ends;
    * awake → **sleep**: inside the window that just clears
      ``manual_awake`` (the schedule itself keeps the panel asleep, and it
      wakes on its own at the window's end); outside it sets
      ``manual_quiet``.

    See :func:`action_theme` for the ordering rationale: the flip happens in
    RAM first, then we push the display (quiet image going in, fresh render
    coming out), then persist. A raise during the display push rolls the flip
    back so ``state.json`` cannot claim "quiet" while the panel still shows a
    quote (or vice versa).

    Persist failures AFTER the display/render succeeded are logged but do
    NOT trigger rollback — the panel is already the source of truth, so
    reverting ``manual_quiet`` would let the next loop tick immediately
    counteract the user action.
    """
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, label, "quiet", telemetry_path=telemetry_path) as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        time_str = runtime_render.current_time_str()
        # Both take ``state.lock`` internally, so they run before the block below.
        asleep_now = _quiet_active(args, state, time_str)
        scheduled = runtime_quiet.scheduled_quiet(args, time_str)
        with state.lock:
            previous = (state.manual_quiet, state.manual_awake)
            if asleep_now:
                state.manual_quiet = False
                state.manual_awake = scheduled
            else:
                state.manual_awake = False
                state.manual_quiet = not scheduled
            quiet_now = not asleep_now
            flags = f"manual_quiet={state.manual_quiet}, manual_awake={state.manual_awake}"
        # Shared with the main loop's scheduled-exit path: clear render-dedup
        # state before painting. The frame painted below commits its own
        # identity (a wake) or is a sleep frame the loop ignores while asleep.
        runtime_quiet.exit_quiet(state)
        _log(f"{label}: {'sleep' if quiet_now else 'wake'} ({flags})")
        try:
            if quiet_now:
                # Shared three-way --quiet-image dispatch. Calling
                # ``_display_quiet_image`` directly here used to skip the
                # ``"auto"`` sentinel, so a themed install raised
                # FileNotFoundError trying to copy a file named "auto".
                # ``manual_only=True`` so the frame claims the time the
                # operator actually pressed the button, not --quiet-start.
                # The gate above already holds render_lock.
                runtime_quiet.render_quiet_frame(args, state, time_str, manual_only=True)
            else:
                # Wake to the current time so the user sees something immediately.
                quote_id = runtime_render.peek_quote_id(
                    time_str, history_path=history_path, history_days=args.history_days,
                    **runtime_render._corpus_kwargs(args),
                )
                runtime_render._render_unlocked(args, state, time_str, history_path, quote_id=quote_id)
        except Exception as exc:
            with state.lock:
                state.manual_quiet, state.manual_awake = previous
            _log(f"{label} quiet toggle failed: {exc!r} (rolled back to {previous!r})", err=True)
            _emit_action(telemetry_path, "quiet", label, ok=False, error=repr(exc))
            return {"ok": False, "error": repr(exc), "rolled_back": True}
        # This action painted the frame, so it takes the quiet edge too. Left
        # to the main loop, the next tick saw an untaken edge and painted the
        # same sleep frame (or the same quote) a second time — a wasted
        # 10–20 s refresh on every toggle. The claim also emits the
        # ``quiet_enter`` / ``quiet_exit`` marker the loop used to.
        from idle_hours.buckets import bucket_for_time
        runtime_quiet.claim_quiet_edge(
            state, quiet_now, telemetry_path, manual=not scheduled, bucket=bucket_for_time(time_str),
        )
        # Display/render succeeded; persist best-effort (see docstring).
        try:
            with state.lock:
                runtime_store.save_runtime_state(args.state_path, state.snapshot_for_persistence())
        except Exception as exc:
            _log(f"{label} quiet toggle: persist after display failed: {exc!r} (keeping in-memory flip)", err=True)
        _emit_action(telemetry_path, "quiet", label, ok=True)
        with state.lock:
            return {
                "ok": True, "asleep": quiet_now,
                "manual_quiet": state.manual_quiet, "manual_awake": state.manual_awake,
            }


def action_rerender(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Repaint the frame that is on the panel. Useful after panel ghosting.

    A repaint, not a re-pick (issue #275): the quote on the panel is already
    on the anti-repeat ledger, so a fresh peek would exclude it and swap the
    quote. It pins ``state.last_quote_id`` under ``state.last_bucket``,
    exactly as ``action_theme`` does, and appends nothing. Only a cold-start panel with
    nothing committed yet falls back to a pick (and records that pick).

    While the panel is asleep the frame on it is the *sleep frame*, so that
    is what gets repainted (issue #278) — the same routing ``action_theme``
    uses; a quote painted here would stay frozen until the window ended.
    """
    from idle_hours.buckets import bucket_for_time
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, label, "rerender", telemetry_path=telemetry_path) as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        try:
            time_str = runtime_render.current_time_str()
            quiet_now, manual_only = runtime_quiet.compute_quiet(args, state, time_str)
            if quiet_now:
                # The gate above already holds render_lock.
                runtime_quiet.render_quiet_frame(args, state, time_str, manual_only=manual_only)
                _log(f"{label}: rerender (sleep frame)")
                _emit_action(telemetry_path, "rerender", label, ok=True)
                return {"ok": True, "asleep": True, "bucket": None, "quote_id": None}
            bucket, quote_id = runtime_render.displayed_quote(state)
            fresh_pick = quote_id is None
            if fresh_pick:
                bucket = bucket_for_time(time_str)
                quote_id = runtime_render.peek_quote_id(
                    time_str, history_path=history_path, history_days=args.history_days,
                    **runtime_render._corpus_kwargs(args),
                )
            runtime_render._render_unlocked(args, state, time_str, history_path, bucket=bucket, quote_id=quote_id)
            if fresh_pick and quote_id is not None:
                runtime_render._append_history_after_render(state, history_path, quote_id)
            _log(f"{label}: rerender bucket={bucket}")
            _emit_action(telemetry_path, "rerender", label, ok=True)
            return {"ok": True, "bucket": bucket, "quote_id": list(quote_id) if quote_id else None}
        except Exception as exc:
            _log(f"{label} rerender failed: {exc!r}", err=True)
            _emit_action(telemetry_path, "rerender", label, ok=False, error=repr(exc))
            return {"ok": False, "error": repr(exc)}


def action_undo_ban(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Undo the most recent ban (``state.last_ban``), theme or quote, and put it back on the panel.

    Mirrors button C long-press. One decision, not all of them: clearing every
    theme ban is a curator-UI action behind a confirm
    (:func:`action_clear_theme_bans`). A theme comes back on the quote now on
    the panel (as the random pick under ``--theme random``, otherwise as the
    manual theme). A quote comes back if it is still its five-minute bucket;
    later than that its ban is lifted and the panel keeps its quote. Either
    repaint carries a "Ban undone" notice. Refused while asleep, like the bans;
    nothing to undo is a no-op success with no repaint.
    """
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, label, "undo_ban", telemetry_path=telemetry_path) as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        refused = _refuse_while_asleep(args, state, "undo_ban", label, telemetry_path)
        if refused is not None:
            return refused
        with state.lock:
            ban = state.last_ban
        if ban is None:
            _log(f"{label}: undo ban: nothing to undo")
            _emit_action(telemetry_path, "undo_ban", label, ok=True, undone=None)
            return {"ok": True, "undone": None}
        time_str = runtime_render.current_time_str()
        if ban["kind"] == "theme":
            return _undo_theme_ban_unlocked(args, state, label, time_str, ban["theme"])
        return _undo_quote_ban_unlocked(args, state, label, time_str, ban)


def _undo_theme_ban_unlocked(
    args: argparse.Namespace, state: RuntimeState, label: str, time_str: str, theme: str,
) -> dict:
    """Lift ``theme``'s ban and repaint the panel's quote in it. The caller holds ``render_lock``."""
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with state.lock:
        if theme in state.banned_themes:
            state.banned_themes.remove(theme)
        state.last_ban = None
        saved = (state.manual_theme, state.current_random_theme)
        if state.theme_arg == "random":
            state.manual_theme = None
            state.current_random_theme = theme
        else:
            state.manual_theme = theme
        quote_id = state.last_quote_id
        try:
            runtime_store.save_runtime_state(args.state_path, state.snapshot_for_persistence())
        except Exception as exc:
            _log(f"{label} undo ban: persist failed: {exc!r}", err=True)
    _log(f"{label}: undo ban: theme {theme} is back")
    try:
        runtime_render._render_unlocked(
            args, state, time_str, history_path, quote_id=quote_id, notice=f"Ban undone: {theme} is back",
        )
    except Exception as exc:
        # The ban stays lifted (that was the ask); only the theme switch is
        # rolled back, so state matches the frame still on the panel.
        with state.lock:
            state.manual_theme, state.current_random_theme = saved
            # The theme switch was persisted with the lifted ban; re-save so
            # a restart does not apply the switch the panel never showed.
            try:
                runtime_store.save_runtime_state(args.state_path, state.snapshot_for_persistence())
            except Exception as persist_exc:
                _log(f"{label} undo ban: persist after rollback failed: {persist_exc!r}", err=True)
        _log(f"{label} undo ban: repaint failed: {exc!r}", err=True)
        _emit_action(telemetry_path, "undo_ban", label, ok=False, error=repr(exc), theme=theme)
        return {"ok": False, "error": repr(exc), "undone": {"kind": "theme", "theme": theme}}
    _emit_action(telemetry_path, "undo_ban", label, ok=True, theme=theme)
    return {"ok": True, "undone": {"kind": "theme", "theme": theme}}


def _undo_quote_ban_unlocked(
    args: argparse.Namespace, state: RuntimeState, label: str, time_str: str, ban: dict,
) -> dict:
    """Lift a quote ban and, within its bucket, put the quote back. The caller holds ``render_lock``."""
    from idle_hours.buckets import bucket_for_time
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    key = ban["key"]
    overrides_path = Path(runtime_render._corpus_kwargs(args)["overrides_path"]).expanduser()
    try:
        with pick_quote_module.OVERRIDES_WRITE_LOCK:
            pick_quote_module.remove_ban_quote_key(overrides_path, key)
    except (OSError, ValueError) as exc:
        # last_ban is kept, so the undo can be retried once the file is fixed.
        _log(f"{label}: undo ban refused, {overrides_path} is unreadable or invalid: {exc!r}", err=True)
        _emit_action(telemetry_path, "undo_ban", label, ok=False, error="overrides_invalid", key=key)
        return {"ok": False, "error": "overrides_invalid", "key": key}
    restore = ban.get("bucket") is not None and ban["bucket"] == bucket_for_time(time_str)
    with state.lock:
        state.last_ban = None
        if restore and state.theme_arg == "random" and state.manual_theme is None and ban.get("theme"):
            # Back in the theme it was banned in, held for this quote.
            state.current_random_theme = ban["theme"]
            state.last_random_quote_id = ban["quote_id"]
    if restore:
        bucket, quote_id, notice = ban["bucket"], ban["quote_id"], "Ban undone: the quote is back"
    else:
        bucket, quote_id = runtime_render.displayed_quote(state)
        notice = "Ban undone: that quote can show again"
    _log(f"{label}: undo ban: quote {key}" + (" is back" if restore else " unbanned (its bucket has passed)"))
    try:
        runtime_render._render_unlocked(
            args, state, time_str, history_path, bucket=bucket, quote_id=quote_id, notice=notice,
        )
    except Exception as exc:
        _log(f"{label} undo ban: repaint failed: {exc!r}", err=True)
        _emit_action(telemetry_path, "undo_ban", label, ok=False, error=repr(exc), key=key)
        return {"ok": False, "error": repr(exc), "undone": {"kind": "quote", "key": key}}
    _emit_action(telemetry_path, "undo_ban", label, ok=True, key=key, restored=restore)
    return {"ok": True, "undone": {"kind": "quote", "key": key}, "restored": restore}


def action_clear_theme_bans(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Lift every theme ban. Curator UI only, behind a confirm; no repaint.

    Deliberately not on a button: bans accumulate one considered press at a
    time and a hold is the easiest gesture to trigger by accident, so the
    wholesale reset lives where it can ask first. Quote bans are untouched;
    they share ``selection_overrides.json`` with the curator's own bans and
    are edited there.
    """
    telemetry_path = args.telemetry_path or None
    with state.lock:
        cleared = list(state.banned_themes)
        state.banned_themes.clear()
        if state.last_ban is not None and state.last_ban.get("kind") == "theme":
            state.last_ban = None
        if cleared:
            try:
                runtime_store.save_runtime_state(args.state_path, state.snapshot_for_persistence())
            except Exception as exc:
                _log(f"{label} clear theme bans: persist failed: {exc!r}", err=True)
    _log(f"{label}: cleared {len(cleared)} theme ban(s)")
    _emit_action(telemetry_path, "clear_theme_bans", label, ok=True, themes=cleared)
    return {"ok": True, "cleared": cleared, "banned_themes": []}
