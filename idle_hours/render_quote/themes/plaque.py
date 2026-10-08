"""The ``plaque`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from ..fonts import load_font, theme_font_candidates
from ..furniture import _clock_hour12, fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, pixel_access, snap_image_to_palette
from ..primitives import _flow_stroke_hash, paint_relief_mask, wrap_quote_into_masks
from ..spec import FrameSpec
from ._shared import _TAROT_ROMAN_NUMERALS

# ---------------------------------------------------------------------------
# plaque — a patinated bronze memorial plaque with relief-lit lettering
# (``paint_relief_mask``). The hour is the dedication year, ``ERECTED · ANNO
# XI``; hour only. Design notes: docs/themes.md § plaque.
_PLAQUE_RIM = (12, 12, 787, 467)               # outer edge of the cast bead
_PLAQUE_RIM_WIDTH = 7
_PLAQUE_QUOTE_RECT = (84, 96, 716, 330)
_PLAQUE_BOLT_R = 9
_PLAQUE_BOLTS = ((38, 38), (762, 38), (38, 442), (762, 442))
_PLAQUE_GOLD_RED = 0.375                       # Y+R 5/8:3/8 — the documented gold
# Ground: 32 of the 64 tile cells go to green+blue, the rest to black. Every
# share is load-bearing for legibility — see _plaque_paint_patina.
_PLAQUE_PATINA_CELLS = 32.0                    # cells of 64 that are NOT black
# Green takes two thirds of the non-black cells: at an even split the
# panel's more chromatic blue wins the hue and the patina reads navy.
_PLAQUE_GREEN_BASE = 21.0                      # cells of the 32, before the swing
_PLAQUE_SWING = 8.0                            # green<->blue sine amplitude, in cells
# Letter faces, as the white share of a Y+W mix. The Y+R gold is too dark to
# carry text on any ground this panel can make (3.3:1 at best), so it stays on
# the bead and bolts; burnished brass gives the prose ~6.3:1 and the matched
# phrase ~6.6:1.
_PLAQUE_PROSE_WHITE = 0.25                     # pale burnished brass
_PLAQUE_POLISH_WHITE = 0.60                    # rubbed to bright bare metal
# Occlusion crease cut on the radius-2 halo. Measured on a *stroke*: one pixel
# outside a 3 px stem the halo is ~93 and two pixels out ~57, so 55 takes those
# two pixels; much lower (~25) starts closing small counters, and a cut near 96
# creases a glyph nowhere.
_PLAQUE_CONTACT_CUT = 55


def _plaque_ground() -> frozenset:
    """Inks exterior relief shading may overwrite: the patina's own colours."""
    return frozenset({SPECTRA6["green"], SPECTRA6["blue"], SPECTRA6["yellow"], SPECTRA6["black"]})


def _plaque_paint_patina(image: Image.Image) -> None:
    """Layer 0: verdigris over dark bronze — half black, half green/blue.

    Of each 8x8 tile, black takes a fixed half and green/blue the rest
    (~33/17 before the swing). The green/blue boundary is swung by two slow
    sine fields (corrosion pools and streaks) and the read is jittered by the
    position hash so the ordered tile cannot lattice.

    **The ground is dark because no lighter one can carry text.** On a
    mid-tone like the catalogue's forest-teal (G+B+Y 40/40/20) even pure white
    reaches only ~3.85:1. Recessed bronze genuinely darkens with grime while
    the raised letters stay burnished.

    **The swing trades hue, not luminance.** It moves only green against blue
    while black keeps its half. Don't let it spend on a bright ink (yellow):
    patches of ground then match the letters' brightness and the inscription
    vanishes. ``TestPlaqueRelief`` fences the local luminance band, since a
    whole-canvas average hides the fault.
    """
    px = pixel_access(image)
    green, blue, black = (SPECTRA6[c] for c in ("green", "blue", "black"))
    for y in range(480):
        row = BAYER_8x8[y % 8]
        for x in range(800):
            h = _flow_stroke_hash(x, y, 5)
            swing = _PLAQUE_SWING * (math.sin(x / 97.0 + y / 61.0) + math.sin(x / 41.0 - y / 149.0))
            rank = (row[x % 8] + (h - 0.5) * 3.0) % 64
            # Both cuts move as one, so the swing trades green against blue
            # while black keeps its fixed half; face contrast holds
            # 6.1-6.4:1 across the sweep.
            green_cut = min(_PLAQUE_PATINA_CELLS, max(0.0, _PLAQUE_GREEN_BASE + swing))
            if rank < green_cut:
                px[x, y] = green
            elif rank < _PLAQUE_PATINA_CELLS:
                px[x, y] = blue
            else:
                px[x, y] = black


def _plaque_paint_rim(image: Image.Image) -> None:
    """The cast border bead: a raised bronze ring under the shared light."""
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle(_PLAQUE_RIM, radius=18, outline=255, width=_PLAQUE_RIM_WIDTH)
    paint_relief_mask(image, mask, highlight=SPECTRA6["white"], shadow=SPECTRA6["black"],
                      face=SPECTRA6["yellow"], face_minor=SPECTRA6["red"],
                      face_minor_share=_PLAQUE_GOLD_RED,
                      radius=2, strength=3.2, cap=0.6, ground=_plaque_ground())


def _plaque_paint_bolts(image: Image.Image) -> None:
    """Four bolt heads pinning the tablet, each with its own specular tick."""
    draw = ImageDraw.Draw(image)
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    r = _PLAQUE_BOLT_R
    for cx, cy in _PLAQUE_BOLTS:
        mask_draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    paint_relief_mask(image, mask, highlight=SPECTRA6["white"], shadow=SPECTRA6["black"],
                      face=SPECTRA6["yellow"], face_minor=SPECTRA6["red"],
                      face_minor_share=_PLAQUE_GOLD_RED,
                      radius=2, strength=3.6, cap=0.65, ground=_plaque_ground())
    for cx, cy in _PLAQUE_BOLTS:
        draw.ellipse((cx - r + 2, cy - r + 2, cx - r + 4, cy - r + 4), fill=SPECTRA6["white"])


def _plaque_paint_quote(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The inscription: raised brass prose, polished matched phrase.

    Two masks from ``wrap_quote_into_masks``, each relief-lit once. The hot
    pass cuts deeper and its face carries more white, so the time phrase
    reads as the tablet's brightest metal under the same light.

    Both passes lay a ``contact`` crease — the occlusion line where a raised
    letter meets the plate — closing the contour on the arcs the raking light
    leaves unshaded. On the dark ground it is a modest edge-contrast gain, not
    load-bearing.
    """
    prose, hot, _ = wrap_quote_into_masks(
        draw, image.size, quote_row, _PLAQUE_QUOTE_RECT,
        theme="plaque", font_max=40, font_min=17, line_height_mult=1.42,
    )
    paint_relief_mask(image, prose, highlight=SPECTRA6["white"], shadow=SPECTRA6["black"],
                      face=SPECTRA6["yellow"], face_minor=SPECTRA6["white"],
                      face_minor_share=_PLAQUE_PROSE_WHITE,
                      radius=2, strength=3.4, cap=0.6, ground=_plaque_ground(),
                      shade_face=False,
                      contact=SPECTRA6["black"], contact_cut=_PLAQUE_CONTACT_CUT)
    paint_relief_mask(image, hot, highlight=SPECTRA6["white"], shadow=SPECTRA6["black"],
                      face=SPECTRA6["yellow"], face_minor=SPECTRA6["white"],
                      face_minor_share=_PLAQUE_POLISH_WHITE,
                      radius=2, strength=4.2, cap=0.75, ground=_plaque_ground(),
                      shade_face=False,
                      contact=SPECTRA6["black"], contact_cut=_PLAQUE_CONTACT_CUT)


def _plaque_paint_cast_line(image: Image.Image, draw: ImageDraw.ImageDraw, text: str, y: int, size: int) -> None:
    """A line of small cast text, raised and lit like the inscription above it.

    Cast rather than engraved: on the dark patina an incised black groove
    measures ~1.3:1 (invisible), and a recess with a lit lip reads as an
    outline rather than as metal. The fine print stays subordinate by size,
    in the same brass under the same light.
    """
    font = load_font(theme_font_candidates("plaque", "quote_regular"), size=size)
    while draw.textlength(text, font=font) > 560 and len(text) > 8:
        text = text[:-2].rstrip(" ,.;:") + "…"
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).text((400, y), text, font=font, fill=255, anchor="ma")
    paint_relief_mask(image, mask, highlight=SPECTRA6["white"], shadow=SPECTRA6["black"],
                      face=SPECTRA6["yellow"], face_minor=SPECTRA6["white"],
                      face_minor_share=_PLAQUE_PROSE_WHITE,
                      radius=1, strength=3.0, cap=0.55,
                      ground=_plaque_ground(), shade_face=False,
                      contact=SPECTRA6["black"], contact_cut=_PLAQUE_CONTACT_CUT)


def _plaque_paint_dedication(image: Image.Image, draw: ImageDraw.ImageDraw, hour: int) -> None:
    numeral = _TAROT_ROMAN_NUMERALS[hour]
    _plaque_paint_cast_line(image, draw, f"ERECTED · ANNO {numeral}", 412, 20)


def _plaque_paint_attribution(image: Image.Image, draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or fallback_title(quote_row) or "").strip()
    parts = " — ".join(p for p in (author, title) if p)
    if not parts:
        return
    _plaque_paint_cast_line(image, draw, parts, 376, 19)


def render_plaque_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A patinated bronze tablet with relief-lit lettering (see the section
    comment).

    Composed at 800x480 and NEAREST-downsampled otherwise (the ``metro``
    convention): the geometry is absolute, and interpolation would average
    the patina's inks into colours the panel cannot print.
    """
    image = Image.new("RGB", (800, 480), color=SPECTRA6["green"])
    _plaque_paint_patina(image)
    _plaque_paint_rim(image)
    _plaque_paint_bolts(image)
    draw = ImageDraw.Draw(image)
    _plaque_paint_quote(image, draw, quote_row)
    _plaque_paint_attribution(image, draw, quote_row)
    _plaque_paint_dedication(image, draw, _clock_hour12(time_str))
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("plaque",), render=render_plaque_frame)
