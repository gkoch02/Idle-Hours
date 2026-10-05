"""Render a picked literary clock quote to an 800x480 Spectra 6 PNG.

A package while issue #335 splits what was one 34,000-line module: the code
still lives in ``_monolith`` and moves out a stage at a time (see
``docs/render_quote_split.md``). ``_facade`` keeps ``render_quote.X`` working for
every name in between: reads resolve in the submodule that binds the name, and
writes reach that submodule or raise, never silently miss.
"""

from . import _facade, _monolith

_facade.install(__name__, (_monolith,))
