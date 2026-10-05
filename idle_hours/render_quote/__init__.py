"""Render a picked literary clock quote to an 800x480 Spectra 6 PNG.

A package while issue #335 splits what was one 34,000-line module, a stage at a
time (see ``docs/render_quote_split.md``). The shared layers have moved out,
lowest first: ``_paths``, ``clock``, ``palette``, ``theme_tables``, ``fonts``,
``layout``, ``text``, ``primitives``, ``furniture``. The themes, frames and the
render entry point still live in ``_monolith``. ``_facade`` keeps
``render_quote.X`` working for every name in between: reads resolve in the
submodule that binds the name, and writes reach that submodule or raise, never
silently miss.
"""

from typing import TYPE_CHECKING

from . import (
    _facade,
    _monolith,
    _paths,
    clock,
    fonts,
    furniture,
    layout,
    palette,
    primitives,
    text,
    theme_tables,
)

if TYPE_CHECKING:
    # The facade resolves names at runtime, which editors and type checkers
    # cannot see. Until the split ends with an explicit __all__, show them every
    # layer's public names (a name several layers bind is the same object in
    # each, so the order is immaterial). Listing only
    # _monolith would hide anything that moved out and isn't re-imported there
    # (THEME_ORDER, CYCLE_EXCLUDED_THEMES, most font constants).
    from ._monolith import *  # noqa: F403
    from ._paths import *  # noqa: F403
    from .clock import *  # noqa: F403
    from .fonts import *  # noqa: F403
    from .furniture import *  # noqa: F403
    from .layout import *  # noqa: F403
    from .palette import *  # noqa: F403
    from .primitives import *  # noqa: F403
    from .text import *  # noqa: F403
    from .theme_tables import *  # noqa: F403
del TYPE_CHECKING

# Lowest layer first, so a name bound in several modules reads from where it is
# defined; _monolith last, since it imports from all of them.
_facade.install(
    __name__,
    (_paths, clock, palette, theme_tables, fonts, layout, text, primitives, furniture, _monolith),
)
