"""Render a picked literary clock quote to an 800x480 Spectra 6 PNG.

A package while issue #335 splits what was one 34,000-line module, a stage at a
time (see ``docs/render_quote_split.md``). The shared layers have moved out,
lowest first: ``_paths``, ``clock``, ``palette``, ``theme_tables``, ``fonts``,
``layout``, ``text``, ``primitives``, ``furniture``, then ``themes._shared``
(code more than one theme uses) and one module per theme under ``themes/``
(every border theme so far). The frame themes and the render entry point still
live in ``_monolith``. ``_facade`` keeps ``render_quote.X`` working for every
name in between: reads resolve in the submodule that binds the name, and writes
reach that submodule or raise, never silently miss.
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
    themes,
)
from .themes import _shared as _themes_shared

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
    from .themes._shared import *  # noqa: F403
    from .themes.alchemy import *  # noqa: F403
    from .themes.anna_atkins import *  # noqa: F403
    from .themes.atomic import *  # noqa: F403
    from .themes.bauhaus import *  # noqa: F403
    from .themes.betweenus import *  # noqa: F403
    from .themes.blueprint import *  # noqa: F403
    from .themes.carcosa import *  # noqa: F403
    from .themes.cartograph import *  # noqa: F403
    from .themes.chalkboard import *  # noqa: F403
    from .themes.chanbara import *  # noqa: F403
    from .themes.circuit import *  # noqa: F403
    from .themes.comic import *  # noqa: F403
    from .themes.deco import *  # noqa: F403
    from .themes.dispatch import *  # noqa: F403
    from .themes.fillmore import *  # noqa: F403
    from .themes.firmament import *  # noqa: F403
    from .themes.glacier import *  # noqa: F403
    from .themes.gothic import *  # noqa: F403
    from .themes.grimdark import *  # noqa: F403
    from .themes.grimoire import *  # noqa: F403
    from .themes.herbarium import *  # noqa: F403
    from .themes.illuminated import *  # noqa: F403
    from .themes.kanagawa import *  # noqa: F403
    from .themes.lcars import *  # noqa: F403
    from .themes.letter import *  # noqa: F403
    from .themes.marker import *  # noqa: F403
    from .themes.mucha import *  # noqa: F403
    from .themes.newsprint import *  # noqa: F403
    from .themes.nightvision import *  # noqa: F403
    from .themes.placard import *  # noqa: F403
    from .themes.risograph import *  # noqa: F403
    from .themes.roman import *  # noqa: F403
    from .themes.saloon import *  # noqa: F403
    from .themes.scholar import *  # noqa: F403
    from .themes.swiss import *  # noqa: F403
    from .themes.synoptic import *  # noqa: F403
del TYPE_CHECKING

# Lowest layer first, so a name bound in several modules reads from where it is
# defined; _monolith last, since it imports from all of them.
_facade.install(
    __name__,
    (
        _paths, clock, palette, theme_tables, fonts, layout, text, primitives, furniture,
        _themes_shared, *themes.THEME_MODULES, _monolith,
    ),
)
