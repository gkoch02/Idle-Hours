"""The ``trisolaris`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random
from itertools import pairwise

from PIL import Image, ImageDraw

from .._paths import META_FONT_BOLD_CANDIDATES, META_FONT_CANDIDATES, SPACEMONO_BOLD, TITILLIUM_ITALIC, YUJI_BOKU_REGULAR
from ..fonts import load_font
from ..furniture import draw_truncated_centred_byline
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, pixel_access, snap_image_to_palette
from ..primitives import _flow_stroke_hash, paint_neon_mask, wrap_quote_into_masks
from ..spec import FrameSpec
from ..text import draw_tracked

# ---------------------------------------------------------------------------
# trisolaris — Liu Cixin's *The Three-Body Problem* (三体, 2008)
# ---------------------------------------------------------------------------
# The Trisolaran sky, computed rather than drawn: three suns and a planet are
# integrated under Newtonian gravity from fixed initial conditions, and the
# clock advances the simulation (each dial minute is a fixed slice of simulated
# time). Every render shows where the suns have got to, with the last hour of
# their paths trailing behind.
#
# **The novel's mechanics come from the physics.** The era is read off the
# integration: *stable* when one sun's pull on the planet exceeds the next
# strongest by ``_TRISOLARIS_STABLE_DOMINANCE``, *chaotic* otherwise. When the
# planet falls into a sun or is flung out, that civilization ends: the planet is
# reborn in a circular orbit about the most isolated sun and the header counter
# advances. The planet's trail is broken at every rebirth so a teleport never
# draws as a streak.
#
# **Byte-identical everywhere.** Only ``+ - * /`` and ``math.sqrt`` are used,
# all correctly rounded under IEEE 754. Don't use ``**`` in the force law
# (``r2 * sqrt(r2)``, not ``r2 ** 1.5``): ``pow`` goes through libm, which need
# not round correctly. Kick-drift-kick leapfrog at a fixed step; forces are
# Plummer-softened because an adaptive step would make the frame depend on
# floating-point comparisons in a step controller.
#
# **The initial conditions were searched offline** for a start whose suns stay
# inside the sky all day and whose planet sees a mix of stable and chaotic eras
# and a handful of lost civilizations (a generic three-body system ejects a sun
# within a few dozen crossing times). ``TestTrisolarisEphemeris`` fences those
# properties against the committed constants.
#
# **Composition.** The orrery owns the left; at its foot the Red Coast Base dish
# on Radar Peak aims at the barycentre with wavefronts leaving its feed. The
# quote sits on the right under a ``三体`` masthead, the matched phrase lit as
# sunlight (yellow core in the bakelite split-band tangerine bloom), the prose
# solid white. Along the foot: DO NOT ANSWER.
#
# **The time.** The clock drives the simulation and the era label; no digit of
# the time is printed (the civilization number is a count of deaths). Composed
# at 800x480 and NEAREST-downsampled (the ``metro`` convention).
# ---------------------------------------------------------------------------
_TRISOLARIS_MASSES = (1.0, 0.85, 1.15)
_TRISOLARIS_INITIAL_SUNS = (
    (-0.7790231091549272, -1.123740528588034),
    (-0.6284556317938058, 0.7024334277767176),
    (1.141922083634489, 0.4579757521546296),
)
_TRISOLARIS_INITIAL_VELOCITIES = (
    (-0.42512274278402506, 0.1819496698677228),
    (0.3824413054486465, -0.3228627894307456),
    (0.08699794187189179, 0.08042060969427037),
)
_TRISOLARIS_INITIAL_PLANET = (-1.0330201690484344, -1.4173172376938314)
_TRISOLARIS_INITIAL_PLANET_VELOCITY = (0.7886371665064716, -0.8681726280332862)
_TRISOLARIS_SOFTENING2 = 0.02          # sun-sun Plummer softening, squared
_TRISOLARIS_PLANET_SOFTENING2 = 0.006  # planet-sun softening, squared
_TRISOLARIS_DT = 0.004
_TRISOLARIS_STEPS_PER_SAMPLE = 5
_TRISOLARIS_SAMPLES_PER_MINUTE = 4
_TRISOLARIS_PREROLL_MINUTES = 90       # so 12:00 already has a trail behind it
_TRISOLARIS_DIAL_MINUTES = 720
_TRISOLARIS_TRAIL_MINUTES = 60
_TRISOLARIS_BURN_RADIUS2 = 0.0049      # planet within 0.07 of a sun: consumed
_TRISOLARIS_LOST_RADIUS2 = 10.24       # planet beyond 3.2 of the barycentre: lost
_TRISOLARIS_REBIRTH_RADIUS = 0.3
_TRISOLARIS_STABLE_DOMINANCE = 4.0
_TRISOLARIS_FIRST_CIVILIZATION = 183

_TRISOLARIS_SKY = (146, 24, 436, 314)  # where the suns' whole-day paths are fitted, clear of the dish
_TRISOLARIS_ORRERY_CLIP = (0, 0, 446, 420)
_TRISOLARIS_COLUMN = (456, 780)        # the quote column's x extent
_TRISOLARIS_QUOTE_RECT = (456, 118, 780, 372)
_TRISOLARIS_DISH_X = 72                # the dish pedestal; its y comes from the ridge
_TRISOLARIS_SUN_RADII = (6, 5, 7)
_TRISOLARIS_STAR_SEED = 0x3B0D1E5
_TRISOLARIS_WARNING = "DO NOT ANSWER!"
_TRISOLARIS_WARNING_Y = 422

_TRISOLARIS_EPHEMERIS: tuple | None = None
_TRISOLARIS_PROJECTION: tuple | None = None


def _trisolaris_sun_accel(pos):
    """Softened pairwise gravity between the three suns (G = 1)."""
    m = _TRISOLARIS_MASSES
    ax = [0.0, 0.0, 0.0]
    ay = [0.0, 0.0, 0.0]
    for i in range(3):
        for j in range(i + 1, 3):
            dx = pos[j][0] - pos[i][0]
            dy = pos[j][1] - pos[i][1]
            r2 = dx * dx + dy * dy + _TRISOLARIS_SOFTENING2
            inv = 1.0 / (r2 * math.sqrt(r2))
            ax[i] += m[j] * dx * inv
            ay[i] += m[j] * dy * inv
            ax[j] -= m[i] * dx * inv
            ay[j] -= m[i] * dy * inv
    return ax, ay


def _trisolaris_planet_accel(p, pos):
    """Acceleration on the (massless) planet, plus each sun's pull strength —
    the latter is what the era is read from."""
    ax = ay = 0.0
    pulls = []
    for i in range(3):
        dx = pos[i][0] - p[0]
        dy = pos[i][1] - p[1]
        r2 = dx * dx + dy * dy + _TRISOLARIS_PLANET_SOFTENING2
        g = _TRISOLARIS_MASSES[i] / (r2 * math.sqrt(r2))
        ax += g * dx
        ay += g * dy
        pulls.append(_TRISOLARIS_MASSES[i] / r2)
    return ax, ay, pulls


def _trisolaris_rebirth(pos, vel):
    """A new civilization: a circular orbit about the most isolated sun — the
    one whose nearest neighbour is furthest away, which is where a planet has
    its best chance of a long stable era."""
    best, home = -1.0, 0
    for i in range(3):
        nearest = min((pos[i][0] - pos[j][0]) * (pos[i][0] - pos[j][0])
                      + (pos[i][1] - pos[j][1]) * (pos[i][1] - pos[j][1])
                      for j in range(3) if j != i)
        if nearest > best:
            best, home = nearest, i
    # Circular speed under the *softened* force law the planet actually feels:
    # v^2 / r = m r / (r^2 + eps^2)^(3/2). The Keplerian sqrt(m / r) is ~5% too
    # fast at this radius and starts every civilization on an eccentric orbit.
    r = _TRISOLARIS_REBIRTH_RADIUS
    q = r * r + _TRISOLARIS_PLANET_SOFTENING2
    speed = r * math.sqrt(_TRISOLARIS_MASSES[home] / (q * math.sqrt(q)))
    return ([pos[home][0] + _TRISOLARIS_REBIRTH_RADIUS, pos[home][1]],
            [vel[home][0], vel[home][1] + speed])


def _trisolaris_ephemeris() -> tuple:
    """The whole day's integration, computed once per process.

    Returns one sample per quarter-minute from the start of the preroll:
    ``(suns, planet, dominance, civilization)`` where ``suns`` is three
    ``(x, y)`` pairs, ``dominance`` is the strongest sun's pull over the next
    strongest, and ``civilization`` counts the planet's deaths so far. About a
    tenth of a second on a desktop; memoised because a contact sheet renders
    144 frames in one process.
    """
    global _TRISOLARIS_EPHEMERIS
    if _TRISOLARIS_EPHEMERIS is not None:
        return _TRISOLARIS_EPHEMERIS
    pos = [list(s) for s in _TRISOLARIS_INITIAL_SUNS]
    vel = [list(v) for v in _TRISOLARIS_INITIAL_VELOCITIES]
    p = list(_TRISOLARIS_INITIAL_PLANET)
    pv = list(_TRISOLARIS_INITIAL_PLANET_VELOCITY)
    ax, ay = _trisolaris_sun_accel(pos)
    pax, pay, pulls = _trisolaris_planet_accel(p, pos)
    half = 0.5 * _TRISOLARIS_DT
    dt = _TRISOLARIS_DT
    civilization = 0
    samples = []
    total = (_TRISOLARIS_PREROLL_MINUTES + _TRISOLARIS_DIAL_MINUTES) * _TRISOLARIS_SAMPLES_PER_MINUTE
    for _ in range(total):
        ranked = sorted(pulls, reverse=True)
        samples.append((tuple((s[0], s[1]) for s in pos), (p[0], p[1]),
                        ranked[0] / ranked[1], civilization))
        for _ in range(_TRISOLARIS_STEPS_PER_SAMPLE):
            for i in range(3):
                vel[i][0] += half * ax[i]
                vel[i][1] += half * ay[i]
            pv[0] += half * pax
            pv[1] += half * pay
            for i in range(3):
                pos[i][0] += dt * vel[i][0]
                pos[i][1] += dt * vel[i][1]
            p[0] += dt * pv[0]
            p[1] += dt * pv[1]
            ax, ay = _trisolaris_sun_accel(pos)
            pax, pay, pulls = _trisolaris_planet_accel(p, pos)
            for i in range(3):
                vel[i][0] += half * ax[i]
                vel[i][1] += half * ay[i]
            pv[0] += half * pax
            pv[1] += half * pay
            # Checked every step, not every sample: a fast pass can dip inside
            # the burn radius and back out between two samples.
            burned = any((p[0] - s[0]) * (p[0] - s[0]) + (p[1] - s[1]) * (p[1] - s[1])
                         < _TRISOLARIS_BURN_RADIUS2 for s in pos)
            lost = p[0] * p[0] + p[1] * p[1] > _TRISOLARIS_LOST_RADIUS2
            if burned or lost:
                civilization += 1
                p, pv = _trisolaris_rebirth(pos, vel)
                pax, pay, pulls = _trisolaris_planet_accel(p, pos)
    _TRISOLARIS_EPHEMERIS = tuple(samples)
    return _TRISOLARIS_EPHEMERIS


def _trisolaris_index(time_str: str) -> int:
    """Ephemeris index for a wall-clock time on the twelve-hour dial.

    Noon and midnight both start the dial, so 00:30 and 12:30 see the same sky.
    """
    try:
        hour, minute = (int(part) for part in time_str.split(":")[:2])
    except (ValueError, AttributeError):
        hour, minute = 0, 0
    dial = (hour % 12) * 60 + minute % 60
    return (_TRISOLARIS_PREROLL_MINUTES + dial) * _TRISOLARIS_SAMPLES_PER_MINUTE


def _trisolaris_projection() -> tuple[float, float, float]:
    """``(scale, offset_x, offset_y)`` fitting the suns' whole-day paths into
    ``_TRISOLARIS_SKY`` at one fixed scale, aspect preserved.

    Derived from the ephemeris rather than hardcoded so the fit cannot drift
    from the constants it depends on. The planet is left out of the fit on
    purpose: a lost planet flies far outside the system, and fitting it would
    shrink the suns to a cluster in the middle of the panel.
    """
    global _TRISOLARIS_PROJECTION
    if _TRISOLARIS_PROJECTION is not None:
        return _TRISOLARIS_PROJECTION
    xs = [s[0] for sample in _trisolaris_ephemeris() for s in sample[0]]
    ys = [s[1] for sample in _trisolaris_ephemeris() for s in sample[0]]
    x0, y0, x1, y1 = _TRISOLARIS_SKY
    scale = min((x1 - x0) / (max(xs) - min(xs)), (y1 - y0) / (max(ys) - min(ys)))
    ox = (x0 + x1) / 2 - scale * (max(xs) + min(xs)) / 2
    oy = (y0 + y1) / 2 - scale * (max(ys) + min(ys)) / 2
    _TRISOLARIS_PROJECTION = (scale, ox, oy)
    return _TRISOLARIS_PROJECTION


def _trisolaris_project(point) -> tuple[float, float]:
    scale, ox, oy = _trisolaris_projection()
    return ox + scale * point[0], oy + scale * point[1]


def _trisolaris_era(time_str: str) -> tuple[bool, int]:
    """``(stable, civilization_number)`` at ``time_str``."""
    sample = _trisolaris_ephemeris()[_trisolaris_index(time_str)]
    return sample[2] > _TRISOLARIS_STABLE_DOMINANCE, _TRISOLARIS_FIRST_CIVILIZATION + sample[3]


def _trisolaris_ridge_y(x: float) -> int:
    """Radar Peak's skyline: high on the left where the dish stands, falling
    away under the quote column. Two incommensurate sines keep it from reading
    as a ruled curve."""
    fall = min(1.0, max(0.0, (x - 60) / 480))
    base = 392 + 62 * fall * fall * (3 - 2 * fall)
    peak = 16 * math.exp(-((x - _TRISOLARIS_DISH_X) / 70.0) ** 2)
    return int(base - peak + 6 * math.sin(x * 0.031) + 4 * math.sin(x * 0.087 + 1.3))


def _trisolaris_paint_sky(image: Image.Image) -> None:
    """Black space and a seeded star field, one star in five a blue one.

    Stars stay out of the whole text column (masthead, quote, byline and
    warning), where a stray white pixel beside a letterform reads as a stroke.
    """
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 799, 479), fill=SPECTRA6["black"])
    px = pixel_access(image)
    rng = random.Random(_TRISOLARIS_STAR_SEED)
    column_x0 = _TRISOLARIS_COLUMN[0] - 10
    for _ in range(230):
        x = int(rng.random() * 800)
        y = int(rng.random() * 440)
        big = rng.random() < 0.1
        blue = rng.random() < 0.18
        if x >= column_x0 - 1:
            continue
        if y >= _trisolaris_ridge_y(x) - 4:
            continue
        ink = SPECTRA6["blue"] if blue else SPECTRA6["white"]
        if big:
            draw.rectangle((x, y, x + 1, y + 1), fill=ink)
        else:
            px[x, y] = ink


def _trisolaris_stipple_line(px, points, *, salt: int, keep: float = 1.0, width: int = 1,
                             ink=None, hot: float = 0.0, clip=(0, 0, 800, 480)) -> None:
    """Stipple a polyline: each pixel along it survives with probability
    ``keep`` (a position hash, so it is deterministic), clipped to ``clip``.

    ``ink=None`` paints tangerine — yellow with probability
    ``hot + (1 - hot) * 3/8``, red otherwise — so a warm line reads as warm
    even at ``hot=0``, where solid red would sit within a few luminance points
    of the panel's black. Every warm line on the frame (sun wakes, the ridge,
    the transmission) goes through here; ``hot`` is how a sun's wake starts
    yellow at the sun and cools toward the 3/8 floor as it ages.
    """
    cx0, cy0, cx1, cy1 = clip
    warm_share = hot + (1.0 - hot) * 0.375
    for (ax, ay), (bx, by) in pairwise(points):
        steps = int(max(abs(bx - ax), abs(by - ay))) + 1
        for k in range(steps + 1):
            t = k / steps
            x0 = int(ax + (bx - ax) * t)
            y0 = int(ay + (by - ay) * t)
            for dy in range(width):
                x, y = x0, y0 + dy
                if not (cx0 <= x < cx1 and cy0 <= y < cy1) or _flow_stroke_hash(x, y, salt) >= keep:
                    continue
                if ink is None:
                    warm = _flow_stroke_hash(x, y, salt + 100) < warm_share
                    px[x, y] = SPECTRA6["yellow"] if warm else SPECTRA6["red"]
                else:
                    px[x, y] = ink


def _trisolaris_paint_orbits(image: Image.Image, index: int) -> None:
    """The last hour of each body's path, cooling as it ages.

    A sun's trail starts yellow and cools to tangerine over its first 40%,
    thinning toward the oldest end. The planet's trail is sparse white and drawn
    only back to its most recent rebirth, so the jump to a new orbit never draws.
    """
    px = pixel_access(image)
    ephemeris = _trisolaris_ephemeris()
    span = _TRISOLARIS_TRAIL_MINUTES * _TRISOLARIS_SAMPLES_PER_MINUTE
    start = max(1, index - span)
    for k in range(start, index + 1):
        age = (index - k) / span
        keep = 0.85 - 0.7 * age
        before, after = ephemeris[k - 1], ephemeris[k]
        for i in range(3):
            segment = [_trisolaris_project(before[0][i]), _trisolaris_project(after[0][i])]
            _trisolaris_stipple_line(px, segment, salt=40 + i, keep=keep,
                                     hot=max(0.0, 1.0 - age * 2.5), clip=_TRISOLARIS_ORRERY_CLIP)
        if before[3] == ephemeris[index][3]:
            segment = [_trisolaris_project(before[1]), _trisolaris_project(after[1])]
            _trisolaris_stipple_line(px, segment, salt=47, keep=keep * 0.7,
                                     ink=SPECTRA6["white"], clip=_TRISOLARIS_ORRERY_CLIP)


def _trisolaris_paint_bodies(image: Image.Image, index: int) -> None:
    """Three suns as gold blooms, then the planet as a blue world with a white
    lit limb. The suns share one mask so two near each other merge into one
    glare rather than double-exposing. The halo is confined to empty sky, so
    it dims into the trails and the dish rather than painting over them."""
    sample = _trisolaris_ephemeris()[index]
    mask = Image.new("L", image.size, 0)
    mdraw = ImageDraw.Draw(mask)
    for (sx, sy), radius in zip((_trisolaris_project(s) for s in sample[0]), _TRISOLARIS_SUN_RADII, strict=True):
        mdraw.ellipse((sx - radius, sy - radius, sx + radius, sy + radius), fill=255)
    paint_neon_mask(
        image, mask, SPECTRA6["yellow"], SPECTRA6["red"],
        radius=6, gamma=1.3, cap=0.75, tile=BAYER_8x8,
        glow_minor=SPECTRA6["yellow"], glow_minor_share=0.375,
        core_minor=SPECTRA6["white"], core_minor_share=0.25,
        # Only onto empty sky: a sun passing the lower-left of the sky box
        # would otherwise stipple its halo over the dish's wavefront arcs.
        ground=frozenset({SPECTRA6["black"], SPECTRA6["blue"]}),
    )
    x, y = _trisolaris_project(sample[1])
    cx0, cy0, cx1, cy1 = _TRISOLARIS_ORRERY_CLIP
    if cx0 + 4 <= x < cx1 - 4 and cy0 + 4 <= y < cy1 - 4:
        draw = ImageDraw.Draw(image)
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=SPECTRA6["blue"], outline=SPECTRA6["white"])


def _trisolaris_dish_geometry(ridge_top: int):
    """Pedestal polygon, dish polygon, feed tip and aim for the Red Coast
    antenna.

    The dish is a parabolic section in profile: the reflecting face curves
    toward the aim, and the back is thickest at the vertex and thins to the
    rim, so the silhouette reads as a bowl rather than a flat plate.
    """
    x = _TRISOLARIS_DISH_X
    pivot = (x, ridge_top - 46)
    pedestal = [(x - 20, ridge_top + 6), (x - 7, pivot[1] + 4), (x + 7, pivot[1] + 4),
                (x + 20, ridge_top + 6)]
    # Aimed at the system's barycentre — the origin of the integration's
    # coordinates, since the initial conditions carry zero total momentum —
    # so the transmission points where the three suns actually dance.
    tx, ty = _trisolaris_project((0.0, 0.0))
    aim = math.atan2(ty - pivot[1], tx - pivot[0])
    ux, uy = math.cos(aim), math.sin(aim)         # along the dish axis
    vx, vy = -uy, ux                              # across the aperture
    half, depth, back = 46, 21, 9
    face, rear = [], []
    for k in range(-12, 13):
        s = k / 12.0
        d = depth * s * s
        face.append((pivot[0] + half * s * vx + d * ux, pivot[1] + half * s * vy + d * uy))
        b = d - back * (1 - s * s)
        rear.append((pivot[0] + half * s * vx + b * ux, pivot[1] + half * s * vy + b * uy))
    feed = (pivot[0] + 40 * ux, pivot[1] + 40 * uy)
    return pedestal, face, rear, pivot, feed, (ux, uy)


def _trisolaris_paint_red_coast(image: Image.Image) -> None:
    """Radar Peak and the Red Coast dish, drawn as line-work.

    The ridge is a tangerine crest line with two fainter contours behind it,
    black below; the dish is white line-work (face, back, feed struts,
    pedestal). Don't make it a black silhouette on a dusk glow: the glow reads
    as a dune field and the dish vanishes. Line-work also matches the orrery.

    The transmission is a fan of wavefront arcs off the feed, thinning as they
    spread; a straight line to the suns reads as one more orbit trail.
    """
    draw = ImageDraw.Draw(image)
    skyline = [(x, _trisolaris_ridge_y(x)) for x in range(0, 801, 4)]
    draw.polygon(skyline + [(800, 480), (0, 480)], fill=SPECTRA6["black"])
    px = pixel_access(image)
    _trisolaris_stipple_line(px, skyline, salt=61, width=2)
    for step, keep in ((11, 0.55), (24, 0.3)):
        contour = [(x, _trisolaris_ridge_y(x) + step + int(3 * math.sin(x * 0.05 + step)))
                   for x in range(0, 801, 4)]
        _trisolaris_stipple_line(px, contour, salt=63 + step, keep=keep)

    ridge_top = _trisolaris_ridge_y(_TRISOLARIS_DISH_X)
    pedestal, face, rear, pivot, feed, (ux, uy) = _trisolaris_dish_geometry(ridge_top)
    white = SPECTRA6["white"]
    draw.polygon(pedestal, fill=SPECTRA6["black"], outline=white)
    draw.line([(pivot[0] - 4, pivot[1] + 4), (pedestal[0][0] + 6, ridge_top), (pedestal[3][0] - 6, pivot[1] + 12)],
              fill=white, width=1)
    outline = [(round(a), round(b)) for a, b in face + rear[::-1]]
    draw.polygon(outline, fill=SPECTRA6["black"])
    draw.line([(round(a), round(b)) for a, b in face], fill=white, width=2)
    draw.line([(round(a), round(b)) for a, b in rear], fill=white, width=1)
    for strut in (face[0], face[-1]):
        draw.line([strut, feed], fill=white, width=1)
    draw.ellipse((feed[0] - 2, feed[1] - 2, feed[0] + 2, feed[1] + 2), fill=SPECTRA6["yellow"])

    aim = math.atan2(uy, ux)
    for ring, radius in enumerate(range(16, 76, 12)):
        keep = 0.95 - 0.16 * ring
        spread = math.radians(16 + 4 * ring)
        steps = int(radius * spread * 2) + 1
        arc = [(feed[0] + radius * math.cos(aim - spread + 2 * spread * k / steps),
                feed[1] + radius * math.sin(aim - spread + 2 * spread * k / steps))
               for k in range(steps + 1)]
        _trisolaris_stipple_line(px, arc, salt=91 + ring, keep=keep)


def _trisolaris_paint_header(draw: ImageDraw.ImageDraw, time_str: str) -> None:
    """``三体`` masthead, the title, the civilization number and the era.

    The era carries its own glyph: three small discs for the three suns, one
    filled in a stable era (the planet has a sun of its own) and all three in
    a chaotic one.
    """
    stable, civilization = _trisolaris_era(time_str)
    col_x0, col_x1 = _TRISOLARIS_COLUMN
    han = load_font([YUJI_BOKU_REGULAR, *META_FONT_BOLD_CANDIDATES], 46)
    draw.text((col_x0, 22), "三体", font=han, fill=SPECTRA6["white"])
    han_w = draw.textlength("三体", font=han)
    chrome = load_font([SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], 11)
    x = col_x0 + han_w + 14
    draw_tracked(draw, (x, 28), "THE THREE-BODY PROBLEM", chrome, SPECTRA6["white"], tracking=1)
    draw_tracked(draw, (x, 47), f"CIVILIZATION NO. {civilization}", chrome, SPECTRA6["yellow"], tracking=1)
    era = "STABLE ERA · REHYDRATE" if stable else "CHAOTIC ERA · DEHYDRATE"
    draw_tracked(draw, (x, 66), era, chrome, SPECTRA6["white"] if stable else SPECTRA6["yellow"], tracking=1)
    # A dotted rule closes the header, ending in the era glyph.
    glyph_x0 = col_x1 - 40
    for xx in range(col_x0, glyph_x0 - 6, 4):
        draw.point((xx, 100), fill=SPECTRA6["white"])
    for k in range(3):
        cx = glyph_x0 + 4 + k * 14
        filled = (not stable) or k == 0
        draw.ellipse((cx - 4, 96, cx + 4, 104), fill=SPECTRA6["yellow"] if filled else None,
                     outline=SPECTRA6["yellow"])


def _trisolaris_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> int:
    """The quote in the dark sky: solid white prose, the matched phrase lit as
    sunlight. Returns the block's bottom y.

    The prose is deliberately unlit: even a faint blue halo reads as an
    outline round every letter.
    """
    prose, hot, bottom = wrap_quote_into_masks(
        draw, image.size, quote_row, _TRISOLARIS_QUOTE_RECT, theme="trisolaris",
        font_max=30, font_min=14, line_height_mult=1.32,
    )
    image.paste(SPECTRA6["white"], (0, 0), prose.point(lambda v: 255 if v > 128 else 0))
    paint_neon_mask(
        image, hot, SPECTRA6["yellow"], SPECTRA6["red"],
        radius=4, gamma=1.5, cap=0.6, ground=frozenset({SPECTRA6["black"], SPECTRA6["blue"]}),
        tile=BAYER_8x8,
        glow_minor=SPECTRA6["yellow"], glow_minor_share=0.375,
    )
    return bottom


def _trisolaris_paint_credits(draw: ImageDraw.ImageDraw, quote_row: dict, top: int) -> None:
    col_x0, col_x1 = _TRISOLARIS_COLUMN
    font = load_font([TITILLIUM_ITALIC, *META_FONT_CANDIDATES], 15)
    draw_truncated_centred_byline(draw, quote_row, centre=(col_x0 + col_x1) // 2,
                                  baseline=min(412, top + 26), max_width=col_x1 - col_x0,
                                  font=font, fill=SPECTRA6["white"])


def _trisolaris_paint_warning(draw: ImageDraw.ImageDraw) -> None:
    """The pacifist's reply, three times along the foot.

    Solid yellow, not red: at 11px red barely clears the panel's black, and a
    two-ink tangerine shreds a letterform that small.
    """
    col_x0, col_x1 = _TRISOLARIS_COLUMN
    font = load_font([SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], 11)
    for repeats in (3, 2, 1):
        text = "  ".join([_TRISOLARIS_WARNING] * repeats)
        width = draw.textlength(text, font=font)
        if width <= col_x1 - col_x0:
            break
    draw.text(((col_x0 + col_x1 - width) / 2, _TRISOLARIS_WARNING_Y), text, font=font, fill=SPECTRA6["yellow"])


def render_trisolaris_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The Trisolaran sky (see the module section comment above)."""
    index = _trisolaris_index(time_str)
    image = Image.new("RGB", (800, 480), color=SPECTRA6["black"])
    _trisolaris_paint_sky(image)
    _trisolaris_paint_orbits(image, index)
    _trisolaris_paint_red_coast(image)
    _trisolaris_paint_bodies(image, index)
    draw = ImageDraw.Draw(image)
    _trisolaris_paint_header(draw, time_str)
    bottom = _trisolaris_paint_quote(image, draw, quote_row)
    _trisolaris_paint_credits(draw, quote_row, bottom)
    _trisolaris_paint_warning(draw)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("trisolaris",), render=render_trisolaris_frame)
