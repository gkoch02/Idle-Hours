"""The ``dsky`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .._paths import JOST_VARIABLE, META_FONT_BOLD_CANDIDATES, META_FONT_CANDIDATES, SPECIALELITE_REGULAR
from ..fonts import load_font
from ..furniture import _clock_hour12, _paint_placed, _place_quote, _row_digest, fallback_title
from ..palette import _PANEL_INKS, SPECTRA6, SPECTRA6_PALETTE, _dither_calibrated, snap_image_to_palette
from ..primitives import _fill_swatch_stipple, _shade_silhouette, _smooth_noise, paint_neon_mask
from ..spec import FrameSpec
from ..text import draw_tracked, fit_text_to_width, tracked_width

# ---------------------------------------------------------------------------
# dsky — the Apollo Guidance Computer's display and keyboard (1966–1972)
# ---------------------------------------------------------------------------
# The Apollo Guidance Computer's display and keyboard (Block II geometry) on
# the grey main console, with a typed flight-plan page clipped beside it. Full
# design notes: docs/themes.md (``dsky``).
#
# The console and the unit are modelled in continuous tone (grey panel with a
# brushed grain, a shaded rim, domed keycaps, shaded screws, recessed dark
# windows, a reflection across the display, soft shadows) and Floyd–Steinberg
# dithered to white and black (``_dither_calibrated``); the card, legends,
# segments, lit lamp and type go on after the dither.
#
# The flight plan is typed in Special Elite in black, with the matched phrase
# in red like the pen-and-ink updates.
#
# The hour is the program: the PROG register shows 01..12, pinned across the
# minutes. VERB 06 NOUN 62 stays up and the three registers are telemetry
# seeded from the quote. Each digit is a true seven-segment glyph in a mask
# (``_dsky_draw_glyph``), painted white-hot with a green bloom through
# ``paint_neon_mask`` with ``ground`` pinned to black. COMP ACTY is the one
# lit lamp, solid green. Composed at 800x480 and NEAREST-downsampled otherwise
# (the ``metro`` convention).
# ---------------------------------------------------------------------------
_DSKY_SEED = 0x44534B59               # DSKY
_DSKY_INKS = ("white", "black")
_DSKY_PANEL = 0.52                    # the console grey, as a fraction of the way to black
_DSKY_CARD_RECT = (30, 34, 452, 452)
_DSKY_QUOTE_RECT = (54, 104, 428, 384)
_DSKY_BYLINE_Y = 404
_DSKY_UNIT_RECT = (476, 18, 786, 464)
_DSKY_RIM = 10
_DSKY_LAMP_WINDOW = (494, 40, 632, 230)
_DSKY_LAMP_ORIGIN = (501, 48)
_DSKY_LAMP_SIZE = (60, 21)
_DSKY_LAMP_GAP = (5, 5)
_DSKY_LAMPS = (("UPLINK", "TEMP"), ("NO ATT", "GIMBAL"), ("STBY", "PROG"), ("KEY REL", "RESTART"),
               ("OPR ERR", "TRACKER"), ("", "ALT"), ("", "VEL"))
_DSKY_DISPLAY_RECT = (642, 40, 770, 230)
_DSKY_KEYPAD_ORIGIN = (497, 252)
_DSKY_KEY = 36
_DSKY_KEY_GAP = 5
_DSKY_KEYS = (("VERB", "+", "7", "8", "9", "CLR", "ENTR"),
              ("NOUN", "-", "4", "5", "6", "PRO", "RSET"),
              ("", "0", "1", "2", "3", "KEY\nREL", ""))
_DSKY_VERB, _DSKY_NOUN = "06", "62"
_DSKY_SCENE: dict = {}
# Seven-segment encodings: a top, b upper right, c lower right, d bottom,
# e lower left, f upper left, g middle.
_DSKY_SEGMENTS = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd",
    "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg", "-": "g", "+": "g|", " ": "",
}


def _dsky_tone(t: float) -> tuple[int, int, int]:
    """A grey ``t`` of the way from the white ink to the black ink."""
    r, g, b = (round(w + (k - w) * t) for w, k in zip(_PANEL_INKS["white"], _PANEL_INKS["black"]))
    return r, g, b


def _dsky_segments(ch: str) -> str:
    return _DSKY_SEGMENTS.get(ch, "")


def _dsky_draw_glyph(draw: ImageDraw.ImageDraw, x: int, y: int, ch: str, *, h: int = 22, w: int = 12,
                     t: int = 3) -> None:
    """One seven-segment character into an ``L`` mask at (x, y)."""
    segs = _dsky_segments(ch)
    mid = y + h // 2
    if "a" in segs:
        draw.rectangle((x + 1, y, x + w - 1, y + t - 1), fill=255)
    if "b" in segs:
        draw.rectangle((x + w - t, y + 1, x + w - 1, mid - 1), fill=255)
    if "c" in segs:
        draw.rectangle((x + w - t, mid + 1, x + w - 1, y + h - 1), fill=255)
    if "d" in segs:
        draw.rectangle((x + 1, y + h - t, x + w - 1, y + h - 1), fill=255)
    if "e" in segs:
        draw.rectangle((x, mid + 1, x + t - 1, y + h - 1), fill=255)
    if "f" in segs:
        draw.rectangle((x, y + 1, x + t - 1, mid - 1), fill=255)
    if "g" in segs:
        draw.rectangle((x + 1, mid - t // 2, x + w - 1, mid - t // 2 + t - 1), fill=255)
    if "|" in segs:
        draw.rectangle((x + w // 2 - t // 2, mid - 6, x + w // 2 - t // 2 + t - 1, mid + 6), fill=255)


def _dsky_registers(quote_row: dict) -> list[str]:
    """Three signed five-digit registers of telemetry, seeded from the quote."""
    rng = random.Random(_DSKY_SEED ^ _row_digest(quote_row))
    return [f"{rng.choice('+-')}{rng.randint(0, 99999):05d}" for _ in range(3)]


def _dsky_label_font(size: int):
    return load_font([(JOST_VARIABLE, "Medium"), *META_FONT_BOLD_CANDIDATES], size=size)


def _dsky_key_rects() -> list:
    rects = []
    ox, oy = _DSKY_KEYPAD_ORIGIN
    k, g = _DSKY_KEY, _DSKY_KEY_GAP
    for r, row in enumerate(_DSKY_KEYS):
        for c, label in enumerate(row):
            if label:
                x, y = ox + c * (k + g), oy + r * (k + g)
                rects.append((x, y, x + k, y + k, label))
    return rects


def _dsky_lamp_rects() -> list:
    rects = []
    ox, oy = _DSKY_LAMP_ORIGIN
    w, h = _DSKY_LAMP_SIZE
    gx, gy = _DSKY_LAMP_GAP
    for r, row in enumerate(_DSKY_LAMPS):
        for c, label in enumerate(row):
            x, y = ox + c * (w + gx), oy + r * (h + gy)
            rects.append((x, y, x + w, y + h, label))
    return rects


def _dsky_paint_console(scene: Image.Image) -> None:
    """The grey panel with its brushed grain, the unit's shadow and the
    card's shadow."""
    size = scene.size
    scene.paste(Image.new("RGB", size, _dsky_tone(_DSKY_PANEL)), (0, 0))
    grain = _smooth_noise(size, (200, 9), _DSKY_SEED + 1).point(lambda v: v * 14 // 255)
    scene.paste(ImageChops.subtract(ImageChops.add(scene, Image.merge("RGB", (grain, grain, grain))),
                                    Image.new("RGB", size, (7, 7, 7))))
    for rect, blur, depth in ((_DSKY_UNIT_RECT, 6, 0.86), (_DSKY_CARD_RECT, 4, 0.80)):
        shadow = Image.new("L", size, 0)
        ImageDraw.Draw(shadow).rounded_rectangle((rect[0] + 5, rect[1] + 6, rect[2] + 7, rect[3] + 8), radius=8, fill=255)
        shadow = shadow.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * 0.8))
        scene.paste(Image.new("RGB", size, _dsky_tone(depth)), (0, 0), shadow)
        shadow.close()


def _dsky_paint_unit(scene: Image.Image) -> None:
    """The unit in tone: the black face plate with a raised, lit rim, the
    recessed windows, the reflection, the keycaps, the screws."""
    size = scene.size
    x0, y0, x1, y1 = _DSKY_UNIT_RECT
    draw = ImageDraw.Draw(scene)
    # The face plate, and the rim modelled as a ring under the upper-left light.
    plate = Image.new("L", size, 0)
    ImageDraw.Draw(plate).rounded_rectangle((x0, y0, x1, y1), radius=10, fill=255)
    rim = ImageChops.subtract(plate, plate.filter(ImageFilter.MinFilter(2 * _DSKY_RIM + 1)))
    shaded = _shade_silhouette(rim, _dsky_tone(0.80), _dsky_tone(0.40), _dsky_tone(0.97), offset=5, blur=3)
    scene.paste(Image.new("RGB", size, _dsky_tone(0.90)), (0, 0), plate)
    scene.paste(shaded, (0, 0), rim)
    # The windows: recessed dark glass, a touch lighter at their top edge.
    for wx0, wy0, wx1, wy1 in (_DSKY_LAMP_WINDOW, _DSKY_DISPLAY_RECT):
        draw.rectangle((wx0, wy0, wx1, wy1), fill=_dsky_tone(0.96))
        draw.rectangle((wx0, wy0, wx1, wy0 + 2), fill=_dsky_tone(0.70))
        draw.rectangle((wx0, wy0, wx0 + 2, wy1), fill=_dsky_tone(0.78))
    # The unlit lamps: smoked glass a shade above the window.
    for lx0, ly0, lx1, ly1, label in _dsky_lamp_rects():
        draw.rectangle((lx0, ly0, lx1, ly1), fill=_dsky_tone(0.92))
    # A reflection across the display glass.
    reflection = Image.new("L", size, 0)
    dx0, dy0, dx1, dy1 = _DSKY_DISPLAY_RECT
    ImageDraw.Draw(reflection).polygon([(dx0 + 30, dy0), (dx0 + 70, dy0), (dx1, dy1 - 70), (dx1, dy1 - 30)], fill=255)
    reflection = reflection.filter(ImageFilter.GaussianBlur(6)).point(lambda v: int(v * 0.22))
    scene.paste(Image.new("RGB", size, _dsky_tone(0.40)), (0, 0), reflection)
    # The keypad: a recessed grey tray, and on it the keycaps — near-black
    # domes with a lit upper-left edge and a core shadow, so each key reads
    # as a dark square on the lighter tray.
    rects = _dsky_key_rects()
    tx0 = min(r[0] for r in rects) - 8
    ty0 = min(r[1] for r in rects) - 8
    tx1 = max(r[2] for r in rects) + 8
    ty1 = max(r[3] for r in rects) + 8
    draw.rounded_rectangle((tx0, ty0, tx1, ty1), radius=6, fill=_dsky_tone(0.62))
    draw.rectangle((tx0, ty0, tx1, ty0 + 2), fill=_dsky_tone(0.80))
    keys = Image.new("L", size, 0)
    kd = ImageDraw.Draw(keys)
    for kx0, ky0, kx1, ky1, label in rects:
        kd.rounded_rectangle((kx0, ky0, kx1, ky1), radius=6, fill=255)
    caps = _shade_silhouette(keys, _dsky_tone(0.90), _dsky_tone(0.40), _dsky_tone(0.99), offset=4, blur=3)
    scene.paste(caps, (0, 0), keys)
    # Screws at the plate's corners.
    for sx, sy in ((x0 + 14, y0 + 14), (x1 - 14, y0 + 14), (x0 + 14, y1 - 14), (x1 - 14, y1 - 14)):
        screw = Image.new("L", size, 0)
        ImageDraw.Draw(screw).ellipse((sx - 5, sy - 5, sx + 5, sy + 5), fill=255)
        head = _shade_silhouette(screw, _dsky_tone(0.55), _dsky_tone(0.20), _dsky_tone(0.92), offset=3, blur=2)
        scene.paste(head, (0, 0), screw)
        screw.close()
    for m in (plate, rim, shaded, reflection, keys, caps):
        m.close()


def _dsky_scene() -> Image.Image:
    """The console, the unit and the card — everything the hour and the
    quote do not touch — dithered. Painted once per process."""
    key = (_dsky_paint_console, _dsky_paint_unit, _dsky_paint_card)
    cached = _DSKY_SCENE.get("frame")
    if cached is not None and cached[0] == key:
        return cached[1]
    size = (800, 480)
    scene = Image.new("RGB", size, _PANEL_INKS["white"])
    _dsky_paint_console(scene)
    _dsky_paint_unit(scene)
    image = _dither_calibrated(scene, _DSKY_INKS)
    _dsky_paint_card(image)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)       # the card's typed header is antialiased
    _DSKY_SCENE["frame"] = (key, image)
    return image


def _dsky_paint_card(image: Image.Image) -> None:
    """The flight-plan card after the dither: cream paper, a hairline edge,
    the clip at its head, the typed header and rule."""
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = _DSKY_CARD_RECT
    black, white = SPECTRA6["black"], SPECTRA6["white"]
    _fill_swatch_stipple(image, (x0, y0, x1, y1), white, SPECTRA6["yellow"], 0.25)
    draw.rectangle((x0, y0, x1, y1), outline=black, width=1)
    # The clip: a bulldog clip's two plates and its loop, in solid inks.
    cx = (x0 + x1) // 2
    draw.rounded_rectangle((cx - 34, y0 - 10, cx + 34, y0 + 14), radius=4, fill=black)
    draw.rectangle((cx - 30, y0 - 6, cx + 30, y0 + 10), outline=white, width=1)
    draw.arc((cx - 16, y0 - 22, cx + 16, y0 + 2), 180, 360, fill=black, width=4)
    font = load_font([SPECIALELITE_REGULAR, *META_FONT_CANDIDATES], size=13)
    draw.text((x0 + 24, y0 + 30), "APOLLO FLIGHT PLAN      CSM/LM TIMELINE", font=font, fill=black)
    draw.text((x1 - 24 - draw.textlength("PAGE 3-61", font=font), y0 + 30), "PAGE 3-61", font=font, fill=black)
    draw.line((x0 + 24, y0 + 52, x1 - 24, y0 + 52), fill=black, width=1)
    for hx in range(x0 + 10, x1 - 10, 2):
        draw.point((hx, y0 + 18), fill=black)


def _dsky_paint_legends(draw: ImageDraw.ImageDraw) -> None:
    """After the dither: the lamp words, the key caps' legends, the window
    labels and the nameplate."""
    white, black = SPECTRA6["white"], SPECTRA6["black"]
    font = _dsky_label_font(10)
    for lx0, ly0, lx1, ly1, label in _dsky_lamp_rects():
        draw.rectangle((lx0, ly0, lx1, ly1), outline=black, width=1)
        if label:
            tw = draw.textlength(label, font=font)
            draw.text((lx0 + (lx1 - lx0 - tw) / 2, ly0 + 5), label, font=font, fill=white,
                      stroke_width=1, stroke_fill=black)
    for kx0, ky0, kx1, ky1, label in _dsky_key_rects():
        lines = label.split("\n")
        ty = ky0 + (_DSKY_KEY - 12 * len(lines)) / 2
        for line in lines:
            tw = draw.textlength(line, font=font)
            draw.text((kx0 + (_DSKY_KEY - tw) / 2, ty), line, font=font, fill=white, stroke_width=1, stroke_fill=black)
            ty += 12
    small = _dsky_label_font(9)
    ux0, uy0, ux1, uy1 = _DSKY_UNIT_RECT
    label = "DSKY  ·  BLOCK II"
    lx = (ux0 + ux1) / 2 - tracked_width(draw, label, small, tracking=2) / 2
    draw.rectangle((lx - 6, uy1 - 24, lx + tracked_width(draw, label, small, tracking=2) + 6, uy1 - 10), fill=black)
    draw_tracked(draw, (lx, uy1 - 22), label, small, white, tracking=2)


def _dsky_paint_display(image: Image.Image, hour: int, quote_row: dict) -> None:
    """PROG / VERB / NOUN and the three registers as glowing segments; the
    COMP ACTY lamp lit in green."""
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = _DSKY_DISPLAY_RECT
    white, green, black = SPECTRA6["white"], SPECTRA6["green"], SPECTRA6["black"]
    font = _dsky_label_font(10)
    draw.rectangle((x0 + 8, y0 + 8, x0 + 40, y0 + 36), fill=green)
    draw.text((x0 + 10, y0 + 11), "COMP", font=font, fill=black)
    draw.text((x0 + 10, y0 + 22), "ACTY", font=font, fill=black)
    mask = Image.new("L", image.size, 0)
    md = ImageDraw.Draw(mask)
    pair_x = x1 - 8 - 2 * 16
    draw.text((pair_x, y0 + 8), "PROG", font=font, fill=white)
    for i, ch in enumerate(f"{hour:02d}"):
        _dsky_draw_glyph(md, pair_x + i * 16, y0 + 22, ch, h=18, w=11)
    row_y = y0 + 52
    for label, value, lx in (("VERB", _DSKY_VERB, x0 + 8), ("NOUN", _DSKY_NOUN, pair_x)):
        draw.text((lx, row_y), label, font=font, fill=white)
        for i, ch in enumerate(value):
            _dsky_draw_glyph(md, lx + i * 16, row_y + 14, ch, h=18, w=11)
    draw.rectangle((x0 + 8, row_y + 40, x1 - 8, row_y + 40), fill=white)
    reg_y = row_y + 48
    for r, value in enumerate(_dsky_registers(quote_row)):
        y = reg_y + r * 40
        for i, ch in enumerate(value):
            _dsky_draw_glyph(md, x0 + 10 + i * 19, y, ch, h=24, w=13)
        if r < 2:
            draw.rectangle((x0 + 8, y + 32, x1 - 8, y + 32), fill=white)
    paint_neon_mask(image, mask, white, green, radius=4, gamma=1.4, cap=0.6, ground=(black,))
    mask.close()


def _dsky_layout(draw: ImageDraw.ImageDraw, quote_row: dict):
    return _place_quote(draw, quote_row, _DSKY_QUOTE_RECT, theme="dsky",
                        font_max=28, font_min=15, line_height_mult=1.42)


def _dsky_paint_quote(draw: ImageDraw.ImageDraw, placed) -> None:
    """Typed on the card: black, with the matched phrase in red ink."""
    _paint_placed(draw, placed, SPECTRA6["black"], SPECTRA6["red"])


def _dsky_paint_byline(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """Author and title typed under the quote."""
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "").strip()
    parts = [p.upper() for p in (author, title) if p]
    if not parts:
        return
    x0 = _DSKY_QUOTE_RECT[0]
    font, text = fit_text_to_width(draw, "  /  ".join(parts), [SPECIALELITE_REGULAR, *META_FONT_CANDIDATES],
                                   14, _DSKY_QUOTE_RECT[2] - x0, floor=12)
    draw.text((x0, _DSKY_BYLINE_Y), text, font=font, fill=SPECTRA6["black"])


def render_dsky_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The Apollo DSKY on its console, the hour in its PROG register, the
    quote typed on the flight plan beside it (see the section comment above)."""
    hour = _clock_hour12(time_str)
    image = _dsky_scene().copy()
    draw = ImageDraw.Draw(image)
    _dsky_paint_legends(draw)
    _dsky_paint_display(image, hour, quote_row)
    draw = ImageDraw.Draw(image)
    _dsky_paint_quote(draw, _dsky_layout(draw, quote_row))
    _dsky_paint_byline(draw, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("dsky",), render=render_dsky_frame)
