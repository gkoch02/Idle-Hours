#!/usr/bin/env python3
"""Runtime loop for the literary clock prototype."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import shlex
import signal
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import pick_quote as pick_quote_module
from buckets import bucket_for_time
from runtime_actions import (  # noqa: F401  re-exported for web_server + tests
    _button_render_gate,
    action_quiet,
    action_rerender,
    action_skip,
    action_theme,
    action_unskip,
)
from runtime_log import _log  # noqa: F401  re-exported
from runtime_quiet import (  # noqa: F401  re-exported
    _display_quiet_image,
    in_quiet_hours,
)
from runtime_state import RuntimeState  # noqa: F401  re-exported
from runtime_store import (  # noqa: F401  re-exported
    DEFAULT_STATE_PATH,
    _atomic_write_text,
    _resolve_state_path,
    load_runtime_state,
    save_runtime_state,
)
from runtime_telemetry import (  # noqa: F401  re-exported
    _TELEMETRY_DATE_RE,
    DEFAULT_TELEMETRY_PATH,
    DEFAULT_TELEMETRY_RETAIN_DAYS,
    append_telemetry,
    daily_telemetry_path,
    prune_telemetry,
)
from runtime_theme import (  # noqa: F401  re-exported
    AUTO_DARK_END_HOUR,
    AUTO_DARK_START_HOUR,
    _maybe_reset_manual_theme_at_midnight,
    auto_theme_for,
    resolve_effective_theme,
)

BASE_DIR = Path(__file__).resolve().parent


def _valid_hhmm(value: str) -> str:
    parts = value.split(":")
    try:
        h, m = int(parts[0]), int(parts[1])
        if not (len(parts) == 2 and 0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
    except (ValueError, IndexError):
        raise argparse.ArgumentTypeError(f"{value!r} is not a valid HH:MM time (expected 00:00–23:59)")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the literary clock render loop.")
    parser.add_argument(
        "--render-script",
        default="render_quote.py",
        help="Path to render script.",
    )
    parser.add_argument(
        "--output",
        default="output/current.png",
        help="Output image path to refresh in place.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Render once and exit.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=60,
        help="Refresh interval in seconds.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=800,
        help="Render width.",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=480,
        help="Render height.",
    )
    parser.add_argument(
        "--display-script",
        default=None,
        help="Optional script to push the rendered image to hardware, e.g. display_inky.py",
    )
    parser.add_argument(
        "--mode",
        choices=["production", "debug"],
        default="debug",
        help="Render mode passed through to render_quote.py",
    )
    parser.add_argument(
        "--theme",
        choices=["default", "dark", "auto"],
        default="default",
        help=(
            "Render theme passed through to render_quote.py. "
            "'auto' selects 'dark' between 18:00 and 06:00 and 'default' otherwise. "
            "Pressing button B toggles theme manually and overrides 'auto' until midnight."
        ),
    )
    parser.add_argument(
        "--buttons-off",
        action="store_true",
        help="Skip the Inky button listener. Use on dev machines or for headless runs.",
    )
    parser.add_argument(
        "--shutdown-command",
        default="sudo -n shutdown -h now",
        help=(
            "Shell command invoked when button D is held for 2 seconds. "
            "Default assumes passwordless sudo for shutdown is configured; set to "
            "an empty string to disable the long-press-to-shutdown feature."
        ),
    )
    parser.add_argument(
        "--startup-image",
        default=None,
        help=(
            "Optional PNG pushed to the display once at loop startup before the "
            "first quote render, so the panel doesn't ghost yesterday's frame "
            "during cold boot. Omit (default) to skip the startup frame."
        ),
    )
    parser.add_argument(
        "--state-path",
        default=DEFAULT_STATE_PATH,
        help=(
            "Path to the persistent runtime state JSON (manual theme override, "
            "manual quiet override). Pass an empty string to disable persistence."
        ),
    )
    parser.add_argument(
        "--telemetry-path",
        default=DEFAULT_TELEMETRY_PATH,
        help=(
            "Path to the JSONL telemetry log. Each successful render appends one line "
            "with bucket, render_ms, display_ms, source_id, line_number. Loop-level "
            "errors append an entry with an 'error' field. Pass an empty string to disable."
        ),
    )
    parser.add_argument(
        "--telemetry-retain-days",
        type=int,
        default=DEFAULT_TELEMETRY_RETAIN_DAYS,
        help=(
            "Drop date-rotated telemetry siblings older than this many days once "
            "per local-date rollover (default: 90). litclock_health.py still globs "
            "the directory every run, so unbounded retention eventually slows the "
            "summariser. 0 disables pruning entirely."
        ),
    )
    parser.add_argument(
        "--quiet-start",
        metavar="HH:MM",
        default="22:00",
        type=_valid_hhmm,
        help="Start of quiet window in 24-hour time (default: 22:00). Requires --quiet-end.",
    )
    parser.add_argument(
        "--quiet-end",
        metavar="HH:MM",
        default="06:00",
        type=_valid_hhmm,
        help="End of quiet window in 24-hour time (default: 06:00). Requires --quiet-start.",
    )
    parser.add_argument(
        "--quiet-image",
        metavar="PATH",
        default="assets/goodnight.png",
        help="PNG to display when quiet hours begin instead of rendering a corpus quote.",
    )
    parser.add_argument(
        "--quiet-off",
        action="store_true",
        help="Disable quiet hours entirely and render around the clock.",
    )
    parser.add_argument(
        "--history-path",
        default=pick_quote_module.DEFAULT_HISTORY_PATH,
        help=(
            "Path to the anti-repeat display history JSONL. "
            "Each successful render appends (timestamp, source_id, line_number); "
            "subsequent picks filter out entries within --history-days. "
            "Pass an empty string to disable."
        ),
    )
    parser.add_argument(
        "--history-days",
        type=int,
        default=pick_quote_module.DEFAULT_HISTORY_DAYS,
        help="Number of days of history to consider when filtering repeats. 0 disables.",
    )
    parser.add_argument(
        "--web-bind",
        default="",
        metavar="HOST:PORT",
        help=(
            "Start the curator web UI bound to HOST:PORT (default: off). "
            "Use '127.0.0.1:8080' for local-only access or '0.0.0.0:8080' to expose "
            "on the LAN. Non-localhost binds additionally require --web-token (or "
            "--web-token-file) on all POST endpoints."
        ),
    )
    parser.add_argument(
        "--web-token",
        default="",
        help=(
            "Shared token required on POSTs when --web-bind exposes the UI beyond "
            "127.0.0.1. Sent by clients as 'X-LitClock-Token: <token>'. GETs remain "
            "open (telemetry / coverage / current.png are not sensitive)."
        ),
    )
    parser.add_argument(
        "--web-token-file",
        default="",
        help=(
            "Path to a file containing the web token (one line). Preferred over "
            "--web-token when running under systemd so the token isn't visible in "
            "the process command line (and therefore in 'ps' / journald)."
        ),
    )
    args = parser.parse_args()
    if (args.quiet_start is None) != (args.quiet_end is None):
        parser.error("--quiet-start and --quiet-end must be specified together")
    return args


def current_time_str() -> str:
    return dt.datetime.now().strftime("%H:%M")


def current_bucket() -> str:
    return bucket_for_time(current_time_str())


def peek_quote_id(time_str: str, history_path: str | None = None, history_days: int = pick_quote_module.DEFAULT_HISTORY_DAYS) -> tuple | None:
    """Return a stable identity tuple for the quote pick_quote would return, or None on failure.

    ``matched_text`` is part of the identity because the renderer uses it to choose which
    phrase is bolded and coloured. Two picks that share (source_id, line_number, display_quote)
    but differ in matched_text (e.g. ``02:50`` vs ``02:55`` landing on the same row) still
    produce visibly different frames, so they must not dedup together.

    History params must match what the render subprocess will use so the peek's dedup
    check stays consistent with the actual render's pick.

    ``pick_quote.select_quote`` raises ``SystemExit`` when no candidate survives the quality
    gate in the target bucket or its neighbours; we swallow that alongside ``Exception`` so
    the runtime loop keeps ticking instead of aborting.
    """
    try:
        row = pick_quote_module.select_quote(time_str=time_str, history_path=history_path, history_days=history_days)
    except (Exception, SystemExit) as exc:
        _log(f"pick_quote failed for {time_str}: {exc!r}", err=True)
        return None
    return (
        row.get("source_id"),
        row.get("line_number"),
        row.get("display_quote"),
        row.get("matched_text"),
    )


def render_now(
    render_script: str,
    output_path: str,
    width: int,
    height: int,
    display_script: str | None = None,
    mode: str = "debug",
    theme: str = "default",
    time_str: str | None = None,
    history_path: str | None = None,
    history_days: int = pick_quote_module.DEFAULT_HISTORY_DAYS,
    telemetry_path: str | None = None,
    bucket: str | None = None,
    quote_id: tuple | None = None,
) -> None:
    if time_str is None:
        time_str = current_time_str()
    python_executable = sys.executable
    render_script_path = str((BASE_DIR / render_script).resolve()) if not Path(render_script).is_absolute() else render_script
    output_path_resolved = str((BASE_DIR / output_path).resolve()) if not Path(output_path).is_absolute() else output_path
    render_start = time.monotonic()
    subprocess.check_call(
        [
            python_executable,
            render_script_path,
            "--time",
            time_str,
            "--output",
            output_path_resolved,
            "--width",
            str(width),
            "--height",
            str(height),
            "--mode",
            mode,
            "--theme",
            theme,
            "--history-path",
            history_path or "",
            "--history-days",
            str(history_days),
        ]
    )
    render_ms = int((time.monotonic() - render_start) * 1000)
    _log(f"Rendered {time_str} -> {output_path_resolved} ({render_ms} ms)")
    display_ms: int | None = None
    if display_script:
        display_script_path = str((BASE_DIR / display_script).resolve()) if not Path(display_script).is_absolute() else display_script
        display_start = time.monotonic()
        subprocess.check_call([python_executable, display_script_path, output_path_resolved, "--theme", theme])
        display_ms = int((time.monotonic() - display_start) * 1000)
        _log(f"Displayed {output_path_resolved} via {display_script_path} ({display_ms} ms)")
    if telemetry_path:
        append_telemetry(
            telemetry_path,
            {
                "bucket": bucket,
                "render_ms": render_ms,
                "display_ms": display_ms,
                "source_id": quote_id[0] if quote_id else None,
                "line_number": quote_id[1] if quote_id else None,
                "mode": mode,
                "theme": theme,
            },
        )


def _render_unlocked(args: argparse.Namespace, state: RuntimeState, time_str: str, history_path: str | None,
                     mode: str | None = None, bucket: str | None = None, quote_id: tuple | None = None) -> None:
    """Core render-and-push. The caller MUST already hold ``state.render_lock``.

    Split out from :func:`_do_render` so a button handler can take the render
    lock non-blocking via :func:`_button_render_gate`, hold it for the handler's
    full duration (state mutations + render + display push), and drop follow-up
    presses that land while a 10–20 s Spectra 6 refresh is still in flight
    instead of queuing behind it.
    """
    effective_theme = resolve_effective_theme(state.theme_arg, time_str, state.manual_theme)
    actual_mode = mode or args.mode
    actual_bucket = bucket or bucket_for_time(time_str)
    render_now(
        args.render_script, args.output, args.width, args.height, args.display_script,
        actual_mode, effective_theme, time_str=time_str,
        history_path=history_path, history_days=args.history_days,
        telemetry_path=args.telemetry_path or None, bucket=actual_bucket, quote_id=quote_id,
    )
    with state.lock:
        state.last_bucket = actual_bucket
        state.last_effective_theme = effective_theme
        if quote_id is not None:
            state.last_quote_id = quote_id


def _do_render(args: argparse.Namespace, state: RuntimeState, time_str: str, history_path: str | None,
               mode: str | None = None, bucket: str | None = None, quote_id: tuple | None = None) -> None:
    """Blocking render-and-push. Acquires ``state.render_lock`` and delegates to
    :func:`_render_unlocked`. Used by the source-card restore timer (which must
    not be dropped, or the card would stay up) and tests.
    """
    with state.render_lock:
        _render_unlocked(args, state, time_str, history_path, mode=mode, bucket=bucket, quote_id=quote_id)


def _build_button_handlers(
    args: argparse.Namespace, state: RuntimeState,
) -> tuple[dict[str, "callable"], dict[str, "callable"]]:
    """Return ``(short_handlers, hold_handlers)`` for ``inky_buttons.start_listener``.

    Thin wrappers around the module-level ``action_*`` functions so the same
    bodies power both GPIO presses and the curator web UI's POST endpoints.
    ``short_handlers`` covers quick taps on A/B/C/D; ``hold_handlers`` adds the
    2-second long-press actions on A (un-skip) and D (shutdown).
    """
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None

    def on_skip() -> None:
        action_skip(args, state, label="button A")

    def on_unskip() -> None:
        action_unskip(args, state, label="button A")

    def on_toggle_theme() -> None:
        action_theme(args, state, label="button B")

    def on_source_card() -> None:
        # Source-card display is button-only for v2 (the web UI surfaces the
        # same title/author/id through ``GET /api/current`` without occupying
        # the panel for 5s). Kept inline because the timer-driven restore
        # doesn't fit the action_* return-dict contract cleanly.
        with _button_render_gate(state, "button C (card)") as acquired:
            if not acquired:
                return
            _log("button C: source card")
            try:
                time_str = current_time_str()
                quote_id = peek_quote_id(time_str, history_path=history_path, history_days=args.history_days)
                _render_unlocked(args, state, time_str, history_path, mode="card", quote_id=quote_id)

                def restore() -> None:
                    # The card needs to come down at the 5-second mark — relying on the
                    # next loop tick would leave it up for up to --interval-seconds (60s
                    # default). Re-pick (the bucket may have moved during the 5s) and
                    # render the normal frame ourselves via the BLOCKING _do_render so
                    # the card is guaranteed to be taken down even if another handler
                    # has the render lock at the 5s mark.
                    try:
                        rs_time = current_time_str()
                        rs_quote = peek_quote_id(rs_time, history_path=history_path, history_days=args.history_days)
                        _do_render(args, state, rs_time, history_path, quote_id=rs_quote)
                    except Exception as restore_exc:
                        _log(f"source card restore failed: {restore_exc!r}", err=True)

                timer = threading.Timer(5.0, restore)
                # Daemon so a pending restore doesn't block process exit on SIGTERM / KeyboardInterrupt.
                timer.daemon = True
                timer.start()
            except Exception as exc:
                _log(f"source card failed: {exc!r}", err=True)
                append_telemetry(telemetry_path, {"bucket": current_bucket(), "error": repr(exc), "mode": "card"})

    def on_shutdown() -> None:
        """Button D held 2s: display the goodnight frame and invoke the shutdown command.

        Best-effort. If ``--shutdown-command`` returns non-zero the failure
        is logged and the loop continues. A clean shutdown on the Pi requires
        passwordless sudo for the default ``sudo -n shutdown -h now``; users
        running without sudo can override via ``--shutdown-command``.

        If ``--shutdown-command`` is empty the feature is fully disabled:
        we return early without flipping quiet state, so an accidental long
        press can't leave the clock stuck in manual quiet across restarts.

        Order-of-operations: when shutdown IS enabled we flip
        ``state.manual_quiet`` BEFORE pushing the goodnight frame so that
        even if the main loop wakes between our ``_display_quiet_image``
        call and the shutdown invocation, it takes the quiet branch and
        (worst case) re-pushes goodnight — it can't slip a normal quote
        onto the panel in the final seconds before poweroff.
        """
        cmd = (args.shutdown_command or "").strip()
        if not cmd:
            _log("button D held: --shutdown-command is empty, skipping system shutdown")
            return
        with _button_render_gate(state, "button D (shutdown)") as acquired:
            if not acquired:
                return
            _log("button D held: shutdown")
            with state.lock:
                state.manual_quiet = True
                save_runtime_state(args.state_path, state.snapshot_for_persistence())
            try:
                if args.quiet_image:
                    _display_quiet_image(
                        args.quiet_image, args.output, args.display_script, reason="shutdown",
                    )
            except Exception as exc:
                _log(f"shutdown pre-frame failed: {exc!r}", err=True)
            try:
                subprocess.check_call(shlex.split(cmd))
            except Exception as exc:
                _log(f"shutdown command {cmd!r} failed: {exc!r}", err=True)
                append_telemetry(telemetry_path, {"bucket": current_bucket(), "error": repr(exc), "mode": "shutdown"})

    def on_quiet_toggle() -> None:
        action_quiet(args, state, label="button D")

    short_handlers = {
        "A": on_skip,
        "B": on_toggle_theme,
        "C": on_source_card,
        "D": on_quiet_toggle,
    }
    hold_handlers = {
        "A": on_unskip,
        "D": on_shutdown,
    }
    return short_handlers, hold_handlers


def _maybe_start_buttons(args: argparse.Namespace, state: RuntimeState):
    """Start the Inky button listener if available; swallow gpiozero import errors.

    Stashes the keepalive handles on ``state.button_handles`` so the main loop
    can call :func:`_check_button_liveness` each tick and surface a dead
    listener (unexpected GPIO release, crashed background thread) instead of
    silently dropping presses.
    """
    if args.buttons_off:
        return None
    try:
        import inky_buttons
        short_handlers, hold_handlers = _build_button_handlers(args, state)

        def _press_logger(label: str, pin: int) -> None:
            _log(f"button {label} (GPIO {pin}): pressed")

        handles = inky_buttons.start_listener(
            short_handlers, hold_handlers=hold_handlers, press_logger=_press_logger,
        )
        state.button_handles = handles
        return handles
    except Exception as exc:
        _log(f"button listener disabled ({exc!r}); pass --buttons-off to silence", err=True)
        return None


def _check_button_liveness(state: RuntimeState, telemetry_path: str | None) -> None:
    """If the button listener died, log loudly (once) and emit a telemetry entry.

    gpiozero runs its event loop in a background thread; if that thread dies
    or the pin claim is lost (flaky GPIO, post-reboot race, another process
    grabs the pin), ``Button.closed`` flips to True and presses silently stop
    working. The main loop has no other way to notice, so we check each tick.

    We deliberately do NOT auto-restart. A button listener that died once may
    die again immediately, and a restart loop would thrash GPIO claims. Log
    the event, emit telemetry, and let the operator decide. The warning is
    latched via ``state.buttons_dead_logged`` so stderr is not spammed every
    tick for a persistent failure.
    """
    if state.buttons_dead_logged:
        return
    try:
        import inky_buttons
    except Exception:
        return
    if inky_buttons.buttons_alive(state.button_handles):
        return
    _log(
        "button listener died: at least one GPIO pin has been released. "
        "Presses will be ignored until the process restarts.",
        err=True,
    )
    state.buttons_dead_logged = True
    append_telemetry(
        telemetry_path,
        {"bucket": current_bucket(), "error": "button listener died", "mode": "buttons_dead"},
    )


def _resolve_web_token(args: argparse.Namespace) -> str:
    """Resolve the web token from --web-token, --web-token-file, or empty (disabled).

    Prefers the file over the inline flag when both are set so rotating the
    token is a single file edit. A missing/unreadable token file is logged and
    falls back to the inline flag (or empty), keeping the server startable even
    if the file has a transient permission hiccup.
    """
    if args.web_token_file:
        try:
            return Path(args.web_token_file).expanduser().read_text(encoding="utf-8").strip()
        except OSError as exc:
            _log(f"--web-token-file {args.web_token_file!r} unreadable: {exc!r}", err=True)
    return (args.web_token or "").strip()


def _maybe_start_web_server(args: argparse.Namespace, state: RuntimeState):
    """Start the curator web server on a daemon thread when --web-bind is set.

    Returns the ``(server, thread)`` handle or ``None`` when the UI is disabled
    (default) or startup fails. Import is lazy so unit tests and headless runs
    never touch ``http.server`` unless the operator opted in. A startup failure
    is logged but does not abort the loop — the clock's primary job is still
    rendering to the panel.
    """
    if not args.web_bind:
        return None
    try:
        import web_server
    except Exception as exc:
        _log(f"web UI disabled ({exc!r}); install failure?", err=True)
        return None
    try:
        token = _resolve_web_token(args)
        handle = web_server.start_web_server(args, state, token=token)
    except Exception as exc:
        _log(f"web UI failed to start on {args.web_bind!r}: {exc!r}", err=True)
        traceback.print_exc(file=sys.stderr)
        return None
    server, _thread = handle
    host, port = server.server_address[:2]
    _log(f"web UI listening on {host}:{port} ({'token required' if token else 'no token'})")
    return handle


def stop_web_server(handle) -> None:
    """Shut down a running curator web server. No-op on None.

    ``ThreadingHTTPServer.shutdown`` blocks until the serving loop exits; we
    pair it with ``server_close`` to release the socket and a short thread join
    so tests can rely on the port being free by the time this returns.
    """
    if handle is None:
        return
    server, thread = handle
    try:
        server.shutdown()
    finally:
        with contextlib.suppress(Exception):
            server.server_close()
    thread.join(timeout=2)


def _maybe_prune_telemetry(args: argparse.Namespace, state: RuntimeState, telemetry_path: str | None) -> None:
    """Prune telemetry once per local-date rollover so we don't glob every tick.

    Piggybacks on ``state.last_seen_date`` (set by the midnight helper) as the
    "it's a new day" edge trigger. The first tick after process start also
    prunes so a long-running appliance that was offline while siblings aged
    past the window doesn't wait an extra day to catch up.
    """
    if not telemetry_path or args.telemetry_retain_days <= 0:
        return
    today = dt.date.today()
    with state.lock:
        last_pruned = getattr(state, "last_pruned_date", None)
        if last_pruned == today:
            return
        state.last_pruned_date = today
    removed = prune_telemetry(telemetry_path, args.telemetry_retain_days, today=today)
    if removed:
        _log(f"telemetry retention: dropped {removed} file(s) older than {args.telemetry_retain_days}d")


def _loop_sleep(state: RuntimeState, seconds: float) -> bool:
    """Interruptible wait between loop ticks.

    Returns True when ``state.stop_requested`` is set (caller should break the
    loop), False otherwise. Extracted as a module-level helper so tests can
    patch it to drive the loop deterministically without racing the event.
    """
    return state.stop_requested.wait(timeout=seconds)


def _install_signal_handlers(state: RuntimeState) -> None:
    """Arm ``SIGTERM`` / ``SIGINT`` so the loop can exit cleanly between ticks.

    systemd sends ``SIGTERM`` on ``systemctl restart`` and waits up to
    ``TimeoutStopSec`` (default 90s) before escalating to ``SIGKILL``. Without
    a handler the default behaviour is immediate termination, which can
    truncate whatever file (``output/current.png``, the history ledger, the
    telemetry log) the loop happens to be writing at that moment. With this
    handler the loop observes the event on its next poll, drains any in-flight
    render via :meth:`RuntimeState.render_lock`, tears down the web server and
    button listener cleanly, and exits.

    Only installed from the long-running main loop; ``--once`` keeps its
    strict-exit behaviour because cron callers rely on a nonzero exit when the
    single render fails.
    """
    def _handler(signum, _frame):
        _log(f"received signal {signum}, requesting clean shutdown")
        state.stop_requested.set()

    # signal.signal only works on the main thread; the loop runs on the main
    # thread so this is fine. We install for both SIGTERM (systemd) and SIGINT
    # (operator ctrl-c in a foreground run). SIGHUP is intentionally not
    # handled — we don't yet support config reload.
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, _handler)


def _shutdown(args: argparse.Namespace, state: RuntimeState, web_handle) -> None:
    """Drain the main loop's runtime resources on exit.

    Order matters:

    1. Block on ``render_lock`` so any in-flight render/display finishes
       before we tear down ingress. We then **hold the lock** across the
       web-server stop and button-close so any late-arriving HTTP POST or
       GPIO callback that reaches ``_button_render_gate`` sees the lock
       held and drops with a "busy" response instead of starting a fresh
       render during shutdown — without this, a press during the teardown
       window could kick off a new render and reintroduce SIGKILL-mid-
       render risk under systemd's ``TimeoutStopSec``.
    2. Stop the web server (joins its thread) while still holding the lock.
    3. Close GPIO button handles (still under the lock) so the ``gpiozero``
       listener thread exits instead of being left holding the pins after
       the process returns.
    4. Release the render lock and persist runtime state one last time so
       ``manual_theme`` / ``manual_quiet`` survive even the final pre-exit
       edit that didn't yet get an explicit ``save_runtime_state`` call.

    Every step is wrapped in ``contextlib.suppress`` so a single teardown
    failure doesn't prevent the others from running — shutdown is best-effort.
    """
    _log("shutdown: draining in-flight render")
    acquired = False
    try:
        with contextlib.suppress(Exception):
            acquired = state.render_lock.acquire(timeout=30.0)
        if not acquired:
            _log("shutdown: render still in flight after 30s, proceeding anyway", err=True)

        # Tear down ingress WHILE holding render_lock so any late web POST
        # or button callback that slips through hits _button_render_gate's
        # non-blocking acquire, sees the lock held, and drops with "busy".
        _log("shutdown: stopping web server")
        with contextlib.suppress(Exception):
            stop_web_server(web_handle)

        _log("shutdown: releasing GPIO buttons")
        with contextlib.suppress(Exception):
            handles = state.button_handles or []
            for handle in handles:
                close = getattr(handle, "close", None)
                if callable(close):
                    with contextlib.suppress(Exception):
                        close()
    finally:
        if acquired:
            with contextlib.suppress(Exception):
                state.render_lock.release()

    _log("shutdown: persisting runtime state")
    with contextlib.suppress(Exception):
        save_runtime_state(args.state_path, state.snapshot_for_persistence())

    _log("shutdown: done")


def main() -> int:
    args = parse_args()
    output_target = Path(args.output)
    if not output_target.is_absolute():
        output_target = BASE_DIR / output_target
    output_target.expanduser().parent.mkdir(parents=True, exist_ok=True)

    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None

    if args.once:
        time_str = current_time_str()
        effective_theme = resolve_effective_theme(args.theme, time_str, manual_theme=None)
        # Peek before rendering so the ledger entry matches what render_quote picks.
        # Both see the same ledger state because run_clock appends only after render succeeds.
        quote_id = peek_quote_id(time_str, history_path=history_path, history_days=args.history_days)
        render_now(
            args.render_script, args.output, args.width, args.height, args.display_script,
            args.mode, effective_theme, time_str=time_str,
            history_path=history_path, history_days=args.history_days,
            telemetry_path=telemetry_path, bucket=current_bucket(), quote_id=quote_id,
        )
        if quote_id is not None:
            pick_quote_module.append_history(history_path, quote_id[0], quote_id[1])
        return 0

    persisted = load_runtime_state(args.state_path)
    state = RuntimeState(args.theme, persisted=persisted)

    # Startup frame: push a static image to the panel before the first quote
    # renders so viewers see something intentional instead of yesterday's
    # ghosted frame during cold boot. Best-effort; a missing file is logged
    # and the loop continues to the first real render. Runs BEFORE the button
    # listener starts so a press during the (potentially slow) Inky push can't
    # collide with the unlocked display call.
    if args.startup_image:
        try:
            _display_quiet_image(
                args.startup_image, args.output, args.display_script, reason="startup",
            )
        except Exception as exc:
            _log(f"startup image display failed: {exc!r}", err=True)

    # ``state.button_handles`` holds the keepalive list for the lifetime of
    # the loop — gpiozero drops callbacks when its ``Button`` objects are
    # garbage-collected, so the reference must live as long as ``state`` does.
    # The liveness check below also reads from ``state.button_handles``.
    _maybe_start_buttons(args, state)

    # Curator web UI. Off by default; only starts when --web-bind is set.
    # Lives in the same process as the main loop so it can share state.render_lock
    # with the button handlers (a separate process would race the atomic state
    # writer). Runs on a daemon thread so process exit tears it down automatically;
    # tests can stop it explicitly via stop_web_server().
    web_handle = _maybe_start_web_server(args, state)

    # Install signal handlers AFTER buttons / web are up so their own teardown
    # registrations (if any) don't clobber ours. Before the main tick loop so a
    # fast-arriving SIGTERM is observed on the first iteration.
    _install_signal_handlers(state)

    _was_quiet = False
    try:
        while not state.stop_requested.is_set():
            time_str = current_time_str()
            _maybe_reset_manual_theme_at_midnight(args, state)
            _check_button_liveness(state, telemetry_path)
            _maybe_prune_telemetry(args, state, telemetry_path)

            with state.lock:
                manual_quiet = state.manual_quiet

            scheduled_quiet = in_quiet_hours(time_str, None if args.quiet_off else args.quiet_start, args.quiet_end)
            now_quiet = scheduled_quiet or manual_quiet

            if now_quiet:
                if not _was_quiet:
                    trigger = "manual" if manual_quiet and not scheduled_quiet else f"{args.quiet_start}–{args.quiet_end}"
                    _log(f"quiet hours start ({trigger})")
                    # Use bucket_for_time(time_str) here rather than current_bucket() so we
                    # don't double-tap the wall clock in tests that only patch current_time_str.
                    quiet_bucket = bucket_for_time(time_str)
                    try:
                        if args.quiet_image:
                            with state.render_lock:
                                _display_quiet_image(args.quiet_image, args.output, args.display_script)
                        else:
                            effective_theme = resolve_effective_theme(state.theme_arg, time_str, state.manual_theme)
                            with state.render_lock:
                                render_now(
                                    args.render_script, args.output, args.width, args.height, args.display_script,
                                    args.mode, effective_theme, time_str=args.quiet_start,
                                    history_path=history_path, history_days=args.history_days,
                                    telemetry_path=telemetry_path, bucket=quiet_bucket, quote_id=None,
                                )
                    except Exception as exc:
                        _log(f"quiet-hours display failed: {exc!r}", err=True)
                        traceback.print_exc(file=sys.stderr)
                        append_telemetry(telemetry_path, {"bucket": quiet_bucket, "error": repr(exc), "mode": "quiet"})
                    _was_quiet = True
                # Interruptible sleep so SIGTERM-during-quiet-hours wakes us up
                # within one tick instead of sitting on the full interval.
                if _loop_sleep(state, max(1, args.interval_seconds)):
                    break
                continue

            if _was_quiet:
                _log("quiet hours end, resuming normal render cycle")
                with state.lock:
                    state.last_bucket = None
                    state.last_quote_id = None
                _was_quiet = False

            bucket = current_bucket()
            effective_theme = resolve_effective_theme(state.theme_arg, time_str, state.manual_theme)
            bucket_changed = bucket != state.last_bucket
            theme_changed = effective_theme != state.last_effective_theme and state.last_effective_theme is not None
            if bucket_changed or theme_changed:
                try:
                    quote_id = peek_quote_id(time_str, history_path=history_path, history_days=args.history_days)
                    if quote_id is not None and quote_id == state.last_quote_id and not theme_changed:
                        _log(f"bucket {bucket}: quote unchanged, skipping redraw")
                        with state.lock:
                            state.last_bucket = bucket
                    else:
                        with state.render_lock:
                            render_now(
                                args.render_script, args.output, args.width, args.height, args.display_script,
                                args.mode, effective_theme, time_str=time_str,
                                history_path=history_path, history_days=args.history_days,
                                telemetry_path=telemetry_path, bucket=bucket, quote_id=quote_id,
                            )
                        with state.lock:
                            state.last_bucket = bucket
                            state.last_effective_theme = effective_theme
                            if quote_id is not None:
                                state.last_quote_id = quote_id
                        if quote_id is not None:
                            with state.ledger_lock:
                                pick_quote_module.append_history(history_path, quote_id[0], quote_id[1])
                except Exception as exc:
                    # Keep the loop alive so a transient failure (pick_quote crash, Inky I/O,
                    # missing corpus row, etc.) does not kill the appliance. last_bucket stays
                    # stale so the next tick retries.
                    _log(f"render/display failed for bucket {bucket}: {exc!r}", err=True)
                    traceback.print_exc(file=sys.stderr)
                    append_telemetry(telemetry_path, {"bucket": bucket, "error": repr(exc), "mode": args.mode})
            elif state.last_effective_theme is None:
                with state.lock:
                    state.last_effective_theme = effective_theme
            if _loop_sleep(state, max(1, args.interval_seconds)):
                break
    finally:
        _shutdown(args, state, web_handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
