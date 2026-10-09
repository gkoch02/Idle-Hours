"""The ``bakelite`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from ..fonts import load_font, theme_font_candidates
from ..furniture import _clock_hour12, fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_4x4, BAYER_8x8, gray_pixel_access, pixel_access, snap_image_to_palette
from ..primitives import paint_neon_mask, wrap_quote_into_masks
from ..spec import FrameSpec
from ..text import draw_tracked, fit_text_to_width, tracked_width

# ---------------------------------------------------------------------------
# bakelite — an amber-phosphor CRT readout in a moulded bakelite console. The
# hour rides a setting index, ``HOUR 2/12``; hour only, so every minute of an
# hour renders byte-identically. Design notes: docs/themes.md § bakelite.
_BAKELITE_SCREEN = (46, 36, 754, 444)          # the CRT face, inset into the slab
_BAKELITE_SCREEN_RADIUS = 26
_BAKELITE_PITCH = 3                            # one lit scanline in every three
_BAKELITE_SCAN_PEAK = 1.0                      # lit-row density at the tube centre
_BAKELITE_SCAN_EDGE = 0.28                     # ... and out at its rim
_BAKELITE_BEVEL = 7                            # moulded-edge band width, both faces
_BAKELITE_RULE_TOP = 150
_BAKELITE_RULE_BOTTOM = 382
_BAKELITE_QUOTE_RECT = (88, 168, 712, 368)
_BAKELITE_MARGIN = 34                          # chrome inset from the screen edge
_BAKELITE_TRACKING = 3.6                       # letterspacing on the small labels
# Split-band fractions: the share of each lit run's lowest ranks that takes the
# minority ink. See ``_bakelite_paint_phosphor`` for why the ratio has to ride
# the density's own read rather than a second key.
_BAKELITE_HALO_YELLOW = 0.375                  # R+Y 5/8:3/8 tangerine, the halo
_BAKELITE_CORE_YELLOW = 0.625                  # Y+R 5/8:3/8 gold, the lit stroke
_BAKELITE_TUBE_GREEN = 0.25                    # R+G 3:1 warm brown, the scanlines
_BAKELITE_HOUR_WORDS = {
    "twelve": 12, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
}


def _bakelite_screen_inks() -> frozenset:
    """Inks a text bloom may overwrite: the tube's own ground, nothing else.

    Excluding white and yellow keeps a later halo off the cores an earlier pass
    already lit, and excluding the bezel's tan mix stops any bloom from bleeding
    out through the screen's rounded edge onto the moulding.
    """
    return frozenset({SPECTRA6["black"], SPECTRA6["red"], SPECTRA6["green"]})


def _bakelite_screen_mask() -> Image.Image:
    mask = Image.new("L", (800, 480), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        _BAKELITE_SCREEN, radius=_BAKELITE_SCREEN_RADIUS, fill=255
    )
    return mask


def _bakelite_grain(x: int, y: int) -> float:
    """A deterministic 0..1 value per pixel — the moulding's fine grain.

    A pure integer hash of position, so the frame re-renders byte-identically.
    """
    h = (x * 0x1F1F1F1F) ^ (y * 0x2545F491)
    h = ((h ^ (h >> 13)) * 0x27D4EB2D) & 0xFFFFFFFF
    return ((h ^ (h >> 15)) & 0xFFFF) / 65535.0


def _bakelite_paint_moulding(image: Image.Image) -> None:
    """Layer 0: the butterscotch slab the tube is set into.

    A three-way white:yellow:red partition at roughly 9:4:3, judged on the
    calibrated inks. Straight Y+W cream lands on khaki (the panel's yellow is
    a green one) and yellow-dominant snaps to flat lemon; red pulls the
    average onto warm sand, and white leading at 9/16 keeps the slab lighter
    than the maroon bevel shadow.

    The ink is chosen by a jittered ordered dither (the Bayer rank plus a
    positional hash at ~40% of a cell): ordered alone lattices and bands the
    marbling, hash alone reads as sandpaper. The marbling sines are safe only
    because of the jitter — two periodic patterns otherwise beat into a plaid.
    Both terms are deterministic, so a re-render is byte-identical.
    """
    pixels = pixel_access(image)
    yellow, white, red = SPECTRA6["yellow"], SPECTRA6["white"], SPECTRA6["red"]
    for y in range(480):
        row = BAYER_4x4[y % 4]
        for x in range(800):
            # Two incommensurate low frequencies: a single one corrugates. The
            # swing is kept to about one part in sixteen — enough to see as
            # marbling, not so much that a patch reads as its own colour.
            swirl = 0.035 * (math.sin(x * 0.021 + y * 0.013) + math.sin(x * 0.0075 - y * 0.019))
            level = (row[x % 4] + 0.5) / 16.0 + (_bakelite_grain(x, y) - 0.5) * 0.42
            pale = 0.5625 + swirl
            pixels[x, y] = white if level < pale else (yellow if level < pale + 0.25 else red)


def _bakelite_bevel_face(x: int, y: int, rect: tuple[int, int, int, int]) -> tuple[str, int]:
    """Which face of a moulded edge a band pixel sits on, and how deep into it.

    The edge the pixel has travelled furthest past wins, so corners resolve
    to the nearer face. The caller maps ``"near"`` (top / left) and ``"far"``
    (bottom / right) onto highlight or shadow for a raised or sunken feature
    (light from the upper left). Depth is measured against the straight
    edges, an approximation along a rounded corner that is invisible at 7 px.
    """
    x0, y0, x1, y1 = rect
    return max((x0 - x, "near"), (y0 - y, "near"), (x - x1, "far"), (y - y1, "far"))[::-1]


def _bakelite_paint_bevels(image: Image.Image) -> None:
    """The two moulded edges: a raised outer lip and the sunken screen recess.

    Painted per pixel from ring masks because PIL strokes a rounded rectangle
    in one colour. White is the highlight; the shadow is R+K maroon, not the
    frame's R+G brown, which sits too close to the slab's tone to read as
    dark. The ink falls in Bayer density from full at the feature's edge to
    nothing across the band, so each face reads as a curved surface rather
    than a drawn outline.
    """
    pixels = pixel_access(image)
    shadow = (SPECTRA6["red"], SPECTRA6["black"])
    white = SPECTRA6["white"]

    # The slab's own edge is square: the canvas *is* the moulding, and a
    # rounded corner would fall outside the band and paint solid wedges.
    outer = (_BAKELITE_BEVEL, _BAKELITE_BEVEL, 799 - _BAKELITE_BEVEL, 479 - _BAKELITE_BEVEL)

    screen = _bakelite_screen_mask()
    recess = Image.new("L", (800, 480), 0)
    ImageDraw.Draw(recess).rounded_rectangle(
        (_BAKELITE_SCREEN[0] - _BAKELITE_BEVEL, _BAKELITE_SCREEN[1] - _BAKELITE_BEVEL,
         _BAKELITE_SCREEN[2] + _BAKELITE_BEVEL, _BAKELITE_SCREEN[3] + _BAKELITE_BEVEL),
        radius=_BAKELITE_SCREEN_RADIUS + _BAKELITE_BEVEL, fill=255,
    )
    rc_px, sc_px = gray_pixel_access(recess), gray_pixel_access(screen)

    for y in range(480):
        row = BAYER_8x8[y % 8]
        for x in range(800):
            if x < outer[0] or y < outer[1] or x > outer[2] or y > outer[3]:
                # The raised outer lip: lit on the near faces, shadowed on the far.
                side, depth = _bakelite_bevel_face(x, y, outer)
                rect_edge = 0
            elif rc_px[x, y] >= 128 and sc_px[x, y] < 128:
                # The ring between moulding and glass. Sunken, so the polarity
                # of the outer lip inverts.
                side, depth = _bakelite_bevel_face(x, y, _BAKELITE_SCREEN)
                side = "far" if side == "near" else "near"
                rect_edge = 1
            else:
                continue
            # Depth runs outward from the feature's edge on the recess and
            # inward from the canvas edge on the lip, so the fade is anchored on
            # whichever edge the eye reads as the fold.
            travelled = depth if rect_edge else _BAKELITE_BEVEL - depth
            weight = max(0.0, 1.0 - travelled / (_BAKELITE_BEVEL + 1.0))
            if row[x % 8] < weight * 64:
                pixels[x, y] = white if side == "near" else shadow[(x + y) & 1]


def _bakelite_paint_tube(image: Image.Image, screen: Image.Image) -> None:
    """The CRT face: black glass carrying warm scanlines (``docs/themes.md`` § bakelite)."""
    pixels = pixel_access(image)
    sc_px = gray_pixel_access(screen)
    black, red, green = SPECTRA6["black"], SPECTRA6["red"], SPECTRA6["green"]
    x0, y0, x1, y1 = _BAKELITE_SCREEN
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    half_w, half_h = max(1.0, (x1 - x0) / 2.0), max(1.0, (y1 - y0) / 2.0)

    # Peak density is 1.0 so the lit rows are solid at the centre and the line
    # structure is legible; the vignette is carried by thinning them toward
    # the rim.
    #
    # Both ranges include the far bound: ``_BAKELITE_SCREEN`` is inclusive
    # (``rounded_rectangle`` fills both endpoints, and ``_bakelite_bevel_face``
    # assumes the same). A half-open range leaves a 1 px line of moulding
    # inside the CRT's right and bottom edges.
    for y in range(y0, y1 + 1):
        lit = (y - y0) % _BAKELITE_PITCH == 0
        for x in range(x0, x1 + 1):
            if sc_px[x, y] < 128:
                continue
            pixels[x, y] = black
            if not lit:
                continue
            # Radial falloff, lifted toward the upper left for the ambient
            # reflection real glass carries.
            radial = min(1.0, (((x - cx) / half_w) ** 2 + ((y - cy) / half_h) ** 2) ** 0.5)
            sheen = 0.10 * max(0.0, 1.0 - ((x - x0) / half_w + (y - y0) / half_h) / 1.4)
            # A high exponent confines the falloff to the corners; a low one
            # (1.6) greys the whole screen.
            density = _BAKELITE_SCAN_EDGE + (_BAKELITE_SCAN_PEAK - _BAKELITE_SCAN_EDGE) * (1.0 - radial ** 3.0)
            lit = (density + sheen) * 64
            rank = BAYER_8x8[y % 8][x % 8]
            if rank < lit:
                # 3:1 red:green, not sepia's 1:1: the panel's green is cool and
                # 1:1 reads grey-green; red-weighted reads as unlit-phosphor
                # brown. Green must come off the same Bayer read as the density
                # (the split band ``paint_neon_mask`` documents): a positional
                # key either hits ranks the threshold already rejected or misses
                # the target ratio.
                pixels[x, y] = green if rank < lit * _BAKELITE_TUBE_GREEN else red


def _bakelite_tracked_width(draw, text: str, font) -> float:
    return tracked_width(draw, text, font, tracking=_BAKELITE_TRACKING)


def _bakelite_draw_tracked(draw, x: float, y: int, text: str, font, fill) -> None:
    """The silkscreened legend at this theme's tracking — see ``draw_tracked``."""
    draw_tracked(draw, (x, y), text, font, fill, tracking=_BAKELITE_TRACKING)


def _bakelite_fit_text(draw, text: str, size: int, max_width: int, floor: int = 17):
    """A chrome readout shrunk to its cell, then ellipsised at the floor — see
    ``fit_text_to_width``; the cells are drawn as single kerned runs."""
    return fit_text_to_width(draw, text, theme_font_candidates("bakelite", "quote_regular"),
                             size, max_width, floor=floor)


def _bakelite_paint_phosphor(image: Image.Image, mask: Image.Image, core=None,
                             *, radius: int = 7, gamma: float = 1.5, cap: float = 0.68) -> None:
    """Bloom one glyph mask as lit amber phosphor (``docs/themes.md`` § bakelite).

    A thin wrapper over ``paint_neon_mask`` supplying this theme's inks and
    tuning; the mechanism is documented there. ``core=None`` (the prose and
    every chrome readout) strokes the glyph as a yellow-dominant amber, 5/8
    against the halo's 3/8, so a character steps gold, orange, brown — solid
    yellow would read lemon. An explicit ``core`` ink pins the core solid
    (the matched phrase's white). The ground is the tube's own inks, so a
    later call cannot dim what an earlier one lit.
    """
    paint_neon_mask(
        image, mask,
        core if core is not None else SPECTRA6["red"], SPECTRA6["red"],
        radius=radius, gamma=gamma, cap=cap, ground=_bakelite_screen_inks(), tile=BAYER_8x8,
        glow_minor=SPECTRA6["yellow"], glow_minor_share=_BAKELITE_HALO_YELLOW,
        core_minor=None if core is not None else SPECTRA6["yellow"],
        core_minor_share=_BAKELITE_CORE_YELLOW,
    )


def _bakelite_paint_rule(image: Image.Image, y: int, x0: int, x1: int) -> None:
    """A dim tangerine divider: red with 3/8 flipped to yellow on the Bayer
    tile (R+Y 5/8:3/8, red-biased so it does not read as lit). A rule's runs
    are wide enough to carry a stipple, unlike the small labels."""
    pixels = pixel_access(image)
    red, yellow = SPECTRA6["red"], SPECTRA6["yellow"]
    for x in range(max(0, x0), min(image.size[0], x1)):
        pixels[x, y] = yellow if BAYER_4x4[y % 4][x % 4] < 6 else red


def _bakelite_paint_chrome(image: Image.Image, draw: ImageDraw.ImageDraw,
                           quote_row: dict, time_str: str) -> None:
    """Labels, rules and readouts — the instrument furniture around the quote.

    Labels are flat solid yellow and rules a dim tangerine stipple; every
    value is bloomed, so the legend reads as silkscreened behind the emissive
    readout. All values accumulate into one mask and bloom in a single pass.
    """
    label_ink = SPECTRA6["yellow"]
    x0, _, x1, _ = _BAKELITE_SCREEN
    left = x0 + _BAKELITE_MARGIN
    right = x1 - _BAKELITE_MARGIN
    label_font = load_font(theme_font_candidates("bakelite", "ornament"), size=11)
    glow = Image.new("L", image.size, 0)
    glow_draw = ImageDraw.Draw(glow)

    for rule_y in (_BAKELITE_RULE_TOP, _BAKELITE_RULE_BOTTOM):
        _bakelite_paint_rule(image, rule_y, left, right)

    # Top left: the hour as a discrete setting index out of twelve.
    _bakelite_draw_tracked(draw, left, 66, "HOUR", label_font, label_ink)
    hour_font = load_font(theme_font_candidates("bakelite", "quote_regular"), size=62)
    scale_font = load_font(theme_font_candidates("bakelite", "quote_regular"), size=24)
    hour_text = str(_clock_hour12(time_str))
    glow_draw.text((left, 84), hour_text, font=hour_font, fill=255)
    hour_w = draw.textlength(hour_text, font=hour_font)
    glow_draw.text((left + hour_w + 10, 122), f"/{len(_BAKELITE_HOUR_WORDS)}",
                   font=scale_font, fill=255)

    # Top right: the book; bottom left: its author. A missing value prints "—"
    # in its labelled cell, as an instrument shows a sensor with no data,
    # rather than dropping the cell (bare corpus rows are common).
    title = (quote_row.get("title") or fallback_title(quote_row) or "").strip()
    label_w = _bakelite_tracked_width(draw, "NOW READING", label_font)
    _bakelite_draw_tracked(draw, right - label_w, 66, "NOW READING", label_font, label_ink)
    title_font, title_text = _bakelite_fit_text(draw, title or "—", 28, 330)
    glow_draw.text((right, 96), title_text, font=title_font, fill=255, anchor="ra")

    author = (quote_row.get("author") or "").strip()
    _bakelite_draw_tracked(draw, left, 396, "AUTHOR", label_font, label_ink)
    author_font, author_text = _bakelite_fit_text(draw, author or "—", 24, 400, floor=16)
    glow_draw.text((left, 410), author_text, font=author_font, fill=255, anchor="la")

    # Right: an unlit maker's mark, silkscreened on the bezel side of the glass.
    mark_w = _bakelite_tracked_width(draw, "IDLE HOURS", label_font)
    _bakelite_draw_tracked(draw, right - mark_w, 416, "IDLE HOURS", label_font, label_ink)

    _bakelite_paint_phosphor(image, glow)


def _bakelite_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The quote as lit phosphor: prose amber, matched phrase over-driven.

    Two masks from ``wrap_quote_into_masks`` so each tier blooms exactly once.
    The hot pass runs last so its wider halo reads as nearer;
    ``_bakelite_paint_phosphor``'s ground keeps it off the prose's already-lit
    halo and cores.
    """
    prose, hot, _ = wrap_quote_into_masks(
        draw, image.size, quote_row, _BAKELITE_QUOTE_RECT,
        theme="bakelite", line_height_mult=1.46,
    )
    _bakelite_paint_phosphor(image, prose)
    _bakelite_paint_phosphor(image, hot, SPECTRA6["white"], radius=11, gamma=1.3, cap=0.78)


def render_bakelite_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """An amber-phosphor CRT in a bakelite console (``docs/themes.md`` § bakelite).

    Every element is an absolute panel coordinate, so the frame is composed at
    800x480 and NEAREST-downsampled otherwise (the ``metro`` convention);
    NEAREST because the frame is per-pixel stipple.
    """
    image = Image.new("RGB", (800, 480), color=SPECTRA6["white"])
    _bakelite_paint_moulding(image)
    _bakelite_paint_bevels(image)
    screen = _bakelite_screen_mask()
    _bakelite_paint_tube(image, screen)
    draw = ImageDraw.Draw(image)
    _bakelite_paint_chrome(image, draw, quote_row, time_str)
    _bakelite_paint_quote(image, draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("bakelite",), render=render_bakelite_frame)
