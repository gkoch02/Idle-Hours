"""The ``nocturne`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from ..fonts import load_font, theme_font_candidates
from ..furniture import fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, snap_image_to_palette
from ..primitives import _flow_stroke_hash, paint_flow_strokes, paint_neon_mask, wrap_quote_into_masks
from ..spec import FrameSpec

# ---------------------------------------------------------------------------
# nocturne — Whistler, Nocturne in Blue and Gold
#
# The Thames at Battersea as Whistler painted it around 1875: a near-black
# blue night of brushwork, punctured by gold. Sky and water are short
# streamline strokes advected through direction fields (``paint_flow_strokes``)
# rather than per-pixel stipple. Full design notes: docs/themes.md
# (``nocturne``).
#
# **Two fields, one vocabulary.** The sky's strokes are sparse, thin and
# near-horizontal, thinning with altitude; the water's are denser, wider and
# shimmer, with an occasional stroke flipped to green in the mid-water (the
# verdigris glaze). The shore is painted *after* the strokes as a solid
# silhouette (plus the shot tower and a chimney), so land reads as the
# absence of light and crops any stroke overhang.
#
# **The gold is bakelite's split-band recipe** (red-major tangerine halo at
# Y 3/8, yellow-major core at Y 5/8, on the 8x8 tile): shore lights, the
# rocket's sparks, the matched phrase and the butterfly monogram. The
# reflections are a third ``paint_flow_strokes`` pass with a near-vertical
# swaying field. Each gold tier accumulates into ONE mask and blooms once (no
# double exposure), and every pass takes ``ground=_nocturne_ground()`` so
# later light never eats earlier light.
#
# **The quote sits in the night.** Prose has white cores with a faint cold
# blue halo; the matched phrase is the brightest gold after the rocket. The
# block sits left of centre so the spark shower owns the upper right.
#
# **No hour carrier: ``time_str`` is del-asserted**, so every render of a row
# is byte-identical at any clock time (pinned by ``TestNocturneBrushwork``).
_NOCTURNE_SKY_BOTTOM = 238
_NOCTURNE_SHORE = (238, 272)
_NOCTURNE_TOWER = (588, 196, 610, 238)         # the Battersea shot tower
_NOCTURNE_CHIMNEY = (636, 212, 644, 238)
_NOCTURNE_QUOTE_RECT = (72, 70, 556, 232)
_NOCTURNE_ROCKET_APEX = (668, 62)
_NOCTURNE_LIGHTS = ((58, 268), (150, 266), (232, 269), (335, 267), (452, 268),
                    (540, 266), (622, 269), (700, 267), (762, 268))
_NOCTURNE_GOLD_HALO_YELLOW = 0.375             # R+Y 5/8:3/8 tangerine, the halo
_NOCTURNE_GOLD_CORE_YELLOW = 0.625             # Y+R 5/8:3/8 gold, the lit stroke
_NOCTURNE_SKY_CELL = 13
_NOCTURNE_WATER_CELL = 8


def _nocturne_ground() -> frozenset:
    """Inks a stroke pass or bloom may overwrite: the night's own colours.

    White, yellow and red are excluded so no later pass can dim a core, a
    spark or a reflection an earlier one already lit.
    """
    return frozenset({SPECTRA6["black"], SPECTRA6["blue"], SPECTRA6["green"]})


def _nocturne_field_sky(x: float, y: float) -> float:
    """Direction of the sky's brushwork: near-horizontal, gently arcing.

    Wavelengths (140 / 220 px) sit far above the 13 px stroke cell so
    neighbouring strokes agree — the coherence rule in ``paint_flow_strokes``.
    """
    return 0.06 * math.sin(x / 140.0) + 0.05 * math.sin((x + y) / 220.0)


def _nocturne_field_water(x: float, y: float) -> float:
    """Direction of the water: horizontal with a shimmer that calms with depth."""
    depth = max(0.0, y - _NOCTURNE_SHORE[1])
    return 0.07 * math.sin(x / 70.0 + y / 45.0) * max(0.35, 1.0 - depth / 300.0)


def _nocturne_sky_ink(x: int, y: int, r: float):
    """Sky stroke acceptance: near-empty at the zenith, quarter-cover at the
    horizon, all blue."""
    density = 0.05 + 0.30 * (y / _NOCTURNE_SKY_BOTTOM) ** 2
    return SPECTRA6["blue"] if r < density else None


def _nocturne_water_ink(x: int, y: int, r: float):
    """Water stroke acceptance, thinning with depth; about one accepted stroke
    in seventeen is green in the mid-water — Whistler's verdigris glaze."""
    depth = max(0.0, y - _NOCTURNE_SHORE[1]) / 208.0
    if r > 0.85 - 0.38 * depth:
        return None
    if 300 <= y <= 400 and int(r * 997) % 17 == 0:
        return SPECTRA6["green"]
    return SPECTRA6["blue"]


def _nocturne_paint_gold(image: Image.Image, mask: Image.Image, core=None,
                         *, radius: int = 4, gamma: float = 1.6, cap: float = 0.55) -> None:
    """Bloom a mask as Whistler's gold — the bakelite amber recipe on the
    night's ground.

    Thin wrapper over ``paint_neon_mask``: red halo carrying 3/8 yellow, gold
    core carrying 5/8 (solid yellow reads lemon). Pass an explicit ``core``
    ink to pin it solid.
    """
    paint_neon_mask(
        image, mask,
        core if core is not None else SPECTRA6["red"], SPECTRA6["red"],
        radius=radius, gamma=gamma, cap=cap, ground=_nocturne_ground(), tile=BAYER_8x8,
        glow_minor=SPECTRA6["yellow"], glow_minor_share=_NOCTURNE_GOLD_HALO_YELLOW,
        core_minor=None if core is not None else SPECTRA6["yellow"],
        core_minor_share=_NOCTURNE_GOLD_CORE_YELLOW,
    )


def _nocturne_paint_night(image: Image.Image) -> None:
    """Layer 0: the black night, with a whisper of blue haze at the horizon,
    kept faint so the light sources stay the subject."""
    ImageDraw.Draw(image).rectangle((0, 0, 799, 479), fill=SPECTRA6["black"])
    px = image.load()
    blue = SPECTRA6["blue"]
    # BAYER_8x8, not 4x4: a ramp on the 17-level tile steps visibly into a
    # hard halftone stripe. The rank is jittered by the position hash (~half a
    # cell) so the ramp doesn't lay a dot lattice.
    for y in range(_NOCTURNE_SKY_BOTTOM - 90, _NOCTURNE_SKY_BOTTOM):
        lift = (y - (_NOCTURNE_SKY_BOTTOM - 90)) / 90.0
        row = BAYER_8x8[y % 8]
        threshold = lift * lift * 7.0
        for x in range(800):
            rank = row[x % 8] + (_flow_stroke_hash(x, y, 11) - 0.5) * 30.0
            if rank < threshold:
                px[x, y] = blue


def _nocturne_paint_strokes(image: Image.Image) -> None:
    """The capability showcase: sky and water as advected brushwork."""
    ground = _nocturne_ground()
    paint_flow_strokes(image, (0, 0, 800, _NOCTURNE_SKY_BOTTOM),
                       _nocturne_field_sky, _nocturne_sky_ink,
                       cell=_NOCTURNE_SKY_CELL, length=16, width=1, ground=ground, salt=1)
    paint_flow_strokes(image, (0, _NOCTURNE_SHORE[1], 800, 480),
                       _nocturne_field_water, _nocturne_water_ink,
                       cell=_NOCTURNE_WATER_CELL, length=30, width=2, ground=ground, salt=2)


def _nocturne_paint_shore(image: Image.Image) -> None:
    """The far bank as absence of light: a solid band, the tower, a chimney.

    Painted after the strokes so it crops their overhang, which is also what
    makes its edge read as a horizon rather than a drawn line.
    """
    draw = ImageDraw.Draw(image)
    black = SPECTRA6["black"]
    draw.rectangle((0, _NOCTURNE_SHORE[0], 799, _NOCTURNE_SHORE[1]), fill=black)
    draw.rectangle(_NOCTURNE_TOWER, fill=black)
    tx0, ty0, tx1, _ = _NOCTURNE_TOWER
    draw.polygon([(tx0, ty0), (tx1, ty0), ((tx0 + tx1) // 2, ty0 - 14)], fill=black)
    draw.rectangle(_NOCTURNE_CHIMNEY, fill=black)


def _nocturne_paint_lights(image: Image.Image) -> None:
    """Gold pinpoints along the far bank, and their smeared reflections.

    The lights accumulate into one mask and bloom once. The reflections are a
    third ``paint_flow_strokes`` pass — near-vertical, swaying, thinning with
    depth — confined by its ``ink_at`` to narrow columns under each light, so
    the same primitive that painted the water also breaks its surface.
    """
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    for lx, ly in _NOCTURNE_LIGHTS:
        mask_draw.rectangle((lx, ly, lx + 1, ly + 1), fill=255)
    _nocturne_paint_gold(image, mask, radius=4, gamma=1.5, cap=0.6)

    columns = tuple(lx for lx, _ in _NOCTURNE_LIGHTS)

    def reflection_ink(x: int, y: int, r: float):
        depth = (y - _NOCTURNE_SHORE[1]) / 160.0
        if depth > 1.0 or r > max(0.15, 0.85 - depth):
            return None
        sway = 3.0 * math.sin(y / 22.0 + x)
        if min(abs(x + sway - c) for c in columns) > 2.5:
            return None
        return SPECTRA6["yellow"] if int(r * 991) % 3 else SPECTRA6["red"]

    paint_flow_strokes(image, (0, _NOCTURNE_SHORE[1] + 2, 800, _NOCTURNE_SHORE[1] + 164),
                       lambda x, y: math.pi / 2 + 0.28 * math.sin(y / 30.0 + x / 90.0),
                       reflection_ink, cell=5, length=11, width=1,
                       ground=_nocturne_ground(), salt=3)


def _nocturne_spark_points() -> list[tuple[int, int, int]]:
    """The Falling Rocket's spark shower: a fan of parabolic arcs, jittered
    deterministically. Returns ``(x, y, size)`` triples."""
    ax, ay = _NOCTURNE_ROCKET_APEX
    sparks = []
    for j in range(11):
        vx = -1.1 + 2.2 * j / 10.0
        for k in range(10):
            t = (k + 1) / 10.0
            jx = (_flow_stroke_hash(j, k, 41) - 0.5) * 12.0
            jy = (_flow_stroke_hash(j, k, 43) - 0.5) * 14.0
            x = int(ax + vx * 112.0 * t + jx)
            y = int(ay + (0.22 * t + 1.05 * t * t) * 170.0 + jy)
            if 8 <= x <= 792 and 4 <= y <= 256:
                sparks.append((x, y, 3 if t > 0.72 else 2))
    return sparks


def _nocturne_paint_rocket(image: Image.Image) -> None:
    """The Falling Rocket: gold sparks raining down the upper right.

    One mask, one bloom — brighter heads lower down the fall, the way burnt
    charges flare before they die.
    """
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    for x, y, size in _nocturne_spark_points():
        mask_draw.rectangle((x, y, x + size - 1, y + size - 1), fill=255)
    _nocturne_paint_gold(image, mask, radius=4, gamma=1.6, cap=0.55)


def _nocturne_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The quote in the night sky: white prose in cold halo, gold time phrase."""
    prose, hot, _ = wrap_quote_into_masks(
        draw, image.size, quote_row, _NOCTURNE_QUOTE_RECT,
        theme="nocturne", font_max=32, font_min=16, line_height_mult=1.5,
    )
    paint_neon_mask(image, prose, SPECTRA6["white"], SPECTRA6["blue"],
                    radius=3, gamma=2.0, cap=0.35, ground=_nocturne_ground())
    _nocturne_paint_gold(image, hot, radius=5, gamma=1.5, cap=0.55)


def _nocturne_paint_butterfly(image: Image.Image) -> None:
    """Whistler's butterfly monogram, bottom-right: the signature cartouche.

    Two wing silhouettes and a dropped sting, drawn small and bloomed at the
    tightest radius so it reads as a pressed gold seal rather than a light.
    """
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    bx, by = 754, 430
    mask_draw.polygon([(bx, by), (bx - 12, by - 9), (bx - 11, by + 7)], fill=255)
    mask_draw.polygon([(bx + 3, by), (bx + 14, by - 10), (bx + 14, by + 6)], fill=255)
    mask_draw.line([(bx + 1, by + 2), (bx - 2, by + 14)], fill=255, width=1)
    _nocturne_paint_gold(image, mask, radius=2, gamma=1.8, cap=0.4)


def _nocturne_paint_credits(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """Attribution, small and solid in the darkest water: unlit by design —
    bloom-vs-no-bloom is the hierarchy, per ``bakelite``."""
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or fallback_title(quote_row) or "").strip()
    parts = " — ".join(p for p in (author, title) if p)
    if not parts:
        return
    font = load_font(theme_font_candidates("nocturne", "quote_regular"), size=14)
    while draw.textlength(parts, font=font) > 470 and len(parts) > 8:
        parts = parts[:-2].rstrip(" ,.;:") + "…"
    draw.text((24, 452), parts, font=font, fill=SPECTRA6["white"], anchor="ls",
              stroke_width=2, stroke_fill=SPECTRA6["black"])


def render_nocturne_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Whistler's blue-and-gold night river (see the section comment).

    Composed at 800x480 and NEAREST-downsampled otherwise (the ``metro``
    convention): the geometry is absolute, and interpolation would average the
    strokework into blues the panel cannot print.
    """
    del time_str  # see the section comment; deliberately unused.
    image = Image.new("RGB", (800, 480), color=SPECTRA6["black"])
    _nocturne_paint_night(image)
    _nocturne_paint_strokes(image)
    _nocturne_paint_shore(image)
    _nocturne_paint_lights(image)
    _nocturne_paint_rocket(image)
    draw = ImageDraw.Draw(image)
    _nocturne_paint_quote(image, draw, quote_row)
    _nocturne_paint_butterfly(image)
    _nocturne_paint_credits(image, draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("nocturne",), render=render_nocturne_frame)
