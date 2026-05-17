"""Theme resolution: auto-dark window, manual override, midnight reset.

``resolve_effective_theme`` merges the CLI ``--theme`` choice, the wall-clock
(for ``auto``), and the user's button-B manual override into the theme actually
passed to the renderer. ``_maybe_reset_manual_theme_at_midnight`` clears the
manual override on day rollover so ``auto`` resumes. Extracted from
:mod:`run_clock`; the original names are re-exported from ``run_clock`` so
existing call sites and test patches keep resolving.
"""
from __future__ import annotations

import datetime as dt
import random

from runtime_log import _log
from runtime_state import RuntimeState
from theme_names import known_theme_names as _registered_themes

# Auto-theme: switch to dark theme during this window, default theme otherwise.
# Boundaries chosen to match civil twilight in temperate latitudes; users who want
# a tighter fit can pass --theme default or --theme dark explicitly.
AUTO_DARK_START_HOUR = 18
AUTO_DARK_END_HOUR = 6


def auto_theme_for(time_str: str, day_theme: str = "default", night_theme: str = "dark") -> str:
    """Return ``night_theme`` during the night window, ``day_theme`` otherwise.

    Defaults match the legacy binary contract (``default`` / ``dark``); callers
    that don't pass the kwargs see no behaviour change. Operators can broaden
    the rotation via ``--auto-day-theme`` / ``--auto-night-theme`` (see
    ``run_clock`` argparse) — e.g. ``scholar`` by day + ``nightvision`` by
    night. Validation of the theme names lives at argparse / config-load time
    rather than here so the per-tick call stays cheap.
    """
    hour = int(time_str.split(":", 1)[0])
    if AUTO_DARK_START_HOUR <= hour or hour < AUTO_DARK_END_HOUR:
        return night_theme
    return day_theme


def _auto_theme_kwargs(args) -> dict[str, str]:
    """Pluck the auto-theme day/night picks off an argparse Namespace.

    Single seam so call sites that thread these into ``resolve_effective_theme``
    don't each have to reach into ``args``; if we ever add a third dimension
    (e.g. weekend/weekday split) only this helper changes. ``getattr`` defaults
    cover programmatic ``argparse.Namespace`` constructions in tests (and any
    caller predating these flags) — the legacy binary contract is preserved
    when the attributes are absent.
    """
    return {
        "auto_day_theme": getattr(args, "auto_day_theme", "default"),
        "auto_night_theme": getattr(args, "auto_night_theme", "dark"),
    }


def pick_random_theme() -> str:
    """Uniformly pick a theme from the registered cycle.

    Used by the ``--once`` path and as the fallback inside
    ``resolve_effective_theme`` when no bag state is available. The main
    loop uses :func:`pick_next_random_theme` instead so every theme is
    shown once before any repeat (true-shuffle behaviour — like a music
    player's shuffled-playlist mode).
    """
    from theme_names import theme_cycle
    return random.choice(list(theme_cycle()))


def pick_next_random_theme(
    bag: list[str], *, just_played: str | None = None,
) -> tuple[str, list[str]]:
    """Draw the next theme from a shuffled bag of unseen themes.

    Returns ``(theme, updated_bag)`` — the caller stores ``updated_bag``
    on :class:`RuntimeState`. When ``bag`` is empty the bag is refilled
    with a fresh shuffle of the full cycle; if the freshly-shuffled next
    pick would replay ``just_played``, it's swapped with another random
    position so back-to-back repeats don't sneak across the reshuffle
    boundary.

    The bag is popped from the end (``list.pop`` is O(1)), so ``bag[-1]``
    is the "next" theme — that's the slot the swap targets.
    """
    from theme_names import theme_cycle

    bag = list(bag)  # never mutate the caller's list
    if not bag:
        bag = list(theme_cycle())
        random.shuffle(bag)
        if just_played is not None and len(bag) > 1 and bag[-1] == just_played:
            swap_idx = random.randint(0, len(bag) - 2)
            bag[-1], bag[swap_idx] = bag[swap_idx], bag[-1]

    theme = bag.pop()
    return theme, bag


def resolve_effective_theme(
    theme_arg: str,
    time_str: str,
    manual_theme: str | None,
    *,
    current_random_theme: str | None = None,
    auto_day_theme: str = "default",
    auto_night_theme: str = "dark",
) -> str:
    """Resolve the theme actually passed to renderer/display.

    ``theme_arg`` is the CLI choice (any registered theme name, or 'auto').
    ``manual_theme`` is the user's button-B / web-dropdown override (set until
    midnight). When ``theme_arg == 'auto'`` and no manual override is active,
    derive from the wall clock using the configured day/night picks (default
    ``default`` / ``dark`` — the legacy binary contract). Any registered theme
    from ``render_quote.THEMES`` is accepted as an override — previously this
    accepted only the legacy pair, so a manual flip to ``scholar`` /
    ``nightvision`` would silently revert to ``theme_arg`` and the cycle never
    advanced past ``dark``.
    """
    if manual_theme is not None and manual_theme in _registered_themes():
        return manual_theme
    if theme_arg == "random":
        # current_random_theme is set by the main loop when the quote changes.
        # Fall back to a fresh pick only when called from --once or startup
        # (where no main-loop tick has populated the field yet).
        return current_random_theme if current_random_theme is not None else pick_random_theme()
    if theme_arg == "auto":
        return auto_theme_for(time_str, auto_day_theme, auto_night_theme)
    return theme_arg


def _maybe_reset_manual_theme_at_midnight(args, state: RuntimeState) -> None:
    """Clear the manual theme override at the day boundary so 'auto' resumes."""
    import run_clock
    today = dt.date.today()
    with state.lock:
        if state.last_seen_date is None:
            state.last_seen_date = today
            return
        if today != state.last_seen_date and state.theme_arg in ("auto", "random") and state.manual_theme is not None:
            _log(f"midnight rollover: clearing manual theme override ({state.manual_theme})")
            state.manual_theme = None
            run_clock.save_runtime_state(args.state_path, state.snapshot_for_persistence())
        state.last_seen_date = today
