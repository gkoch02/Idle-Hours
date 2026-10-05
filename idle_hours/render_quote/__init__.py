"""Render a picked literary clock quote to an 800x480 Spectra 6 PNG.

A package while issue #335 splits what was one 34,000-line module: the code
still lives in ``_monolith`` and moves out a stage at a time (see
``docs/render_quote_split.md``). ``_facade`` keeps ``render_quote.X`` working for
every name in between: reads resolve in the submodule that binds the name, and
writes reach that submodule or raise, never silently miss.
"""

from typing import TYPE_CHECKING

from . import _facade, _monolith

if TYPE_CHECKING:
    # The facade resolves names at runtime, which editors and type checkers
    # cannot see. Until the split ends with an explicit __all__, show them the
    # monolith's public names.
    from ._monolith import *  # noqa: F403
del TYPE_CHECKING

_facade.install(__name__, (_monolith,))
