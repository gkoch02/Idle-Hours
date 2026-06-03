"""Mutable runtime state shared between the main loop, button listener, and web server.

Extracted from :mod:`run_clock` as part of the orchestrator slim-down. The class
itself has no logic — it's the synchronisation vocabulary that the loop, GPIO
listener thread, and curator web server all agree on. ``run_clock.RuntimeState``
is preserved as a re-export so existing call sites keep resolving.
"""
from __future__ import annotations

import datetime as dt
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - type-checking only
    from threading import Timer


from idle_hours.theme_names import known_theme_names as _known_theme_names


class RuntimeState:
    """Mutable shared state between the main loop and the button listener thread.

    Button handlers act synchronously in their own thread and serialize against
    the main loop via :attr:`render_lock`. Per-button mutations of theme/quiet
    state are guarded by :attr:`lock`.
    """

    def __init__(self, theme_arg: str, persisted: dict | None = None):
        self.lock = threading.Lock()
        self.render_lock = threading.Lock()
        # Serialises read-modify-write of ~/.idle-hours/history.jsonl. Button A's
        # long-press does a remove-last-entry that would otherwise race the main
        # loop's post-render append and silently drop it.
        self.ledger_lock = threading.Lock()
        # CLI ``--theme`` value — any registered theme name in
        # ``render_quote.THEMES`` (default/dark/scholar/newsprint/nightvision
        # at the time of writing), ``"auto"``, or ``"random"``. Stored verbatim;
        # resolved to an effective render theme per-tick via ``resolve_effective_theme``.
        self.theme_arg = theme_arg
        # Button-B / web dropdown override, cleared at midnight when
        # ``theme_arg`` is ``"auto"`` or ``"random"``. Any registered theme name or ``None``.
        self.manual_theme: str | None = None
        # Current theme for ``--theme random``; updated by the main loop when
        # the displayed quote changes. Not persisted — a restart picks a fresh
        # random theme on the first render.
        self.current_random_theme: str | None = None
        # quote_id the current random pick was paired with. Gates
        # ``_maybe_pick_random_theme`` so a render-failure retry on the same
        # quote_id is idempotent: without this, every retry tick would
        # consume another bag entry (since the main loop leaves
        # ``last_quote_id`` stale on failure) and the visible pass would
        # silently lose themes. Not persisted, same rationale as
        # ``current_random_theme``.
        self.last_random_quote_id: tuple | None = None
        # Shuffled bag of themes not yet drawn in the current pass. Drained
        # one entry per quote change; refilled (reshuffled) when empty so
        # every theme is shown once before any repeat. Not persisted — a
        # restart starts a fresh pass, same rationale as
        # ``current_random_theme``.
        self.random_theme_bag: list[str] = []
        # Rolling window of the most-recently-drawn themes (most-recent last),
        # capped at ~half the pool. Carried across the bag-refill boundary so
        # a theme drawn at the tail of one pass can't reappear at the head of
        # the next — the independent per-pass shuffles otherwise let the same
        # theme recur only one or two picks later. Not persisted, same
        # rationale as ``random_theme_bag``.
        self.random_theme_recent: list[str] = []
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
        # Last local date we compacted the anti-repeat history ledger
        # (pick_quote.compact_history). Gated the same way
        # ``last_pruned_date`` gates telemetry retention so a multi-year
        # appliance doesn't streamingly re-parse the ledger on every pick.
        self.last_compacted_date: dt.date | None = None
        # Tracks whether the PREVIOUS main-loop tick was in quiet hours, so
        # the loop can detect the rising edge (push the quiet image once on
        # entry) and the falling edge (clear render-dedup state on exit).
        # Only the main loop writes this, so no lock is needed.
        self.was_quiet: bool = False
        # Flipped by the SIGTERM/SIGINT handler so the main loop can exit
        # cleanly between ticks. ``threading.Event`` (not a bool) because the
        # loop's interruptible sleep polls it; a plain flag would force us to
        # keep time.sleep() in the non-interruptible form.
        self.stop_requested = threading.Event()
        # Exponential backoff when render/display keeps failing. The inner
        # ``display_inky.py`` already retries 3× per push with its own backoff;
        # this is the outer-loop equivalent so a persistent hardware fault
        # (pulled ribbon cable, wedged I2C bus) degrades to "retry once every
        # 15 min" instead of "retry every tick forever and spam the log."
        self.consecutive_render_failures: int = 0
        self.backoff_skip_until: float = 0.0  # time.monotonic() deadline
        # Repr of the most recently logged render/display exception, used to
        # deduplicate journald output while the outer-loop backoff keeps
        # retrying the same failure. Without this, a pulled ribbon cable fills
        # the log with identical tracebacks every tick inside the backoff
        # window. The latch clears on any successful render (via
        # ``commit_render_result``) so a genuinely new error after recovery
        # still logs normally.
        self.last_logged_error: str | None = None
        # First-run wizard dismissal. ``False`` until the operator clicks
        # "Done" on the curator UI's setup overlay; persisted to state.json
        # so the wizard doesn't reappear on every page load.
        self.setup_complete: bool = False
        # Pending ``threading.Timer`` objects that must be cancelled on
        # shutdown to stop them firing after ``_shutdown`` has torn down the
        # display handle. Currently only the source-card 5s restore timer
        # registers itself here.
        #
        # Convention for new timers — follow these three rules:
        #
        # 1. Register BEFORE ``.start()`` under ``state.lock`` so a SIGTERM
        #    arriving mid-``.start()`` can still observe and cancel the
        #    timer (``Timer.cancel`` is idempotent — a timer that already
        #    fired is a no-op, so the race is safe in either direction).
        # 2. Deregister from inside the timer callback on completion so the
        #    list doesn't grow unbounded over a long-running session. Wrap
        #    the ``list.remove`` in ``contextlib.suppress(ValueError)``
        #    because ``_shutdown`` may have already drained the list.
        # 3. Set ``.daemon = True`` so a pending timer doesn't block process
        #    exit on SIGTERM / KeyboardInterrupt — the cancel path is a
        #    durability optimization, not a correctness requirement.
        #
        # Without (1), a timer that fires between ``_shutdown`` draining
        # ``pending_timers`` and the operating system terminating the
        # process can kick off a render against torn-down display handles.
        self.pending_timers: list["Timer"] = []
        # time.monotonic() at last emitted heartbeat so the loop can throttle
        # heartbeat writes to HEARTBEAT_INTERVAL_SECONDS even when
        # --interval-seconds is smaller (e.g. tests running at 1s ticks).
        self.last_heartbeat_monotonic: float = 0.0
        if persisted:
            mt = persisted.get("manual_theme")
            if isinstance(mt, str) and mt in _known_theme_names():
                self.manual_theme = mt
            self.manual_quiet = bool(persisted.get("manual_quiet", False))
            # Render-identity fields (last_bucket / last_quote_id /
            # last_effective_theme) survive a restart so a mid-bucket
            # ``systemctl restart`` does not redraw an identical frame. The
            # main loop's skip-if-unchanged check then short-circuits the
            # first post-restart tick. Shape is validated to match the
            # runtime types so a hand-edited or corrupted state file can't
            # poison the loop with a wrong-type field (a bad ``last_bucket``
            # string would just trigger a redraw, which is fine).
            last_bucket = persisted.get("last_bucket")
            if isinstance(last_bucket, str) and last_bucket:
                self.last_bucket = last_bucket
            last_theme = persisted.get("last_effective_theme")
            if isinstance(last_theme, str) and last_theme in _known_theme_names():
                self.last_effective_theme = last_theme
            last_quote_id = persisted.get("last_quote_id")
            if isinstance(last_quote_id, list) and last_quote_id:
                # Stored as a list in JSON; restore as tuple so equality checks
                # against freshly-peeked ids (also tuples) line up. We don't
                # pin a strict length because the runtime identity shape has
                # evolved before (the initial 3-tuple grew to 4-tuple when
                # ``matched_text`` was added to the dedup key); a persisted
                # shape that doesn't match the current peek will just miss
                # the dedup check and force a redraw — safe, not a crash.
                self.last_quote_id = tuple(last_quote_id)
            # Wizard dismissal flag — defaults False so a fresh appliance
            # triggers the wizard on first visit. Schema validation in
            # runtime_store.load_runtime_state already enforces bool.
            self.setup_complete = bool(persisted.get("setup_complete", False))

    def snapshot_for_persistence(self) -> dict:
        """Serialise the fields the operator (or the main loop) needs across restarts.

        Includes the two user-facing preferences (``manual_theme``,
        ``manual_quiet``) and the render-identity triple
        (``last_bucket`` / ``last_quote_id`` / ``last_effective_theme``) so
        a ``systemctl restart`` mid-bucket doesn't force a redraw of the
        identical frame that's already on the panel. The three identity
        fields are written atomically as a group — see
        :meth:`commit_render_result`.
        """
        last_quote_id = list(self.last_quote_id) if self.last_quote_id is not None else None
        return {
            "manual_theme": self.manual_theme,
            "manual_quiet": self.manual_quiet,
            "last_bucket": self.last_bucket,
            "last_quote_id": last_quote_id,
            "last_effective_theme": self.last_effective_theme,
            "setup_complete": self.setup_complete,
        }

    def commit_render_result(
        self, bucket: str, effective_theme: str, quote_id: tuple | None,
    ) -> None:
        """Record the identity of the frame we just pushed to the panel.

        ``last_bucket``, ``last_effective_theme``, and ``last_quote_id`` form an
        atomic group — the skip-if-unchanged check at the top of every tick
        compares all three, so writing them separately risks a stale pair. This
        method is the single entry point; ``quote_id`` is left untouched when
        ``None`` (theme-only repaints reuse the previous quote).
        """
        with self.lock:
            self.last_bucket = bucket
            self.last_effective_theme = effective_theme
            if quote_id is not None:
                self.last_quote_id = quote_id
            # A successful render/push is the single signal that the render
            # path is healthy; reset the outer-loop backoff counters so we
            # go straight back to normal tick cadence.
            self.consecutive_render_failures = 0
            self.backoff_skip_until = 0.0
            # A successful render also clears the error-dedup latch so the
            # next genuine failure (after an intermittent recovery) logs its
            # full traceback instead of being silenced as a "repeat".
            self.last_logged_error = None
