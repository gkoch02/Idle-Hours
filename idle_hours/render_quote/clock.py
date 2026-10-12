"""The renderer's one read of the wall clock.

Call it as ``clock.now()`` through the module, never ``from .clock import now``: a name import
is a second binding that the golden suite's freeze cannot reach (docs/render_quote_split.md).
"""

from __future__ import annotations

import datetime
import os


def now() -> datetime.datetime:
    """The current local time.

    Every clock-dependent surface (the sleep frame's fallback time, astrarium's
    dashboard) goes through here, so the golden
    suite, the preview generator and the fingerprint tool freeze time by
    patching this one function. ``tests/test_render_golden.py`` fails on any
    other clock read in the package, and on any name import of this function.
    """
    return datetime.datetime.now()


def zone() -> str | None:
    """The local time zone's IANA name (``America/Los_Angeles``), or ``None``.

    ``astrarium`` places its sky by the zone's principal city rather than asking where the
    panel is: the zone is not personal data and is close enough. Read from ``TZ``, then the
    ``/etc/localtime`` link, then ``/etc/timezone``. Frozen beside ``now`` wherever that is.

    A set ``TZ`` is what ``now`` follows, so it decides the zone whatever the host says:
    ``UTC`` or ``PST8PDT`` as given (a POSIX rule that is no zone name leaves ``astrarium``
    on the offset ``now`` has), an empty ``TZ`` is UTC as libc reads it, and a zone file
    outside a ``zoneinfo`` tree has no name to give.
    """
    if "TZ" in os.environ:
        tz = os.environ["TZ"].lstrip(":")
        if "zoneinfo/" in tz:
            return tz.split("zoneinfo/", 1)[1]
        if not tz:
            return "UTC"
        return None if tz.startswith("/") else tz
    try:
        target = os.readlink("/etc/localtime")
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    try:
        with open("/etc/timezone", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None
