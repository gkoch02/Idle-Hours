"""PIL-free shim exposing the registered theme names + cycle order.

Three runtime modules (:mod:`runtime_state`, :mod:`runtime_theme`,
:mod:`runtime_actions`) need theme-name lists to validate persisted state,
gate manual-theme overrides, and drive the button-B / web cycle. They each
previously inlined a near-duplicate ``try: from render_quote import …`` lazy
import with a hand-coded ``("default", "dark")`` fallback — and the fallback
types had drifted (``frozenset`` vs ``tuple``) across copies. Consolidating
into one module kills the drift class-by-construction.

The lazy import is preserved (rather than an unconditional one at the top)
so importing these helpers does not pull Pillow into the main-loop import
graph at module load — ``render_quote.THEMES`` triggers ``from PIL import``,
and we want :mod:`run_clock`, :mod:`runtime_state`, etc. to stay PIL-free
on import for the test harness and for any future no-render mode.

Failure mode: if ``render_quote`` cannot be imported (e.g. a stripped-down
test fixture, or a Pillow install that's broken on the appliance), we fall
back to the legacy ``("default", "dark")`` pair so state-file load /
persisted-theme validation can still proceed. The appliance won't render in
that state, but it also shouldn't wedge state-machine code.
"""
from __future__ import annotations

_FALLBACK: tuple[str, ...] = ("default", "dark")


def known_theme_names() -> frozenset[str]:
    """Set of theme names registered in ``render_quote.THEMES``.

    Used to validate persisted manual-theme values and gate
    ``resolve_effective_theme`` overrides. Membership-style lookups; order
    does not matter (use :func:`theme_cycle` when you need the curated
    button-B / web-dropdown ordering).
    """
    try:
        from idle_hours.render_quote import THEMES
    except Exception:
        return frozenset(_FALLBACK)
    return frozenset(THEMES.keys())


def theme_cycle() -> tuple[str, ...]:
    """Curated order for button-B / web-dropdown theme advancement.

    Pulled from ``render_quote.THEME_ORDER`` (an explicit tuple, distinct from
    ``THEMES.keys()`` — the registered names without an ordering guarantee).
    """
    try:
        from idle_hours.render_quote import THEME_ORDER
    except Exception:
        return _FALLBACK
    return tuple(THEME_ORDER)
