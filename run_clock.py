#!/usr/bin/env python3
"""Runtime loop for the literary clock prototype."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import pick_quote as pick_quote_module
from buckets import bucket_for_time

BASE_DIR = Path(__file__).resolve().parent

DEFAULT_STATE_PATH = "~/.litclock/state.json"
DEFAULT_TELEMETRY_PATH = "~/.litclock/telemetry.jsonl"

# Auto-theme: switch to dark theme during this window, default theme otherwise.
# Boundaries chosen to match civil twilight in temperate latitudes; users who want
# a tighter fit can pass --theme default or --theme dark explicitly.
AUTO_DARK_START_HOUR = 18
AUTO_DARK_END_HOUR = 6


def _log(msg: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    print(f"[{dt.datetime.now().isoformat(timespec='seconds')}] {msg}", file=stream, flush=True)


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
    args = parser.parse_args()
    if (args.quiet_start is None) != (args.quiet_end is None):
        parser.error("--quiet-start and --quiet-end must be specified together")
    return args


def current_time_str() -> str:
    return dt.datetime.now().strftime("%H:%M")


def current_bucket() -> str:
    return bucket_for_time(current_time_str())


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


def _resolve_state_path(state_path: str | None) -> Path | None:
    if not state_path:
        return None
    return Path(state_path).expanduser()


def load_runtime_state(state_path: str | None) -> dict:
    """Load persisted runtime state. Returns ``{}`` when disabled, missing, or malformed.

    We expect the file to contain a JSON object. Anything else (a bare string,
    number, list, or parse error) is treated as unreadable and ignored rather
    than bricking startup with ``AttributeError`` when ``RuntimeState.__init__``
    later calls ``.get()`` on it.
    """
    path = _resolve_state_path(state_path)
    if path is None or not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log(f"runtime state at {path} unreadable, ignoring: {exc!r}", err=True)
        return {}
    if not isinstance(parsed, dict):
        _log(f"runtime state at {path} is not a JSON object ({type(parsed).__name__}), ignoring", err=True)
        return {}
    return parsed


def save_runtime_state(state_path: str | None, state: dict) -> None:
    """Persist runtime state atomically. No-op when disabled.

    Writes to a sibling ``*.tmp`` file, fsyncs, then ``os.replace``s into place.
    The rename is atomic on POSIX, so a crash during the write leaves *either*
    the old file intact or the new file fully written — never a half-written
    JSON blob that would silently lose the user's last theme/quiet preference
    when ``load_runtime_state`` parses it on the next boot.
    """
    path = _resolve_state_path(state_path)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise


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


class RuntimeState:
    """Mutable shared state between the main loop and the button listener thread.

    Button handlers act synchronously in their own thread and serialize against
    the main loop via :attr:`render_lock`. Per-button mutations of theme/quiet
    state are guarded by :attr:`lock`.
    """

    def __init__(self, theme_arg: str, persisted: dict | None = None):
        self.lock = threading.Lock()
        self.render_lock = threading.Lock()
        # Serialises read-modify-write of ~/.litclock/history.jsonl. Button A's
        # long-press does a remove-last-entry that would otherwise race the main
        # loop's post-render append and silently drop it.
        self.ledger_lock = threading.Lock()
        self.theme_arg = theme_arg            # CLI value ('default'/'dark'/'auto')
        self.manual_theme: str | None = None  # set by button B until midnight
        self.manual_quiet = False             # toggled by button D
        self.last_bucket: str | None = None
        self.last_quote_id: tuple | None = None
        self.last_effective_theme: str | None = None
        self.last_seen_date: dt.date | None = None
        # Populated when button A (skip) bans a quote; button A long-press
        # rolls that ban back and re-renders.
        self.last_skipped: tuple | None = None
        if persisted:
            mt = persisted.get("manual_theme")
            if mt in ("default", "dark"):
                self.manual_theme = mt
            self.manual_quiet = bool(persisted.get("manual_quiet", False))

    def snapshot_for_persistence(self) -> dict:
        return {"manual_theme": self.manual_theme, "manual_quiet": self.manual_quiet}


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


@contextlib.contextmanager
def _button_render_gate(state: RuntimeState, name: str):
    """Try-acquire ``state.render_lock`` for a button handler.

    Yields ``True`` if the lock was acquired (caller does its work; the gate
    releases on exit) or ``False`` if a render is already in flight, in which
    case the press is logged and dropped. This coalesces a rapid tap-tap-tap
    down to "first wins, rest are no-ops" — without it, gpiozero queues
    subsequent events behind the slow eInk refresh and the user sees
    unpredictable multi-second delays.
    """
    if not state.render_lock.acquire(blocking=False):
        _log(f"button {name}: busy (render in flight), press ignored")
        yield False
        return
    try:
        yield True
    finally:
        state.render_lock.release()


def _build_button_handlers(
    args: argparse.Namespace, state: RuntimeState,
) -> tuple[dict[str, "callable"], dict[str, "callable"]]:
    """Return ``(short_handlers, hold_handlers)`` for ``inky_buttons.start_listener``.

    ``short_handlers`` covers quick taps on A/B/C/D; ``hold_handlers`` adds the
    2-second long-press actions on A (un-skip) and D (shutdown). Each handler
    does its work synchronously in the listener thread and serialises against
    the loop via ``state.render_lock``. Mutations of theme/quiet state are
    persisted to ``--state-path`` so they survive a process restart; ledger
    appends/removes go through ``state.ledger_lock`` to prevent the main loop's
    post-render append from racing the un-skip's read-modify-write.
    """
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None

    def on_skip() -> None:
        with _button_render_gate(state, "A (skip)") as acquired:
            if not acquired:
                return
            _log("button A: skip")
            try:
                with state.lock:
                    previous = state.last_quote_id
                if previous is not None:
                    # Ban the currently-shown quote so the next pick filters it out for the week.
                    with state.ledger_lock:
                        pick_quote_module.append_history(history_path, previous[0], previous[1])
                    with state.lock:
                        # Remember what we just banned so A long-press can reverse it.
                        state.last_skipped = previous
                time_str = current_time_str()
                quote_id = peek_quote_id(time_str, history_path=history_path, history_days=args.history_days)
                _render_unlocked(args, state, time_str, history_path, quote_id=quote_id)
                if quote_id is not None:
                    with state.ledger_lock:
                        pick_quote_module.append_history(history_path, quote_id[0], quote_id[1])
            except Exception as exc:
                _log(f"skip failed: {exc!r}", err=True)
                append_telemetry(telemetry_path, {"bucket": current_bucket(), "error": repr(exc), "mode": "skip"})

    def on_unskip() -> None:
        """Button A held 2s: reverse the most recent skip.

        Removes the last-skipped quote's ban from the history ledger and
        re-renders the current time. If the bucket hasn't moved since the skip,
        the un-banned quote is likely to be picked again. If the bucket has
        moved on, the user just sees a fresh render for the new time — the
        ledger is still cleaned up either way. The ledger read-modify-write is
        serialised against the main loop's ``append_history`` via
        ``state.ledger_lock`` so a concurrent append is not silently lost.
        """
        with _button_render_gate(state, "A (unskip)") as acquired:
            if not acquired:
                return
            _log("button A held: un-skip")
            try:
                with state.lock:
                    target = state.last_skipped
                    state.last_skipped = None
                if target is None:
                    _log("un-skip: no recently-skipped quote recorded")
                    return
                with state.ledger_lock:
                    removed = pick_quote_module.remove_last_history_entry(history_path, target[0], target[1])
                _log(f"un-skip: removed ledger entry for source={target[0]} line={target[1]} ok={removed}")
                time_str = current_time_str()
                quote_id = peek_quote_id(time_str, history_path=history_path, history_days=args.history_days)
                _render_unlocked(args, state, time_str, history_path, quote_id=quote_id)
                if quote_id is not None:
                    with state.ledger_lock:
                        pick_quote_module.append_history(history_path, quote_id[0], quote_id[1])
            except Exception as exc:
                _log(f"un-skip failed: {exc!r}", err=True)
                append_telemetry(telemetry_path, {"bucket": current_bucket(), "error": repr(exc), "mode": "unskip"})

    def on_toggle_theme() -> None:
        with _button_render_gate(state, "B (theme)") as acquired:
            if not acquired:
                return
            try:
                time_str = current_time_str()
                with state.lock:
                    current = state.last_effective_theme or resolve_effective_theme(
                        state.theme_arg, time_str, state.manual_theme,
                    )
                    state.manual_theme = "dark" if current == "default" else "default"
                    save_runtime_state(args.state_path, state.snapshot_for_persistence())
                    quote_id = state.last_quote_id
                _log(f"button B: theme -> {state.manual_theme}")
                _render_unlocked(args, state, time_str, history_path, quote_id=quote_id)
            except Exception as exc:
                _log(f"theme toggle failed: {exc!r}", err=True)
                append_telemetry(telemetry_path, {"bucket": current_bucket(), "error": repr(exc), "mode": "theme"})

    def on_source_card() -> None:
        with _button_render_gate(state, "C (card)") as acquired:
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
        with _button_render_gate(state, "D (shutdown)") as acquired:
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
        with _button_render_gate(state, "D (quiet)") as acquired:
            if not acquired:
                return
            try:
                with state.lock:
                    state.manual_quiet = not state.manual_quiet
                    save_runtime_state(args.state_path, state.snapshot_for_persistence())
                    state.last_bucket = None  # force the loop to repaint on exit
                    state.last_quote_id = None
                    # Snapshot inside the lock so a concurrent toggle can't flip the
                    # branch we take below.
                    quiet_now = state.manual_quiet
                _log(f"button D: manual quiet -> {quiet_now}")
                if quiet_now and args.quiet_image:
                    _display_quiet_image(args.quiet_image, args.output, args.display_script)
                elif not quiet_now:
                    # Wake to the current time so the user sees something immediately.
                    time_str = current_time_str()
                    quote_id = peek_quote_id(time_str, history_path=history_path, history_days=args.history_days)
                    _render_unlocked(args, state, time_str, history_path, quote_id=quote_id)
            except Exception as exc:
                _log(f"quiet toggle failed: {exc!r}", err=True)
                append_telemetry(telemetry_path, {"bucket": current_bucket(), "error": repr(exc), "mode": "quiet"})

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
    """Start the Inky button listener if available; swallow gpiozero import errors."""
    if args.buttons_off:
        return None
    try:
        import inky_buttons
        short_handlers, hold_handlers = _build_button_handlers(args, state)

        def _press_logger(label: str, pin: int) -> None:
            _log(f"button {label} (GPIO {pin}): pressed")

        return inky_buttons.start_listener(
            short_handlers, hold_handlers=hold_handlers, press_logger=_press_logger,
        )
    except Exception as exc:
        _log(f"button listener disabled ({exc!r}); pass --buttons-off to silence", err=True)
        return None


def _maybe_reset_manual_theme_at_midnight(args: argparse.Namespace, state: RuntimeState) -> None:
    """Clear the manual theme override at the day boundary so 'auto' resumes."""
    today = dt.date.today()
    with state.lock:
        if state.last_seen_date is None:
            state.last_seen_date = today
            return
        if today != state.last_seen_date and state.theme_arg == "auto" and state.manual_theme is not None:
            _log(f"midnight rollover: clearing manual theme override ({state.manual_theme})")
            state.manual_theme = None
            save_runtime_state(args.state_path, state.snapshot_for_persistence())
        state.last_seen_date = today


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

    # Hold the returned button list as a local for the lifetime of the loop —
    # gpiozero drops handlers when its Button objects are garbage-collected.
    _buttons = _maybe_start_buttons(args, state)  # noqa: F841

    _was_quiet = False
    while True:
        time_str = current_time_str()
        _maybe_reset_manual_theme_at_midnight(args, state)

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
            time.sleep(max(1, args.interval_seconds))
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
        time.sleep(max(1, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
