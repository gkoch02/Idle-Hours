"""The ``vinyl`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw

from idle_hours.buckets import DEFAULT_BUCKET_MINUTES, bucket_for_time

from .. import clock
from .._paths import (
    ANTONIO_VARIABLE,
    CARDO_ITALIC,
    EBGARAMOND_BOLD,
    META_FONT_BOLD_CANDIDATES,
    META_FONT_CANDIDATES,
    SPACEMONO_BOLD,
)
from ..fonts import _font_ascent, load_font, normalize_dashes, theme_font_candidates
from ..furniture import _clock_hh_mm, _fit_dotted_byline
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, pixel_access, snap_image_to_palette
from ..primitives import position_noise
from ..spec import FrameSpec
from ..text import draw_text_dithered
from ._shared import _astrarium_paint_cream_wash

# ─── vinyl (turntable + record label) ────────────────────────────────────────

# Disc geometry. The platter must not fill the plinth: the disc is kept
# small enough that the tonearm pivot sits far enough from the spindle for
# a sane stylus position.
_VINYL_DISK_CX = 178
_VINYL_DISK_CY = 246
_VINYL_DISK_R = 168
_VINYL_LABEL_R = 76


def _vinyl_paint_wear_speckle(image: Image.Image, seed: int) -> None:
    """Sparse 1-in-32 black speckle on the sleeve, daily-seeded for variation.

    Only flips white or yellow (cream-wash) pixels, so the disc and other
    graphics are untouched.
    """
    BLACK = SPECTRA6["black"]
    WHITE = SPECTRA6["white"]
    YELLOW = SPECTRA6["yellow"]
    rng = random.Random(seed)
    px = pixel_access(image)
    w, h = image.size
    # Only on the right half (sleeve region — x >= 400).
    for y in range(0, h, 2):
        for x in range(400, w, 2):
            if rng.random() < 1 / 32 and px[x, y] in (WHITE, YELLOW):
                px[x, y] = BLACK


# Programme-band sheen. Peak density stays low because a record is black:
# a satin hint of reflection, not a silver ring. The light jitter only
# dissolves the residual tile lattice (bakelite's ordered-plus-jitter
# recipe; hash alone at this density reads as sandpaper).
_VINYL_SHEEN_BANDS = 6
_VINYL_SHEEN_PEAK = 0.20
_VINYL_SHEEN_JITTER = 0.20


def _vinyl_paint_disk(
    image: Image.Image, draw: ImageDraw.ImageDraw, cx: int, cy: int, r_outer: int, r_label: int,
) -> None:
    """Solid black disk + densely-packed groove band + dead-wax + label + spindle.

    Three concentric pressing zones, after a real 12-inch LP:

    1. Dead wax (``r_label`` → ``r_label + 12``): left smooth black.
    2. Programme band (``r_label + 12`` → ``r_outer - 10``): a smooth radial
       **sheen**, painted per pixel — a cosine density ramp peaking on each
       reflection band, dithered on ``BAYER_8x8`` with a light
       :func:`position_noise` jitter.

       Deliberately not hairline grooves: groove pitch is unresolvable at
       viewing distance, packed 1-px rasterised rings beat into radial
       moiré, and many white rings turn the disc grey. A smooth per-pixel
       ramp has no rasterisation phase and gives the dither nothing
       periodic to alias against.
    3. Lead-in groove near the rim: a single 2-px white ring.
    """
    BLACK = SPECTRA6["black"]
    WHITE = SPECTRA6["white"]
    # Outer disk.
    draw.ellipse((cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer), fill=BLACK)

    # Programme band — a smooth radial *sheen*, painted per pixel.
    px = pixel_access(image)
    w, h = image.size
    lo, hi = r_label + 12, r_outer - 10
    span = max(1, hi - lo)
    x0, y0 = max(0, cx - r_outer), max(0, cy - r_outer)
    x1, y1 = min(w, cx + r_outer + 1), min(h, cy + r_outer + 1)
    for y in range(y0, y1):
        dy = y - cy
        for x in range(x0, x1):
            dx = x - cx
            radius = math.hypot(dx, dy)
            if not (lo <= radius <= hi):
                continue
            # Smooth cosine banding, with no hard periodic edge for the
            # dither tile to beat against.
            phase = (radius - lo) / span * _VINYL_SHEEN_BANDS * 2 * math.pi
            amp = ((math.cos(phase) + 1) / 2) ** 1.6
            rank = BAYER_8x8[y % 8][x % 8] + (position_noise(x, y) / 255 - 0.5) * 64 * _VINYL_SHEEN_JITTER
            if rank < amp * _VINYL_SHEEN_PEAK * 64:
                px[x, y] = WHITE

    # Lead-in groove — an isolated drawn ring is fine; packed ones beat.
    lead_in_r = r_outer - 4
    draw.ellipse(
        (cx - lead_in_r, cy - lead_in_r, cx + lead_in_r, cy + lead_in_r),
        outline=WHITE, width=2,
    )
    # The label fill and spindle are painted by ``_vinyl_paint_label``, after
    # the tonearm, so the label covers any part of the arm crossing it.


def _vinyl_paint_label(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    r_label: int,
    matched_text: str,
    bucket: str,
) -> None:
    """White-on-red label for a literary-audiobook LP.

    A music-LP label with the chrome reframed for the spoken-word labels
    (Caedmon, Spoken Arts, Listening Library) that pressed literary
    readings to vinyl.

    Composition top to bottom:

    * Black ring border, 2 px, inset 4 px from the label edge.
    * "SPOKEN WORD" format mark (the music LP's "STEREO").
    * The matched phrase, truncated to 18 chars, as the passage title.
    * A white hairline divider.
    * "IDLE HOURS" in Cormorant Bold 14pt.
    * "READ ALOUD" subtitle (a music LP's volume / side line).
    * Catalog number in Space Mono Bold ("IH-H11-15" etc).
    * The current year, small, at the bottom.

    Only the most iconic elements, so the label still reads at its ~76 px
    radius.
    """
    WHITE = SPECTRA6["white"]
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    # Label fill painted here, after the tonearm, so it covers the arm.
    draw.ellipse((cx - r_label, cy - r_label, cx + r_label, cy + r_label), fill=RED)
    # Outer black ring border — 2 px thick, inset 4 px from the label edge.
    ring_r = r_label - 4
    draw.ellipse((cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r), outline=BLACK, width=2)
    # SPOKEN WORD mark at the top of the label.
    format_font = load_font([(ANTONIO_VARIABLE, "Bold"), *META_FONT_BOLD_CANDIDATES], size=9)
    format_text = "· SPOKEN WORD ·"
    bbox = draw.textbbox((0, 0), format_text, font=format_font)
    w = bbox[2] - bbox[0]
    draw.text((cx - w // 2 - bbox[0], cy - 60 - bbox[1]), format_text, font=format_font, fill=WHITE)
    # Matched phrase (truncated) — the "track title".
    matched_font = load_font(theme_font_candidates("vinyl", "quote_bold"), size=11)
    snippet = (matched_text or "").strip()
    if len(snippet) > 18:
        snippet = snippet[:17] + "…"
    if snippet:
        bbox = draw.textbbox((0, 0), snippet, font=matched_font)
        w = bbox[2] - bbox[0]
        draw.text((cx - w // 2 - bbox[0], cy - 38 - bbox[1]), snippet, font=matched_font, fill=WHITE)
    # Hairline under matched phrase.
    draw.line((cx - r_label + 18, cy - 22, cx + r_label - 18, cy - 22), fill=WHITE, width=1)
    # IDLE HOURS line.
    title_font = load_font(theme_font_candidates("vinyl", "quote_bold"), size=14)
    title_text = "IDLE HOURS"
    bbox = draw.textbbox((0, 0), title_text, font=title_font)
    w = bbox[2] - bbox[0]
    draw.text((cx - w // 2 - bbox[0], cy - 18 - bbox[1]), title_text, font=title_font, fill=WHITE)
    # READ ALOUD subtitle.
    sub_font = load_font(theme_font_candidates("vinyl", "quote_regular"), size=11)
    sub_text = "READ ALOUD"
    bbox = draw.textbbox((0, 0), sub_text, font=sub_font)
    w = bbox[2] - bbox[0]
    draw.text((cx - w // 2 - bbox[0], cy + 8 - bbox[1]), sub_text, font=sub_font, fill=WHITE)
    # Catalog number (mono).
    cat_font = load_font([SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=9)
    cat_text = _vinyl_catalog_number(bucket)
    bbox = draw.textbbox((0, 0), cat_text, font=cat_font)
    w = bbox[2] - bbox[0]
    draw.text((cx - w // 2 - bbox[0], cy + 28 - bbox[1]), cat_text, font=cat_font, fill=WHITE)
    # Current year at the bottom arc of the label.
    year_font = load_font([(ANTONIO_VARIABLE, "Bold"), *META_FONT_BOLD_CANDIDATES], size=9)
    year_text = f"© {clock.now().year}"
    bbox = draw.textbbox((0, 0), year_text, font=year_font)
    w = bbox[2] - bbox[0]
    draw.text((cx - w // 2 - bbox[0], cy + 50 - bbox[1]), year_text, font=year_font, fill=WHITE)
    # Spindle hole, painted last so it sits on top of anything near centre.
    draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=WHITE)


# Tonearm mount, derived from the disc so the two cannot drift apart. The
# pivot sits 1.46x the record radius from the spindle (a real deck's 222 mm
# on a 152 mm record radius), behind and right of the platter.
_VINYL_PIVOT_DISTANCE_RATIO = 1.46
_VINYL_PIVOT_ANGLE_DEG = -40.0


def _vinyl_tonearm_pivot(cx: int, cy: int, r_outer: int) -> tuple[float, float]:
    """Where the arm's bearing sits, in panel coordinates."""
    d = r_outer * _VINYL_PIVOT_DISTANCE_RATIO
    ang = math.radians(_VINYL_PIVOT_ANGLE_DEG)
    return cx + d * math.cos(ang), cy + d * math.sin(ang)


# Tonearm geometry: 1.51x the disc radius is a 9-inch arm on a 12-inch
# record (230 mm effective length, 152 mm record radius), long enough for
# the stylus to reach outer edge to run-out within a narrow arc.
_VINYL_ARM_LENGTH_RATIO = 1.51
# Where the stylus stops at minute 59: just clear of the 76 px label, as a
# real run-out groove clears it by a few millimetres.
_VINYL_RUNOUT_RATIO = 0.55
_VINYL_COUNTERWEIGHT_OFFSET = 34


def _vinyl_paint_tonearm(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    r_outer: int,
    minute: int,
) -> None:
    """Pivoted tonearm whose stylus tracks *inward* across the hour.

    **The minute drives the stylus radius, not a rim angle.** A record
    plays outside-in, so minute 0 puts the stylus at the outer edge of the
    programme band and minute 59 near the run-out. The arm's angle falls out
    of the geometry: with the pivot a fixed distance ``d`` from the centre
    and arm length ``L``, the stylus is an intersection of the circle of
    radius ``r`` about the centre with the circle of radius ``L`` about the
    pivot (the two-circle solve below). This yields a ~23° sweep across the
    hour — visibly moving, never leaving the playing side.
    """
    BLACK = SPECTRA6["black"]
    WHITE = SPECTRA6["white"]
    RED = SPECTRA6["red"]
    pivot_x, pivot_y = _vinyl_tonearm_pivot(cx, cy, r_outer)
    arm_len = r_outer * _VINYL_ARM_LENGTH_RATIO

    # Stylus radius: outer edge of the programme band at minute 0,
    # creeping toward the run-out by minute 59.
    r_start = r_outer - 8
    r_end = r_outer * _VINYL_RUNOUT_RATIO
    frac = min(max(minute, 0), 59) / 59.0
    r_stylus = r_start + (r_end - r_start) * frac

    d = math.hypot(pivot_x - cx, pivot_y - cy)
    if d < 1:
        return
    # Two-circle intersection: |S - C| = r_stylus, |S - P| = arm_len.
    a = (r_stylus * r_stylus - arm_len * arm_len + d * d) / (2 * d)
    h_sq = r_stylus * r_stylus - a * a
    if h_sq < 0:
        # Unreachable geometry (the disc shrunk past what the pivot and
        # arm can span): draw no arm rather than a nonsense one.
        return
    h = math.sqrt(h_sq)
    ux, uy = (pivot_x - cx) / d, (pivot_y - cy) / d
    # Perpendicular; the negative sign takes the intersection on the near
    # face of the disc below the pivot, where a rear-right arm rests.
    px_, py_ = -uy, ux
    tip_x = cx + a * ux + h * px_
    tip_y = cy + a * uy + h * py_

    # Unit vector from stylus back to pivot — the arm axis.
    dx, dy = pivot_x - tip_x, pivot_y - tip_y
    axis = math.hypot(dx, dy)
    if axis < 1:
        return
    ax, ay = dx / axis, dy / axis
    perp_x, perp_y = -ay, ax

    # Counterweight sits behind the pivot, balancing the cartridge end.
    cw_x = pivot_x + ax * _VINYL_COUNTERWEIGHT_OFFSET
    cw_y = pivot_y + ay * _VINYL_COUNTERWEIGHT_OFFSET

    # Arm tube: one stroke through the pivot so it reads as rigid, cased as
    # a dark outline with a white core — a plain black tube would vanish
    # over the black disc (the ``metro`` route-line trick).
    ends = (tip_x + ax * 6, tip_y + ay * 6, cw_x, cw_y)
    draw.line(ends, fill=BLACK, width=5)
    draw.line(ends, fill=WHITE, width=2)
    # Pivot mount on the plate.
    draw.ellipse((pivot_x - 8, pivot_y - 8, pivot_x + 8, pivot_y + 8), fill=BLACK)
    draw.ellipse((pivot_x - 3, pivot_y - 3, pivot_x + 3, pivot_y + 3), fill=RED)
    # Counterweight cylinder.
    cw_r = 8
    draw.ellipse((cw_x - cw_r, cw_y - cw_r, cw_x + cw_r, cw_y + cw_r), fill=BLACK)
    draw.ellipse((cw_x - cw_r, cw_y - cw_r, cw_x + cw_r, cw_y + cw_r), outline=RED, width=1)
    # Cartridge headshell — a 4-point polygon along the arm axis.
    head_long, head_wide = 13, 8
    body_cx = tip_x + ax * (head_long * 0.45)
    body_cy = tip_y + ay * (head_long * 0.45)
    draw.polygon(
        [
            (body_cx + ax * head_long / 2 + perp_x * head_wide / 2,
             body_cy + ay * head_long / 2 + perp_y * head_wide / 2),
            (body_cx + ax * head_long / 2 - perp_x * head_wide / 2,
             body_cy + ay * head_long / 2 - perp_y * head_wide / 2),
            (body_cx - ax * head_long / 2 - perp_x * head_wide / 2,
             body_cy - ay * head_long / 2 - perp_y * head_wide / 2),
            (body_cx - ax * head_long / 2 + perp_x * head_wide / 2,
             body_cy - ay * head_long / 2 + perp_y * head_wide / 2),
        ],
        fill=BLACK,
        outline=WHITE,
    )
    # Stylus contact point.
    draw.ellipse((tip_x - 2, tip_y - 2, tip_x + 2, tip_y + 2), fill=RED)


def _vinyl_paint_33rpm_badge(
    image: Image.Image, draw: ImageDraw.ImageDraw, x_right: int, y_top: int,
) -> None:
    """Small red rect with white '33 RPM' Space Mono Bold, top-right corner.

    ASCII "33 RPM", not "33⅓": Space Mono Bold has no U+2153 and would tofu.
    """
    RED = SPECTRA6["red"]
    WHITE = SPECTRA6["white"]
    rect = (x_right - 64, y_top, x_right, y_top + 24)
    draw.rectangle(rect, fill=RED)
    font = load_font([SPACEMONO_BOLD, *META_FONT_BOLD_CANDIDATES], size=12)
    text = "33 RPM"
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    rect_cx = (rect[0] + rect[2]) // 2
    rect_cy = (rect[1] + rect[3]) // 2
    draw.text((rect_cx - w // 2 - bbox[0], rect_cy - h // 2 - bbox[1]), text, font=font, fill=WHITE)


def _vinyl_paint_track_heading(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    x_left: int,
    y_top: int,
) -> None:
    """Small red "READING" heading above the quote body.

    Spoken-word LP backs (Caedmon) introduced each selection with
    "READING" / "PASSAGE" / "EXCERPT", the music LP's "TRACK ONE".
    """
    RED = SPECTRA6["red"]
    font = load_font([(ANTONIO_VARIABLE, "Bold"), *META_FONT_BOLD_CANDIDATES], size=13)
    text = "—  READING  —"
    draw.text((x_left, y_top), text, font=font, fill=RED)


def _vinyl_paint_spec_line(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    bucket: str,
    x_left: int,
    x_right: int,
    y_top: int,
) -> None:
    """Liner-note spec strip just under the READING heading.

    Spoken-word LP backs ran a technical line under each selection heading
    — side, speed, channel, running time. Space Mono, with a hairline above
    echoing the catalog bar's rule so the two strips bracket the quote. The
    running time is synthesised from the bucket, like the catalog number,
    so a given quote always renders the same strip.
    """
    BLACK = SPECTRA6["black"]
    font = load_font([SPACEMONO_BOLD, *META_FONT_CANDIDATES], size=10)
    # Deterministic "running time" 1:00–8:59 from the bucket. Never
    # ``hash()``: it is PYTHONHASHSEED-salted and would break the byte-exact
    # golden / dedup contract.
    h = sum(ord(c) for c in bucket)
    mins = 1 + (h % 8)
    secs = (h * 7) % 60
    # ASCII "33 RPM": Space Mono has no U+2153 (⅓) glyph.
    left_text = "SIDE ONE  ·  33 RPM  ·  MONO"
    right_text = f"RUNNING TIME {mins}:{secs:02d}"
    rule_y = y_top - 4
    draw.line((x_left, rule_y, x_right, rule_y), fill=BLACK, width=1)
    draw.text((x_left, y_top), left_text, font=font, fill=BLACK)
    bbox = draw.textbbox((0, 0), right_text, font=font)
    w = bbox[2] - bbox[0]
    draw.text((x_right - w - bbox[0], y_top - bbox[1]), right_text, font=font, fill=BLACK)


# Catalog-bar typography. The imprint shortens before the size steps down,
# and the size has a floor: below ~8 pt Cardo Italic shreds after palette
# snapping.
_VINYL_CATALOG_SIZE = 11
_VINYL_CATALOG_MIN_SIZE = 8
_VINYL_CATALOG_GAP = 14
_VINYL_IMPRINTS = (
    "IDLE HOURS LITERARY RECORDINGS",
    "IDLE HOURS RECORDINGS",
    "IDLE HOURS",
)


def _vinyl_paint_catalog_bar(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    bucket: str,
    x_left: int,
    x_right: int,
    y_top: int,
) -> None:
    """Bottom-of-sleeve catalog info bar: brand · catalog · year.

    Small italic Cardo — the register of an LP jacket's legal / catalog
    band. The catalog number repeats the label's, as real records do.
    """
    BLACK = SPECTRA6["black"]
    year = clock.now().year
    cat = _vinyl_catalog_number(bucket)
    right_text = f"CAT NO. {cat}  ·  © {year}"
    # The catalog number carries the information, so the brand gives way:
    # try each shorter imprint, then step the size down. The halves must
    # never overlap.
    for size in range(_VINYL_CATALOG_SIZE, _VINYL_CATALOG_MIN_SIZE - 1, -1):
        font = load_font([CARDO_ITALIC, *META_FONT_CANDIDATES], size=size)
        right_w = draw.textlength(right_text, font=font)
        for left_text in _VINYL_IMPRINTS:
            left_w = draw.textlength(left_text, font=font)
            if left_w + right_w + _VINYL_CATALOG_GAP <= x_right - x_left:
                break
        else:
            continue
        break
    # Both halves share one baseline.
    baseline = y_top + size
    draw.text((x_left, baseline), left_text, font=font, fill=BLACK, anchor="ls")
    draw.text((x_right, baseline), right_text, font=font, fill=BLACK, anchor="rs")
    # Thin rule just above the catalog text.
    rule_y = y_top - 6
    draw.line((x_left, rule_y, x_right, rule_y), fill=BLACK, width=1)


def _vinyl_paint_quote_body(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    quote_row: dict,
    rect: tuple[int, int, int, int],
) -> None:
    """Quote body on the sleeve with tangerine matched-phrase substitution."""
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    YELLOW = SPECTRA6["yellow"]
    x0, y0, x1, y1 = rect
    width = x1 - x0
    height = y1 - y0
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    matched = quote_row.get("matched_text") or ""

    quote_font, quote_font_bold, wrapped_quote, line_height, _ = fit_quote(
        draw,
        display_quote,
        matched,
        width,
        height,
        font_max=32,
        font_min=18,
        line_height_mult=1.22,
        theme="vinyl",
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
        x: float = x0
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            chunk_y = y + (body_ascent - _font_ascent(font))
            if is_bold:
                # Tangerine R+Y 5/8:3/8, same recipe astrarium uses.
                draw_text_dithered(
                    image, (x, chunk_y), chunk, font=font,
                    dark=RED, light=YELLOW, light_density=0.375,
                )
            else:
                draw.text((x, chunk_y), chunk, font=font, fill=BLACK)
            bbox = draw.textbbox((0, 0), chunk, font=font)
            x += bbox[2] - bbox[0]
        y += line_height


def _vinyl_paint_attribution(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    quote_row: dict,
    x_right: int,
    y_top: int,
) -> None:
    """Right-aligned author + ' · ' + title at the bottom of the sleeve."""
    BLACK = SPECTRA6["black"]
    font = load_font([EBGARAMOND_BOLD, *META_FONT_BOLD_CANDIDATES], size=12)
    # Truncate if too wide for the sleeve column (~360 px).
    max_w = 360
    fitted = _fit_dotted_byline(draw, quote_row, font, max_w)
    if fitted is None:
        return
    text, bbox = fitted
    w = bbox[2] - bbox[0]
    draw.text((x_right - w - bbox[0], y_top - bbox[1]), text, font=font, fill=BLACK)


def _vinyl_catalog_number(bucket: str) -> str:
    """Derive an album-style catalog number from a fuzzy bucket.

    e.g. ``"h2_half_past"`` → ``"IH-H2-30"``. Falls back to ``"IH-?"`` for
    malformed inputs so callers never raise.
    """
    if not bucket or "_" not in bucket:
        return "IH-?"
    hour_part, _, state = bucket.partition("_")
    minute = DEFAULT_BUCKET_MINUTES.get(state)
    if minute is None:
        return f"IH-{hour_part.upper()}-?"
    return f"IH-{hour_part.upper()}-{minute:02d}"


def render_vinyl_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Turntable + literary-audiobook LP back-cover (Caedmon / Spoken Arts register).

    Left half: a black LP (radius 200, centred at (200, 240)) with grooves,
    a lead-in groove, a dead-wax ring, a red label (SPOKEN WORD mark,
    matched-phrase title, brand stack, catalog number, © year) and a
    tonearm whose headshell sits at the current-minute rim position.

    Right half: cream liner-notes panel — "— READING —" heading, spec
    strip, the quote with a tangerine matched phrase, the attribution,
    a catalog bar, and the 33 RPM badge top-right. See docs/themes.md
    (``vinyl``).
    """
    # Composed at the canonical 800x480 and NEAREST-downsampled for other
    # sizes (``metro`` convention): the disc, label and tonearm pivot are
    # absolute panel coordinates.
    image = Image.new("RGB", (800, 480), color=SPECTRA6["white"])
    # Sleeve cream wash full-canvas — the disk will overpaint the left half.
    _astrarium_paint_cream_wash(image)
    # Daily-seeded wear marks on the sleeve (right half only).
    today = clock.now().date()
    speckle_seed = int(today.strftime("%Y%m%d"))
    _vinyl_paint_wear_speckle(image, speckle_seed)

    draw = ImageDraw.Draw(image)

    # Render order: disk body (grooves only) → tonearm → label, so the
    # label paints over the arm and the arm never cuts through its text.
    _vinyl_paint_disk(image, draw, _VINYL_DISK_CX, _VINYL_DISK_CY, _VINYL_DISK_R, _VINYL_LABEL_R)
    hour, minute = _clock_hh_mm(time_str)
    bucket = quote_row.get("fuzzy_bucket") or bucket_for_time(f"{hour:02d}:{minute:02d}")
    matched = quote_row.get("matched_text") or ""
    _vinyl_paint_tonearm(image, draw, _VINYL_DISK_CX, _VINYL_DISK_CY, _VINYL_DISK_R, minute)
    _vinyl_paint_label(image, draw, _VINYL_DISK_CX, _VINYL_DISK_CY, _VINYL_LABEL_R, matched, bucket)

    # Right-half liner-notes chrome.
    sleeve_x_left, sleeve_x_right = 420, 800 - 20
    # 33 RPM badge in the sleeve's top-right.
    _vinyl_paint_33rpm_badge(image, draw, x_right=sleeve_x_right, y_top=20)
    # TRACK ONE heading at the top of the liner-notes column.
    _vinyl_paint_track_heading(image, draw, x_left=sleeve_x_left, y_top=24)
    # Liner-note spec strip (side · speed · channel · running time) just
    # below the heading — fills the dead cream between heading and quote.
    _vinyl_paint_spec_line(image, draw, bucket, x_left=sleeve_x_left,
                           x_right=sleeve_x_right, y_top=48)
    # Quote body on the sleeve (top nudged down to clear the spec strip).
    body_rect = (sleeve_x_left, 74, sleeve_x_right, 390)
    _vinyl_paint_quote_body(image, draw, quote_row, body_rect)
    # Author + title attribution (right-aligned).
    _vinyl_paint_attribution(image, draw, quote_row, x_right=sleeve_x_right, y_top=412)
    # Bottom catalog bar — the LP back-cover small-print band.
    _vinyl_paint_catalog_bar(image, draw, bucket, x_left=sleeve_x_left,
                             x_right=sleeve_x_right, y_top=450)

    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("vinyl",), render=render_vinyl_frame)
