"""The ``vitrail`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from ..fonts import _font_ascent, load_font, normalize_dashes, theme_font_candidates
from ..furniture import _clock_hour12, _fit_dotted_byline
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_4x4, pixel_access, snap_image_to_palette
from ..spec import FrameSpec
from ..text import draw_text_dithered
from ._shared import _TAROT_ROMAN_NUMERALS, _vitrail_fill_polygon

# ─── vitrail (Gothic stained-glass cathedral window) ─────────────────────────

# Geometry below is the 800×480 reference; render_vitrail_frame scales the
# rose / arch / cartouche positions by (width/800, height/480) so the frame
# composes at any resolution and reproduces these exact values at native size.
_VITRAIL_SURROUND = 16        # black stone masonry inset from the canvas edge
_VITRAIL_CAME_W = 5           # lead-came line thickness
_VITRAIL_ROSE_CY = 96         # rose-window medallion centre y (cx is always width//2)
_VITRAIL_ROSE_R = 74          # rose-window medallion radius
_VITRAIL_ARCH_SPRING_Y = 150  # where the pointed-arch spandrels meet the sides
_VITRAIL_GRID_COLS = 6
_VITRAIL_GRID_ROWS = 5
_VITRAIL_CAME_INNER = 3       # black core thickness of the came between glass shapes
_VITRAIL_CAME_BEVEL = 2       # highlight/shadow offset that fakes the rounded raised-lead 3D profile
# Irregular-tessellation controls. A fixed seed keeps every render of the
# window byte-identical (golden / dedup determinism); the jitter nudges the
# interior lattice vertices off the grid and the split probability decides how
# many cells break into two triangular shards — together they turn the regular
# grid into a hand-leaded mosaic of varied quadrilaterals and triangles.
_VITRAIL_SEED = 0x711A55
_VITRAIL_JITTER = 0.30
# Per-row split probability ramp: the top row sits behind the rose window, so
# keeping it calm (few shards) avoids slivers crowding the medallion; the
# bottom rows split heavily to break up otherwise-oversized flat panes.
_VITRAIL_SPLIT_PROB_TOP = 0.18
_VITRAIL_SPLIT_PROB_BOTTOM = 0.82
# Clear white-glass cartouche the literary quote is knocked out onto so the
# dark body text stays legible over the busy colored field. Fixed for the
# 800×480 panel, like the other custom-render frames' coordinates.
_VITRAIL_CARTOUCHE = (150, 200, 650, 392)
# Pointed-gable rise above the cartouche's top edge, echoing the lancet arch
# so the quote panel reads as a light set into the tracery. Kept shallow: the
# cartouche paints after the rose window, so a taller gable would erase the
# rose's lower petals.
_VITRAIL_CARTOUCHE_ARCH = 20

# Deterministic jewel-tone cycle for the leaded glass panes, covering the
# native inks plus the 2-/3-ink stipple recipes from spectra6_color_recipes.md.
# Each entry is a fill spec consumed by _vitrail_pane_ink / _vitrail_fill_polygon:
#   ("solid", ink)                  → a native Spectra-6 ink
#   ("2", dark, light, density)     → 2-ink stipple (mirrors _fill_swatch_stipple)
#   ("3", a, b, c, dens_a, dens_b)  → 3-ink Bayer partition (mirrors
#                                     _fill_swatch_stipple_3way)
_VITRAIL_GLASS: list[tuple] = [
    ("solid", SPECTRA6["red"]),                                  # ruby
    ("solid", SPECTRA6["blue"]),                                 # sapphire
    ("2", SPECTRA6["red"], SPECTRA6["yellow"], 0.375),           # amber / gold
    ("solid", SPECTRA6["green"]),                                # emerald
    ("2", SPECTRA6["red"], SPECTRA6["blue"], 0.5),               # royal purple
    ("solid", SPECTRA6["yellow"]),                               # solid gold
    ("2", SPECTRA6["green"], SPECTRA6["blue"], 0.375),           # teal
    ("3", SPECTRA6["red"], SPECTRA6["blue"], SPECTRA6["black"], 0.34, 0.33),   # plum
    ("2", SPECTRA6["red"], SPECTRA6["white"], 0.5),              # rose / coral
    ("2", SPECTRA6["blue"], SPECTRA6["black"], 0.5),             # navy
    ("2", SPECTRA6["yellow"], SPECTRA6["green"], 0.5),           # olive
    ("3", SPECTRA6["red"], SPECTRA6["blue"], SPECTRA6["white"], 0.34, 0.33),   # lavender
    ("2", SPECTRA6["blue"], SPECTRA6["white"], 0.5),             # sky blue
    ("2", SPECTRA6["green"], SPECTRA6["black"], 0.5),            # forest
    ("2", SPECTRA6["green"], SPECTRA6["white"], 0.5),            # mint
]


def _vitrail_build_panes(
    field: tuple[int, int, int, int], rose: tuple[float, float, float],
) -> list[tuple[list, tuple]]:
    """Deterministically tessellate the window opening into irregular leaded
    glass shapes.

    A jittered lattice (border vertices pinned, interior vertices nudged by a
    seeded RNG) yields irregular quads; some cells split along a diagonal into
    two triangular shards of different tones. The per-row +2 palette shear
    keeps vertically adjacent shapes from sharing a hue. Fixed seed, so the
    window is byte-identical on every render. Splitting ramps from calm at the
    top to busy at the bottom, and cells under the rose disc never split, so
    the medallion sits on calm glass."""
    x0, y0, x1, y1 = field
    cols, rows = _VITRAIL_GRID_COLS, _VITRAIL_GRID_ROWS
    rng = random.Random(_VITRAIL_SEED)
    cw = (x1 - x0) / cols
    ch = (y1 - y0) / rows
    jx = cw * _VITRAIL_JITTER
    jy = ch * _VITRAIL_JITTER
    rose_cx, rose_cy, rose_r = rose
    rose_keep_out = (rose_r + ch) ** 2
    pts: dict[tuple[int, int], tuple[float, float]] = {}
    for r in range(rows + 1):
        for c in range(cols + 1):
            px = x0 + c * cw
            py = y0 + r * ch
            if 0 < c < cols:
                px += rng.uniform(-jx, jx)
            if 0 < r < rows:
                py += rng.uniform(-jy, jy)
            pts[(r, c)] = (px, py)
    n = len(_VITRAIL_GLASS)
    panes: list[tuple[list, tuple]] = []
    for r in range(rows):
        row_frac = r / (rows - 1) if rows > 1 else 0.0
        split_prob = _VITRAIL_SPLIT_PROB_TOP + (_VITRAIL_SPLIT_PROB_BOTTOM - _VITRAIL_SPLIT_PROB_TOP) * row_frac
        for c in range(cols):
            tl = pts[(r, c)]
            tr = pts[(r, c + 1)]
            br = pts[(r + 1, c + 1)]
            bl = pts[(r + 1, c)]
            idx = (r * cols + c + r * 2) % n
            cell_cx = (tl[0] + tr[0] + br[0] + bl[0]) / 4
            cell_cy = (tl[1] + tr[1] + br[1] + bl[1]) / 4
            under_rose = (cell_cx - rose_cx) ** 2 + (cell_cy - rose_cy) ** 2 < rose_keep_out
            if not under_rose and rng.random() < split_prob:
                # Split into two triangular shards on one of the two diagonals.
                alt = _VITRAIL_GLASS[(idx + 7) % n]
                if rng.random() < 0.5:
                    panes.append(([tl, tr, br], _VITRAIL_GLASS[idx]))
                    panes.append(([tl, br, bl], alt))
                else:
                    panes.append(([tl, tr, bl], _VITRAIL_GLASS[idx]))
                    panes.append(([tr, br, bl], alt))
            else:
                panes.append(([tl, tr, br, bl], _VITRAIL_GLASS[idx]))
    return panes


def _vitrail_paint_glass_panes(image: Image.Image, panes: list) -> None:
    """Fill every leaded glass shape with its jewel tone."""
    for polygon, spec in panes:
        _vitrail_fill_polygon(image, polygon, spec)


# Diagonal specular "sheen" bands swept across the glass so the panes read as a
# glossy reflective surface catching light, not flat colour fields. Each entry
# is (centre_fraction, half_width_px, peak_density) in the t = x − y diagonal
# coordinate (lines of constant x − y run top-left → bottom-right, the classic
# glass-glint direction with light from the upper-left). White is stippled into
# the glass with density tapering linearly to zero at each band's edge.
_VITRAIL_SHIMMER = [(0.37, 120, 0.62), (0.63, 66, 0.40)]


def _vitrail_paint_shimmer(
    image: Image.Image,
    field: tuple[int, int, int, int],
    region: tuple[int, int, int, int] | None = None,
    clip: tuple[int, int, int] | None = None,
) -> None:
    """Sweep diagonal specular sheen bands across the filled glass.

    White is Bayer-stippled in at a density peaking on each band's centreline.
    Only glass-coloured pixels are touched (black and white are skipped); runs
    before the came / cartouche. A pure function of pixel position.

    Band positions always derive from ``field`` so a streak lands on the same
    diagonal everywhere. ``region`` restricts the pixels visited (to re-apply
    the same streaks to the rose glass); ``clip`` = ``(cx, cy, r)`` limits the
    pass to a disc."""
    WHITE = SPECTRA6["white"]
    BLACK = SPECTRA6["black"]
    fx0, fy0, fx1, fy1 = field
    t_min = fx0 - fy1
    span = (fx1 - fy0) - t_min
    if span <= 0:
        return
    bands = [(t_min + frac * span, hw, peak) for frac, hw, peak in _VITRAIL_SHIMMER]
    rx0, ry0, rx1, ry1 = region if region is not None else field
    rx0 = max(0, rx0)
    ry0 = max(0, ry0)
    rx1 = min(image.size[0], rx1)
    ry1 = min(image.size[1], ry1)
    cx = cy = 0  # read only when ``cr2`` is set, i.e. with a clip
    cr2 = None
    if clip is not None:
        cx, cy, cr = clip
        cr2 = cr * cr
    px = pixel_access(image)
    for y in range(ry0, ry1):
        brow = BAYER_4x4[y % 4]
        for x in range(rx0, rx1):
            cur = px[x, y]
            if cur == BLACK or cur == WHITE:
                continue
            if cr2 is not None and (x - cx) * (x - cx) + (y - cy) * (y - cy) > cr2:
                continue
            t = x - y
            best = 0.0
            for centre, hw, peak in bands:
                d = abs(t - centre)
                if d < hw:
                    dens = peak * (1.0 - d / hw)
                    if dens > best:
                        best = dens
            if best > 0.0 and brow[x % 4] < round(best * 16):
                px[x, y] = WHITE


def _vitrail_paint_arch_spandrels(
    image: Image.Image, draw: ImageDraw.ImageDraw, field: tuple[int, int, int, int], spring_y: int,
) -> None:
    """Carve a pointed (lancet) arch into the top of the colored field by
    filling the two top-corner spandrel triangles with black stone, so the
    glass reads as a Gothic arch rather than a plain rectangle."""
    BLACK = SPECTRA6["black"]
    x0, y0, x1, _ = field
    apex = ((x0 + x1) // 2, y0)
    draw.polygon([(x0, y0), apex, (x0, spring_y)], fill=BLACK)
    draw.polygon([apex, (x1, y0), (x1, spring_y)], fill=BLACK)


def _vitrail_paint_lead_came(
    draw: ImageDraw.ImageDraw, panes: list, field: tuple[int, int, int, int],
) -> None:
    """Trace lead came along every glass-shape boundary as a *beveled* raised
    bar, then lay the heavy outer window frame on top.

    Each seam is drawn in three passes, light from the upper-left: a white
    highlight offset up-left, a black drop shadow offset down-right, then the
    black core on the true path. Shared edges are painted twice, harmlessly."""
    BLACK = SPECTRA6["black"]
    WHITE = SPECTRA6["white"]
    core = _VITRAIL_CAME_INNER
    b = _VITRAIL_CAME_BEVEL
    for polygon, _ in panes:
        closed = [*polygon, polygon[0]]
        hi = [(x - b, y - b) for x, y in closed]
        sh = [(x + b, y + b) for x, y in closed]
        draw.line(hi, fill=WHITE, width=core, joint="curve")
        draw.line(sh, fill=BLACK, width=core, joint="curve")
        draw.line(closed, fill=BLACK, width=core, joint="curve")
    _vitrail_paint_outer_frame(draw, field)


def _vitrail_paint_outer_frame(draw: ImageDraw.ImageDraw, field: tuple[int, int, int, int]) -> None:
    """Heavy beveled stone surround around the whole window: the opening's
    top-left lip is lit white, the bottom-right stays black, so the masonry
    reads as raised stone with the glass recessed behind it."""
    BLACK = SPECTRA6["black"]
    WHITE = SPECTRA6["white"]
    came = _VITRAIL_CAME_W
    x0, y0, x1, y1 = field
    for o in range(came):
        draw.rectangle((x0 + o, y0 + o, x1 - o, y1 - o), outline=BLACK)
    # Lit top + left lip of the opening.
    ix0, iy0, ix1, iy1 = x0 + came, y0 + came, x1 - came, y1 - came
    draw.line((ix0, iy0, ix1, iy0), fill=WHITE, width=1)
    draw.line((ix0, iy0, ix0, iy1), fill=WHITE, width=1)


def _vitrail_paint_rose_window(
    image: Image.Image, draw: ImageDraw.ImageDraw, hour_int: int,
    cx: int, cy: int, R: int, came: int,
) -> None:
    """Top-centre rose-window medallion: a stone-ringed glass disc divided
    into twelve jewel-tone petal wedges by radial came, ringed by a band of
    small clear-glass foil roundels (the tracery a real rose window carries),
    with the Roman-numeral hour set in the ecclesiastical ornament face at the
    hub."""
    BLACK = SPECTRA6["black"]
    WHITE = SPECTRA6["white"]
    # Stone ring + clear glass disc base.
    draw.ellipse((cx - R - came, cy - R - came, cx + R + came, cy + R + came), fill=BLACK)
    draw.ellipse((cx - R, cy - R, cx + R, cy + R), fill=WHITE)
    # Twelve petal wedges cycling the four saturated inks.
    petals = 12
    wedge_inks = [SPECTRA6["red"], SPECTRA6["blue"], SPECTRA6["yellow"], SPECTRA6["green"]]
    for k in range(petals):
        start = k * 360 / petals
        end = (k + 1) * 360 / petals
        draw.pieslice((cx - R, cy - R, cx + R, cy + R), start, end, fill=wedge_inks[k % len(wedge_inks)])
    # Radial came between petals + a concentric rim ring.
    for k in range(petals):
        ang = math.radians(k * 360 / petals)
        ex = cx + R * math.cos(ang)
        ey = cy + R * math.sin(ang)
        draw.line((cx, cy, ex, ey), fill=BLACK, width=came - 2)
    draw.ellipse((cx - R, cy - R, cx + R, cy + R), outline=BLACK, width=came - 2)
    # Tracery: a concentric came ring splits the petals into two tiers, and
    # twelve clear-glass foil roundels (one per outer petal) keep the
    # medallion from reading as a flat pie chart.
    ring_r = R * 0.60
    draw.ellipse((cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r), outline=BLACK, width=came - 2)
    foil_band = R * 0.80
    foil_r = max(3, round(R * 0.10))
    for k in range(petals):
        ang = math.radians((k + 0.5) * 360 / petals)
        fx = cx + foil_band * math.cos(ang)
        fy = cy + foil_band * math.sin(ang)
        draw.ellipse((fx - foil_r - 1, fy - foil_r - 1, fx + foil_r + 1, fy + foil_r + 1), fill=BLACK)
        draw.ellipse((fx - foil_r, fy - foil_r, fx + foil_r, fy + foil_r), fill=WHITE)
    # Central hub carrying the numeral, knocked out clear.
    hub = max(10, round(R * 0.38))
    draw.ellipse((cx - hub - 2, cy - hub - 2, cx + hub + 2, cy + hub + 2), fill=BLACK)
    draw.ellipse((cx - hub, cy - hub, cx + hub, cy + hub), fill=WHITE)
    numeral = _TAROT_ROMAN_NUMERALS.get(hour_int, "—")
    # Shrink from 30pt until the numeral fits the hub — wide numerals
    # ("VIII", "XII") overflow it at a fixed size. ~3px margin off the came.
    fit = hub - 3
    font_candidates = theme_font_candidates("vitrail", "ornament")
    font = load_font(font_candidates, size=30)
    for size in range(30, 11, -2):
        font = load_font(font_candidates, size=size)
        left, top, right, bottom = draw.textbbox((0, 0), numeral, font=font)
        if (right - left) <= fit * 2 and (bottom - top) <= fit * 2:
            break
    draw.text((cx, cy), numeral, font=font, fill=BLACK, anchor="mm")


def _vitrail_cartouche_top_points(x0: int, y0: int, x1: int, rise: int) -> list[tuple[int, int]]:
    """Polyline tracing the cartouche's pointed-arch top from the left top
    corner (x0, y0) up to the central apex (xc, y0 − rise) and down to the
    right top corner (x1, y0).

    The rise must stay shallow (the rose window sits just above), and a
    straight gable that shallow reads flat; easing each half by ``u ** p``
    (p > 1) concentrates the rise into a sharp central spire."""
    xc = (x0 + x1) / 2.0
    half = xc - x0
    p = 1.8
    n = 24
    pts: list[tuple[float, float]] = []
    for i in range(n + 1):                       # left half: x0 → apex
        u = i / n
        pts.append((x0 + u * half, y0 - rise * (u ** p)))
    for i in range(1, n + 1):                    # right half: apex → x1
        u = i / n
        pts.append((xc + u * half, y0 - rise * ((1.0 - u) ** p)))
    return [(int(round(px)), int(round(py))) for px, py in pts]


def _vitrail_paint_quote_cartouche(
    image: Image.Image, draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], arch_rise: int,
) -> None:
    """Knock out a clear white-glass panel for the quote and frame it in came.

    A solid white wipe clears every stipple under the body so the text sits on
    legible ground. The panel has a pointed-arch top (apex at y0 − arch rise);
    its came frame follows that outline and is beveled like the panes (white
    lip top-left, black lip bottom-right). Just inside the came, adjacent red
    and blue 1px rules average to violet at panel distance, so the panel reads
    as set into coloured glass."""
    BLACK = SPECTRA6["black"]
    WHITE = SPECTRA6["white"]
    RED = SPECTRA6["red"]
    BLUE = SPECTRA6["blue"]
    x0, y0, x1, y1 = rect
    came = _VITRAIL_CAME_W
    top = _vitrail_cartouche_top_points(x0, y0, x1, arch_rise)
    # White knockout: arched top + rectangular body, as one polygon.
    draw.polygon(top + [(x1, y1), (x0, y1)], fill=WHITE)
    # Came frame along the full arched outline; curved joins keep the apex clean.
    outline = [(x0, y1)] + top + [(x1, y1), (x0, y1)]
    draw.line(outline, fill=BLACK, width=came, joint="curve")
    # Bevel: lit white lip along the lit top-left edges (left wall + left half of
    # the arch up to the apex), shadowed black lip along the bottom-right.
    apex_idx = len(top) // 2
    draw.line([(x0, y1), (x0, y0)] + top[: apex_idx + 1], fill=WHITE, width=1)
    draw.line(top[apex_idx:] + [(x1, y1), (x0, y1)], fill=BLACK, width=1)
    # Violet inner rule: concentric red then blue 1px outlines just inside the came.
    for inset, ink in ((3, RED), (4, BLUE)):
        itop = _vitrail_cartouche_top_points(x0 + inset, y0 + inset, x1 - inset, max(0, arch_rise - inset))
        draw.line(itop + [(x1 - inset, y1 - inset), (x0 + inset, y1 - inset), (x0 + inset, y0 + inset)],
                  fill=ink, width=1, joint="curve")


def _vitrail_paint_quote_body(
    image: Image.Image, draw: ImageDraw.ImageDraw,
    quote_row: dict, rect: tuple[int, int, int, int],
) -> None:
    """Quote body fitted into the cartouche, matched phrase in violet glass.

    Mirrors _tarot_paint_body: centred block, per-line horizontal centring,
    regular chunks in solid black, the matched time phrase stippled in R+B
    purple (the canonical violet-glass tone) via draw_text_dithered."""
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    BLUE = SPECTRA6["blue"]
    x0, y0, x1, y1 = rect
    pad = 14
    x0 += pad
    y0 += pad
    width = (x1 - pad) - x0
    height = (y1 - pad) - y0
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    matched = quote_row.get("matched_text") or ""
    quote_font, quote_font_bold, wrapped_quote, line_height, _ = fit_quote(
        draw, display_quote, matched, width, height,
        font_max=30, font_min=15, line_height_mult=1.22, theme="vitrail",
    )
    quote_block_height = len(wrapped_quote) * line_height
    block_top = y0 + max(0, (height - quote_block_height) // 2)
    body_ascent = _font_ascent(quote_font)
    y = block_top
    for line in wrapped_quote:
        start = 0
        while start < len(line) and line[start][0].strip() == "":
            start += 1
        end = len(line)
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        drawable = line[start:end]
        line_width: float = 0
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            bbox = draw.textbbox((0, 0), chunk, font=font)
            line_width += bbox[2] - bbox[0]
        x: float = x0 + max(0, (width - line_width) // 2)
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            chunk_y = y + (body_ascent - _font_ascent(font))
            if is_bold:
                draw_text_dithered(
                    image, (x, chunk_y), chunk, font=font,
                    dark=RED, light=BLUE, light_density=0.5,
                )
            else:
                draw.text((x, chunk_y), chunk, font=font, fill=BLACK)
            bbox = draw.textbbox((0, 0), chunk, font=font)
            x += bbox[2] - bbox[0]
        y += line_height


def _vitrail_paint_attribution(
    image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict, cx: int, y_top: int,
) -> None:
    """Author · title in the Liberation Serif body face, solid black, centred.

    Not the Uncial Antiqua ornament face: its open letterforms shatter at
    byline sizes after palette snapping."""
    BLACK = SPECTRA6["black"]
    font = load_font(theme_font_candidates("vitrail", "quote_regular"), size=15)
    max_w = 460
    fitted = _fit_dotted_byline(draw, quote_row, font, max_w)
    if fitted is None:
        return
    text, bbox = fitted
    w = bbox[2] - bbox[0]
    draw.text((cx - w // 2 - bbox[0], y_top - bbox[1]), text, font=font, fill=BLACK)


def render_vitrail_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Gothic stained-glass cathedral window.

    A tall lancet window whose black lead-came tracery divides the canvas into
    jewel-toned glass panes spanning the full synthesised Spectra-6 palette, a
    rose-window medallion carrying the Roman-numeral hour, and the literary
    quote glowing in a clear white-glass central cartouche (matched time phrase
    in violet glass). The matched phrase and the rose-window numeral carry the
    time; HH:MM digits are never shown.
    """
    image = Image.new("RGB", (width, height), color=SPECTRA6["black"])
    draw = ImageDraw.Draw(image)
    field = (_VITRAIL_SURROUND, _VITRAIL_SURROUND, width - _VITRAIL_SURROUND, height - _VITRAIL_SURROUND)
    # Scale the 800×480 reference geometry to the canvas so the frame composes
    # at any size; at native size it reproduces the constants exactly.
    sx, sy = width / 800.0, height / 480.0
    rose_cx = width // 2
    rose_cy = round(_VITRAIL_ROSE_CY * sy)
    rose_r = round(_VITRAIL_ROSE_R * sy)
    came = _VITRAIL_CAME_W
    spring_y = round(_VITRAIL_ARCH_SPRING_Y * sy)
    cx0, cy0, cx1, cy1 = _VITRAIL_CARTOUCHE
    cart = (round(cx0 * sx), round(cy0 * sy), round(cx1 * sx), round(cy1 * sy))
    arch_rise = round(_VITRAIL_CARTOUCHE_ARCH * sy)
    # Paint order: fill glass shapes → lead came along every seam → arch
    # spandrels (black stone over the top corners) → rose (on top of the top
    # shapes) → cartouche white knockout (erases any came/glass crossing it) →
    # cartouche frame + quote body + attribution.
    panes = _vitrail_build_panes(field, (rose_cx, rose_cy, rose_r))
    _vitrail_paint_glass_panes(image, panes)
    _vitrail_paint_shimmer(image, field)
    _vitrail_paint_lead_came(draw, panes, field)
    _vitrail_paint_arch_spandrels(image, draw, field, spring_y)
    hour_int = _clock_hour12(time_str)
    _vitrail_paint_rose_window(image, draw, hour_int, rose_cx, rose_cy, rose_r, came)
    # Re-apply the same sheen to the rose glass (painted after the field-wide
    # pass) so it stays continuous with the panes; clipped to the disc.
    _vitrail_paint_shimmer(
        image, field,
        region=(rose_cx - rose_r, rose_cy - rose_r, rose_cx + rose_r, rose_cy + rose_r),
        clip=(rose_cx, rose_cy, rose_r),
    )
    _vitrail_paint_quote_cartouche(image, draw, cart, arch_rise)
    _vitrail_paint_quote_body(image, draw, quote_row, (cart[0], cart[1], cart[2], cart[3] - round(24 * sy)))
    _vitrail_paint_attribution(image, draw, quote_row, (cart[0] + cart[2]) // 2, cart[3] - round(20 * sy))
    return snap_image_to_palette(image, SPECTRA6_PALETTE)


SPEC = FrameSpec(themes=("vitrail",), render=render_vitrail_frame)
