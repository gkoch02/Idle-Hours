"""The ``bladerunner`` theme's frame and the code only it uses.

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .._paths import BARLOWCOND_BOLD, BARLOWCOND_SEMIBOLD, META_FONT_CANDIDATES, SHARETECHMONO_REGULAR
from ..fonts import load_font
from ..furniture import _clock_hour12, _paint_placed, _place_quote, _row_digest, fallback_title
from ..palette import SPECTRA6, SPECTRA6_PALETTE, _dither_calibrated, snap_image_to_palette
from ..primitives import _catmull_rom, _smooth_noise
from ..spec import FrameSpec
from ..text import draw_tracked, fit_text_to_width

# ---------------------------------------------------------------------------
# bladerunner — *Blade Runner 2049* (2017): the LAPD's systems
# ---------------------------------------------------------------------------
# Not the city: the screens K works at. A records terminal in the
# monochrome, hairline manner of the film's interfaces, black glass with
# white rules and type, yellow for what the system has found, red for what
# it wants you to look at. Full design notes: docs/themes.md
# (``bladerunner``).
#
# Four panes. The record holds the quote. The bone scan is the box's
# remains on the light table: a pelvis and the heads of both femurs as an
# X-ray, painted in continuous tone (bright cortical rims over a dimmer
# marrow, a soft scatter, film grain) and Floyd–Steinberg dithered to
# black, blue and white (``_dither_calibrated``), with the serial on the
# iliac crest boxed in red and magnified in an inset. The DNA comparison is
# the twins born 06.10.21, two sequences seeded from the quote and identical
# base for base. The baseline strip is the post-trauma test: twelve words
# of the call-and-response along a flat trace.
#
# The hour is the baseline's prompt: the hour's word is lit yellow and the
# trace spikes above it, pinned across the minutes; the matched phrase
# carries the minute. Composed at 800x480 and NEAREST-downsampled otherwise
# (the ``metro`` convention).
# ---------------------------------------------------------------------------
_BLADERUNNER_SEED = 0x4C415044        # LAPD
_BLADERUNNER_XRAY_INKS = ("black", "blue", "white")
_BLADERUNNER_RECORD = (20, 56, 468, 372)
_BLADERUNNER_QUOTE_RECT = (36, 84, 456, 322)
_BLADERUNNER_BYLINE_Y = 334
_BLADERUNNER_SCAN_RECT = (488, 56, 780, 232)
_BLADERUNNER_SERIAL = "N7FAA52318"
_BLADERUNNER_DNA_RECT = (488, 246, 780, 372)
_BLADERUNNER_BASELINE_RECT = (20, 386, 780, 466)
_BLADERUNNER_TRACE_BAND = (20, 402, 780, 428)
_BLADERUNNER_WORD_BAND = (20, 434, 780, 458)
_BLADERUNNER_WORD_GAP = 4
# The baseline's prompts, from the poem K recites back; the hour's is lit.
_BLADERUNNER_WORDS = ("SYSTEM", "CELLS", "INTERLINKED", "WITHIN", "STEM", "DREADFULLY",
                      "DISTINCT", "AGAINST", "DARK", "TALL", "WHITE", "FOUNTAIN")
_BLADERUNNER_SCENE: dict = {}


def _bladerunner_font(size: int, path: str = BARLOWCOND_SEMIBOLD):
    return load_font([path, *META_FONT_CANDIDATES], size=size)


def _bladerunner_mono(size: int):
    return load_font([SHARETECHMONO_REGULAR, *META_FONT_CANDIDATES], size=size)


def _bladerunner_bone_mask(size) -> Image.Image:
    """The pelvis and the femurs as one ``L`` mask in plate coordinates:
    both ilia flaring out from the sacrum with a joint line between, the
    pubic ring with its two foramina cut out, the femoral heads in their
    sockets, the necks and the shafts running off the foot."""
    w, h = size
    cx = w // 2
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    # The left ilium, a fan: the crest arcs up and out, the wing narrows
    # down to the socket. Mirrored for the right.
    ilium = [(cx - 30, 44), (cx - 46, 22), (cx - 76, 12), (cx - 104, 18), (cx - 120, 34), (cx - 112, 52),
             (cx - 88, 72), (cx - 74, 92), (cx - 60, 100), (cx - 46, 88), (cx - 34, 66)]
    for side in (-1, 1):
        pts = ilium if side < 0 else [(2 * cx - x, y) for x, y in ilium]
        draw.polygon(_catmull_rom(pts, closed=True, samples=8), fill=255)
    # The sacrum, a tapering wedge with the coccyx, clear of the ilia.
    draw.polygon(_catmull_rom([(cx - 22, 30), (cx + 22, 30), (cx + 16, 70), (cx + 6, 96), (cx, 106),
                               (cx - 6, 96), (cx - 16, 70)], closed=True, samples=8), fill=255)
    for side in (-1, 1):
        # The femur: the head in the socket, the neck angling out to the
        # greater trochanter, the shaft running down off the plate.
        hx, hy = cx + side * 66, 104
        draw.ellipse((hx - 13, hy - 13, hx + 13, hy + 13), fill=255)
        tx = hx + side * 30
        draw.line((hx, hy, tx, hy + 14), fill=255, width=14)
        draw.ellipse((tx - 10, hy + 2, tx + 10, hy + 24), fill=255)
        draw.line((tx - side * 4, hy + 14, tx - side * 12, h + 10), fill=255, width=17)
        # The pubic ring below the socket, meeting its twin at the midline.
        draw.polygon(_catmull_rom([(hx - side * 4, hy + 6), (cx + side * 4, hy + 18), (cx + side * 4, hy + 34),
                                   (cx + side * 20, hy + 50), (hx - side * 2, hy + 42), (hx + side * 2, hy + 22)],
                                  closed=True, samples=8), fill=255)
    for side in (-1, 1):
        fx = cx + side * 30
        draw.ellipse((fx - 11, 118, fx + 11, 144), fill=0)
    return mask


def _bladerunner_bone_tone(size) -> Image.Image:
    """The X-ray as luminance: bright cortical rims, a dimmer marrow, a soft
    scatter round the bone, film grain over all."""
    mask = _bladerunner_bone_mask(size)
    rim = ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(5))).filter(ImageFilter.GaussianBlur(1))
    scatter = mask.filter(ImageFilter.GaussianBlur(9)).point(lambda v: v * 34 // 255)
    # Thick bone is denser: the marrow brightens away from the edges, so the
    # wings and the sacrum read as volumes rather than flat cut-outs.
    depth = ImageChops.multiply(mask.filter(ImageFilter.GaussianBlur(7)), mask)
    marrow = depth.point(lambda v: 40 + v * 90 // 255 if v else 0)
    # Trabecular texture in the marrow: blotchy, not flat.
    texture = _smooth_noise(size, (size[0] // 5, size[1] // 5), _BLADERUNNER_SEED + 1).point(lambda v: v * 44 // 255)
    marrow = ImageChops.add(marrow, ImageChops.multiply(texture, mask))
    tone = ImageChops.lighter(ImageChops.lighter(scatter, marrow), rim)
    grain = _smooth_noise(size, (size[0] // 2, size[1] // 2), _BLADERUNNER_SEED + 2).point(lambda v: v * 12 // 255)
    for m in (mask, rim, scatter, marrow, texture, depth):
        m.close()
    return ImageChops.add(tone, grain)


def _bladerunner_paint_xray(image: Image.Image) -> None:
    """The bone scan, dithered from luminance to black, blue and white."""
    x0, y0, x1, y1 = _BLADERUNNER_SCAN_RECT
    size = (x1 - x0 - 1, y1 - y0 - 19)
    tone = _bladerunner_bone_tone(size)
    # Luminance onto the cold light-box ramp: black, through blue, to white.
    blue, white = (35, 63, 142), (185, 199, 201)

    def ramp(v: int, c: int) -> int:
        # Black holds to a tenth so the grain and the scatter stay sparse;
        # the marrow sits in the blue, only the rims reach white.
        t = max(0.0, v / 255 - 0.1) / 0.9
        lo, hi = ((31, 34, 38)[c], blue[c]) if t < 0.5 else (blue[c], white[c])
        f = t / 0.5 if t < 0.5 else (t - 0.5) / 0.5
        return round(lo + (hi - lo) * f)

    rgb = Image.merge("RGB", tuple(tone.point([ramp(v, c) for v in range(256)]) for c in range(3)))
    image.paste(_dither_calibrated(rgb, _BLADERUNNER_XRAY_INKS), (x0 + 1, y0 + 18))
    tone.close()
    rgb.close()


def _bladerunner_scene() -> Image.Image:
    """The black glass and the dithered X-ray. Painted once per process."""
    key = (_bladerunner_paint_xray,)
    cached = _BLADERUNNER_SCENE.get("frame")
    if cached is not None and cached[0] == key:
        return cached[1]
    image = Image.new("RGB", (800, 480), SPECTRA6["black"])
    _bladerunner_paint_xray(image)
    _BLADERUNNER_SCENE["frame"] = (key, image)
    return image


def _bladerunner_brackets(draw: ImageDraw.ImageDraw, rect, fill, arm: int = 8, width: int = 1) -> None:
    x0, y0, x1, y1 = rect
    for (x, y), (dx, dy) in (((x0, y0), (1, 1)), ((x1, y0), (-1, 1)), ((x0, y1), (1, -1)), ((x1, y1), (-1, -1))):
        draw.line((x, y, x + arm * dx, y), fill=fill, width=width)
        draw.line((x, y, x, y + arm * dy), fill=fill, width=width)


def _bladerunner_label(draw: ImageDraw.ImageDraw, xy, text: str, *, fill=None, size: int = 12,
                       anchor_right: bool = False) -> float:
    return draw_tracked(draw, xy, text, _bladerunner_font(size), fill or SPECTRA6["white"], tracking=2,
                        anchor_right=anchor_right)


def _bladerunner_paint_header(draw: ImageDraw.ImageDraw) -> None:
    """The LAPD block, the division, the officer, and a ticked rule."""
    white, black, red = SPECTRA6["white"], SPECTRA6["black"], SPECTRA6["red"]
    draw.rectangle((20, 14, 72, 36), fill=white)
    draw_tracked(draw, (27, 15), "LAPD", _bladerunner_font(17, BARLOWCOND_BOLD), black, tracking=3)
    draw_tracked(draw, (84, 17), "RECORDS DIVISION  ·  DNA ARCHIVE  ·  REPLICANT DETECTION",
                 _bladerunner_font(14), white, tracking=3)
    right = draw_tracked(draw, (780, 17), "OFFICER  KD6-3.7", _bladerunner_font(14), white, tracking=3,
                         anchor_right=True)
    rx = round(780 - right - 16)
    draw.ellipse((rx - 3, 22, rx + 5, 30), fill=red)
    draw.line((20, 44, 780, 44), fill=white, width=1)
    for x in range(20, 781, 20):
        draw.line((x, 44, x, 47 if x % 100 else 50), fill=white, width=1)


def _bladerunner_paint_record(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The record pane's furniture: its file line, brackets and the yellow
    gutter bar beside the text."""
    white, yellow = SPECTRA6["white"], SPECTRA6["yellow"]
    x0, y0, x1, y1 = _BLADERUNNER_RECORD
    _bladerunner_brackets(draw, (x0, y0, x1, y1), white)
    source = str(quote_row.get("source_id") or "0")
    line = str(quote_row.get("line_number") or "0")
    _bladerunner_label(draw, (x0 + 16, y0 + 6), f"RECORD  {source.zfill(6)[-6:]}", size=13)
    _bladerunner_label(draw, (x1 - 16, y0 + 6), f"LN {line.zfill(5)[-5:]}  ·  TEXT", size=13, anchor_right=True)
    draw.line((x0 + 16, y0 + 22, x1 - 16, y0 + 22), fill=white, width=1)
    qx0, qy0, _, qy1 = _BLADERUNNER_QUOTE_RECT
    draw.rectangle((x0 + 4, qy0 + 2, x0 + 6, qy1 - 2), fill=yellow)
    draw.line((x0 + 16, _BLADERUNNER_BYLINE_Y - 6, x1 - 16, _BLADERUNNER_BYLINE_Y - 6), fill=white, width=1)


def _bladerunner_paint_scan(draw: ImageDraw.ImageDraw) -> None:
    """The bone scan's frame, label and the red zoom on the serial."""
    white, red, black = SPECTRA6["white"], SPECTRA6["red"], SPECTRA6["black"]
    x0, y0, x1, y1 = _BLADERUNNER_SCAN_RECT
    draw.rectangle((x0, y0, x1, y1), outline=white, width=1)
    draw.rectangle((x0, y0, x1, y0 + 17), fill=white)
    draw_tracked(draw, (x0 + 6, y0 + 2), "OSTEO SCAN  ·  SAMPLE 27", _bladerunner_font(12), black, tracking=2)
    draw_tracked(draw, (x1 - 6, y0 + 2), "ENH 4.0", _bladerunner_font(12), black, tracking=2, anchor_right=True)
    # The serial lies along the left iliac crest; box it and magnify it.
    cx = x0 + 1 + (x1 - x0 - 1) // 2
    bx, by = cx - 104, y0 + 18 + 30
    box = (bx - 4, by - 6, bx + 30, by + 8)
    draw.rectangle(box, outline=red, width=2)
    mono = _bladerunner_mono(6)
    draw.text((bx - 1, by - 4), _BLADERUNNER_SERIAL[:5], font=mono, fill=white)
    inset = (x1 - 118, y1 - 40, x1 - 8, y1 - 10)
    draw.rectangle(inset, fill=black, outline=red, width=2)
    draw.line((box[2], box[3], inset[0], inset[1]), fill=red, width=1)
    font = _bladerunner_mono(16)
    tw = draw.textlength(_BLADERUNNER_SERIAL, font=font)
    draw.text(((inset[0] + inset[2] - tw) / 2, inset[1] + 6), _BLADERUNNER_SERIAL, font=font, fill=white)


def _bladerunner_sequence(quote_row: dict, count: int) -> str:
    rng = random.Random(_BLADERUNNER_SEED ^ _row_digest(quote_row))
    return "".join(rng.choice("ACGT") for _ in range(count))


def _bladerunner_paint_dna(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    """The twins' DNA, side by side: two subjects born 06.10.21, one male,
    one female, and the same sequence base for base, with a tick for every
    match between them and IDENTICAL in yellow."""
    white, yellow, black = SPECTRA6["white"], SPECTRA6["yellow"], SPECTRA6["black"]
    x0, y0, x1, y1 = _BLADERUNNER_DNA_RECT
    _bladerunner_brackets(draw, (x0, y0, x1, y1), white)
    _bladerunner_label(draw, (x0 + 8, y0 + 5), "DNA  ·  SEQUENCE COMPARISON", size=12)
    tag = "IDENTICAL"
    font = _bladerunner_font(12, BARLOWCOND_BOLD)
    tw = draw_tracked(draw, (0, -100), tag, font, black, tracking=2)
    draw.rectangle((x1 - 14 - tw, y0 + 4, x1 - 6, y0 + 19), fill=yellow)
    draw_tracked(draw, (x1 - 10, y0 + 5), tag, font, black, tracking=2, anchor_right=True)
    mono = _bladerunner_mono(12)
    advance = draw.textlength("A", font=mono) + 2
    count = int((x1 - x0 - 20) // advance)
    seq = _bladerunner_sequence(quote_row, count * 2)
    for subject, (sy, sex) in enumerate(((y0 + 26, "M"), (y0 + 76, "F"))):
        _bladerunner_label(draw, (x0 + 10, sy), f"SUBJ {subject + 1:02d}   DOB 06.10.21   SEX {sex}", size=11)
        for row in range(2):
            for i in range(count):
                base = seq[row * count + i]
                draw.text((x0 + 10 + i * advance, sy + 13 + row * 13), base, font=mono,
                          fill=yellow if base == "G" and (i + row) % 5 == 0 else white)
    for i in range(count):
        mx = x0 + 10 + i * advance + advance / 2 - 1
        draw.line((mx, y0 + 68, mx, y0 + 72), fill=yellow, width=1)


def _bladerunner_word_rects() -> list:
    x0, y0, x1, y1 = _BLADERUNNER_WORD_BAND
    width = (x1 - x0 - 11 * _BLADERUNNER_WORD_GAP) / 12
    return [(round(x0 + i * (width + _BLADERUNNER_WORD_GAP)), y0,
             round(x0 + i * (width + _BLADERUNNER_WORD_GAP) + width), y1) for i in range(12)]


def _bladerunner_paint_baseline(draw: ImageDraw.ImageDraw, hour: int) -> None:
    """The baseline test: its label, a flat trace that spikes above the
    hour's prompt, and the twelve prompts with the hour's lit."""
    white, yellow, black, red = SPECTRA6["white"], SPECTRA6["yellow"], SPECTRA6["black"], SPECTRA6["red"]
    x0, y0, x1, y1 = _BLADERUNNER_BASELINE_RECT
    _bladerunner_label(draw, (x0, y0), "BASELINE  ·  POST-TRAUMA", size=12)
    _bladerunner_label(draw, (x1, y0), "WITHIN TOLERANCE", size=12, anchor_right=True)
    rects = _bladerunner_word_rects()
    tx0, ty0, tx1, ty1 = _BLADERUNNER_TRACE_BAND
    mid = (ty0 + ty1) // 2
    rng = random.Random(_BLADERUNNER_SEED + 3)
    ax0, _, ax1, _ = rects[hour - 1]
    centre = (ax0 + ax1) / 2
    points = []
    for x in range(tx0, tx1 + 1, 2):
        d = abs(x - centre)
        spike = 0.0 if d > 14 else (1 - d / 14) * (11 if (x // 2) % 2 else -9)
        points.append((x, mid + rng.uniform(-1.2, 1.2) + spike))
    for x in range(tx0, tx1 + 1, 10):
        draw.point((x, mid), fill=white)
    draw.line(points, fill=white, width=1)
    draw.line((centre, ty0 - 2, centre, ty1 + 2), fill=red, width=1)
    font, small = _bladerunner_font(12), _bladerunner_font(10)
    for i, (wx0, wy0, wx1, wy1) in enumerate(rects):
        active = i + 1 == hour
        draw.rectangle((wx0, wy0, wx1, wy1), fill=yellow if active else black, outline=yellow if active else white)
        word = _BLADERUNNER_WORDS[i]
        face = font if draw.textlength(word, font=font) <= wx1 - wx0 - 8 else small
        width = draw.textlength(word, font=face)
        draw.text((wx0 + (wx1 - wx0 - width) / 2, wy0 + (4 if face is font else 5)), word, font=face,
                  fill=black if active else white)


def _bladerunner_layout(draw: ImageDraw.ImageDraw, quote_row: dict):
    return _place_quote(draw, quote_row, _BLADERUNNER_QUOTE_RECT, theme="bladerunner",
                        font_max=36, font_min=18, line_height_mult=1.24)


def _bladerunner_paint_byline(draw: ImageDraw.ImageDraw, quote_row: dict) -> None:
    author = (quote_row.get("author") or "").strip()
    title = (quote_row.get("title") or "").strip() or (fallback_title(quote_row) or "").strip()
    parts = [p.upper() for p in (author, title) if p]
    if not parts:
        return
    x0, _, x1, _ = _BLADERUNNER_QUOTE_RECT
    font, text = fit_text_to_width(draw, "  ·  ".join(parts), [BARLOWCOND_SEMIBOLD, *META_FONT_CANDIDATES],
                                   16, x1 - x0, floor=13, tracking=2)
    draw_tracked(draw, (x0, _BLADERUNNER_BYLINE_Y), text, font, SPECTRA6["yellow"], tracking=2)


def render_bladerunner_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """The LAPD records terminal (see the section comment above)."""
    hour = _clock_hour12(time_str)
    image = _bladerunner_scene().copy()
    draw = ImageDraw.Draw(image)
    _bladerunner_paint_header(draw)
    _bladerunner_paint_record(draw, quote_row)
    _paint_placed(draw, _bladerunner_layout(draw, quote_row), SPECTRA6["white"], SPECTRA6["yellow"])
    _bladerunner_paint_byline(draw, quote_row)
    _bladerunner_paint_scan(draw)
    _bladerunner_paint_dna(draw, quote_row)
    _bladerunner_paint_baseline(draw, hour)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image


SPEC = FrameSpec(themes=("bladerunner",), render=render_bladerunner_frame)
