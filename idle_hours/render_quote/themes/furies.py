"""The ``furies`` theme's frame and the code only it uses (issue #335).

Design notes: ``docs/themes.md``.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .._paths import LIBREFRANKLIN_ITALIC_VARIABLE, META_FONT_CANDIDATES
from ..fonts import load_font
from ..furniture import draw_truncated_centred_byline
from ..palette import SPECTRA6, SPECTRA6_PALETTE, BAYER_8x8, dither_image_to_palette, snap_image_to_palette
from ..primitives import (
    _bayer_threshold_field,
    _catmull_rom,
    _shade_silhouette,
    _shift_no_wrap,
    _white_noise,
    position_noise,
    wrap_quote_into_masks,
)

# ---------------------------------------------------------------------------
# furies — Francis Bacon, *Three Studies for Figures at the Base of a
# Crucifixion* (1944)
# ---------------------------------------------------------------------------
# The triptych hung under glass in gilt frames on a dark gallery wall, with
# the quote beneath it as wall text:
#
# * **Left.** A hunched, draped figure on a table, its head bowed under a
#   hanging mass of dark hair.
# * **Centre.** A long-necked figure on a pedestal, eyes bound by a white
#   bandage, the lower face opened into a mouth of teeth.
# * **Right.** A body on stalk legs rooted in a tuft of grass, its neck
#   stretched horizontal to end in a screaming mouth.
#
# All three stand on flat cadmium orange with a few thin perspective lines.
#
# **The painting is built in memory as separate paint layers** (ground, lines,
# flesh, pedestal, grass), each with its own soft alpha, then:
#
# 1. **Dragged.** ``_furies_drag`` pulls each figure along a vector in fading,
#    striated steps (noise held constant *along* the drag, like bristles), so
#    the trail reads as a smear, not a motion blur; the core is carried at
#    partial strength so the form itself is smeared.
# 2. **Separated per layer against its own inks** (Floyd–Steinberg): ground
#    red/yellow, flesh white/black/red, grass green/yellow/black. One pass over
#    the flattened image would scatter green into grey flesh and white into
#    the orange.
# 3. **Composited through a dithered alpha** (``BAYER_8x8`` threshold, not a
#    50% cut), so smeared edges interpenetrate instead of reading as stickers.
#
# Flesh is modelled under an upper-left light (``_shade_silhouette``) and given
# brush marks before the drag so they smear with it. Mouths and the bandage are
# painted *after* the drag — the focal points stay sharp.
#
# Each panel sits in a bevelled gilt moulding, and one diagonal window
# reflection crosses all three panes as a sparse white stipple.
#
# **The matched phrase is the scream**: wall text in white Libre Franklin, the
# phrase in yellow-major orange (``_FURIES_PHRASE_RED_RANKS``) with a red smear
# dragged off it. The trail is written only onto the black wall, so it never
# cuts a prose glyph.
#
# ``time_str`` is ``del``-asserted (a painting carries no clock). The triptych
# is quote-independent and deterministic, so it is composed once and cached.
#
# Composed at the canonical 800x480 and NEAREST-downsampled for other sizes
# (``metro`` convention).
# ---------------------------------------------------------------------------
_FURIES_PANEL_W, _FURIES_PANEL_H = 212, 268
_FURIES_PANEL_Y = 24
_FURIES_PANEL_XS = (60, 294, 528)
_FURIES_FRAME = 8                          # gilt moulding width
_FURIES_QUOTE_RECT = (44, 318, 756, 440)
_FURIES_BYLINE_BASELINE = 464

_FURIES_ORANGE = (238, 116, 20)
_FURIES_FLESH = (170, 164, 166)
_FURIES_FLESH_LIGHT = (250, 246, 240)
_FURIES_FLESH_SHADOW = (48, 38, 42)
_FURIES_LINE = (104, 34, 14)               # the thin perspective lines, R+K
_FURIES_HAIR = (38, 28, 28)
_FURIES_MAW = (76, 12, 12)
_FURIES_THROAT = (18, 0, 0)
_FURIES_TOOTH = (252, 252, 250)

# The ground separates against red + yellow only: with black available, FS
# drops black specks into the deeper scumble and the orange goes olive. The
# perspective lines, which need black, are their own R+K layer.
_FURIES_GROUND_INKS = [SPECTRA6["red"], SPECTRA6["yellow"]]
_FURIES_LINE_INKS = [SPECTRA6["red"], SPECTRA6["black"]]
_FURIES_FLESH_INKS = [SPECTRA6["white"], SPECTRA6["black"], SPECTRA6["red"]]
_FURIES_GRASS_INKS = [SPECTRA6["green"], SPECTRA6["yellow"], SPECTRA6["black"]]

# The window reflection, as (intercept, half-width, peak density) of bands
# along y + slope * x = intercept — one shallow diagonal across all three panes.
_FURIES_GLARE_SLOPE = 0.28
_FURIES_GLARE = ((252, 9, 0.16), (290, 24, 0.07))

# The matched phrase's orange: ranks of 64 given to red (the rest yellow);
# 24/64 reads as cadmium on black where an even mix goes rust. Then the smear's
# density relative to its own alpha.
_FURIES_PHRASE_RED_RANKS = 24
_FURIES_SMEAR_STRENGTH = 0.7

_FURIES_TRIPTYCH_CACHE: dict = {}


def _furies_tube(draw: ImageDraw.ImageDraw, points, w0: float, w1: float, fill=255) -> None:
    """A neck or a limb: a spline swept at a width tapering ``w0`` → ``w1``."""
    path = _catmull_rom(points, closed=False, samples=8)
    left, right = [], []
    last = len(path) - 1
    for i, (x, y) in enumerate(path):
        ax, ay = path[max(i - 1, 0)]
        bx, by = path[min(i + 1, last)]
        length = math.hypot(bx - ax, by - ay) or 1.0
        nx, ny = (ay - by) / length, (bx - ax) / length
        half = (w0 + (w1 - w0) * i / last) / 2
        left.append((x + nx * half, y + ny * half))
        right.append((x - nx * half, y - ny * half))
    draw.polygon(left + right[::-1], fill=fill)


def _furies_dithered_alpha(alpha: Image.Image) -> Image.Image:
    """A soft alpha thresholded against the ordered tile: a smeared edge
    becomes a stippled interpenetration of the two layers, not a hard cut."""
    return ImageChops.subtract(alpha, _bayer_threshold_field(alpha.size)).point(lambda v: 255 if v else 0)


def _furies_noise(size, seed: int, scale: int, amp: float) -> Image.Image:
    """Low-frequency value noise centred on 128 — a tiny seeded grid upscaled
    BICUBIC, so the ground's scumble is C-speed and byte-deterministic."""
    rng = random.Random(seed)
    gw, gh = size[0] // scale + 2, size[1] // scale + 2
    small = Image.new("L", (gw, gh))
    small.putdata([int(128 + rng.uniform(-amp, amp)) for _ in range(gw * gh)])
    return small.resize(size, Image.BICUBIC)


def _furies_striations(size, angle: float, seed: int) -> Image.Image:
    """Bristle rows for a drag along ``angle``: noise held constant along the
    drag direction and stepping across it, like the hairs of a loaded brush."""
    rng = random.Random(seed)
    n = int(math.hypot(*size)) + 4
    values, v = [], rng.uniform(90, 255)
    for _ in range(n):
        if rng.random() < 0.35:
            v = rng.uniform(90, 255)
        values.append(int(v))
    column = Image.new("L", (1, n))
    column.putdata(values)
    square = column.resize((n, n), Image.NEAREST).rotate(-math.degrees(angle), resample=Image.NEAREST)
    left, top = (n - size[0]) // 2, (n - size[1]) // 2
    return square.crop((left, top, left + size[0], top + size[1]))


def _furies_drag(rgb: Image.Image, alpha: Image.Image, dx: int, dy: int, *, steps: int,
                 decay: float, seed: int, keep: float = 0.9) -> tuple[Image.Image, Image.Image]:
    """Drag wet paint along ``(dx, dy)``.

    Walks from the far end of the trail back to the figure, pasting shifted
    copies whose alpha fades by ``decay`` per step, modulated by the bristle
    striations. The figure goes down last at ``keep`` strength so the trail
    shows through it. Returns the new colour layer and alpha.
    """
    striations = _furies_striations(rgb.size, math.atan2(dy, dx), seed)
    out_rgb = Image.new("RGB", rgb.size, (0, 0, 0))
    out_alpha = Image.new("L", rgb.size, 0)
    for i in range(steps, 0, -1):
        weight = decay ** i
        sx, sy = round(dx * i / steps), round(dy * i / steps)
        step_alpha = ImageChops.multiply(
            _shift_no_wrap(alpha, sx, sy).point(lambda v, w=weight: int(v * w)), striations)
        out_rgb.paste(_shift_no_wrap(rgb, sx, sy), (0, 0), step_alpha)
        out_alpha = ImageChops.lighter(out_alpha, step_alpha)
    core = alpha.point(lambda v: int(v * keep))
    out_rgb.paste(rgb, (0, 0), core)
    return out_rgb, ImageChops.lighter(out_alpha, core)


def _furies_brushwork(rgb: Image.Image, mask: Image.Image, seed: int, *, count: int = 26,
                      direction: float = 0.0) -> None:
    """Curved brush marks inside a silhouette — light and dark greys and a
    few pink scumbles swept roughly along ``direction``. Painted before the
    drag so the marks smear with the flesh; the silhouette's alpha clips them."""
    box = mask.getbbox()
    if box is None:
        return
    rng = random.Random(seed)
    draw = ImageDraw.Draw(rgb)
    x0, y0, x1, y1 = box
    tones = ((236, 232, 228), (214, 208, 208), (128, 116, 120), (96, 84, 88), (206, 150, 150))
    for i in range(count):
        cx, cy = rng.uniform(x0, x1 - 1), rng.uniform(y0, y1 - 1)
        angle = direction + rng.uniform(-0.9, 0.9)
        length, bend = rng.uniform(14, 34), rng.uniform(-8, 8)
        width = rng.choice((2, 3, 4))
        if not mask.getpixel((int(cx), int(cy))):
            continue
        ux, uy = math.cos(angle) * length / 2, math.sin(angle) * length / 2
        stroke = [(cx - ux, cy - uy), (cx - math.sin(angle) * bend, cy + math.cos(angle) * bend),
                  (cx + ux, cy + uy)]
        draw.line(_catmull_rom(stroke, closed=False), fill=tones[i % len(tones)], width=width)


def _furies_ground(seed: int) -> Image.Image:
    """Cadmium orange on the rough side of the board: a scumble of warmer and
    deeper patches, and a vignette that browns toward the edges."""
    size = (_FURIES_PANEL_W, _FURIES_PANEL_H)
    img = Image.new("RGB", size, _FURIES_ORANGE)
    noise = _furies_noise(size, seed, 24, 24)
    img = Image.composite(Image.new("RGB", size, (246, 140, 28)), img,
                          noise.point(lambda v: max(0, v - 128) * 2))
    img = Image.composite(Image.new("RGB", size, (220, 88, 14)), img,
                          noise.point(lambda v: max(0, 128 - v) * 2))
    vignette = Image.new("L", size, 0)
    vd = ImageDraw.Draw(vignette)
    for i in range(36):
        vd.rectangle((i, i, size[0] - 1 - i, size[1] - 1 - i), outline=int(80 * (1 - i / 36) ** 2))
    img = Image.composite(Image.new("RGB", size, (180, 56, 12)), img, vignette)
    # Board grain: FS over a flat colour settles into vertical worms; a seeded
    # per-pixel jitter (``randbytes``; ``effect_noise`` is unseeded) breaks them.
    grain = _white_noise(size[0], size[1], seed * 7919)
    img = Image.composite(Image.new("RGB", size, (255, 160, 40)), img, grain.point(lambda v: max(0, v - 200)))
    return Image.composite(Image.new("RGB", size, (236, 84, 12)), img, grain.point(lambda v: max(0, 55 - v)))


def _furies_teeth(draw: ImageDraw.ImageDraw, x0: int, x1: int, y: int, step: int, down: bool) -> None:
    """A row of small triangular teeth hanging from (or rising to) ``y``."""
    depth = 5 if down else -4
    for tx in range(x0, x1, step):
        draw.polygon([(tx, y), (tx + step - 1, y), (tx + (step - 1) // 2, y + depth)], fill=_FURIES_TOOTH)


def _furies_ink(colour) -> Image.Image:
    """A flat continuous-tone colour at panel size — a layer's paint when its
    shape lives entirely in its alpha."""
    return Image.new("RGB", (_FURIES_PANEL_W, _FURIES_PANEL_H), colour)


def _furies_layer() -> Image.Image:
    return Image.new("L", (_FURIES_PANEL_W, _FURIES_PANEL_H), 0)


def _furies_left_panel() -> list:
    """The hunched, draped figure on a table, hair hanging over its face."""
    ground = _furies_ground(11)
    lines = _furies_layer()
    d = ImageDraw.Draw(lines)
    d.line((0, 206, _FURIES_PANEL_W, 198), fill=255, width=1)          # floor
    d.line((36, 176, 176, 176), fill=255, width=2)                      # table front
    d.line((56, 166, 194, 166), fill=255, width=1)                      # table back
    d.line((36, 176, 56, 166), fill=255, width=1)
    d.line((176, 176, 194, 166), fill=255, width=1)
    for x, top, bottom in ((44, 177, 250), (170, 177, 250), (190, 167, 236)):
        d.line((x, top, x, bottom), fill=255, width=2)
    mask = _furies_layer()
    md = ImageDraw.Draw(mask)
    md.polygon(_catmull_rom([(50, 176), (52, 140), (66, 108), (92, 86), (114, 90), (126, 78),
                               (150, 86), (166, 108), (170, 140), (176, 176)]), fill=255)
    md.polygon(_catmull_rom([(140, 112), (166, 104), (184, 124), (182, 150), (164, 160),
                               (144, 146)]), fill=255)
    _furies_tube(md, [(128, 128), (138, 152), (136, 176)], 14, 9)
    flesh = _shade_silhouette(mask, _FURIES_FLESH, _FURIES_FLESH_LIGHT, _FURIES_FLESH_SHADOW)
    _furies_brushwork(flesh, mask, 41, direction=-0.5)
    fd = ImageDraw.Draw(flesh)
    fd.polygon(_catmull_rom([(142, 110), (166, 102), (186, 122), (184, 160), (176, 176),
                               (168, 150), (160, 164), (156, 136), (146, 130)]), fill=_FURIES_HAIR)
    fd.line(_catmull_rom([(66, 150), (92, 118), (124, 104), (150, 108)], closed=False),
            fill=(118, 100, 104), width=2)
    fd.line(_catmull_rom([(110, 176), (116, 150), (134, 132)], closed=False), fill=(120, 104, 108), width=2)
    flesh, alpha = _furies_drag(flesh, mask, 10, 6, steps=8, decay=0.8, seed=21)
    return [(ground, None, _FURIES_GROUND_INKS), (_furies_ink(_FURIES_LINE), lines, _FURIES_LINE_INKS),
            (flesh, alpha, _FURIES_FLESH_INKS)]


def _furies_centre_panel() -> list:
    """The bandaged figure on its pedestal, the lower face opened into teeth."""
    ground = _furies_ground(12)
    lines = _furies_layer()
    d = ImageDraw.Draw(lines)
    d.line((0, 210, _FURIES_PANEL_W, 204), fill=255, width=1)
    d.line((0, 40, 60, 90), fill=255, width=1)
    d.line((_FURIES_PANEL_W, 36, 156, 88), fill=255, width=1)
    pedestal = _furies_layer()
    pd = ImageDraw.Draw(pedestal)
    pd.rectangle((84, 190, 132, 248), fill=255)
    pd.ellipse((84, 184, 132, 196), fill=255)
    pd.ellipse((84, 242, 132, 254), fill=255)
    stone = _shade_silhouette(pedestal, (70, 58, 56), (140, 120, 110), (20, 14, 14))
    mask = _furies_layer()
    md = ImageDraw.Draw(mask)
    md.polygon(_catmull_rom([(70, 190), (64, 160), (74, 128), (100, 118), (128, 128), (140, 158),
                               (134, 190)]), fill=255)
    _furies_tube(md, [(106, 132), (100, 104), (112, 80), (136, 74)], 30, 22)
    md.polygon(_catmull_rom([(122, 72), (148, 58), (176, 70), (180, 98), (168, 118), (140, 122),
                               (124, 104)]), fill=255)
    flesh = _shade_silhouette(mask, _FURIES_FLESH, _FURIES_FLESH_LIGHT, _FURIES_FLESH_SHADOW)
    _furies_brushwork(flesh, mask, 42, direction=1.2)
    fd = ImageDraw.Draw(flesh)
    fd.line(_catmull_rom([(78, 150), (96, 176), (126, 170)], closed=False), fill=(120, 104, 108), width=2)
    fd.line(_catmull_rom([(92, 126), (110, 140), (128, 136)], closed=False), fill=(130, 114, 118), width=1)
    flesh, alpha = _furies_drag(flesh, mask, -8, 10, steps=7, decay=0.8, seed=22)
    # The bandage and the mouth go down after the drag: the focal points.
    fd, ad = ImageDraw.Draw(flesh), ImageDraw.Draw(alpha)
    bandage = [(118, 70), (178, 76), (178, 90), (118, 86)]
    fd.polygon(bandage, fill=(248, 246, 244))
    ad.polygon(bandage, fill=255)
    fd.line((124, 78, 172, 83), fill=(170, 160, 160), width=1)
    fd.ellipse((132, 94, 170, 116), fill=_FURIES_MAW)
    fd.ellipse((140, 100, 162, 114), fill=_FURIES_THROAT)
    _furies_teeth(fd, 136, 168, 96, 4, down=True)
    _furies_teeth(fd, 140, 162, 115, 4, down=False)
    return [(ground, None, _FURIES_GROUND_INKS), (_furies_ink(_FURIES_LINE), lines, _FURIES_LINE_INKS),
            (stone, pedestal, _FURIES_FLESH_INKS),
            (flesh, alpha, _FURIES_FLESH_INKS)]


def _furies_right_panel() -> list:
    """The stalk-legged body in its tuft of grass, neck out, mouth screaming."""
    ground = _furies_ground(13)
    lines = _furies_layer()
    d = ImageDraw.Draw(lines)
    d.line((0, 196, _FURIES_PANEL_W, 206), fill=255, width=1)
    d.line((150, 0, 150, 60), fill=255, width=1)
    grass = _furies_layer()
    gd = ImageDraw.Draw(grass)
    blades = Image.new("RGB", grass.size, (40, 140, 40))
    bd = ImageDraw.Draw(blades)
    rng = random.Random(31)
    gd.ellipse((110, 214, 206, 244), fill=255)
    for _ in range(70):
        x, h, lean = rng.uniform(112, 204), rng.uniform(8, 26), rng.uniform(-6, 6)
        gd.line((x, 232, x + lean, 232 - h), fill=255, width=2)
        bd.line((x, 232, x + lean, 232 - h), fill=(90, 190, 40), width=1)
    mask = _furies_layer()
    md = ImageDraw.Draw(mask)
    md.polygon(_catmull_rom([(122, 128), (146, 104), (182, 106), (198, 136), (190, 170), (160, 180),
                               (130, 164)]), fill=255)
    _furies_tube(md, [(136, 140), (104, 128), (78, 122), (58, 118)], 30, 22)
    md.polygon(_catmull_rom([(18, 104), (40, 86), (68, 92), (76, 118), (66, 146), (34, 150),
                               (14, 132)]), fill=255)
    _furies_tube(md, [(146, 170), (142, 196), (146, 228)], 9, 4)
    _furies_tube(md, [(176, 172), (180, 200), (176, 228)], 9, 4)
    flesh = _shade_silhouette(mask, _FURIES_FLESH, _FURIES_FLESH_LIGHT, _FURIES_FLESH_SHADOW)
    _furies_brushwork(flesh, mask, 43, direction=0.2)
    flesh, alpha = _furies_drag(flesh, mask, 12, -4, steps=8, decay=0.8, seed=23)
    fd, ad = ImageDraw.Draw(flesh), ImageDraw.Draw(alpha)
    fd.ellipse((10, 104, 58, 144), fill=_FURIES_MAW)      # the scream opens the whole face
    ad.ellipse((10, 104, 58, 144), fill=255)
    fd.ellipse((18, 112, 50, 138), fill=_FURIES_THROAT)
    _furies_teeth(fd, 16, 52, 106, 5, down=True)
    _furies_teeth(fd, 20, 48, 142, 5, down=False)
    return [(ground, None, _FURIES_GROUND_INKS), (_furies_ink(_FURIES_LINE), lines, _FURIES_LINE_INKS),
            (blades, grass, _FURIES_GRASS_INKS),
            (flesh, alpha, _FURIES_FLESH_INKS)]


def _furies_compose_panel(layers: list) -> Image.Image:
    """Separate each paint layer against its own inks, then stack them through
    their dithered alphas. The first layer is the ground and has no alpha."""
    out = None
    for rgb, alpha, inks in layers:
        separated = dither_image_to_palette(rgb, inks)
        out = separated if alpha is None else Image.composite(separated, out, _furies_dithered_alpha(alpha))
    return out


def _furies_triptych() -> list:
    """The three separated panels, composed once per process."""
    cached = _FURIES_TRIPTYCH_CACHE.get("panels")
    if cached is None:
        cached = [_furies_compose_panel(build()) for build in
                  (_furies_left_panel, _furies_centre_panel, _furies_right_panel)]
        _FURIES_TRIPTYCH_CACHE["panels"] = cached
    return cached


def _furies_paint_triptych(image: Image.Image) -> None:
    for x, panel in zip(_FURIES_PANEL_XS, _furies_triptych()):
        image.paste(panel, (x, _FURIES_PANEL_Y))


def _furies_paint_frames(image: Image.Image) -> None:
    """Bevelled gilt mouldings: gold (Y-major Y+R) on the flat, a Y+W lit face
    on the top and left, an R+K shaded face on the bottom and right, and a
    black rebate where the moulding meets the board."""
    px = image.load()
    red, yellow, white, black = (SPECTRA6[k] for k in ("red", "yellow", "white", "black"))
    f = _FURIES_FRAME
    for x0 in _FURIES_PANEL_XS:
        y0 = _FURIES_PANEL_Y
        x1, y1 = x0 + _FURIES_PANEL_W, y0 + _FURIES_PANEL_H
        for y in range(y0 - f, y1 + f):
            row = BAYER_8x8[y & 7]
            for x in range(x0 - f, x1 + f):
                if x0 <= x < x1 and y0 <= y < y1:
                    continue
                inset = min(x - (x0 - f), y - (y0 - f), (x1 + f - 1) - x, (y1 + f - 1) - y)
                rank = row[x & 7]
                if inset == f - 1:
                    ink = black                                   # the rebate
                elif inset <= 1 and (x - (x0 - f) == inset or y - (y0 - f) == inset):
                    ink = white if rank < 28 else yellow          # lit face
                elif inset <= 1:
                    ink = black if rank < 28 else red             # shaded face
                else:
                    ink = red if rank < 12 else yellow            # gold flat
                px[x, y] = ink


def _furies_paint_glass(image: Image.Image) -> None:
    """The window reflection on the glazing: sparse white along diagonal bands,
    one reflection continuous across all three panes, on the paint only."""
    px = image.load()
    white = SPECTRA6["white"]
    y0, y1 = _FURIES_PANEL_Y, _FURIES_PANEL_Y + _FURIES_PANEL_H
    for x0 in _FURIES_PANEL_XS:
        for y in range(y0, y1):
            for x in range(x0, x0 + _FURIES_PANEL_W):
                u = y + _FURIES_GLARE_SLOPE * x
                for centre, half, peak in _FURIES_GLARE:
                    d = abs(u - centre)
                    if d < half and position_noise(x, y) < 255 * peak * (1 - d / half):
                        px[x, y] = white
                        break


def _furies_paint_quote(image: Image.Image, quote_row: dict) -> None:
    """Wall text in white, and the matched phrase in the painting's orange
    with a red smear dragged off it — written only onto the black wall."""
    draw = ImageDraw.Draw(image)
    prose, hot, _ = wrap_quote_into_masks(draw, image.size, quote_row, _FURIES_QUOTE_RECT,
                                          theme="furies", font_max=30, font_min=15,
                                          line_height_mult=1.3)
    black, red, yellow = SPECTRA6["black"], SPECTRA6["red"], SPECTRA6["yellow"]
    solid_prose = prose.point(lambda v: 255 if v >= 128 else 0)
    image.paste(SPECTRA6["white"], (0, 0), solid_prose)
    box = hot.getbbox()
    if box is None:
        return
    x0, y0, x1, y1 = box
    trail_box = (x0, y0, min(image.width, x1 + 11), min(image.height, y1 + 9))
    _, smear = _furies_drag(Image.new("RGB", image.size), hot, 9, 7, steps=9, decay=0.8,
                            seed=51, keep=0.0)
    # The smear keeps a two-pixel berth round every glyph of the phrase, so it
    # never fills a counter or bridges two letters.
    berth = hot.filter(ImageFilter.MaxFilter(5))
    smear_px, hot_px, berth_px, px = smear.load(), hot.load(), berth.load(), image.load()
    for y in range(trail_box[1], trail_box[3]):
        row = BAYER_8x8[y & 7]
        for x in range(trail_box[0], trail_box[2]):
            if hot_px[x, y] >= 128:
                # Cadmium orange, yellow-leaning so it holds on the black wall.
                px[x, y] = red if row[x & 7] < _FURIES_PHRASE_RED_RANKS else yellow
            elif (px[x, y] == black and berth_px[x, y] < 128
                  and smear_px[x, y] * _FURIES_SMEAR_STRENGTH > row[x & 7] * 4 + 2):
                px[x, y] = red


def _furies_paint_byline(image: Image.Image, quote_row: dict) -> None:
    draw = ImageDraw.Draw(image)
    font = load_font([(LIBREFRANKLIN_ITALIC_VARIABLE, "Medium Italic"), *META_FONT_CANDIDATES], size=14)
    draw_truncated_centred_byline(draw, quote_row, centre=image.width // 2,
                                  baseline=_FURIES_BYLINE_BASELINE, max_width=image.width - 96,
                                  font=font, fill=SPECTRA6["white"])


def render_furies_frame(time_str: str, quote_row: dict, width: int, height: int) -> Image.Image:
    """Bacon's 1944 triptych under glass, the quote as wall text beneath it.

    ``time_str`` is unused by design: a painting carries no clock.
    """
    del time_str
    image = Image.new("RGB", (800, 480), color=SPECTRA6["black"])
    _furies_paint_triptych(image)
    _furies_paint_glass(image)
    _furies_paint_frames(image)
    _furies_paint_quote(image, quote_row)
    _furies_paint_byline(image, quote_row)
    image = snap_image_to_palette(image, SPECTRA6_PALETTE)
    if (width, height) != (800, 480):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    return image
