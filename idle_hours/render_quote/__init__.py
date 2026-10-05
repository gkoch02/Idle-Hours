"""Render a picked literary clock quote to an 800x480 Spectra 6 PNG.

A package while issue #335 splits what was one 34,000-line module, a stage at a
time (see ``docs/render_quote_split.md``). The shared layers have moved out,
lowest first: ``_paths``, ``clock``, ``palette``, ``theme_tables``, ``fonts``,
``layout``, ``text``, ``primitives``, ``furniture``, then ``themes._shared``
(code more than one theme uses), ``themes._culture_common`` (the culture and
orbital family's) and one module per theme under ``themes/``. The dispatch
tables, the sleep and source-card frames and ``render()`` still live in
``_monolith``. ``_facade`` keeps ``render_quote.X`` working for every name in
between: reads resolve in the submodule that binds the name, and writes reach
that submodule or raise, never silently miss.
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
from .themes import _culture_common as _themes_culture_common
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
    from .themes._culture_common import *  # noqa: F403
    from .themes._shared import *  # noqa: F403
    from .themes.abyssal import *  # noqa: F403
    from .themes.alchemy import *  # noqa: F403
    from .themes.anna_atkins import *  # noqa: F403
    from .themes.astrarium import *  # noqa: F403
    from .themes.atomic import *  # noqa: F403
    from .themes.atropos import *  # noqa: F403
    from .themes.autochrome import *  # noqa: F403
    from .themes.bakelite import *  # noqa: F403
    from .themes.bauhaus import *  # noqa: F403
    from .themes.beksinski import *  # noqa: F403
    from .themes.betweenus import *  # noqa: F403
    from .themes.biomech import *  # noqa: F403
    from .themes.blueprint import *  # noqa: F403
    from .themes.bosch import *  # noqa: F403
    from .themes.carcosa import *  # noqa: F403
    from .themes.cardcatalog import *  # noqa: F403
    from .themes.cartograph import *  # noqa: F403
    from .themes.chalkboard import *  # noqa: F403
    from .themes.chanbara import *  # noqa: F403
    from .themes.chrono import *  # noqa: F403
    from .themes.circuit import *  # noqa: F403
    from .themes.codex import *  # noqa: F403
    from .themes.comic import *  # noqa: F403
    from .themes.control import *  # noqa: F403
    from .themes.culture import *  # noqa: F403
    from .themes.daguerreotype import *  # noqa: F403
    from .themes.deco import *  # noqa: F403
    from .themes.diags import *  # noqa: F403
    from .themes.dispatch import *  # noqa: F403
    from .themes.dsky import *  # noqa: F403
    from .themes.escritoire import *  # noqa: F403
    from .themes.expanse import *  # noqa: F403
    from .themes.expedition import *  # noqa: F403
    from .themes.fillmore import *  # noqa: F403
    from .themes.firmament import *  # noqa: F403
    from .themes.furies import *  # noqa: F403
    from .themes.glacier import *  # noqa: F403
    from .themes.gothic import *  # noqa: F403
    from .themes.goya import *  # noqa: F403
    from .themes.grimdark import *  # noqa: F403
    from .themes.grimoire import *  # noqa: F403
    from .themes.hades import *  # noqa: F403
    from .themes.hal import *  # noqa: F403
    from .themes.herbarium import *  # noqa: F403
    from .themes.hitchhiker import *  # noqa: F403
    from .themes.illuminated import *  # noqa: F403
    from .themes.intaglio import *  # noqa: F403
    from .themes.izakaya import *  # noqa: F403
    from .themes.kanagawa import *  # noqa: F403
    from .themes.lcars import *  # noqa: F403
    from .themes.letter import *  # noqa: F403
    from .themes.lieder import *  # noqa: F403
    from .themes.lumon import *  # noqa: F403
    from .themes.marker import *  # noqa: F403
    from .themes.marquee import *  # noqa: F403
    from .themes.metro import *  # noqa: F403
    from .themes.mucha import *  # noqa: F403
    from .themes.newsprint import *  # noqa: F403
    from .themes.nightvision import *  # noqa: F403
    from .themes.nocturne import *  # noqa: F403
    from .themes.oblivion import *  # noqa: F403
    from .themes.observation import *  # noqa: F403
    from .themes.orbital import *  # noqa: F403
    from .themes.outrun import *  # noqa: F403
    from .themes.photo import *  # noqa: F403
    from .themes.placard import *  # noqa: F403
    from .themes.plaque import *  # noqa: F403
    from .themes.pride import *  # noqa: F403
    from .themes.pulp import *  # noqa: F403
    from .themes.questline import *  # noqa: F403
    from .themes.risograph import *  # noqa: F403
    from .themes.roman import *  # noqa: F403
    from .themes.saloon import *  # noqa: F403
    from .themes.sampler import *  # noqa: F403
    from .themes.saros import *  # noqa: F403
    from .themes.scholar import *  # noqa: F403
    from .themes.semiotic import *  # noqa: F403
    from .themes.swiss import *  # noqa: F403
    from .themes.synoptic import *  # noqa: F403
    from .themes.tarot import *  # noqa: F403
    from .themes.trisolaris import *  # noqa: F403
    from .themes.vhs import *  # noqa: F403
    from .themes.vinyl import *  # noqa: F403
    from .themes.vitrail import *  # noqa: F403
    from .themes.witcher import *  # noqa: F403
    from .themes.yorha import *  # noqa: F403
del TYPE_CHECKING

# Lowest layer first, so a name bound in several modules reads from where it is
# defined; _monolith last, since it imports from all of them.
_facade.install(
    __name__,
    (
        _paths, clock, palette, theme_tables, fonts, layout, text, primitives, furniture,
        _themes_shared, _themes_culture_common, *themes.THEME_MODULES, _monolith,
    ),
)
