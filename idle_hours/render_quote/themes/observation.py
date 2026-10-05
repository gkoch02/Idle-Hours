"""The ``observation`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from .._paths import (
    META_FONT_BOLD_CANDIDATES,
    META_FONT_CANDIDATES,
    PLEXMONO_BOLD,
    PLEXMONO_MEDIUM,
    PLEXMONO_SEMIBOLD,
    SPACEMONO_BOLD,
    SPACEMONO_REGULAR,
)
from ..fonts import load_font
from ..furniture import _clock_hour12, _row_digest, fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, snap_image_to_palette
from ..primitives import paint_neon_mask, position_noise, wrap_quote_into_masks
from ..spec import FrameSpec
from ..text import fit_text_to_width

# ---------------------------------------------------------------------------
# observation — S.A.M.'s camera feed, after No Code's *Observation* (2019)
# ---------------------------------------------------------------------------
# The quote as seen by S.A.M., the AI of the Observation station orbiting
# Saturn: one camera feed with the AI's interface laid over it.
#
# * **The feed.** Black space, a seeded star field, and Saturn — a banded
#   disc shaded by a terminator, its blue-grey north polar cap carrying the
#   hexagonal jet stream, and the rings cast as a tilted annulus that passes
#   *behind* the planet on the far side and *in front* of it on the near side.
#   Titan is a small tangerine disc. Faint blue sensor noise, and three
#   tracking tears shear bands of the feed sideways.
# * **The anomaly.** Nested glowing hexagons (white core, blue bloom) below
#   the rings, boxed by a yellow tracking reticle.
# * **The HUD.** Camera-frame corner brackets, the S.A.M. identifier, a red
#   REC tally and the camera's designation across the top; an uplink meter
#   and a station schematic along the foot, the current camera's module lit.
# * **The quote is an audio log.** An opaque terminal panel on the left with
#   an inverted header naming the author as the log's source, the quote set
#   ragged-right in white Plex Mono, the matched phrase yellow with a
#   tangerine halo, a playback waveform, and the title as the file name.
#
# **Saturn's shading** is a *single* ``BAYER_8x8`` read partitioned three
# ways: the lowest ranks take black for the terminator and the rest split
# between the band's two inks in its own ratio (``pride``'s rule — a second
# read would drift the hue across the terminator instead of darkening it).
#
# **The time is the camera number, hour only** (``CAM 07`` reads as a feed);
# the frame is pinned byte-identical across the minutes of an hour by
# ``TestObservationFrame``. The hour also picks the lit schematic module.
#
# The log number and the waveform are seeded from ``_row_digest``, never the
# clock.
#
# Composed at the canonical 800x480 and NEAREST-downsampled for other sizes
# (``metro`` convention).
# ---------------------------------------------------------------------------
_OBSERVATION_PANEL = (26, 50, 436, 424)
_OBSERVATION_HEADER_H = 24
_OBSERVATION_QUOTE_RECT = (44, 92, 420, 346)
_OBSERVATION_WAVE_RECT = (44, 362, 420, 390)
_OBSERVATION_FILE_Y = 398
_OBSERVATION_SATURN = (636, 206, 108)       # centre x, centre y, radius
_OBSERVATION_TILT = 0.22                    # ring-plane rotation, radians
_OBSERVATION_RING_K = 0.36                  # ring ellipse minor/major = sin(pole tilt)
_OBSERVATION_LIGHT = (-0.62, -0.42, 0.66)   # sun direction (screen x, y, toward viewer)
# Saturn's bands, north to south, as (lower sin-latitude bound, major ink,
# minor ink, minor share): a blue polar cap, then mostly cream zones broken by
# thin gold and tangerine belts (saturated orange stripes read as a beach ball).
_OBSERVATION_BANDS = (
    (0.80, "blue", "white", 0.50),
    (0.68, "white", "yellow", 0.45),
    (0.58, "red", "yellow", 0.45),
    (0.36, "yellow", "white", 0.45),
    (0.26, "red", "yellow", 0.50),
    (0.10, "yellow", "white", 0.38),
    (-0.08, "white", "yellow", 0.40),
    (-0.18, "yellow", "red", 0.30),
    (-2.00, "yellow", "white", 0.45),
)
_OBSERVATION_HEX_LAT = 0.975                # sin(78 deg N) — the real hexagon's latitude
# Rings as (inner, outer radius in planet radii, major ink, minor ink,
# minor share, fill density). The Cassini division and Encke gap are the
# spaces between entries.
_OBSERVATION_RINGS = (
    (1.24, 1.52, "yellow", "white", 0.50, 0.26),   # C ring: faint
    (1.52, 1.94, "white", "yellow", 0.40, 0.92),   # B ring: the bright one
    (2.02, 2.16, "yellow", "white", 0.35, 0.66),   # A ring, inside Encke
    (2.19, 2.26, "yellow", "red", 0.30, 0.55),     # A ring, outside Encke
    (2.33, 2.35, "white", "white", 0.00, 0.45),    # F ring: a thread
)
_OBSERVATION_TITAN = (474, 96, 7)
_OBSERVATION_STAR_SEED = 0x0B5E
_OBSERVATION_STAR_COUNT = 190
# Tracking tears, as (top y, height, horizontal shift). Applied to the feed
# only, before the HUD, so a tear can never cut the quote.
_OBSERVATION_TEARS = ((150, 3, 11), (238, 2, -9), (300, 4, 15))
_OBSERVATION_ANOMALY = (548, 380, 22)       # centre x, centre y, outer hexagon radius
_OBSERVATION_MAP_RECT = (604, 422, 776, 466)
# Two cameras per module; the hour picks the camera, the camera picks the module.
_OBSERVATION_MODULES = ("HAB", "SCIENCE", "COMMS", "ENGINEERING", "AIRLOCK", "OBSERVATION")


def _observation_module_index(camera: int) -> int:
    return (camera - 1) // 2 % len(_OBSERVATION_MODULES)


def _observation_mix(rank: int, black: float, major, minor, share: float):
    """One ``BAYER_8x8`` rank, partitioned three ways: shade, then band mix.

    The lowest ``round(black * 64)`` ranks take black; the remainder splits
    between the band's two inks in its own ratio. One read, never two.
    """
    nb = int(round(black * 64))
    if rank < nb:
        return SPECTRA6["black"]
    return minor if (rank - nb) < share * (64 - nb) else major


def _observation_paint_stars(image: Image.Image) -> None:
    rng = random.Random(_OBSERVATION_STAR_SEED)
    px = image.load()
    width, height = image.size
    white, yellow, blue = SPECTRA6["white"], SPECTRA6["yellow"], SPECTRA6["blue"]
    for _ in range(_OBSERVATION_STAR_COUNT):
        x, y = rng.randrange(width), rng.randrange(height)
        roll = rng.random()
        ink = yellow if roll < 0.06 else blue if roll < 0.12 else white
        px[x, y] = ink
        if rng.random() < 0.09 and x + 1 < width and y + 1 < height:
            px[x + 1, y] = px[x, y + 1] = px[x + 1, y + 1] = white


def _observation_ring_frame(dx: float, dy: float):
    """Screen offset from Saturn's centre → ring-plane coordinates (u, v)."""
    c, s = math.cos(_OBSERVATION_TILT), math.sin(_OBSERVATION_TILT)
    return dx * c + dy * s, -dx * s + dy * c


def _observation_from_ring_frame(u: float, v: float):
    c, s = math.cos(_OBSERVATION_TILT), math.sin(_OBSERVATION_TILT)
    return u * c - v * s, u * s + v * c


def _observation_paint_saturn(image: Image.Image) -> None:
    """The planet: latitude bands, a lit limb and a terminator, one read per pixel."""
    cx, cy, r = _OBSERVATION_SATURN
    width, height = image.size
    px = image.load()
    k = _OBSERVATION_RING_K
    cos_phi = math.sqrt(1 - k * k)
    lx, ly, lz = _OBSERVATION_LIGHT
    norm = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / norm, ly / norm, lz / norm
    inks = {name: SPECTRA6[name] for name in ("white", "yellow", "red", "blue")}
    for y in range(max(0, cy - r), min(height, cy + r + 1)):
        row = BAYER_8x8[y % 8]
        dy = y - cy
        for x in range(max(0, cx - r), min(width, cx + r + 1)):
            dx = x - cx
            d2 = dx * dx + dy * dy
            if d2 > r * r:
                continue
            z = math.sqrt(r * r - d2)
            u, v = _observation_ring_frame(dx, dy)
            # sin(latitude): north is -v, and the pole leans toward us by k.
            lat = (-v * cos_phi + z * k) / r
            lat += 0.018 * math.sin(u * 0.11 + lat * 9.0)       # band turbulence
            for upper, major, minor, share in _OBSERVATION_BANDS:
                if lat >= upper:
                    break
            lit = (dx * lx + dy * ly + z * lz) / r
            limb = z / r
            shade = 0.08 + max(0.0, 0.55 - lit) * 1.5 + (1 - limb) ** 3 * 0.35
            shade = min(0.94, shade)
            px[x, y] = _observation_mix(row[x % 8], shade, inks[major], inks[minor], share)


def _observation_paint_hexagon(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """Saturn's north-polar hexagon, projected onto the visible pole."""
    cx, cy, r = _OBSERVATION_SATURN
    k = _OBSERVATION_RING_K
    cos_phi = math.sqrt(1 - k * k)
    sin_lat = _OBSERVATION_HEX_LAT
    cos_lat = math.sqrt(1 - sin_lat * sin_lat)
    pole = (0.0, -cos_phi, k)
    e2 = (0.0, k, cos_phi)
    pts = []
    for i in range(7):
        a = math.radians(60 * i + 15)
        u = r * (sin_lat * pole[0] + cos_lat * math.cos(a))
        v = r * (sin_lat * pole[1] + cos_lat * math.sin(a) * e2[1])
        dx, dy = _observation_from_ring_frame(u, v)
        pts.append((cx + dx, cy + dy))
    draw.line([(round(x), round(y)) for x, y in pts], fill=SPECTRA6["blue"], width=2, joint="curve")


def _observation_paint_rings(image: Image.Image) -> None:
    """The ring system: behind the planet on the far side, over it on the near."""
    cx, cy, r = _OBSERVATION_SATURN
    width, height = image.size
    px = image.load()
    k = _OBSERVATION_RING_K
    outer = _OBSERVATION_RINGS[-1][1] * r
    reach_x = int(outer) + 2
    reach_y = int(outer * max(abs(math.sin(_OBSERVATION_TILT)), k)) + int(outer * k) + 4
    inks = {name: SPECTRA6[name] for name in ("white", "yellow", "red")}
    black = SPECTRA6["black"]
    for y in range(max(0, cy - reach_y), min(height, cy + reach_y + 1)):
        row = BAYER_8x8[y % 8]
        dy = y - cy
        for x in range(max(0, cx - reach_x), min(width, cx + reach_x + 1)):
            dx = x - cx
            u, v = _observation_ring_frame(dx, dy)
            rho = math.sqrt(u * u + (v / k) ** 2) / r
            if rho < _OBSERVATION_RINGS[0][0] or rho > _OBSERVATION_RINGS[-1][1]:
                continue
            on_disc = dx * dx + dy * dy <= r * r
            if on_disc and v < 0:
                continue                                    # far side, hidden by the planet
            # Over the disc the rings are translucent: an unlit tile cell and
            # a gap both leave the planet showing, rather than punching black.
            for inner, outer_r, major, minor, share, density in _OBSERVATION_RINGS:
                if inner <= rho < outer_r:
                    rank = row[x % 8]
                    if rank < density * 64:
                        px[x, y] = _observation_mix(rank, 0.0, inks[major], inks[minor], share)
                    elif not on_disc:
                        px[x, y] = black
                    break
            else:
                if not on_disc:
                    px[x, y] = black                        # Cassini division / Encke gap


def _observation_paint_titan(draw: ImageDraw.ImageDraw, image: Image.Image) -> None:
    """Titan: a small tangerine disc with a lit crescent of white haze."""
    tx, ty, tr = _OBSERVATION_TITAN
    px = image.load()
    red, yellow, white = SPECTRA6["red"], SPECTRA6["yellow"], SPECTRA6["white"]
    for y in range(ty - tr, ty + tr + 1):
        row = BAYER_8x8[y % 8]
        for x in range(tx - tr, tx + tr + 1):
            d2 = (x - tx) ** 2 + (y - ty) ** 2
            if d2 > tr * tr:
                continue
            rank = row[x % 8]
            haze = (x - tx) + (y - ty) < -tr * 0.9 and d2 > (tr - 2) ** 2
            px[x, y] = white if haze else (yellow if rank < 24 else red)


def _observation_paint_noise(image: Image.Image) -> None:
    """Faint blue sensor noise on the black of the feed — every third row."""
    width, height = image.size
    px = image.load()
    black, blue = SPECTRA6["black"], SPECTRA6["blue"]
    for y in range(0, height, 3):
        for x in range(width):
            if px[x, y] == black and position_noise(x, y) % 16 == 0:
                px[x, y] = blue


def _observation_paint_tears(image: Image.Image) -> None:
    """Tracking tears: thin bands of the feed sheared sideways (feed only)."""
    width, height = image.size
    for top, band_h, shift in _OBSERVATION_TEARS:
        if top + band_h > height:
            continue
        band = image.crop((0, top, width, top + band_h))
        image.paste(SPECTRA6["black"], (0, top, width, top + band_h))
        image.paste(band, (shift, top))


def _observation_hex_points(cx: float, cy: float, radius: float, rot: float = 0.0):
    return [(cx + radius * math.cos(math.radians(60 * i + 30 + rot)),
             cy + radius * math.sin(math.radians(60 * i + 30 + rot))) for i in range(6)]


def _observation_paint_anomaly(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    """The anomaly: nested hexagons, white-cored, blooming blue into space."""
    ax, ay, ar = _OBSERVATION_ANOMALY
    mask = Image.new("L", image.size, 0)
    md = ImageDraw.Draw(mask)
    for radius, rot, stroke in ((ar, 0, 3), (ar * 0.62, 30, 2), (ar * 0.3, 0, 2)):
        pts = [(round(x), round(y)) for x, y in _observation_hex_points(ax, ay, radius, rot)]
        md.line(pts + [pts[0]], fill=255, width=stroke, joint="curve")
    for x, y in _observation_hex_points(ax, ay, ar):
        md.line([(ax, ay), (round(x), round(y))], fill=255, width=1)
    paint_neon_mask(image, mask, SPECTRA6["white"], SPECTRA6["blue"],
                    radius=6, gamma=1.3, cap=0.78,
                    ground=frozenset({SPECTRA6["black"]}), tile=BAYER_8x8)
    mask.close()


def _observation_brackets(draw, box, length: int, fill, width: int) -> None:
    """Four L-shaped corner brackets — the camera-frame idiom."""
    x0, y0, x1, y1 = box
    for (x, y, sx, sy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        draw.line([(x, y + sy * length), (x, y), (x + sx * length, y)], fill=fill, width=width)


def _observation_paint_tracker(draw: ImageDraw.ImageDraw) -> None:
    """A yellow tracking reticle round the anomaly, with S.A.M.'s label."""
    ax, ay, ar = _OBSERVATION_ANOMALY
    yellow, white = SPECTRA6["yellow"], SPECTRA6["white"]
    pad = ar + 14
    _observation_brackets(draw, (ax - pad, ay - pad, ax + pad, ay + pad), 9, yellow, 2)
    for x0, x1 in ((ax - pad - 12, ax - pad - 3), (ax + pad + 3, ax + pad + 12)):
        draw.line([(x0, ay), (x1, ay)], fill=yellow, width=1)
    label = load_font([PLEXMONO_SEMIBOLD, SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=11)
    tx = ax + pad + 16
    draw.text((tx, ay - 20), "UNIDENTIFIED OBJECT", font=label, fill=white)
    draw.text((tx, ay - 5), "TRACKING", font=label, fill=yellow)
    draw.text((tx + draw.textlength("TRACKING ", font=label), ay - 5), "— NO DATA", font=label, fill=white)


def _observation_paint_chrome(image: Image.Image, draw: ImageDraw.ImageDraw, camera: int) -> None:
    """Camera brackets, the S.A.M. identifier, REC tally and camera designation."""
    width, height = image.size
    white, red, yellow = SPECTRA6["white"], SPECTRA6["red"], SPECTRA6["yellow"]
    _observation_brackets(draw, (10, 10, width - 11, height - 11), 24, white, 2)
    big = load_font([PLEXMONO_BOLD, SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=17)
    small = load_font([PLEXMONO_SEMIBOLD, SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=11)
    draw.text((42, 16), "S.A.M.", font=big, fill=white)
    draw.text((42 + draw.textlength("S.A.M. ", font=big), 21),
              "SYSTEMS ADMINISTRATION & MAINTENANCE", font=small, fill=white)
    module = _OBSERVATION_MODULES[_observation_module_index(camera)]
    cam = f"CAM {camera:02d} · {module}"
    right = width - 42
    cam_w = draw.textlength(cam, font=big)
    draw.text((right - cam_w, 16), cam, font=big, fill=yellow)
    rec_w = draw.textlength("REC", font=small)
    rx = right - cam_w - 18 - rec_w
    draw.text((rx, 21), "REC", font=small, fill=red)
    draw.ellipse((rx - 14, 22, rx - 5, 31), fill=red)


def _observation_paint_uplink(draw: ImageDraw.ImageDraw) -> None:
    """Foot-left: the uplink meter — three of five bars, and a red DEGRADED."""
    white, green, red = SPECTRA6["white"], SPECTRA6["green"], SPECTRA6["red"]
    small = load_font([PLEXMONO_SEMIBOLD, SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=11)
    x, base = 42, 460
    draw.text((x, base - 14), "UPLINK / EARTH", font=small, fill=white)
    bx = x + draw.textlength("UPLINK / EARTH ", font=small) + 4
    for i in range(5):
        h = 5 + i * 3
        box = (bx + i * 9, base - h, bx + i * 9 + 5, base)
        if i < 3:
            draw.rectangle(box, fill=green)
        else:
            draw.rectangle(box, outline=white, width=1)
    draw.text((bx + 5 * 9 + 10, base - 14), "DEGRADED", font=small, fill=red)


def _observation_paint_map(draw: ImageDraw.ImageDraw, camera: int) -> None:
    """Foot-right: the station schematic, the current camera's module lit."""
    x0, y0, x1, y1 = _OBSERVATION_MAP_RECT
    white, yellow, black = SPECTRA6["white"], SPECTRA6["yellow"], SPECTRA6["black"]
    tiny = load_font([PLEXMONO_SEMIBOLD, SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=9)
    draw.text((x0, y0 - 12), "STATION MAP", font=tiny, fill=white)
    spine_y = (y0 + y1) // 2 + 4
    draw.line([(x0 + 6, spine_y), (x1 - 6, spine_y)], fill=white, width=1)
    lit = _observation_module_index(camera)
    n = len(_OBSERVATION_MODULES)
    step = (x1 - x0 - 12) / (n - 1)
    for i in range(n):
        mx = round(x0 + 6 + i * step)
        above = i % 2 == 0
        top, bottom = (spine_y - 18, spine_y - 5) if above else (spine_y + 5, spine_y + 18)
        draw.line([(mx, spine_y), (mx, top if not above else bottom)], fill=white, width=1)
        box = (mx - 9, top, mx + 9, bottom)
        if i == lit:
            draw.rectangle(box, fill=yellow, outline=yellow)
        else:
            draw.rectangle(box, fill=black, outline=white, width=1)
    draw.ellipse((x1 - 6 - 2, spine_y - 2, x1 - 6 + 2, spine_y + 2), fill=white)


def _observation_log_header(quote_row: dict) -> str:
    author = (quote_row.get("author") or "").strip()
    return f"AUDIO LOG — {author.upper()}" if author else "AUDIO LOG — UNATTRIBUTED"


def _observation_paint_panel(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The audio-log terminal: header, transcript, waveform, file name."""
    x0, y0, x1, y1 = _OBSERVATION_PANEL
    white, black, yellow, red, green = (SPECTRA6[n] for n in ("white", "black", "yellow", "red", "green"))
    draw.rectangle((x0, y0, x1, y1), fill=black, outline=white, width=1)
    _observation_brackets(draw, (x0 - 3, y0 - 3, x1 + 3, y1 + 3), 14, white, 3)

    # Header: inverted strip, log source left, recording number right.
    hy1 = y0 + _OBSERVATION_HEADER_H
    draw.rectangle((x0, y0, x1, hy1), fill=white)
    digest = _row_digest(quote_row)
    log_no = f"#{digest % 10000:04d}"
    chrome = [PLEXMONO_BOLD, SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES]
    num_font = load_font(chrome, size=12)
    num_w = draw.textlength(log_no, font=num_font)
    draw.text((x1 - 10 - num_w, y0 + 5), log_no, font=num_font, fill=black)
    font, text = fit_text_to_width(draw, _observation_log_header(quote_row), chrome, 13,
                                   x1 - x0 - 34 - num_w, floor=10)
    draw.text((x0 + 10, y0 + 5), text, font=font, fill=black)

    # Transcript: white prose, the matched phrase yellow in a tangerine halo.
    prose, hot, _ = wrap_quote_into_masks(
        draw, image.size, quote_row, _OBSERVATION_QUOTE_RECT, theme="observation",
        font_max=36, font_min=13, line_height_mult=1.34, align="left",
    )
    image.paste(white, (0, 0), prose.point(lambda v: 255 if v > 128 else 0))
    paint_neon_mask(
        image, hot, yellow, red,
        radius=3, gamma=1.8, cap=0.5,
        ground=frozenset({black}), tile=BAYER_8x8,
        glow_minor=yellow, glow_minor_share=0.375,
    )
    prose.close()
    hot.close()

    # Playback waveform: green bars, a yellow playhead, played part solid.
    wx0, wy0, wx1, wy1 = _OBSERVATION_WAVE_RECT
    mid = (wy0 + wy1) // 2
    rng = random.Random(digest)
    head = wx0 + int((wx1 - wx0) * (0.35 + 0.5 * rng.random()))
    draw.line([(wx0, mid), (wx1, mid)], fill=green, width=1)
    for x in range(wx0, wx1, 4):
        env = 0.35 + 0.65 * abs(math.sin((x - wx0) * 0.045 + rng.random() * 0.6))
        amp = max(1, int((wy1 - wy0) / 2 * env * (0.4 + 0.6 * rng.random())))
        if x < head:
            draw.rectangle((x, mid - amp, x + 1, mid + amp), fill=green)
        else:
            draw.line([(x, mid - amp), (x, mid + amp)], fill=green, width=1)
    draw.line([(head, wy0 - 3), (head, wy1 + 3)], fill=yellow, width=2)

    # File line: the title as the recording's file name.
    title = (quote_row.get("title") or fallback_title(quote_row) or "").strip()
    meta = [PLEXMONO_MEDIUM, SPACEMONO_REGULAR, *META_FONT_CANDIDATES]
    label_font = load_font(chrome, size=11)
    draw.text((x0 + 18, _OBSERVATION_FILE_Y), "FILE", font=label_font, fill=yellow)
    fx = x0 + 18 + draw.textlength("FILE  ", font=label_font)
    if title:
        font, text = fit_text_to_width(draw, title.upper(), meta, 11, x1 - 14 - fx, floor=9)
        draw.text((fx, _OBSERVATION_FILE_Y), text, font=font, fill=white)


def render_observation_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """S.A.M.'s camera feed of Saturn (see the module section comment above)."""
    camera = _clock_hour12(time_str)
    image = Image.new("RGB", (800, 480), color=SPECTRA6["black"])
    draw = ImageDraw.Draw(image)
    _observation_paint_stars(image)
    _observation_paint_saturn(image)
    _observation_paint_hexagon(image, draw)
    _observation_paint_rings(image)
    _observation_paint_titan(draw, image)
    _observation_paint_noise(image)
    _observation_paint_tears(image)
    _observation_paint_anomaly(image, draw)
    _observation_paint_tracker(draw)
    _observation_paint_chrome(image, draw, camera)
    _observation_paint_uplink(draw)
    _observation_paint_map(draw, camera)
    _observation_paint_panel(image, draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("observation",), render=render_observation_frame)
