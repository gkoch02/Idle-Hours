"""Mutable runtime state shared between the main loop, button listener, and web server.

Extracted from :mod:`run_clock` as part of the orchestrator slim-down. The class
itself has no logic — it's the synchronisation vocabulary that the loop, GPIO
listener thread, and curator web server all agree on. ``run_clock.RuntimeState``
is preserved as a re-export so existing call sites keep resolving.
"""
from __future__ import annotations

import datetime as dt
import threading


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
