"""The ``tarot`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

from .._paths import BASE_DIR
from ..fonts import _font_ascent, load_font, normalize_dashes, theme_font_candidates
from ..furniture import _clock_hour12, _fit_dotted_byline
from ..layout import fit_quote, strip_underscore_emphasis
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_4x4, snap_image_to_palette
from ..primitives import _white_noise
from ..spec import FrameSpec
from ..text import draw_text_dithered
from ._shared import _TAROT_ROMAN_NUMERALS

# Separated Tarot de Marseille trumps (Jean Dodal, Lyon, 1701-1715), one
# 220x290 tile per hour on a 3x4 sheet (scripts/ingest_tarot_plates.py). Unlike
# the plates above this is NOT dithered at render time: a woodcut is line and
# flat colour, so the ingest separates it to white/black/red once. Absent, the
# polygon painters still draw every hour.
TAROT_PLATES = BASE_DIR / "assets" / "tarot_plates.png"
_TAROT_PLATE_COLS, _TAROT_PLATE_ROWS = 3, 4
_TAROT_PLATE_CACHE: dict = {}


# ─── tarot (major-arcana card) ───────────────────────────────────────────────

# Vellum ground densities: mostly cream, with sparse foxing.
_TAROT_CREAM_DENSITY = 0.12
_TAROT_FOXING_DENSITY = 0.035
# Independent streams for the two layers: sampling one stream twice would
# correlate them (as ``cardcatalog``'s shared-period lattices cancelled).
_TAROT_CREAM_SEED = 0x7A6017
_TAROT_FOXING_SEED = 0x7A6018


def _tarot_paint_vellum(image: Image.Image) -> None:
    """Sparse R+G sepia foxing over a warm Y+W cream ground.

    1. Cream Y+W base at ``_TAROT_CREAM_DENSITY``.
    2. Sparse R+G foxing at ``_TAROT_FOXING_DENSITY``, split red/green by
       the low bit of the draw, so adjacent dots blend to rust-brown sepia.

    Foxing is pasted first and cream over it, so a pixel both layers claim
    comes out cream. Paints the whole canvas unconditionally, so it must be
    the first thing laid on the frame.
    """
    width, height = image.size
    cream_cut = round(_TAROT_CREAM_DENSITY * 255)
    fox_cut = round(_TAROT_FOXING_DENSITY * 255)
    foxing = _white_noise(width, height, _TAROT_FOXING_SEED)
    image.paste(SPECTRA6["red"], (0, 0), foxing.point(lambda v: 255 if v < fox_cut and v & 1 else 0))
    image.paste(SPECTRA6["green"], (0, 0), foxing.point(lambda v: 255 if v < fox_cut and not v & 1 else 0))
    cream = _white_noise(width, height, _TAROT_CREAM_SEED)
    image.paste(SPECTRA6["yellow"], (0, 0), cream.point(lambda v: 255 if v < cream_cut else 0))


# The trump's name, carried along the card's foot (not the time phrase,
# which the reading beside it already states).
#
# TWO tables because the two emblem sources number the deck differently and
# the name must match the figure drawn: the Dodal plates (Marseille) number
# Justice VIII and La Force XI and stop at Le Pendu; the polygon painters
# follow Waite, which swaps those two, and draw the World at XII. Names are
# in English to match the reading; the ingest crops the plate's own printed
# title band.
_TAROT_TRUMP_NAMES = {
    1: "The Magician",
    2: "The High Priestess",
    3: "The Empress",
    4: "The Emperor",
    5: "The Hierophant",
    6: "The Lovers",
    7: "The Chariot",
    8: "Justice",
    9: "The Hermit",
    10: "The Wheel of Fortune",
    11: "Strength",
    12: "The Hanged Man",
}
# Where the polygon painters disagree with the plates (see above).
_TAROT_PAINTER_TRUMP_NAMES = {
    **_TAROT_TRUMP_NAMES,
    8: "Strength",
    11: "Justice",
    12: "The World",
}


# Card and reading-column geometry: a portrait card (a real tarot card's
# ratio is 0.58) laid on the cloth at the left, the interpretation written
# beside it — the left-object / right-text composition of ``vinyl`` and
# ``astrarium``. The emblem gets a tall panel, the quote a full column, and
# the vellum shows on every side of the card.
_TAROT_CARD_RECT = (34, 24, 294, 456)  # 260 x 432 — ratio 0.602
_TAROT_CARD_SHADOW = 4
_TAROT_READING_RECT = (324, 54, 768, 426)


def _tarot_paint_doubled_border(
    image: Image.Image, draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int],
) -> None:
    """Outer 3-px red rule + 2-px gap + inner 1-px black rule."""
    RED = SPECTRA6["red"]
    BLACK = SPECTRA6["black"]
    x0, y0, x1, y1 = rect
    # Outer red rule (3 px thick).
    for offset in range(3):
        draw.rectangle((x0 + offset, y0 + offset, x1 - offset, y1 - offset), outline=RED)
    # Inner black rule, 5 px inset (3 px outer + 2 px gap).
    draw.rectangle((x0 + 5, y0 + 5, x1 - 5, y1 - 5), outline=BLACK)


def _tarot_paint_corner_pips(
    draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int],
) -> None:
    """Small rubricated lozenges in the card's four inner corners.
    A red lozenge keeps the corners from reading as empty. Not the hour as
    corner indices: rotated Roman numerals misread (``XI`` becomes ``IX``),
    and Marseille / Rider-Waite trumps carry no indices — the numeral sits
    at the head and the name at the foot.
    """
    RED = SPECTRA6["red"]
    x0, y0, x1, y1 = rect
    inset = 17
    r = 4
    for px_x in (x0 + inset, x1 - inset):
        for px_y in (y0 + inset, y1 - inset):
            draw.polygon(
                [(px_x, px_y - r), (px_x + r, px_y), (px_x, px_y + r), (px_x - r, px_y)],
                fill=RED,
            )


def _tarot_paint_pentagram(
    draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple,
) -> None:
    """Single five-point star as a 10-vertex polygon (alternating r_out/r_in)."""
    points: list[tuple[float, float]] = []
    for i in range(10):
        # Start at the top point (270°), alternate outer/inner radius.
        angle = -math.pi / 2 + i * math.pi / 5
        radius = r if i % 2 == 0 else r * 0.4
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    draw.polygon(points, fill=color)


def _tarot_paint_roman_numeral(
    image: Image.Image, draw: ImageDraw.ImageDraw, hour_int: int, cx: int, y_top: int,
) -> None:
    """Roman numeral hour in Cinzel Decorative Black 36, solid black."""
    BLACK = SPECTRA6["black"]
    font = load_font(theme_font_candidates("tarot", "ornament"), size=36)
    numeral = _TAROT_ROMAN_NUMERALS.get(hour_int, "—")
    bbox = draw.textbbox((0, 0), numeral, font=font)
    w = bbox[2] - bbox[0]
    draw.text((cx - w // 2 - bbox[0], y_top - bbox[1]), numeral, font=font, fill=BLACK)


# The name band's size is fitted to the card: the names span "Justice" to
# "The Wheel of Fortune" (~300 px at 22pt on a 260 px card). A real trump
# likewise sets a long title smaller.
_TAROT_NAME_SIZE_MAX = 22
_TAROT_NAME_SIZE_MIN = 12
# Inset from the card's outer edge. The inner black rule sits at 5 px;
# this leaves a further 7 px of breathing room either side.
_TAROT_NAME_INSET = 12


def _tarot_paint_card_name(
    image: Image.Image, draw: ImageDraw.ImageDraw, name: str, rect: tuple[int, int, int, int], y_top: int,
) -> None:
    """The trump's name in Tyrian purple, Cinzel Decorative Bold, along the foot.

    Stepped down from ``_TAROT_NAME_SIZE_MAX`` until it fits the card's inner
    width. Below the floor the name is drawn anyway rather than truncated:
    every committed name fits well above it, so a spill means an unmeasured
    new entry, which is a louder signal than a silent cut.
    """
    RED = SPECTRA6["red"]
    BLUE = SPECTRA6["blue"]
    text = (name or "").upper().strip()
    if not text:
        return
    x0, _, x1, _ = rect
    cx = (x0 + x1) // 2
    budget = (x1 - x0) - 2 * _TAROT_NAME_INSET
    for size in range(_TAROT_NAME_SIZE_MAX, _TAROT_NAME_SIZE_MIN - 1, -1):
        font = load_font(theme_font_candidates("tarot", "quote_bold"), size=size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= budget:
            break
    w = bbox[2] - bbox[0]
    # Re-anchor so left edge of the bbox lands at the intended start.
    draw_text_dithered(
        image,
        (cx - w // 2 - bbox[0], y_top - bbox[1]),
        text,
        font=font,
        dark=RED,
        light=BLUE,
        light_density=0.5,
    )


# The emblems that read on the panel all resolve into a *figure* — a
# trapezoid robe under a head, with the trump's attribute held beside it;
# attributes with no figure give the eye nothing to assemble them onto. Most
# emblems are therefore drawn on the shared ``_tarot_robed_figure`` skeleton.
#
# Native coordinates stay inside ±70 horizontally and ±88 vertically: the
# illustration panel is 216 x 274 and _TAROT_EMBLEM_SCALE enlarges by 1.5,
# so anything beyond that is clipped at the keyline.


def _tarot_face(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    r: int,
    *,
    hair: str = "none",
    gaze: int = 0,
) -> None:
    """Brows, eyes, nose and mouth inside a head circle.

    Two eyes and a mouth turn a circle over a trapezoid into a person, so
    the trump's attribute reads as *held*. Kept to five strokes because the
    head is only ~30 px across: brows as well as eyes, since a lone dot
    reads as a blemish. ``gaze`` shifts both pupils sideways so the figure
    can look at its attribute. ``hair`` is a coarse silhouette cue so the
    twelve heads aren't identical.
    """
    BLACK = SPECTRA6["black"]
    eye_dx = max(2, round(r * 0.36))
    eye_r = max(1, r // 7)
    eye_y = cy - max(1, r // 8)
    if hair == "long":
        # Two narrow falls either side of the face, drawn before the
        # features. Strokes, not filled polygons, which read as a helmet.
        for side in (-1, 1):
            draw.line(
                [
                    (cx + side * (r - 2), cy - r // 2),
                    (cx + side * (r + 2), cy + r // 2),
                    (cx + side * (r - 1), cy + r + 4),
                ],
                fill=BLACK, width=3, joint="curve",
            )
    if hair in ("long", "veil", "short"):
        # A shallow cap across the brow. The 215-325 arc leaves a forehead;
        # a wider chord (190-350) fills the top half solid — a helmet.
        draw.chord((cx - r, cy - r, cx + r, cy + r), 215, 325, fill=BLACK)
    for side in (-1, 1):
        ex = cx + side * eye_dx
        draw.line((ex - eye_r - 1, eye_y - eye_r - 2, ex + eye_r + 1, eye_y - eye_r - 2), fill=BLACK, width=1)
        draw.ellipse(
            (ex - eye_r + gaze, eye_y - eye_r, ex + eye_r + gaze, eye_y + eye_r),
            fill=BLACK,
        )
    draw.line((cx, eye_y + eye_r, cx, cy + r // 3), fill=BLACK, width=1)
    draw.line((cx - r // 3, cy + r // 2, cx + r // 3, cy + r // 2), fill=BLACK, width=1)
    if hair == "beard":
        # Outline plus two interior strokes: a solid wedge would swallow
        # the mouth.
        draw.polygon(
            [
                (cx - r + 3, cy + r // 2),
                (cx + r - 3, cy + r // 2),
                (cx + r // 3, cy + r + 8),
                (cx - r // 3, cy + r + 8),
            ],
            outline=BLACK, width=2,
        )
        for side in (-1, 1):
            draw.line(
                (cx + side * r // 3, cy + r // 2 + 2, cx + side * r // 5, cy + r + 5),
                fill=BLACK, width=1,
            )


def _tarot_drapery(
    draw: ImageDraw.ImageDraw,
    cx: int,
    shoulder_y: int,
    hem_y: int,
    half_top: int,
    half_bot: int,
    folds: int = 4,
) -> None:
    """Fold lines down the inside of a robe, at one third the outline weight.

    The folds are hairlines against the outline's 3 px, so the eye reads a
    hierarchy — contour, then interior detail — which separates a drawing
    from clip art. Each fold fans from near the neck to its own place on
    the hem, since parallel verticals read as stripes.
    """
    BLACK = SPECTRA6["black"]
    # Fixed offsets rather than an RNG (the frame must stay byte-
    # deterministic): evenly spaced folds read as accordion pleats.
    jitter = (0.0, 0.13, -0.09, 0.06, -0.15)
    for i in range(1, folds + 1):
        t = i / (folds + 1) + jitter[i % len(jitter)] * 0.5
        x_top = cx + round((t - 0.5) * 2 * half_top * 0.55)
        x_bot = cx + round((t - 0.5) * 2 * half_bot * 0.88)
        mid_y = shoulder_y + (hem_y - shoulder_y) * (0.5 + jitter[i % len(jitter)])
        mid_x = x_top + (x_bot - x_top) * 0.45
        draw.line(
            [(x_top, shoulder_y + 4), (mid_x, mid_y), (x_bot, hem_y - 2)],
            fill=BLACK, width=1, joint="curve",
        )


def _tarot_hand(draw: ImageDraw.ImageDraw, x: float, y: float, r: int = 4) -> None:
    """A small filled disc terminating an arm.

    Crude on purpose — at this scale a modelled hand is ambiguous pixels.
    The arm must *end* in something so the attribute reads as gripped.
    """
    draw.ellipse((x - r, y - r, x + r, y + r), fill=SPECTRA6["black"])


def _tarot_arm(
    draw: ImageDraw.ImageDraw,
    x0: float, y0: float, x1: float, y1: float,
    *, elbow: float = 0.35, hand: bool = True,
) -> tuple[float, float]:
    """A two-segment arm from shoulder to hand. Returns the hand's centre.

    One bend reads as a limb where a straight line reads as a stick.
    ``elbow`` displaces the joint perpendicular to the shoulder-to-hand
    line, so the bend follows the reach.
    """
    BLACK = SPECTRA6["black"]
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    span = math.hypot(dx, dy) or 1
    ex, ey = mx - dy / span * span * elbow * 0.35, my + dx / span * span * elbow * 0.35
    draw.line([(x0, y0), (ex, ey), (x1, y1)], fill=BLACK, width=3, joint="curve")
    if hand:
        _tarot_hand(draw, x1, y1)
    return x1, y1


def _tarot_robed_figure(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    top: int,
    bottom: int,
    half_w: int,
    *,
    hair: str = "none",
    gaze: int = 0,
    folds: int = 4,
) -> tuple[int, int]:
    """Head over a trapezoid robe, with a face and drapery. Returns (cx, cy) of the head.

    ``top`` is the crown of the head and ``bottom`` the hem, both relative
    to the emblem centre; the head is sized from the gap so a short figure
    is not all head. Shared by most emblems so the set reads as one hand.
    """
    BLACK = SPECTRA6["black"]
    head_r = max(9, (bottom - top) // 7)
    head_cy = cy + top + head_r
    draw.ellipse(
        (cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r),
        outline=BLACK, width=3,
    )
    _tarot_face(draw, cx, head_cy, head_r, hair=hair, gaze=gaze)
    shoulder = head_cy + head_r + 4
    half_top = head_r + 6
    draw.polygon(
        [
            (cx - half_top, shoulder),
            (cx + half_top, shoulder),
            (cx + half_w, cy + bottom),
            (cx - half_w, cy + bottom),
        ],
        outline=BLACK, width=3,
    )
    _tarot_drapery(draw, cx, shoulder, cy + bottom, half_top, half_w, folds=folds)
    return cx, head_cy


def _tarot_crown(draw: ImageDraw.ImageDraw, cx: int, base_y: int, half_w: int) -> None:
    """Three-spike crown sitting on a band — the head's, not free-floating."""
    BLACK = SPECTRA6["black"]
    draw.rectangle((cx - half_w, base_y - 5, cx + half_w, base_y), fill=BLACK)
    step = half_w
    for tip_x in (cx - step, cx, cx + step):
        draw.polygon(
            [(tip_x - 5, base_y - 5), (tip_x, base_y - 17), (tip_x + 5, base_y - 5)],
            fill=BLACK,
        )


def _tarot_emblem_magician(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """Magician (I): one arm raised to the wand, one pointing down.

    "As above, so below" is the gesture of this trump, and it needs two
    arms and a body; the lemniscate and the four tools annotate it.
    """
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    _, head_cy = _tarot_robed_figure(draw, cx, cy, top=-46, bottom=44, half_w=34)
    # Lemniscate hovering above the head.
    draw.arc((cx - 30, cy - 76, cx - 2, cy - 58), 0, 360, fill=BLACK, width=3)
    draw.arc((cx + 2, cy - 76, cx + 30, cy - 58), 0, 360, fill=BLACK, width=3)
    # Raised arm to the wand held aloft on the right.
    draw.line((cx + 12, cy - 12, cx + 44, cy - 34), fill=BLACK, width=3)
    draw.line((cx + 44, cy - 34, cx + 52, cy - 84), fill=BLACK, width=4)
    draw.ellipse((cx + 44, cy - 94, cx + 60, cy - 78), fill=RED)
    # Lowered arm pointing at the earth on the left.
    draw.line((cx - 12, cy - 12, cx - 44, cy + 16), fill=BLACK, width=3)
    draw.line((cx - 44, cy + 16, cx - 52, cy + 34), fill=BLACK, width=3)
    # Altar of the four suit tools across the foot.
    altar_y = cy + 62
    draw.rectangle((cx - 62, altar_y, cx + 62, altar_y + 6), fill=BLACK)
    sx = cx - 46  # cup
    draw.arc((sx - 10, altar_y - 20, sx + 10, altar_y), 0, 180, fill=RED, width=3)
    draw.line((sx - 10, altar_y - 10, sx - 10, altar_y - 20), fill=RED, width=3)
    draw.line((sx + 10, altar_y - 10, sx + 10, altar_y - 20), fill=RED, width=3)
    sx = cx - 16  # wand
    draw.line((sx, altar_y - 22, sx, altar_y - 2), fill=BLACK, width=3)
    draw.ellipse((sx - 5, altar_y - 28, sx + 5, altar_y - 18), fill=RED)
    sx = cx + 16  # sword
    draw.line((sx, altar_y - 24, sx, altar_y - 2), fill=BLACK, width=3)
    draw.line((sx - 8, altar_y - 16, sx + 8, altar_y - 16), fill=BLACK, width=3)
    _tarot_paint_pentagram(draw, cx + 46, altar_y - 12, 11, RED)  # pentacle


def _tarot_emblem_hermit(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """Hermit (IX): hooded silhouette with a raised lantern (a red star
    flame inside) and a diagonal staff.
    """
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    # Hooded silhouette: a triangle robe with a smaller triangle hood.
    robe = [
        (cx - 32, cy + 80),  # left foot
        (cx - 16, cy + 8),   # left shoulder
        (cx - 10, cy - 20),  # neck (left side of hood)
        (cx + 14, cy - 20),  # neck (right side of hood)
        (cx + 20, cy + 8),   # right shoulder
        (cx + 36, cy + 80),  # right foot
    ]
    draw.polygon(robe, fill=BLACK)
    # Hood: pointed peak above the head.
    hood = [
        (cx - 14, cy - 18),
        (cx + 2, cy - 50),
        (cx + 18, cy - 18),
    ]
    draw.polygon(hood, fill=BLACK)
    # Diagonal staff from the right shoulder to the ground.
    draw.line((cx + 18, cy + 4, cx + 60, cy + 90), fill=BLACK, width=4)
    # Raised lantern above the left shoulder.
    lx0, ly0, lx1, ly1 = cx - 60, cy - 50, cx - 28, cy - 14
    draw.rectangle((lx0, ly0, lx1, ly1), outline=BLACK, width=3)
    # Lantern panes — two vertical bars dividing the front face into 3.
    third = (lx1 - lx0) // 3
    draw.line((lx0 + third, ly0 + 2, lx0 + third, ly1 - 2), fill=BLACK, width=1)
    draw.line((lx0 + 2 * third, ly0 + 2, lx0 + 2 * third, ly1 - 2), fill=BLACK, width=1)
    # Lantern bail (handle).
    bail_cx = (lx0 + lx1) // 2
    draw.line((bail_cx, ly0, bail_cx, ly0 - 10), fill=BLACK, width=2)
    draw.arc((lx0 + 2, ly0 - 14, lx1 - 2, ly0 - 4), 0, 180, fill=BLACK, width=2)
    # Holding-arm line from lantern bail up to figure's hand.
    draw.line((bail_cx, ly0 - 10, cx - 10, cy - 14), fill=BLACK, width=2)
    # Flame inside the lantern — a red 12-point star.
    fx, fy = bail_cx, (ly0 + ly1) // 2
    flame_pts: list[tuple[float, float]] = []
    for i in range(24):
        angle = -math.pi / 2 + i * math.pi / 12
        r = 12 if i % 2 == 0 else 5
        flame_pts.append((fx + r * math.cos(angle), fy + r * math.sin(angle)))
    draw.polygon(flame_pts, fill=RED)


def _tarot_emblem_wheel(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """Wheel of Fortune (X): concentric rims with spokes, a red hub, and
    four letters (T A R O) at the cardinal points of the rim band.
    """
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    r_outer = 88
    r_mid = 70
    r_inner = 40
    r_hub = 16
    # Outer rim.
    draw.ellipse((cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer), outline=BLACK, width=4)
    # Mid rim (inscribed band).
    draw.ellipse((cx - r_mid, cy - r_mid, cx + r_mid, cy + r_mid), outline=BLACK, width=2)
    # Inner rim.
    draw.ellipse((cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner), outline=BLACK, width=2)
    # Eight spokes from inner rim to mid rim — the wheel's structural axles.
    for i in range(8):
        angle = i * math.pi / 4
        x1 = cx + r_inner * math.cos(angle)
        y1 = cy + r_inner * math.sin(angle)
        x2 = cx + r_mid * math.cos(angle)
        y2 = cy + r_mid * math.sin(angle)
        draw.line((x1, y1, x2, y2), fill=BLACK, width=2)
    # Red filled hub at the centre.
    draw.ellipse((cx - r_hub, cy - r_hub, cx + r_hub, cy + r_hub), fill=RED)
    # Cardinal letters in the band between the mid and outer rims.
    sigil_r = (r_outer + r_mid) // 2
    sigil_font = load_font(theme_font_candidates("tarot", "ornament"), size=14)
    for angle_deg, glyph in ((-90, "T"), (0, "A"), (90, "R"), (180, "O")):
        angle = math.radians(angle_deg)
        sx = cx + sigil_r * math.cos(angle)
        sy = cy + sigil_r * math.sin(angle)
        bbox = draw.textbbox((0, 0), glyph, font=sigil_font)
        gw = bbox[2] - bbox[0]
        gh = bbox[3] - bbox[1]
        draw.text((sx - gw // 2 - bbox[0], sy - gh // 2 - bbox[1]), glyph, font=sigil_font, fill=BLACK)
    # Engraver's divisions on the outer rim every 30°.
    for i in range(12):
        angle = i * math.pi / 6
        x1 = cx + (r_outer - 6) * math.cos(angle)
        y1 = cy + (r_outer - 6) * math.sin(angle)
        x2 = cx + r_outer * math.cos(angle)
        y2 = cy + r_outer * math.sin(angle)
        draw.line((x1, y1, x2, y2), fill=BLACK, width=1)


def _tarot_emblem_default(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """Generic red pentagram in a double circle with twelve radial ticks —
    the fallback for hours without a dedicated emblem.
    """
    RED = SPECTRA6["red"]
    BLACK = SPECTRA6["black"]
    # Inscribed circle behind the star.
    draw.ellipse((cx - 90, cy - 90, cx + 90, cy + 90), outline=BLACK, width=2)
    draw.ellipse((cx - 72, cy - 72, cx + 72, cy + 72), outline=BLACK, width=1)
    # Big pentagram.
    _tarot_paint_pentagram(draw, cx, cy, 70, RED)
    # Twelve radial dashes around the outer ring — clock-face ticks.
    for i in range(12):
        angle = i * math.pi / 6
        x1 = cx + 96 * math.cos(angle)
        y1 = cy + 96 * math.sin(angle)
        x2 = cx + 104 * math.cos(angle)
        y2 = cy + 104 * math.sin(angle)
        draw.line((x1, y1, x2, y2), fill=BLACK, width=1)


def _tarot_emblem_priestess(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """High Priestess (II): two pillars (B / J) flanking a crescent moon.

    The Rider-Waite Priestess sits between the pillars Boaz (left) and
    Jachin (right) with a crescent moon; a smaller moon rests at her feet.
    """
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    # Two pillars, left+right, height ~140.
    draw.rectangle((cx - 70, cy - 70, cx - 50, cy + 70), outline=BLACK, width=3)
    draw.rectangle((cx + 50, cy - 70, cx + 70, cy + 70), outline=BLACK, width=3)
    # Pillar capitals (cap blocks at the top of each).
    draw.rectangle((cx - 76, cy - 80, cx - 44, cy - 70), fill=BLACK)
    draw.rectangle((cx + 44, cy - 80, cx + 76, cy - 70), fill=BLACK)
    # "B" / "J" letters carved on the pillars.
    pillar_font = load_font(theme_font_candidates("tarot", "ornament"), size=18)
    for label, anchor_cx in (("B", cx - 60), ("J", cx + 60)):
        bbox = draw.textbbox((0, 0), label, font=pillar_font)
        gw = bbox[2] - bbox[0]
        gh = bbox[3] - bbox[1]
        draw.text(
            (anchor_cx - gw // 2 - bbox[0], cy - gh // 2 - bbox[1]),
            label, font=pillar_font, fill=BLACK,
        )
    # Crescent moon between the pillars: a disc with an offset knockout.
    moon_cx, moon_cy, moon_r = cx, cy - 50, 18
    draw.ellipse((moon_cx - moon_r, moon_cy - moon_r, moon_cx + moon_r, moon_cy + moon_r), fill=BLACK)
    # Knock out the right portion to create the crescent.
    knock_cx = moon_cx + 8
    draw.ellipse((knock_cx - moon_r, moon_cy - moon_r, knock_cx + moon_r, moon_cy + moon_r), fill=SPECTRA6["white"])
    # Scroll / TORA tablet at the priestess's lap (centred between pillars).
    scroll_cx, scroll_cy = cx, cy + 8
    draw.rectangle((scroll_cx - 16, scroll_cy - 12, scroll_cx + 16, scroll_cy + 12), outline=BLACK, width=2)
    # Three horizontal "text" hairlines on the scroll.
    for dy in (-5, 0, 5):
        draw.line((scroll_cx - 12, scroll_cy + dy, scroll_cx + 12, scroll_cy + dy), fill=BLACK, width=1)
    # Small red lunar dot at her feet — the moon she stands on.
    draw.ellipse((cx - 6, cy + 60, cx + 6, cy + 72), fill=RED)


def _tarot_emblem_empress(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """Empress (III): enthroned figure, twelve-star crown, wheat at her feet.

    The throne is a back behind the seated figure; drawn as the figure
    itself it read as a shield.
    """
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    # Throne back rising behind her.
    draw.polygon(
        [(cx - 58, cy + 76), (cx - 46, cy - 34), (cx + 46, cy - 34), (cx + 58, cy + 76)],
        outline=BLACK, width=3,
    )
    _, head_cy = _tarot_robed_figure(draw, cx, cy, top=-30, bottom=76, half_w=44, hair="long")
    # Corona stellarum duodecim — the twelve-star crown of Revelation 12.
    for i in range(12):
        angle = math.radians(200 + i * (140 / 11))
        sx = cx + 34 * math.cos(angle)
        sy = head_cy + 34 * math.sin(angle)
        draw.ellipse((sx - 2, sy - 2, sx + 2, sy + 2), fill=RED)
    # Heart shield resting against the robe.
    hy = cy + 18
    draw.polygon([
        (cx, hy + 14), (cx - 11, hy), (cx - 7, hy - 9),
        (cx, hy - 3), (cx + 7, hy - 9), (cx + 11, hy),
    ], fill=RED)
    # Wheat sheaf at her feet.
    for i in range(7):
        angle = math.radians(250 + i * 10)
        x2 = cx + 24 * math.cos(angle)
        y2 = cy + 86 + 24 * math.sin(angle)
        draw.line((cx, cy + 86, x2, y2), fill=BLACK, width=2)
        draw.ellipse((x2 - 2, y2 - 2, x2 + 2, y2 + 2), fill=BLACK)


def _tarot_emblem_emperor(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """Emperor (IV): seated crowned figure, ram finials, ankh and orb.

    The throne is two posts behind the seated figure (an empty rectangle
    read as a goalpost).
    """
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    # Throne back: two posts flanking the figure, ram spirals on top.
    for post_x in (cx - 62, cx + 62):
        draw.line((post_x, cy - 44, post_x, cy + 76), fill=BLACK, width=5)
        draw.arc((post_x - 14, cy - 62, post_x + 14, cy - 34), 0, 360, fill=BLACK, width=3)
        draw.arc((post_x - 7, cy - 55, post_x + 7, cy - 41), 0, 360, fill=BLACK, width=2)
    draw.line((cx - 62, cy - 44, cx + 62, cy - 44), fill=BLACK, width=4)
    _, head_cy = _tarot_robed_figure(draw, cx, cy, top=-26, bottom=76, half_w=44)
    _tarot_crown(draw, cx, head_cy - 13, 11)
    # Ankh scepter (right hand) and orb of dominion (left).
    ax, ay = cx + 36, cy + 14
    draw.ellipse((ax - 8, ay - 18, ax + 8, ay - 2), outline=RED, width=3)
    draw.line((ax, ay - 2, ax, ay + 26), fill=RED, width=3)
    draw.line((ax - 11, ay + 8, ax + 11, ay + 8), fill=RED, width=3)
    draw.ellipse((cx - 44, cy + 8, cx - 26, cy + 26), fill=RED)


def _tarot_emblem_hierophant(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """Hierophant (V): bearded figure under the triregnum, hand raised in blessing.

    He holds the keys, and the tiara sits on a head with a face.
    """
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    _, head_cy = _tarot_robed_figure(draw, cx, cy, top=-24, bottom=74, half_w=42, hair="beard")
    # Triple tiara: three outlined tiers with air between them. Stacked
    # flush they merge into one solid trapezoid (a dunce cap); the bands
    # between the crowns are what make it read as three.
    base = head_cy - 14
    for top_w, bot_w, depth in ((32, 40, 0), (24, 32, 17), (17, 24, 34)):
        bot_y = base - depth
        top_y = bot_y - 12
        draw.polygon([
            (cx - bot_w // 2, bot_y), (cx - top_w // 2, top_y),
            (cx + top_w // 2, top_y), (cx + bot_w // 2, bot_y),
        ], outline=BLACK, width=2)
        draw.rectangle((cx - bot_w // 2, bot_y - 3, cx + bot_w // 2, bot_y), fill=BLACK)
    draw.line((cx, base - 46, cx, base - 58), fill=BLACK, width=2)
    draw.line((cx - 4, base - 54, cx + 4, base - 54), fill=BLACK, width=2)
    # Right hand raised in benediction, left holding the crossed keys.
    _tarot_arm(draw, cx + 16, cy + 6, cx + 44, cy - 22)
    _tarot_arm(draw, cx - 16, cy + 6, cx - 44, cy + 26)
    for sign in (-1, 1):
        draw.line((cx - 52, cy + 56 - sign * 12, cx - 22, cy + 26 + sign * 12), fill=RED, width=3)
    draw.ellipse((cx - 58, cy + 38, cx - 44, cy + 52), outline=RED, width=2)
    draw.ellipse((cx - 58, cy + 56, cx - 44, cy + 70), outline=RED, width=2)


def _tarot_emblem_lovers(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """Lovers (VI): two figures beneath the sun, a tree behind each.

    The figures are kept well apart and given bodies: overlapping discs
    merged into a single blot at panel distance.
    """
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    # Sun overhead with rays.
    draw.ellipse((cx - 15, cy - 88, cx + 15, cy - 58), fill=RED)
    for i in range(12):
        a = i * math.pi / 6
        draw.line(
            (cx + 19 * math.cos(a), cy - 73 + 19 * math.sin(a),
             cx + 29 * math.cos(a), cy - 73 + 29 * math.sin(a)),
            fill=RED, width=2,
        )
    # The two figures, well clear of each other.
    for fx in (cx - 38, cx + 38):
        _tarot_robed_figure(draw, fx, cy, top=-34, bottom=52, half_w=24)
    # A tree behind each at the outer margin. The canopy sits well above
    # the heads and larger than one, or it reads as a second face.
    for tx in (cx - 68, cx + 68):
        draw.line((tx, cy - 18, tx, cy + 52), fill=BLACK, width=3)
        draw.ellipse((tx - 18, cy - 54, tx + 18, cy - 18), outline=BLACK, width=3)
    # Joined hands between them — the union the trump is about.
    draw.line((cx - 20, cy + 6, cx + 20, cy + 6), fill=BLACK, width=3)
    draw.polygon(
        [(cx, cy - 2), (cx + 9, cy + 6), (cx, cy + 16), (cx - 9, cy + 6)],
        fill=RED,
    )


def _tarot_emblem_chariot(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """Chariot (VII): crowned charioteer riding a canopied car.

    The charioteer stands in the car as a full figure; a small head over
    the cab rim read as an unmanned cart.
    """
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    # Canopy roof and its four columns, behind the rider.
    draw.line((cx - 58, cy - 62, cx + 58, cy - 62), fill=BLACK, width=3)
    for col_x in (cx - 50, cx + 50):
        draw.line((col_x, cy - 62, col_x, cy + 26), fill=BLACK, width=2)
    _tarot_paint_pentagram(draw, cx, cy - 76, 11, RED)
    # The charioteer, hem hidden behind the car's front panel.
    _tarot_robed_figure(draw, cx, cy, top=-50, bottom=30, half_w=30, folds=3)
    # Car: front panel drawn after the figure so he stands *in* it.
    draw.rectangle((cx - 58, cy + 26, cx + 58, cy + 62), fill=SPECTRA6["white"], outline=BLACK, width=3)
    draw.line((cx - 58, cy + 34, cx + 58, cy + 34), fill=BLACK, width=1)
    for wheel_cx in (cx - 44, cx + 44):
        draw.ellipse((wheel_cx - 17, cy + 56, wheel_cx + 17, cy + 88), outline=BLACK, width=3)
        draw.line((wheel_cx, cy + 56, wheel_cx, cy + 88), fill=BLACK, width=2)
        draw.line((wheel_cx - 17, cy + 72, wheel_cx + 17, cy + 72), fill=BLACK, width=2)
        draw.ellipse((wheel_cx - 4, cy + 68, wheel_cx + 4, cy + 76), fill=RED)


def _tarot_emblem_strength(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """Strength (VIII): lion's head crowned by an infinity lemniscate.

    Distils the Rider-Waite card (a woman closing a lion's jaws under the
    lemniscate) to the maned lion's head and the lemniscate above it.
    """
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    # Infinity lemniscate at the top — two overlapping circles.
    draw.arc((cx - 44, cy - 100, cx, cy - 70), 0, 360, fill=BLACK, width=3)
    draw.arc((cx, cy - 100, cx + 44, cy - 70), 0, 360, fill=BLACK, width=3)
    # Lion's mane — many short black lines radiating outward from the head.
    head_cx, head_cy, head_r = cx, cy + 10, 36
    for i in range(28):
        angle = 2 * math.pi * i / 28
        # Vary the mane length slightly so it looks furry.
        r_out = head_r + (14 if i % 2 == 0 else 22)
        x1 = head_cx + head_r * math.cos(angle)
        y1 = head_cy + head_r * math.sin(angle)
        x2 = head_cx + r_out * math.cos(angle)
        y2 = head_cy + r_out * math.sin(angle)
        draw.line((x1, y1, x2, y2), fill=BLACK, width=2)
    # Lion's face — filled black circle with red eye dots and a stylised mouth.
    draw.ellipse((head_cx - head_r, head_cy - head_r, head_cx + head_r, head_cy + head_r), fill=BLACK)
    # Eyes.
    draw.ellipse((head_cx - 14, head_cy - 8, head_cx - 6, head_cy), fill=RED)
    draw.ellipse((head_cx + 6, head_cy - 8, head_cx + 14, head_cy), fill=RED)
    # Mouth — small red curve.
    draw.arc((head_cx - 10, head_cy + 4, head_cx + 10, head_cy + 20), 0, 180, fill=RED, width=2)
    # Two small fang triangles in the mouth.
    draw.polygon([(head_cx - 4, head_cy + 14), (head_cx - 2, head_cy + 20), (head_cx, head_cy + 14)], fill=SPECTRA6["white"])
    draw.polygon([(head_cx, head_cy + 14), (head_cx + 2, head_cy + 20), (head_cx + 4, head_cy + 14)], fill=SPECTRA6["white"])


def _tarot_emblem_justice(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """Justice (XI): crowned figure, sword raised right, scales held left.

    The sword in one hand and the scales in the other (the Rider-Waite
    composition) is what makes each attribute legible as itself.
    """
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    _, head_cy = _tarot_robed_figure(draw, cx, cy, top=-40, bottom=68, half_w=38)
    _tarot_crown(draw, cx, head_cy - 12, 10)
    # Sword raised in the right hand: blade up, crossguard, red pommel.
    sx = cx + 44
    draw.line((sx, cy - 66, sx, cy + 26), fill=BLACK, width=5)
    draw.line((sx - 14, cy + 12, sx + 14, cy + 12), fill=BLACK, width=4)
    draw.ellipse((sx - 6, cy + 26, sx + 6, cy + 38), fill=RED)
    draw.line((cx + 16, cy + 2, sx, cy + 18), fill=BLACK, width=3)
    # Scales held out in the left hand.
    # Held out clear of the robe: at half_w=38 the hem reaches cx-38, and
    # an inboard pan landed on top of it.
    hx, hy = cx - 52, cy - 22
    draw.line((cx - 16, cy - 4, hx, hy + 4), fill=BLACK, width=3)
    draw.line((hx, hy, hx, hy + 14), fill=BLACK, width=3)
    beam_y = hy + 14
    draw.line((hx - 18, beam_y, hx + 18, beam_y), fill=BLACK, width=3)
    for pan_x in (hx - 16, hx + 16):
        draw.line((pan_x, beam_y, pan_x, beam_y + 16), fill=BLACK, width=2)
        draw.polygon(
            [
                (pan_x - 13, beam_y + 16), (pan_x + 13, beam_y + 16),
                (pan_x + 9, beam_y + 26), (pan_x - 9, beam_y + 26),
            ],
            fill=BLACK,
        )
    draw.polygon(
        [(hx, beam_y - 5), (hx + 5, beam_y), (hx, beam_y + 5), (hx - 5, beam_y)],
        fill=RED,
    )


def _tarot_emblem_world(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
    """World (XII): dancing figure within a laurel wreath, four corner creatures.

    Distils the Rider-Waite card — the dancer in an oval laurel wreath with
    the four creatures at the corners — to the wreath, the figure and four
    small corner marks.
    """
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    # Laurel wreath — oval of small leaf shapes around a central oval.
    wreath_a, wreath_b = 60, 80  # semi-major / semi-minor axes
    n_leaves = 24
    for i in range(n_leaves):
        angle = 2 * math.pi * i / n_leaves
        ox = cx + wreath_a * math.cos(angle)
        oy = cy + wreath_b * math.sin(angle)
        # Leaf: small ellipse oriented tangent to the wreath.
        leaf_a, leaf_b = 8, 4
        # Polygon-approximated rotated ellipse (PIL has no rotate-ellipse).
        leaf_pts = []
        for j in range(8):
            la = 2 * math.pi * j / 8
            lx = leaf_a * math.cos(la)
            ly = leaf_b * math.sin(la)
            # Rotate by the wreath-tangent angle (perpendicular to radial).
            tangent = angle + math.pi / 2
            rx = lx * math.cos(tangent) - ly * math.sin(tangent)
            ry = lx * math.sin(tangent) + ly * math.cos(tangent)
            leaf_pts.append((ox + rx, oy + ry))
        draw.polygon(leaf_pts, fill=BLACK)
    # Dancing figure inside the wreath: the one unrobed trump (the dancer
    # is conventionally bare with a floating scarf), but with the same face.
    head_r = 11
    head_cy = cy - 30
    draw.ellipse(
        (cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r),
        outline=BLACK, width=3,
    )
    _tarot_face(draw, cx, head_cy, head_r, hair="short")
    draw.line((cx, head_cy + head_r, cx, cy + 12), fill=BLACK, width=4)
    _tarot_arm(draw, cx, cy - 12, cx - 26, cy - 30, elbow=-0.4)
    _tarot_arm(draw, cx, cy - 12, cx + 26, cy + 4, elbow=0.4)
    # Legs, one straight and one bent — the crossed-leg dancing pose.
    draw.line([(cx, cy + 12), (cx - 12, cy + 30), (cx - 18, cy + 48)], fill=BLACK, width=3, joint="curve")
    draw.line([(cx, cy + 12), (cx + 15, cy + 28), (cx + 5, cy + 46)], fill=BLACK, width=3, joint="curve")
    # The floating scarf, in the rubric red the rest of the card uses.
    draw.line(
        [(cx - 30, cy - 16), (cx - 8, cy - 4), (cx + 14, cy - 14), (cx + 32, cy - 2)],
        fill=RED, width=3, joint="curve",
    )
    # Wreath ribbons — two red bow-knots at top and bottom where the wreath ties.
    draw.ellipse((cx - 6, cy - 86, cx + 6, cy - 74), fill=RED)
    draw.ellipse((cx - 6, cy + 74, cx + 6, cy + 86), fill=RED)
    # The four creatures as small red pentagrams. Kept within ±62 x: at
    # ±90 the illustration panel clipped them away entirely.
    for corner_cx in (cx - 62, cx + 62):
        for corner_cy in (cy - 66, cy + 66):
            _tarot_paint_pentagram(draw, corner_cx, corner_cy, 7, RED)


_TAROT_EMBLEMS = {
    1: _tarot_emblem_magician,
    2: _tarot_emblem_priestess,
    3: _tarot_emblem_empress,
    4: _tarot_emblem_emperor,
    5: _tarot_emblem_hierophant,
    6: _tarot_emblem_lovers,
    7: _tarot_emblem_chariot,
    8: _tarot_emblem_strength,
    9: _tarot_emblem_hermit,
    10: _tarot_emblem_wheel,
    11: _tarot_emblem_justice,
    12: _tarot_emblem_world,
}


# The emblems are drawn at native size and the tile enlarged, rather than
# re-scaling twelve hand-tuned coordinate sets; the enlargement also
# thickens every stroke (2 px → 3 px), giving the line figures a woodcut's
# weight.
_TAROT_EMBLEM_SCALE = 1.5
# Native half-extent of the largest emblem (the Magician's staff reaches
# ~100 px above centre); the tile must hold the whole figure.
_TAROT_EMBLEM_TILE = 240
# The emblems paint in black and red plus a few white knockouts (the
# Priestess's moon, Strength's fangs, the Chariot's front panel). Enlarging
# is done in RGB rather than per-ink masks because masks lose the draw
# order, and a knockout only works stamped after its black ground.
_TAROT_EMBLEM_INKS = [SPECTRA6["white"], SPECTRA6["black"], SPECTRA6["red"]]


def _tarot_plate_tile(hour_int: int) -> Image.Image | None:
    """One trump cropped from the committed sprite sheet, or ``None``.

    The sheet is decoded once per process and memoised, so a render pays a
    crop rather than a decode (it matters for the 144-frame contact sheet).

    Hour maps to trump number directly, keeping the plate's Marseille
    numbering in step with the Roman hour painted above it.
    """
    if not TAROT_PLATES.exists():
        return None
    sheet = _TAROT_PLATE_CACHE.get("sheet")
    if sheet is None:
        try:
            with Image.open(TAROT_PLATES) as raw:
                sheet = raw.convert("RGB")
        except (OSError, ValueError):
            return None
        _TAROT_PLATE_CACHE["sheet"] = sheet
    tw = sheet.width // _TAROT_PLATE_COLS
    th = sheet.height // _TAROT_PLATE_ROWS
    i = (hour_int - 1) % (_TAROT_PLATE_COLS * _TAROT_PLATE_ROWS)
    col, row = i % _TAROT_PLATE_COLS, i // _TAROT_PLATE_COLS
    return sheet.crop((col * tw, row * th, (col + 1) * tw, (row + 1) * th))


def _tarot_stamp_tile(
    image: Image.Image,
    tile: Image.Image,
    cx: int,
    cy: int,
    clip: tuple[int, int, int, int] | None,
) -> None:
    """Stamp a tile centred on (cx, cy), skipping white and honouring ``clip``.

    White is skipped so the card's cream wash shows through the figure's
    negative space. The plate tile is exactly panel-sized, so ``clip`` is a
    no-op for it; the oversized polygon tile relies on it.
    """
    px = image.load()
    src = tile.load()
    w, h = image.size
    ox = cx - tile.width // 2
    oy = cy - tile.height // 2
    lo_x, lo_y, hi_x, hi_y = (0, 0, w, h) if clip is None else clip
    # Inset by one so the stamp never lands on the keyline itself.
    lo_x, lo_y = max(0, lo_x + 1), max(0, lo_y + 1)
    hi_x, hi_y = min(w, hi_x), min(h, hi_y)
    WHITE = SPECTRA6["white"]
    for ty in range(tile.height):
        y = oy + ty
        if not lo_y <= y < hi_y:
            continue
        for tx in range(tile.width):
            x = ox + tx
            if not lo_x <= x < hi_x:
                continue
            ink = src[tx, ty]
            if ink != WHITE:
                px[x, y] = ink


def _tarot_paint_emblem(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    hour_int: int,
    cx: int,
    cy: int,
    clip: tuple[int, int, int, int] | None = None,
) -> str:
    """Stamp the hour's trump: the committed Dodal plate, else the painter.

    The painter's figure is drawn at native size onto a white tile, scaled
    by ``_TAROT_EMBLEM_SCALE``, snapped back to its three inks, and stamped
    with white skipped.

    ``clip`` bounds the stamp to the illustration panel: the widest
    emblems reach past the keyline once enlarged, and a figure crossing its
    frame reads as a layout fault. Clipping rather than shrinking keeps the
    stroke weight.

    Returns the drawn trump's name, so the card is titled by the same call
    that chose the figure — the two sources number three of the twelve
    hours differently (see ``_TAROT_TRUMP_NAMES``).
    """
    tile = _tarot_plate_tile(hour_int)
    if tile is not None:
        _tarot_stamp_tile(image, tile, cx, cy, clip)
        return _TAROT_TRUMP_NAMES.get(hour_int, "")

    painter = _TAROT_EMBLEMS.get(hour_int, _tarot_emblem_default)
    size = _TAROT_EMBLEM_TILE
    half = size // 2
    tile = Image.new("RGB", (size, size), SPECTRA6["white"])
    painter(ImageDraw.Draw(tile), half, half)
    scaled = size * _TAROT_EMBLEM_SCALE
    tile = tile.resize((round(scaled), round(scaled)), Image.LANCZOS)
    tile = snap_image_to_palette(tile, _TAROT_EMBLEM_INKS)
    _tarot_stamp_tile(image, tile, cx, cy, clip)
    return _TAROT_PAINTER_TRUMP_NAMES.get(hour_int, "")


def _tarot_paint_body_panel(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
) -> None:
    """Knock out a clean cream "interpretation panel" beneath the emblem.

    The card-stock foxing breaks up EB Garamond's hairlines and muddles the
    purple matched-phrase dither, so the body region is overpainted with a
    clean cream wash (Y+W at 1-in-8, no R+G dots) and framed with a thin red
    rule, so the knockout reads as a deliberate cartouche.
    """
    WHITE = SPECTRA6["white"]
    YELLOW = SPECTRA6["yellow"]
    RED = SPECTRA6["red"]
    x0, y0, x1, y1 = rect
    # Step 1: solid white wipe — clears any foxing dots within the panel.
    draw.rectangle((x0, y0, x1, y1), fill=WHITE)
    # Step 2: a fresh cream wash so the panel still matches the vellum.
    px = image.load()
    # Clip the PixelAccess writes: the fixed 800x480 coordinates overrun
    # smaller canvases.
    w, h = image.size
    for y in range(max(0, y0), min(h, y1)):
        row = BAYER_4x4[y % 4]
        for x in range(max(0, x0), min(w, x1)):
            if row[x % 4] < 2:
                px[x, y] = YELLOW
    # Step 3: thin red rule framing the panel.
    draw.rectangle((x0, y0, x1, y1), outline=RED, width=1)


def _tarot_paint_body(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    quote_row: dict,
    rect: tuple[int, int, int, int],
) -> None:
    """Quote body fitted into ``rect`` with matched-phrase Tyrian purple.

    Expects ``_tarot_paint_body_panel`` to have knocked out a clean panel
    under ``rect`` first.
    """
    BLACK = SPECTRA6["black"]
    RED = SPECTRA6["red"]
    BLUE = SPECTRA6["blue"]
    x0, y0, x1, y1 = rect
    width = x1 - x0
    height = y1 - y0
    # Inset slightly from the panel edge so glyphs don't kiss the red rule.
    pad = 8
    width -= 2 * pad
    height -= 2 * pad
    x0 += pad
    y0 += pad
    display_quote = normalize_dashes(strip_underscore_emphasis(quote_row.get("display_quote") or ""))
    matched = quote_row.get("matched_text") or ""

    quote_font, quote_font_bold, wrapped_quote, line_height, _ = fit_quote(
        draw,
        display_quote,
        matched,
        width,
        height,
        font_max=26,
        font_min=15,
        line_height_mult=1.24,
        theme="tarot",
    )
    quote_block_height = len(wrapped_quote) * line_height
    block_top = y0 + max(0, (height - quote_block_height) // 2)
    body_ascent = _font_ascent(quote_font)
    y = block_top
    for line in wrapped_quote:
        # Trim leading/trailing whitespace tokens.
        start = 0
        while start < len(line) and line[start][0].strip() == "":
            start += 1
        end = len(line)
        while end > start and line[end - 1][0].strip() == "":
            end -= 1
        drawable = line[start:end]
        # Centre the line horizontally.
        line_width = 0
        for chunk, is_bold in drawable:
            font = quote_font_bold if is_bold else quote_font
            bbox = draw.textbbox((0, 0), chunk, font=font)
            line_width += bbox[2] - bbox[0]
        x = x0 + max(0, (width - line_width) // 2)
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


def _tarot_paint_attribution(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    quote_row: dict,
    cx: int,
    y_top: int,
    max_w: int,
) -> None:
    """Author · title in Cinzel Decorative Regular 12, solid black, centred.

    ``max_w`` is passed by the caller (the reading panel's inner width), so
    the byline can never cross the cartouche's rule.
    """
    BLACK = SPECTRA6["black"]
    font = load_font(theme_font_candidates("tarot", "ornament"), size=12)
    fitted = _fit_dotted_byline(draw, quote_row, font, max_w)
    if fitted is None:
        return
    text, bbox = fitted
    w = bbox[2] - bbox[0]
    draw.text((cx - w // 2 - bbox[0], y_top - bbox[1]), text, font=font, fill=BLACK)


def _tarot_paint_card_stock(
    image: Image.Image, draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int],
) -> None:
    """Lay the card onto the cloth: drop shadow, then a cleaner stock.

    The card and the cloth share a recipe, so without a tonal split the
    card's border reads as a rule drawn *on* the cloth. The interior is
    re-washed at a lower cream density with no foxing, and lifted by a black
    shadow ledge on the lower-right (as ``kanagawa`` / ``pride`` do).
    """
    WHITE = SPECTRA6["white"]
    YELLOW = SPECTRA6["yellow"]
    BLACK = SPECTRA6["black"]
    x0, y0, x1, y1 = rect
    off = _TAROT_CARD_SHADOW
    draw.rectangle((x0 + off, y0 + off, x1 + off, y1 + off), fill=BLACK)
    draw.rectangle((x0, y0, x1, y1), fill=WHITE)
    card_w = max(0, min(image.width, x1 + 1) - max(0, x0))
    card_h = max(0, min(image.height, y1 + 1) - max(0, y0))
    if not card_w or not card_h:
        return
    cut = round(_TAROT_CREAM_DENSITY * 0.75 * 255)
    stock = _white_noise(card_w, card_h, _TAROT_CREAM_SEED)
    image.paste(YELLOW, (max(0, x0), max(0, y0)), stock.point(lambda v: 255 if v < cut else 0))


def _tarot_paint_emblem_panel(
    draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int],
) -> None:
    """Thin keyline around the trump illustration.

    Historical trumps set the figure inside a ruled panel; without it the
    compact line emblems read as clip art floating on the stock.
    """
    draw.rectangle(rect, outline=SPECTRA6["black"], width=1)


def render_tarot_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """A single trump laid on a reading cloth, interpretation beside it.

    Left: a portrait card on foxed vellum — doubled red+black rule, corner
    lozenges, the Roman-numeral hour above a ruled illustration panel, and
    the trump's name along the foot (the layout every historical trump
    uses). The time itself stays in the quote's matched phrase.

    Right: the reading — a clean cream cartouche carrying the quote in EB
    Garamond with a Tyrian-purple matched phrase, attribution at its foot.
    """
    # Composed at the canonical 800x480 and NEAREST-downsampled otherwise
    # (the ``metro`` convention): every rectangle is an absolute panel
    # coordinate, and a direct small render would put the reading panel
    # off-canvas.
    image = Image.new("RGB", (800, 480), color=SPECTRA6["white"])
    _tarot_paint_vellum(image)
    draw = ImageDraw.Draw(image)

    hour_int = _clock_hour12(time_str)

    # ── the card ──────────────────────────────────────────────────────
    card_rect = _TAROT_CARD_RECT
    x0, y0, x1, y1 = card_rect
    card_cx = (x0 + x1) // 2
    _tarot_paint_card_stock(image, draw, card_rect)
    _tarot_paint_doubled_border(image, draw, card_rect)
    _tarot_paint_corner_pips(draw, card_rect)
    _tarot_paint_roman_numeral(image, draw, hour_int, card_cx, y0 + 20)

    # Illustration panel: the numeral and name bands are carved out of the
    # card's height first, and the emblem gets what is left.
    panel = (x0 + 20, y0 + 68, x1 - 20, y1 - 74)
    _tarot_paint_emblem_panel(draw, panel)
    trump = _tarot_paint_emblem(image, draw, hour_int, card_cx, (panel[1] + panel[3]) // 2, clip=panel)

    # The trump's name along the foot, titled by the emblem call itself.
    _tarot_paint_card_name(image, draw, trump, card_rect, y1 - 60)

    # ── the reading ───────────────────────────────────────────────────
    rx0, ry0, rx1, ry1 = _TAROT_READING_RECT
    _tarot_paint_body_panel(image, draw, (rx0, ry0, rx1, ry1))
    attribution_band = 30
    _tarot_paint_body(image, draw, quote_row, (rx0, ry0, rx1, ry1 - attribution_band))
    # The byline shares the body's inset from the panel rule, so it can
    # never be wider than the text it attributes.
    _tarot_paint_attribution(image, draw, quote_row, (rx0 + rx1) // 2, ry1 - 22, (rx1 - rx0) - 16)

    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("tarot",), render=render_tarot_frame)
