"""The render path: pick the quote, run the renderer, push it to the panel.

``render_now`` runs the renderer subprocess (and the display script, when one
is configured) for one frame. ``_render_unlocked`` resolves the theme, renders
and commits the frame's identity on ``RuntimeState``. ``peek_quote_id`` asks
the picker which row is current, and ``displayed_quote`` returns the one on the
panel. ``_record_render_failure`` advances the backoff after a failed render.

The main loop, the button and web actions and the quiet-hours frame all render
through this module, so it sits below all of them: it imports none of
``run_clock``, ``runtime_actions``, ``runtime_quiet`` or ``web_server``.

Callers in other modules read these names through the module
(``runtime_render.render_now(...)``), never ``from runtime_render import
render_now``, so a test that patches ``runtime_render.X`` reaches every caller.
Extracted from :mod:`run_clock` (issue #353).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TypedDict

from idle_hours import pick_quote as pick_quote_module
from idle_hours import runtime_store, runtime_telemetry, runtime_theme, sd_notify
from idle_hours.buckets import bucket_for_time
from idle_hours.path_resolution import resolve_input_path
from idle_hours.runtime_log import _log
from idle_hours.runtime_state import RuntimeState

BASE_DIR = Path(__file__).resolve().parent

# Bounds on the render / display subprocesses so a wedged child
# (Pillow encode stuck on a font load, inky.show() waiting on a dead I2C bus,
# sudo hanging on PAM) can't stall the entire main loop indefinitely. These
# are SAFETY NETS, not expected durations — set wide enough that a normal
# Spectra 6 refresh (10–20s) plus display_inky's internal 3× retry with
# backoff (up to ~5s) fits comfortably. We use ``subprocess.run(timeout=...)``
# rather than ``check_call(timeout=...)`` because ``run`` kills the child on
# TimeoutExpired before re-raising; ``check_call`` leaves the zombie.
RENDER_TIMEOUT_SECONDS = 45
DISPLAY_TIMEOUT_SECONDS = 60

# Outer-loop backoff after repeated render/display failures. Every N
# consecutive failures we skip the next block of ticks; the skip grows
# exponentially up to BACKOFF_MAX_SECONDS so a hard hardware fault stops
# thrashing the log / GPIO thread.
BACKOFF_EVERY_N_FAILURES = 3
BACKOFF_MAX_SECONDS = 15 * 60



def current_time_str() -> str:
    return dt.datetime.now().strftime("%H:%M")


def current_bucket() -> str:
    return bucket_for_time(current_time_str())


class CorpusKwargs(TypedDict):
    """The corpus / sidecar paths ``_corpus_kwargs`` hands to the peek and the render."""

    database_path: str
    input_path: str
    overrides_path: str


def _corpus_kwargs(args) -> CorpusKwargs:
    """Pluck the corpus / sidecar paths off an argparse Namespace.

    Single seam so the many ``peek_quote_id`` / ``render_now`` call sites don't
    each reach into ``args`` for three attributes — same pattern (and same
    rationale) as ``runtime_theme._auto_theme_kwargs``. An unset flag
    (``None``) falls back to the bundled asset.

    Both the peek and the render subprocess MUST be given the same values, or
    they can disagree about which quote is current and break the dedup check.
    """
    return {
        "database_path": args.baked_db or pick_quote_module.DEFAULT_DATABASE_PATH,
        "input_path": args.raw_corpus or pick_quote_module.DEFAULT_INPUT_PATH,
        "overrides_path": args.overrides or pick_quote_module.DEFAULT_OVERRIDES_PATH,
    }


def _corpus_render_args(
    database_path: str | None,
    input_path: str | None,
    overrides_path: str | None,
) -> list[str]:
    """Build the corpus/sidecar argv tail for the render subprocess.

    Each flag is emitted ONLY when it differs from the value ``render_quote.py``
    would compute for itself. That keeps two properties:

    * **Correctness.** When the operator relocates a path (the issue #179
      deployment), the renderer must be told — otherwise it picks from the
      bundled corpus while ``peek_quote_id`` scored against the relocated one,
      and the dedup check compares two different worlds.
    * **Backwards compatibility.** ``--render-script`` is a documented
      extension point for operator-supplied renderers, which only have to
      accept the flags that existed when they were written. Emitting these
      unconditionally would make every tick fail with argparse's "unrecognized
      arguments" exit 2 — and because the render path counts failures, the
      appliance would slide into exponential backoff and stop updating
      entirely. Omitting a flag whose value is already the renderer's default
      leaves the default-deployment argv byte-identical to what shipped
      before, so no existing custom renderer can break by upgrading.

    An operator who both relocates the corpus AND runs a custom renderer does
    have to teach it these three flags — but that is a new opt-in
    configuration, and sending the flags is the only correct behaviour there.
    """
    argv: list[str] = []
    for flag, value, default in (
        ("--database", database_path, pick_quote_module.DEFAULT_DATABASE_PATH),
        ("--input", input_path, pick_quote_module.DEFAULT_INPUT_PATH),
        ("--overrides", overrides_path, pick_quote_module.DEFAULT_OVERRIDES_PATH),
    ):
        if value and value != default:
            argv += [flag, value]
    return argv


def peek_quote_id(
    time_str: str,
    history_path: str | None = None,
    history_days: int = pick_quote_module.DEFAULT_HISTORY_DAYS,
    database_path: str | None = None,
    input_path: str | None = None,
    overrides_path: str | None = None,
) -> tuple | None:
    """Return a stable identity tuple for the quote pick_quote would return, or None on failure.

    ``matched_text`` is part of the identity because the renderer uses it to choose which
    phrase is bolded and coloured. Two picks that share (source_id, line_number, display_quote)
    but differ in matched_text (e.g. ``02:50`` vs ``02:55`` landing on the same row) still
    produce visibly different frames, so they must not dedup together.

    History params must match what the render subprocess will use so the peek's dedup
    check stays consistent with the actual render's pick. The same goes for the
    three corpus/sidecar paths: if the peek scored against the bundled assets
    while the subprocess rendered from the operator's relocated copies, the two
    would disagree about which quote is current and the dedup check would either
    suppress a needed redraw or force a redundant one.

    ``pick_quote.select_quote`` raises ``SystemExit`` when no candidate survives the quality
    gate in the target bucket or its neighbours; we swallow that alongside ``Exception`` so
    the runtime loop keeps ticking instead of aborting.
    """
    try:
        row = pick_quote_module.select_quote(
            time_str=time_str,
            history_path=history_path,
            history_days=history_days,
            database_path=database_path or pick_quote_module.DEFAULT_DATABASE_PATH,
            input_path=input_path or pick_quote_module.DEFAULT_INPUT_PATH,
            overrides_path=overrides_path or pick_quote_module.DEFAULT_OVERRIDES_PATH,
        )
    except (Exception, SystemExit) as exc:
        _log(f"pick_quote failed for {time_str}: {exc!r}", err=True)
        return None
    return (
        row.get("source_id"),
        row.get("line_number"),
        row.get("display_quote"),
        row.get("matched_text"),
    )


def _persist_state_after_render(args: argparse.Namespace, state: RuntimeState) -> None:
    """Write the render-identity triple + user toggles to ``--state-path`` after a commit.

    The three render-identity fields (``last_bucket`` / ``last_quote_id`` /
    ``last_effective_theme``) only live in RAM otherwise, so a
    ``systemctl restart`` mid-bucket forces a redraw of the same frame on
    the next startup — wasteful on a 10–20 s Spectra 6 refresh. Saving
    here (after every successful render commit) makes the triple durable
    without adding a separate heartbeat write. Best-effort: swallows
    exceptions so a disk hiccup can't bubble into the render path and
    trigger the outer-loop backoff.
    """
    state_path = args.state_path
    if not state_path:
        return
    try:
        runtime_store.save_runtime_state(state_path, state.snapshot_for_persistence())
    except Exception as exc:
        _log(f"runtime state persist after render failed: {exc!r}", err=True)


def _append_history_after_render(state: RuntimeState, history_path: str | None, quote_id: tuple) -> None:
    """Append ``quote_id`` to the anti-repeat ledger under ``state.ledger_lock``.

    Single seam for every caller that has successfully rendered a new quote —
    the main loop's bucket-change branch and the ``action_*`` handlers for
    skip / un-skip / rerender. Must NOT be called by theme or quiet toggles,
    which repaint the same quote and would otherwise double-record it.
    """
    with state.ledger_lock:
        pick_quote_module.append_history(history_path, quote_id[0], quote_id[1])


def displayed_quote(state: RuntimeState) -> tuple[str | None, tuple | None]:
    """Return ``(bucket, quote_id)`` for the frame currently on the panel, or ``(None, None)``.

    The "repaint what is on the panel" seam (issue #275), used by every
    repaint (theme change, button-C source card and its restore,
    ``action_rerender``) instead of re-peeking. A peek is history-filtered:
    the quote on the panel was appended to the anti-repeat ledger when it
    rendered, so a peek excludes it and returns the *next-best* row. Callers
    fall back to a fresh peek only when nothing has been committed yet (first
    tick after a cold boot).
    """
    with state.lock:
        return state.last_bucket, state.last_quote_id


def _pin_key_for(quote_id) -> tuple | None:
    """Build a ``--pin-quote`` key from a peeked/committed quote identity.

    ``quote_id`` is ``(source_id, line_number, display_quote, matched_text)``.
    ``matched_text`` rides along as the third pin element because
    ``(source_id, line_number)`` is NOT a unique corpus row key — one source
    line can carry several time phrases, and pinning on the bare key renders
    whichever duplicate happens to come first on disk.

    Tolerates a short tuple: ``last_quote_id`` is restored from ``state.json``
    without a pinned length (the identity shape has grown before), so a legacy
    3-element persisted value degrades to an unqualified pin rather than
    raising IndexError on the render path.
    """
    if quote_id is None or len(quote_id) < 2:
        return None
    if len(quote_id) > 3 and quote_id[3] is not None:
        return (quote_id[0], quote_id[1], quote_id[3])
    return (quote_id[0], quote_id[1])


# What ``--render-script`` names. The bundled renderer is launched as a module,
# not by file path, because the file is becoming a package (issue #335): the
# command ``python -m idle_hours.render_quote`` works on both sides of that move,
# while a path to ``render_quote.py`` stops existing. ``"auto"`` matches the
# sentinel ``--quiet-image`` / ``--startup-image`` already use for "render with
# the bundled renderer".
BUNDLED_RENDER_SCRIPT = "auto"
BUNDLED_RENDERER_MODULE = "idle_hours.render_quote"
# Every config written before #335 says this, including every appliance built
# from ``config.toml.example``. It keeps meaning "the bundled renderer".
_LEGACY_BUNDLED_RENDER_SCRIPT = "render_quote.py"


def _uses_bundled_renderer(render_script: str) -> bool:
    """True when ``render_script`` selects the bundled renderer, not a file.

    The legacy literal counts only when no ``./render_quote.py`` exists in the
    working directory. That is exactly when ``resolve_input_path`` used to fall
    back to the bundled file. An operator's own file of that name, in the
    working directory, still wins, as it always did.
    """
    if render_script == BUNDLED_RENDER_SCRIPT:
        return True
    if render_script == _LEGACY_BUNDLED_RENDER_SCRIPT:
        return not Path(render_script).exists()
    return _is_former_bundled_renderer_path(render_script)


def _is_former_bundled_renderer_path(render_script: str) -> bool:
    """True for a path to where the single-file renderer used to live (issue #364).

    Hand-written appliance configs named it by absolute path
    (``/home/pi/IdleHours/idle_hours/render_quote.py``), which stopped existing
    in #335. Only that exact file counts, and only while it is missing: a
    ``render_quote.py`` anywhere else is an operator's own renderer, and an old
    path from a checkout that has since moved still fails preflight with a hint.
    """
    if not render_script or Path(render_script).name != _LEGACY_BUNDLED_RENDER_SCRIPT:
        return False
    path = Path(render_script).expanduser()
    if path.exists():
        return False
    try:
        return path.resolve() == BASE_DIR / _LEGACY_BUNDLED_RENDER_SCRIPT
    except (OSError, RuntimeError):
        return False


def _render_command(render_script: str) -> list[str]:
    """The argv prefix that launches the renderer; the flags follow it.

    A custom renderer is an INPUT path: prefer CWD (the operator's checkout or
    script) and fall back to ``BASE_DIR``. ``output_path`` in ``render_now`` is
    an OUTPUT and always CWD-relative, because writing into ``BASE_DIR`` would
    put the file inside the installed package.
    """
    if _uses_bundled_renderer(render_script):
        if _package_imported_from_cwd():
            return [sys.executable, "-m", BUNDLED_RENDERER_MODULE]
        return [sys.executable, "-P", "-m", BUNDLED_RENDERER_MODULE]
    return [sys.executable, str(resolve_input_path(render_script, BASE_DIR))]


def _package_imported_from_cwd() -> bool:
    """Whether this process found ``idle_hours`` in the working directory.

    ``python -m`` puts the working directory first on the child's ``sys.path``.
    A file-path launch put the script's own directory there instead, which
    holds no ``idle_hours/``. So when the working directory holds some other
    ``idle_hours/`` tree (``idle-hours run`` from a checkout while a wheel is
    installed), the child would render with different code than this process
    peeked with. ``-P`` (Python 3.11+) leaves the working directory off the
    child's path, unless that is where this process's own package came from.
    """
    try:
        package_file = sys.modules["idle_hours"].__file__
        # A namespace package has no __file__, so no checkout to compare.
        return package_file is not None and Path(package_file).resolve().parent.parent == Path.cwd().resolve()
    except (KeyError, OSError):
        return False


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
    database_path: str | None = None,
    input_path: str | None = None,
    overrides_path: str | None = None,
    pin_quote: tuple | None = None,
) -> None:
    if time_str is None:
        time_str = current_time_str()
    render_command = _render_command(render_script)
    output_path_resolved = str(Path(output_path).expanduser().resolve())
    render_start = time.monotonic()
    try:
        subprocess.run(
            [
                *render_command,
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
                # Pin the subprocess to the exact row the caller peeked (or is
                # repainting): the subprocess otherwise re-picks with the
                # anti-repeat filter, which excludes the currently-displayed
                # quote and silently swaps it on theme-only changes (#190).
                # The matched_text element is not optional in practice —
                # (source_id, line_number) is a non-unique row key, so without
                # it the subprocess can render a different phrase (and a
                # different bucket) than the one we just committed.
                *(["--pin-quote", f"{pin_quote[0]}:{pin_quote[1]}"] if pin_quote else []),
                *(["--pin-matched-text", str(pin_quote[2])] if pin_quote and len(pin_quote) > 2 else []),
                *_corpus_render_args(database_path, input_path, overrides_path),
            ],
            check=True,
            timeout=RENDER_TIMEOUT_SECONDS,
            # Silence the child's corpus-degradation warnings: this process
            # peeked the same corpus moments ago and has already emitted them,
            # latched per file version. Without this a fresh child re-warns on
            # every repaint, since the latch is module-level and it starts with
            # empty globals. Passed as an environment variable rather than a
            # flag because ``_corpus_render_args`` above documents why the
            # subprocess argv must stay recognisable to an operator's own
            # ``--render-script`` — an unknown env var is ignored, an unknown
            # flag exits 2 and takes the appliance into backoff.
            env={**os.environ, pick_quote_module.SUPPRESS_WARNINGS_ENV: "1"},
        )
    except subprocess.TimeoutExpired as exc:
        # subprocess.run has already killed the child before re-raising; we
        # only need to telemetrise and re-raise so the main loop's error
        # handler logs + keeps last_bucket stale for retry next tick.
        sd_notify.notify_watchdog()
        _log(
            f"render subprocess timed out after {RENDER_TIMEOUT_SECONDS}s for {time_str}",
            err=True,
        )
        runtime_telemetry.append_telemetry(
            telemetry_path,
            {
                "bucket": bucket,
                "error": repr(exc),
                "mode": "render_timeout",
                "timeout_seconds": RENDER_TIMEOUT_SECONDS,
            },
        )
        raise
    render_ms = int((time.monotonic() - render_start) * 1000)
    # Pet the watchdog at every subprocess boundary, not only from the tick-top
    # heartbeat (#236). ``WatchdogSec`` is meant to ask "is this process still
    # executing", but a tick-only ping made it measure "did a tick complete" —
    # and a tick can also spend up to a full render+display waiting on
    # ``render_lock`` behind the source-card restore timer or a quiet-hours
    # entry, a term the old 165 s budget never included. Pinging here (and
    # before the loop's blocking acquire) bounds the gap between pings by a
    # single subprocess timeout rather than by a whole tick, so a slow-but-
    # working appliance is never killed by the supervisor that exists to
    # prevent downtime. Cheap and safe from any thread: a no-op datagram when
    # ``$NOTIFY_SOCKET`` is unset.
    sd_notify.notify_watchdog()
    _log(f"Rendered {time_str} -> {output_path_resolved} ({render_ms} ms)")
    display_ms: int | None = None
    if display_script:
        display_script_path = str(resolve_input_path(display_script, BASE_DIR))
        display_start = time.monotonic()
        try:
            subprocess.run(
                [sys.executable, display_script_path, output_path_resolved, "--theme", theme],
                check=True,
                timeout=DISPLAY_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            sd_notify.notify_watchdog()
            _log(
                f"display subprocess timed out after {DISPLAY_TIMEOUT_SECONDS}s for {output_path_resolved}",
                err=True,
            )
            runtime_telemetry.append_telemetry(
                telemetry_path,
                {
                    "bucket": bucket,
                    "error": repr(exc),
                    "mode": "display_timeout",
                    "timeout_seconds": DISPLAY_TIMEOUT_SECONDS,
                },
            )
            raise
        display_ms = int((time.monotonic() - display_start) * 1000)
        sd_notify.notify_watchdog()
        _log(f"Displayed {output_path_resolved} via {display_script_path} ({display_ms} ms)")
    if telemetry_path:
        runtime_telemetry.append_telemetry(
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


# Render modes that produce a "normal" frame whose (bucket, quote_id, theme)
# identity is what the operator expects to see on the panel. Anything outside
# this set is a transient overlay (currently just ``"card"`` from the button-C
# source-card handler) that the restore timer will replace within a few
# seconds — we must NOT commit or persist its identity or a process death
# inside that window would leave the overlay pinned on-screen forever (the
# next-boot dedup check would see ``last_bucket``/``last_quote_id`` match the
# current tick and skip the redraw).
_IDENTITY_RENDER_MODES: frozenset[str] = frozenset({"production", "debug"})


def _maybe_pick_random_theme(state: RuntimeState, quote_id: tuple | None) -> str | None:
    """Pick a new random theme when the quote changes in ``--theme random`` mode.

    Returns the newly-chosen theme name when a pick was made (the caller should
    update ``effective_theme`` and recompute ``theme_changed``), or ``None``
    when the mode is inactive, a manual override is in effect, or the quote
    hasn't changed and a theme is already stored.

    Picks are drained from :attr:`RuntimeState.random_theme_bag` (a shuffled
    pass through the full cycle) so every theme is shown once before any
    repeat. When the bag empties it's refilled with a fresh shuffle, and the
    themes in :attr:`RuntimeState.random_theme_recent` (the last ~half-pool
    picks) are held out of the new bag's draw-front so a theme shown at the
    tail of one pass can't reappear at the head of the next.

    The gate uses :attr:`RuntimeState.last_random_quote_id` (advanced
    synchronously by this function), not ``last_quote_id`` (advanced only by
    ``commit_render_result`` on render success). The split matters when a
    render fails: the main loop / action handler leaves ``last_quote_id``
    stale and retries the same ``quote_id`` on the next tick — gating on
    ``last_random_quote_id`` keeps that retry idempotent so the bag isn't
    drained for a theme the panel never actually showed. The theme picked on
    the failed tick is held on ``current_random_theme`` and used by the
    eventual successful render, so the bag draw maps 1:1 to a displayed
    theme even across N failed retries.
    """
    if state.theme_arg != "random" or state.manual_theme is not None:
        return None
    # The gate check and the bag drain must happen atomically: the main loop and
    # a concurrent button-A / web skip both call this, and a lock-free gate read
    # would let two threads pass for the same quote_id and double-drain the bag,
    # breaking the documented 1:1 bag-draw-to-displayed-theme invariant.
    with state.lock:
        quote_changed = (
            (quote_id is not None and quote_id != state.last_random_quote_id)
            or state.current_random_theme is None
        )
        if not quote_changed:
            return None
        new_theme, new_bag = runtime_theme.pick_next_random_theme(
            list(state.random_theme_bag), recent=state.random_theme_recent
        )
        state.current_random_theme = new_theme
        state.random_theme_bag = new_bag
        # Roll the recent-window forward (most-recent last) and cap it at
        # ~half the pool, so the next refill keeps these themes out of the
        # new bag's draw-front. This is what prevents a tail-of-pass theme
        # from reappearing a pick or two into the next pass.
        window = runtime_theme.recent_window_size(len(runtime_theme.random_theme_pool()))
        state.random_theme_recent = (state.random_theme_recent + [new_theme])[-window:]
        state.last_random_quote_id = quote_id
    return new_theme


def _render_unlocked(args: argparse.Namespace, state: RuntimeState, time_str: str, history_path: str | None,
                     mode: str | None = None, bucket: str | None = None, quote_id: tuple | None = None) -> None:
    """Core render-and-push. The caller MUST already hold ``state.render_lock``.

    Split out from :func:`_do_render` so a button handler can take the render
    lock non-blocking via :func:`_button_render_gate`, hold it for the handler's
    full duration (state mutations + render + display push), and drop follow-up
    presses that land while a 10–20 s Spectra 6 refresh is still in flight
    instead of queuing behind it.
    """
    effective_theme = runtime_theme.resolve_effective_theme(
        state.theme_arg, time_str, state.manual_theme,
        current_random_theme=state.current_random_theme,
        **runtime_theme._auto_theme_kwargs(args),
    )
    actual_mode = mode or args.mode
    actual_bucket = bucket or bucket_for_time(time_str)
    render_now(
        args.render_script, args.output, args.width, args.height, args.display_script,
        actual_mode, effective_theme, time_str=time_str,
        history_path=history_path, history_days=args.history_days,
        telemetry_path=args.telemetry_path or None, bucket=actual_bucket, quote_id=quote_id,
        pin_quote=_pin_key_for(quote_id),
        **_corpus_kwargs(args),
    )
    if actual_mode in _IDENTITY_RENDER_MODES:
        state.commit_render_result(actual_bucket, effective_theme, quote_id)
        # Persist the render-identity triple so a mid-bucket restart doesn't
        # redraw the frame already on the panel. Best-effort: a disk error
        # here must never fail the render path.
        _persist_state_after_render(args, state)
    else:
        # Transient overlay (e.g. source card): the frame is about to be
        # replaced by the restore timer, so don't let its identity land in
        # the dedup triple. We DO still reset the render-failure backoff
        # because the render itself succeeded — that's orthogonal to dedup.
        with state.lock:
            state.consecutive_render_failures = 0
            state.backoff_skip_until = 0.0


def _do_render(args: argparse.Namespace, state: RuntimeState, time_str: str, history_path: str | None,
               mode: str | None = None, bucket: str | None = None, quote_id: tuple | None = None) -> None:
    """Blocking render-and-push. Acquires ``state.render_lock`` and delegates to
    :func:`_render_unlocked`. Used by the source-card restore timer (which must
    not be dropped, or the card would stay up) and tests.
    """
    with state.render_lock:
        _render_unlocked(args, state, time_str, history_path, mode=mode, bucket=bucket, quote_id=quote_id)




def _record_render_failure(state: RuntimeState, telemetry_path: str | None, bucket: str | None) -> None:
    """Advance the outer-loop backoff state after a render/display exception.

    Every ``BACKOFF_EVERY_N_FAILURES`` consecutive failures we extend
    ``backoff_skip_until`` so the next tick (or ticks) no-op. The skip grows
    exponentially — 2^n seconds capped at ``BACKOFF_MAX_SECONDS`` — so a
    pulled ribbon cable degrades to "retry once every 15 min" instead of
    "retry every --interval-seconds forever and drown the log." The counter
    is reset by ``RuntimeState.commit_render_result`` on any success.
    """
    with state.lock:
        state.consecutive_render_failures += 1
        failures = state.consecutive_render_failures
        if failures % BACKOFF_EVERY_N_FAILURES != 0:
            return
        # n is the backoff "level" — 1 at the first threshold, 2 at the
        # second, etc. 2**n gives 2s, 4s, 8s, 16s, ... capped at 15 min.
        level = failures // BACKOFF_EVERY_N_FAILURES
        skip_seconds = min(2 ** level, BACKOFF_MAX_SECONDS)
        state.backoff_skip_until = time.monotonic() + skip_seconds
    _log(
        f"render failures: {failures} consecutive; backing off {skip_seconds}s",
        err=True,
    )
    runtime_telemetry.append_telemetry(
        telemetry_path,
        {
            "bucket": bucket,
            "mode": "backoff",
            "failures": failures,
            "skip_seconds": skip_seconds,
        },
    )
