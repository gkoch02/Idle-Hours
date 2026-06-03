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

from idle_hours import pick_quote as pick_quote_module
from idle_hours import pidfile, runtime_config, runtime_webhook, sd_notify
from idle_hours.buckets import bucket_for_time
from idle_hours.path_resolution import resolve_input_path
from idle_hours.runtime_actions import (  # noqa: F401  re-exported for web_server + tests
    _button_render_gate,
    action_quiet,
    action_rerender,
    action_skip,
    action_theme,
    action_unskip,
)
from idle_hours.runtime_log import _log  # noqa: F401  re-exported
from idle_hours.runtime_quiet import (  # noqa: F401  in_quiet_hours + _display_quiet_image re-exported
    _display_quiet_image,
    compute_quiet,
    enter_quiet,
    exit_quiet,
    in_quiet_hours,
)
from idle_hours.runtime_state import RuntimeState  # noqa: F401  re-exported
from idle_hours.runtime_store import (  # noqa: F401  load_runtime_state re-exported for tests
    DEFAULT_STATE_PATH,
    load_runtime_state,
    save_runtime_state,
)
from idle_hours.runtime_telemetry import (  # noqa: F401  daily_telemetry_path re-exported for tests
    DEFAULT_TELEMETRY_PATH,
    DEFAULT_TELEMETRY_RETAIN_DAYS,
    append_heartbeat,
    append_telemetry,
    daily_telemetry_path,
    prune_telemetry,
)
from idle_hours.runtime_theme import (  # noqa: F401  auto_theme_for + _maybe_reset_* re-exported for tests
    _auto_theme_kwargs,
    _maybe_reset_manual_theme_at_midnight,
    auto_theme_for,
    pick_next_random_theme,
    pick_random_theme,
    random_theme_pool,
    recent_window_size,
    resolve_effective_theme,
)

BASE_DIR = Path(__file__).resolve().parent

# Bounds on the render / display / shutdown subprocesses so a wedged child
# (Pillow encode stuck on a font load, inky.show() waiting on a dead I2C bus,
# sudo hanging on PAM) can't stall the entire main loop indefinitely. These
# are SAFETY NETS, not expected durations — set wide enough that a normal
# Spectra 6 refresh (10–20s) plus display_inky's internal 3× retry with
# backoff (up to ~5s) fits comfortably. We use ``subprocess.run(timeout=...)``
# rather than ``check_call(timeout=...)`` because ``run`` kills the child on
# TimeoutExpired before re-raising; ``check_call`` leaves the zombie.
RENDER_TIMEOUT_SECONDS = 45
DISPLAY_TIMEOUT_SECONDS = 60
SHUTDOWN_TIMEOUT_SECONDS = 30

# Outer-loop backoff after repeated render/display failures. Every N
# consecutive failures we skip the next block of ticks; the skip grows
# exponentially up to BACKOFF_MAX_SECONDS so a hard hardware fault stops
# thrashing the log / GPIO thread.
BACKOFF_EVERY_N_FAILURES = 3
BACKOFF_MAX_SECONDS = 15 * 60

# Minimum wall-clock spacing between loop-heartbeat telemetry writes. The
# heartbeat is a positive "I'm ticking" signal that works during quiet
# hours and between bucket changes, but writing on every tick of a
# default 60s loop would be noisy and on a 1s test loop would be absurd.
HEARTBEAT_INTERVAL_SECONDS = 60


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
        "--config",
        metavar="PATH",
        default=None,
        help=(
            "Path to a TOML config file whose keys mirror the argparse dest names "
            "(e.g. `display_script = \"display_inky.py\"`). CLI flags override config "
            "values; config values override argparse defaults. See assets/config.toml.example."
        ),
    )
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
    # Kept in lockstep with render_quote.THEME_ORDER (+ "auto"). The test
    # tests/test_run_clock.py::TestCliThemeChoices pins this invariant.
    _theme_choices = [
        "default",
        "dark",
        "swiss",
        "scholar",
        "herbarium",
        "newsprint",
        "nightvision",
        "blueprint",
        "illuminated",
        "gothic",
        "bauhaus",
        "risograph",
        "comic",
        "dispatch",
        "atomic",
        "marker",
        "saloon",
        "roman",
        "alchemy",
        "grimoire",
        "deco",
        "glacier",
        "mucha",
        "chalkboard",
        "placard",
        "chanbara",
        "lcars",
        "fillmore",
        "firmament",
        "astrarium",
        "kanagawa",
        "marquee",
        "tarot",
        "vinyl",
        "vitrail",
        "cartograph",
        "questline",
        "chrono",
        "outrun",
        "circuit",
        "letter",
        "grimdark",
        "sampler",
        "anna_atkins",
        "diags",
    ]
    parser.add_argument(
        "--theme",
        choices=[*_theme_choices, "auto", "random"],
        default="default",
        help=(
            "Render theme passed through to render_quote.py. "
            "Light: 'default' (white/black/red), 'scholar' (white/blue/red), "
            "'newsprint' (white/black/no-accent), 'blueprint' (white/blue/red, "
            "geometric sans), 'illuminated' (white/red/blue, manuscript serif + "
            "blackletter ornaments), 'bauhaus' (white/black/blue with red "
            "ornaments, geometric sans), 'risograph' (white/red/blue, no black, "
            "rounded sans), 'comic' (yellow bg / black body / red accent, "
            "comic-book display face), 'dispatch' (white/black/red, Special "
            "Elite typewriter face, vintage-office dossier border with "
            "tractor-feed perforations and red rubber-stamp imprint), "
            "'atomic' (green-bg/black-body/red-accent, Atomic Age display "
            "face, mid-century border with rounded frame, atom symbol "
            "and starbursts), "
            "'marker' (white/black/blue + multi-colour decorative border, "
            "Permanent Marker hand-drawn face — fridge-doodle vibe, lights "
            "up every spot colour the Spectra 6 panel can produce), "
            "'saloon' (white/black/red, Rye wood-engraved slab serif — "
            "19th-century Wild West wanted-poster vibe, layered "
            "background with red foxing speckles, decorative banner "
            "bands, double-rule frame, corner fleurons and mid-edge "
            "diamonds), "
            "'roman' (white limestone / black body / red rubrum accent, "
            "Cinzel Decorative Trajan-column inscriptional capitals — "
            "Roman lapidary inscription vibe, tabula ansata frame with "
            "trapezoidal handles, SPQR cartouche, stone-grain speckles, "
            "mid-edge interpunct dots, and a laurel sprig), "
            "'alchemy' (yellow parchment / black IM Fell English body / "
            "red MedievalSharp matched phrase + blue Hermetic ornaments, "
            "alchemical tome with corner pentagrams, planetary mid-edge "
            "sigils, and a central transmutation circle), "
            "'deco' (white/black/red→tangerine, Righteous geometric "
            "display sans, 1930s art-deco poster — doubled hairline "
            "frame, stepped skyscraper-corner ornaments, top-centre "
            "rising-sun fan), "
            "'glacier' (white / blue Iceland body / green matched "
            "phrase→cyan, icy aurora panel with frost-crystal corner "
            "clusters and snowflake-tick mid-edges), "
            "'placard' (white / black hand-printed body / red accent, "
            "Patrick Hand SC small-caps, hand-lettered sandwich-board "
            "signage with weathered sign-painter's frame and red "
            "thumbtack corners), "
            "'diags' (white/black/red, DejaVu Sans — REPLACES the "
            "literary frame with a calibration / status panel: clock + "
            "bucket / layout / quality / source fields + the Spectra 6 "
            "native palette + 2-ink stipple recipe swatches; excluded "
            "from --theme random). "
            "Dark: 'dark' (black/white/yellow), "
            "'nightvision' (black / green Space Mono body / yellow "
            "matched phrase→lime, retro-terminal mono with CRT-style "
            "scanlines and HUD-bracket corners), "
            "'gothic' (black/white/red, EB Garamond body + "
            "UnifrakturMaguntia blackletter matched phrase + ornaments, "
            "cathedral double-rule frame with corner quatrefoils and "
            "mid-edge diamonds), "
            "'grimoire' (black / white IM Fell English body / red "
            "TFoust hollow-outline matched phrase, occultist spellbook "
            "with corner pentagrams + mid-edge planetary sigils), "
            "'chalkboard' (black slate / white Playwrite GB J Guides "
            "dotted-cursive body / yellow chalk-stick matched phrase, "
            "doubled white wooden frame, green chalk teacher's tick, "
            "coral eraser smudges along the bottom), "
            "'chanbara' (black / white Shojumaru brush body / red "
            "accent, samurai-cinema poster with a dominant red "
            "rising-sun disc anchored off-canvas in the bottom-right "
            "and a small red artist's-chop seal in the top-left), "
            "'lcars' (black/white/yellow, Antonio condensed sans, Star Trek "
            "Okudagram console panel — annular quarter-circle elbow chrome "
            "wrapping the canvas top-left and bottom-left corners in synthesised "
            "tangerine, stacked colour-coded rail blocks down the sidebar "
            "(lavender / yellow / coral / lilac / red / coral / blue), LCARS "
            "wordmark in the top bar and STARDATE callout in the bottom bar). "
            "'firmament' (navy synthesised ground / white Cardo humanist serif "
            "body / yellow→cream matched phrase, 17th-century celestial atlas — "
            "lavender Milky Way swaths in two corners, ~80 scattered yellow "
            "stars in three magnitude tiers, Cassiopeia + Orion's Belt "
            "constellation polylines, sun / crescent moon / compass rose / "
            "ringed Saturn corner ornaments, and a sky-blue ecliptic arc "
            "across the top margin). "
            "'auto' selects 'dark' between "
            "18:00 and 06:00 and 'default' otherwise — broaden the rotation via "
            "--auto-day-theme / --auto-night-theme. "
            "'random' picks a theme at random each time the displayed quote changes. "
            "Pressing button B cycles themes manually and overrides 'auto'/'random' until midnight."
        ),
    )
    parser.add_argument(
        "--auto-day-theme",
        choices=_theme_choices,
        default="default",
        help=(
            "Theme used by --theme auto during 06:00–18:00. Defaults to 'default' "
            "(legacy binary contract). Must be a registered theme name; 'auto' is rejected."
        ),
    )
    parser.add_argument(
        "--auto-night-theme",
        choices=_theme_choices,
        default="dark",
        help=(
            "Theme used by --theme auto during 18:00–06:00. Defaults to 'dark' "
            "(legacy binary contract). Must be a registered theme name; 'auto' is rejected."
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
        "--webhook-url",
        default="",
        metavar="URL",
        help=(
            "Optional HTTP endpoint that receives a JSON POST for each "
            "interesting telemetry event (errors, render/display/shutdown timeouts, "
            "backoff entered, button listener died, state validation issues). "
            "Successful renders and heartbeats are NOT posted by default. "
            "Best-effort: dispatched on a daemon thread with a 5s timeout, "
            "failures are logged but never block the loop."
        ),
    )
    parser.add_argument(
        "--webhook-all-events",
        action="store_true",
        help=(
            "Post every telemetry event to --webhook-url (except heartbeats and "
            "successful renders, which would generate alert spam). Default behaviour "
            "is to post only operationally-interesting modes — see runtime_webhook.ALERT_MODES."
        ),
    )
    parser.add_argument(
        "--telemetry-retain-days",
        type=int,
        default=DEFAULT_TELEMETRY_RETAIN_DAYS,
        help=(
            "Drop date-rotated telemetry siblings older than this many days once "
            "per local-date rollover (default: 90). idle_hours_health.py still globs "
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
            "127.0.0.1. Sent by clients as 'X-Idle-Hours-Token: <token>'. GETs remain "
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
    parser.add_argument(
        "--pidfile",
        default=pidfile.DEFAULT_PIDFILE_PATH,
        help=(
            "Path to the single-instance pidfile. Locked via fcntl.flock at "
            "loop startup; a second run_clock detects the held lock and exits 1. "
            "Stale files left by SIGKILL or power-loss are reclaimed. Pass an "
            "empty string to disable the single-instance check."
        ),
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help=(
            "Skip the startup existence checks for --render-script / --display-script "
            "/ --quiet-image / --startup-image. Escape hatch for unusual setups; "
            "normally these paths are validated so a misconfigured unit file fails "
            "loudly at startup instead of on first use."
        ),
    )
    # Two-pass parse so a ``--config PATH`` value can seed argparse's own
    # defaults before the real parse runs: argparse uses a default only
    # when the flag is absent from argv, so the surviving CLI flags
    # naturally win over config values, and absent flags fall back to
    # the argparse literal default. No bespoke merge layer, no
    # precedence-ordering bugs.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=None)
    pre_args, _ = pre.parse_known_args()
    config_path = Path(pre_args.config) if pre_args.config else None
    # Mirror argparse's own ``choices=`` gate through ``load_config`` so a
    # typoed ``mode = "produciton"`` or ``theme = "drak"`` fails at
    # startup instead of silently propagating into every render
    # subprocess. ``_actions`` is a stable argparse API used widely;
    # pulling choices from it keeps the list of valid values
    # single-seated at the ``add_argument`` call that already owns it.
    choices_map = {
        action.dest: list(action.choices)
        for action in parser._actions
        if action.choices is not None
    }
    config_defaults = runtime_config.load_config(
        config_path, hhmm_validator=_valid_hhmm, choices_map=choices_map,
    )
    if config_defaults:
        parser.set_defaults(**config_defaults)

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
        row = pick_quote_module.select_quote(
            time_str=time_str,
            history_path=history_path,
            history_days=history_days,
            database_path=pick_quote_module.DEFAULT_DATABASE_PATH,
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
    state_path = getattr(args, "state_path", None)
    if not state_path:
        return
    try:
        save_runtime_state(state_path, state.snapshot_for_persistence())
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
    # render-script is an INPUT path: prefer CWD (operator's checkout or
    # custom script) and fall back to the bundled ``idle_hours/render_quote.py``
    # when the CWD candidate doesn't exist. ``output_path`` is an OUTPUT and
    # always CWD-relative — writing into ``BASE_DIR`` would put the file
    # inside the installed package.
    render_script_path = str(resolve_input_path(render_script, BASE_DIR))
    output_path_resolved = str(Path(output_path).expanduser().resolve())
    render_start = time.monotonic()
    try:
        subprocess.run(
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
            ],
            check=True,
            timeout=RENDER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        # subprocess.run has already killed the child before re-raising; we
        # only need to telemetrise and re-raise so the main loop's error
        # handler logs + keeps last_bucket stale for retry next tick.
        _log(
            f"render subprocess timed out after {RENDER_TIMEOUT_SECONDS}s for {time_str}",
            err=True,
        )
        append_telemetry(
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
    _log(f"Rendered {time_str} -> {output_path_resolved} ({render_ms} ms)")
    display_ms: int | None = None
    if display_script:
        display_script_path = str(resolve_input_path(display_script, BASE_DIR))
        display_start = time.monotonic()
        try:
            subprocess.run(
                [python_executable, display_script_path, output_path_resolved, "--theme", theme],
                check=True,
                timeout=DISPLAY_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            _log(
                f"display subprocess timed out after {DISPLAY_TIMEOUT_SECONDS}s for {output_path_resolved}",
                err=True,
            )
            append_telemetry(
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
        new_theme, new_bag = pick_next_random_theme(
            list(state.random_theme_bag), recent=state.random_theme_recent
        )
        state.current_random_theme = new_theme
        state.random_theme_bag = new_bag
        # Roll the recent-window forward (most-recent last) and cap it at
        # ~half the pool, so the next refill keeps these themes out of the
        # new bag's draw-front. This is what prevents a tail-of-pass theme
        # from reappearing a pick or two into the next pass.
        window = recent_window_size(len(random_theme_pool()))
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
    effective_theme = resolve_effective_theme(
        state.theme_arg, time_str, state.manual_theme,
        current_random_theme=state.current_random_theme,
        **_auto_theme_kwargs(args),
    )
    actual_mode = mode or args.mode
    actual_bucket = bucket or bucket_for_time(time_str)
    render_now(
        args.render_script, args.output, args.width, args.height, args.display_script,
        actual_mode, effective_theme, time_str=time_str,
        history_path=history_path, history_days=args.history_days,
        telemetry_path=args.telemetry_path or None, bucket=actual_bucket, quote_id=quote_id,
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
        with _button_render_gate(state, "button C", "card", telemetry_path=telemetry_path) as acquired:
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

                def _restore_and_deregister() -> None:
                    try:
                        restore()
                    finally:
                        # Remove ourselves from pending_timers so we don't leak
                        # a reference. The lock is held briefly; safe inside
                        # the timer thread.
                        with state.lock:
                            with contextlib.suppress(ValueError):
                                state.pending_timers.remove(timer)

                timer = threading.Timer(5.0, _restore_and_deregister)
                # Daemon so a pending restore doesn't block process exit on SIGTERM / KeyboardInterrupt.
                timer.daemon = True
                # Register BEFORE start() so a _shutdown arriving mid-start
                # can still cancel us (Timer.cancel is a no-op if the timer
                # already fired, so the race is safe in either direction).
                with state.lock:
                    state.pending_timers.append(timer)
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
        with _button_render_gate(state, "button D", "shutdown", telemetry_path=telemetry_path) as acquired:
            if not acquired:
                return
            _log("button D held: shutdown")
            with state.lock:
                state.manual_quiet = True
                save_runtime_state(args.state_path, state.snapshot_for_persistence())
            try:
                if args.quiet_image:
                    _display_quiet_image(
                        args.quiet_image, args.output, args.display_script,
                        reason="shutdown", telemetry_path=telemetry_path,
                    )
            except Exception as exc:
                _log(f"shutdown pre-frame failed: {exc!r}", err=True)
            try:
                subprocess.run(shlex.split(cmd), check=True, timeout=SHUTDOWN_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired as exc:
                _log(
                    f"shutdown command {cmd!r} timed out after {SHUTDOWN_TIMEOUT_SECONDS}s",
                    err=True,
                )
                append_telemetry(
                    telemetry_path,
                    {
                        "bucket": current_bucket(),
                        "error": repr(exc),
                        "mode": "shutdown_timeout",
                        "timeout_seconds": SHUTDOWN_TIMEOUT_SECONDS,
                    },
                )
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
        from idle_hours import inky_buttons
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
        from idle_hours import inky_buttons
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
    """Resolve the web token from --web-token or --web-token-file for startup logging.

    Prefers the file over the inline flag when both are set so rotating the
    token is a single file edit. A missing/unreadable token file is logged and
    falls back to the inline flag (or empty), keeping the server startable even
    if the file has a transient permission hiccup.

    Note: this is the *startup* read; the live auth check uses
    :meth:`WebContext.current_token` which re-reads the file on every request
    when the mtime changes, so rotating the token doesn't need a restart.
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
        from idle_hours import web_server
    except Exception as exc:
        _log(f"web UI disabled ({exc!r}); install failure?", err=True)
        return None
    try:
        token = _resolve_web_token(args)
        handle = web_server.start_web_server(
            args, state, token=token, token_file=args.web_token_file or None,
        )
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


def _maybe_compact_history(args: argparse.Namespace, state: RuntimeState) -> None:
    """Compact the anti-repeat history ledger once per local-date rollover.

    Gated on ``state.last_compacted_date`` so the compact sweep runs at most
    once per calendar day — the ledger is a ~288-entries-per-week
    append-only file, so a per-tick compact would re-parse it needlessly.
    Serialised against button A's ``remove_last_history_entry`` rewrite via
    ``state.ledger_lock`` to avoid stepping on a concurrent un-skip.
    Best-effort: a disk hiccup here must not bubble into the render path and
    trip the outer-loop backoff counter.

    Failure-retry policy: we set ``last_compacted_date`` *before* running the
    compact, so a disk error leaves the flag set and the sweep doesn't retry
    until tomorrow. This is intentional — retrying every tick on a persistent
    fault (readonly fs, full disk) would just spam the log. The next day's
    rollover retries naturally; if compaction is truly wedged, the ledger's
    linear scan stays cheap for months before the bloat is user-visible.
    """
    history_path = args.history_path or None
    if not history_path or args.history_days <= 0:
        return
    today = dt.date.today()
    with state.lock:
        if state.last_compacted_date == today:
            return
        state.last_compacted_date = today
    try:
        with state.ledger_lock:
            dropped = pick_quote_module.compact_history(history_path, args.history_days)
    except Exception as exc:
        _log(f"history compact failed: {exc!r}", err=True)
        return
    if dropped:
        _log(f"history compact: dropped {dropped} entr{'y' if dropped == 1 else 'ies'} older than {2 * args.history_days}d")


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
    append_telemetry(
        telemetry_path,
        {
            "bucket": bucket,
            "mode": "backoff",
            "failures": failures,
            "skip_seconds": skip_seconds,
        },
    )


def _in_backoff_skip(state: RuntimeState) -> bool:
    """Return True if the loop should skip this tick because of render backoff."""
    with state.lock:
        return time.monotonic() < state.backoff_skip_until


def _maybe_emit_heartbeat(state: RuntimeState, telemetry_path: str | None) -> None:
    """Emit a loop-liveness telemetry marker, throttled to HEARTBEAT_INTERVAL_SECONDS.

    Without this, there is no positive "the loop is ticking" signal during
    quiet hours or between bucket changes — ``idle_hours_health.py`` can only
    tell that renders happened, not that the loop is alive and idle. The
    throttle is wall-clock (``time.monotonic``) so a 1s test loop doesn't
    flood telemetry even though a 60s appliance loop emits once per tick.

    On the same cadence we pet systemd's watchdog via ``sd_notify(WATCHDOG=1)``
    when ``$NOTIFY_SOCKET`` is set. The heartbeat and the watchdog ping
    share a trigger so an appliance supervised by systemd's ``WatchdogSec``
    restarts for exactly the same class of wedge that shows up as silence in
    ``idle_hours_health.py``. Off-socket (dev hosts, unit tests) the watchdog
    call is a no-op. The ping is OUTSIDE the telemetry-path gate so an
    operator who disabled telemetry still gets supervised. It is INSIDE the
    throttle gate so the watchdog cadence tracks the heartbeat cadence
    exactly.

    WatchdogSec budget: the nominal cadence is 60s (``HEARTBEAT_INTERVAL_SECONDS``)
    but the *worst-case* interval between two pings is bounded by how long a
    single tick can take before returning to this function: up to
    ``RENDER_TIMEOUT_SECONDS (45) + DISPLAY_TIMEOUT_SECONDS (60) +
    interval_seconds (60) = 165s``. ``idle-hours.service.example`` ships
    ``WatchdogSec=180s`` which leaves ~15s margin on that pathological case —
    enough for real-world wobble but not much more. Raise ``WatchdogSec`` or
    lower the render/display timeouts if your appliance sees tighter margins.
    """
    now = time.monotonic()
    with state.lock:
        if now - state.last_heartbeat_monotonic < HEARTBEAT_INTERVAL_SECONDS:
            return
        # We advance the throttle clock unconditionally once the window
        # elapses — even when telemetry is disabled — so the telemetry-off
        # and telemetry-on paths share the same cadence. The field is
        # private to this function so the "useless write when telemetry is
        # off" is free.
        state.last_heartbeat_monotonic = now
    if telemetry_path:
        append_heartbeat(telemetry_path)
    sd_notify.notify_watchdog()


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

    Also installed from the ``--once`` path against a throwaway
    :class:`RuntimeState` so ``atomic_io``'s write→fsync→replace sequence
    can complete even when systemd sends ``SIGTERM`` mid-render; the caller
    observes ``state.stop_requested`` after the render returns and surfaces
    exit code ``143`` to distinguish "rendered cleanly" from "rendered then
    told to shut down."
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
    # Cancel pending timers (currently only the source-card 5s restore) BEFORE
    # draining the render lock so a timer callback doesn't kick off a new
    # render during teardown. ``Timer.cancel`` is idempotent — a timer that
    # already fired is a no-op.
    _log("shutdown: cancelling pending timers")
    with contextlib.suppress(Exception):
        with state.lock:
            timers = list(state.pending_timers)
            state.pending_timers.clear()
        for timer in timers:
            with contextlib.suppress(Exception):
                timer.cancel()

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


_PREFLIGHT_PATH_FLAGS: tuple[tuple[str, bool], ...] = (
    # (attr, required) — required=True means missing-when-set is fatal; the
    # --display-script / --quiet-image / --startup-image flags are off-by-default
    # (None or empty string) so we only validate when the operator actually set them.
    ("render_script", True),
    ("display_script", False),
    ("quiet_image", False),
    ("startup_image", False),
)


def _preflight_paths(args: argparse.Namespace) -> list[str]:
    """Return a list of human-readable errors for missing --render-script / --display-script /
    --quiet-image / --startup-image paths.

    This catches the "typoed path in the systemd unit file" class of failure at
    startup instead of at first use (first bucket change, first quiet-hours
    entry, first cold boot). Operator-supplied relative paths resolve against
    CWD; bundled defaults are absolute strings (anchored on ``BASE_DIR``) at
    argparse-time. Both branches match the resolver used by ``render_now`` /
    ``_display_quiet_image`` so a path that passes pre-flight will also be
    found at run-time.

    Also catches the "the wheel doesn't ship static assets" class of failure
    that ``pip install idle-hours`` produces today: when ``BASE_DIR`` doesn't
    contain ``assets/quote_database.jsonl`` (the baked runtime corpus the
    picker reads by default) we surface a clear error pointing at the two
    supported install paths (``pip install -e .`` from a checkout, or the
    bundled Dockerfile). Without this, a wheel-only install would only fail
    at first render with a cryptic ``FileNotFoundError`` deep inside
    ``pick_quote``.
    """
    errors: list[str] = []
    for attr, required in _PREFLIGHT_PATH_FLAGS:
        value = getattr(args, attr, None)
        if not value:
            if required:
                errors.append(f"--{attr.replace('_', '-')} is required")
            continue
        # The "auto" sentinel for --quiet-image / --startup-image routes through
        # render_now(mode='goodnight') instead of treating value as a file path,
        # so pre-flight existence checks would reject a perfectly valid config.
        if attr in ("quiet_image", "startup_image") and value == "auto":
            continue
        # Matches the resolver used by ``render_now`` / ``_display_quiet_image``:
        # input paths try CWD first and fall back to the bundled location
        # under ``BASE_DIR``. Lets ``--render-script render_quote.py`` (a
        # config-file or default value) find the bundled script while an
        # operator's ``./my_script.py`` still wins when present.
        path = resolve_input_path(value, BASE_DIR)
        if not path.exists():
            errors.append(f"--{attr.replace('_', '-')} {value!r} does not exist (resolved to {path})")
    # Static-asset guard: the corpus is the one runtime input we cannot
    # operate without. Web assets / fonts degrade gracefully (the curator
    # UI 404s, the renderer falls back to bitmap fonts), but the picker
    # has no fallback for a missing baked DB.
    baked_db = BASE_DIR / "assets" / "quote_database.jsonl"
    raw_corpus = BASE_DIR / "assets" / "candidates-attributed.jsonl"
    if not baked_db.exists() and not raw_corpus.exists():
        errors.append(
            f"corpus assets missing at {BASE_DIR / 'assets'} (no quote_database.jsonl "
            "or candidates-attributed.jsonl). The wheel ships only Python modules; "
            "the static assets need a checkout. Install via `pip install -e .` from a "
            "git clone, or use the bundled Dockerfile."
        )
    return errors


def _run_preflight(args: argparse.Namespace) -> None:
    """Abort loudly when any configured script / image path is missing.

    Skipped entirely by ``--skip-preflight``. Raises :class:`SystemExit` with
    code 1 and a multi-line message so an operator can tell from the journal
    which file was wrong — the systemd ``ExecStart=`` field gets copied into
    the log preamble so all the context is right there.
    """
    if getattr(args, "skip_preflight", False):
        return
    errors = _preflight_paths(args)
    if errors:
        message = "pre-flight path checks failed:\n  " + "\n  ".join(errors)
        _log(message, err=True)
        raise SystemExit(1)


def main() -> int:
    args = parse_args()
    # Output is a runtime artifact (see render_now() — same rationale): resolve
    # relative paths against the caller's CWD, not against ``BASE_DIR`` (which
    # now points inside the installed ``idle_hours/`` package).
    #
    # Persist the resolved absolute path back onto ``args.output`` so every
    # downstream consumer (``web_server.WebContext``, ``runtime_quiet`` paths,
    # the render-subprocess flag plumbing in ``render_now``) sees the same
    # absolute path and can't drift apart. Without this, a relative
    # ``args.output = "output/current.png"`` would be re-resolved per-callsite
    # — and any consumer whose resolver still anchors on ``BASE_DIR`` would
    # silently target a different file than the main loop is writing.
    output_target = Path(args.output).expanduser()
    if not output_target.is_absolute():
        output_target = output_target.resolve()
    output_target.parent.mkdir(parents=True, exist_ok=True)
    args.output = str(output_target)

    history_path = args.history_path or None
    telemetry_path = args.telemetry_path or None

    # Wire webhook config once at startup so every later append_telemetry
    # call (across run_clock, runtime_actions, runtime_quiet, web_server)
    # picks up the destination without per-call plumbing. Empty URL =
    # disabled; runtime_webhook.configure handles that explicitly.
    runtime_webhook.configure(
        getattr(args, "webhook_url", "") or None,
        all_events=getattr(args, "webhook_all_events", False),
    )

    _run_preflight(args)

    if args.once:
        # Install signal handlers for the --once path too so a mid-render
        # SIGTERM / SIGINT doesn't truncate whatever atomic_io is currently
        # writing (the PNG, the history ledger, telemetry). The handler sets
        # a flag on the throwaway RuntimeState; atomic_io's write→fsync→
        # replace sequence is not interruptible at the OS level, so even a
        # signal arriving mid-render unwinds cleanly through the normal
        # return path.
        once_state = RuntimeState(args.theme)
        _install_signal_handlers(once_state)
        time_str = current_time_str()
        if args.theme == "random" and once_state.manual_theme is None:
            once_state.current_random_theme = pick_random_theme()
        effective_theme = resolve_effective_theme(
            args.theme, time_str, manual_theme=None,
            current_random_theme=once_state.current_random_theme,
            **_auto_theme_kwargs(args),
        )
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
        # If a signal arrived during the render, propagate a nonzero exit so
        # cron / systemd one-shot units can distinguish "rendered cleanly"
        # from "rendered then told to shut down." The render itself already
        # completed durably.
        return 143 if once_state.stop_requested.is_set() else 0

    # Single-instance lock. Without this, overlapping ``systemctl restart``
    # cycles (or a botched boot that races a slow-to-die predecessor) can
    # briefly have two run_clock processes writing to state.json /
    # history.jsonl / telemetry concurrently — atomic_io guards against
    # crashes but not concurrent writers.
    pidfile_handle: pidfile.PidfileHandle | None = None
    try:
        pidfile_handle = pidfile.acquire_pidfile(args.pidfile)
    except pidfile.PidfileLockedError as exc:
        _log(str(exc), err=True)
        return 1

    persisted = load_runtime_state(args.state_path, telemetry_path=telemetry_path)
    state = RuntimeState(args.theme, persisted=persisted)

    # Startup frame: push a static image to the panel before the first quote
    # renders so viewers see something intentional instead of yesterday's
    # ghosted frame during cold boot. Best-effort; a missing file is logged
    # and the loop continues to the first real render. Runs BEFORE the button
    # listener starts so a press during the (potentially slow) Inky push can't
    # collide with the unlocked display call.
    if args.startup_image == "auto":
        # On-the-fly goodnight frame in the active theme. Honours any persisted
        # ``manual_theme`` so an operator who pressed button B before reboot
        # still gets their chosen theme on cold boot, not just the --theme arg.
        try:
            time_str = current_time_str()
            effective_theme = resolve_effective_theme(
                args.theme, time_str, state.manual_theme,
                current_random_theme=state.current_random_theme,
                **_auto_theme_kwargs(args),
            )
            render_now(
                args.render_script, args.output, args.width, args.height, args.display_script,
                "goodnight", effective_theme, time_str=time_str,
                history_path=history_path, history_days=args.history_days,
                telemetry_path=telemetry_path, bucket=None, quote_id=None,
            )
        except Exception as exc:
            _log(f"startup image render failed: {exc!r}", err=True)
    elif args.startup_image:
        try:
            _display_quiet_image(
                args.startup_image, args.output, args.display_script,
                reason="startup", telemetry_path=telemetry_path,
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

    # Notify systemd (Type=notify) that startup is complete. Off-socket this is
    # a no-op. We do this AFTER buttons + web + signal handlers are all armed
    # so a ``systemctl start`` that blocks on READY=1 only returns once the
    # appliance is actually able to respond to SIGTERM cleanly and answer
    # GPIO / HTTP ingress — otherwise systemd could start follow-on units
    # ahead of us being fully ready.
    sd_notify.notify_ready()

    try:
        while not state.stop_requested.is_set():
            time_str = current_time_str()
            _maybe_reset_manual_theme_at_midnight(args, state)
            _check_button_liveness(state, telemetry_path)
            _maybe_prune_telemetry(args, state, telemetry_path)
            _maybe_compact_history(args, state)
            _maybe_emit_heartbeat(state, telemetry_path)

            # If the render path has failed repeatedly, skip the render
            # attempt this tick (but keep the heartbeat / button liveness
            # checks above so the appliance is still observably alive during
            # the backoff window).
            if _in_backoff_skip(state):
                if _loop_sleep(state, max(1, args.interval_seconds)):
                    break
                continue

            now_quiet, manual_only = compute_quiet(args, state, time_str)

            if now_quiet:
                if not state.was_quiet:
                    enter_quiet(args, state, time_str, manual_only=manual_only)
                    state.was_quiet = True
                # Interruptible sleep so SIGTERM-during-quiet-hours wakes us up
                # within one tick instead of sitting on the full interval.
                if _loop_sleep(state, max(1, args.interval_seconds)):
                    break
                continue

            if state.was_quiet:
                _log("quiet hours end, resuming normal render cycle")
                exit_quiet(state)
                # Falling-edge marker paired with the enter_quiet emission so
                # idle_hours_health can count balanced quiet windows (and an
                # operator can spot "we stopped rendering because we entered
                # quiet" vs "we stopped rendering because we wedged").
                append_telemetry(telemetry_path, {"mode": "quiet_exit"})
                state.was_quiet = False

            bucket = current_bucket()
            effective_theme = resolve_effective_theme(
                state.theme_arg, time_str, state.manual_theme,
                current_random_theme=state.current_random_theme,
                **_auto_theme_kwargs(args),
            )
            bucket_changed = bucket != state.last_bucket
            theme_changed = effective_theme != state.last_effective_theme and state.last_effective_theme is not None
            if bucket_changed or theme_changed:
                try:
                    quote_id = peek_quote_id(time_str, history_path=history_path, history_days=args.history_days)
                    new_rnd = _maybe_pick_random_theme(state, quote_id)
                    if new_rnd is not None:
                        effective_theme = new_rnd
                        # Recompute so the dedup check below reflects the new pick.
                        theme_changed = (
                            effective_theme != state.last_effective_theme
                            and state.last_effective_theme is not None
                        )
                    if quote_id is not None and quote_id == state.last_quote_id and not theme_changed:
                        _log(f"bucket {bucket}: quote unchanged, skipping redraw")
                        # A successful peek that matches the last-rendered quote is still
                        # a "the render path is healthy" signal — reset backoff counters
                        # alongside last_bucket so a streak of below-threshold failures
                        # (consecutive_render_failures < BACKOFF_EVERY_N_FAILURES) doesn't
                        # accumulate across dedup-skipped ticks and trip a bogus skip window.
                        with state.lock:
                            state.last_bucket = bucket
                            state.consecutive_render_failures = 0
                            state.backoff_skip_until = 0.0
                    else:
                        with state.render_lock:
                            render_now(
                                args.render_script, args.output, args.width, args.height, args.display_script,
                                args.mode, effective_theme, time_str=time_str,
                                history_path=history_path, history_days=args.history_days,
                                telemetry_path=telemetry_path, bucket=bucket, quote_id=quote_id,
                            )
                        state.commit_render_result(bucket, effective_theme, quote_id)
                        _persist_state_after_render(args, state)
                        if quote_id is not None:
                            _append_history_after_render(state, history_path, quote_id)
                except Exception as exc:
                    # Keep the loop alive so a transient failure (pick_quote crash, Inky I/O,
                    # missing corpus row, etc.) does not kill the appliance. last_bucket stays
                    # stale so the next tick retries.
                    #
                    # Error-log dedup latch: when the same ``repr(exc)`` repeats
                    # back-to-back (the outer-loop backoff window is retrying
                    # the same hardware fault), drop the stderr+traceback
                    # emission so journald doesn't fill with identical
                    # tracebacks. The structured telemetry entry is still
                    # written every time so ``idle_hours_health.py`` sees the
                    # full failure count. The latch clears on the next success
                    # via ``commit_render_result``, so a genuinely new error
                    # after a recovery still logs loudly.
                    error_repr = repr(exc)
                    with state.lock:
                        is_repeat = state.last_logged_error == error_repr
                        state.last_logged_error = error_repr
                    if not is_repeat:
                        _log(f"render/display failed for bucket {bucket}: {error_repr}", err=True)
                        traceback.print_exc(file=sys.stderr)
                    append_telemetry(telemetry_path, {"bucket": bucket, "error": error_repr, "mode": args.mode})
                    _record_render_failure(state, telemetry_path, bucket)
            elif state.last_effective_theme is None:
                with state.lock:
                    state.last_effective_theme = effective_theme
            if _loop_sleep(state, max(1, args.interval_seconds)):
                break
    finally:
        _shutdown(args, state, web_handle)
        if pidfile_handle is not None:
            pidfile_handle.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
