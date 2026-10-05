"""The Marain script and Culture data the ``culture`` and ``orbital`` themes share (issue #335).

One family's helpers, so neither theme module imports the other. Code more
than one unrelated theme uses goes in ``_shared``.
"""

from __future__ import annotations

import math

from PIL import ImageDraw

from ..furniture import _row_digest
from ..palette import SPECTRA6
from ..primitives import position_noise

# ---------------------------------------------------------------------------
# The Culture — shared machinery for ``culture`` and ``orbital``
# ---------------------------------------------------------------------------
# Two views of one object, after Iain M. Banks's Culture novels: ``culture`` is
# a Mind's signal with the Orbital it concerns beside it; ``orbital`` stands on
# that Orbital and looks up at the far side of the ring.
#
# **Both tell the time with the Orbital itself.** The ring spins once a day,
# so at any instant it carries every local time at once:
#
# * ``culture`` marks the plate whose local time is now; the marker travels
#   the full ring once per 24 hours (lit inner face by day, hull by night).
# * ``orbital`` paints the far side of the ring, which is twelve hours away:
#   at noon the zenith is dark, at midnight it blazes across a black sky. The
#   sky follows the hour too.
#
# Neither shows a digit; both use the full 24-hour clock to the minute.
#
# **Marain.** The glyphs are a generated *Marain-idiom* script on a 3x3 grid
# (``_marain_code``), not Banks's own table. ``culture`` writes the matched
# phrase out in it.
#
# **Ship names are invented**, not lifted from the novels.
# ---------------------------------------------------------------------------
_CULTURE_SHIP_NAMES = (
    "Punctuality Is A Lesser Virtue",
    "Late Again, As Foretold",
    "Nobody Checks The Minutes",
    "Tea Before Eschatology",
    "Quietly Keeping Count",
    "Still Reading, Do Not Disturb",
    "An Hour Is Mostly Interval",
    "Borrowed Time, Returned With Interest",
    "The Clock Is Only A Suggestion",
    "Patience Of A Minor Deity",
    "Footnote To A Longer Argument",
    "Ask Me Again After This Chapter",
    "Wrong Century, Right Intentions",
    "Well-Thumbed Margins",
    "Somewhat Overdue",
    "Terminally Bookish",
    "Reads Aloud To Strangers",
    "Dog-Eared But Unbowed",
    "Never Skips To The Last Page",
    "Idle Hours Well Spent",
)
_CULTURE_SHIP_CLASSES = ("GSV", "GCU", "LSV", "MSV", "VFP", "GOU")
_CULTURE_CHANNELS = ("tight point", "stuttered tight point", "broadcast", "swept beam", "compact point")
_CULTURE_MARAIN_LEVELS = ("M1", "M8", "M16", "M16.4", "M32")
_CULTURE_ORBITAL_NAMES = (
    "Masquerade Reach", "Tessellate", "Quillon", "Arvenhale", "Sorrowless", "Pelluc",
    "Hollin Sweep", "Vey Toussant",
)
_CULTURE_PLATE_NAMES = (
    "Lakeshore", "Hivel", "Orrent Downs", "Sallow", "Tarn Mile", "Cressing",
    "Undersky", "Fennet",
)


def _culture_clock(time_str: str) -> float:
    """Local time as a fraction of the day, 0.0 (midnight) .. <1.0.

    Hour *and* minute, since the frames place things along the ring by it. A
    malformed string reads as noon.
    """
    try:
        hh, mm = str(time_str).split(":", 1)
        hour, minute = int(hh) % 24, int(mm[:2]) % 60
    except ValueError:
        hour, minute = 12, 0
    return (hour * 60 + minute) / 1440.0


def _culture_signal(quote_row: dict) -> dict:
    """The signal's header furniture, derived from the row, never the clock.

    Seeded from ``_row_digest`` so the same quote is the same signal on every
    render. The two ships are always distinct.
    """
    digest = _row_digest(quote_row)
    n = len(_CULTURE_SHIP_NAMES)
    src = digest % n
    dst = (src + 1 + (digest >> 5) % (n - 1)) % n
    return {
        "from": f"{_CULTURE_SHIP_CLASSES[(digest >> 10) % len(_CULTURE_SHIP_CLASSES)]} "
                f"{_CULTURE_SHIP_NAMES[src]}",
        "to": f"{_CULTURE_SHIP_CLASSES[(digest >> 13) % len(_CULTURE_SHIP_CLASSES)]} "
              f"{_CULTURE_SHIP_NAMES[dst]}",
        "channel": _CULTURE_CHANNELS[(digest >> 16) % len(_CULTURE_CHANNELS)],
        "level": _CULTURE_MARAIN_LEVELS[(digest >> 19) % len(_CULTURE_MARAIN_LEVELS)],
        # The ``tra.`` stamp is the signal's send date, derived from the row.
        "stamp": f"n4.{28 + (digest >> 3) % 3}.{840 + (digest >> 7) % 60:03d}.{(digest >> 11) % 10000:04d}",
        "orbital": _CULTURE_ORBITAL_NAMES[(digest >> 22) % len(_CULTURE_ORBITAL_NAMES)],
        "plate": _CULTURE_PLATE_NAMES[(digest >> 25) % len(_CULTURE_PLATE_NAMES)],
    }


# -- Marain-idiom glyphs ------------------------------------------------------
_MARAIN_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def _marain_connected(code: int) -> bool:
    """True when the set cells of a 3x3 code form one orthogonally connected run."""
    cells = [i for i in range(9) if code >> i & 1]
    if not cells:
        return False
    seen, stack = {cells[0]}, [cells[0]]
    while stack:
        c = stack.pop()
        r, q = divmod(c, 3)
        for dr, dq in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            rr, qq = r + dr, q + dq
            n = rr * 3 + qq
            if 0 <= rr < 3 and 0 <= qq < 3 and code >> n & 1 and n not in seen:
                seen.add(n)
                stack.append(n)
    return len(seen) == len(cells)


def _marain_table() -> dict[str, int]:
    """Assign every letter and digit a distinct, connected, 4-6 point pattern.

    A fixed affine step through the 512 codes scatters the assignment (so
    neighbouring letters don't get near-identical glyphs), filtered to single
    connected figures. Deterministic at import.
    """
    table: dict[str, int] = {}
    used: set[int] = set()
    code = 0
    for ch in _MARAIN_ALPHABET:
        while True:
            code = (code * 5 + 173) % 512
            if 4 <= bin(code).count("1") <= 6 and code not in used and _marain_connected(code):
                break
        used.add(code)
        table[ch] = code
    return table


_MARAIN_TABLE = _marain_table()


def _marain_code(ch: str) -> int | None:
    """The 9-bit pattern for one character, ``None`` for a word gap."""
    return _MARAIN_TABLE.get(ch.lower())


def _marain_draw_glyph(draw: ImageDraw.ImageDraw, x: int, y: int, code: int,
                       pitch: int, fill, *, stroke: int = 2, dot: int = 2) -> None:
    """One glyph with its top-left grid point at ``(x, y)``.

    Set points are joined to their set orthogonal neighbours, and every set
    point carries a dot, so a lone point still reads as part of the figure.
    """
    pts = {}
    for i in range(9):
        if code >> i & 1:
            r, q = divmod(i, 3)
            pts[i] = (x + q * pitch, y + r * pitch)
    for i, (px_, py_) in pts.items():
        if i % 3 < 2 and i + 1 in pts:
            draw.line([(px_, py_), pts[i + 1]], fill=fill, width=stroke)
        if i + 3 in pts:
            draw.line([(px_, py_), pts[i + 3]], fill=fill, width=stroke)
    for px_, py_ in pts.values():
        draw.ellipse((px_ - dot, py_ - dot, px_ + dot, py_ + dot), fill=fill)


def _culture_terrain(arc: float, across: float) -> tuple[float, float]:
    """``(land, cloud)`` fields over the ring's inner face.

    Sums of incommensurate sines on (arc length, fraction across the band) —
    smooth, continuous around the ring and byte-deterministic. Land above zero
    is continent, below is sea; the face ink treats cloud above 1.25 as weather.
    """
    land = (math.sin(arc * 0.071 + 1.7 * math.sin(arc * 0.019))
            + 0.55 * math.sin(arc * 0.043 + across * 4.1 + 0.6)
            + 0.35 * math.sin(across * 9.0 - arc * 0.013))
    cloud = (math.sin(arc * 0.17 + across * 7.0 + 2.0 * math.sin(arc * 0.037))
             + 0.7 * math.sin(arc * 0.29 - across * 5.0))
    return land, cloud


def _culture_face_ink(rank: int, x: int, y: int, arc: float, across: float, day: float):
    """Ink for one pixel of the inner (habitable) face.

    ``day`` is the cosine of the sun's angle from the plate's zenith: above
    zero the plate is in daylight. A single ``BAYER_8x8`` read decides both the
    shading and the surface mix (``pride``'s rule).
    """
    black, white, blue, green, yellow = (SPECTRA6[n] for n in ("black", "white", "blue", "green", "yellow"))
    land, cloud = _culture_terrain(arc, across)
    if day <= 0.0:
        # Night: dark plates, lit by their own cities.
        if land > 0.15 and position_noise(x, y) < 26:
            return yellow
        return black
    shade = max(0.0, 1.0 - day * 2.2)
    cut = shade * 64
    if rank < cut:
        return black
    share = (rank - cut) / max(1.0, 64 - cut)
    if cloud > 1.25:
        return white
    if land > 0.25:
        return yellow if share < 0.12 else green
    return white if share < 0.1 else blue
