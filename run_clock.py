#!/usr/bin/env python3
"""Runtime loop for the literary clock prototype."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import atomic_io
import pick_quote as pick_quote_module
from buckets import bucket_for_time

BASE_DIR = Path(__file__).resolve().parent

DEFAULT_STATE_PATH = "~/.litclock/state.json"
DEFAULT_TELEMETRY_PATH = "~/.litclock/telemetry.jsonl"
DEFAULT_TELEMETRY_RETAIN_DAYS = 90
# Matches ``daily_telemetry_path``'s suffix format: stem-YYYYMMDD. We use a
# glob and then a stricter fullmatch regex so an operator pointing --telemetry
# -path at a hand-named file can't accidentally catch unrelated siblings.
_TELEMETRY_DATE_RE = re.compile(r"^(.+)-(\d{8})$")

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


def _atomic_write_text(path: Path, payload: str) -> None:
    """Durably write ``payload`` to ``path``.

    Thin shim around :func:`atomic_io.atomic_write_text` so every caller that
    imports ``run_clock._atomic_write_text`` keeps the same contract while the
    implementation lives in one place (see ``atomic_io`` for the tmp → fsync →
    replace → dir-fsync details). Shared by ``save_runtime_state`` and the web
    UI's override writer.
    """
    atomic_io.atomic_write_text(path, payload)


def save_runtime_state(state_path: str | None, state: dict) -> None:
    """Persist runtime state atomically. No-op when disabled."""
    path = _resolve_state_path(state_path)
    if path is None:
        return
    _atomic_write_text(path, json.dumps(state, ensure_ascii=False, indent=2))


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
        # Button listener bookkeeping. ``button_handles`` is the keepalive list
        # returned by ``inky_buttons.start_listener`` (we must hold the refs
        # for the lifetime of the loop or gpiozero drops our callbacks).
        # ``buttons_dead_logged`` latches the first "listener died" warning so
        # the loop doesn't spam stderr every tick once a pin is released.
        self.button_handles: list | None = None
        self.buttons_dead_logged = False
        # Last local date we ran telemetry retention on; only re-checked on
        # date rollover so the main loop doesn't glob every tick.
        self.last_pruned_date: dt.date | None = None
        # Flipped by the SIGTERM/SIGINT handler so the main loop can exit
        # cleanly between ticks. ``threading.Event`` (not a bool) because the
        # loop's interruptible sleep polls it; a plain flag would force us to
        # keep time.sleep() in the non-interruptible form.
        self.stop_requested = threading.Event()
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


# ----------------------------------------------------------------------------
# Module-level action functions shared by the button listener thread and the
# curator web server's HTTP handler thread. Each returns a result dict so the
# web handler can serialise it to JSON (e.g. {"ok": True, "theme": "dark"} or
# {"ok": False, "error": "busy"}); button handlers ignore the return value and
# rely on the internal logging / telemetry writes for feedback.
#
# Every action:
#  - wraps its work in ``_button_render_gate`` for coalesced-press semantics,
#  - serialises state mutations via ``state.lock`` and ledger writes via
#    ``state.ledger_lock``,
#  - catches ``Exception`` so a failure in one caller can't kill the listener
#    thread or the HTTP server thread.
#
# ``label`` is the attribution prefix: ``"button A"`` when driven by GPIO,
# ``"web"`` (or a route-specific variant) when driven by an HTTP POST.
# ----------------------------------------------------------------------------

def action_skip(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Ban the currently-shown quote and render the next pick.

    Mirrors button A short-press. Returns ``{"ok": True, "new_quote_id": [...]}``,
    ``{"ok": False, "error": "busy"}`` when a render is already in flight, or
    ``{"ok": False, "error": "<repr>"}`` on exception.
    """
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
                with state.ledger_lock:
                    pick_quote_module.append_history(history_path, previous[0], previous[1])
                with state.lock:
                    # Remember what we just banned so A long-press / web unskip can reverse it.
                    state.last_skipped = previous
            time_str = current_time_str()
            quote_id = peek_quote_id(time_str, history_path=history_path, history_days=args.history_days)
            _render_unlocked(args, state, time_str, history_path, quote_id=quote_id)
            if quote_id is not None:
                with state.ledger_lock:
                    pick_quote_module.append_history(history_path, quote_id[0], quote_id[1])
            return {"ok": True, "new_quote_id": list(quote_id) if quote_id else None}
        except Exception as exc:
            _log(f"{label} skip failed: {exc!r}", err=True)
            append_telemetry(telemetry_path, {"bucket": current_bucket(), "error": repr(exc), "mode": "skip"})
            return {"ok": False, "error": repr(exc)}


def action_unskip(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Reverse the most recent skip: remove the ledger entry, pick, re-render.

    Mirrors button A long-press. The ledger read-modify-write is serialised
    against the main loop's ``append_history`` via ``state.ledger_lock`` so a
    concurrent append cannot be silently lost.
    """
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
                removed = pick_quote_module.remove_last_history_entry(history_path, target[0], target[1])
            _log(f"un-skip: removed ledger entry for source={target[0]} line={target[1]} ok={removed}")
            time_str = current_time_str()
            quote_id = peek_quote_id(time_str, history_path=history_path, history_days=args.history_days)
            _render_unlocked(args, state, time_str, history_path, quote_id=quote_id)
            if quote_id is not None:
                with state.ledger_lock:
                    pick_quote_module.append_history(history_path, quote_id[0], quote_id[1])
            return {"ok": True, "restored": list(target)}
        except Exception as exc:
            _log(f"{label} un-skip failed: {exc!r}", err=True)
            append_telemetry(telemetry_path, {"bucket": current_bucket(), "error": repr(exc), "mode": "unskip"})
            return {"ok": False, "error": repr(exc)}


def action_theme(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Toggle default ↔ dark, persist to ``--state-path``, re-render. Mirrors button B."""
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, f"{label} (theme)") as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        try:
            time_str = current_time_str()
            with state.lock:
                current = state.last_effective_theme or resolve_effective_theme(
                    state.theme_arg, time_str, state.manual_theme,
                )
                state.manual_theme = "dark" if current == "default" else "default"
                save_runtime_state(args.state_path, state.snapshot_for_persistence())
                new_theme = state.manual_theme
                quote_id = state.last_quote_id
            _log(f"{label}: theme -> {new_theme}")
            _render_unlocked(args, state, time_str, history_path, quote_id=quote_id)
            return {"ok": True, "theme": new_theme}
        except Exception as exc:
            _log(f"{label} theme toggle failed: {exc!r}", err=True)
            append_telemetry(telemetry_path, {"bucket": current_bucket(), "error": repr(exc), "mode": "theme"})
            return {"ok": False, "error": repr(exc)}


def action_quiet(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Toggle the manual quiet override, persist, display goodnight-or-wake frame.

    Mirrors button D short-press.
    """
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, f"{label} (quiet)") as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        try:
            with state.lock:
                state.manual_quiet = not state.manual_quiet
                save_runtime_state(args.state_path, state.snapshot_for_persistence())
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
                time_str = current_time_str()
                quote_id = peek_quote_id(time_str, history_path=history_path, history_days=args.history_days)
                _render_unlocked(args, state, time_str, history_path, quote_id=quote_id)
            return {"ok": True, "manual_quiet": quiet_now}
        except Exception as exc:
            _log(f"{label} quiet toggle failed: {exc!r}", err=True)
            append_telemetry(telemetry_path, {"bucket": current_bucket(), "error": repr(exc), "mode": "quiet"})
            return {"ok": False, "error": repr(exc)}


def action_rerender(args: argparse.Namespace, state: RuntimeState, *, label: str = "web") -> dict:
    """Force a re-render of the current time+bucket. Useful after panel ghosting or override edits."""
    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None
    with _button_render_gate(state, f"{label} (rerender)") as acquired:
        if not acquired:
            return {"ok": False, "error": "busy"}
        try:
            time_str = current_time_str()
            bucket = bucket_for_time(time_str)
            quote_id = peek_quote_id(time_str, history_path=history_path, history_days=args.history_days)
            _render_unlocked(args, state, time_str, history_path, bucket=bucket, quote_id=quote_id)
            if quote_id is not None:
                with state.ledger_lock:
                    pick_quote_module.append_history(history_path, quote_id[0], quote_id[1])
            _log(f"{label}: rerender bucket={bucket}")
            return {"ok": True, "bucket": bucket, "quote_id": list(quote_id) if quote_id else None}
        except Exception as exc:
            _log(f"{label} rerender failed: {exc!r}", err=True)
            append_telemetry(telemetry_path, {"bucket": current_bucket(), "error": repr(exc), "mode": "rerender"})
            return {"ok": False, "error": repr(exc)}


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


def prune_telemetry(telemetry_path: str | None, retain_days: int, today: dt.date | None = None) -> int:
    """Delete date-rotated telemetry siblings older than ``retain_days``. Returns count deleted.

    ``daily_telemetry_path`` rotates per local date so each file stays bounded,
    but without a retention sweep the directory grows unbounded over months.
    We glob the base path's directory for ``<stem>-YYYYMMDD<suffix>`` siblings
    (using a stricter regex than the glob so a hand-named file with a numeric
    stem isn't mistaken for rotation output), parse the date suffix, and
    ``unlink`` anything older than today minus ``retain_days``.

    Defensive: swallows every per-file exception so one unreadable sibling
    can't block pruning of the rest; returns the count of successful unlinks
    for observability. A zero-or-negative retain_days disables pruning.
    """
    if not telemetry_path or retain_days <= 0:
        return 0
    if today is None:
        today = dt.date.today()
    cutoff = today - dt.timedelta(days=retain_days)
    try:
        base = Path(telemetry_path).expanduser()
        parent = base.parent
        if not parent.exists():
            return 0
        stem = base.stem
        suffix = base.suffix or ".jsonl"
        pattern = f"{stem}-*{suffix}"
        removed = 0
        for candidate in parent.glob(pattern):
            match = _TELEMETRY_DATE_RE.fullmatch(candidate.stem)
            if match is None or match.group(1) != stem:
                continue
            try:
                file_date = dt.datetime.strptime(match.group(2), "%Y%m%d").date()
            except ValueError:
                continue
            if file_date < cutoff:
                with contextlib.suppress(OSError):
                    candidate.unlink()
                    removed += 1
        return removed
    except OSError as exc:
        _log(f"telemetry prune failed for {telemetry_path!r}: {exc!r}", err=True)
        return 0


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
