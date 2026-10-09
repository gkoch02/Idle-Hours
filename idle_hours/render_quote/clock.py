"""The renderer's one read of the wall clock.

Call it as ``clock.now()`` through the module, never ``from .clock import now``: a name import
is a second binding that the golden suite's freeze cannot reach (docs/render_quote_split.md).
"""

from __future__ import annotations

import datetime


def now() -> datetime.datetime:
    """The current local time.

    Every clock-dependent surface (the sleep frame's fallback time, astrarium's
    dashboard) goes through here, so the golden
    suite, the preview generator and the fingerprint tool freeze time by
    patching this one function. ``tests/test_render_golden.py`` fails on any
    other clock read in the package, and on any name import of this function.
    """
    return datetime.datetime.now()
